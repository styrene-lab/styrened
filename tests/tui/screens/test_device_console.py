"""Tests for Device Console Screen."""

from unittest.mock import AsyncMock

import pytest

from styrened.rpc.messages import (
    ExecResult,
    RebootResult,
    StatusResponse,
    UpdateConfigResult,
)
from styrened.tui.screens.device_console import DeviceConsoleScreen
from styrened.rpc.errors import RPCTimeoutError


@pytest.fixture
def mock_rpc_client() -> AsyncMock:
    """Create mock RPC client."""
    client = AsyncMock()

    # Mock status response
    client.call_status.return_value = StatusResponse(
        uptime=3600,
        ip="192.168.1.100",
        services=["reticulum", "lxmf"],
        disk_used=50_000,
        disk_total=100_000,
    )

    # Mock exec result
    client.call_exec.return_value = ExecResult(
        exit_code=0,
        stdout="Hello World\n",
        stderr="",
    )

    # Mock reboot result
    client.call_reboot.return_value = RebootResult(
        success=True,
        message="Reboot scheduled",
        scheduled_time=None,
    )

    # Mock update_config result
    client.call_update_config.return_value = UpdateConfigResult(
        success=True,
        message="Configuration updated",
        updated_keys=["test_key"],
    )

    return client


class TestDeviceConsoleScreenInitialization:
    """Test screen initialization."""

    def test_create_screen(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should initialize with device hash and RPC client."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        assert screen.device_hash == "test_device_hash_123"
        assert screen.rpc_client is mock_rpc_client
        assert screen.command_history == []

    def test_screen_has_bindings(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should have escape and clear bindings."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        binding_keys = [b.key for b in screen.BINDINGS]
        assert "escape" in binding_keys
        assert "ctrl+l" in binding_keys


class TestImperialCRTTheme:
    """Test Imperial CRT theme application."""

    def test_screen_has_imperial_crt_css(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should define Imperial CRT theme CSS."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        assert hasattr(screen, "CSS")
        assert "#39ff14" in screen.CSS  # Imperial green
        assert "#0a0a0a" in screen.CSS  # Black background


class TestCommandParsing:
    """Test command parsing and execution."""

    @pytest.mark.asyncio
    async def test_parse_status_command(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should parse 'status' command."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("status")

        mock_rpc_client.call_status.assert_called_once_with(
            "test_device_hash_123", timeout=30.0
        )

    @pytest.mark.asyncio
    async def test_parse_exec_command(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should parse 'exec <cmd> <args>' command."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("exec echo Hello World")

        mock_rpc_client.call_exec.assert_called_once_with(
            "test_device_hash_123",
            command="echo",
            args=["Hello", "World"],
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_parse_reboot_command_no_delay(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should parse 'reboot' command without delay."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("reboot")

        mock_rpc_client.call_reboot.assert_called_once_with(
            "test_device_hash_123",
            delay=0,
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_parse_reboot_command_with_delay(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should parse 'reboot <delay>' command."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("reboot 300")

        mock_rpc_client.call_reboot.assert_called_once_with(
            "test_device_hash_123",
            delay=300,
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_parse_update_config_command(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should parse 'update-config <key> <value>' command."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("update-config log_level DEBUG")

        mock_rpc_client.call_update_config.assert_called_once_with(
            "test_device_hash_123",
            config_updates={"log_level": "DEBUG"},
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_invalid_command_shows_error(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should show error for invalid command."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("invalid_command")

        # Should not call any RPC methods
        mock_rpc_client.call_status.assert_not_called()
        mock_rpc_client.call_exec.assert_not_called()
        mock_rpc_client.call_reboot.assert_not_called()
        mock_rpc_client.call_update_config.assert_not_called()

        # Should add error to history
        assert len(screen.command_history) == 1
        assert "Unknown command" in screen.command_history[0]["response"]


class TestCommandHistory:
    """Test command history tracking."""

    @pytest.mark.asyncio
    async def test_command_history_records_status(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should record status command in history."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("status")

        assert len(screen.command_history) == 1
        assert screen.command_history[0]["command"] == "status"
        assert "response" in screen.command_history[0]

    @pytest.mark.asyncio
    async def test_command_history_records_exec(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should record exec command in history."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("exec echo test")

        assert len(screen.command_history) == 1
        assert screen.command_history[0]["command"] == "exec echo test"
        assert "Hello World" in screen.command_history[0]["response"]

    @pytest.mark.asyncio
    async def test_command_history_limits_to_100(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should limit history to last 100 entries."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        # Execute 150 commands
        for _i in range(150):
            await screen._execute_command("status")

        # Should only keep last 100
        assert len(screen.command_history) == 100


class TestErrorHandling:
    """Test RPC error handling."""

    @pytest.mark.asyncio
    async def test_handle_rpc_timeout(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should handle RPC timeout errors gracefully."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        # Mock timeout error
        mock_rpc_client.call_status.side_effect = RPCTimeoutError(
            "Request timed out after 30 seconds",
            request_id="req-123",
            destination="test_device_hash_123",
            timeout=30.0,
        )

        await screen._execute_command("status")

        # Should record error in history
        assert len(screen.command_history) == 1
        assert "timed out" in screen.command_history[0]["response"].lower()

    @pytest.mark.asyncio
    async def test_handle_authorization_denied(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should handle authorization denial."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        # Mock authorization denial (ExecResult with failure)
        mock_rpc_client.call_exec.return_value = ExecResult(
            exit_code=-1,
            stdout="",
            stderr="Unauthorized: exec denied",
        )

        await screen._execute_command("exec systemctl status")

        # Should record denial in history
        assert len(screen.command_history) == 1
        assert "Unauthorized" in screen.command_history[0]["response"]

    @pytest.mark.asyncio
    async def test_handle_generic_exception(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should handle generic exceptions gracefully."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        # Mock generic exception
        mock_rpc_client.call_status.side_effect = Exception("Network error")

        await screen._execute_command("status")

        # Should record error in history
        assert len(screen.command_history) == 1
        assert "error" in screen.command_history[0]["response"].lower()


class TestResponseDisplay:
    """Test response formatting and display."""

    @pytest.mark.asyncio
    async def test_format_status_response(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should format status response correctly."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("status")

        response = screen.command_history[0]["response"]
        assert "192.168.1.100" in response  # IP address
        assert "3600" in response or "1h" in response  # Uptime
        assert "reticulum" in response.lower()  # Service name
        assert "50" in response  # Disk usage

    @pytest.mark.asyncio
    async def test_format_exec_result_success(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should format exec success result."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("exec echo test")

        response = screen.command_history[0]["response"]
        assert "Hello World" in response
        assert "exit code: 0" in response.lower() or "success" in response.lower()

    @pytest.mark.asyncio
    async def test_format_exec_result_failure(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should format exec failure result."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        # Mock failure
        mock_rpc_client.call_exec.return_value = ExecResult(
            exit_code=1,
            stdout="",
            stderr="Command failed",
        )

        await screen._execute_command("exec false")

        response = screen.command_history[0]["response"]
        assert "Command failed" in response
        assert "exit code: 1" in response.lower() or "failed" in response.lower()

    @pytest.mark.asyncio
    async def test_format_reboot_result(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should format reboot result."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("reboot")

        response = screen.command_history[0]["response"]
        assert "Reboot scheduled" in response or "success" in response.lower()

    @pytest.mark.asyncio
    async def test_format_update_config_result(self, mock_rpc_client: AsyncMock) -> None:
        """DeviceConsoleScreen should format update-config result."""
        screen = DeviceConsoleScreen(
            device_hash="test_device_hash_123",
            rpc_client=mock_rpc_client,
        )

        await screen._execute_command("update-config log_level DEBUG")

        response = screen.command_history[0]["response"]
        assert "Configuration updated" in response or "success" in response.lower()
        assert "test_key" in response  # Updated key
