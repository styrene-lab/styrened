"""Tests for hardware detection services."""
from __future__ import annotations


import sys
from unittest.mock import MagicMock, patch

import pytest

from styrened.services.hardware import (
    PlatformNotSupportedError,
    get_disks,
    get_network_interfaces,
    get_system_info,
)
from styrened.tui.models.hardware import (
    DiskInfo,
    DiskType,
    InterfaceCategory,
    NetworkInterface,
    NetworkInterfaceType,
    SystemInfo,
)


class TestGetSystemInfo:
    """Tests for get_system_info service."""

    def test_get_system_info_returns_system_info(self) -> None:
        """Verify get_system_info returns a SystemInfo object."""
        with patch("styrened.services.hardware._get_system_info_darwin") as mock:
            mock.return_value = SystemInfo(
                cpu_model="Apple M1",
                cpu_cores=8,
                ram_total_bytes=17179869184,
            )
            with patch("styrened.services.hardware.sys") as mock_sys:
                mock_sys.platform = "darwin"
                info = get_system_info()
                assert isinstance(info, SystemInfo)
                assert info.cpu_model == "Apple M1"
                assert info.cpu_cores == 8

    def test_get_system_info_linux_dispatches(self) -> None:
        """Verify Linux dispatches to _get_system_info_linux."""
        with patch("styrened.services.hardware._get_system_info_linux") as mock:
            mock.return_value = SystemInfo(
                cpu_model="AMD EPYC 7551",
                cpu_cores=4,
                ram_total_bytes=8589934592,
            )
            with patch("styrened.services.hardware.sys") as mock_sys:
                mock_sys.platform = "linux"
                info = get_system_info()
                assert isinstance(info, SystemInfo)
                assert info.cpu_model == "AMD EPYC 7551"
                mock.assert_called_once()

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only test")
    def test_get_system_info_darwin_real(self) -> None:
        """Test actual macOS system info retrieval (integration test)."""
        info = get_system_info()
        assert isinstance(info, SystemInfo)
        assert info.cpu_model != ""
        assert info.cpu_cores > 0
        assert info.ram_total_bytes > 0


class TestGetSystemInfoDarwin:
    """Tests for Darwin-specific system info retrieval."""

    def test_darwin_parses_sysctl_output(self) -> None:
        """Verify Darwin implementation parses sysctl output."""
        mock_cpu_model = "Apple M1 Pro"
        mock_cpu_cores = "10"
        mock_ram = "34359738368"

        with patch("styrened.services.hardware.subprocess.run") as mock_run:
            # Mock sysctl calls
            def run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
                result = MagicMock()
                result.returncode = 0
                if "machdep.cpu.brand_string" in args:
                    result.stdout = mock_cpu_model
                elif "hw.ncpu" in args:
                    result.stdout = mock_cpu_cores
                elif "hw.memsize" in args:
                    result.stdout = mock_ram
                return result

            mock_run.side_effect = run_side_effect

            from styrened.services.hardware import _get_system_info_darwin

            info = _get_system_info_darwin()
            assert info.cpu_model == "Apple M1 Pro"
            assert info.cpu_cores == 10
            assert info.ram_total_bytes == 34359738368


class TestGetDisks:
    """Tests for get_disks service."""

    def test_get_disks_returns_list(self) -> None:
        """Verify get_disks returns a list of DiskInfo."""
        with patch("styrened.services.hardware._get_disks_darwin") as mock:
            mock.return_value = [
                DiskInfo(
                    name="disk0",
                    size_bytes=500107862016,
                    disk_type=DiskType.INTERNAL,
                    mount_point="/",
                    filesystem="apfs",
                ),
            ]
            with patch("styrened.services.hardware.sys") as mock_sys:
                mock_sys.platform = "darwin"
                disks = get_disks()
                assert isinstance(disks, list)
                assert len(disks) == 1
                assert isinstance(disks[0], DiskInfo)

    def test_get_disks_linux_dispatches(self) -> None:
        """Verify Linux dispatches to _get_disks_linux."""
        with patch("styrened.services.hardware._get_disks_linux") as mock:
            mock.return_value = [
                DiskInfo(
                    name="sda1",
                    size_bytes=107374182400,
                    disk_type=DiskType.INTERNAL,
                    mount_point="/",
                    filesystem="ext4",
                ),
            ]
            with patch("styrened.services.hardware.sys") as mock_sys:
                mock_sys.platform = "linux"
                disks = get_disks()
                assert len(disks) == 1
                assert disks[0].name == "sda1"
                mock.assert_called_once()

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only test")
    def test_get_disks_darwin_real(self) -> None:
        """Test actual macOS disk retrieval (integration test)."""
        disks = get_disks()
        assert isinstance(disks, list)
        assert len(disks) > 0
        # Should have at least one internal disk
        internal_disks = [d for d in disks if d.disk_type == DiskType.INTERNAL]
        assert len(internal_disks) > 0


class TestGetDisksDarwin:
    """Tests for Darwin-specific disk enumeration."""

    def test_darwin_parses_diskutil_output(self) -> None:
        """Verify Darwin implementation parses diskutil output."""
        mock_diskutil_list = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>AllDisksAndPartitions</key>
    <array>
        <dict>
            <key>DeviceIdentifier</key>
            <string>disk0</string>
            <key>Size</key>
            <integer>500107862016</integer>
            <key>Content</key>
            <string>GUID_partition_scheme</string>
        </dict>
    </array>
</dict>
</plist>"""

        mock_diskutil_info = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>DeviceIdentifier</key>
    <string>disk0</string>
    <key>Size</key>
    <integer>500107862016</integer>
    <key>Internal</key>
    <true/>
    <key>Removable</key>
    <false/>
    <key>MountPoint</key>
    <string>/</string>
    <key>FilesystemType</key>
    <string>apfs</string>
</dict>
</plist>"""

        with patch("styrened.services.hardware.subprocess.run") as mock_run:

            def run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
                result = MagicMock()
                result.returncode = 0
                if "list" in args:
                    result.stdout = mock_diskutil_list
                else:
                    result.stdout = mock_diskutil_info
                return result

            mock_run.side_effect = run_side_effect

            from styrened.services.hardware import _get_disks_darwin

            disks = _get_disks_darwin()
            assert len(disks) >= 1
            disk = disks[0]
            assert disk.name == "disk0"
            assert disk.disk_type == DiskType.INTERNAL

    def test_darwin_identifies_removable_disk(self) -> None:
        """Verify Darwin correctly identifies removable disks."""
        mock_diskutil_list = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>AllDisksAndPartitions</key>
    <array>
        <dict>
            <key>DeviceIdentifier</key>
            <string>disk2</string>
            <key>Size</key>
            <integer>32010928128</integer>
        </dict>
    </array>
</dict>
</plist>"""

        mock_diskutil_info = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>DeviceIdentifier</key>
    <string>disk2</string>
    <key>Size</key>
    <integer>32010928128</integer>
    <key>Internal</key>
    <false/>
    <key>Removable</key>
    <true/>
    <key>RemovableMedia</key>
    <true/>
    <key>MountPoint</key>
    <string>/Volumes/USB_DRIVE</string>
    <key>FilesystemType</key>
    <string>msdos</string>
</dict>
</plist>"""

        with patch("styrened.services.hardware.subprocess.run") as mock_run:

            def run_side_effect(args: list[str], **kwargs: object) -> MagicMock:
                result = MagicMock()
                result.returncode = 0
                if "list" in args:
                    result.stdout = mock_diskutil_list
                else:
                    result.stdout = mock_diskutil_info
                return result

            mock_run.side_effect = run_side_effect

            from styrened.services.hardware import _get_disks_darwin

            disks = _get_disks_darwin()
            usb_disk = next((d for d in disks if d.name == "disk2"), None)
            assert usb_disk is not None
            assert usb_disk.disk_type == DiskType.REMOVABLE
            assert usb_disk.is_removable is True


class TestGetNetworkInterfaces:
    """Tests for get_network_interfaces service."""

    def test_get_network_interfaces_returns_list(self) -> None:
        """Verify get_network_interfaces returns a list of NetworkInterface."""
        with patch("styrened.services.hardware._get_network_interfaces_darwin") as mock:
            mock.return_value = [
                NetworkInterface(
                    name="en0",
                    interface_type=NetworkInterfaceType.WIFI,
                    category=InterfaceCategory.HARDWARE,
                    mac_address="aa:bb:cc:dd:ee:ff",
                    ip_address="192.168.1.100",
                ),
            ]
            with patch("styrened.services.hardware.sys") as mock_sys:
                mock_sys.platform = "darwin"
                interfaces = get_network_interfaces()
                assert isinstance(interfaces, list)
                assert len(interfaces) == 1
                assert isinstance(interfaces[0], NetworkInterface)

    def test_get_network_interfaces_linux_dispatches(self) -> None:
        """Verify Linux dispatches to _get_network_interfaces_linux."""
        with patch("styrened.services.hardware._get_network_interfaces_linux") as mock:
            mock.return_value = [
                NetworkInterface(
                    name="eth0",
                    interface_type=NetworkInterfaceType.ETHERNET,
                    category=InterfaceCategory.HARDWARE,
                    mac_address="aa:bb:cc:dd:ee:ff",
                    ip_address="192.168.1.50",
                ),
            ]
            with patch("styrened.services.hardware.sys") as mock_sys:
                mock_sys.platform = "linux"
                interfaces = get_network_interfaces()
                assert len(interfaces) == 1
                assert interfaces[0].name == "eth0"
                mock.assert_called_once()

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only test")
    def test_get_network_interfaces_darwin_real(self) -> None:
        """Test actual macOS interface retrieval (integration test)."""
        interfaces = get_network_interfaces()
        assert isinstance(interfaces, list)
        assert len(interfaces) > 0
        # Should have at least loopback
        loopback = [i for i in interfaces if i.interface_type == NetworkInterfaceType.LOOPBACK]
        assert len(loopback) > 0


class TestGetNetworkInterfacesDarwin:
    """Tests for Darwin-specific network interface enumeration."""

    def test_darwin_parses_ifconfig_output(self) -> None:
        """Verify Darwin implementation parses ifconfig output."""
        mock_ifconfig = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether aa:bb:cc:dd:ee:ff
\tinet 192.168.1.100 netmask 0xffffff00 broadcast 192.168.1.255
en1: flags=8963<UP,BROADCAST,SMART,RUNNING,PROMISC,SIMPLEX,MULTICAST> mtu 1500
\tether 11:22:33:44:55:66
utun0: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380
\tinet 10.0.0.1 --> 10.0.0.1 netmask 0xffffffff
"""

        with patch("styrened.services.hardware.subprocess.run") as mock_run:
            result = MagicMock()
            result.returncode = 0
            result.stdout = mock_ifconfig
            mock_run.return_value = result

            # Mock networksetup for interface type detection
            with patch("styrened.services.hardware._get_interface_type_darwin") as mock_type:

                def type_side_effect(name: str) -> NetworkInterfaceType:
                    types = {
                        "lo0": NetworkInterfaceType.LOOPBACK,
                        "en0": NetworkInterfaceType.WIFI,
                        "en1": NetworkInterfaceType.ETHERNET,
                        "utun0": NetworkInterfaceType.VIRTUAL,
                    }
                    return types.get(name, NetworkInterfaceType.UNKNOWN)

                mock_type.side_effect = type_side_effect

                from styrened.services.hardware import _get_network_interfaces_darwin

                interfaces = _get_network_interfaces_darwin()

                # Check we got expected interfaces
                names = [i.name for i in interfaces]
                assert "lo0" in names
                assert "en0" in names

                # Check loopback
                lo = next(i for i in interfaces if i.name == "lo0")
                assert lo.interface_type == NetworkInterfaceType.LOOPBACK
                assert lo.ip_address == "127.0.0.1"
                assert lo.category == InterfaceCategory.VIRTUAL

                # Check wifi
                en0 = next(i for i in interfaces if i.name == "en0")
                assert en0.interface_type == NetworkInterfaceType.WIFI
                assert en0.mac_address == "aa:bb:cc:dd:ee:ff"
                assert en0.ip_address == "192.168.1.100"
                assert en0.category == InterfaceCategory.HARDWARE

    def test_darwin_classifies_interface_types(self) -> None:
        """Verify Darwin correctly classifies interface types by name pattern."""
        # Test interface name patterns
        from styrened.services.hardware import _classify_interface_name_darwin

        assert _classify_interface_name_darwin("lo0") == NetworkInterfaceType.LOOPBACK
        # en* interfaces return UNKNOWN from name classification because they
        # require networksetup lookup to distinguish WiFi from Ethernet
        assert _classify_interface_name_darwin("en0") == NetworkInterfaceType.UNKNOWN
        assert _classify_interface_name_darwin("bridge0") == NetworkInterfaceType.BRIDGE
        assert _classify_interface_name_darwin("utun0") == NetworkInterfaceType.VIRTUAL
        assert _classify_interface_name_darwin("awdl0") == NetworkInterfaceType.VIRTUAL
        assert _classify_interface_name_darwin("llw0") == NetworkInterfaceType.VIRTUAL

    def test_darwin_identifies_hardware_vs_virtual(self) -> None:
        """Verify Darwin correctly identifies hardware vs virtual interfaces."""
        from styrened.tui.models.hardware import infer_interface_category

        # Hardware types
        assert infer_interface_category(NetworkInterfaceType.ETHERNET) == InterfaceCategory.HARDWARE
        assert infer_interface_category(NetworkInterfaceType.WIFI) == InterfaceCategory.HARDWARE
        assert (
            infer_interface_category(NetworkInterfaceType.BLUETOOTH) == InterfaceCategory.HARDWARE
        )

        # Virtual types
        assert infer_interface_category(NetworkInterfaceType.LOOPBACK) == InterfaceCategory.VIRTUAL
        assert infer_interface_category(NetworkInterfaceType.VIRTUAL) == InterfaceCategory.VIRTUAL
        assert infer_interface_category(NetworkInterfaceType.BRIDGE) == InterfaceCategory.VIRTUAL


class TestLinuxSystemInfo:
    """Tests for Linux-specific system info retrieval."""

    def test_linux_uses_psutil(self) -> None:
        """Verify Linux implementation uses psutil for CPU and RAM."""
        mock_vmem = MagicMock()
        mock_vmem.total = 8589934592

        mock_psutil = MagicMock()
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = mock_vmem

        with (
            patch.dict("sys.modules", {"psutil": mock_psutil}),
            patch("styrened.services.hardware.platform") as mock_platform,
            patch("styrened.services.hardware.subprocess.run"),
        ):
            mock_platform.processor.return_value = "x86_64"

            from styrened.services.hardware import _get_system_info_linux

            info = _get_system_info_linux()
            assert info.cpu_cores == 4
            assert info.ram_total_bytes == 8589934592

    def test_linux_reads_proc_cpuinfo_fallback(self) -> None:
        """Verify Linux falls back to /proc/cpuinfo for CPU model."""
        mock_vmem = MagicMock()
        mock_vmem.total = 4294967296

        mock_psutil = MagicMock()
        mock_psutil.cpu_count.return_value = 2
        mock_psutil.virtual_memory.return_value = mock_vmem

        with (
            patch.dict("sys.modules", {"psutil": mock_psutil}),
            patch("styrened.services.hardware.platform") as mock_platform,
            patch("styrened.services.hardware.subprocess.run") as mock_run,
        ):
            mock_platform.processor.return_value = ""  # Empty on some Linux
            mock_platform.machine.return_value = "aarch64"

            result = MagicMock()
            result.returncode = 0
            result.stdout = "model name\t: AMD EPYC 7551 32-Core"
            mock_run.return_value = result

            from styrened.services.hardware import _get_system_info_linux

            info = _get_system_info_linux()
            assert "AMD EPYC 7551" in info.cpu_model


class TestLinuxDisks:
    """Tests for Linux-specific disk enumeration."""

    def test_linux_parses_psutil_partitions(self) -> None:
        """Verify Linux parses psutil disk partitions."""
        mock_partition = MagicMock()
        mock_partition.device = "/dev/sda1"
        mock_partition.mountpoint = "/"
        mock_partition.fstype = "ext4"

        mock_usage = MagicMock()
        mock_usage.total = 107374182400

        mock_psutil = MagicMock()
        mock_psutil.disk_partitions.return_value = [mock_partition]
        mock_psutil.disk_usage.return_value = mock_usage

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            from styrened.services.hardware import _get_disks_linux

            disks = _get_disks_linux()
            assert len(disks) == 1
            assert disks[0].name == "sda1"
            assert disks[0].disk_type == DiskType.INTERNAL
            assert disks[0].filesystem == "ext4"
            assert disks[0].size_bytes == 107374182400

    def test_linux_identifies_removable_media(self) -> None:
        """Verify Linux identifies USB/media mounts as removable."""
        mock_partition = MagicMock()
        mock_partition.device = "/dev/sdb1"
        mock_partition.mountpoint = "/media/usb"
        mock_partition.fstype = "vfat"

        mock_usage = MagicMock()
        mock_usage.total = 32010928128

        mock_psutil = MagicMock()
        mock_psutil.disk_partitions.return_value = [mock_partition]
        mock_psutil.disk_usage.return_value = mock_usage

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            from styrened.services.hardware import _get_disks_linux

            disks = _get_disks_linux()
            assert disks[0].disk_type == DiskType.REMOVABLE

    def test_linux_identifies_nfs(self) -> None:
        """Verify Linux identifies network filesystems."""
        mock_partition = MagicMock()
        mock_partition.device = "nas:/share"
        mock_partition.mountpoint = "/mnt/nas"
        mock_partition.fstype = "nfs4"

        mock_usage = MagicMock()
        mock_usage.total = 1099511627776

        mock_psutil = MagicMock()
        mock_psutil.disk_partitions.return_value = [mock_partition]
        mock_psutil.disk_usage.return_value = mock_usage

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            from styrened.services.hardware import _get_disks_linux

            disks = _get_disks_linux()
            assert disks[0].disk_type == DiskType.NETWORK


class TestLinuxNetworkInterfaces:
    """Tests for Linux-specific network interface enumeration."""

    def test_linux_parses_psutil_interfaces(self) -> None:
        """Verify Linux parses psutil network interfaces."""
        mock_inet_family = MagicMock()
        mock_inet_family.name = "AF_INET"

        mock_addr_inet = MagicMock()
        mock_addr_inet.family = mock_inet_family
        mock_addr_inet.address = "192.168.1.50"

        mock_addr_packet = MagicMock()
        mock_addr_packet.family.name = "AF_PACKET"
        mock_addr_packet.address = "aa:bb:cc:dd:ee:ff"

        mock_stats = MagicMock()
        mock_stats.isup = True

        mock_psutil = MagicMock()
        mock_psutil.net_if_addrs.return_value = {
            "eth0": [mock_addr_packet, mock_addr_inet],
        }
        mock_psutil.net_if_stats.return_value = {
            "eth0": mock_stats,
        }

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            from styrened.services.hardware import _get_network_interfaces_linux

            interfaces = _get_network_interfaces_linux()
            assert len(interfaces) == 1
            assert interfaces[0].name == "eth0"
            assert interfaces[0].interface_type == NetworkInterfaceType.ETHERNET
            assert interfaces[0].ip_address == "192.168.1.50"
            assert interfaces[0].mac_address == "aa:bb:cc:dd:ee:ff"

    def test_linux_classifies_interface_types(self) -> None:
        """Verify Linux correctly classifies interface types by name."""
        from styrened.services.hardware import _classify_interface_name_linux

        assert _classify_interface_name_linux("lo") == NetworkInterfaceType.LOOPBACK
        assert _classify_interface_name_linux("eth0") == NetworkInterfaceType.ETHERNET
        assert _classify_interface_name_linux("enp0s3") == NetworkInterfaceType.ETHERNET
        assert _classify_interface_name_linux("wlan0") == NetworkInterfaceType.WIFI
        assert _classify_interface_name_linux("wlp2s0") == NetworkInterfaceType.WIFI
        assert _classify_interface_name_linux("docker0") == NetworkInterfaceType.BRIDGE
        assert _classify_interface_name_linux("br-abc") == NetworkInterfaceType.BRIDGE
        assert _classify_interface_name_linux("veth123") == NetworkInterfaceType.VIRTUAL
        assert _classify_interface_name_linux("tun0") == NetworkInterfaceType.VIRTUAL
        assert _classify_interface_name_linux("wg0") == NetworkInterfaceType.VIRTUAL
        assert _classify_interface_name_linux("hci0") == NetworkInterfaceType.BLUETOOTH


class TestPlatformNotSupportedError:
    """Tests for PlatformNotSupportedError."""

    def test_error_contains_platform(self) -> None:
        """Verify error message contains platform name."""
        error = PlatformNotSupportedError("freebsd")
        assert "freebsd" in str(error)
        assert "not supported" in str(error).lower()

    def test_error_is_exception(self) -> None:
        """Verify PlatformNotSupportedError is an Exception."""
        error = PlatformNotSupportedError("windows")
        assert isinstance(error, Exception)
