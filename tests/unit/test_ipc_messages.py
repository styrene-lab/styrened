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

    def test_pqc_status_request(self):
        """PQCStatusRequest should serialize correctly."""
        from styrened.ipc.messages import PQCStatusRequest

        req = PQCStatusRequest(peer_hash="abc123def456")
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_PQC_STATUS
        assert payload == {"peer_hash": "abc123def456"}

    def test_pqc_status_request_default(self):
        """PQCStatusRequest should have empty peer_hash by default."""
        from styrened.ipc.messages import PQCStatusRequest

        req = PQCStatusRequest()
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_PQC_STATUS
        assert payload == {"peer_hash": ""}


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
            device_type="styrene",
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
        assert restored.device_type == "styrene"
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

    def test_identity_info_round_trip_with_appearance_fields(self):
        """IdentityInfo should round-trip display_name, icon, short_name."""
        info = IdentityInfo(
            identity_hash="abc123",
            destination_hash="def456",
            lxmf_destination_hash="ghi789",
            display_name="Alice",
            icon="🖥️",
            short_name="alice",
        )

        data = info.to_dict()
        assert data["display_name"] == "Alice"
        assert data["icon"] == "🖥️"
        assert data["short_name"] == "alice"

        restored = IdentityInfo.from_dict(data)
        assert restored.display_name == "Alice"
        assert restored.icon == "🖥️"
        assert restored.short_name == "alice"

    def test_identity_info_backward_compat(self):
        """IdentityInfo.from_dict should handle dicts without appearance fields."""
        data = {
            "identity_hash": "abc123",
            "destination_hash": "def456",
            "lxmf_destination_hash": "ghi789",
        }
        restored = IdentityInfo.from_dict(data)
        assert restored.display_name == ""
        assert restored.icon == ""
        assert restored.short_name is None

    def test_cmd_set_identity_request_serialization(self):
        """CmdSetIdentityRequest should serialize correctly."""
        from styrened.ipc.messages import CmdSetIdentityRequest

        req = CmdSetIdentityRequest(
            display_name="Bob",
            icon="📱",
            short_name="bob",
        )
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_SET_IDENTITY
        assert payload["display_name"] == "Bob"
        assert payload["icon"] == "📱"
        assert payload["short_name"] == "bob"

    def test_cmd_set_identity_request_omits_none_short_name(self):
        """CmdSetIdentityRequest should omit short_name when None."""
        from styrened.ipc.messages import CmdSetIdentityRequest

        req = CmdSetIdentityRequest(
            display_name="Bob",
            icon="📱",
            short_name=None,
        )
        _, payload = req.to_wire()
        assert "short_name" not in payload

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

    def test_remote_status_info_with_available_commands(self):
        """RemoteStatusInfo should round-trip available_commands."""
        status = RemoteStatusInfo(
            uptime=100.0,
            ip="10.0.0.1",
            services=[],
            disk_used=0,
            disk_total=0,
            available_commands=["df", "ls", "uptime"],
        )

        data = status.to_dict()
        assert data["available_commands"] == ["df", "ls", "uptime"]

        restored = RemoteStatusInfo.from_dict(data)
        assert restored.available_commands == ["df", "ls", "uptime"]

    def test_remote_status_info_available_commands_defaults_empty(self):
        """RemoteStatusInfo.available_commands defaults to empty list."""
        status = RemoteStatusInfo(
            uptime=0, ip="", services=[], disk_used=0, disk_total=0,
        )
        assert status.available_commands == []

        # Also works from legacy dicts without the key
        restored = RemoteStatusInfo.from_dict({"uptime": 0, "ip": ""})
        assert restored.available_commands == []

    def test_reboot_result_info_round_trip(self):
        """RebootResultInfo should serialize and deserialize correctly."""
        from styrened.ipc.messages import RebootResultInfo

        info = RebootResultInfo(
            success=True,
            message="Rebooting in 5 seconds",
            scheduled_time=1234567890.0,
        )

        data = info.to_dict()
        assert data["success"] is True
        assert data["message"] == "Rebooting in 5 seconds"
        assert data["scheduled_time"] == 1234567890.0

        restored = RebootResultInfo.from_dict(data)
        assert restored.success is True
        assert restored.message == "Rebooting in 5 seconds"
        assert restored.scheduled_time == 1234567890.0

    def test_reboot_result_info_defaults(self):
        """RebootResultInfo defaults for missing fields."""
        from styrened.ipc.messages import RebootResultInfo

        restored = RebootResultInfo.from_dict({})
        assert restored.success is False
        assert restored.message == ""
        assert restored.scheduled_time is None

    def test_cmd_reboot_device_request(self):
        """CmdRebootDeviceRequest should serialize correctly."""
        from styrened.ipc.messages import CmdRebootDeviceRequest

        req = CmdRebootDeviceRequest(destination="abc123", delay=5, timeout=15.0)
        msg_type, payload = req.to_wire()

        assert msg_type == IPCMessageType.CMD_REBOOT_DEVICE
        assert payload["destination"] == "abc123"
        assert payload["delay"] == 5
        assert payload["timeout"] == 15.0


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

    def test_create_cmd_sync_messages(self):
        """Should create CmdSyncMessagesRequest."""
        from styrened.ipc.messages import CmdSyncMessagesRequest

        req = create_request(IPCMessageType.CMD_SYNC_MESSAGES, {})
        assert isinstance(req, CmdSyncMessagesRequest)

    def test_create_query_path_info(self):
        """Should create QueryPathInfoRequest."""
        from styrened.ipc.messages import QueryPathInfoRequest

        req = create_request(
            IPCMessageType.QUERY_PATH_INFO,
            {"destination_hash": "abcd1234" * 4},
        )
        assert isinstance(req, QueryPathInfoRequest)
        assert req.destination_hash == "abcd1234" * 4

    def test_create_cmd_reboot_device(self):
        """Should create CmdRebootDeviceRequest."""
        from styrened.ipc.messages import CmdRebootDeviceRequest

        req = create_request(
            IPCMessageType.CMD_REBOOT_DEVICE,
            {"destination": "abc", "delay": 5, "timeout": 15.0},
        )
        assert isinstance(req, CmdRebootDeviceRequest)
        assert req.destination == "abc"
        assert req.delay == 5
        assert req.timeout == 15.0

    def test_create_cmd_set_identity(self):
        """Should create CmdSetIdentityRequest."""
        from styrened.ipc.messages import CmdSetIdentityRequest

        req = create_request(
            IPCMessageType.CMD_SET_IDENTITY,
            {"display_name": "Alice", "icon": "🖥️", "short_name": "alice"},
        )
        assert isinstance(req, CmdSetIdentityRequest)
        assert req.display_name == "Alice"
        assert req.icon == "🖥️"
        assert req.short_name == "alice"

    def test_create_cmd_set_identity_defaults(self):
        """Should create CmdSetIdentityRequest with defaults for missing fields."""
        from styrened.ipc.messages import CmdSetIdentityRequest

        req = create_request(IPCMessageType.CMD_SET_IDENTITY, {})
        assert isinstance(req, CmdSetIdentityRequest)
        assert req.display_name == ""
        assert req.icon == ""
        assert req.short_name is None

    def test_create_cmd_pqc_status(self):
        """Should create PQCStatusRequest with peer_hash from payload."""
        from styrened.ipc.messages import PQCStatusRequest

        req = create_request(
            IPCMessageType.CMD_PQC_STATUS,
            {"peer_hash": "abcd1234" * 4},
        )
        assert isinstance(req, PQCStatusRequest)
        assert req.peer_hash == "abcd1234" * 4

    def test_create_cmd_pqc_status_defaults(self):
        """Should create PQCStatusRequest with default empty peer_hash."""
        from styrened.ipc.messages import PQCStatusRequest

        req = create_request(IPCMessageType.CMD_PQC_STATUS, {})
        assert isinstance(req, PQCStatusRequest)
        assert req.peer_hash == ""

    def test_unknown_type_raises(self):
        """Should raise ValueError for unknown types."""
        with pytest.raises(ValueError, match="Unknown request type"):
            create_request(IPCMessageType.RESULT, {})
