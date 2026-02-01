"""Unit tests for IPC message dataclasses."""

import pytest

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
    IPCErrorCode,
    PingRequest,
    PongResponse,
    QueryDevicesRequest,
    QueryIdentityRequest,
    QueryStatusRequest,
    RemoteStatusInfo,
    ResultResponse,
    create_request,
)
from styrened.ipc.protocol import IPCMessageType


class TestQueryRequests:
    """Tests for query request dataclasses."""

    def test_ping_request(self):
        """PingRequest should serialize correctly."""
        req = PingRequest()
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.PING
        assert payload == {}

    def test_query_devices_request(self):
        """QueryDevicesRequest should serialize correctly."""
        req = QueryDevicesRequest(styrene_only=True)
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.QUERY_DEVICES
        assert payload == {"styrene_only": True}

    def test_query_identity_request(self):
        """QueryIdentityRequest should serialize correctly."""
        req = QueryIdentityRequest()
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.QUERY_IDENTITY
        assert payload == {}

    def test_query_status_request(self):
        """QueryStatusRequest should serialize correctly."""
        req = QueryStatusRequest()
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.QUERY_STATUS
        assert payload == {}


class TestCommandRequests:
    """Tests for command request dataclasses."""

    def test_cmd_send_request(self):
        """CmdSendRequest should serialize correctly."""
        req = CmdSendRequest(
            destination="abc123",
            message="Hello",
            protocol="chat",
            retry=True,
            timeout=45.0,
        )
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_SEND
        assert payload["destination"] == "abc123"
        assert payload["message"] == "Hello"
        assert payload["protocol"] == "chat"
        assert payload["retry"] is True
        assert payload["timeout"] == 45.0

    def test_cmd_exec_request(self):
        """CmdExecRequest should serialize correctly."""
        req = CmdExecRequest(
            destination="def456",
            command="uptime",
            args=["-p"],
            timeout=30.0,
        )
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_EXEC
        assert payload["destination"] == "def456"
        assert payload["command"] == "uptime"
        assert payload["args"] == ["-p"]
        assert payload["timeout"] == 30.0

    def test_cmd_announce_request(self):
        """CmdAnnounceRequest should serialize correctly."""
        req = CmdAnnounceRequest()
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_ANNOUNCE
        assert payload == {}

    def test_cmd_device_status_request(self):
        """CmdDeviceStatusRequest should serialize correctly."""
        req = CmdDeviceStatusRequest(destination="ghi789", timeout=20.0)
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_DEVICE_STATUS
        assert payload["destination"] == "ghi789"
        assert payload["timeout"] == 20.0


class TestResponses:
    """Tests for response dataclasses."""

    def test_pong_response(self):
        """PongResponse should serialize and deserialize correctly."""
        resp = PongResponse(daemon_version="0.2.0")
        msg_type, payload = resp.to_wire()

        assert msg_type == IPCMessageType.PONG
        assert payload["success"] is True
        assert payload["daemon_version"] == "0.2.0"

        # Deserialize
        restored = PongResponse.from_payload(payload)
        assert restored.daemon_version == "0.2.0"

    def test_result_response(self):
        """ResultResponse should serialize and deserialize correctly."""
        resp = ResultResponse(data={"devices": [{"name": "node1"}]})
        msg_type, payload = resp.to_wire()

        assert msg_type == IPCMessageType.RESULT
        assert payload["success"] is True
        assert payload["data"]["devices"][0]["name"] == "node1"

        # Deserialize
        restored = ResultResponse.from_payload(payload)
        assert restored.data["devices"][0]["name"] == "node1"

    def test_error_response(self):
        """ErrorResponse should serialize and deserialize correctly."""
        resp = ErrorResponse(
            code=IPCErrorCode.NOT_FOUND,
            message="Device not found",
            details={"destination": "xyz"},
        )
        msg_type, payload = resp.to_wire()

        assert msg_type == IPCMessageType.ERROR
        assert payload["success"] is False
        assert payload["code"] == IPCErrorCode.NOT_FOUND
        assert payload["message"] == "Device not found"
        assert payload["details"]["destination"] == "xyz"

        # Deserialize
        restored = ErrorResponse.from_payload(payload)
        assert restored.code == IPCErrorCode.NOT_FOUND
        assert restored.message == "Device not found"

    def test_error_response_factories(self):
        """ErrorResponse factory methods should work correctly."""
        not_found = ErrorResponse.not_found("Missing")
        assert not_found.code == IPCErrorCode.NOT_FOUND

        timeout = ErrorResponse.timeout("Timed out")
        assert timeout.code == IPCErrorCode.TIMEOUT

        invalid = ErrorResponse.invalid_request("Bad request")
        assert invalid.code == IPCErrorCode.INVALID_REQUEST

        internal = ErrorResponse.internal_error("Oops")
        assert internal.code == IPCErrorCode.INTERNAL_ERROR


class TestInfoDataclasses:
    """Tests for info dataclasses."""

    def test_device_info_round_trip(self):
        """DeviceInfo should serialize and deserialize correctly."""
        info = DeviceInfo(
            destination_hash="abc123",
            identity_hash="def456",
            name="test-node",
            device_type="styrene_node",
            status="active",
            is_styrene_node=True,
            lxmf_destination_hash="ghi789",
            last_announce=1234567890.0,
            announce_count=5,
        )

        data = info.to_dict()
        restored = DeviceInfo.from_dict(data)

        assert restored.destination_hash == "abc123"
        assert restored.identity_hash == "def456"
        assert restored.name == "test-node"
        assert restored.device_type == "styrene_node"
        assert restored.is_styrene_node is True
        assert restored.announce_count == 5

    def test_identity_info_round_trip(self):
        """IdentityInfo should serialize and deserialize correctly."""
        info = IdentityInfo(
            identity_hash="abc123",
            destination_hash="def456",
            lxmf_destination_hash="ghi789",
        )

        data = info.to_dict()
        restored = IdentityInfo.from_dict(data)

        assert restored.identity_hash == "abc123"
        assert restored.destination_hash == "def456"
        assert restored.lxmf_destination_hash == "ghi789"

    def test_daemon_status_round_trip(self):
        """DaemonStatus should serialize and deserialize correctly."""
        status = DaemonStatus(
            uptime=3600.5,
            daemon_version="0.2.0",
            rns_initialized=True,
            lxmf_initialized=True,
            device_count=10,
            styrene_node_count=3,
            pending_rpc_count=1,
        )

        data = status.to_dict()
        restored = DaemonStatus.from_dict(data)

        assert restored.uptime == 3600.5
        assert restored.daemon_version == "0.2.0"
        assert restored.rns_initialized is True
        assert restored.device_count == 10

    def test_exec_result_info(self):
        """ExecResultInfo should serialize correctly."""
        result = ExecResultInfo(exit_code=0, stdout="output", stderr="")
        assert result.success is True

        result_fail = ExecResultInfo(exit_code=1, stdout="", stderr="error")
        assert result_fail.success is False

    def test_remote_status_info_round_trip(self):
        """RemoteStatusInfo should serialize and deserialize correctly."""
        status = RemoteStatusInfo(
            uptime=7200.0,
            ip="192.168.1.100",
            services=["styrened", "sshd"],
            disk_used=50 * 1024**3,
            disk_total=100 * 1024**3,
        )

        data = status.to_dict()
        restored = RemoteStatusInfo.from_dict(data)

        assert restored.uptime == 7200.0
        assert restored.ip == "192.168.1.100"
        assert restored.services == ["styrened", "sshd"]


class TestCreateRequest:
    """Tests for create_request() factory function."""

    def test_create_ping(self):
        """Should create PingRequest."""
        req = create_request(IPCMessageType.PING, {})
        assert isinstance(req, PingRequest)

    def test_create_query_devices(self):
        """Should create QueryDevicesRequest."""
        req = create_request(IPCMessageType.QUERY_DEVICES, {"styrene_only": True})
        assert isinstance(req, QueryDevicesRequest)
        assert req.styrene_only is True

    def test_create_cmd_send(self):
        """Should create CmdSendRequest."""
        req = create_request(
            IPCMessageType.CMD_SEND,
            {"destination": "abc", "message": "hi", "retry": True},
        )
        assert isinstance(req, CmdSendRequest)
        assert req.destination == "abc"
        assert req.message == "hi"
        assert req.retry is True

    def test_create_cmd_exec(self):
        """Should create CmdExecRequest."""
        req = create_request(
            IPCMessageType.CMD_EXEC,
            {"destination": "abc", "command": "ls", "args": ["-la"]},
        )
        assert isinstance(req, CmdExecRequest)
        assert req.command == "ls"
        assert req.args == ["-la"]

    def test_unknown_type_raises(self):
        """Should raise ValueError for unknown types."""
        with pytest.raises(ValueError, match="Unknown request type"):
            create_request(IPCMessageType.RESULT, {})
