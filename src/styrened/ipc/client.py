"""IPC control client for connecting to styrened daemon.

Provides a client interface for CLI tools to communicate with a running
daemon over Unix sockets.

Usage:
    from styrened.ipc import ControlClient

    async with ControlClient() as client:
        devices = await client.query_devices()
        print(f"Found {len(devices)} devices")
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, cast

from styrened.ipc.messages import (
    CmdAnnounceRequest,
    CmdDeviceStatusRequest,
    CmdExecRequest,
    CmdSendRequest,
    DaemonStatus,
    DeviceInfo,
    ErrorResponse,
    ExecResultInfo,
    IdentityInfo,
    IPCRequest,
    PingRequest,
    QueryConfigRequest,
    QueryConversationsRequest,
    QueryDevicesRequest,
    QueryIdentityRequest,
    QueryMessagesRequest,
    QueryStatusRequest,
    RemoteStatusInfo,
)
from styrened.ipc.protocol import (
    FrameDecodeError,
    IPCError,
    IPCMessageType,
    generate_request_id,
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
        """Background task to receive responses."""
        while self._connected and self._reader:
            try:
                msg_type, request_id, payload = await read_frame(self._reader)

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
