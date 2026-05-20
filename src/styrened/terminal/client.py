"""Terminal client for TUI/CLI applications.

Connects to remote styrened terminals using LXMF for session control
and RNS Links for data plane I/O.

Architecture:
    1. Client sends TERMINAL_REQUEST via LXMF (Styrene protocol)
    2. Server validates identity and returns TERMINAL_ACCEPT with Link destination
    3. Client establishes RNS Link to server's terminal destination
    4. Bidirectional I/O flows over Link until session ends

Usage:
    from styrened.terminal import TerminalClient

    client = TerminalClient(styrene_protocol)
    session = await client.connect(
        destination="abc123...",
        term_type="xterm-256color",
        rows=24,
        cols=80,
    )
    await session.run_interactive()
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import termios
import tty
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from styrened.models.styrene_wire import (
    StyreneEnvelope,
    StyreneMessageType,
    create_terminal_close,
    create_terminal_request,
    decode_payload,
)
from styrened.protocols.base import LXMFMessage
from styrened.services.rns_limits import request_path_once
from styrened.terminal.messages import (
    CommandExited,
    Error,
    StreamData,
    VersionInfo,
    WindowSize,
    deserialize_message,
    register_message_types,
    serialize_message,
)

if TYPE_CHECKING:
    import RNS

    from styrened.protocols.styrene import StyreneProtocol

logger = logging.getLogger(__name__)

# Connection timeout (waiting for TERMINAL_ACCEPT)
CONNECT_TIMEOUT = 30.0

# Link establishment timeout
LINK_TIMEOUT = 15.0


@dataclass
class TerminalClientSession:
    """Active terminal client session.

    Manages the client side of a terminal connection, handling:
    - RNS Link for data plane I/O
    - Local terminal raw mode management
    - Window resize propagation
    - Signal forwarding

    Attributes:
        session_id: Session identifier from server
        link_destination: RNS destination hash for data Link
        identity_hash: Identity hash for resolving destination identity
        link: Established RNS Link (set after connect)
        remote_version: Server's protocol version info
        exit_code: Process exit code (set when session ends)
    """

    session_id: bytes
    link_destination: str
    styrene_protocol: StyreneProtocol
    destination: str  # Remote destination hash
    identity_hash: str | None = None  # Identity hash for RNS.Identity.recall()

    link: RNS.Link | None = None
    channel: RNS.Channel.Channel | None = None
    remote_version: VersionInfo | None = None
    exit_code: int | None = None

    # Callbacks
    on_output: Callable[[bytes], None] | None = None
    on_exit: Callable[[int], None] | None = None
    on_error: Callable[[str], None] | None = None

    # Internal state
    _connected: asyncio.Event = field(default_factory=asyncio.Event)
    _exited: asyncio.Event = field(default_factory=asyncio.Event)
    _original_termios: list | None = None
    _read_task: asyncio.Task | None = None
    _resize_handler_installed: bool = False
    _event_loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)

    def _thread_safe_event_set(self, event: asyncio.Event) -> None:
        """Set an asyncio.Event in a thread-safe manner.

        RNS callbacks run in RNS's thread, not the asyncio event loop thread.
        This method ensures events are set safely from any thread.
        """
        if self._event_loop is not None and self._event_loop.is_running():
            self._event_loop.call_soon_threadsafe(event.set)
        else:
            # Fallback for edge cases (shutdown, no loop)
            event.set()

    async def connect(self, timeout: float = LINK_TIMEOUT) -> bool:
        """Establish RNS Link to server.

        Args:
            timeout: Link establishment timeout in seconds

        Returns:
            True if connected successfully
        """
        import RNS

        # Capture event loop for thread-safe callbacks
        self._event_loop = asyncio.get_running_loop()

        # Resolve identity - prefer identity_hash with from_identity_hash=True
        try:
            dest_identity = None

            # If we have identity_hash from TERMINAL_ACCEPT, use it with from_identity_hash=True
            if self.identity_hash:
                logger.debug(f"Using identity_hash {self.identity_hash[:16]}... for recall")
                dest_identity = RNS.Identity.recall(
                    bytes.fromhex(self.identity_hash),
                    from_identity_hash=True,
                )

            if not dest_identity:
                # Fall back to path request using link destination hash
                logger.info(f"Requesting path to {self.link_destination[:16]}...")
                request_path_once(
                    bytes.fromhex(self.link_destination), reason="terminal link resolution"
                )

                # Wait for path resolution - this populates the identity cache
                for _ in range(int(timeout * 10)):
                    # After path resolution, try to recall by link_destination (dest hash)
                    dest_identity = RNS.Identity.recall(bytes.fromhex(self.link_destination))
                    if dest_identity:
                        break
                    await asyncio.sleep(0.1)

            if not dest_identity:
                logger.error(
                    f"Could not resolve identity "
                    f"(identity_hash={self.identity_hash[:16] if self.identity_hash else 'none'}...)"
                )
                return False

            # Create destination
            destination = RNS.Destination(
                dest_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                "styrene",
                "terminal",
            )

            # Establish Link
            logger.info(f"Establishing Link to {self.link_destination[:16]}...")
            self.link = RNS.Link(destination)

            # Set callbacks
            self.link.set_link_established_callback(self._on_link_established)
            self.link.set_link_closed_callback(self._on_link_closed)
            self.link.set_packet_callback(self._on_link_packet)

            # Wait for Link to establish
            try:
                await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            except TimeoutError:
                logger.error("Link establishment timeout")
                if self.link:
                    self.link.teardown()
                return False

            return True

        except Exception as e:
            logger.error(f"Link establishment failed: {e}")
            return False

    def _send_packet(self, data: bytes) -> bool:
        """Send data packet over the Link.

        Args:
            data: Data to send

        Returns:
            True if sent successfully
        """
        import RNS

        if not self.link or self.link.status != RNS.Link.ACTIVE:
            return False

        try:
            packet = RNS.Packet(self.link, data)
            packet.send()
            return True
        except Exception as e:
            logger.error(f"Failed to send packet: {e}")
            return False

    def _on_link_established(self, link: RNS.Link) -> None:
        """Handle Link establishment.

        Identifies client to server and sends session_id to associate Link with terminal session.
        """
        import RNS

        from styrened.services.reticulum import get_operator_identity_object

        logger.info(f"Terminal Link established (link.status={link.status})")

        # Identify ourselves to the server so it can verify our identity
        # This is required for the server to call link.get_remote_identity()
        identity = get_operator_identity_object()
        if identity:
            logger.info("Sending identity proof to server...")
            link.identify(identity)
        else:
            logger.warning("No operator identity available for Link identification")

        logger.info(
            f"Sending session_id ({len(self.session_id)} bytes): {self.session_id.hex()[:16]}..."
        )

        # Send session_id to associate Link with terminal session
        # Use the link parameter directly since self.link may not be ready yet
        try:
            packet1 = RNS.Packet(link, self.session_id)
            logger.info(f"Created session_id packet, MTU={link.get_mtu()}")
            receipt1 = packet1.send()
            logger.info(
                f"Session_id packet sent, receipt={receipt1}, status={receipt1.status if receipt1 else 'None'}"
            )
        except Exception as e:
            logger.error(f"Failed to send session_id: {e}", exc_info=True)
            return

        # Send version info (advertise v2.0 Channel support)
        version_msg = VersionInfo(version="2.0", software="styrene-client")
        version_data = serialize_message(version_msg)
        logger.info(
            f"Sending version info ({len(version_data)} bytes): {version_data[:16].hex()}..."
        )
        try:
            packet2 = RNS.Packet(link, version_data)
            receipt2 = packet2.send()
            logger.info(f"Version packet sent, receipt={receipt2}")
        except Exception as e:
            logger.error(f"Failed to send version info: {e}", exc_info=True)

        # Note: _connected is set in _on_link_packet when we receive VersionInfo from server
        # This ensures the version handshake completes before we consider the connection ready
        logger.info("Link established, waiting for server version exchange...")

    def _on_link_closed(self, link: RNS.Link) -> None:
        """Handle Link closure.

        Note: This callback runs in RNS's thread, not the asyncio event loop.
        """
        logger.info("Terminal Link closed")

        if self.exit_code is None:
            self.exit_code = -1

        # Thread-safe event set (callback runs in RNS thread)
        self._thread_safe_event_set(self._exited)

        if self.on_exit and self.exit_code is not None:
            self.on_exit(self.exit_code)

    def _on_link_packet(self, data: bytes, packet: RNS.Packet) -> None:
        """Handle data received from server.

        Note: This callback runs in RNS's thread, not the asyncio event loop.
        """
        try:
            msg = deserialize_message(data)

            if isinstance(msg, StreamData):
                if msg.is_stdout or msg.is_stderr:
                    if self.on_output:
                        self.on_output(msg.data)
                    else:
                        # Default: write to stdout/stderr
                        if msg.is_stdout:
                            sys.stdout.buffer.write(msg.data)
                            sys.stdout.buffer.flush()
                        else:
                            sys.stderr.buffer.write(msg.data)
                            sys.stderr.buffer.flush()

            elif isinstance(msg, CommandExited):
                self.exit_code = msg.return_code
                # Thread-safe event set (callback runs in RNS thread)
                self._thread_safe_event_set(self._exited)
                if self.on_exit:
                    self.on_exit(msg.return_code)

            elif isinstance(msg, VersionInfo):
                self.remote_version = msg
                logger.debug(f"Server version: {msg.version} ({msg.software})")

                # Set up Channel if server supports v2.0
                if msg.version >= "2.0" and self.link:
                    try:
                        channel = self.link.get_channel()
                        register_message_types(channel)
                        channel.add_message_handler(self._on_channel_message)
                        self.channel = channel
                        logger.info(
                            f"Channel established (mdu={channel.mdu}, "
                            f"server_version={msg.version})"
                        )
                    except Exception as e:
                        logger.warning(f"Channel setup failed, using raw packets: {e}")
                        self.channel = None

                # Mark as connected after version exchange (thread-safe)
                self._thread_safe_event_set(self._connected)

            elif isinstance(msg, Error):
                logger.error(f"Server error: {msg.message} (code={msg.code})")
                if self.on_error:
                    self.on_error(msg.message)
                if msg.fatal:
                    # Thread-safe event set (callback runs in RNS thread)
                    self._thread_safe_event_set(self._exited)

        except Exception as e:
            logger.error(f"Failed to handle terminal packet: {e}")

    def _on_channel_message(self, message: RNS.Channel.MessageBase) -> bool:
        """Handle a message received via RNS Channel (v2.0 data plane).

        Note: This callback runs in RNS's thread, not the asyncio event loop.

        Args:
            message: Received Channel message (already unpacked)

        Returns:
            True to indicate the message was consumed
        """
        try:
            if isinstance(message, StreamData):
                if message.is_stdout or message.is_stderr:
                    if self.on_output:
                        self.on_output(message.data)
                    else:
                        if message.is_stdout:
                            sys.stdout.buffer.write(message.data)
                            sys.stdout.buffer.flush()
                        else:
                            sys.stderr.buffer.write(message.data)
                            sys.stderr.buffer.flush()

            elif isinstance(message, CommandExited):
                self.exit_code = message.return_code
                self._thread_safe_event_set(self._exited)
                if self.on_exit:
                    self.on_exit(message.return_code)

            elif isinstance(message, Error):
                logger.error(f"Server error (channel): {message.message} (code={message.code})")
                if self.on_error:
                    self.on_error(message.message)
                if message.fatal:
                    self._thread_safe_event_set(self._exited)

        except Exception as e:
            logger.error(f"Failed to handle channel message: {e}")

        return True

    def send_input(self, data: bytes) -> bool:
        """Send input data to remote terminal.

        Uses Channel when available (v2.0), falls back to raw packets (v1.0).

        Args:
            data: Input bytes (stdin)

        Returns:
            True if sent successfully
        """
        msg = StreamData(stream=StreamData.STDIN, data=data)
        if self.channel:
            if not self.channel.is_ready_to_send():
                return False
            try:
                self.channel.send(msg)
                return True
            except Exception as e:
                logger.error(f"Channel send failed: {e}")
                return False
        return self._send_packet(serialize_message(msg))

    def send_resize(self, rows: int, cols: int, xpixel: int = 0, ypixel: int = 0) -> bool:
        """Send window resize to remote terminal.

        Uses Channel when available (v2.0), falls back to raw packets (v1.0).

        Args:
            rows: New terminal rows
            cols: New terminal columns
            xpixel: Width in pixels (optional)
            ypixel: Height in pixels (optional)

        Returns:
            True if sent successfully
        """
        msg = WindowSize(rows=rows, cols=cols, xpixel=xpixel, ypixel=ypixel)
        if self.channel:
            if not self.channel.is_ready_to_send():
                return False
            try:
                self.channel.send(msg)
                return True
            except Exception as e:
                logger.error(f"Channel send failed: {e}")
                return False
        return self._send_packet(serialize_message(msg))

    async def close(self) -> None:
        """Close the terminal session gracefully."""
        # Send close request via LXMF control plane
        close_env = create_terminal_close(
            session_id=self.session_id,
            request_id=self.session_id,
        )
        await self.styrene_protocol.send(self.destination, close_env)

        # Teardown Link
        if self.link:
            self.link.teardown()

        self._exited.set()

    async def run_interactive(self) -> int:
        """Run interactive terminal session.

        Takes over the local terminal, forwarding I/O to the remote session.
        Returns when the session ends.

        Returns:
            Process exit code
        """
        if not self.link:
            raise RuntimeError("Not connected")

        # Save and set raw terminal mode
        stdin_fd = sys.stdin.fileno()
        try:
            self._original_termios = termios.tcgetattr(stdin_fd)
            tty.setraw(stdin_fd)
        except termios.error:
            # Not a TTY (e.g., piped input)
            self._original_termios = None

        # Install SIGWINCH handler for window resize
        loop = asyncio.get_running_loop()

        def handle_sigwinch(signum, frame):
            try:
                rows, cols = os.get_terminal_size()
                # Schedule resize in event loop
                loop.call_soon_threadsafe(lambda: self.send_resize(rows, cols))
            except OSError:
                pass

        old_sigwinch = signal.signal(signal.SIGWINCH, handle_sigwinch)
        self._resize_handler_installed = True

        # Send initial window size
        try:
            rows, cols = os.get_terminal_size()
            self.send_resize(rows, cols)
        except OSError:
            pass

        # Start stdin read task
        self._read_task = asyncio.create_task(self._stdin_read_loop())

        try:
            # Wait for session to end
            await self._exited.wait()
        finally:
            # Restore terminal
            if self._original_termios:
                termios.tcsetattr(stdin_fd, termios.TCSADRAIN, self._original_termios)

            # Restore signal handler
            if self._resize_handler_installed:
                signal.signal(signal.SIGWINCH, old_sigwinch)

            # Cancel read task
            if self._read_task:
                self._read_task.cancel()
                try:
                    await self._read_task
                except asyncio.CancelledError:
                    pass

        return self.exit_code or 0

    async def _stdin_read_loop(self) -> None:
        """Read from stdin and send to remote terminal.

        When Channel is available (v2.0), applies backpressure via
        is_ready_to_send() before each send.
        """
        loop = asyncio.get_running_loop()
        stdin_fd = sys.stdin.fileno()

        try:
            while self.link and self.link.status == 0x00:
                # Non-blocking read from stdin
                try:
                    data = await loop.run_in_executor(
                        None,
                        lambda: os.read(stdin_fd, 1024),
                    )
                    if data:
                        if self.channel:
                            # Channel mode: backpressure
                            while not self.channel.is_ready_to_send():
                                if not self.link or self.link.status != 0x00:
                                    return
                                await asyncio.sleep(0.01)
                            msg = StreamData(stream=StreamData.STDIN, data=data)
                            self.channel.send(msg)
                        else:
                            self.send_input(data)
                    else:
                        # EOF on stdin
                        break
                except BlockingIOError:
                    await asyncio.sleep(0.01)
                except OSError:
                    break

        except asyncio.CancelledError:
            pass


class TerminalClient:
    """Terminal client for connecting to remote styrened terminals.

    Handles session establishment via LXMF control plane and manages
    the RNS Link data plane connection.

    Usage:
        client = TerminalClient(styrene_protocol)
        session = await client.connect(
            destination="abc123...",
            term_type="xterm-256color",
        )
        exit_code = await session.run_interactive()
    """

    def __init__(self, styrene_protocol: StyreneProtocol):
        """Initialize terminal client.

        Args:
            styrene_protocol: Styrene protocol for LXMF messaging
        """
        self.styrene_protocol = styrene_protocol

        # Pending session requests (request_id -> Future)
        self._pending_requests: dict[bytes, asyncio.Future] = {}

        # Register handlers for terminal responses
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register LXMF handlers for terminal responses."""
        self.styrene_protocol.register_handler(
            StyreneMessageType.TERMINAL_ACCEPT,
            self._handle_terminal_accept,
        )
        self.styrene_protocol.register_handler(
            StyreneMessageType.TERMINAL_REJECT,
            self._handle_terminal_reject,
        )
        self.styrene_protocol.register_handler(
            StyreneMessageType.TERMINAL_CLOSED,
            self._handle_terminal_closed,
        )

    async def _handle_terminal_accept(
        self,
        message: LXMFMessage,
        envelope: StyreneEnvelope,
    ) -> None:
        """Handle TERMINAL_ACCEPT response."""
        _ = message  # Not used, but required by protocol dispatch signature
        request_id = envelope.request_id
        logger.info(
            f"Received TERMINAL_ACCEPT, request_id={request_id.hex()[:16] if request_id else 'none'}"
        )
        if not request_id:
            logger.warning("TERMINAL_ACCEPT missing request_id")
            return

        future = self._pending_requests.get(request_id)
        logger.info(
            f"Looking for pending request {request_id.hex()[:16]}, found={future is not None}"
        )
        if future and not future.done():
            payload = decode_payload(envelope.payload)

            # Validate identity_hash format if provided
            identity_hash = payload.get("identity_hash")
            if identity_hash is not None:
                # Identity hash should be a 64-character hex string (32 bytes)
                if not isinstance(identity_hash, str) or len(identity_hash) != 64:
                    logger.warning(
                        f"Invalid identity_hash format in TERMINAL_ACCEPT: "
                        f"expected 64 hex chars, got {type(identity_hash).__name__} "
                        f"len={len(identity_hash) if isinstance(identity_hash, str) else 'N/A'}"
                    )
                    identity_hash = None
                else:
                    try:
                        bytes.fromhex(identity_hash)  # Validate hex format
                    except ValueError:
                        logger.warning(
                            f"Invalid identity_hash hex format in TERMINAL_ACCEPT: {identity_hash[:16]}..."
                        )
                        identity_hash = None

            logger.info(f"Setting future result for {request_id.hex()[:16]}")
            future.set_result(
                {
                    "accepted": True,
                    "link_destination": payload["link_destination"],
                    "identity_hash": identity_hash,
                    "session_id": bytes.fromhex(payload["session_id"])
                    if isinstance(payload.get("session_id"), str)
                    else payload.get("session_id", request_id),
                }
            )
        else:
            logger.warning(f"No pending request found for {request_id.hex()[:16]}")

    async def _handle_terminal_reject(
        self,
        message: LXMFMessage,
        envelope: StyreneEnvelope,
    ) -> None:
        """Handle TERMINAL_REJECT response."""
        _ = message  # Not used, but required by protocol dispatch signature
        request_id = envelope.request_id
        if not request_id:
            return

        future = self._pending_requests.get(request_id)
        if future and not future.done():
            payload = decode_payload(envelope.payload)
            future.set_result(
                {
                    "accepted": False,
                    "reason": payload.get("reason", "Unknown"),
                    "code": payload.get("code", 1),
                }
            )

    async def _handle_terminal_closed(
        self,
        message: LXMFMessage,
        envelope: StyreneEnvelope,
    ) -> None:
        """Handle TERMINAL_CLOSED notification."""
        _ = message  # Not used, but required by protocol dispatch signature
        # This is informational - the session will handle it via Link closure
        payload = decode_payload(envelope.payload) if envelope.payload else {}
        logger.info(
            f"Terminal session closed: exit_code={payload.get('exit_code')}, "
            f"reason={payload.get('reason')}"
        )

    async def connect(
        self,
        destination: str,
        term_type: str = "xterm-256color",
        rows: int | None = None,
        cols: int | None = None,
        shell: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        timeout: float = CONNECT_TIMEOUT,
    ) -> TerminalClientSession:
        """Connect to a remote terminal.

        Sends TERMINAL_REQUEST via LXMF and establishes RNS Link for I/O.

        Args:
            destination: Remote styrened destination hash
            term_type: Terminal type (TERM env var)
            rows: Terminal rows (auto-detected if None)
            cols: Terminal columns (auto-detected if None)
            shell: Shell to execute (server default if None)
            command: Command to run instead of shell
            args: Command arguments
            timeout: Connection timeout in seconds

        Returns:
            Connected TerminalClientSession

        Raises:
            ConnectionRefusedError: If server rejects the request
            TimeoutError: If connection times out
            RuntimeError: If connection fails
        """
        # Auto-detect terminal size
        if rows is None or cols is None:
            try:
                detected_cols, detected_rows = os.get_terminal_size()
                rows = rows or detected_rows
                cols = cols or detected_cols
            except OSError:
                rows = rows or 24
                cols = cols or 80

        # Create request
        request = create_terminal_request(
            term_type=term_type,
            rows=rows,
            cols=cols,
            shell=shell,
            command=command,
            args=args,
        )
        request_id = request.request_id
        if request_id is None:
            raise ValueError("Terminal request must have a request_id")

        # Create future for response
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future

        try:
            # Send request
            logger.info(f"Sending terminal request to {destination[:16]}...")
            await self.styrene_protocol.send(destination, request)

            # Wait for response
            try:
                result = await asyncio.wait_for(future, timeout=timeout)
            except TimeoutError as e:
                raise TimeoutError(f"Terminal request timed out after {timeout}s") from e

            if not result["accepted"]:
                raise ConnectionRefusedError(
                    f"Terminal request rejected: {result['reason']} (code={result['code']})"
                )

            # Create session with identity_hash for Link establishment
            session = TerminalClientSession(
                session_id=result["session_id"],
                link_destination=result["link_destination"],
                styrene_protocol=self.styrene_protocol,
                destination=destination,
                identity_hash=result.get("identity_hash"),
            )

            # Establish Link
            if not await session.connect(timeout=timeout):
                raise RuntimeError("Failed to establish terminal Link")

            logger.info(f"Terminal session established: {session.session_id.hex()[:16]}...")

            return session

        finally:
            # Clean up pending request
            self._pending_requests.pop(request_id, None)

    async def run_command(
        self,
        destination: str,
        command: str,
        args: list[str] | None = None,
        timeout: float = CONNECT_TIMEOUT,
        capture_output: bool = False,
    ) -> tuple[int, bytes | None]:
        """Run a command on remote terminal and wait for completion.

        Non-interactive version for scripted use.

        Args:
            destination: Remote styrened destination hash
            command: Command to execute
            args: Command arguments
            timeout: Connection timeout in seconds
            capture_output: If True, collect and return stdout/stderr

        Returns:
            Tuple of (exit_code, output_bytes or None)
        """
        output_buffer = bytearray() if capture_output else None

        def capture(data: bytes) -> None:
            if output_buffer is not None:
                output_buffer.extend(data)
            else:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()

        session = await self.connect(
            destination=destination,
            command=command,
            args=args,
            timeout=timeout,
        )

        session.on_output = capture

        # Wait for command to complete
        await session._exited.wait()

        return (
            session.exit_code or 0,
            bytes(output_buffer) if output_buffer else None,
        )
