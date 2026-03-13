"""Tests for forge screen integrations: DeviceInfoPanel and DeviceConsoleScreen."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from textual.binding import Binding

from styrened.tui.models.fleet import Device, DeviceStatus
from styrened.tui.screens.device import DeviceInfoPanel, DeviceScreen
from styrened.tui.screens.device_console import DeviceConsoleScreen


def make_mock_device(
    name: str = "test-node",
    profile: str = "node",
    hardware: str = "rpi-zero2w",
    status: DeviceStatus = "online",
    last_seen: datetime | None = None,
    reticulum_identity: str | None = "abc123def456",
    ip_address: str | None = "10.0.0.1",
    notes: str | None = None,
) -> Device:
    """Create a Device instance with sensible defaults."""
    if last_seen is None:
        last_seen = datetime(2026, 3, 13, 9, 0, 0)
    return Device(
        name=name,
        profile=profile,
        hardware=hardware,
        status=status,
        last_seen=last_seen,
        reticulum_identity=reticulum_identity,
        ip_address=ip_address,
        notes=notes,
    )


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


class TestDeviceScreenLifecycle:
    """Tests for DeviceScreen compose/mount lifecycle."""

    def test_device_screen_constructed_with_device(self) -> None:
        """DeviceScreen accepts a Device object directly (C3 fix: no service I/O)."""
        device = make_mock_device(name="boot-node")
        screen = DeviceScreen(device=device)
        assert screen.device is device
        assert screen.device.name == "boot-node"

    def test_device_screen_stores_device(self) -> None:
        """DeviceScreen.device attribute holds the provided Device instance."""
        device = make_mock_device(name="relay-node", profile="hub")
        screen = DeviceScreen(device=device)
        assert screen.device.name == "relay-node"
        assert screen.device.profile == "hub"


class TestDeviceConsoleScreen:
    """Tests for DeviceConsoleScreen class structure."""

    def test_class_exists(self) -> None:
        """DeviceConsoleScreen class is importable and is a Screen subclass."""
        from textual.screen import Screen

        assert issubclass(DeviceConsoleScreen, Screen)

    def test_has_expected_bindings(self) -> None:
        """DeviceConsoleScreen has escape and ctrl+l bindings."""
        # BindingType = Binding | tuple[str, str] | tuple[str, str, str]
        # Normalise all forms safely: Binding has .key, tuple has [0] as str.
        def _key(b: object) -> str:
            if isinstance(b, Binding):
                return b.key
            if isinstance(b, tuple):
                return str(b[0])  # str() avoids [no-any-return] on tuple[0]
            return str(b)

        keys = {_key(b) for b in DeviceConsoleScreen.BINDINGS}
        assert "escape" in keys
        assert "ctrl+l" in keys

    def test_can_be_instantiated_with_device_hash(self) -> None:
        """DeviceConsoleScreen can be instantiated with only a device_hash (C4 fix)."""
        screen = DeviceConsoleScreen(device_hash="aabbccddeeff0011")
        assert screen.device_hash == "aabbccddeeff0011"

    def test_command_history_starts_empty(self) -> None:
        """DeviceConsoleScreen initializes with empty command history."""
        screen = DeviceConsoleScreen(device_hash="abcdef")
        assert screen.command_history == []

    def test_add_to_history_appends_entry(self) -> None:
        """_add_to_history stores command/response without Textual app running."""
        screen = DeviceConsoleScreen(device_hash="abcdef")
        with patch.object(screen, "_update_history_display"), \
             patch.object(screen, "query_one", side_effect=Exception("no app")):
            screen._add_to_history("status", "ip: 10.0.0.1")
        assert len(screen.command_history) == 1
        assert screen.command_history[0]["command"] == "status"
        assert screen.command_history[0]["response"] == "ip: 10.0.0.1"

    def test_history_capped_at_100(self) -> None:
        """_add_to_history caps history at 100 entries."""
        screen = DeviceConsoleScreen(device_hash="abcdef")
        with patch.object(screen, "query_one", side_effect=Exception("no app")):
            for i in range(150):
                screen._add_to_history(f"cmd{i}", f"response{i}")
        assert len(screen.command_history) == 100
        assert screen.command_history[-1]["command"] == "cmd149"

    def test_format_status_response(self) -> None:
        """_format_status_response returns a readable string."""
        from styrened.rpc.messages import StatusResponse

        screen = DeviceConsoleScreen(device_hash="abcdef")

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

        screen = DeviceConsoleScreen(device_hash="abcdef")

        result = ExecResult(exit_code=0, stdout="hello\n", stderr="")
        text = screen._format_exec_result(result)
        assert "0" in text
        assert "hello" in text
        assert "Success" in text

    def test_format_reboot_result_success(self) -> None:
        """_format_reboot_result handles success."""
        from styrened.rpc.messages import RebootResult

        screen = DeviceConsoleScreen(device_hash="abcdef")

        result = RebootResult(success=True, message="Rebooting now", scheduled_time=None)
        text = screen._format_reboot_result(result)
        assert "Success" in text
        assert "Rebooting now" in text
