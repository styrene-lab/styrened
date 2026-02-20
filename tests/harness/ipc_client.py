"""Shared IPC client and polling helpers for mesh tests.

Extracted from tests/mesh/conftest.py so both Docker Compose mesh tests
and Kubernetes mesh tests can use the same MeshControlClient and polling
primitives.

IPC access strategy: Each container runs a Python TCP relay (tcp_relay.py)
that bridges the styrened Unix socket to a TCP port. The test host connects
via TCP using MeshControlClient, a thin ControlClient subclass that uses
asyncio.open_connection instead of open_unix_connection.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from styrened.ipc.client import ControlClient, IPCConnectionError

logger = logging.getLogger(__name__)


class MeshControlClient(ControlClient):
    """ControlClient subclass that connects via TCP instead of Unix socket.

    Used for reaching containerized styrened daemons through the TCP relay.
    The IPC wire protocol is identical over both transport types.
    """

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 30.0,
    ) -> None:
        # Initialize parent with a dummy socket_path (unused for TCP)
        super().__init__(socket_path=Path("/dev/null"), timeout=timeout)
        self._tcp_host = host
        self._tcp_port = port

    async def connect(self) -> None:
        """Connect to the daemon via TCP relay."""
        if self.connected:
            return

        try:
            self._reader, self._writer = await asyncio.open_connection(
                host=self._tcp_host, port=self._tcp_port
            )
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            logger.debug("Connected to daemon via TCP %s:%d", self._tcp_host, self._tcp_port)

        except ConnectionRefusedError as e:
            raise IPCConnectionError(
                f"TCP relay refused at {self._tcp_host}:{self._tcp_port}"
            ) from e
        except Exception as e:
            raise IPCConnectionError(f"Failed to connect via TCP: {e}") from e


async def wait_for_ping(client: ControlClient, timeout: float) -> bool:
    """Connect and ping a daemon, retrying until timeout.

    Args:
        client: ControlClient instance (MeshControlClient or standard).
        timeout: Maximum seconds to wait.

    Returns:
        True if ping succeeded, False on timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            if not client.connected:
                await client.connect()
            if await client.ping(timeout=3.0):
                return True
        except Exception:
            try:
                await client.disconnect()
            except Exception:
                pass
        await asyncio.sleep(1.0)
    return False


def extract_content(raw_content: str | None) -> str | None:
    """Extract user-facing content from a message's raw content field.

    The chat protocol stores content as a JSON envelope:
        {"type": "chat", "protocol": "chat", "content": "actual text"}

    This helper returns the inner content if JSON-wrapped, or the
    raw string if it's plain text.
    """
    if not raw_content:
        return raw_content
    try:
        parsed = json.loads(raw_content)
        if isinstance(parsed, dict) and "content" in parsed:
            return parsed["content"]
    except (json.JSONDecodeError, TypeError):
        pass
    return raw_content


async def poll_for_message(
    client: ControlClient,
    content: str,
    timeout: float = 30,
    poll_interval: float = 1.0,
) -> dict[str, Any] | None:
    """Poll query_conversations + query_messages until content appears.

    Handles JSON-encoded protocol envelopes in the content field.

    Args:
        client: Connected ControlClient instance.
        content: Message content to search for (user-facing text).
        timeout: Maximum seconds to wait.
        poll_interval: Seconds between polls.

    Returns:
        Message dict if found, None if timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            convs = await client.query_conversations()
            for conv in convs:
                messages = await client.query_messages(
                    peer_hash=conv["peer_hash"], limit=20
                )
                for msg in messages:
                    extracted = extract_content(msg.get("content"))
                    if extracted == content:
                        return msg
        except Exception as e:
            logger.debug("poll_for_message error: %s", e)
        await asyncio.sleep(poll_interval)
    return None


async def poll_for_status(
    client: ControlClient,
    peer_hash: str,
    message_id: int,
    target_status: str,
    timeout: float = 30,
    poll_interval: float = 1.0,
) -> bool:
    """Poll message list until target message reaches desired status.

    Args:
        client: Connected ControlClient instance.
        peer_hash: Peer hash for the conversation.
        message_id: Message ID to track.
        target_status: Status string to wait for (e.g., "delivered").
        timeout: Maximum seconds to wait.
        poll_interval: Seconds between polls.

    Returns:
        True if status reached, False on timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            messages = await client.query_messages(peer_hash=peer_hash, limit=50)
            for msg in messages:
                if msg.get("id") == message_id and msg.get("status") == target_status:
                    return True
        except Exception as e:
            logger.debug("poll_for_status error: %s", e)
        await asyncio.sleep(poll_interval)
    return False


async def warmup_path(
    sender: ControlClient,
    receiver: ControlClient,
    receiver_lxmf: str,
    label: str,
    timeout: float = 30,
) -> None:
    """Send a warmup message to pre-establish LXMF delivery paths."""
    warmup_content = f"__warmup_{label}__"
    try:
        await sender.send_chat(peer_hash=receiver_lxmf, content=warmup_content)
        received = await poll_for_message(receiver, content=warmup_content, timeout=timeout)
        if received:
            logger.info("LXMF warmup %s delivered", label)
        else:
            logger.warning("LXMF warmup %s not received within %ds", label, timeout)
    except Exception as e:
        logger.warning("Warmup %s failed: %s", label, e)
