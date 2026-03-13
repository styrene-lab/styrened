"""Tests for forge screen integrations: DeviceInfoPanel and DeviceConsoleScreen."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from textual.binding import Binding

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


class TestDeviceScreenLifecycle:
    """Tests for DeviceScreen compose/mount lifecycle (C1 regression guard)."""

    def test_device_screen_mounts_panels_after_load(self) -> None:
        """DeviceScreen._load_device() mounts info and action panels when device found.

        This is a regression test for C1: compose() always saw self.device=None
        and rendered dead/error markup regardless of inventory state.
        The fix moves panel construction into _load_device(), which runs in on_mount().
        """
        from unittest.mock import patch as _patch

        from styrened.tui.screens.device import DeviceScreen

        device = make_mock_device(name="boot-node")

        screen = DeviceScreen(device_name="boot-node")

        # Simulate what on_mount() does: call _load_device with a mocked inventory.
        # We verify that the container receives mounted panels, not an error message.
        with _patch("styrened.tui.screens.device.get_device", return_value=device):
            with _patch("styrened.tui.screens.device.HighlightedPanel") as mock_panel_cls, \
                 _patch.object(screen, "query_one") as mock_query_one, \
                 _patch.object(screen, "notify"):

                mock_container = MagicMock()
                mock_placeholder = MagicMock()

                def query_side_effect(selector, *args, **kwargs):
                    if selector == "#device-container":
                        return mock_container
                    if selector == "#device-placeholder":
                        return mock_placeholder
                    raise Exception(f"Unexpected query: {selector}")

                mock_query_one.side_effect = query_side_effect

                screen._load_device()

        # After _load_device(), the placeholder should be removed and two panels mounted.
        mock_placeholder.remove.assert_called_once()
        assert mock_container.mount.call_count == 2

    def test_device_screen_shows_error_when_device_not_found(self) -> None:
        """DeviceScreen._load_device() updates placeholder when device is None.

        Ensures the error path in the fixed implementation works correctly.
        """
        from unittest.mock import patch as _patch

        from styrened.tui.screens.device import DeviceScreen

        screen = DeviceScreen(device_name="missing-node")

        with _patch("styrened.tui.screens.device.get_device", return_value=None):
            with _patch.object(screen, "query_one") as mock_query_one, \
                 _patch.object(screen, "notify"):

                mock_container = MagicMock()
                mock_placeholder = MagicMock()

                def query_side_effect(selector, *args, **kwargs):
                    if selector == "#device-container":
                        return mock_container
                    if selector == "#device-placeholder":
                        return mock_placeholder
                    raise Exception(f"Unexpected query: {selector}")

                mock_query_one.side_effect = query_side_effect
                screen._load_device()

        # No panels mounted; placeholder updated with error text.
        mock_container.mount.assert_not_called()
        mock_placeholder.update.assert_called_once()
        call_arg = mock_placeholder.update.call_args[0][0]
        assert "not found" in call_arg


class TestDeviceConsoleScreen:
    """Tests for DeviceConsoleScreen class structure."""

    def test_class_exists(self) -> None:
        """DeviceConsoleScreen class is importable and is a Screen subclass."""
        from textual.screen import Screen

        assert issubclass(DeviceConsoleScreen, Screen)

    def test_has_expected_bindings(self) -> None:
        """DeviceConsoleScreen has escape and ctrl+l bindings."""
        # BindingType = Binding | tuple[str, str] | tuple[str, str, str]
        # Normalise all forms safely before accessing .key to avoid AttributeError
        # on tuple entries (which have no .key attribute).
        def _key(b: object) -> str:
            if isinstance(b, Binding):
                return b.key
            if isinstance(b, tuple):
                return b[0]
            return str(b)

        keys = {_key(b) for b in DeviceConsoleScreen.BINDINGS}
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
        # Use patch.object rather than direct attribute assignment to avoid
        # mypy's "Cannot assign to a method" error (C3).
        with patch.object(screen, "_update_history_display"):
            screen._add_to_history("status", "ip: 10.0.0.1")
        assert len(screen.command_history) == 1
        assert screen.command_history[0]["command"] == "status"
        assert screen.command_history[0]["response"] == "ip: 10.0.0.1"

    def test_history_capped_at_100(self) -> None:
        """_add_to_history caps history at 100 entries."""
        mock_client = MagicMock()
        screen = DeviceConsoleScreen(device_hash="abcdef", rpc_client=mock_client)
        with patch.object(screen, "_update_history_display"):
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
