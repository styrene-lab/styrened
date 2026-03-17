"""Auto-reply handler for headless daemon mode.

This module provides automatic responses to LXMF messages when running
in headless mode. Two modes are supported:

- TEMPLATE: Static template with {hostname}, {uptime}, etc. (original behavior)
- CHATBOT: LLM-backed conversational responses via any OpenAI-compatible endpoint

The handler includes cooldown logic to prevent spam loops with other
auto-reply systems, and bot-to-bot loop prevention for chatbot mode.

Memory optimization: Uses raw bytes for identity keys and limits the
cooldown cache size to prevent unbounded growth from mesh scanning.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from collections.abc import Callable
from importlib.metadata import version as get_version
from typing import TYPE_CHECKING, Any

from styrened.models.config import AutoReplyMode

if TYPE_CHECKING:
    from styrened.models.config import ChatConfig

try:
    import LXMF
    import RNS

    LXMF_AVAILABLE = True
except ImportError:
    LXMF_AVAILABLE = False

logger = logging.getLogger(__name__)

# Maximum number of sender cooldowns to track (LRU eviction beyond this)
MAX_COOLDOWN_ENTRIES = 256


def _call_chat_completions(
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    api_key: str = "",
    max_tokens: int = 256,
    temperature: float = 0.7,
) -> str:
    """Call an OpenAI-compatible chat completions endpoint.

    Uses stdlib urllib to avoid adding dependencies. Designed to be called
    via asyncio.to_thread() for non-blocking operation.

    Args:
        endpoint: Base URL (e.g., "http://localhost:11434/v1").
        model: Model name for the completion request.
        messages: Chat messages in OpenAI format [{role, content}, ...].
        api_key: Optional API key for Bearer authentication.
        max_tokens: Maximum tokens in the response.
        temperature: Sampling temperature.

    Returns:
        The assistant's response content, or empty string on error.
    """
    url = f"{endpoint.rstrip('/')}/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            return ""
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        logger.error(f"Chat completions request failed: {e}")
        return ""
    except (TimeoutError, OSError) as e:
        logger.error(f"Chat completions request timed out: {e}")
        return ""
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse chat completions response: {e}")
        return ""


class AutoReplyHandler:
    """Handles automatic replies to incoming LXMF messages.

    This handler is designed for headless daemon mode where no operator
    is available to respond. Supports two modes:

    - TEMPLATE: Sends a configurable static message with placeholders
    - CHATBOT: Generates conversational responses via an LLM endpoint

    Memory-optimized: Uses bytes keys and LRU eviction to cap memory usage.
    """

    __slots__ = (
        "_broadcast_callback",
        "_config_accessor",
        "_conversation_service",
        "_event_loop",
        "_identity",
        "_last_reply",
        "_router",
        "_start_time",
        "skip_reply_on_no_path",
    )

    def __init__(
        self,
        config: ChatConfig | None = None,
        identity: Any = None,  # RNS.Identity
        router: Any = None,  # LXMF.LXMRouter
        start_time: float | None = None,
        skip_reply_on_no_path: bool = True,
        *,
        config_accessor: Callable[[], ChatConfig] | None = None,
        conversation_service: Any = None,
        broadcast_callback: Callable[..., None] | None = None,
        event_loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """Initialize the auto-reply handler.

        Args:
            config: Chat configuration (legacy, creates a static accessor).
            identity: RNS identity for this node.
            router: LXMF router for sending messages.
            start_time: Daemon start time for uptime calculation.
            skip_reply_on_no_path: If True, skip auto-reply when no path
                to sender exists. If False, attempt sending anyway.
            config_accessor: Callable returning current ChatConfig.
                Preferred over config for hot-reload support.
            conversation_service: ConversationService for chat history
                and message persistence (chatbot mode).
            broadcast_callback: Callable to broadcast chat events to IPC
                clients (chatbot mode).
            event_loop: The daemon's asyncio event loop for scheduling
                async chatbot operations from sync callbacks.
        """
        if config_accessor is not None:
            self._config_accessor = config_accessor
        elif config is not None:
            _static = config
            self._config_accessor = lambda: _static
        else:
            raise TypeError("Either config or config_accessor must be provided")
        self._identity = identity
        self._router = router
        self._start_time = start_time or time.time()
        self.skip_reply_on_no_path = skip_reply_on_no_path
        self._conversation_service = conversation_service
        self._broadcast_callback = broadcast_callback
        self._event_loop = event_loop

        # Track last reply time per sender (bytes key for memory efficiency)
        # OrderedDict provides LRU semantics via move_to_end()
        self._last_reply: OrderedDict[bytes, float] = OrderedDict()

    @property
    def config(self) -> ChatConfig:
        """Return current chat config via accessor for hot-reload support."""
        return self._config_accessor()

    def handle_message(self, message: LXMF.LXMessage) -> None:
        """Handle an incoming LXMF message.

        This is registered as a callback with the LXMF router. It checks
        the auto_reply_mode and dispatches to the appropriate handler.

        Only replies to chat messages - skips RPC, read receipts, and other
        non-chat protocols to avoid unnecessary inter-daemon traffic.

        Args:
            message: Incoming LXMF message.
        """
        mode = self.config.auto_reply_mode
        if mode == AutoReplyMode.DISABLED:
            return

        if not LXMF_AVAILABLE:
            return

        try:
            # Check if this is a chat message (or plain text from Sideband/NomadNet)
            # Skip non-chat protocols to prevent auto-reply loops with other daemons
            fields = message.fields or {}
            protocol = fields.get("protocol", "")

            # Skip explicit non-chat protocols
            if protocol and protocol != "chat":
                logger.debug(f"Skipping auto-reply for non-chat protocol: {protocol}")
                return

            # Skip StyreneProtocol messages (binary RPC, FIELD_CUSTOM_TYPE = 0xFB)
            if fields.get(0xFB) or fields.get("custom_type"):
                logger.debug("Skipping auto-reply for Styrene RPC message")
                return

            # Bot-to-bot loop prevention: skip messages marked as bot-generated
            if fields.get("bot"):
                logger.debug("Skipping auto-reply for bot-generated message")
                return

            # Keep as bytes for memory efficiency
            source_hash_bytes: bytes = message.source_hash

            # Cooldown check: template mode uses the configured cooldown to
            # prevent spamming the same static message. Chatbot mode skips
            # the cooldown — every message deserves a conversational reply,
            # and bot-to-bot loop prevention is handled by the "bot" field.
            if mode == AutoReplyMode.TEMPLATE and not self._check_cooldown(
                source_hash_bytes
            ):
                try:
                    from styrened.web.metrics import auto_replies_total

                    auto_replies_total.labels(result="cooldown_skip").inc()
                except ImportError:
                    pass
                return

            # Check if path to sender exists before attempting reply
            if self.skip_reply_on_no_path and not RNS.Transport.has_path(source_hash_bytes):
                logger.warning(
                    f"No path to sender {source_hash_bytes.hex()[:16]}..., skipping auto-reply"
                )
                try:
                    from styrened.web.metrics import auto_replies_total

                    auto_replies_total.labels(result="no_path_skip").inc()
                except ImportError:
                    pass
                return

            # Only log and process if we're actually sending a reply
            if logger.isEnabledFor(logging.INFO):
                content = message.content.decode("utf-8") if message.content else ""
                logger.info(
                    f"Received message from {source_hash_bytes.hex()[:16]}...: {content[:50]}..."
                )

            # Dispatch based on mode
            if mode == AutoReplyMode.TEMPLATE:
                self._send_reply(source_hash_bytes)
            elif mode == AutoReplyMode.CHATBOT:
                self._schedule_chatbot_reply(source_hash_bytes)

        except Exception as e:
            logger.error(f"Error handling message for auto-reply: {e}")

    def _check_cooldown(self, source_hash: bytes) -> bool:
        """Check if cooldown period has passed for this sender.

        Args:
            source_hash: Sender's identity hash (raw bytes).

        Returns:
            True if we can send a reply, False if still in cooldown.
        """
        now = time.time()
        last_reply = self._last_reply.get(source_hash, 0.0)
        return now - last_reply >= self.config.auto_reply_cooldown

    def _send_reply(self, destination_hash: bytes) -> None:
        """Send a template auto-reply message.

        Args:
            destination_hash: Recipient's identity hash (raw bytes).
        """
        try:
            # Recall the sender's identity
            dest_identity = RNS.Identity.recall(destination_hash)

            if dest_identity is None:
                logger.warning(
                    f"Cannot reply to {destination_hash.hex()[:16]}...: identity not known"
                )
                return

            # Format the reply message with placeholders
            reply_content = self._format_message(self.config.auto_reply_message)

            # Create destination for the reply
            dest_destination = RNS.Destination(
                dest_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                LXMF.APP_NAME,
                "delivery",
            )

            # Create our source destination
            source_destination = RNS.Destination(
                self._identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                LXMF.APP_NAME,
                "delivery",
            )

            # Create and send the reply with LXMF fields for ecosystem interoperability
            # FIELD_RENDERER tells clients how to render the message content
            reply = LXMF.LXMessage(
                destination=dest_destination,
                source=source_destination,
                content=reply_content.encode("utf-8"),
                fields={
                    "protocol": "chat",
                    LXMF.FIELD_RENDERER: LXMF.RENDERER_PLAIN,
                },
            )

            self._router.handle_outbound(reply)

            # Update cooldown tracker with LRU eviction
            self._record_reply(destination_hash)

            try:
                from styrened.web.metrics import auto_replies_total

                auto_replies_total.labels(result="sent").inc()
            except ImportError:
                pass

            logger.info(f"Sent auto-reply to {destination_hash.hex()[:16]}...")

        except Exception as e:
            logger.error(f"Failed to send auto-reply: {e}")

    # -------------------------------------------------------------------------
    # Chatbot mode
    # -------------------------------------------------------------------------

    def _schedule_chatbot_reply(self, destination_hash: bytes) -> None:
        """Schedule an async chatbot reply from a sync LXMF callback.

        Uses asyncio.run_coroutine_threadsafe() to bridge from the sync
        LXMF callback context to the daemon's async event loop.

        Args:
            destination_hash: Recipient's identity hash (raw bytes).
        """
        loop = self._event_loop
        if loop is None:
            logger.warning("No event loop available for chatbot reply")
            return

        asyncio.run_coroutine_threadsafe(
            self._async_chatbot_reply(destination_hash), loop
        )

    async def _async_chatbot_reply(self, destination_hash: bytes) -> None:
        """Generate and send an LLM-backed chatbot reply.

        Builds conversation context from history, calls the LLM endpoint
        in a thread, persists the response, broadcasts to IPC, and sends
        via LXMF.

        Args:
            destination_hash: Recipient's identity hash (raw bytes).
        """
        try:
            chatbot_cfg = self.config.chatbot
            peer_hash_hex = destination_hash.hex()

            # Build LLM messages from conversation history
            llm_messages = self._build_llm_messages(peer_hash_hex)

            # Resolve API key (config → env var)
            api_key = chatbot_cfg.api_key or os.environ.get(
                "STYRENED_CHATBOT_API_KEY", ""
            )

            # Call LLM in a thread to avoid blocking the event loop
            response = await asyncio.to_thread(
                _call_chat_completions,
                chatbot_cfg.endpoint,
                chatbot_cfg.model,
                llm_messages,
                api_key=api_key,
                max_tokens=chatbot_cfg.max_tokens,
                temperature=chatbot_cfg.temperature,
            )

            if not response:
                logger.warning(
                    f"Empty LLM response for {peer_hash_hex[:16]}..., skipping reply"
                )
                return

            # Persist the bot's response to conversation service
            msg_id = None
            if self._conversation_service is not None:
                msg_id = self._conversation_service.save_outgoing_message(
                    destination_hash=peer_hash_hex,
                    content=response,
                    fields={"protocol": "chat", "bot": True},
                )

            # Broadcast to IPC clients so TUI shows the response
            if self._broadcast_callback is not None and msg_id is not None:
                self._broadcast_callback(
                    msg_id=msg_id,
                    peer_hash=peer_hash_hex,
                    content=response,
                    timestamp=time.time(),
                    is_outgoing=True,
                    fields={"protocol": "chat", "bot": True},
                )

            # Send via LXMF with bot marker
            self._send_chatbot_lxmf(destination_hash, response)

            # Record cooldown after successful send
            self._record_reply(destination_hash)

            try:
                from styrened.web.metrics import auto_replies_total

                auto_replies_total.labels(result="chatbot_sent").inc()
            except ImportError:
                pass

            logger.info(f"Sent chatbot reply to {peer_hash_hex[:16]}...")

        except Exception as e:
            logger.error(f"Failed to send chatbot reply: {e}")

    def _build_llm_messages(self, peer_hash: str) -> list[dict[str, str]]:
        """Build the LLM messages array from system prompt and conversation history.

        Args:
            peer_hash: LXMF hash of the conversation peer.

        Returns:
            List of message dicts in OpenAI format [{role, content}, ...].
        """
        chatbot_cfg = self.config.chatbot
        system_prompt = self._format_message(chatbot_cfg.system_prompt)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Add conversation history if available
        if self._conversation_service is not None:
            try:
                history = self._conversation_service.get_messages(
                    peer_hash=peer_hash,
                    limit=chatbot_cfg.max_context_messages,
                )
                # get_messages returns oldest-first (chronological order)
                for msg in history:
                    role = "assistant" if msg.is_outgoing else "user"
                    messages.append({"role": role, "content": msg.content})
            except Exception as e:
                logger.warning(f"Failed to load conversation history: {e}")

        return messages

    def _send_chatbot_lxmf(self, destination_hash: bytes, content: str) -> None:
        """Send a chatbot reply via LXMF with bot marker field.

        Args:
            destination_hash: Recipient's identity hash (raw bytes).
            content: Response text to send.
        """
        try:
            dest_identity = RNS.Identity.recall(destination_hash)

            if dest_identity is None:
                logger.warning(
                    f"Cannot reply to {destination_hash.hex()[:16]}...: identity not known"
                )
                return

            dest_destination = RNS.Destination(
                dest_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                LXMF.APP_NAME,
                "delivery",
            )

            source_destination = RNS.Destination(
                self._identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                LXMF.APP_NAME,
                "delivery",
            )

            reply = LXMF.LXMessage(
                destination=dest_destination,
                source=source_destination,
                content=content.encode("utf-8"),
                fields={
                    "protocol": "chat",
                    "bot": True,
                    LXMF.FIELD_RENDERER: LXMF.RENDERER_PLAIN,
                },
            )

            self._router.handle_outbound(reply)

        except Exception as e:
            logger.error(f"Failed to send chatbot LXMF reply: {e}")

    # -------------------------------------------------------------------------
    # Shared utilities
    # -------------------------------------------------------------------------

    def _record_reply(self, source_hash: bytes) -> None:
        """Record a reply timestamp with LRU eviction.

        Args:
            source_hash: Sender's identity hash (raw bytes).
        """
        now = time.time()

        # If key exists, update and move to end (most recent)
        if source_hash in self._last_reply:
            self._last_reply[source_hash] = now
            self._last_reply.move_to_end(source_hash)
        else:
            # New entry - evict oldest if at capacity
            if len(self._last_reply) >= MAX_COOLDOWN_ENTRIES:
                self._last_reply.popitem(last=False)
            self._last_reply[source_hash] = now

    def _format_message(self, template: str) -> str:
        """Format a message template with placeholders.

        Supported placeholders:
            {hostname}: System hostname
            {identity}: Node's identity hash (first 16 chars)
            {uptime}: Human-readable uptime
            {version}: Styrene version

        Args:
            template: Message template with placeholders.

        Returns:
            Formatted message string.
        """
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "unknown"

        try:
            version = get_version("styrened")
        except Exception:
            version = "0.1.0"

        identity = self._identity.hexhash[:16] if self._identity else "unknown"
        uptime = self._format_uptime(time.time() - self._start_time)

        return template.format(
            hostname=hostname,
            identity=identity,
            uptime=uptime,
            version=version,
        )

    def _format_uptime(self, seconds: float) -> str:
        """Format uptime as human-readable string.

        Args:
            seconds: Uptime in seconds.

        Returns:
            Formatted string like "2d 5h 30m" or "45m 12s".
        """
        # Guard against negative values (e.g., NTP sync issues causing future start_time)
        if seconds < 0:
            return "0s"

        days, remainder = divmod(int(seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if not parts:
            parts.append(f"{secs}s")

        return " ".join(parts)

    def cleanup_stale_cooldowns(self, max_age: int = 3600) -> None:
        """Remove stale cooldown entries.

        Note: With LRU eviction capped at MAX_COOLDOWN_ENTRIES, this is
        optional but can reclaim memory from expired entries.

        Args:
            max_age: Maximum age in seconds before removing entry.
        """
        if not self._last_reply:
            return

        now = time.time()
        # Iterate from oldest (front) and stop when we hit non-stale
        while self._last_reply:
            source, last_time = next(iter(self._last_reply.items()))
            if now - last_time > max_age:
                del self._last_reply[source]
            else:
                break  # OrderedDict is sorted by insertion, so rest are newer
