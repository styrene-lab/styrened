"""Unit tests for RPC server command execution and security.

Tests the critical security path for command execution whitelist validation,
timeout handling, error conditions, authorization, rate limiting, and replay protection.
"""

import asyncio
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.styrene_wire import (
    StyreneEnvelope,
    StyreneMessageType,
    encode_payload,
    generate_request_id,
)
from styrened.rpc.server import (
    DANGEROUS_RPC_COMMANDS,
    DEFAULT_ALLOWED_COMMANDS,
    DEFAULT_RPC_RATE_LIMIT,
    MAX_RECENT_REQUEST_IDS,
    PUBLIC_RPC_COMMANDS,
    RATE_LIMIT_WINDOW_SECONDS,
    REQUEST_ID_EXPIRY_SECONDS,
    RPCServer,
)


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


class TestAuthorization:
    """Tests for RPC authorization security."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    def test_is_authorized_allows_known_identity(self, mock_protocol: MagicMock) -> None:
        """Known identity in authorized set should be allowed."""
        server = RPCServer(
            mock_protocol,
            authorized_identities={"abc123", "def456"},
        )

        assert server._is_authorized("abc123") is True
        assert server._is_authorized("def456") is True

    def test_is_authorized_rejects_unknown_identity(self, mock_protocol: MagicMock) -> None:
        """Unknown identity should be rejected when authorized set is non-empty."""
        server = RPCServer(
            mock_protocol,
            authorized_identities={"abc123"},
        )

        assert server._is_authorized("unknown_hash") is False
        assert server._is_authorized("def456") is False

    def test_empty_authorized_identities_allows_all(self, mock_protocol: MagicMock) -> None:
        """Empty authorized set allows all identities (with warning logged at init)."""
        server = RPCServer(mock_protocol, authorized_identities=set())

        # Any identity should be allowed when no authorization configured
        assert server._is_authorized("any_hash") is True
        assert server._is_authorized("another_hash") is True

    def test_none_authorized_identities_allows_all(self, mock_protocol: MagicMock) -> None:
        """None authorized_identities (default) allows all identities."""
        server = RPCServer(mock_protocol)

        assert server._is_authorized("any_hash") is True

    def test_authorization_file_loading_valid_format(self, mock_protocol: MagicMock) -> None:
        """Authorized identities should be loaded from file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("abc123\n")
            f.write("def456\n")
            f.write("ghi789\n")
            f.flush()

            server = RPCServer(
                mock_protocol,
                authorized_identities_file=Path(f.name),
            )

            assert "abc123" in server._authorized_identities
            assert "def456" in server._authorized_identities
            assert "ghi789" in server._authorized_identities
            assert len(server._authorized_identities) == 3

    def test_authorization_file_loading_with_comments(self, mock_protocol: MagicMock) -> None:
        """Comments and empty lines should be ignored in auth file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("# This is a comment\n")
            f.write("abc123\n")
            f.write("\n")
            f.write("# Another comment\n")
            f.write("def456  # inline comment ignored (takes first token)\n")
            f.write("   \n")
            f.flush()

            server = RPCServer(
                mock_protocol,
                authorized_identities_file=Path(f.name),
            )

            assert "abc123" in server._authorized_identities
            assert "def456" in server._authorized_identities
            assert len(server._authorized_identities) == 2

    def test_authorization_file_missing_handled_gracefully(self, mock_protocol: MagicMock) -> None:
        """Missing authorization file should not crash, just log warning."""
        server = RPCServer(
            mock_protocol,
            authorized_identities_file=Path("/nonexistent/path/identities.txt"),
        )

        # Server should be created, just with empty authorized set
        assert len(server._authorized_identities) == 0

    def test_authorization_combined_file_and_set(self, mock_protocol: MagicMock) -> None:
        """File identities should be added to existing authorized set."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("file_identity\n")
            f.flush()

            server = RPCServer(
                mock_protocol,
                authorized_identities={"preset_identity"},
                authorized_identities_file=Path(f.name),
            )

            assert "preset_identity" in server._authorized_identities
            assert "file_identity" in server._authorized_identities

    def test_public_commands_constant(self) -> None:
        """PUBLIC_RPC_COMMANDS should contain only safe read-only commands."""
        assert StyreneMessageType.PING in PUBLIC_RPC_COMMANDS
        assert StyreneMessageType.STATUS_REQUEST in PUBLIC_RPC_COMMANDS
        # Dangerous commands should NOT be public
        assert StyreneMessageType.EXEC not in PUBLIC_RPC_COMMANDS
        assert StyreneMessageType.REBOOT not in PUBLIC_RPC_COMMANDS
        assert StyreneMessageType.CONFIG_UPDATE not in PUBLIC_RPC_COMMANDS

    def test_dangerous_commands_constant(self) -> None:
        """DANGEROUS_RPC_COMMANDS should contain commands requiring explicit enable."""
        assert StyreneMessageType.EXEC in DANGEROUS_RPC_COMMANDS
        assert StyreneMessageType.REBOOT in DANGEROUS_RPC_COMMANDS
        assert StyreneMessageType.CONFIG_UPDATE in DANGEROUS_RPC_COMMANDS
        # Safe commands should NOT be dangerous
        assert StyreneMessageType.PING not in DANGEROUS_RPC_COMMANDS
        assert StyreneMessageType.STATUS_REQUEST not in DANGEROUS_RPC_COMMANDS

    def test_dangerous_commands_disabled_by_default(self, mock_protocol: MagicMock) -> None:
        """Dangerous commands should be disabled by default."""
        server = RPCServer(mock_protocol)
        assert server._enable_dangerous_commands is False

    def test_dangerous_commands_can_be_enabled(self, mock_protocol: MagicMock) -> None:
        """Dangerous commands can be explicitly enabled."""
        server = RPCServer(mock_protocol, enable_dangerous_commands=True)
        assert server._enable_dangerous_commands is True


class TestRateLimiting:
    """Tests for RPC rate limiting security."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    def test_rate_limit_first_request_allowed(self, mock_protocol: MagicMock) -> None:
        """First request from any identity should be allowed."""
        server = RPCServer(mock_protocol, rate_limit=10)

        result = server._check_rate_limit("abc123")
        assert result is None  # None means allowed

    def test_rate_limit_within_limit_allowed(self, mock_protocol: MagicMock) -> None:
        """Requests within rate limit should be allowed."""
        server = RPCServer(mock_protocol, rate_limit=5)

        # Make 5 requests (at limit)
        for i in range(5):
            result = server._check_rate_limit("abc123")
            assert result is None, f"Request {i + 1} should be allowed"

    def test_rate_limit_exceeded_rejected(self, mock_protocol: MagicMock) -> None:
        """Requests exceeding rate limit should be rejected."""
        server = RPCServer(mock_protocol, rate_limit=3)

        # Make 3 requests (at limit)
        for _ in range(3):
            server._check_rate_limit("abc123")

        # 4th request should be rejected
        result = server._check_rate_limit("abc123")
        assert result is not None
        assert "Rate limit exceeded" in result

    def test_rate_limit_per_identity_isolation(self, mock_protocol: MagicMock) -> None:
        """Rate limits should be tracked per identity."""
        server = RPCServer(mock_protocol, rate_limit=2)

        # Identity A makes 2 requests
        server._check_rate_limit("identity_a")
        server._check_rate_limit("identity_a")

        # Identity A is now rate limited
        assert server._check_rate_limit("identity_a") is not None

        # Identity B should still be allowed
        assert server._check_rate_limit("identity_b") is None
        assert server._check_rate_limit("identity_b") is None

    def test_rate_limit_window_expiration(self, mock_protocol: MagicMock) -> None:
        """Requests should be allowed after rate limit window expires."""
        server = RPCServer(mock_protocol, rate_limit=1)

        # Make request
        server._check_rate_limit("abc123")

        # Immediately rate limited
        assert server._check_rate_limit("abc123") is not None

        # Simulate time passing beyond window
        # Manually set old timestamp
        old_time = time.time() - RATE_LIMIT_WINDOW_SECONDS - 1
        server._request_timestamps["abc123"] = [old_time]

        # Should be allowed now (old timestamp cleaned up)
        result = server._check_rate_limit("abc123")
        assert result is None

    def test_rate_limit_timestamp_cleanup(self, mock_protocol: MagicMock) -> None:
        """Old timestamps should be cleaned up on each check."""
        server = RPCServer(mock_protocol, rate_limit=10)

        # Add old timestamps manually
        old_time = time.time() - RATE_LIMIT_WINDOW_SECONDS - 10
        server._request_timestamps["abc123"] = [old_time] * 100

        # Check should clean up old timestamps
        server._check_rate_limit("abc123")

        # Old timestamps should be removed
        assert len(server._request_timestamps.get("abc123", [])) <= 1

    def test_rate_limit_default_value(self, mock_protocol: MagicMock) -> None:
        """Default rate limit should match constant."""
        server = RPCServer(mock_protocol)
        assert server._rate_limit == DEFAULT_RPC_RATE_LIMIT

    def test_rate_limit_custom_value(self, mock_protocol: MagicMock) -> None:
        """Custom rate limit should be respected."""
        server = RPCServer(mock_protocol, rate_limit=100)
        assert server._rate_limit == 100


class TestReplayProtection:
    """Tests for RPC replay protection security."""

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

    def test_first_request_id_not_replay(self, server: RPCServer) -> None:
        """First occurrence of a request_id should not be detected as replay."""
        request_id = generate_request_id()

        is_replay = server._is_replay(request_id)
        assert is_replay is False

    def test_duplicate_request_id_is_replay(self, server: RPCServer) -> None:
        """Same request_id sent twice should be detected as replay."""
        request_id = generate_request_id()

        # First request - not a replay
        assert server._is_replay(request_id) is False

        # Same request_id again - IS a replay
        assert server._is_replay(request_id) is True

    def test_different_request_ids_allowed(self, server: RPCServer) -> None:
        """Different request_ids should all be allowed."""
        request_id_1 = generate_request_id()
        request_id_2 = generate_request_id()
        request_id_3 = generate_request_id()

        assert server._is_replay(request_id_1) is False
        assert server._is_replay(request_id_2) is False
        assert server._is_replay(request_id_3) is False

    def test_replay_window_expiration(self, server: RPCServer) -> None:
        """Request_id should be allowed after expiry window."""
        request_id = generate_request_id()

        # First request
        assert server._is_replay(request_id) is False

        # Simulate time passing beyond expiry
        old_time = time.time() - REQUEST_ID_EXPIRY_SECONDS - 1
        server._recent_request_ids[request_id] = old_time

        # Should be allowed now (expired entry)
        assert server._is_replay(request_id) is False

    def test_replay_cache_cleanup_on_overflow(self, server: RPCServer) -> None:
        """Cache should be cleaned when it exceeds max size."""
        # Fill cache beyond max
        for i in range(MAX_RECENT_REQUEST_IDS + 100):
            request_id = f"request_{i}".encode()
            server._recent_request_ids[request_id] = time.time()

        # Trigger cleanup by checking a new request
        new_request = generate_request_id()
        server._is_replay(new_request)

        # Cache should have been pruned
        assert len(server._recent_request_ids) <= MAX_RECENT_REQUEST_IDS

    def test_replay_cache_removes_expired_first(self, server: RPCServer) -> None:
        """Cleanup should remove expired entries first."""
        # Add some expired entries
        old_time = time.time() - REQUEST_ID_EXPIRY_SECONDS - 10
        for i in range(50):
            server._recent_request_ids[f"old_{i}".encode()] = old_time

        # Add some fresh entries
        current_time = time.time()
        for i in range(50):
            server._recent_request_ids[f"new_{i}".encode()] = current_time

        # Force overflow to trigger cleanup
        for i in range(MAX_RECENT_REQUEST_IDS):
            server._recent_request_ids[f"overflow_{i}".encode()] = current_time

        # Trigger cleanup
        server._is_replay(generate_request_id())

        # Old entries should be gone, new ones should remain
        old_keys = [k for k in server._recent_request_ids if k.startswith(b"old_")]
        assert len(old_keys) == 0

    def test_replay_protection_constants(self) -> None:
        """Verify replay protection constants are reasonable."""
        # Should track enough request IDs
        assert MAX_RECENT_REQUEST_IDS >= 100

        # Expiry should be reasonable (not too short, not too long)
        assert 60 <= REQUEST_ID_EXPIRY_SECONDS <= 600


class TestSecurityIntegration:
    """Integration tests for security checks in protocol handler."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_dangerous_command_rejected_when_disabled(self, mock_protocol: MagicMock) -> None:
        """Dangerous commands should be rejected when not enabled."""
        server = RPCServer(
            mock_protocol,
            enable_dangerous_commands=False,  # Default
            authorized_identities={"abc123"},
        )
        server.start()

        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.EXEC,
            payload=encode_payload({"command": "uptime", "args": []}),
            request_id=request_id,
        )

        message = MagicMock()
        message.source_hash = "abc123"

        await server._protocol_handler(message, envelope)

        # Should send error response
        mock_protocol.send_typed_message.assert_called()
        call_args = mock_protocol.send_typed_message.call_args
        assert call_args.kwargs["message_type"] == StyreneMessageType.ERROR

    @pytest.mark.asyncio
    async def test_unauthorized_command_rejected(self, mock_protocol: MagicMock) -> None:
        """Non-public commands should be rejected for unauthorized identities."""
        server = RPCServer(
            mock_protocol,
            authorized_identities={"authorized_id"},
            enable_dangerous_commands=True,
        )
        server.start()

        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.EXEC,
            payload=encode_payload({"command": "uptime", "args": []}),
            request_id=request_id,
        )

        message = MagicMock()
        message.source_hash = "unauthorized_id"

        await server._protocol_handler(message, envelope)

        # Should send error response
        mock_protocol.send_typed_message.assert_called()
        call_args = mock_protocol.send_typed_message.call_args
        assert call_args.kwargs["message_type"] == StyreneMessageType.ERROR

    @pytest.mark.asyncio
    async def test_public_command_allowed_without_auth(self, mock_protocol: MagicMock) -> None:
        """Public commands should be allowed without authorization."""
        server = RPCServer(
            mock_protocol,
            authorized_identities={"some_other_id"},  # Not the requester
        )
        server.start()

        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.PING,
            payload=b"",
            request_id=request_id,
        )

        message = MagicMock()
        message.source_hash = "unauthorized_but_public_ok"

        await server._protocol_handler(message, envelope)

        # Allow async task to complete
        await asyncio.sleep(0.1)

        # Should send PONG response (not error)
        mock_protocol.send_typed_message.assert_called()
        call_args = mock_protocol.send_typed_message.call_args
        assert call_args.kwargs["message_type"] == StyreneMessageType.PONG

    @pytest.mark.asyncio
    async def test_rate_limited_request_rejected(self, mock_protocol: MagicMock) -> None:
        """Rate limited requests should be rejected."""
        server = RPCServer(
            mock_protocol,
            rate_limit=1,  # Very low limit for testing
        )
        server.start()

        message = MagicMock()
        message.source_hash = "abc123"

        # First request - allowed
        envelope1 = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.PING,
            payload=b"",
            request_id=generate_request_id(),
        )
        await server._protocol_handler(message, envelope1)
        await asyncio.sleep(0.1)

        # Reset mock to check second call
        mock_protocol.send_typed_message.reset_mock()

        # Second request - should be rate limited
        envelope2 = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.PING,
            payload=b"",
            request_id=generate_request_id(),
        )
        await server._protocol_handler(message, envelope2)

        # Should send error response for rate limit
        mock_protocol.send_typed_message.assert_called()
        call_args = mock_protocol.send_typed_message.call_args
        assert call_args.kwargs["message_type"] == StyreneMessageType.ERROR

    @pytest.mark.asyncio
    async def test_replay_request_silently_dropped(self, mock_protocol: MagicMock) -> None:
        """Replay requests should be silently dropped (no error response)."""
        server = RPCServer(
            mock_protocol,
            authorized_identities={"abc123"},
            enable_dangerous_commands=True,
        )
        server.start()

        request_id = generate_request_id()
        message = MagicMock()
        message.source_hash = "abc123"

        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.EXEC,
            payload=encode_payload({"command": "uptime", "args": []}),
            request_id=request_id,
        )

        # First request - should be processed
        with patch.object(server, "_execute_command") as mock_exec:
            mock_exec.return_value = {"exit_code": 0, "stdout": "", "stderr": ""}
            await server._protocol_handler(message, envelope)
            await asyncio.sleep(0.1)

        # Reset mock
        mock_protocol.send_typed_message.reset_mock()

        # Replay same request_id - should be silently dropped
        await server._protocol_handler(message, envelope)

        # No response should be sent for replays (avoids amplification)
        mock_protocol.send_typed_message.assert_not_called()
