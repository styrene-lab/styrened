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

    Checks in order:
    1. $STYRENED_SOCKET environment variable
    2. /run/styrened/control.sock (system daemon)
    3. $XDG_RUNTIME_DIR/styrened/control.sock (user session)
    4. ~/.local/run/styrened/control.sock (fallback)

    Returns:
        Path to use for the control socket.
    """
    # Environment override
    env_socket = os.environ.get("STYRENED_SOCKET")
    if env_socket:
        return Path(env_socket)

    # System daemon path (requires root)
    system_path = Path("/run/styrened/control.sock")
    if system_path.parent.exists() and os.access(system_path.parent, os.W_OK):
        return system_path

    # XDG runtime directory (user session)
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        return Path(xdg_runtime) / "styrened" / "control.sock"

    # Fallback to home directory
    return Path.home() / ".local" / "run" / "styrened" / "control.sock"


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
            IPCMessageType.CMD_SEND: self._handlers.handle_cmd_send,
            IPCMessageType.CMD_EXEC: self._handlers.handle_cmd_exec,
            IPCMessageType.CMD_ANNOUNCE: self._handlers.handle_cmd_announce,
            IPCMessageType.CMD_DEVICE_STATUS: self._handlers.handle_cmd_device_status,
            IPCMessageType.CMD_SEND_CHAT: self._handlers.handle_cmd_send_chat,
            IPCMessageType.CMD_MARK_READ: self._handlers.handle_cmd_mark_read,
            IPCMessageType.CMD_DELETE_CONVERSATION: self._handlers.handle_cmd_delete_conversation,
            IPCMessageType.CMD_DELETE_MESSAGE: self._handlers.handle_cmd_delete_message,
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

            # Dispatch to handler
            response = await self._dispatch(msg_type, payload)
            await client.send_response(request_id, response)

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
        """Broadcast an event to all connected clients.

        Args:
            event_type: Event message type.
            payload: Event payload.
        """
        # Remove closed clients
        closed = {c for c in self._clients if c.closed}
        self._clients -= closed

        # Broadcast to remaining clients
        for client in self._clients:
            await client.send_event(event_type, payload)

    @property
    def client_count(self) -> int:
        """Number of connected clients."""
        return len(self._clients)

    @property
    def is_running(self) -> bool:
        """Whether the server is running."""
        return self._server is not None and self._server.is_serving()
