"""High-level chat session abstraction for TUI/GUI integration.

ChatSession wraps ControlClient with subscription management,
typed event iteration, and convenience methods for interactive chat.

Usage:
    async with ChatSession() as chat:
        await chat.send("abcd1234abcd1234", "Hello!")

        async for event in chat.events():
            print(f"{event.peer_hash}: {event.content}")
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from styrened.ipc.client import ControlClient
from styrened.ipc.protocol import IPCMessageType

logger = logging.getLogger(__name__)


@dataclass
class ChatEvent:
    """Parsed chat event from the IPC event stream.

    Attributes:
        event_type: Event category ("new", "status_changed", "delivered", "failed").
        message_id: Database message ID.
        peer_hash: LXMF destination hash of the peer.
        content: Message content (may be None for status events).
        timestamp: Event timestamp.
        status: Message status.
        is_outgoing: Whether this is an outgoing message event.
        delivery_method: How message was delivered.
        signature_valid: LXMF signature validation result.
        transport_encrypted: Whether transport encryption was used.
    """

    event_type: str
    message_id: int
    peer_hash: str
    content: str | None = None
    timestamp: float = 0.0
    status: str = ""
    is_outgoing: bool = False
    delivery_method: str | None = None
    signature_valid: bool | None = None
    transport_encrypted: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ChatEvent":
        """Create ChatEvent from IPC event payload."""
        return cls(
            event_type=payload.get("event_type", ""),
            message_id=payload.get("message_id", 0),
            peer_hash=payload.get("peer_hash", ""),
            content=payload.get("content"),
            timestamp=payload.get("timestamp", 0.0),
            status=payload.get("status", ""),
            is_outgoing=payload.get("is_outgoing", False),
            delivery_method=payload.get("delivery_method"),
            signature_valid=payload.get("signature_valid"),
            transport_encrypted=payload.get("transport_encrypted"),
        )


class ChatSession:
    """Async context manager for interactive chat sessions.

    Manages IPC client lifecycle, message subscriptions, and
    provides convenience methods for common chat operations.

    Args:
        client: Optional pre-existing ControlClient. If None, creates one.
        peer_filter: Optional list of peer hashes to subscribe to.
            Empty or None means all messages.

    Usage:
        # Own client lifecycle
        async with ChatSession() as chat:
            await chat.send("abcd1234", "Hello!")

        # External client
        async with ChatSession(client=existing_client) as chat:
            await chat.send("abcd1234", "Hello!")
    """

    def __init__(
        self,
        client: ControlClient | None = None,
        peer_filter: list[str] | None = None,
    ) -> None:
        self._client = client
        self._owns_client = client is None
        self._peer_filter = peer_filter or []

    @property
    def _active_client(self) -> ControlClient:
        """Return the active client, raising if not connected."""
        assert self._client is not None, "ChatSession not entered"
        return self._client

    async def __aenter__(self) -> "ChatSession":
        """Connect and subscribe to messages."""
        if self._owns_client:
            self._client = ControlClient()
            await self._client.connect()

        # Subscribe to message events
        await self._active_client.subscribe_messages(peer_hashes=self._peer_filter)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Unsubscribe and disconnect if we own the client."""
        if self._client is not None:
            try:
                if self._client.connected:
                    await self._client.unsubscribe(subscription_type="messages")
            except Exception:
                pass

            if self._owns_client:
                await self._client.disconnect()

    async def send(
        self,
        peer_hash: str,
        content: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat message.

        Args:
            peer_hash: LXMF destination hash of the peer.
            content: Message content.
            **kwargs: Additional args passed to send_chat (title, delivery_method, etc).

        Returns:
            Dict with message_id and status.
        """
        return await self._active_client.send_chat(peer_hash, content, **kwargs)

    async def mark_read(self, peer_hash: str) -> int:
        """Mark a conversation as read.

        Args:
            peer_hash: LXMF destination hash of the peer.

        Returns:
            Number of messages marked as read.
        """
        return await self._active_client.mark_read(peer_hash)

    async def events(self) -> AsyncIterator[ChatEvent]:
        """Async iterator over incoming chat events.

        Yields:
            ChatEvent instances parsed from IPC EVENT_MESSAGE frames.
        """
        async for _, payload in self._active_client.iter_events(
            event_type=IPCMessageType.EVENT_MESSAGE
        ):
            yield ChatEvent.from_payload(payload)

    async def conversations(self) -> list[dict[str, Any]]:
        """List conversations.

        Returns:
            List of conversation dicts.
        """
        return await self._active_client.query_conversations()

    async def messages(
        self,
        peer_hash: str,
        limit: int = 50,
        before_timestamp: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get message history for a conversation.

        Args:
            peer_hash: LXMF destination hash of the peer.
            limit: Maximum messages to return.
            before_timestamp: Pagination cursor.

        Returns:
            List of message dicts.
        """
        return await self._active_client.query_messages(
            peer_hash, limit=limit, before_timestamp=before_timestamp
        )

    async def search(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Search messages by content.

        Args:
            query: Search string.
            **kwargs: Additional args (peer_hash, limit).

        Returns:
            List of matching message dicts.
        """
        return await self._active_client.search_messages(query, **kwargs)

    # -------------------------------------------------------------------------
    # Contact methods (delegate to client)
    # -------------------------------------------------------------------------

    async def set_contact(
        self, peer_hash: str, alias: str, notes: str | None = None
    ) -> dict[str, Any]:
        """Set a contact alias."""
        return await self._active_client.set_contact(peer_hash, alias, notes=notes)

    async def remove_contact(self, peer_hash: str) -> bool:
        """Remove a contact alias."""
        return await self._active_client.remove_contact(peer_hash)

    async def contacts(self) -> list[dict[str, Any]]:
        """List all contacts."""
        return await self._active_client.query_contacts()

    async def resolve_name(self, name: str) -> str | None:
        """Resolve a name to a peer hash."""
        return await self._active_client.resolve_name(name)
