"""Unit tests for IPC page browser message dataclasses."""

from styrened.ipc.messages import (
    CmdPageDisconnectRequest,
    QueryPageRequest,
    create_request,
)
from styrened.ipc.protocol import IPCMessageType


class TestQueryPageRequest:
    """Tests for QueryPageRequest serialization."""

    def test_default_serialization(self):
        """QueryPageRequest with defaults should serialize correctly."""
        req = QueryPageRequest()
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.QUERY_PAGE
        assert payload["destination_hash"] == ""
        assert payload["path"] == "/page/index.mu"
        assert "form_data" not in payload  # None form_data is excluded
        assert payload["timeout"] == 30.0

    def test_full_serialization(self):
        """QueryPageRequest with all fields should serialize correctly."""
        req = QueryPageRequest(
            destination_hash="abcdef1234567890",
            path="/page/about.mu",
            form_data={"field1": "value1"},
            timeout=45.0,
        )
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.QUERY_PAGE
        assert payload["destination_hash"] == "abcdef1234567890"
        assert payload["path"] == "/page/about.mu"
        assert payload["form_data"] == {"field1": "value1"}
        assert payload["timeout"] == 45.0


class TestCmdPageDisconnectRequest:
    """Tests for CmdPageDisconnectRequest serialization."""

    def test_serialization(self):
        """CmdPageDisconnectRequest should serialize correctly."""
        req = CmdPageDisconnectRequest(destination_hash="abcdef1234567890")
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_PAGE_DISCONNECT
        assert payload["destination_hash"] == "abcdef1234567890"

    def test_default_serialization(self):
        """CmdPageDisconnectRequest with defaults should serialize correctly."""
        req = CmdPageDisconnectRequest()
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_PAGE_DISCONNECT
        assert payload["destination_hash"] == ""


class TestCreateRequestFactory:
    """Tests for create_request() with page browser types."""

    def test_create_query_page(self):
        """Should create QueryPageRequest via factory."""
        req = create_request(
            IPCMessageType.QUERY_PAGE,
            {
                "destination_hash": "abc123",
                "path": "/page/test.mu",
                "timeout": 20.0,
            },
        )
        assert isinstance(req, QueryPageRequest)
        assert req.destination_hash == "abc123"
        assert req.path == "/page/test.mu"
        assert req.timeout == 20.0

    def test_create_cmd_page_disconnect(self):
        """Should create CmdPageDisconnectRequest via factory."""
        req = create_request(
            IPCMessageType.CMD_PAGE_DISCONNECT,
            {"destination_hash": "abc123"},
        )
        assert isinstance(req, CmdPageDisconnectRequest)
        assert req.destination_hash == "abc123"
