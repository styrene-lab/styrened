"""Auto-reply handler for headless daemon mode.

This module provides automatic responses to LXMF messages when running
in headless mode. It responds to messages from NomadNet, MeshChat, or
other LXMF-compatible clients with a configurable friendly message.

The handler includes cooldown logic to prevent spam loops with other
auto-reply systems.

Memory optimization: Uses raw bytes for identity keys and limits the
cooldown cache size to prevent unbounded growth from mesh scanning.
"""

import logging
import socket
import time
from collections import OrderedDict
from importlib.metadata import version as get_version
from typing import TYPE_CHECKING, Any

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


class AutoReplyHandler:
    """Handles automatic replies to incoming LXMF messages.

    This handler is designed for headless daemon mode where no operator
    is available to respond. It sends a configurable auto-reply message
    to any incoming chat/LXMF message, with cooldown to prevent loops.

    Memory-optimized: Uses bytes keys and LRU eviction to cap memory usage.
    """

    __slots__ = (
        "_identity",
        "_last_reply",
        "_router",
        "_start_time",
        "config",
        "skip_reply_on_no_path",
    )

    def __init__(
        self,
        config: "ChatConfig",
        identity: Any,  # RNS.Identity
        router: Any,  # LXMF.LXMRouter
        start_time: float | None = None,
        skip_reply_on_no_path: bool = True,
    ) -> None:
        """Initialize the auto-reply handler.

        Args:
            config: Chat configuration with auto-reply settings.
            identity: RNS identity for this node.
            router: LXMF router for sending messages.
            start_time: Daemon start time for uptime calculation.
            skip_reply_on_no_path: If True, skip auto-reply when no path
                to sender exists. If False, attempt sending anyway.
        """
        self.config = config
        self._identity = identity
        self._router = router
        self._start_time = start_time or time.time()
        self.skip_reply_on_no_path = skip_reply_on_no_path

        # Track last reply time per sender (bytes key for memory efficiency)
        # OrderedDict provides LRU semantics via move_to_end()
        self._last_reply: OrderedDict[bytes, float] = OrderedDict()

    def handle_message(self, message: "LXMF.LXMessage") -> None:
        """Handle an incoming LXMF message.

        This is registered as a callback with the LXMF router. It checks
        if auto-reply is enabled and sends a response if appropriate.

        Only replies to chat messages - skips RPC, read receipts, and other
        non-chat protocols to avoid unnecessary inter-daemon traffic.

        Args:
            message: Incoming LXMF message.
        """
        if not self.config.auto_reply_enabled:
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

            # Keep as bytes for memory efficiency
            source_hash_bytes: bytes = message.source_hash

            # Check cooldown (fast path - no string conversion)
            if not self._check_cooldown(source_hash_bytes):
                return

            # Check if path to sender exists before attempting reply
            if self.skip_reply_on_no_path and not RNS.Transport.has_path(source_hash_bytes):
                logger.warning(
                    f"No path to sender {source_hash_bytes.hex()[:16]}..., skipping auto-reply"
                )
                return

            # Only log and process if we're actually sending a reply
            if logger.isEnabledFor(logging.INFO):
                content = message.content.decode("utf-8") if message.content else ""
                logger.info(
                    f"Received message from {source_hash_bytes.hex()[:16]}...: {content[:50]}..."
                )

            # Send auto-reply
            self._send_reply(source_hash_bytes)

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
        """Send an auto-reply message.

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

            logger.info(f"Sent auto-reply to {destination_hash.hex()[:16]}...")

        except Exception as e:
            logger.error(f"Failed to send auto-reply: {e}")

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
        """Format the auto-reply message with placeholders.

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
            version = get_version("styrene-tui")
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
