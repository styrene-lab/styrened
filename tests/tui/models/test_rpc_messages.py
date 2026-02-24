"""Tests for RPC message models.

These tests verify:
- Message serialization to JSON
- Message deserialization from JSON
- Round-trip serialization/deserialization
- Validation of required fields
- Handling of missing/extra fields
"""

import pytest

from styrened.rpc.messages import (
    ExecCommand,
    ExecResult,
    SelfUpdateResult,
    StatusRequest,
    StatusResponse,
)


class TestStatusRequest:
    """Tests for StatusRequest message model."""

    def test_status_request_to_json(self) -> None:
        """Test StatusRequest serializes to correct JSON."""
        msg = StatusRequest()
        data = msg.to_dict()

        assert data == {"type": "status_request"}

    def test_status_request_from_dict(self) -> None:
        """Test StatusRequest deserializes from JSON."""
        data = {"type": "status_request"}
        msg = StatusRequest.from_dict(data)

        assert isinstance(msg, StatusRequest)

    def test_status_request_round_trip(self) -> None:
        """Test StatusRequest serialization round-trip."""
        original = StatusRequest()
        data = original.to_dict()
        restored = StatusRequest.from_dict(data)

        assert isinstance(restored, StatusRequest)
        assert restored.to_dict() == original.to_dict()

    def test_status_request_from_json_with_extra_fields(self) -> None:
        """Test StatusRequest ignores extra fields in JSON."""
        data = {"type": "status_request", "extra": "ignored"}
        msg = StatusRequest.from_dict(data)

        assert isinstance(msg, StatusRequest)
        assert msg.to_dict() == {"type": "status_request"}


class TestStatusResponse:
    """Tests for StatusResponse message model."""

    def test_status_response_to_json(self) -> None:
        """Test StatusResponse serializes to correct JSON."""
        msg = StatusResponse(
            uptime=123456,
            ip="192.168.0.101",
            services=["reticulum", "nomadnet"],
            disk_used=4200000000,
            disk_total=28000000000,
        )
        data = msg.to_dict()

        assert data["type"] == "status_response"
        assert data["uptime"] == 123456
        assert data["ip"] == "192.168.0.101"
        assert data["services"] == ["reticulum", "nomadnet"]
        assert data["disk_used"] == 4200000000
        assert data["disk_total"] == 28000000000
        # New optional fields default to None
        assert data["styrened_version"] is None
        assert data["hostname"] is None
        assert data["arch"] is None
        assert data["os_id"] is None
        assert data["os_version"] is None
        assert data["nixos_generation"] is None

    def test_status_response_from_dict(self) -> None:
        """Test StatusResponse deserializes from JSON."""
        data = {
            "type": "status_response",
            "uptime": 123456,
            "ip": "192.168.0.101",
            "services": ["reticulum", "nomadnet"],
            "disk_used": 4200000000,
            "disk_total": 28000000000,
        }
        msg = StatusResponse.from_dict(data)

        assert isinstance(msg, StatusResponse)
        assert msg.uptime == 123456
        assert msg.ip == "192.168.0.101"
        assert msg.services == ["reticulum", "nomadnet"]
        assert msg.disk_used == 4200000000
        assert msg.disk_total == 28000000000

    def test_status_response_round_trip(self) -> None:
        """Test StatusResponse serialization round-trip."""
        original = StatusResponse(
            uptime=987654,
            ip="10.0.0.5",
            services=["ssh", "docker"],
            disk_used=1000000,
            disk_total=2000000,
        )
        data = original.to_dict()
        restored = StatusResponse.from_dict(data)

        assert restored.uptime == original.uptime
        assert restored.ip == original.ip
        assert restored.services == original.services
        assert restored.disk_used == original.disk_used
        assert restored.disk_total == original.disk_total

    def test_status_response_with_empty_services(self) -> None:
        """Test StatusResponse with empty services list."""
        msg = StatusResponse(
            uptime=0,
            ip="127.0.0.1",
            services=[],
            disk_used=0,
            disk_total=100,
        )
        data = msg.to_dict()

        assert data["services"] == []

        restored = StatusResponse.from_dict(data)
        assert restored.services == []

    def test_status_response_missing_field_raises_error(self) -> None:
        """Test StatusResponse raises error when required field missing."""
        data = {
            "type": "status_response",
            "uptime": 123456,
            # Missing ip, services, disk_used, disk_total
        }

        with pytest.raises((KeyError, TypeError)):
            StatusResponse.from_dict(data)


class TestExecCommand:
    """Tests for ExecCommand message model."""

    def test_exec_command_to_json(self) -> None:
        """Test ExecCommand serializes to correct JSON."""
        msg = ExecCommand(
            command="systemctl",
            args=["status", "reticulum"],
        )
        data = msg.to_dict()

        assert data == {
            "type": "exec",
            "command": "systemctl",
            "args": ["status", "reticulum"],
        }

    def test_exec_command_from_dict(self) -> None:
        """Test ExecCommand deserializes from JSON."""
        data = {
            "type": "exec",
            "command": "systemctl",
            "args": ["status", "reticulum"],
        }
        msg = ExecCommand.from_dict(data)

        assert isinstance(msg, ExecCommand)
        assert msg.command == "systemctl"
        assert msg.args == ["status", "reticulum"]

    def test_exec_command_round_trip(self) -> None:
        """Test ExecCommand serialization round-trip."""
        original = ExecCommand(
            command="ls",
            args=["-la", "/tmp"],
        )
        data = original.to_dict()
        restored = ExecCommand.from_dict(data)

        assert restored.command == original.command
        assert restored.args == original.args

    def test_exec_command_with_no_args(self) -> None:
        """Test ExecCommand with empty args list."""
        msg = ExecCommand(
            command="uptime",
            args=[],
        )
        data = msg.to_dict()

        assert data["args"] == []

        restored = ExecCommand.from_dict(data)
        assert restored.args == []

    def test_exec_command_with_many_args(self) -> None:
        """Test ExecCommand with many arguments."""
        msg = ExecCommand(
            command="docker",
            args=["run", "-d", "--name", "test", "alpine", "sh", "-c", "sleep 1000"],
        )
        data = msg.to_dict()
        restored = ExecCommand.from_dict(data)

        assert restored.command == "docker"
        assert len(restored.args) == 8


class TestExecResult:
    """Tests for ExecResult message model."""

    def test_exec_result_to_json(self) -> None:
        """Test ExecResult serializes to correct JSON."""
        msg = ExecResult(
            exit_code=0,
            stdout="● reticulum.service - Reticulum Network Stack\n",
            stderr="",
        )
        data = msg.to_dict()

        assert data == {
            "type": "exec_result",
            "exit_code": 0,
            "stdout": "● reticulum.service - Reticulum Network Stack\n",
            "stderr": "",
        }

    def test_exec_result_from_dict(self) -> None:
        """Test ExecResult deserializes from JSON."""
        data = {
            "type": "exec_result",
            "exit_code": 0,
            "stdout": "output here",
            "stderr": "",
        }
        msg = ExecResult.from_dict(data)

        assert isinstance(msg, ExecResult)
        assert msg.exit_code == 0
        assert msg.stdout == "output here"
        assert msg.stderr == ""

    def test_exec_result_round_trip(self) -> None:
        """Test ExecResult serialization round-trip."""
        original = ExecResult(
            exit_code=1,
            stdout="",
            stderr="command not found\n",
        )
        data = original.to_dict()
        restored = ExecResult.from_dict(data)

        assert restored.exit_code == original.exit_code
        assert restored.stdout == original.stdout
        assert restored.stderr == original.stderr

    def test_exec_result_with_nonzero_exit_code(self) -> None:
        """Test ExecResult with nonzero exit code."""
        msg = ExecResult(
            exit_code=127,
            stdout="",
            stderr="bash: foobar: command not found\n",
        )
        data = msg.to_dict()
        restored = ExecResult.from_dict(data)

        assert restored.exit_code == 127
        assert restored.stderr == "bash: foobar: command not found\n"

    def test_exec_result_with_multiline_output(self) -> None:
        """Test ExecResult with multiline stdout/stderr."""
        msg = ExecResult(
            exit_code=0,
            stdout="line 1\nline 2\nline 3\n",
            stderr="warning 1\nwarning 2\n",
        )
        data = msg.to_dict()
        restored = ExecResult.from_dict(data)

        assert restored.stdout == "line 1\nline 2\nline 3\n"
        assert restored.stderr == "warning 1\nwarning 2\n"


class TestSelfUpdateResult:
    """Tests for SelfUpdateResult message model."""

    def test_self_update_result_to_dict(self) -> None:
        """Test SelfUpdateResult serializes to correct dict."""
        msg = SelfUpdateResult(
            success=True,
            message="Updated from 0.10.5 to 0.10.6",
            old_version="0.10.5",
            new_version="0.10.6",
        )
        data = msg.to_dict()

        assert data["type"] == "self_update_result"
        assert data["success"] is True
        assert data["message"] == "Updated from 0.10.5 to 0.10.6"
        assert data["old_version"] == "0.10.5"
        assert data["new_version"] == "0.10.6"

    def test_self_update_result_from_dict(self) -> None:
        """Test SelfUpdateResult deserializes from dict."""
        data = {
            "success": True,
            "message": "Updated",
            "old_version": "0.10.5",
            "new_version": "0.10.6",
        }
        msg = SelfUpdateResult.from_dict(data)

        assert isinstance(msg, SelfUpdateResult)
        assert msg.success is True
        assert msg.old_version == "0.10.5"
        assert msg.new_version == "0.10.6"

    def test_self_update_result_round_trip(self) -> None:
        """Test SelfUpdateResult serialization round-trip."""
        original = SelfUpdateResult(
            success=True,
            message="Updated from 0.10.5 to 0.10.6",
            old_version="0.10.5",
            new_version="0.10.6",
        )
        data = original.to_dict()
        restored = SelfUpdateResult.from_dict(data)

        assert restored.success == original.success
        assert restored.message == original.message
        assert restored.old_version == original.old_version
        assert restored.new_version == original.new_version

    def test_self_update_result_failure(self) -> None:
        """Test SelfUpdateResult failure with no new_version."""
        msg = SelfUpdateResult(
            success=False,
            message="pip install failed: package not found",
            old_version="0.10.5",
        )
        data = msg.to_dict()

        assert data["success"] is False
        assert data["new_version"] is None

        restored = SelfUpdateResult.from_dict(data)
        assert restored.success is False
        assert restored.new_version is None

    def test_self_update_result_missing_new_version(self) -> None:
        """Test SelfUpdateResult deserializes when new_version is missing."""
        data = {
            "success": False,
            "message": "Failed",
            "old_version": "0.10.5",
        }
        msg = SelfUpdateResult.from_dict(data)

        assert msg.new_version is None
