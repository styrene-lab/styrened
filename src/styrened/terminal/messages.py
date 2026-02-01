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

Usage:
    from styrened.terminal.messages import register_message_types, StreamData

    # Register with RNS Channel
    register_message_types(channel)

    # Send stream data
    msg = StreamData(stream=StreamData.STDOUT, data=b"Hello, world!")
    channel.send(msg)
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, cast

import msgpack

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


class TerminalMessage:
    """Base class for terminal data plane messages.

    Subclasses must define:
        MSGTYPE: TerminalMessageType value
        pack(): Return msgpack-serializable representation
        unpack(data): Class method to reconstruct from packed data
    """

    MSGTYPE: TerminalMessageType

    def pack(self) -> bytes:
        """Serialize message for transmission."""
        raise NotImplementedError

    @classmethod
    def unpack(cls, data: bytes) -> "TerminalMessage":
        """Deserialize message from received data."""
        raise NotImplementedError


@dataclass
class Noop(TerminalMessage):
    """Keep-alive message for Link health monitoring."""

    MSGTYPE = TerminalMessageType.NOOP

    def pack(self) -> bytes:
        return cast(bytes, msgpack.packb({}))

    @classmethod
    def unpack(cls, data: bytes) -> "Noop":
        return cls()


@dataclass
class StreamData(TerminalMessage):
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

    stream: int
    data: bytes
    eof: bool = False

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

    @classmethod
    def unpack(cls, data: bytes) -> "StreamData":
        d = msgpack.unpackb(data, raw=True)
        return cls(
            stream=d[b"s"] if b"s" in d else d["s"],
            data=d[b"d"] if b"d" in d else d["d"],
            eof=d.get(b"e", d.get("e", False)),
        )

    @property
    def is_stdin(self) -> bool:
        return self.stream == self.STDIN

    @property
    def is_stdout(self) -> bool:
        return self.stream == self.STDOUT

    @property
    def is_stderr(self) -> bool:
        return self.stream == self.STDERR


@dataclass
class WindowSize(TerminalMessage):
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

    rows: int
    cols: int
    xpixel: int = 0
    ypixel: int = 0

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

    @classmethod
    def unpack(cls, data: bytes) -> "WindowSize":
        d = msgpack.unpackb(data, raw=True)
        return cls(
            rows=d[b"r"] if b"r" in d else d["r"],
            cols=d[b"c"] if b"c" in d else d["c"],
            xpixel=d.get(b"x", d.get("x", 0)),
            ypixel=d.get(b"y", d.get("y", 0)),
        )


@dataclass
class CommandExited(TerminalMessage):
    """Process termination notification.

    Sent when the shell/command process exits.

    Attributes:
        return_code: Process exit code (0-255 for normal exit)
        signal: Signal that killed the process (None if exited normally)
    """

    MSGTYPE = TerminalMessageType.COMMAND_EXITED

    return_code: int
    signal: int | None = None

    def pack(self) -> bytes:
        d: dict[str, Any] = {"rc": self.return_code}
        if self.signal is not None:
            d["sig"] = self.signal
        return cast(bytes, msgpack.packb(d))

    @classmethod
    def unpack(cls, data: bytes) -> "CommandExited":
        d = msgpack.unpackb(data, raw=True)
        return cls(
            return_code=d[b"rc"] if b"rc" in d else d["rc"],
            signal=d.get(b"sig", d.get("sig")),
        )


@dataclass
class VersionInfo(TerminalMessage):
    """Protocol version handshake.

    Exchanged at Link establishment to ensure compatibility.

    Attributes:
        version: Protocol version (e.g., "1.0")
        software: Software identifier (e.g., "styrened/0.2.0")
    """

    MSGTYPE = TerminalMessageType.VERSION_INFO

    version: str = "1.0"
    software: str = "styrened"

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

    @classmethod
    def unpack(cls, data: bytes) -> "VersionInfo":
        d = msgpack.unpackb(data, raw=True)
        return cls(
            version=(d[b"v"] if b"v" in d else d["v"]).decode()
            if isinstance(d.get(b"v", d.get("v")), bytes)
            else d.get(b"v", d.get("v")),
            software=(d[b"sw"] if b"sw" in d else d["sw"]).decode()
            if isinstance(d.get(b"sw", d.get("sw")), bytes)
            else d.get(b"sw", d.get("sw")),
        )


@dataclass
class Error(TerminalMessage):
    """Error message.

    Attributes:
        message: Human-readable error description
        code: Error code (application-specific)
        fatal: If True, session should be terminated
    """

    MSGTYPE = TerminalMessageType.ERROR

    message: str
    code: int = 1
    fatal: bool = False

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

    @classmethod
    def unpack(cls, data: bytes) -> "Error":
        d = msgpack.unpackb(data, raw=True)
        msg = d[b"m"] if b"m" in d else d["m"]
        if isinstance(msg, bytes):
            msg = msg.decode()
        return cls(
            message=msg,
            code=d.get(b"c", d.get("c", 1)),
            fatal=d.get(b"f", d.get("f", False)),
        )


# Message type registry for RNS Channel integration
MESSAGE_TYPES: dict[TerminalMessageType, type[TerminalMessage]] = {
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
    # RNS Channel uses a different registration pattern than raw messages
    # For now, we'll handle serialization ourselves and use raw packets
    # TODO: Integrate with RNS.MessageBase when available
    pass


def serialize_message(msg: TerminalMessage) -> bytes:
    """Serialize a terminal message for transmission.

    Args:
        msg: Message to serialize

    Returns:
        Wire format: [type:1][packed_data:N]
    """
    return bytes([msg.MSGTYPE]) + msg.pack()


def deserialize_message(data: bytes) -> TerminalMessage:
    """Deserialize a terminal message from wire format.

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

    return msg_class.unpack(data[1:])
