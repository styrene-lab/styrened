"""Terminal data plane messages for RNS Link transport.

These messages travel directly over RNS Links (not LXMF) for low-latency
bidirectional terminal I/O. They follow patterns established by rnsh.

Message Types:
    - StreamData: Terminal stdin/stdout/stderr chunks
    - WindowSize: Terminal resize events
    - CommandExited: Process termination notification
    - Noop: Keep-alive for Link health

Wire Format:
    Messages are serialized with msgpack and sent via RNS Channel API.
    Each message type is registered with RNS.Channel.register_message_type().

    For backward compatibility with v1.0 raw-packet mode, serialize_message()
    and deserialize_message() provide the [type:1][packed_data:N] wire format.

Usage:
    from styrened.terminal.messages import register_message_types, StreamData

    # Register with RNS Channel
    register_message_types(channel)

    # Send stream data
    msg = StreamData(stream=StreamData.STDOUT, data=b"Hello, world!")
    channel.send(msg)
"""

from enum import IntEnum
from typing import TYPE_CHECKING, Any, cast

import msgpack
from RNS.Channel import MessageBase

if TYPE_CHECKING:
    import RNS


class TerminalMessageType(IntEnum):
    """Message types for terminal data plane (RNS Link)."""

    NOOP = 0  # Keep-alive
    STREAM_DATA = 1  # stdin/stdout/stderr data
    WINDOW_SIZE = 2  # Terminal dimensions
    COMMAND_EXITED = 3  # Process terminated
    VERSION_INFO = 4  # Protocol version handshake
    ERROR = 5  # Error message


# Legacy alias for backward compatibility
TerminalMessage = MessageBase


class Noop(MessageBase):
    """Keep-alive message for Link health monitoring."""

    MSGTYPE = TerminalMessageType.NOOP

    def __init__(self) -> None:
        pass

    def pack(self) -> bytes:
        return cast(bytes, msgpack.packb({}))

    def unpack(self, raw: bytes) -> None:  # type: ignore[override]
        # Nothing to unpack for keep-alive
        pass


class StreamData(MessageBase):
    """Terminal I/O data (stdin/stdout/stderr).

    Attributes:
        stream: Stream identifier (STDIN=0, STDOUT=1, STDERR=2)
        data: Raw bytes to transmit
        eof: True if stream has ended
    """

    MSGTYPE = TerminalMessageType.STREAM_DATA

    # Stream identifiers
    STDIN = 0
    STDOUT = 1
    STDERR = 2

    def __init__(
        self,
        stream: int = 0,
        data: bytes = b"",
        eof: bool = False,
    ) -> None:
        self.stream = stream
        self.data = data
        self.eof = eof

    def pack(self) -> bytes:
        return cast(
            bytes,
            msgpack.packb(
                {
                    "s": self.stream,
                    "d": self.data,
                    "e": self.eof,
                }
            ),
        )

    def unpack(self, raw: bytes) -> None:  # type: ignore[override]
        d = msgpack.unpackb(raw, raw=True)
        self.stream = d[b"s"] if b"s" in d else d["s"]
        self.data = d[b"d"] if b"d" in d else d["d"]
        self.eof = d.get(b"e", d.get("e", False))

    @property
    def is_stdin(self) -> bool:
        return self.stream == self.STDIN

    @property
    def is_stdout(self) -> bool:
        return self.stream == self.STDOUT

    @property
    def is_stderr(self) -> bool:
        return self.stream == self.STDERR


class WindowSize(MessageBase):
    """Terminal window size change notification.

    Sent when client terminal is resized. Server uses this to
    update PTY dimensions via TIOCSWINSZ ioctl.

    Attributes:
        rows: Terminal height in rows
        cols: Terminal width in columns
        xpixel: Width in pixels (optional, 0 if unknown)
        ypixel: Height in pixels (optional, 0 if unknown)
    """

    MSGTYPE = TerminalMessageType.WINDOW_SIZE

    def __init__(
        self,
        rows: int = 0,
        cols: int = 0,
        xpixel: int = 0,
        ypixel: int = 0,
    ) -> None:
        self.rows = rows
        self.cols = cols
        self.xpixel = xpixel
        self.ypixel = ypixel

    def pack(self) -> bytes:
        return cast(
            bytes,
            msgpack.packb(
                {
                    "r": self.rows,
                    "c": self.cols,
                    "x": self.xpixel,
                    "y": self.ypixel,
                }
            ),
        )

    def unpack(self, raw: bytes) -> None:  # type: ignore[override]
        d = msgpack.unpackb(raw, raw=True)
        self.rows = d[b"r"] if b"r" in d else d["r"]
        self.cols = d[b"c"] if b"c" in d else d["c"]
        self.xpixel = d.get(b"x", d.get("x", 0))
        self.ypixel = d.get(b"y", d.get("y", 0))


class CommandExited(MessageBase):
    """Process termination notification.

    Sent when the shell/command process exits.

    Attributes:
        return_code: Process exit code (0-255 for normal exit)
        signal: Signal that killed the process (None if exited normally)
    """

    MSGTYPE = TerminalMessageType.COMMAND_EXITED

    def __init__(
        self,
        return_code: int = 0,
        signal: int | None = None,
    ) -> None:
        self.return_code = return_code
        self.signal = signal

    def pack(self) -> bytes:
        d: dict[str, Any] = {"rc": self.return_code}
        if self.signal is not None:
            d["sig"] = self.signal
        return cast(bytes, msgpack.packb(d))

    def unpack(self, raw: bytes) -> None:  # type: ignore[override]
        d = msgpack.unpackb(raw, raw=True)
        self.return_code = d[b"rc"] if b"rc" in d else d["rc"]
        self.signal = d.get(b"sig", d.get("sig"))


class VersionInfo(MessageBase):
    """Protocol version handshake.

    Exchanged at Link establishment to ensure compatibility.

    Attributes:
        version: Protocol version (e.g., "1.0")
        software: Software identifier (e.g., "styrened/0.2.0")
    """

    MSGTYPE = TerminalMessageType.VERSION_INFO

    def __init__(
        self,
        version: str = "1.0",
        software: str = "styrened",
    ) -> None:
        self.version = version
        self.software = software

    def pack(self) -> bytes:
        return cast(
            bytes,
            msgpack.packb(
                {
                    "v": self.version,
                    "sw": self.software,
                }
            ),
        )

    def unpack(self, raw: bytes) -> None:  # type: ignore[override]
        d = msgpack.unpackb(raw, raw=True)
        v = d[b"v"] if b"v" in d else d["v"]
        sw = d[b"sw"] if b"sw" in d else d["sw"]
        self.version = v.decode() if isinstance(v, bytes) else v
        self.software = sw.decode() if isinstance(sw, bytes) else sw


class Error(MessageBase):
    """Error message.

    Attributes:
        message: Human-readable error description
        code: Error code (application-specific)
        fatal: If True, session should be terminated
    """

    MSGTYPE = TerminalMessageType.ERROR

    def __init__(
        self,
        message: str = "",
        code: int = 1,
        fatal: bool = False,
    ) -> None:
        self.message = message
        self.code = code
        self.fatal = fatal

    def pack(self) -> bytes:
        return cast(
            bytes,
            msgpack.packb(
                {
                    "m": self.message,
                    "c": self.code,
                    "f": self.fatal,
                }
            ),
        )

    def unpack(self, raw: bytes) -> None:  # type: ignore[override]
        d = msgpack.unpackb(raw, raw=True)
        msg = d[b"m"] if b"m" in d else d["m"]
        if isinstance(msg, bytes):
            msg = msg.decode()
        self.message = msg
        self.code = d.get(b"c", d.get("c", 1))
        self.fatal = d.get(b"f", d.get("f", False))


# Message type registry for RNS Channel integration
MESSAGE_TYPES: dict[TerminalMessageType, type[MessageBase]] = {
    TerminalMessageType.NOOP: Noop,
    TerminalMessageType.STREAM_DATA: StreamData,
    TerminalMessageType.WINDOW_SIZE: WindowSize,
    TerminalMessageType.COMMAND_EXITED: CommandExited,
    TerminalMessageType.VERSION_INFO: VersionInfo,
    TerminalMessageType.ERROR: Error,
}


def register_message_types(channel: "RNS.Channel.Channel") -> None:
    """Register terminal message types with an RNS Channel.

    This must be called before sending/receiving terminal messages
    over a Link's Channel.

    Args:
        channel: RNS Channel to register message types with
    """
    for msg_class in MESSAGE_TYPES.values():
        channel.register_message_type(msg_class)


def serialize_message(msg: MessageBase) -> bytes:
    """Serialize a terminal message for transmission (v1.0 raw packet format).

    Args:
        msg: Message to serialize

    Returns:
        Wire format: [type:1][packed_data:N]
    """
    return bytes([msg.MSGTYPE]) + msg.pack()


def deserialize_message(data: bytes) -> MessageBase:
    """Deserialize a terminal message from wire format (v1.0 raw packet format).

    Args:
        data: Wire format bytes

    Returns:
        Deserialized message

    Raises:
        ValueError: If message type is unknown
    """
    if len(data) < 1:
        raise ValueError("Empty message")

    msg_type = TerminalMessageType(data[0])
    msg_class = MESSAGE_TYPES.get(msg_type)

    if msg_class is None:
        raise ValueError(f"Unknown message type: {msg_type}")

    instance = msg_class()
    instance.unpack(data[1:])
    return instance
