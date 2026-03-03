"""IPC control server for styrened daemon.

Provides a Unix socket server that handles CLI/TUI requests, allowing
external tools to communicate with the running daemon without initializing
their own RNS/LXMF stack.

Usage:
    from styrened.ipc import ControlServer

    # In daemon
    server = ControlServer(daemon, socket_path)
    await server.start()

    # On shutdown
    await server.stop()
"""

import asyncio
import logging
import os
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from styrened.ipc.messages import (
    ErrorResponse,
    IPCRequest,
    IPCResponse,
    create_request,
)
from styrened.ipc.protocol import (
    FrameDecodeError,
    IPCMessageType,
    generate_request_id,
    read_frame,
    write_frame,
)

if TYPE_CHECKING:
    from styrened.daemon import StyreneDaemon
    from styrened.ipc.handlers import IPCHandlers

logger = logging.getLogger(__name__)

# Type alias for handler functions
HandlerFunc = Callable[[IPCRequest], Coroutine[Any, Any, IPCResponse]]


def get_default_socket_path() -> Path:
    """Determine the default socket path.

    Delegates to the central ``paths`` module. Respects ``STYRENED_SOCKET``
    env var, then mode-dependent defaults.

    Returns:
        Path to use for the control socket.
    """
    from styrened import paths

    return paths.control_socket()


class ClientConnection:
    """Represents a connected IPC client.

    Attributes:
        reader: asyncio StreamReader for receiving.
        writer: asyncio StreamWriter for sending.
        subscriptions: Set of subscription IDs for this client.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.subscriptions: set[str] = set()
        self.message_peer_filter: set[str] = set()  # Empty = all peers
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed or self.writer.is_closing()

    async def send_response(
        self,
        request_id: bytes,
        response: IPCResponse,
    ) -> None:
        """Send a response to this client.

        Args:
            request_id: Original request ID for correlation.
            response: Response to send.
        """
        if self.closed:
            return

        msg_type, payload = response.to_wire()
        try:
            await write_frame(self.writer, msg_type, request_id, payload)
        except Exception as e:
            logger.warning(f"Failed to send response: {e}")
            self._closed = True

    async def send_event(
        self,
        event_type: IPCMessageType,
        payload: dict[str, Any],
    ) -> None:
        """Send an event to this client.

        Args:
            event_type: Event message type.
            payload: Event payload.
        """
        if self.closed:
            return

        event_id = generate_request_id()
        try:
            await write_frame(self.writer, event_type, event_id, payload)
        except Exception as e:
            logger.warning(f"Failed to send event: {e}")
            self._closed = True

    async def close(self) -> None:
        """Close the client connection."""
        self._closed = True
        if not self.writer.is_closing():
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass


class ControlServer:
    """Unix socket server for IPC control interface.

    Handles incoming connections from CLI tools and routes requests
    to appropriate handlers.

    Attributes:
        daemon: Reference to the StyreneDaemon instance.
        socket_path: Path to the Unix socket.
        handlers: IPCHandlers instance for request processing.
    """

    def __init__(
        self,
        daemon: "StyreneDaemon",
        socket_path: Path | None = None,
        socket_mode: int = 0o660,
    ) -> None:
        """Initialize the control server.

        Args:
            daemon: StyreneDaemon instance to control.
            socket_path: Path for Unix socket (None = auto-detect).
            socket_mode: File permissions for socket.
        """
        self.daemon = daemon
        self.socket_path = socket_path or get_default_socket_path()
        self.socket_mode = socket_mode

        self._server: asyncio.Server | None = None
        self._clients: set[ClientConnection] = set()
        self._handlers: IPCHandlers | None = None
        self._handler_map: dict[IPCMessageType, HandlerFunc] = {}

    async def start(self) -> None:
        """Start the control server.

        Creates the socket directory if needed, removes any stale socket,
        and begins accepting connections.
        """
        # Import handlers here to avoid circular import
        from styrened.ipc.handlers import IPCHandlers

        self._handlers = IPCHandlers(self.daemon)
        self._register_handlers()

        # Ensure socket directory exists
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove stale socket if it exists
        if self.socket_path.exists():
            logger.warning(f"Removing stale socket: {self.socket_path}")
            self.socket_path.unlink()

        # Start server
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
        )

        # Set socket permissions
        os.chmod(self.socket_path, self.socket_mode)

        logger.info(f"IPC control server listening on {self.socket_path}")

    async def stop(self) -> None:
        """Stop the control server and close all connections."""
        logger.info("Stopping IPC control server")

        # Close all client connections
        for client in list(self._clients):
            await client.close()
        self._clients.clear()

        # Stop accepting new connections
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Remove socket file
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except OSError as e:
                logger.warning(f"Failed to remove socket: {e}")

    def _register_handlers(self) -> None:
        """Register request handlers."""
        if not self._handlers:
            return

        self._handler_map = {
            IPCMessageType.PING: self._handlers.handle_ping,
            IPCMessageType.QUERY_DEVICES: self._handlers.handle_query_devices,
            IPCMessageType.QUERY_IDENTITY: self._handlers.handle_query_identity,
            IPCMessageType.QUERY_STATUS: self._handlers.handle_query_status,
            IPCMessageType.QUERY_CONFIG: self._handlers.handle_query_config,
            IPCMessageType.QUERY_CONVERSATIONS: self._handlers.handle_query_conversations,
            IPCMessageType.QUERY_MESSAGES: self._handlers.handle_query_messages,
            IPCMessageType.QUERY_SEARCH_MESSAGES: self._handlers.handle_query_search_messages,
            IPCMessageType.CMD_SEND: self._handlers.handle_cmd_send,
            IPCMessageType.CMD_EXEC: self._handlers.handle_cmd_exec,
            IPCMessageType.CMD_ANNOUNCE: self._handlers.handle_cmd_announce,
            IPCMessageType.CMD_DEVICE_STATUS: self._handlers.handle_cmd_device_status,
            IPCMessageType.CMD_SEND_CHAT: self._handlers.handle_cmd_send_chat,
            IPCMessageType.CMD_MARK_READ: self._handlers.handle_cmd_mark_read,
            IPCMessageType.CMD_DELETE_CONVERSATION: self._handlers.handle_cmd_delete_conversation,
            IPCMessageType.CMD_DELETE_MESSAGE: self._handlers.handle_cmd_delete_message,
            IPCMessageType.CMD_RETRY_MESSAGE: self._handlers.handle_cmd_retry_message,
            IPCMessageType.QUERY_CONTACTS: self._handlers.handle_query_contacts,
            IPCMessageType.QUERY_RESOLVE_NAME: self._handlers.handle_query_resolve_name,
            IPCMessageType.CMD_SET_CONTACT: self._handlers.handle_cmd_set_contact,
            IPCMessageType.CMD_REMOVE_CONTACT: self._handlers.handle_cmd_remove_contact,
            IPCMessageType.QUERY_AUTO_REPLY: self._handlers.handle_query_auto_reply,
            IPCMessageType.CMD_SET_AUTO_REPLY: self._handlers.handle_cmd_set_auto_reply,
            IPCMessageType.CMD_SYNC_MESSAGES: self._handlers.handle_cmd_sync_messages,
            IPCMessageType.QUERY_PATH_INFO: self._handlers.handle_query_path_info,
            IPCMessageType.QUERY_PAGE: self._handlers.handle_query_page,
            IPCMessageType.QUERY_PAGE_SERVER_STATUS: self._handlers.handle_query_page_server_status,
            IPCMessageType.QUERY_ATTACHMENT: self._handlers.handle_query_attachment,
            IPCMessageType.CMD_PAGE_DISCONNECT: self._handlers.handle_cmd_page_disconnect,
            IPCMessageType.CMD_PAGE_REGENERATE: self._handlers.handle_cmd_page_regenerate,
            IPCMessageType.CMD_REBOOT_DEVICE: self._handlers.handle_cmd_reboot_device,
            IPCMessageType.CMD_SELF_UPDATE: self._handlers.handle_cmd_self_update,
            IPCMessageType.CMD_SET_IDENTITY: self._handlers.handle_cmd_set_identity,
            IPCMessageType.CMD_REMOTE_INBOX: self._handlers.handle_cmd_remote_inbox,
            IPCMessageType.CMD_REMOTE_MESSAGES: self._handlers.handle_cmd_remote_messages,
            IPCMessageType.CMD_PQC_STATUS: self._handlers.handle_cmd_pqc_status,
            # Terminal handlers (input/resize/close dispatched normally;
            # terminal_open is handled inline in _client_loop for client ref)
            IPCMessageType.CMD_TERMINAL_INPUT: self._handlers.handle_cmd_terminal_input,
            IPCMessageType.CMD_TERMINAL_RESIZE: self._handlers.handle_cmd_terminal_resize,
            IPCMessageType.CMD_TERMINAL_CLOSE: self._handlers.handle_cmd_terminal_close,
        }

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a connected client.

        Args:
            reader: asyncio StreamReader for the connection.
            writer: asyncio StreamWriter for the connection.
        """
        client = ClientConnection(reader, writer)
        self._clients.add(client)

        peer = writer.get_extra_info("peername") or "unknown"
        logger.debug(f"IPC client connected: {peer}")

        try:
            await self._client_loop(client)
        except asyncio.IncompleteReadError:
            logger.debug(f"IPC client disconnected: {peer}")
        except Exception as e:
            logger.warning(f"IPC client error: {e}")
        finally:
            await client.close()
            self._clients.discard(client)
            logger.debug(f"IPC client cleanup complete: {peer}")

    async def _client_loop(self, client: ClientConnection) -> None:
        """Process requests from a client until disconnection.

        Subscription requests (SUB_MESSAGES, SUB_DEVICES, UNSUB) are handled
        inline since they need the client reference for per-connection state.

        Args:
            client: ClientConnection to process.
        """
        while not client.closed:
            try:
                msg_type, request_id, payload = await read_frame(client.reader)
            except FrameDecodeError as e:
                logger.warning(f"Frame decode error: {e}")
                error = ErrorResponse.invalid_request(str(e))
                await client.send_response(generate_request_id(), error)
                continue

            # Handle subscription requests inline (need client reference)
            if msg_type == IPCMessageType.SUB_MESSAGES:
                client.subscriptions.add("messages")
                peer_hashes = payload.get("peer_hashes", [])
                client.message_peer_filter = set(peer_hashes) if peer_hashes else set()
                from styrened.ipc.messages import ResultResponse

                response = ResultResponse(data={"subscribed": True})
                await client.send_response(request_id, response)
                continue

            if msg_type == IPCMessageType.SUB_DEVICES:
                client.subscriptions.add("devices")
                from styrened.ipc.messages import ResultResponse

                response = ResultResponse(data={"subscribed": True})
                await client.send_response(request_id, response)
                continue

            if msg_type == IPCMessageType.SUB_ACTIVITY:
                client.subscriptions.add("activity")
                from styrened.ipc.messages import ResultResponse

                response = ResultResponse(data={"subscribed": True})
                await client.send_response(request_id, response)
                continue

            if msg_type == IPCMessageType.UNSUB:
                sub_type = payload.get("subscription_type", "")
                if sub_type:
                    client.subscriptions.discard(sub_type)
                    if sub_type == "messages":
                        client.message_peer_filter.clear()
                else:
                    client.subscriptions.clear()
                    client.message_peer_filter.clear()
                from styrened.ipc.messages import ResultResponse

                response = ResultResponse(data={"unsubscribed": True})
                await client.send_response(request_id, response)
                continue

            # Terminal open needs client reference for event routing
            if msg_type == IPCMessageType.CMD_TERMINAL_OPEN:
                if self._handlers:
                    request = create_request(msg_type, payload)
                    dispatch_response = await self._handlers.handle_cmd_terminal_open(
                        request, client=client
                    )
                else:
                    dispatch_response = ErrorResponse.internal_error("Handlers not initialized")
                await client.send_response(request_id, dispatch_response)
                continue

            # Dispatch to handler
            dispatch_response = await self._dispatch(msg_type, payload)
            await client.send_response(request_id, dispatch_response)

    async def _dispatch(
        self,
        msg_type: IPCMessageType,
        payload: dict[str, Any],
    ) -> IPCResponse:
        """Dispatch a request to the appropriate handler.

        Args:
            msg_type: Request message type.
            payload: Request payload.

        Returns:
            Response from handler or error response.
        """
        handler = self._handler_map.get(msg_type)
        if not handler:
            return ErrorResponse.invalid_request(f"Unknown message type: {msg_type.name}")

        try:
            request = create_request(msg_type, payload)
            return await handler(request)
        except Exception as e:
            logger.exception(f"Handler error for {msg_type.name}: {e}")
            return ErrorResponse.internal_error(str(e))

    async def broadcast_event(
        self,
        event_type: IPCMessageType,
        payload: dict[str, Any],
    ) -> None:
        """Broadcast an event to subscribed clients.

        Filters by subscription type and applies message_peer_filter
        for EVENT_MESSAGE events.

        Args:
            event_type: Event message type.
            payload: Event payload.
        """
        # Remove closed clients
        closed = {c for c in self._clients if c.closed}
        self._clients -= closed

        # Determine subscription key from event type
        if event_type == IPCMessageType.EVENT_MESSAGE:
            sub_key = "messages"
        elif event_type == IPCMessageType.EVENT_DEVICE:
            sub_key = "devices"
        elif event_type == IPCMessageType.EVENT_ACTIVITY:
            sub_key = "activity"
        else:
            sub_key = ""

        # Broadcast to subscribed clients
        for client in self._clients:
            # Skip if not subscribed (unless no subscriptions configured at all,
            # which means legacy behavior — send to all)
            if sub_key and client.subscriptions and sub_key not in client.subscriptions:
                continue

            # Apply peer filter for message events
            if (
                event_type == IPCMessageType.EVENT_MESSAGE
                and client.message_peer_filter
            ):
                peer_hash = payload.get("peer_hash", "")
                if peer_hash not in client.message_peer_filter:
                    continue

            await client.send_event(event_type, payload)

    @property
    def client_count(self) -> int:
        """Number of connected clients."""
        return len(self._clients)

    @property
    def is_running(self) -> bool:
        """Whether the server is running."""
        return self._server is not None and self._server.is_serving()
