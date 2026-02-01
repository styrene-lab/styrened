"""Unit tests for terminal data plane messages."""

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
