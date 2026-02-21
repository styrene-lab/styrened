"""Tests for HardwarePanel widget."""

from unittest.mock import patch

import pytest

from styrened.tui.models.hardware import (
    DiskInfo,
    DiskType,
    InterfaceCategory,
    NetworkInterface,
    NetworkInterfaceType,
    SystemInfo,
)

# Mock data for testing
MOCK_SYSTEM_INFO = SystemInfo(
    cpu_model="Apple M1 Pro",
    cpu_cores=10,
    ram_total_bytes=32 * 1024**3,  # 32 GB
)

MOCK_DISKS = [
    DiskInfo(
        name="disk0",
        size_bytes=500 * 1024**3,  # 500 GB
        disk_type=DiskType.INTERNAL,
        mount_point="/",
        filesystem="apfs",
    ),
    DiskInfo(
        name="disk2",
        size_bytes=64 * 1024**3,  # 64 GB
        disk_type=DiskType.REMOVABLE,
        mount_point="/Volumes/USB",
        filesystem="exfat",
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
    NetworkInterface(
        name="en1",
        interface_type=NetworkInterfaceType.ETHERNET,
        category=InterfaceCategory.HARDWARE,
        mac_address="11:22:33:44:55:66",
        ip_address=None,
    ),
    NetworkInterface(
        name="lo0",
        interface_type=NetworkInterfaceType.LOOPBACK,
        category=InterfaceCategory.VIRTUAL,
        mac_address=None,
        ip_address="127.0.0.1",
    ),
]


class TestHardwarePanelInstantiation:
    """Test HardwarePanel widget creation."""

    def test_can_import_hardware_panel(self) -> None:
        """Verify HardwarePanel can be imported."""
        from styrened.tui.widgets.hardware_panel import HardwarePanel

        assert HardwarePanel is not None

    def test_hardware_panel_instantiation(self) -> None:
        """Verify HardwarePanel can be instantiated."""
        from styrened.tui.widgets.hardware_panel import HardwarePanel

        panel = HardwarePanel()
        assert panel is not None


class TestHardwarePanelSystemInfo:
    """Test HardwarePanel system info display."""

    @pytest.mark.asyncio
    async def test_displays_cpu_info(self) -> None:
        """Verify panel displays CPU model and cores."""
        from styrened.tui.widgets.hardware_panel import HardwarePanel

        with (
            patch(
                "styrened.tui.widgets.hardware_panel.get_system_info",
                return_value=MOCK_SYSTEM_INFO,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_disks",
                return_value=MOCK_DISKS,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_network_interfaces",
                return_value=MOCK_NETWORK_INTERFACES,
            ),
        ):
            panel = HardwarePanel()
            panel._load_hardware_data()
            rendered = panel.render()

            assert "M1" in rendered or "Apple" in rendered
            assert "10c" in rendered  # cores

    @pytest.mark.asyncio
    async def test_displays_ram_info(self) -> None:
        """Verify panel displays RAM information."""
        from styrened.tui.widgets.hardware_panel import HardwarePanel

        with (
            patch(
                "styrened.tui.widgets.hardware_panel.get_system_info",
                return_value=MOCK_SYSTEM_INFO,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_disks",
                return_value=MOCK_DISKS,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_network_interfaces",
                return_value=MOCK_NETWORK_INTERFACES,
            ),
        ):
            panel = HardwarePanel()
            panel._load_hardware_data()
            rendered = panel.render()

            # Should show RAM in GB
            assert "32" in rendered and "GB" in rendered


class TestHardwarePanelDisks:
    """Test HardwarePanel disk display."""

    @pytest.mark.asyncio
    async def test_displays_removable_count(self) -> None:
        """Verify panel displays removable device count."""
        from styrened.tui.widgets.hardware_panel import HardwarePanel

        with (
            patch(
                "styrened.tui.widgets.hardware_panel.get_system_info",
                return_value=MOCK_SYSTEM_INFO,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_disks",
                return_value=MOCK_DISKS,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_network_interfaces",
                return_value=MOCK_NETWORK_INTERFACES,
            ),
        ):
            panel = HardwarePanel()
            panel._load_hardware_data()
            rendered = panel.render()

            assert "STORAGE:" in rendered
            assert "1 removable" in rendered


class TestHardwarePanelNetwork:
    """Test HardwarePanel network interface display."""

    @pytest.mark.asyncio
    async def test_displays_primary_interface(self) -> None:
        """Verify panel displays primary network interface."""
        from styrened.tui.widgets.hardware_panel import HardwarePanel

        with (
            patch(
                "styrened.tui.widgets.hardware_panel.get_system_info",
                return_value=MOCK_SYSTEM_INFO,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_disks",
                return_value=MOCK_DISKS,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_network_interfaces",
                return_value=MOCK_NETWORK_INTERFACES,
            ),
        ):
            panel = HardwarePanel()
            panel._load_hardware_data()
            rendered = panel.render()

            assert "NETWORK:" in rendered
            assert "en0" in rendered  # Primary interface

    @pytest.mark.asyncio
    async def test_shows_interface_ip_address(self) -> None:
        """Verify panel shows IP addresses for active interfaces."""
        from styrened.tui.widgets.hardware_panel import HardwarePanel

        with (
            patch(
                "styrened.tui.widgets.hardware_panel.get_system_info",
                return_value=MOCK_SYSTEM_INFO,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_disks",
                return_value=MOCK_DISKS,
            ),
            patch(
                "styrened.tui.widgets.hardware_panel.get_network_interfaces",
                return_value=MOCK_NETWORK_INTERFACES,
            ),
        ):
            panel = HardwarePanel()
            panel._load_hardware_data()
            rendered = panel.render()

            assert "192.168.0.100" in rendered


class TestHardwarePanelErrorHandling:
    """Test HardwarePanel error handling."""

    @pytest.mark.asyncio
    async def test_handles_platform_not_supported(self) -> None:
        """Verify panel handles PlatformNotSupportedError gracefully."""
        from styrened.tui.services.hardware import PlatformNotSupportedError
        from styrened.tui.widgets.hardware_panel import HardwarePanel

        with patch(
            "styrened.tui.widgets.hardware_panel.get_system_info",
            side_effect=PlatformNotSupportedError("linux"),
        ):
            panel = HardwarePanel()
            panel._load_hardware_data()
            rendered = panel.render()

            # Should show error message
            assert "not supported" in rendered.lower()
