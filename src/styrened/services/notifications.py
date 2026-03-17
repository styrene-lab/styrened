"""Notification service with pluggable backends.

Dispatches notification events (new messages, delivery status, announces)
to registered backends. Supports in-process callbacks for TUI/GUI embedding
and IPC event broadcasting for connected clients.
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NotificationEvent:
    """Notification event dispatched to backends.

    Attributes:
        event_type: Event category ("new_message", "delivery_status", "announce").
        peer_hash: LXMF destination hash of the peer.
        message_id: Database message ID (0 if not applicable).
        content: Message content (may be None).
        timestamp: Event timestamp.
        status: Message status (pending, sent, delivered, failed, received).
        is_outgoing: Whether this is an outgoing message event.
        metadata: Additional event-specific data.
    """

    event_type: str
    peer_hash: str
    message_id: int = 0
    content: str | None = None
    timestamp: float = 0.0
    status: str = ""
    is_outgoing: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationBackend(ABC):
    """Abstract base for notification dispatch backends."""

    @abstractmethod
    async def dispatch(self, event: NotificationEvent) -> bool:
        """Dispatch a notification event.

        Args:
            event: The notification event.

        Returns:
            True if dispatched successfully.
        """

    def should_notify(self, event: NotificationEvent, config: Any) -> bool:
        """Check if this event should generate a notification.

        Override for custom filtering. Default checks enabled state,
        quiet hours, and muted conversations.

        Args:
            event: The notification event.
            config: NotificationsConfig instance.

        Returns:
            True if notification should be dispatched.
        """
        if config is not None and not config.enabled:
            return False

        # Check quiet hours
        if config is not None and config.quiet_hours_start is not None and config.quiet_hours_end is not None:
            current_hour = time.localtime().tm_hour
            start = config.quiet_hours_start
            end = config.quiet_hours_end

            if start <= end:
                # Normal range: e.g., 22-6 means NOT quiet
                # Actually 22-6 wraps. start <= end means e.g. 8-17
                if start <= current_hour < end:
                    return False
            else:
                # Wrap-around: e.g., 22-6
                if current_hour >= start or current_hour < end:
                    return False

        return True


class CallbackBackend(NotificationBackend):
    """In-process callback backend for TUI/GUI embedding.

    Registered callbacks receive NotificationEvent instances directly.
    Errors in callbacks are logged but don't affect other callbacks.
    """

    def __init__(self) -> None:
        self._callbacks: list[Callable[[NotificationEvent], Any]] = []

    def register(self, callback: Callable[[NotificationEvent], Any]) -> None:
        """Register a notification callback."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unregister(self, callback: Callable[[NotificationEvent], Any]) -> None:
        """Unregister a notification callback."""
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    async def dispatch(self, event: NotificationEvent) -> bool:
        """Dispatch event to all registered callbacks."""
        if not self._callbacks:
            return True

        for cb in list(self._callbacks):
            try:
                result = cb(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning(f"Notification callback error: {e}")

        return True


class IPCEventBackend(NotificationBackend):
    """Bridges notifications to IPC event broadcasting.

    Routes notification events to targeted IPC event types (EVENT_MESSAGE,
    EVENT_DEVICE) and always broadcasts to EVENT_ACTIVITY as a unified feed.
    """

    # Map event_type strings to targeted IPC message types
    _EVENT_ROUTING: dict[str, Any] = {}  # Populated at class load time

    def __init__(self, control_server: Any) -> None:
        self._control_server = control_server

    async def dispatch(self, event: NotificationEvent) -> bool:
        """Broadcast event to IPC clients with type-based routing.

        Routes events to both targeted types (EVENT_MESSAGE, EVENT_DEVICE)
        and the unified EVENT_ACTIVITY feed.
        """
        if self._control_server is None:
            return False

        try:
            from styrened.ipc.protocol import IPCMessageType

            # Lazily populate routing table (avoids import-time circular ref)
            if not IPCEventBackend._EVENT_ROUTING:
                IPCEventBackend._EVENT_ROUTING = {
                    "new_message": IPCMessageType.EVENT_MESSAGE,
                    "delivery_status": IPCMessageType.EVENT_MESSAGE,
                    "device_discovered": IPCMessageType.EVENT_DEVICE,
                    "device_updated": IPCMessageType.EVENT_DEVICE,
                }

            payload = {
                "event_type": event.event_type,
                "message_id": event.message_id,
                "peer_hash": event.peer_hash,
                "content": event.content,
                "timestamp": event.timestamp,
                "status": event.status,
                "is_outgoing": event.is_outgoing,
            }
            payload.update(event.metadata)

            # Send to targeted event type if mapped.
            # Only "new_message", "delivery_status", "device_discovered", and
            # "device_updated" have targeted IPC channels (EVENT_MESSAGE,
            # EVENT_DEVICE).  All other event types (announce_sent,
            # rpc_received, config_changed, etc.) are intentionally routed
            # ONLY to the unified EVENT_ACTIVITY feed.  TUI/GUI consumers
            # that need specific event types should subscribe to
            # EVENT_ACTIVITY and filter by event_type string.
            targeted_type = self._EVENT_ROUTING.get(event.event_type)
            if targeted_type is not None:
                await self._control_server.broadcast_event(targeted_type, payload)

            # Always broadcast to unified activity feed
            await self._control_server.broadcast_event(
                IPCMessageType.EVENT_ACTIVITY, payload
            )
            return True
        except Exception as e:
            logger.warning(f"IPC event broadcast failed: {e}")
            return False


class NotificationService:
    """Dispatches notification events to pluggable backends.

    Manages backend registration, muted conversations, and
    configuration-based filtering (quiet hours, enabled state).

    Args:
        config: NotificationsConfig instance for filtering.
    """

    def __init__(self, config: Any = None) -> None:
        self._config = config
        self._backends: list[NotificationBackend] = []
        self._muted_conversations: set[str] = set()

    def add_backend(self, backend: NotificationBackend) -> None:
        """Register a notification backend."""
        if backend not in self._backends:
            self._backends.append(backend)

    def remove_backend(self, backend: NotificationBackend) -> None:
        """Unregister a notification backend."""
        try:
            self._backends.remove(backend)
        except ValueError:
            pass

    async def notify(self, event: NotificationEvent) -> int:
        """Dispatch a notification event to all backends.

        Respects muted conversations and backend-level filtering.

        Args:
            event: The notification event.

        Returns:
            Number of backends that received the event.
        """
        # Check muted conversations
        if event.peer_hash in self._muted_conversations:
            return 0

        dispatched = 0
        for backend in self._backends:
            if not backend.should_notify(event, self._config):
                continue
            try:
                if await backend.dispatch(event):
                    dispatched += 1
            except Exception as e:
                logger.warning(f"Backend dispatch error: {e}")

        return dispatched

    def mute_conversation(self, peer_hash: str) -> None:
        """Mute notifications for a conversation."""
        self._muted_conversations.add(peer_hash)

    def unmute_conversation(self, peer_hash: str) -> None:
        """Unmute notifications for a conversation."""
        self._muted_conversations.discard(peer_hash)
