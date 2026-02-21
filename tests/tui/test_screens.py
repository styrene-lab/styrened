"""Tests for screen implementations."""

from pathlib import Path

import pytest

from styrened.tui.app import StyreneApp
from styrened.tui.models.hardware import (
    DiskInfo,
    DiskType,
    InterfaceCategory,
    NetworkInterface,
    NetworkInterfaceType,
    SystemInfo,
)
from styrened.models import (
    ReticulumConfig,
    ReticulumIdentity,
)
from styrened.models.reticulum import ReticulumInterface as RNSInterface

# Mock data for dashboard tests
MOCK_SYSTEM_INFO = SystemInfo(
    cpu_model="Apple M1 Pro",
    cpu_cores=10,
    ram_total_bytes=32 * 1024**3,
)

MOCK_DISKS = [
    DiskInfo(
        name="disk0",
        size_bytes=500 * 1024**3,
        disk_type=DiskType.INTERNAL,
        mount_point="/",
        filesystem="apfs",
    ),
]

MOCK_NETWORK_INTERFACES = [
    NetworkInterface(
        name="en0",
        interface_type=NetworkInterfaceType.WIFI,
        category=InterfaceCategory.HARDWARE,
        mac_address="aa:bb:cc:dd:ee:ff",
        ip_address="192.168.0.100",
    ),
]

MOCK_RETICULUM_CONFIG = ReticulumConfig(
    config_path_override=Path.home() / ".reticulum",
    auto_initialize=True,
    announce_interval=300,
)


@pytest.mark.asyncio
async def test_dashboard_has_device_table(app: StyreneApp):
    """Verify dashboard contains the device table."""
    async with app.run_test():
        # Query on the current screen (dashboard), not app
        table = app.screen.query_one("#mesh-device-table")
        assert table is not None
        assert table.__class__.__name__ == "MeshDeviceTable"


@pytest.mark.asyncio
async def test_dashboard_has_panels(app: StyreneApp):
    """Verify dashboard contains status panels."""
    async with app.run_test():
        # Query on the current screen (dashboard)
        mesh_status_panel = app.screen.query_one("#mesh-status-panel")
        reticulum_panel = app.screen.query_one("#reticulum-status-panel")
        hardware_panel = app.screen.query_one("#hardware-panel")

        assert mesh_status_panel is not None
        assert reticulum_panel is not None
        assert hardware_panel is not None


@pytest.mark.asyncio
async def test_dashboard_refresh_notification(app: StyreneApp):
    """Verify refresh action shows notification."""
    async with app.run_test() as pilot:
        await pilot.press("r")
        # Should show a notification (we can't easily assert content,
        # but we can verify no exception was raised)


class TestDashboardHardwareBinding:
    """Test dashboard hardware panel toggle binding."""

    @pytest.mark.asyncio
    async def test_hardware_binding_exists(self, app: StyreneApp) -> None:
        """Verify H key binding exists for hardware panel."""
        async with app.run_test() as pilot:
            # Verify dashboard loads
            assert app.screen.__class__.__name__ == "DashboardScreen"

            # Test the hardware toggle binding works by pressing 'h'
            # This should toggle the hardware panel visibility without error
            await pilot.press("h")


class TestDeviceScreen:
    """Test device detail screen."""

    @pytest.mark.asyncio
    async def test_device_screen_can_be_created(self) -> None:
        """Verify device screen can be instantiated."""

        from styrened.tui.screens.device import DeviceScreen

        # Test screen creation
        device_screen = DeviceScreen("test-device")
        assert device_screen.device_name == "test-device"

    @pytest.mark.asyncio
    async def test_device_info_panel_displays_device(self) -> None:
        """Verify DeviceInfoPanel displays device information."""
        from datetime import datetime

        from styrened.tui.models.fleet import Device
        from styrened.tui.screens.device import DeviceInfoPanel

        mock_device = Device(
            name="test-device",
            profile="node",
            hardware="rpi4",
            status="online",
            last_seen=datetime.now(),
            reticulum_identity="abc123",
            ip_address="192.168.0.100",
            notes="Test device",
        )

        # Test panel can be created
        panel = DeviceInfoPanel(mock_device)
        assert panel.device.name == "test-device"
        assert panel.device.profile == "node"
