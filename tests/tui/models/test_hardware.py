"""Tests for hardware detection models."""

import pytest

from styrened.tui.models.hardware import (
    DiskInfo,
    DiskType,
    InterfaceCategory,
    NetworkInterface,
    NetworkInterfaceType,
    SystemInfo,
)


class TestSystemInfo:
    """Tests for SystemInfo model."""

    def test_system_info_instantiation(self) -> None:
        """Verify SystemInfo can be instantiated with required fields."""
        info = SystemInfo(
            cpu_model="Apple M1",
            cpu_cores=8,
            ram_total_bytes=17179869184,  # 16 GB
        )
        assert info.cpu_model == "Apple M1"
        assert info.cpu_cores == 8
        assert info.ram_total_bytes == 17179869184

    def test_system_info_ram_gb_property(self) -> None:
        """Verify RAM can be retrieved in GB."""
        info = SystemInfo(
            cpu_model="Intel Core i7",
            cpu_cores=4,
            ram_total_bytes=8589934592,  # 8 GB
        )
        assert info.ram_total_gb == 8.0

    def test_system_info_ram_gb_fractional(self) -> None:
        """Verify fractional GB calculation."""
        info = SystemInfo(
            cpu_model="Test CPU",
            cpu_cores=2,
            ram_total_bytes=6442450944,  # 6 GB
        )
        assert info.ram_total_gb == 6.0

    def test_system_info_repr(self) -> None:
        """Verify string representation."""
        info = SystemInfo(
            cpu_model="Test CPU",
            cpu_cores=4,
            ram_total_bytes=8589934592,
        )
        repr_str = repr(info)
        assert "Test CPU" in repr_str
        assert "4" in repr_str


class TestDiskType:
    """Tests for DiskType enum."""

    def test_disk_type_values(self) -> None:
        """Verify DiskType enum has expected values."""
        assert DiskType.INTERNAL.value == "internal"
        assert DiskType.REMOVABLE.value == "removable"
        assert DiskType.NETWORK.value == "network"
        assert DiskType.VIRTUAL.value == "virtual"

    def test_disk_type_from_string(self) -> None:
        """Verify DiskType can be created from string."""
        assert DiskType("internal") == DiskType.INTERNAL
        assert DiskType("removable") == DiskType.REMOVABLE


class TestDiskInfo:
    """Tests for DiskInfo model."""

    def test_disk_info_instantiation(self) -> None:
        """Verify DiskInfo can be instantiated."""
        disk = DiskInfo(
            name="disk0",
            size_bytes=500107862016,
            disk_type=DiskType.INTERNAL,
            mount_point="/",
            filesystem="apfs",
        )
        assert disk.name == "disk0"
        assert disk.size_bytes == 500107862016
        assert disk.disk_type == DiskType.INTERNAL
        assert disk.mount_point == "/"
        assert disk.filesystem == "apfs"

    def test_disk_info_optional_mount(self) -> None:
        """Verify DiskInfo accepts None mount point."""
        disk = DiskInfo(
            name="disk1",
            size_bytes=32000000000,
            disk_type=DiskType.REMOVABLE,
            mount_point=None,
            filesystem=None,
        )
        assert disk.mount_point is None
        assert disk.filesystem is None

    def test_disk_info_size_gb_property(self) -> None:
        """Verify size can be retrieved in GB."""
        disk = DiskInfo(
            name="disk0",
            size_bytes=107374182400,  # 100 GB
            disk_type=DiskType.INTERNAL,
            mount_point="/",
            filesystem="apfs",
        )
        assert disk.size_gb == pytest.approx(100.0, rel=0.01)

    def test_disk_info_is_removable(self) -> None:
        """Verify is_removable property."""
        internal = DiskInfo(
            name="disk0",
            size_bytes=500000000000,
            disk_type=DiskType.INTERNAL,
            mount_point="/",
            filesystem="apfs",
        )
        removable = DiskInfo(
            name="disk1",
            size_bytes=32000000000,
            disk_type=DiskType.REMOVABLE,
            mount_point="/Volumes/USB",
            filesystem="fat32",
        )
        assert internal.is_removable is False
        assert removable.is_removable is True

    def test_disk_info_human_readable_size(self) -> None:
        """Verify human readable size formatting."""
        disk = DiskInfo(
            name="disk0",
            size_bytes=1099511627776,  # 1 TB
            disk_type=DiskType.INTERNAL,
            mount_point="/",
            filesystem="apfs",
        )
        assert "1" in disk.size_human and "TB" in disk.size_human


class TestNetworkInterfaceType:
    """Tests for NetworkInterfaceType enum."""

    def test_interface_type_values(self) -> None:
        """Verify NetworkInterfaceType enum has expected values."""
        assert NetworkInterfaceType.ETHERNET.value == "ethernet"
        assert NetworkInterfaceType.WIFI.value == "wifi"
        assert NetworkInterfaceType.BLUETOOTH.value == "bluetooth"
        assert NetworkInterfaceType.LOOPBACK.value == "loopback"
        assert NetworkInterfaceType.VIRTUAL.value == "virtual"
        assert NetworkInterfaceType.BRIDGE.value == "bridge"
        assert NetworkInterfaceType.UNKNOWN.value == "unknown"


class TestInterfaceCategory:
    """Tests for InterfaceCategory enum."""

    def test_category_values(self) -> None:
        """Verify InterfaceCategory enum has expected values."""
        assert InterfaceCategory.HARDWARE.value == "hardware"
        assert InterfaceCategory.VIRTUAL.value == "virtual"


class TestNetworkInterface:
    """Tests for NetworkInterface model."""

    def test_network_interface_instantiation(self) -> None:
        """Verify NetworkInterface can be instantiated."""
        iface = NetworkInterface(
            name="en0",
            interface_type=NetworkInterfaceType.WIFI,
            category=InterfaceCategory.HARDWARE,
            mac_address="aa:bb:cc:dd:ee:ff",
            ip_address="192.168.1.100",
        )
        assert iface.name == "en0"
        assert iface.interface_type == NetworkInterfaceType.WIFI
        assert iface.category == InterfaceCategory.HARDWARE
        assert iface.mac_address == "aa:bb:cc:dd:ee:ff"
        assert iface.ip_address == "192.168.1.100"

    def test_network_interface_optional_fields(self) -> None:
        """Verify optional fields can be None."""
        iface = NetworkInterface(
            name="lo0",
            interface_type=NetworkInterfaceType.LOOPBACK,
            category=InterfaceCategory.VIRTUAL,
            mac_address=None,
            ip_address="127.0.0.1",
        )
        assert iface.mac_address is None
        assert iface.ip_address == "127.0.0.1"

    def test_network_interface_is_hardware(self) -> None:
        """Verify is_hardware property."""
        hardware = NetworkInterface(
            name="en0",
            interface_type=NetworkInterfaceType.ETHERNET,
            category=InterfaceCategory.HARDWARE,
            mac_address="aa:bb:cc:dd:ee:ff",
            ip_address="192.168.1.100",
        )
        virtual = NetworkInterface(
            name="utun0",
            interface_type=NetworkInterfaceType.VIRTUAL,
            category=InterfaceCategory.VIRTUAL,
            mac_address=None,
            ip_address=None,
        )
        assert hardware.is_hardware is True
        assert virtual.is_hardware is False

    def test_network_interface_is_up(self) -> None:
        """Verify is_up property based on IP presence."""
        up = NetworkInterface(
            name="en0",
            interface_type=NetworkInterfaceType.WIFI,
            category=InterfaceCategory.HARDWARE,
            mac_address="aa:bb:cc:dd:ee:ff",
            ip_address="192.168.1.100",
        )
        down = NetworkInterface(
            name="en1",
            interface_type=NetworkInterfaceType.ETHERNET,
            category=InterfaceCategory.HARDWARE,
            mac_address="aa:bb:cc:dd:ee:00",
            ip_address=None,
        )
        assert up.is_up is True
        assert down.is_up is False

    @pytest.mark.parametrize(
        "iface_type,expected_category",
        [
            (NetworkInterfaceType.ETHERNET, InterfaceCategory.HARDWARE),
            (NetworkInterfaceType.WIFI, InterfaceCategory.HARDWARE),
            (NetworkInterfaceType.BLUETOOTH, InterfaceCategory.HARDWARE),
            (NetworkInterfaceType.LOOPBACK, InterfaceCategory.VIRTUAL),
            (NetworkInterfaceType.VIRTUAL, InterfaceCategory.VIRTUAL),
            (NetworkInterfaceType.BRIDGE, InterfaceCategory.VIRTUAL),
        ],
    )
    def test_interface_type_default_category(
        self, iface_type: NetworkInterfaceType, expected_category: InterfaceCategory
    ) -> None:
        """Verify interface types map to expected default categories."""
        # This tests the helper function that infers category from type
        from styrened.tui.models.hardware import infer_interface_category

        assert infer_interface_category(iface_type) == expected_category
