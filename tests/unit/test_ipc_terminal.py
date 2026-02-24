"""Unit tests for IPC terminal message serialization/deserialization.

Tests the terminal request types and their round-trip through the
create_request factory, as well as IPCMessageType membership and
is_event_type behavior for terminal events.
"""

from styrened.ipc.messages import (
    CmdTerminalCloseRequest,
    CmdTerminalInputRequest,
    CmdTerminalOpenRequest,
    CmdTerminalResizeRequest,
    create_request,
)
from styrened.ipc.protocol import IPCMessageType, is_event_type


class TestTerminalMessageTypes:
    """Test terminal message type enum values and classification."""

    def test_terminal_command_types_exist(self):
        """Terminal command types should be in the enum."""
        assert IPCMessageType.CMD_TERMINAL_OPEN == 0x50
        assert IPCMessageType.CMD_TERMINAL_INPUT == 0x51
        assert IPCMessageType.CMD_TERMINAL_RESIZE == 0x52
        assert IPCMessageType.CMD_TERMINAL_CLOSE == 0x53

    def test_terminal_event_types_exist(self):
        """Terminal event types should be in the enum."""
        assert IPCMessageType.EVENT_TERMINAL_OUTPUT == 0xC2
        assert IPCMessageType.EVENT_TERMINAL_EXITED == 0xC3
        assert IPCMessageType.EVENT_TERMINAL_ERROR == 0xC4
        assert IPCMessageType.EVENT_TERMINAL_READY == 0xC5

    def test_terminal_events_are_event_type(self):
        """Terminal events should pass is_event_type check."""
        assert is_event_type(IPCMessageType.EVENT_TERMINAL_OUTPUT) is True
        assert is_event_type(IPCMessageType.EVENT_TERMINAL_EXITED) is True
        assert is_event_type(IPCMessageType.EVENT_TERMINAL_ERROR) is True
        assert is_event_type(IPCMessageType.EVENT_TERMINAL_READY) is True

    def test_terminal_commands_not_event_type(self):
        """Terminal commands should NOT pass is_event_type check."""
        assert is_event_type(IPCMessageType.CMD_TERMINAL_OPEN) is False
        assert is_event_type(IPCMessageType.CMD_TERMINAL_INPUT) is False
        assert is_event_type(IPCMessageType.CMD_TERMINAL_RESIZE) is False
        assert is_event_type(IPCMessageType.CMD_TERMINAL_CLOSE) is False


class TestTerminalOpenRequest:
    """Test CmdTerminalOpenRequest serialization."""

    def test_to_payload_all_fields(self):
        """Open request should serialize all fields."""
        req = CmdTerminalOpenRequest(
            destination="abc123",
            term_type="vt100",
            rows=40,
            cols=120,
            shell="/bin/zsh",
        )
        payload = req.to_payload()
        assert payload["destination"] == "abc123"
        assert payload["term_type"] == "vt100"
        assert payload["rows"] == 40
        assert payload["cols"] == 120
        assert payload["shell"] == "/bin/zsh"

    def test_to_payload_defaults(self):
        """Open request defaults should be xterm-256color 24x80."""
        req = CmdTerminalOpenRequest(destination="abc123")
        payload = req.to_payload()
        assert payload["term_type"] == "xterm-256color"
        assert payload["rows"] == 24
        assert payload["cols"] == 80
        assert "shell" not in payload

    def test_to_wire_type(self):
        """Open request wire type should be CMD_TERMINAL_OPEN."""
        req = CmdTerminalOpenRequest()
        msg_type, _ = req.to_wire()
        assert msg_type == IPCMessageType.CMD_TERMINAL_OPEN

    def test_roundtrip_via_create_request(self):
        """Open request should roundtrip through create_request factory."""
        original = CmdTerminalOpenRequest(
            destination="deadbeef12345678",
            term_type="xterm-256color",
            rows=30,
            cols=100,
            shell="/bin/bash",
        )
        payload = original.to_payload()
        restored = create_request(IPCMessageType.CMD_TERMINAL_OPEN, payload)
        assert isinstance(restored, CmdTerminalOpenRequest)
        assert restored.destination == "deadbeef12345678"
        assert restored.rows == 30
        assert restored.cols == 100
        assert restored.shell == "/bin/bash"


class TestTerminalInputRequest:
    """Test CmdTerminalInputRequest serialization."""

    def test_to_payload(self):
        """Input request should serialize session_id and data_b64."""
        req = CmdTerminalInputRequest(
            session_id="aabbccdd",
            data_b64="SGVsbG8=",
        )
        payload = req.to_payload()
        assert payload["session_id"] == "aabbccdd"
        assert payload["data_b64"] == "SGVsbG8="

    def test_to_wire_type(self):
        """Input request wire type should be CMD_TERMINAL_INPUT."""
        req = CmdTerminalInputRequest()
        msg_type, _ = req.to_wire()
        assert msg_type == IPCMessageType.CMD_TERMINAL_INPUT

    def test_roundtrip_via_create_request(self):
        """Input request should roundtrip through create_request factory."""
        payload = {"session_id": "abc123", "data_b64": "dGVzdA=="}
        restored = create_request(IPCMessageType.CMD_TERMINAL_INPUT, payload)
        assert isinstance(restored, CmdTerminalInputRequest)
        assert restored.session_id == "abc123"
        assert restored.data_b64 == "dGVzdA=="


class TestTerminalResizeRequest:
    """Test CmdTerminalResizeRequest serialization."""

    def test_to_payload(self):
        """Resize request should serialize all fields."""
        req = CmdTerminalResizeRequest(session_id="abc", rows=48, cols=160)
        payload = req.to_payload()
        assert payload["session_id"] == "abc"
        assert payload["rows"] == 48
        assert payload["cols"] == 160

    def test_to_wire_type(self):
        """Resize request wire type should be CMD_TERMINAL_RESIZE."""
        req = CmdTerminalResizeRequest()
        msg_type, _ = req.to_wire()
        assert msg_type == IPCMessageType.CMD_TERMINAL_RESIZE

    def test_roundtrip_via_create_request(self):
        """Resize request should roundtrip through create_request factory."""
        payload = {"session_id": "xyz", "rows": 50, "cols": 200}
        restored = create_request(IPCMessageType.CMD_TERMINAL_RESIZE, payload)
        assert isinstance(restored, CmdTerminalResizeRequest)
        assert restored.session_id == "xyz"
        assert restored.rows == 50
        assert restored.cols == 200


class TestTerminalCloseRequest:
    """Test CmdTerminalCloseRequest serialization."""

    def test_to_payload(self):
        """Close request should serialize session_id."""
        req = CmdTerminalCloseRequest(session_id="sess123")
        payload = req.to_payload()
        assert payload["session_id"] == "sess123"

    def test_to_wire_type(self):
        """Close request wire type should be CMD_TERMINAL_CLOSE."""
        req = CmdTerminalCloseRequest()
        msg_type, _ = req.to_wire()
        assert msg_type == IPCMessageType.CMD_TERMINAL_CLOSE

    def test_roundtrip_via_create_request(self):
        """Close request should roundtrip through create_request factory."""
        payload = {"session_id": "close_me"}
        restored = create_request(IPCMessageType.CMD_TERMINAL_CLOSE, payload)
        assert isinstance(restored, CmdTerminalCloseRequest)
        assert restored.session_id == "close_me"


class TestTerminalWireRoundtrip:
    """Test full wire format encode/decode roundtrip for terminal messages."""

    def test_terminal_open_frame_roundtrip(self):
        """Terminal open request should survive encode/decode cycle."""
        from styrened.ipc.protocol import decode_frame, encode_frame, generate_request_id

        req = CmdTerminalOpenRequest(
            destination="abcdef1234567890",
            rows=24,
            cols=80,
        )
        msg_type, payload = req.to_wire()
        request_id = generate_request_id()

        frame = encode_frame(msg_type, request_id, payload)
        decoded_type, decoded_id, decoded_payload = decode_frame(frame)

        assert decoded_type == IPCMessageType.CMD_TERMINAL_OPEN
        assert decoded_id == request_id
        assert decoded_payload["destination"] == "abcdef1234567890"
        assert decoded_payload["rows"] == 24
        assert decoded_payload["cols"] == 80
