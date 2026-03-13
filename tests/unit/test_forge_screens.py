"""Tests for forge screen integrations: DeviceInfoPanel and DeviceConsoleScreen."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from styrened.tui.models.fleet import Device
from styrened.tui.screens.device import DeviceInfoPanel, DeviceScreen
from styrened.tui.screens.device_console import DeviceConsoleScreen


def make_mock_device(**kwargs) -> Device:
    """Create a Device instance with sensible defaults."""
    defaults = {
        "name": "test-node",
        "profile": "node",
        "hardware": "rpi-zero2w",
        "status": "online",
        "last_seen": datetime(2026, 3, 13, 9, 0, 0),
        "reticulum_identity": "abc123def456",
        "ip_address": "10.0.0.1",
        "notes": None,
    }
    defaults.update(kwargs)
    return Device(**defaults)


class TestDeviceInfoPanel:
    """Tests for DeviceInfoPanel widget."""

    def test_can_be_instantiated_with_mock_device(self) -> None:
        """DeviceInfoPanel can be instantiated with a valid Device."""
        device = make_mock_device()
        panel = DeviceInfoPanel(device)
        assert panel.device is device

    def test_stores_device_reference(self) -> None:
        """DeviceInfoPanel stores the device reference exactly."""
        device = make_mock_device(name="my-node", profile="edge-router")
        panel = DeviceInfoPanel(device)
        assert panel.device.name == "my-node"
        assert panel.device.profile == "edge-router"

    def test_instantiation_with_optional_fields_none(self) -> None:
        """DeviceInfoPanel accepts device with no optional fields."""
        device = make_mock_device(
            ip_address=None,
            reticulum_identity=None,
            last_seen=None,
            notes=None,
        )
        panel = DeviceInfoPanel(device)
        assert panel.device.ip_address is None
        assert panel.device.reticulum_identity is None

    def test_format_status_online(self) -> None:
        """_format_status returns green markup for online status."""
        device = make_mock_device()
        panel = DeviceInfoPanel(device)
        result = panel._format_status("online")
        assert "green" in result
        assert "ONLINE" in result

    def test_format_status_offline(self) -> None:
        """_format_status returns red markup for offline status."""
        device = make_mock_device()
        panel = DeviceInfoPanel(device)
        result = panel._format_status("offline")
        assert "red" in result
        assert "OFFLINE" in result

    def test_format_status_unknown(self) -> None:
        """_format_status uses white for unknown statuses."""
        device = make_mock_device()
        panel = DeviceInfoPanel(device)
        result = panel._format_status("unknown-state")
        assert "white" in result


class TestDeviceConsoleScreen:
    """Tests for DeviceConsoleScreen class structure."""

    def test_class_exists(self) -> None:
        """DeviceConsoleScreen class is importable and is a Screen subclass."""
        from textual.screen import Screen

        assert issubclass(DeviceConsoleScreen, Screen)

    def test_has_expected_bindings(self) -> None:
        """DeviceConsoleScreen has escape and ctrl+l bindings."""
        keys = {b.key for b in DeviceConsoleScreen.BINDINGS}
        assert "escape" in keys
        assert "ctrl+l" in keys

    def test_can_be_instantiated_with_mock_rpc_client(self) -> None:
        """DeviceConsoleScreen can be instantiated with mock RPC client."""
        mock_client = MagicMock()
        screen = DeviceConsoleScreen(
            device_hash="aabbccddeeff0011",
            rpc_client=mock_client,
        )
        assert screen.device_hash == "aabbccddeeff0011"
        assert screen.rpc_client is mock_client

    def test_command_history_starts_empty(self) -> None:
        """DeviceConsoleScreen initializes with empty command history."""
        mock_client = MagicMock()
        screen = DeviceConsoleScreen(device_hash="abcdef", rpc_client=mock_client)
        assert screen.command_history == []

    def test_add_to_history_appends_entry(self) -> None:
        """_add_to_history stores command/response without Textual app running."""
        mock_client = MagicMock()
        screen = DeviceConsoleScreen(device_hash="abcdef", rpc_client=mock_client)
        # Patch _update_history_display to avoid Textual DOM calls
        screen._update_history_display = MagicMock()
        screen._add_to_history("status", "ip: 10.0.0.1")
        assert len(screen.command_history) == 1
        assert screen.command_history[0]["command"] == "status"
        assert screen.command_history[0]["response"] == "ip: 10.0.0.1"

    def test_history_capped_at_100(self) -> None:
        """_add_to_history caps history at 100 entries."""
        mock_client = MagicMock()
        screen = DeviceConsoleScreen(device_hash="abcdef", rpc_client=mock_client)
        screen._update_history_display = MagicMock()
        for i in range(150):
            screen._add_to_history(f"cmd{i}", f"response{i}")
        assert len(screen.command_history) == 100
        # Most recent entries should be kept
        assert screen.command_history[-1]["command"] == "cmd149"

    def test_format_status_response(self) -> None:
        """_format_status_response returns a readable string."""
        from styrened.rpc.messages import StatusResponse

        mock_client = MagicMock()
        screen = DeviceConsoleScreen(device_hash="abcdef", rpc_client=mock_client)

        status = StatusResponse(
            ip="10.0.0.5",
            uptime=3600,
            services=["styrened"],
            disk_used=1000,
            disk_total=10000,
        )
        result = screen._format_status_response(status)
        assert "10.0.0.5" in result
        assert "3600" in result or "1:00:00" in result

    def test_format_exec_result_success(self) -> None:
        """_format_exec_result includes stdout and exit code."""
        from styrened.rpc.messages import ExecResult

        mock_client = MagicMock()
        screen = DeviceConsoleScreen(device_hash="abcdef", rpc_client=mock_client)

        result = ExecResult(exit_code=0, stdout="hello\n", stderr="")
        text = screen._format_exec_result(result)
        assert "0" in text
        assert "hello" in text
        assert "Success" in text

    def test_format_reboot_result_success(self) -> None:
        """_format_reboot_result handles success."""
        from styrened.rpc.messages import RebootResult

        mock_client = MagicMock()
        screen = DeviceConsoleScreen(device_hash="abcdef", rpc_client=mock_client)

        result = RebootResult(success=True, message="Rebooting now", scheduled_time=None)
        text = screen._format_reboot_result(result)
        assert "Success" in text
        assert "Rebooting now" in text
