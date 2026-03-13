"""IPC bridge — high-level client for daemon communication.

Wraps styrened's ControlClient with auto-reconnection, friendly method
names, and event subscription support.  This is the shared abstraction
used by any consumer that needs to talk to the daemon:

- TUI (via TUIServices protocol)
- Embedded web API
- Planned web bridge (styrene-web-bridge)

Lives in ``styrened.ipc`` (not ``styrened.tui``) so non-TUI consumers
can import it without pulling in Textual.

Usage::

    bridge = IPCBridge()
    await bridge.connect()

    devices = await bridge.get_devices()
    status = await bridge.get_status()

    async for event_type, payload in bridge.iter_events():
        ...

    await bridge.disconnect()
"""
from __future__ import annotations


import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from styrened.ipc.client import ControlClient, IPCConnectionError
from styrened.ipc.protocol import IPCMessageType
from styrened.ipc.server import get_default_socket_path
from styrened.ipc.messages import (
    DaemonStatus,
    DeviceInfo,
    ExecResultInfo,
    IdentityInfo,
    RebootResultInfo,
    RemoteStatusInfo,
    SelfUpdateResultInfo,
)

logger = logging.getLogger(__name__)

# Reconnect backoff parameters
_RECONNECT_DELAY_INITIAL = 1.0
_RECONNECT_DELAY_MAX = 30.0
_RECONNECT_BACKOFF_FACTOR = 2.0
_MAX_RECONNECT_ATTEMPTS = 5


class IPCBridge:
    """Service abstraction layer over the styrened IPC client.

    Provides TUI-friendly method names, automatic reconnection,
    and event subscription management.
    """

    def __init__(
        self,
        socket_path: Path | None = None,
        timeout: float = 30.0,
        auto_reconnect: bool = True,
    ) -> None:
        self._socket_path = socket_path or get_default_socket_path()
        self._timeout = timeout
        self._auto_reconnect = auto_reconnect
        self._client: ControlClient | None = None
        self._connected = False
        self._reconnect_task: asyncio.Task | None = None

    @property
    def connected(self) -> bool:
        return self._connected and self._client is not None and self._client.connected

    async def connect(self) -> bool:
        """Connect to the daemon.

        Returns:
            True if connected successfully.
        """
        if self.connected:
            return True

        try:
            self._client = ControlClient(
                socket_path=self._socket_path,
                timeout=self._timeout,
            )
            await self._client.connect()
            if await self._client.ping(timeout=3.0):
                self._connected = True
                logger.info(f"IPCBridge connected to {self._socket_path}")
                return True
            else:
                await self._client.disconnect()
                self._client = None
                return False
        except IPCConnectionError as e:
            logger.warning(f"IPCBridge connection failed: {e}")
            self._client = None
            return False
        except Exception as e:
            logger.error(f"IPCBridge unexpected error: {e}")
            self._client = None
            return False

    async def disconnect(self) -> None:
        """Disconnect from the daemon."""
        self._connected = False

        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None

        logger.debug("IPCBridge disconnected")

    async def _ensure_connected(self) -> ControlClient:
        """Ensure we have a live connection, attempting reconnect if needed.

        Returns:
            Connected ControlClient.

        Raises:
            IPCConnectionError: If connection cannot be established.
        """
        if self.connected and self._client is not None:
            return self._client

        if self._auto_reconnect:
            if await self._reconnect():
                assert self._client is not None
                return self._client

        raise IPCConnectionError("Not connected to daemon")

    async def _reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff."""
        delay = _RECONNECT_DELAY_INITIAL

        for attempt in range(_MAX_RECONNECT_ATTEMPTS):
            logger.info(f"Reconnect attempt {attempt + 1}/{_MAX_RECONNECT_ATTEMPTS}")

            if await self.connect():
                return True

            if attempt < _MAX_RECONNECT_ATTEMPTS - 1:
                await asyncio.sleep(delay)
                delay = min(delay * _RECONNECT_BACKOFF_FACTOR, _RECONNECT_DELAY_MAX)

        logger.error("Failed to reconnect after all attempts")
        return False

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call a method on the underlying ControlClient with reconnection.

        Args:
            method: Method name on ControlClient.
            *args, **kwargs: Passed to the method.

        Returns:
            Method return value.
        """
        client = await self._ensure_connected()
        try:
            return await getattr(client, method)(*args, **kwargs)
        except IPCConnectionError:
            # Connection lost — try one reconnect
            if self._auto_reconnect:
                self._connected = False
                client = await self._ensure_connected()
                return await getattr(client, method)(*args, **kwargs)
            raise

    # -------------------------------------------------------------------------
    # Device queries (maps: discover_devices → get_devices)
    # -------------------------------------------------------------------------

    async def get_devices(self, styrene_only: bool = False) -> list[DeviceInfo]:
        """Get list of discovered mesh devices.

        Args:
            styrene_only: If True, only return Styrene nodes.
        """
        return await self._call("query_devices", styrene_only=styrene_only)

    # -------------------------------------------------------------------------
    # Status queries (maps: get_rns_service().get_status() → get_status)
    # -------------------------------------------------------------------------

    async def get_status(self) -> DaemonStatus:
        """Get daemon status (uptime, init state, device counts)."""
        return await self._call("query_status")

    # -------------------------------------------------------------------------
    # Identity (maps: get_operator_identity → get_identity)
    # -------------------------------------------------------------------------

    async def get_identity(self) -> IdentityInfo:
        """Get local operator identity hashes."""
        return await self._call("query_identity")

    # -------------------------------------------------------------------------
    # Chat (maps: ChatProtocol.send_message → send_chat)
    # -------------------------------------------------------------------------

    async def send_chat(
        self,
        peer_hash: str,
        content: str,
        title: str | None = None,
        delivery_method: str = "auto",
        reply_to_hash: str | None = None,
        attachment_data_b64: str | None = None,
        attachment_filename: str | None = None,
        attachment_mime: str | None = None,
    ) -> dict[str, Any]:
        """Send a chat message to a peer."""
        return await self._call(
            "send_chat",
            peer_hash=peer_hash,
            content=content,
            title=title,
            delivery_method=delivery_method,
            reply_to_hash=reply_to_hash,
            attachment_data_b64=attachment_data_b64,
            attachment_filename=attachment_filename,
            attachment_mime=attachment_mime,
        )

    async def get_attachment(self, message_id: int) -> dict[str, Any]:
        """Get attachment data for a message."""
        return await self._call("query_attachment", message_id=message_id)

    # -------------------------------------------------------------------------
    # Messages (maps: session.query(Message) → get_messages)
    # -------------------------------------------------------------------------

    async def get_messages(
        self,
        peer_hash: str,
        limit: int = 50,
        before_timestamp: float | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get message history for a conversation."""
        return await self._call(
            "query_messages",
            peer_hash=peer_hash,
            limit=limit,
            before_timestamp=before_timestamp,
            status_filter=status_filter,
        )

    async def get_conversations(self) -> list[dict[str, Any]]:
        """Get list of conversations with unread counts."""
        return await self._call("query_conversations")

    async def mark_read(self, peer_hash: str) -> int:
        """Mark all messages in a conversation as read."""
        return await self._call("mark_read", peer_hash=peer_hash)

    async def search_messages(
        self,
        query: str,
        peer_hash: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search messages by content."""
        return await self._call(
            "search_messages",
            query=query,
            peer_hash=peer_hash,
            limit=limit,
        )

    async def delete_conversation(self, peer_hash: str) -> int:
        """Delete all messages in a conversation."""
        return await self._call("delete_conversation", peer_hash=peer_hash)

    async def delete_message(self, message_id: int) -> bool:
        """Delete a specific message."""
        return await self._call("delete_message", message_id=message_id)

    async def retry_message(self, message_id: int) -> dict[str, Any]:
        """Retry sending a failed message."""
        return await self._call("retry_message", message_id=message_id)

    # -------------------------------------------------------------------------
    # RPC (maps: RPCClient.call_status → query_device_status)
    # -------------------------------------------------------------------------

    async def query_device_status(
        self,
        destination: str,
        timeout: float = 30.0,
    ) -> RemoteStatusInfo:
        """Query status of a remote device."""
        return await self._call(
            "device_status",
            destination=destination,
            timeout=timeout,
        )

    async def send_rpc(
        self,
        destination: str,
        command: str,
        args: list[str] | None = None,
        timeout: float = 60.0,
    ) -> ExecResultInfo:
        """Execute a command on a remote node."""
        return await self._call(
            "exec_command",
            destination=destination,
            command=command,
            args=args,
            timeout=timeout,
        )

    async def reboot_device(
        self,
        destination: str,
        delay: int = 0,
        timeout: float = 10.0,
    ) -> RebootResultInfo:
        """Reboot a remote device."""
        return await self._call(
            "reboot_device",
            destination=destination,
            delay=delay,
            timeout=timeout,
        )

    async def self_update_device(
        self,
        destination: str,
        version: str | None = None,
        timeout: float = 120.0,
    ) -> SelfUpdateResultInfo:
        """Trigger self-update on a remote device."""
        return await self._call(
            "self_update_device",
            destination=destination,
            version=version,
            timeout=timeout,
        )

    # -------------------------------------------------------------------------
    # Mesh operations
    # -------------------------------------------------------------------------

    async def send_message(
        self,
        destination: str,
        message: str,
        protocol: str = "chat",
        retry: bool = False,
        timeout: float = 30.0,
    ) -> bool:
        """Send a message via the mesh."""
        return await self._call(
            "send_message",
            destination=destination,
            message=message,
            protocol=protocol,
            retry=retry,
            timeout=timeout,
        )

    async def announce(self) -> str:
        """Trigger a local announce. Returns destination hash."""
        return await self._call("announce")

    async def get_config(self) -> dict[str, Any]:
        """Query daemon configuration."""
        return await self._call("query_config")

    # -------------------------------------------------------------------------
    # Contacts
    # -------------------------------------------------------------------------

    async def get_contacts(self) -> list[dict[str, Any]]:
        """Get list of contacts."""
        return await self._call("query_contacts")

    async def set_contact(
        self,
        peer_hash: str,
        alias: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Set or update a contact alias."""
        return await self._call(
            "set_contact",
            peer_hash=peer_hash,
            alias=alias,
            notes=notes,
        )

    async def remove_contact(self, peer_hash: str) -> bool:
        """Remove a contact alias."""
        return await self._call("remove_contact", peer_hash=peer_hash)

    async def resolve_name(
        self,
        name: str,
        prefix_match: bool = True,
    ) -> str | None:
        """Resolve a name to a peer hash."""
        return await self._call(
            "resolve_name",
            name=name,
            prefix_match=prefix_match,
        )

    # -------------------------------------------------------------------------
    # Auto-reply (OOO)
    # -------------------------------------------------------------------------

    async def get_auto_reply(self) -> dict[str, Any]:
        """Get auto-reply configuration (enabled, message, cooldown)."""
        return await self._call("query_auto_reply")

    async def set_auto_reply(
        self,
        mode: str = "disabled",
        message: str = "",
        cooldown: int = 300,
    ) -> dict[str, Any]:
        """Set auto-reply configuration."""
        return await self._call(
            "set_auto_reply",
            mode=mode,
            message=message,
            cooldown=cooldown,
        )

    # -------------------------------------------------------------------------
    # Identity
    # -------------------------------------------------------------------------

    async def set_identity(
        self,
        display_name: str = "",
        icon: str = "",
        short_name: str | None = None,
    ) -> dict[str, Any]:
        """Set operator identity appearance fields."""
        return await self._call(
            "set_identity",
            display_name=display_name,
            icon=icon,
            short_name=short_name,
        )

    # -------------------------------------------------------------------------
    # Propagation sync
    # -------------------------------------------------------------------------

    async def sync_messages(self) -> dict[str, Any]:
        """Request message sync from propagation node."""
        return await self._call("sync_messages")

    # -------------------------------------------------------------------------
    # Path info
    # -------------------------------------------------------------------------

    async def get_path_info(self, destination_hash: str) -> dict[str, Any]:
        """Get path info for a destination (hops, interface, etc.)."""
        return await self._call(
            "query_path_info",
            destination_hash=destination_hash,
        )

    # -------------------------------------------------------------------------
    # Page browser
    # -------------------------------------------------------------------------

    async def fetch_page(
        self,
        destination_hash: str,
        path: str = "/page/index.mu",
        form_data: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Fetch a page from a NomadNet node."""
        return await self._call(
            "fetch_page",
            destination_hash=destination_hash,
            path=path,
            form_data=form_data,
            timeout=timeout,
        )

    async def fetch_page_url(
        self,
        url: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Fetch an explicit HTTP(S) or I2P URL."""
        return await self._call(
            "fetch_page_url",
            url=url,
            timeout=timeout,
        )

    async def page_disconnect(self, destination_hash: str) -> bool:
        """Disconnect a cached link to a NomadNet node."""
        return await self._call(
            "page_disconnect",
            destination_hash=destination_hash,
        )

    async def page_save_site(
        self,
        destination_hash: str,
        display_name: str = "",
        refresh_interval: int = 3600,
        max_depth: int = 3,
    ) -> bool:
        """Save a NomadNet node for periodic background crawling."""
        return await self._call(
            "page_save_site",
            destination_hash=destination_hash,
            display_name=display_name,
            refresh_interval=refresh_interval,
            max_depth=max_depth,
        )

    async def page_remove_site(self, destination_hash: str) -> bool:
        """Remove a saved NomadNet site."""
        return await self._call(
            "page_remove_site",
            destination_hash=destination_hash,
        )

    async def page_list_sites(self) -> list[dict[str, Any]]:
        """List all saved NomadNet sites."""
        return await self._call("page_list_sites")

    async def page_crawl_site(
        self, destination_hash: str, max_depth: int = 3
    ) -> int:
        """Manually trigger a full site crawl."""
        return await self._call(
            "page_crawl_site",
            destination_hash=destination_hash,
            max_depth=max_depth,
        )

    async def page_get_cached(
        self, destination_hash: str, path: str = "/page/index.mu"
    ) -> dict[str, Any] | None:
        """Get a cached page."""
        return await self._call(
            "page_get_cached",
            destination_hash=destination_hash,
            path=path,
        )

    async def page_regenerate_index(self) -> bool:
        """Regenerate the default node info page."""
        return await self._call("page_regenerate_index")

    # -------------------------------------------------------------------------
    # Event subscriptions
    # -------------------------------------------------------------------------

    async def subscribe_messages(
        self,
        peer_hashes: list[str] | None = None,
    ) -> bool:
        """Subscribe to real-time message events."""
        return await self._call(
            "subscribe_messages",
            peer_hashes=peer_hashes,
        )

    # ── TUI-specific methods (nodes, core config, hub, unread) ───

    async def get_nodes(self, styrene_only: bool = False) -> list[DeviceInfo]:
        """Get nodes from the persisted node store.

        Unlike get_devices which merges in-memory + persisted data, this
        returns only persisted nodes from the node store.
        """
        return await self._call("get_nodes", styrene_only=styrene_only)

    async def get_core_config(self) -> dict[str, Any]:
        """Get full serialized CoreConfig (round-trippable).

        Unlike get_config which returns a sanitized subset, this returns
        the complete config dict suitable for round-tripping.
        """
        return await self._call("get_core_config")

    async def save_core_config(self, config_dict: dict[str, Any]) -> bool:
        """Save a modified CoreConfig dict to disk."""
        return await self._call("save_core_config", config_dict=config_dict)

    async def get_hub_status(self) -> dict[str, Any]:
        """Get hub connection status dict."""
        return await self._call("get_hub_status")

    async def get_unread_counts(self) -> dict[str, int]:
        """Get per-peer unread message counts."""
        return await self._call("get_unread_counts")

    async def get_adapter_state(self) -> list[dict]:
        """Get current state of all registered adapters."""
        return await self._call("get_adapter_state")

    # ── Direct data link methods ──────────────────────────────────

    async def block_peer(
        self, identity_hash: str, lxmf_dest_hash: str = "", alias: str = ""
    ) -> dict:
        """Block a peer."""
        return await self._call(
            "block_peer",
            identity_hash=identity_hash,
            lxmf_dest_hash=lxmf_dest_hash,
            alias=alias,
        )

    async def unblock_peer(self, identity_hash: str) -> dict:
        """Unblock a peer."""
        return await self._call("unblock_peer", identity_hash=identity_hash)

    async def get_blocked_peers(self) -> dict:
        """List blocked peers."""
        return await self._call("get_blocked_peers")

    async def datalink_establish(self, destination_hash: str) -> dict:
        """Establish a direct data link to a Styrene peer."""
        return await self._call("datalink_establish", destination_hash=destination_hash)

    async def datalink_teardown(self, destination_hash: str) -> dict:
        """Tear down a direct data link."""
        return await self._call("datalink_teardown", destination_hash=destination_hash)

    async def datalink_status(self, destination_hash: str) -> dict:
        """Get direct link status for a peer."""
        return await self._call("datalink_status", destination_hash=destination_hash)

    async def datalink_query(self, destination_hash: str) -> dict:
        """Query peer status over an established direct link."""
        return await self._call("datalink_query", destination_hash=destination_hash)

    async def datalink_speedtest(self, destination_hash: str) -> dict:
        """Run bandwidth test over an established direct link."""
        return await self._call("datalink_speedtest", destination_hash=destination_hash)

    async def datalink_meta(self, destination_hash: str) -> dict | None:
        """Request non-identifiable metadata from peer over direct link.

        Returns styrene_version, profile, capabilities, arch, os_id.
        Returns None if the peer doesn't support /meta (older version) or link failed.
        """
        try:
            result = await self._call("datalink_meta", destination_hash=destination_hash)
            return result.get("meta") if isinstance(result, dict) else None
        except Exception:
            return None

    async def datalink_info(self, destination_hash: str) -> dict | None:
        """Request identifiable metadata from peer over direct link.

        Returns name and operator_label if the remote has info_respond=True.
        Returns None if the peer declined (default) or the request failed.
        A None result is NOT an error — it means the node chose not to identify.
        """
        try:
            result = await self._call("datalink_info", destination_hash=destination_hash)
            return result.get("info") if isinstance(result, dict) else None
        except Exception:
            return None

    # ── Adapter Provisioning ───────────────────────────────────────

    async def provision_adapter(self, adapter_name: str) -> dict[str, Any]:
        """Provision an adapter binary locally via IPC.

        LOCAL context — RBAC is bypassed for IPC calls.

        Args:
            adapter_name: Adapter to provision (e.g., "yggdrasil").

        Returns:
            Dict with success, installed_path, adapter, and optional error.
        """
        result = await self._call("provision_adapter", adapter_name=adapter_name)
        return result if isinstance(result, dict) else {"success": False, "error": "Unexpected response"}

    # ── Subscriptions ──────────────────────────────────────────────

    async def boundary_snapshot(self) -> list[dict[str, Any]]:
        """Return a snapshot of the boundary log ring buffer from the daemon.

        Returns up to 200 records with keys: ts, boundary, severity,
        retryable, stack_name, operation, message.
        Returns empty list if handler is not initialised or on error.
        """
        try:
            result: Any = await self._call("boundary_snapshot")
            if isinstance(result, dict):
                records = result.get("records", [])
                return list(records) if isinstance(records, list) else []
            return []
        except Exception:
            return []

    async def subscribe_devices(self) -> bool:
        """Subscribe to real-time device events."""
        return await self._call("subscribe_devices")

    async def subscribe_activity(self) -> bool:
        """Subscribe to unified activity events for dashboard feed."""
        return await self._call("subscribe_activity")

    async def unsubscribe(self, subscription_type: str = "") -> bool:
        """Unsubscribe from events."""
        return await self._call(
            "unsubscribe",
            subscription_type=subscription_type,
        )

    def on_event(
        self,
        event_type: IPCMessageType,
        callback: Callable,
    ) -> None:
        """Register a callback for a specific event type."""
        if self._client is not None:
            self._client.on_event(event_type, callback)

    def remove_event_handler(
        self,
        event_type: IPCMessageType,
        callback: Callable,
    ) -> None:
        """Unregister an event callback."""
        if self._client is not None:
            self._client.remove_event_handler(event_type, callback)

    async def iter_events(
        self,
        event_type: IPCMessageType | None = None,
    ) -> AsyncIterator[tuple[IPCMessageType, dict]]:
        """Async iterator over incoming events from the daemon."""
        client = await self._ensure_connected()
        async for evt_type, payload in client.iter_events(event_type):
            yield evt_type, payload

    # -------------------------------------------------------------------------
    # Terminal
    # -------------------------------------------------------------------------

    async def terminal_open(
        self,
        destination: str,
        rows: int = 24,
        cols: int = 80,
        term_type: str = "xterm-256color",
        shell: str | None = None,
    ) -> dict[str, Any]:
        """Open a terminal session to a remote node."""
        return await self._call(
            "terminal_open",
            destination=destination,
            rows=rows,
            cols=cols,
            term_type=term_type,
            shell=shell,
        )

    async def terminal_input(self, session_id: str, data: bytes) -> None:
        """Send input data to a terminal session."""
        await self._call("terminal_input", session_id=session_id, data=data)

    async def terminal_resize(self, session_id: str, rows: int, cols: int) -> None:
        """Resize a terminal session."""
        await self._call("terminal_resize", session_id=session_id, rows=rows, cols=cols)

    async def terminal_close(self, session_id: str) -> None:
        """Close a terminal session."""
        await self._call("terminal_close", session_id=session_id)
