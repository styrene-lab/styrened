"""Server-Sent Events broadcaster for real-time mesh updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from styrened.models.mesh_device import MeshDevice

logger = logging.getLogger(__name__)

KEEPALIVE_INTERVAL = 30  # seconds


class SSEBroadcaster:
    """Manages SSE client connections and broadcasts mesh events."""

    def __init__(self) -> None:
        self._clients: set[asyncio.Queue[str]] = set()

    async def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._clients.add(queue)
        logger.debug(f"SSE client connected (total: {len(self._clients)})")
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._clients.discard(queue)
        logger.debug(f"SSE client disconnected (total: {len(self._clients)})")

    async def broadcast(self, event_type: str, data: dict) -> None:
        """Send an event to all connected clients."""
        if not self._clients:
            return
        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        dead: list[asyncio.Queue[str]] = []
        for q in self._clients:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._clients.discard(q)

    def _broadcast_sync(self, event_type: str, data: dict) -> None:
        """Broadcast from a sync context (schedules on the event loop)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.broadcast(event_type, data))
            else:
                loop.run_until_complete(self.broadcast(event_type, data))
        except RuntimeError:
            pass  # No event loop available

    def broadcast_message_event(self, event_dict: dict) -> None:
        """Queue a message event for broadcast (called from sync context)."""
        self._broadcast_sync("message-event", event_dict)

    def broadcast_device_event(self, device: MeshDevice) -> None:
        """Queue a device event for broadcast (called from sync context)."""
        data = {
            "id": device.destination_hash,
            "label": device.name,
            "type": device.device_type.value,
            "status": device.status.value,
            "last_seen": device.last_announce,
            "announce_count": device.announce_count,
            "version": device.version,
        }
        self._broadcast_sync("device-updated", data)

    def broadcast_conversation_event(self, peer_hash: str, update: dict) -> None:
        """Broadcast conversation list change (new unread, new message, etc.)."""
        data = {"peer_hash": peer_hash, **update}
        self._broadcast_sync("conversation-updated", data)

    def broadcast_contact_event(self, peer_hash: str, action: str) -> None:
        """Broadcast contact change (set/removed)."""
        data = {"peer_hash": peer_hash, "action": action}
        self._broadcast_sync("contact-updated", data)

    def broadcast_config_event(self) -> None:
        """Broadcast config change notification."""
        self._broadcast_sync("config-updated", {})

    def broadcast_auto_reply_event(self, enabled: bool, message: str) -> None:
        """Broadcast auto-reply state change."""
        data = {"enabled": enabled, "message": message}
        self._broadcast_sync("auto-reply-updated", data)


# Events safe to broadcast in public mode (whitelist — new event types
# are blocked until explicitly added here).
_PUBLIC_EVENTS = frozenset({"device-updated", "config-updated"})


def create_events_router(broadcaster: SSEBroadcaster) -> APIRouter:
    """Create the SSE events router."""
    router = APIRouter()

    @router.get("/events")
    async def events(request: Request) -> StreamingResponse:
        queue = await broadcaster.subscribe()

        def _is_public() -> bool:
            daemon = getattr(request.app.state, "daemon", None)
            return daemon is not None and daemon.config.api.public_mode

        async def stream():
            try:
                last_keepalive = time.monotonic()
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                        # Filter private events in public mode
                        if _is_public():
                            event_type = msg.split("\n", 1)[0].removeprefix("event: ").strip()
                            if event_type not in _PUBLIC_EVENTS:
                                continue
                        yield msg
                    except asyncio.TimeoutError:
                        if time.monotonic() - last_keepalive >= KEEPALIVE_INTERVAL:
                            yield ": keepalive\n\n"
                            last_keepalive = time.monotonic()
            finally:
                broadcaster.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return router
