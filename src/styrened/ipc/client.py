"""IPC control client for connecting to styrened daemon.

Provides a client interface for CLI tools to communicate with a running
daemon over Unix sockets.

Usage:
    from styrened.ipc import ControlClient

    async with ControlClient() as client:
        devices = await client.query_devices()
        print(f"Found {len(devices)} devices")
"""
from __future__ import annotations


import asyncio
import base64
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, cast

from styrened.ipc.messages import (
    CmdAnnounceRequest,
    CmdDeleteConversationRequest,
    CmdDeleteMessageRequest,
    CmdDeviceStatusRequest,
    CmdExecRequest,
    CmdMarkReadRequest,
    CmdPageDisconnectRequest,
    CmdPageRegenerateRequest,
    CmdRebootDeviceRequest,
    CmdRemoteInboxRequest,
    CmdRemoteMessagesRequest,
    CmdRemoveContactRequest,
    CmdRetryMessageRequest,
    CmdSelfUpdateRequest,
    CmdSendChatRequest,
    CmdSendRequest,
    CmdSetAutoReplyRequest,
    CmdSetContactRequest,
    CmdSetIdentityRequest,
    CmdSyncMessagesRequest,
    CmdTerminalCloseRequest,
    CmdTerminalInputRequest,
    CmdTerminalOpenRequest,
    CmdTerminalResizeRequest,
    DaemonStatus,
    DeviceInfo,
    ErrorResponse,
    ExecResultInfo,
    IdentityInfo,
    IPCRequest,
    PingRequest,
    QueryAttachmentRequest,
    QueryAutoReplyRequest,
    QueryConfigRequest,
    QueryContactsRequest,
    QueryConversationsRequest,
    QueryDevicesRequest,
    QueryIdentityRequest,
    QueryMessagesRequest,
    QueryPageRequest,
    QueryPageServerStatusRequest,
    QueryPathInfoRequest,
    QueryResolveNameRequest,
    QuerySearchMessagesRequest,
    QueryStatusRequest,
    RebootResultInfo,
    RemoteStatusInfo,
    SelfUpdateResultInfo,
    SubActivityRequest,
    SubDevicesRequest,
    SubMessagesRequest,
    UnsubRequest,
)
from styrened.ipc.protocol import (
    FrameDecodeError,
    IPCError,
    IPCMessageType,
    generate_request_id,
    is_event_type,
    read_frame,
    write_frame,
)
from styrened.ipc.server import get_default_socket_path

logger = logging.getLogger(__name__)


class IPCConnectionError(IPCError):
    """Error connecting to daemon socket."""

    pass


class IPCTimeoutError(IPCError):
    """Request timed out."""

    pass


class IPCResponseError(IPCError):
    """Error response from daemon."""

    def __init__(self, code: int, message: str, details: dict | None = None):
        self.code = code
        self.details = details
        super().__init__(message)


class ControlClient:
    """Client for connecting to styrened control socket.

    Can be used as an async context manager for automatic cleanup.

    Usage:
        async with ControlClient() as client:
            if await client.ping():
                devices = await client.query_devices()
    """

    def __init__(
        self,
        socket_path: Path | None = None,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the control client.

        Args:
            socket_path: Path to Unix socket (None = auto-detect).
            timeout: Default timeout for requests in seconds.
        """
        self.socket_path = socket_path or get_default_socket_path()
        self.default_timeout = timeout

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._pending: dict[bytes, asyncio.Future] = {}
        self._receive_task: asyncio.Task | None = None

        # Event dispatch infrastructure
        self._event_callbacks: dict[IPCMessageType, list[Callable]] = {}
        self._event_queue: asyncio.Queue[tuple[IPCMessageType, dict]] = asyncio.Queue()

    async def __aenter__(self) -> "ControlClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    @property
    def connected(self) -> bool:
        """Whether client is connected to daemon."""
        return self._connected and self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Connect to the daemon socket.

        Raises:
            IPCConnectionError: If connection fails.
        """
        if self.connected:
            return

        try:
            self._reader, self._writer = await asyncio.open_unix_connection(
                path=str(self.socket_path)
            )
            self._connected = True
            self._receive_task = asyncio.create_task(self._receive_loop())
            logger.debug(f"Connected to daemon at {self.socket_path}")

        except FileNotFoundError as e:
            raise IPCConnectionError(f"Daemon socket not found: {self.socket_path}") from e
        except ConnectionRefusedError as e:
            raise IPCConnectionError(f"Connection refused: {self.socket_path}") from e
        except PermissionError as e:
            raise IPCConnectionError(f"Permission denied: {self.socket_path}") from e
        except Exception as e:
            raise IPCConnectionError(f"Failed to connect: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect from the daemon."""
        self._connected = False

        # Cancel receive task
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        # Cancel pending requests
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

        # Close connection
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        logger.debug("Disconnected from daemon")

    async def _receive_loop(self) -> None:
        """Background task to receive responses and events."""
        while self._connected and self._reader:
            try:
                msg_type, request_id, payload = await read_frame(self._reader)

                # Check if this is a server-pushed event
                if is_event_type(msg_type):
                    await self._dispatch_event(msg_type, payload)
                    continue

                # Find pending request
                future = self._pending.pop(request_id, None)
                if future and not future.done():
                    future.set_result((msg_type, payload))
                else:
                    logger.warning(f"Received response for unknown request: {request_id.hex()}")

            except asyncio.IncompleteReadError:
                logger.debug("Connection closed by daemon")
                self._connected = False
                break
            except FrameDecodeError as e:
                logger.warning(f"Frame decode error: {e}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Receive error: {e}")
                self._connected = False
                break

    async def _dispatch_event(
        self, event_type: IPCMessageType, payload: dict[str, Any]
    ) -> None:
        """Dispatch a server-pushed event to callbacks and queue."""
        # Queue for iter_events consumers
        try:
            self._event_queue.put_nowait((event_type, payload))
        except asyncio.QueueFull:
            logger.warning("Event queue full, dropping event")

        # Invoke registered callbacks
        callbacks = self._event_callbacks.get(event_type, [])
        for cb in list(callbacks):
            try:
                result = cb(event_type, payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning(f"Event callback error: {e}")

    def on_event(
        self,
        event_type: IPCMessageType,
        callback: Callable,
    ) -> None:
        """Register a callback for a specific event type.

        Callbacks receive (event_type, payload_dict) arguments.

        Args:
            event_type: Event type to listen for.
            callback: Callable to invoke (sync or async).
        """
        if event_type not in self._event_callbacks:
            self._event_callbacks[event_type] = []
        if callback not in self._event_callbacks[event_type]:
            self._event_callbacks[event_type].append(callback)

    def remove_event_handler(
        self,
        event_type: IPCMessageType,
        callback: Callable,
    ) -> None:
        """Unregister an event callback.

        Args:
            event_type: Event type the callback was registered for.
            callback: Callback to remove.
        """
        callbacks = self._event_callbacks.get(event_type, [])
        try:
            callbacks.remove(callback)
        except ValueError:
            pass

    async def iter_events(
        self, event_type: IPCMessageType | None = None
    ) -> AsyncIterator[tuple[IPCMessageType, dict]]:
        """Async iterator over incoming events.

        Args:
            event_type: Optional filter for specific event type.
                None means all events.

        Yields:
            Tuples of (event_type, payload_dict).
        """
        while self._connected:
            try:
                evt_type, payload = await asyncio.wait_for(
                    self._event_queue.get(), timeout=1.0
                )
                if event_type is None or evt_type == event_type:
                    yield evt_type, payload
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _request(
        self,
        request: IPCRequest,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a request and wait for response.

        Args:
            request: Request to send.
            timeout: Timeout in seconds (None = use default).

        Returns:
            Response payload data dict.

        Raises:
            IPCConnectionError: If not connected.
            IPCTimeoutError: If request times out.
            IPCResponseError: If daemon returns an error.
        """
        if not self.connected:
            raise IPCConnectionError("Not connected to daemon")

        msg_type, payload = request.to_wire()
        request_id = generate_request_id()

        # Create future for response
        future: asyncio.Future = asyncio.Future()
        self._pending[request_id] = future

        # Send request
        try:
            await write_frame(self._writer, msg_type, request_id, payload)
        except Exception as e:
            self._pending.pop(request_id, None)
            raise IPCConnectionError(f"Failed to send request: {e}") from e

        # Wait for response
        try:
            response_type, response_payload = await asyncio.wait_for(
                future,
                timeout=timeout or self.default_timeout,
            )
        except TimeoutError as e:
            self._pending.pop(request_id, None)
            raise IPCTimeoutError(
                f"Request timed out after {timeout or self.default_timeout}s"
            ) from e

        # Check for error response
        if response_type == IPCMessageType.ERROR:
            error = ErrorResponse.from_payload(response_payload)
            raise IPCResponseError(error.code, error.message, error.details)

        # Extract data from result
        return cast(dict[str, Any], response_payload.get("data", response_payload))

    # -------------------------------------------------------------------------
    # Query methods
    # -------------------------------------------------------------------------

    async def ping(self, timeout: float = 5.0) -> bool:
        """Check if daemon is responsive.

        Args:
            timeout: Timeout in seconds.

        Returns:
            True if daemon responds, False otherwise.
        """
        try:
            await self._request(PingRequest(), timeout=timeout)
            return True
        except Exception:
            return False

    async def query_devices(self, styrene_only: bool = False) -> list[DeviceInfo]:
        """Query list of discovered devices.

        Args:
            styrene_only: If True, only return Styrene nodes.

        Returns:
            List of DeviceInfo instances.
        """
        data = await self._request(QueryDevicesRequest(styrene_only=styrene_only))
        devices = data.get("devices", [])
        return [DeviceInfo.from_dict(d) for d in devices]

    async def query_identity(self) -> IdentityInfo:
        """Query local identity information.

        Returns:
            IdentityInfo with identity hashes.
        """
        data = await self._request(QueryIdentityRequest())
        return IdentityInfo.from_dict(data)

    async def query_status(self) -> DaemonStatus:
        """Query daemon status.

        Returns:
            DaemonStatus with uptime, counts, etc.
        """
        data = await self._request(QueryStatusRequest())
        return DaemonStatus.from_dict(data)

    async def query_config(self) -> dict[str, Any]:
        """Query current configuration.

        Returns:
            Configuration dict (sanitized).
        """
        data = await self._request(QueryConfigRequest())
        return cast(dict[str, Any], data.get("config", {}))

    async def query_conversations(self) -> list[dict[str, Any]]:
        """Query list of conversations.

        Returns:
            List of conversation dicts with peer_hash, unread_count, etc.
        """
        data = await self._request(QueryConversationsRequest())
        return cast(list[dict[str, Any]], data.get("conversations", []))

    async def query_messages(
        self,
        peer_hash: str,
        limit: int = 50,
        before_timestamp: float | None = None,
        status_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query message history for a conversation.

        Args:
            peer_hash: LXMF destination hash of the peer.
            limit: Maximum number of messages to return.
            before_timestamp: Only return messages before this timestamp.
            status_filter: Filter by message status.

        Returns:
            List of message dicts.
        """
        request = QueryMessagesRequest(
            peer_hash=peer_hash,
            limit=limit,
            before_timestamp=before_timestamp,
            status_filter=status_filter,
        )
        data = await self._request(request)
        return cast(list[dict[str, Any]], data.get("messages", []))

    # -------------------------------------------------------------------------
    # Command methods
    # -------------------------------------------------------------------------

    async def send_message(
        self,
        destination: str,
        message: str,
        protocol: str = "chat",
        retry: bool = False,
        timeout: float = 30.0,
    ) -> bool:
        """Send a message via the mesh.

        Args:
            destination: Destination hash.
            message: Message content.
            protocol: Protocol type ("chat" or "styrene").
            retry: Whether to retry if path unavailable.
            timeout: Timeout in seconds.

        Returns:
            True if message was sent.
        """
        request = CmdSendRequest(
            destination=destination,
            message=message,
            protocol=protocol,
            retry=retry,
            timeout=timeout,
        )
        data = await self._request(request, timeout=timeout + 5)
        return cast(bool, data.get("sent", False))

    async def exec_command(
        self,
        destination: str,
        command: str,
        args: list[str] | None = None,
        timeout: float = 60.0,
    ) -> ExecResultInfo:
        """Execute a command on a remote node.

        Args:
            destination: Destination hash.
            command: Command to execute.
            args: Command arguments.
            timeout: Timeout in seconds.

        Returns:
            ExecResultInfo with exit code and output.
        """
        request = CmdExecRequest(
            destination=destination,
            command=command,
            args=args or [],
            timeout=timeout,
        )
        data = await self._request(request, timeout=timeout + 5)
        return ExecResultInfo.from_dict(data)

    async def announce(self) -> str:
        """Trigger a local announce.

        Returns:
            Destination hash that was announced.
        """
        data = await self._request(CmdAnnounceRequest())
        return cast(str, data.get("destination_hash", ""))

    async def device_status(
        self,
        destination: str,
        timeout: float = 30.0,
    ) -> RemoteStatusInfo:
        """Query status of a specific remote device.

        Args:
            destination: Destination hash.
            timeout: Timeout in seconds.

        Returns:
            RemoteStatusInfo with device status.
        """
        request = CmdDeviceStatusRequest(
            destination=destination,
            timeout=timeout,
        )
        data = await self._request(request, timeout=timeout + 5)
        return RemoteStatusInfo.from_dict(data)

    async def reboot_device(
        self,
        destination: str,
        delay: int = 0,
        timeout: float = 10.0,
    ) -> RebootResultInfo:
        """Reboot a remote device.

        Args:
            destination: Destination hash.
            delay: Seconds to delay reboot (0 = immediate).
            timeout: Timeout in seconds.

        Returns:
            RebootResultInfo with result.
        """
        request = CmdRebootDeviceRequest(
            destination=destination,
            delay=delay,
            timeout=timeout,
        )
        data = await self._request(request, timeout=timeout + 5)
        return RebootResultInfo.from_dict(data)

    async def self_update_device(
        self,
        destination: str,
        version: str | None = None,
        timeout: float = 120.0,
    ) -> SelfUpdateResultInfo:
        """Trigger self-update on a remote device.

        Args:
            destination: Destination hash.
            version: Target version (None = latest from PyPI).
            timeout: Timeout in seconds.

        Returns:
            SelfUpdateResultInfo with result.
        """
        request = CmdSelfUpdateRequest(
            destination=destination,
            version=version,
            timeout=timeout,
        )
        data = await self._request(request, timeout=timeout + 5)
        return SelfUpdateResultInfo.from_dict(data)

    # -------------------------------------------------------------------------
    # Chat methods
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
        """Send a chat message to a peer.

        Args:
            peer_hash: LXMF destination hash of the peer.
            content: Message content.
            title: Optional message title.
            delivery_method: "auto", "direct", or "propagated".
            reply_to_hash: LXMF hash of message being replied to.
            attachment_data_b64: Base64-encoded attachment data.
            attachment_filename: Original filename.
            attachment_mime: MIME type.

        Returns:
            Dict with message_id and status.
        """
        request = CmdSendChatRequest(
            peer_hash=peer_hash,
            content=content,
            title=title,
            delivery_method=delivery_method,
            reply_to_hash=reply_to_hash,
            attachment_data_b64=attachment_data_b64,
            attachment_filename=attachment_filename,
            attachment_mime=attachment_mime,
        )
        return await self._request(request)

    async def query_attachment(self, message_id: int) -> dict[str, Any]:
        """Get attachment data for a message.

        Args:
            message_id: Database ID of the message.

        Returns:
            Dict with data_b64, filename, mime, size.
        """
        request = QueryAttachmentRequest(message_id=message_id)
        return await self._request(request)

    async def mark_read(self, peer_hash: str) -> int:
        """Mark all messages in a conversation as read.

        Args:
            peer_hash: LXMF destination hash of the peer.

        Returns:
            Number of messages marked as read.
        """
        data = await self._request(CmdMarkReadRequest(peer_hash=peer_hash))
        return cast(int, data.get("marked_count", 0))

    async def search_messages(
        self,
        query: str,
        peer_hash: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search messages by content.

        Args:
            query: Search query string.
            peer_hash: Optional peer hash to limit search scope.
            limit: Maximum results to return.

        Returns:
            List of matching message dicts.
        """
        request = QuerySearchMessagesRequest(
            query=query,
            peer_hash=peer_hash,
            limit=limit,
        )
        data = await self._request(request)
        return cast(list[dict[str, Any]], data.get("messages", []))

    async def delete_conversation(self, peer_hash: str) -> int:
        """Delete all messages in a conversation.

        Args:
            peer_hash: LXMF destination hash of the peer.

        Returns:
            Number of messages deleted.
        """
        data = await self._request(
            CmdDeleteConversationRequest(peer_hash=peer_hash)
        )
        return cast(int, data.get("deleted_count", 0))

    async def delete_message(self, message_id: int) -> bool:
        """Delete a specific message.

        Args:
            message_id: Database message ID.

        Returns:
            True if message was deleted.
        """
        data = await self._request(CmdDeleteMessageRequest(message_id=message_id))
        return cast(bool, data.get("deleted", False))

    async def retry_message(self, message_id: int) -> dict[str, Any]:
        """Retry sending a failed message.

        Args:
            message_id: Database message ID of the failed message.

        Returns:
            Dict with retry status.
        """
        return await self._request(CmdRetryMessageRequest(message_id=message_id))

    # -------------------------------------------------------------------------
    # Subscription methods
    # -------------------------------------------------------------------------

    async def subscribe_messages(
        self, peer_hashes: list[str] | None = None
    ) -> bool:
        """Subscribe to message events.

        Args:
            peer_hashes: Optional list of peer hashes to filter.
                Empty list or None means all messages.

        Returns:
            True if subscribed successfully.
        """
        request = SubMessagesRequest(peer_hashes=peer_hashes or [])
        data = await self._request(request)
        return cast(bool, data.get("subscribed", False))

    async def subscribe_devices(self) -> bool:
        """Subscribe to device events.

        Returns:
            True if subscribed successfully.
        """
        data = await self._request(SubDevicesRequest())
        return cast(bool, data.get("subscribed", False))

    async def subscribe_activity(self) -> bool:
        """Subscribe to unified activity events.

        Receives all event types (messages, devices, config changes, etc.)
        as EVENT_ACTIVITY frames for dashboard activity feed.

        Returns:
            True if subscribed successfully.
        """
        data = await self._request(SubActivityRequest())
        return cast(bool, data.get("subscribed", False))

    async def unsubscribe(self, subscription_type: str = "") -> bool:
        """Unsubscribe from events.

        Args:
            subscription_type: Type to unsubscribe from ("messages", "devices").
                Empty string unsubscribes from all.

        Returns:
            True if unsubscribed successfully.
        """
        data = await self._request(UnsubRequest(subscription_type=subscription_type))
        return cast(bool, data.get("unsubscribed", False))

    # -------------------------------------------------------------------------
    # Contact methods
    # -------------------------------------------------------------------------

    async def set_contact(
        self,
        peer_hash: str,
        alias: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Set or update a contact alias.

        Args:
            peer_hash: LXMF destination hash of the peer.
            alias: Display name alias.
            notes: Optional notes.

        Returns:
            Contact info dict.
        """
        request = CmdSetContactRequest(
            peer_hash=peer_hash,
            alias=alias,
            notes=notes,
        )
        return await self._request(request)

    async def remove_contact(self, peer_hash: str) -> bool:
        """Remove a contact alias.

        Args:
            peer_hash: LXMF destination hash of the peer.

        Returns:
            True if contact was removed.
        """
        data = await self._request(CmdRemoveContactRequest(peer_hash=peer_hash))
        return cast(bool, data.get("removed", False))

    async def query_contacts(self) -> list[dict[str, Any]]:
        """Query list of contacts.

        Returns:
            List of contact info dicts.
        """
        data = await self._request(QueryContactsRequest())
        return cast(list[dict[str, Any]], data.get("contacts", []))

    async def resolve_name(
        self,
        name: str,
        prefix_match: bool = True,
    ) -> str | None:
        """Resolve a name to a peer hash.

        Args:
            name: Name to resolve.
            prefix_match: Whether to try prefix matching.

        Returns:
            Peer hash or None if not resolved.
        """
        data = await self._request(
            QueryResolveNameRequest(name=name, prefix_match=prefix_match)
        )
        return cast(str | None, data.get("peer_hash"))

    # -------------------------------------------------------------------------
    # Auto-reply methods
    # -------------------------------------------------------------------------

    async def query_auto_reply(self) -> dict[str, Any]:
        """Query auto-reply configuration.

        Returns:
            Dict with enabled, message, cooldown fields.
        """
        return await self._request(QueryAutoReplyRequest())

    async def set_auto_reply(
        self,
        mode: str = "disabled",
        message: str = "",
        cooldown: int = 300,
    ) -> dict[str, Any]:
        """Set auto-reply configuration.

        Args:
            mode: Auto-reply mode ("disabled", "template", "chatbot").
            message: Auto-reply message text.
            cooldown: Cooldown between replies in seconds.

        Returns:
            Dict with updated mode, message, cooldown fields.
        """
        return await self._request(
            CmdSetAutoReplyRequest(
                mode=mode,
                message=message,
                cooldown=cooldown,
            )
        )

    async def set_identity(
        self,
        display_name: str = "",
        icon: str = "",
        short_name: str | None = None,
    ) -> dict[str, Any]:
        """Set operator identity appearance fields.

        Args:
            display_name: Human-readable name for announces.
            icon: Emoji or short string for identity icon.
            short_name: Optional short identifier (3-20 chars, lowercase).

        Returns:
            Dict with updated display_name, icon, short_name.
        """
        return await self._request(
            CmdSetIdentityRequest(
                display_name=display_name,
                icon=icon,
                short_name=short_name,
            )
        )

    async def sync_messages(self) -> dict[str, Any]:
        """Request message sync from propagation node.

        Returns:
            Dict with 'synced' boolean.
        """
        return await self._request(CmdSyncMessagesRequest())

    async def query_path_info(self, destination_hash: str) -> dict[str, Any]:
        """Query path info for a destination.

        Args:
            destination_hash: Hex-encoded destination hash.

        Returns:
            Dict with path info (hops, interface, etc.) or {'found': False}.
        """
        return await self._request(
            QueryPathInfoRequest(destination_hash=destination_hash)
        )

    # -------------------------------------------------------------------------
    # Page browser methods
    # -------------------------------------------------------------------------

    async def fetch_page(
        self,
        destination_hash: str,
        path: str = "/page/index.mu",
        form_data: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Fetch a page from a NomadNet node."""
        request = QueryPageRequest(
            destination_hash=destination_hash,
            path=path,
            form_data=form_data,
            timeout=timeout,
        )
        return await self._request(request, timeout=timeout + 20)

    async def fetch_page_url(
        self,
        url: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Fetch an explicit HTTP(S) or I2P URL through the page browser."""
        request = QueryPageRequest(
            url=url,
            timeout=timeout,
        )
        return await self._request(request, timeout=timeout + 20)

    async def page_disconnect(self, destination_hash: str) -> bool:
        """Disconnect a cached link to a NomadNet node.

        Args:
            destination_hash: Hex-encoded destination hash.

        Returns:
            True if a link was disconnected.
        """
        data = await self._request(
            CmdPageDisconnectRequest(destination_hash=destination_hash)
        )
        return cast(bool, data.get("disconnected", False))

    async def page_save_site(
        self,
        destination_hash: str,
        display_name: str = "",
        refresh_interval: int = 3600,
        max_depth: int = 3,
    ) -> bool:
        """Save a NomadNet node for periodic background crawling."""
        from styrened.ipc.messages import CmdPageSaveSiteRequest

        data = await self._request(
            CmdPageSaveSiteRequest(
                destination_hash=destination_hash,
                display_name=display_name,
                refresh_interval=refresh_interval,
                max_depth=max_depth,
            )
        )
        return cast(bool, data.get("saved", False))

    async def page_remove_site(self, destination_hash: str) -> bool:
        """Remove a saved NomadNet site."""
        from styrened.ipc.messages import CmdPageRemoveSiteRequest

        data = await self._request(
            CmdPageRemoveSiteRequest(destination_hash=destination_hash)
        )
        return cast(bool, data.get("removed", False))

    async def page_list_sites(self) -> list[dict[str, Any]]:
        """List all saved NomadNet sites."""
        from styrened.ipc.messages import CmdPageListSitesRequest

        data = await self._request(CmdPageListSitesRequest())
        return cast(list, data.get("sites", []))

    async def page_crawl_site(
        self, destination_hash: str, max_depth: int = 3
    ) -> int:
        """Manually trigger a full site crawl."""
        from styrened.ipc.messages import CmdPageCrawlSiteRequest

        data = await self._request(
            CmdPageCrawlSiteRequest(
                destination_hash=destination_hash,
                max_depth=max_depth,
            )
        )
        return cast(int, data.get("pages_cached", 0))

    async def page_get_cached(
        self, destination_hash: str, path: str = "/page/index.mu"
    ) -> dict[str, Any] | None:
        """Get a cached page."""
        from styrened.ipc.messages import CmdPageGetCachedRequest

        data = await self._request(
            CmdPageGetCachedRequest(
                destination_hash=destination_hash,
                path=path,
            )
        )
        if data.get("found"):
            return {
                "content": data.get("content", ""),
                "content_length": data.get("content_length", 0),
                "fetched_at": data.get("fetched_at", 0.0),
            }
        return None

    async def page_regenerate_index(self) -> bool:
        """Regenerate the default node info page.

        Returns:
            True if page was regenerated successfully.
        """
        data = await self._request(CmdPageRegenerateRequest())
        return cast(bool, data.get("regenerated", False))

    async def query_page_server_status(self) -> dict[str, Any]:
        """Query page server status.

        Returns:
            Dict with enabled, started, owns_destination, pages_dir,
            static_pages, and registered_handlers.
        """
        return await self._request(QueryPageServerStatusRequest())

    # -------------------------------------------------------------------------
    # TUI-specific methods (nodes, core config, hub, unread)
    # -------------------------------------------------------------------------

    async def get_nodes(self, styrene_only: bool = False) -> list[DeviceInfo]:
        """Get nodes from the persisted node store.

        Unlike query_devices which merges in-memory discovery with persisted
        data, this returns only persisted nodes from the node store.

        Args:
            styrene_only: If True, only return Styrene nodes.

        Returns:
            List of DeviceInfo instances.
        """
        from styrened.ipc.messages import GetNodesRequest

        data = await self._request(GetNodesRequest(styrene_only=styrene_only))
        nodes = data.get("nodes", [])
        return [DeviceInfo.from_dict(n) for n in nodes]

    async def get_core_config(self) -> dict[str, Any]:
        """Get full serialized CoreConfig (round-trippable).

        Unlike query_config which returns a sanitized subset, this
        returns the complete config dict suitable for modification
        and round-tripping through save_core_config.

        Returns:
            Full config dict.
        """
        from styrened.ipc.messages import GetCoreConfigRequest

        data = await self._request(GetCoreConfigRequest())
        return cast(dict[str, Any], data.get("config", {}))

    async def save_core_config(self, config_dict: dict[str, Any]) -> bool:
        """Save a modified CoreConfig dict to disk.

        Args:
            config_dict: Full serialized config dict.

        Returns:
            True if saved successfully.
        """
        from styrened.ipc.messages import SaveCoreConfigRequest

        data = await self._request(SaveCoreConfigRequest(config_dict=config_dict))
        return cast(bool, data.get("saved", False))

    async def get_hub_status(self) -> dict[str, Any]:
        """Get hub connection status.

        Returns:
            Dict with is_connected, hub_address, status fields.
        """
        from styrened.ipc.messages import GetHubStatusRequest

        return await self._request(GetHubStatusRequest())

    async def get_unread_counts(self) -> dict[str, int]:
        """Get per-peer unread message counts.

        Returns:
            Dict mapping peer_hash to unread count.
        """
        from styrened.ipc.messages import GetUnreadCountsRequest

        data = await self._request(GetUnreadCountsRequest())
        return cast(dict[str, int], data.get("counts", {}))

    # -------------------------------------------------------------------------
    # Direct data link methods
    # -------------------------------------------------------------------------

    async def block_peer(
        self, identity_hash: str, lxmf_dest_hash: str = "", alias: str = ""
    ) -> dict[str, Any]:
        """Block a peer — silently drop all future messages from them."""
        from styrened.ipc.messages import CmdBlockPeerRequest

        return await self._request(
            CmdBlockPeerRequest(
                identity_hash=identity_hash,
                lxmf_dest_hash=lxmf_dest_hash,
                alias=alias,
            )
        )

    async def unblock_peer(self, identity_hash: str) -> dict[str, Any]:
        """Unblock a previously blocked peer."""
        from styrened.ipc.messages import CmdUnblockPeerRequest

        return await self._request(CmdUnblockPeerRequest(identity_hash=identity_hash))

    async def get_blocked_peers(self) -> dict[str, Any]:
        """List all blocked peers."""
        from styrened.ipc.messages import QueryBlockedPeersRequest

        return await self._request(QueryBlockedPeersRequest())

    async def datalink_establish(self, destination_hash: str) -> dict[str, Any]:
        """Establish a direct data link to a Styrene peer."""
        from styrened.ipc.messages import CmdDatalinkEstablishRequest

        return await self._request(
            CmdDatalinkEstablishRequest(destination_hash=destination_hash)
        )

    async def datalink_teardown(self, destination_hash: str) -> dict[str, Any]:
        """Tear down a direct data link."""
        from styrened.ipc.messages import CmdDatalinkTeardownRequest

        return await self._request(
            CmdDatalinkTeardownRequest(destination_hash=destination_hash)
        )

    async def datalink_status(self, destination_hash: str) -> dict[str, Any]:
        """Get direct link status for a peer."""
        from styrened.ipc.messages import CmdDatalinkStatusRequest

        return await self._request(
            CmdDatalinkStatusRequest(destination_hash=destination_hash)
        )

    async def datalink_query(self, destination_hash: str) -> dict[str, Any]:
        """Query peer status over an established direct link."""
        from styrened.ipc.messages import CmdDatalinkQueryRequest

        return await self._request(
            CmdDatalinkQueryRequest(destination_hash=destination_hash)
        )

    async def datalink_speedtest(self, destination_hash: str) -> dict[str, Any]:
        """Run bandwidth test over an established direct link."""
        from styrened.ipc.messages import CmdDatalinkSpeedtestRequest

        return await self._request(
            CmdDatalinkSpeedtestRequest(destination_hash=destination_hash),
            timeout=120.0,  # speedtest can take a while over slow links
        )

    async def datalink_meta(self, destination_hash: str) -> dict[str, Any]:
        """Request non-identifiable metadata from peer over direct link."""
        from styrened.ipc.messages import CmdDatalinkMetaRequest

        return await self._request(
            CmdDatalinkMetaRequest(destination_hash=destination_hash),
        )

    async def datalink_info(self, destination_hash: str) -> dict[str, Any]:
        """Request identifiable metadata from peer over direct link.

        A result with info=None means the remote declined (info_respond=False).
        """
        from styrened.ipc.messages import CmdDatalinkInfoRequest

        return await self._request(
            CmdDatalinkInfoRequest(destination_hash=destination_hash),
        )

    # -------------------------------------------------------------------------
    # Boundary logging
    # -------------------------------------------------------------------------

    async def boundary_snapshot(self) -> dict[str, Any]:
        """Return a snapshot of the boundary log ring buffer."""
        from styrened.ipc.messages import CmdBoundarySnapshotRequest

        return await self._request(CmdBoundarySnapshotRequest())

    # -------------------------------------------------------------------------
    # Remote inbox methods (RPC over LXMF)
    # -------------------------------------------------------------------------

    async def remote_inbox(
        self,
        destination: str,
        limit: int = 50,
        timeout: float = 30.0,
    ) -> list[dict[str, Any]]:
        """Query inbox on a remote node via RPC over LXMF.

        Args:
            destination: Destination hash of remote node.
            limit: Maximum conversations to return.
            timeout: RPC timeout in seconds.

        Returns:
            List of conversation dicts from the remote node.
        """
        request = CmdRemoteInboxRequest(
            destination=destination,
            limit=limit,
            timeout=timeout,
        )
        data = await self._request(request, timeout=timeout + 5)
        return cast(list[dict[str, Any]], data.get("conversations", []))

    async def remote_messages(
        self,
        destination: str,
        peer_hash: str,
        limit: int = 50,
        timeout: float = 30.0,
    ) -> list[dict[str, Any]]:
        """Query messages for a peer on a remote node via RPC over LXMF.

        Args:
            destination: Destination hash of remote node.
            peer_hash: Peer hash to query messages for.
            limit: Maximum messages to return.
            timeout: RPC timeout in seconds.

        Returns:
            List of message dicts from the remote node.
        """
        request = CmdRemoteMessagesRequest(
            destination=destination,
            peer_hash=peer_hash,
            limit=limit,
            timeout=timeout,
        )
        data = await self._request(request, timeout=timeout + 5)
        return cast(list[dict[str, Any]], data.get("messages", []))

    # -------------------------------------------------------------------------
    # Terminal methods
    # -------------------------------------------------------------------------

    async def terminal_open(
        self,
        destination: str,
        rows: int = 24,
        cols: int = 80,
        term_type: str = "xterm-256color",
        shell: str | None = None,
    ) -> dict[str, Any]:
        """Open a terminal session to a remote node.

        Args:
            destination: Destination identity hash.
            rows: Terminal rows.
            cols: Terminal columns.
            term_type: Terminal type string.
            shell: Optional shell path.

        Returns:
            Dict with session_id and connected status.
        """
        request = CmdTerminalOpenRequest(
            destination=destination,
            rows=rows,
            cols=cols,
            term_type=term_type,
            shell=shell,
        )
        return await self._request(request, timeout=45.0)

    async def terminal_input(self, session_id: str, data: bytes) -> None:
        """Send input data to a terminal session.

        Args:
            session_id: Hex-encoded session ID.
            data: Raw input bytes to send.
        """
        request = CmdTerminalInputRequest(
            session_id=session_id,
            data_b64=base64.b64encode(data).decode("ascii"),
        )
        await self._request(request)

    async def terminal_resize(self, session_id: str, rows: int, cols: int) -> None:
        """Resize a terminal session.

        Args:
            session_id: Hex-encoded session ID.
            rows: New row count.
            cols: New column count.
        """
        request = CmdTerminalResizeRequest(
            session_id=session_id,
            rows=rows,
            cols=cols,
        )
        await self._request(request)

    async def terminal_close(self, session_id: str) -> None:
        """Close a terminal session.

        Args:
            session_id: Hex-encoded session ID.
        """
        request = CmdTerminalCloseRequest(session_id=session_id)
        await self._request(request)


async def get_daemon_client() -> ControlClient | None:
    """Try to connect to a running daemon.

    Convenience function for CLI commands. Returns a connected client
    if the daemon is running, or None if not available.

    Returns:
        Connected ControlClient, or None if daemon unavailable.

    Note:
        Caller is responsible for calling disconnect() when done.
    """
    client = ControlClient()
    try:
        await client.connect()
        if await client.ping(timeout=2.0):
            return client
        await client.disconnect()
        return None
    except IPCConnectionError:
        return None
    except Exception as e:
        logger.debug(f"Failed to connect to daemon: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass
        return None
