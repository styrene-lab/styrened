"""Unit tests for RPC server command execution and security.

Tests the critical security path for command execution whitelist validation,
timeout handling, and error conditions.
"""

import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.styrene_wire import (
    StyreneEnvelope,
    StyreneMessageType,
    encode_payload,
    generate_request_id,
)
from styrened.rpc.server import DEFAULT_ALLOWED_COMMANDS, RPCServer


class TestCommandWhitelist:
    """Tests for command whitelist security validation."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.fixture
    def server(self, mock_protocol: MagicMock) -> RPCServer:
        """Create an RPCServer with mock protocol."""
        return RPCServer(mock_protocol)

    def test_allowed_command_executes(self, server: RPCServer) -> None:
        """Whitelisted command should execute successfully."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="hello",
                stderr="",
            )

            result = server._execute_command("echo", ["hello"])

            assert result["exit_code"] == 0
            assert result["stdout"] == "hello"
            assert result["stderr"] == ""
            mock_run.assert_called_once_with(
                ["echo", "hello"],
                capture_output=True,
                text=True,
                timeout=30,
            )

    def test_disallowed_command_rejected(self, server: RPCServer) -> None:
        """Command not in whitelist should be rejected with exit code 126."""
        result = server._execute_command("rm", ["-rf", "/"])

        assert result["exit_code"] == 126
        assert "not allowed" in result["stderr"].lower()
        assert result["stdout"] == ""

    def test_disallowed_command_no_subprocess_call(self, server: RPCServer) -> None:
        """Disallowed commands should never invoke subprocess."""
        with patch("subprocess.run") as mock_run:
            server._execute_command("malicious_script", ["--evil"])
            mock_run.assert_not_called()

    def test_command_not_found_returns_127(self, server: RPCServer) -> None:
        """Non-existent command should return exit code 127."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("Command not found")

            # Need to add the command to allowed list first
            server.allowed_commands.add("nonexistent_cmd")
            result = server._execute_command("nonexistent_cmd", [])

            assert result["exit_code"] == 127
            assert "not found" in result["stderr"].lower()

    def test_command_timeout_returns_124(self, server: RPCServer) -> None:
        """Command that times out should return exit code 124."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep", timeout=30)

            result = server._execute_command("uptime", [])

            assert result["exit_code"] == 124
            assert "timed out" in result["stderr"].lower()

    def test_command_generic_error_returns_1(self, server: RPCServer) -> None:
        """Generic subprocess error should return exit code 1."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = OSError("Permission denied")

            result = server._execute_command("ls", ["-la"])

            assert result["exit_code"] == 1
            assert "Permission denied" in result["stderr"]

    def test_default_allowed_commands_includes_safe_commands(self) -> None:
        """Default whitelist should include expected safe commands."""
        expected_commands = {
            "systemctl",
            "df",
            "free",
            "uptime",
            "hostname",
            "uname",
            "cat",
            "ls",
            "ps",
            "date",
            "whoami",
            "echo",
            "rnstatus",
        }
        assert expected_commands.issubset(DEFAULT_ALLOWED_COMMANDS)

    def test_default_allowed_commands_excludes_dangerous(self) -> None:
        """Default whitelist should not include dangerous commands."""
        dangerous_commands = {
            "rm",
            "dd",
            "mkfs",
            "fdisk",
            "shutdown",
            "reboot",  # reboot is handled via RPC, not subprocess
            "chmod",
            "chown",
            "passwd",
            "useradd",
            "userdel",
            "curl",
            "wget",
            "bash",
            "sh",
            "python",
            "perl",
        }
        for cmd in dangerous_commands:
            assert cmd not in DEFAULT_ALLOWED_COMMANDS, f"{cmd} should not be allowed"

    def test_custom_allowed_commands_override(self, mock_protocol: MagicMock) -> None:
        """Custom allowed_commands should override defaults."""
        custom_commands = {"custom_cmd", "another_cmd"}
        server = RPCServer(mock_protocol, allowed_commands=custom_commands)

        # Custom command should be allowed
        assert "custom_cmd" in server.allowed_commands

        # Default commands should not be present
        assert "systemctl" not in server.allowed_commands


class TestExecHandler:
    """Tests for EXEC request handling."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.fixture
    def server(self, mock_protocol: MagicMock) -> RPCServer:
        """Create a started RPCServer with mock protocol."""
        server = RPCServer(mock_protocol)
        server.start()
        return server

    @pytest.mark.asyncio
    async def test_exec_sends_result(self, server: RPCServer, mock_protocol: MagicMock) -> None:
        """EXEC should send result back to source."""
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.EXEC,
            payload=encode_payload({"command": "uptime", "args": []}),
            request_id=request_id,
        )

        with patch.object(server, "_execute_command") as mock_exec:
            mock_exec.return_value = {
                "exit_code": 0,
                "stdout": " 10:30:00 up 5 days",
                "stderr": "",
            }

            # Trigger handler
            server._handle_exec("abc123", envelope)

            # Allow async task to complete
            await asyncio.sleep(0.1)

            # Verify response was sent
            mock_protocol.send_typed_message.assert_called()
            call_args = mock_protocol.send_typed_message.call_args
            assert call_args.kwargs["destination"] == "abc123"
            assert call_args.kwargs["message_type"] == StyreneMessageType.EXEC_RESULT
            assert call_args.kwargs["request_id"] == request_id

    @pytest.mark.asyncio
    async def test_exec_invalid_payload_sends_error(
        self, server: RPCServer, mock_protocol: MagicMock
    ) -> None:
        """Invalid EXEC payload should send error response."""
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.EXEC,
            payload=b"\xff\xff\xff",  # Invalid msgpack
            request_id=request_id,
        )

        # Trigger handler
        server._handle_exec("abc123", envelope)

        # Allow async task to complete
        await asyncio.sleep(0.1)

        # Verify error was sent
        mock_protocol.send_typed_message.assert_called()
        call_args = mock_protocol.send_typed_message.call_args
        assert call_args.kwargs["message_type"] == StyreneMessageType.ERROR


class TestServerLifecycle:
    """Tests for server start/stop lifecycle."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        return mock

    def test_server_starts_and_stops(self, mock_protocol: MagicMock) -> None:
        """Server should track running state."""
        server = RPCServer(mock_protocol)

        assert not server._running

        server.start()
        assert server._running

        server.stop()
        assert not server._running

    def test_double_start_is_safe(self, mock_protocol: MagicMock) -> None:
        """Starting an already-running server should be idempotent."""
        server = RPCServer(mock_protocol)

        server.start()
        server.start()  # Should not raise
        assert server._running

    def test_stopped_server_ignores_messages(self, mock_protocol: MagicMock) -> None:
        """Stopped server should not process messages."""
        server = RPCServer(mock_protocol)
        # Don't start the server

        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=generate_request_id(),
        )

        message = MagicMock()
        message.source_hash = "abc123"

        # Handler should return early without processing
        # This is an async function, but we're testing that it returns early
        with patch.object(server, "_handle_status_request") as mock_handler:
            asyncio.run(server._protocol_handler(message, envelope))
            mock_handler.assert_not_called()


class TestStatusRequest:
    """Tests for STATUS_REQUEST handling."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.fixture
    def server(self, mock_protocol: MagicMock) -> RPCServer:
        """Create a started RPCServer with mock protocol."""
        server = RPCServer(mock_protocol)
        server.start()
        return server

    def test_gather_status_returns_required_fields(self, server: RPCServer) -> None:
        """_gather_status should return all required fields."""
        status = server._gather_status()

        assert "uptime" in status
        assert "ip" in status
        assert "services" in status
        assert "disk_used" in status
        assert "disk_total" in status

        # Types should be correct
        assert isinstance(status["uptime"], int)
        assert isinstance(status["ip"], str)
        assert isinstance(status["services"], list)
        assert isinstance(status["disk_used"], int)
        assert isinstance(status["disk_total"], int)

    @pytest.mark.asyncio
    async def test_status_request_sends_response(
        self, server: RPCServer, mock_protocol: MagicMock
    ) -> None:
        """STATUS_REQUEST should send STATUS_RESPONSE."""
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=request_id,
        )

        server._handle_status_request("abc123", envelope)

        # Allow async task to complete
        await asyncio.sleep(0.1)

        mock_protocol.send_typed_message.assert_called()
        call_args = mock_protocol.send_typed_message.call_args
        assert call_args.kwargs["destination"] == "abc123"
        assert call_args.kwargs["message_type"] == StyreneMessageType.STATUS_RESPONSE
        assert call_args.kwargs["request_id"] == request_id


class TestRebootHandler:
    """Tests for REBOOT request handling."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.fixture
    def server(self, mock_protocol: MagicMock) -> RPCServer:
        """Create a started RPCServer with mock protocol."""
        server = RPCServer(mock_protocol)
        server.start()
        return server

    def test_schedule_reboot_immediate(self, server: RPCServer) -> None:
        """Immediate reboot should be scheduled for 5 seconds."""
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.call_later = MagicMock()

            result = server._schedule_reboot(0)

            assert result["success"] is True
            assert "5 seconds" in result["message"]
            assert result["scheduled_time"] is not None
            mock_loop.return_value.call_later.assert_called_once()
            # Verify it was scheduled for 5 seconds
            call_args = mock_loop.return_value.call_later.call_args
            assert call_args[0][0] == 5

    def test_schedule_reboot_delayed(self, server: RPCServer) -> None:
        """Delayed reboot should be scheduled for specified time."""
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.return_value.call_later = MagicMock()

            result = server._schedule_reboot(60)

            assert result["success"] is True
            assert "60 seconds" in result["message"]
            mock_loop.return_value.call_later.assert_called_once()
            call_args = mock_loop.return_value.call_later.call_args
            assert call_args[0][0] == 60

    def test_schedule_reboot_error(self, server: RPCServer) -> None:
        """Reboot scheduling error should return failure result."""
        with patch("asyncio.get_event_loop") as mock_loop:
            mock_loop.side_effect = RuntimeError("No event loop")

            result = server._schedule_reboot(0)

            assert result["success"] is False
            assert "Failed" in result["message"]
            assert result["scheduled_time"] is None


class TestPingHandler:
    """Tests for PING/PONG handling."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.fixture
    def server(self, mock_protocol: MagicMock) -> RPCServer:
        """Create a started RPCServer with mock protocol."""
        server = RPCServer(mock_protocol)
        server.start()
        return server

    @pytest.mark.asyncio
    async def test_ping_sends_pong(self, server: RPCServer, mock_protocol: MagicMock) -> None:
        """PING should respond with PONG."""
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.PING,
            payload=b"",
            request_id=request_id,
        )

        server._handle_ping("abc123", envelope)

        # Allow async task to complete
        await asyncio.sleep(0.1)

        mock_protocol.send_typed_message.assert_called()
        call_args = mock_protocol.send_typed_message.call_args
        assert call_args.kwargs["destination"] == "abc123"
        assert call_args.kwargs["message_type"] == StyreneMessageType.PONG
        assert call_args.kwargs["request_id"] == request_id
