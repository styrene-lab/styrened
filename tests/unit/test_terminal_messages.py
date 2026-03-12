"""Unit tests for terminal data plane messages."""
from __future__ import annotations


from unittest.mock import MagicMock

import pytest

from styrened.terminal.messages import (
    CommandExited,
    Error,
    Noop,
    StreamData,
    TerminalMessageType,
    VersionInfo,
    WindowSize,
    deserialize_message,
    register_message_types,
    serialize_message,
)


class TestStreamData:
    """Tests for StreamData message."""

    def test_stdin_roundtrip(self) -> None:
        """STDIN StreamData should serialize and deserialize."""
        msg = StreamData(stream=StreamData.STDIN, data=b"hello world")
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert isinstance(decoded, StreamData)
        assert decoded.stream == StreamData.STDIN
        assert decoded.data == b"hello world"
        assert decoded.eof is False
        assert decoded.is_stdin

    def test_stdout_roundtrip(self) -> None:
        """STDOUT StreamData should serialize and deserialize."""
        msg = StreamData(stream=StreamData.STDOUT, data=b"output", eof=True)
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert isinstance(decoded, StreamData)
        assert decoded.stream == StreamData.STDOUT
        assert decoded.data == b"output"
        assert decoded.eof is True
        assert decoded.is_stdout

    def test_stderr_roundtrip(self) -> None:
        """STDERR StreamData should serialize and deserialize."""
        msg = StreamData(stream=StreamData.STDERR, data=b"error message")
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert isinstance(decoded, StreamData)
        assert decoded.is_stderr

    def test_binary_data(self) -> None:
        """StreamData should handle binary data."""
        binary = bytes(range(256))
        msg = StreamData(stream=StreamData.STDOUT, data=binary)
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert decoded.data == binary

    def test_empty_data(self) -> None:
        """StreamData should handle empty data."""
        msg = StreamData(stream=StreamData.STDOUT, data=b"")
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert decoded.data == b""


class TestWindowSize:
    """Tests for WindowSize message."""

    def test_basic_roundtrip(self) -> None:
        """WindowSize should serialize and deserialize."""
        msg = WindowSize(rows=24, cols=80)
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert isinstance(decoded, WindowSize)
        assert decoded.rows == 24
        assert decoded.cols == 80
        assert decoded.xpixel == 0
        assert decoded.ypixel == 0

    def test_with_pixels(self) -> None:
        """WindowSize should preserve pixel dimensions."""
        msg = WindowSize(rows=40, cols=120, xpixel=1920, ypixel=1080)
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert decoded.rows == 40
        assert decoded.cols == 120
        assert decoded.xpixel == 1920
        assert decoded.ypixel == 1080


class TestCommandExited:
    """Tests for CommandExited message."""

    def test_normal_exit(self) -> None:
        """CommandExited should handle normal exit."""
        msg = CommandExited(return_code=0)
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert isinstance(decoded, CommandExited)
        assert decoded.return_code == 0
        assert decoded.signal is None

    def test_error_exit(self) -> None:
        """CommandExited should handle error exit code."""
        msg = CommandExited(return_code=1)
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert decoded.return_code == 1

    def test_signal_exit(self) -> None:
        """CommandExited should handle signal termination."""
        import signal

        msg = CommandExited(return_code=128 + signal.SIGKILL, signal=signal.SIGKILL)
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert decoded.return_code == 137  # 128 + 9
        assert decoded.signal == signal.SIGKILL


class TestVersionInfo:
    """Tests for VersionInfo message."""

    def test_default_values(self) -> None:
        """VersionInfo should have sensible defaults."""
        msg = VersionInfo()
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert isinstance(decoded, VersionInfo)
        assert decoded.version == "1.0"
        assert decoded.software == "styrened"

    def test_custom_values(self) -> None:
        """VersionInfo should preserve custom values."""
        msg = VersionInfo(version="2.0", software="my-client/1.2.3")
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert decoded.version == "2.0"
        assert decoded.software == "my-client/1.2.3"


class TestError:
    """Tests for Error message."""

    def test_basic_error(self) -> None:
        """Error should serialize and deserialize."""
        msg = Error(message="Something went wrong")
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert isinstance(decoded, Error)
        assert decoded.message == "Something went wrong"
        assert decoded.code == 1
        assert decoded.fatal is False

    def test_fatal_error(self) -> None:
        """Error should preserve fatal flag."""
        msg = Error(message="Connection lost", code=42, fatal=True)
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert decoded.message == "Connection lost"
        assert decoded.code == 42
        assert decoded.fatal is True


class TestNoop:
    """Tests for Noop message."""

    def test_roundtrip(self) -> None:
        """Noop should serialize and deserialize."""
        msg = Noop()
        wire = serialize_message(msg)
        decoded = deserialize_message(wire)

        assert isinstance(decoded, Noop)


class TestMessageTypeIdentification:
    """Tests for message type byte prefix."""

    def test_type_prefix(self) -> None:
        """Each message type should have correct prefix byte."""
        messages = [
            (Noop(), TerminalMessageType.NOOP),
            (StreamData(stream=0, data=b""), TerminalMessageType.STREAM_DATA),
            (WindowSize(rows=24, cols=80), TerminalMessageType.WINDOW_SIZE),
            (CommandExited(return_code=0), TerminalMessageType.COMMAND_EXITED),
            (VersionInfo(), TerminalMessageType.VERSION_INFO),
            (Error(message="test"), TerminalMessageType.ERROR),
        ]

        for msg, expected_type in messages:
            wire = serialize_message(msg)
            assert wire[0] == expected_type

    def test_unknown_type_raises(self) -> None:
        """Unknown message type should raise ValueError."""
        invalid_wire = bytes([99])  # Invalid type (not in TerminalMessageType)
        # The enum conversion will raise ValueError for invalid types
        with pytest.raises(ValueError):
            deserialize_message(invalid_wire)

    def test_empty_data_raises(self) -> None:
        """Empty data should raise ValueError."""
        with pytest.raises(ValueError, match="Empty message"):
            deserialize_message(b"")


class TestChannelMessageBaseCompat:
    """Tests for RNS.Channel.MessageBase compatibility.

    Message classes must work as Channel messages: no-arg construction,
    instance-method unpack(), MSGTYPE < 0xf000, and register_message_types().
    """

    ALL_CLASSES = [Noop, StreamData, WindowSize, CommandExited, VersionInfo, Error]

    def test_no_arg_construction(self) -> None:
        """All message classes must be constructable with no arguments."""
        for cls in self.ALL_CLASSES:
            instance = cls()
            assert instance is not None, f"{cls.__name__}() should succeed with no args"

    def test_msgtype_below_threshold(self) -> None:
        """All MSGTYPE values must be < 0xf000 (Channel reserved threshold)."""
        for cls in self.ALL_CLASSES:
            assert cls.MSGTYPE < 0xF000, (
                f"{cls.__name__}.MSGTYPE={cls.MSGTYPE} must be < 0xf000"
            )

    def test_instance_method_unpack_roundtrip(self) -> None:
        """unpack() as instance method should populate self from packed bytes."""
        # StreamData round-trip via instance method
        original = StreamData(stream=StreamData.STDOUT, data=b"test data", eof=True)
        packed = original.pack()
        restored = StreamData()
        restored.unpack(packed)
        assert restored.stream == StreamData.STDOUT
        assert restored.data == b"test data"
        assert restored.eof is True

    def test_instance_method_unpack_window_size(self) -> None:
        """WindowSize unpack() instance method should work."""
        original = WindowSize(rows=50, cols=132, xpixel=800, ypixel=600)
        packed = original.pack()
        restored = WindowSize()
        restored.unpack(packed)
        assert restored.rows == 50
        assert restored.cols == 132
        assert restored.xpixel == 800
        assert restored.ypixel == 600

    def test_instance_method_unpack_command_exited(self) -> None:
        """CommandExited unpack() instance method should work."""
        import signal

        original = CommandExited(return_code=137, signal=signal.SIGKILL)
        packed = original.pack()
        restored = CommandExited()
        restored.unpack(packed)
        assert restored.return_code == 137
        assert restored.signal == signal.SIGKILL

    def test_instance_method_unpack_version_info(self) -> None:
        """VersionInfo unpack() instance method should work."""
        original = VersionInfo(version="2.0", software="test-client/1.0")
        packed = original.pack()
        restored = VersionInfo()
        restored.unpack(packed)
        assert restored.version == "2.0"
        assert restored.software == "test-client/1.0"

    def test_instance_method_unpack_error(self) -> None:
        """Error unpack() instance method should work."""
        original = Error(message="connection lost", code=42, fatal=True)
        packed = original.pack()
        restored = Error()
        restored.unpack(packed)
        assert restored.message == "connection lost"
        assert restored.code == 42
        assert restored.fatal is True

    def test_instance_method_unpack_noop(self) -> None:
        """Noop unpack() instance method should work."""
        original = Noop()
        packed = original.pack()
        restored = Noop()
        restored.unpack(packed)  # Should not raise

    def test_register_message_types_calls_channel(self) -> None:
        """register_message_types() should register all types with the Channel."""
        mock_channel = MagicMock()
        register_message_types(mock_channel)

        # Should have called register_message_type for each message class
        assert mock_channel.register_message_type.call_count == len(self.ALL_CLASSES)

        # Verify all classes were registered
        registered = {
            call.args[0] for call in mock_channel.register_message_type.call_args_list
        }
        for cls in self.ALL_CLASSES:
            assert cls in registered, f"{cls.__name__} not registered"

    def test_backward_compat_serialize_deserialize(self) -> None:
        """serialize_message/deserialize_message must still work for v1.0 raw packet path."""
        messages = [
            Noop(),
            StreamData(stream=StreamData.STDIN, data=b"hello"),
            WindowSize(rows=24, cols=80),
            CommandExited(return_code=0),
            VersionInfo(version="1.0"),
            Error(message="test"),
        ]
        for msg in messages:
            wire = serialize_message(msg)
            decoded = deserialize_message(wire)
            assert type(decoded) is type(msg), (
                f"Round-trip failed for {type(msg).__name__}"
            )

    def test_is_message_base_subclass(self) -> None:
        """All message classes should extend RNS.Channel.MessageBase."""
        from RNS.Channel import MessageBase

        for cls in self.ALL_CLASSES:
            assert issubclass(cls, MessageBase), (
                f"{cls.__name__} must be a MessageBase subclass"
            )
