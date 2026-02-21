"""Hardware detection services.

Platform-specific implementations for detecting system hardware including
CPU, RAM, disks, and network interfaces.
"""

from __future__ import annotations

import platform
import re
import subprocess
import sys

from styrened.models.hardware import (
    DiskInfo,
    DiskType,
    NetworkInterface,
    NetworkInterfaceType,
    SystemInfo,
    infer_interface_category,
)


class PlatformNotSupportedError(Exception):
    """Raised when the current platform is not supported."""

    def __init__(self, platform: str) -> None:
        self.platform = platform
        super().__init__(f"Platform '{platform}' is not supported")


def get_system_info() -> SystemInfo:
    """Get system information (CPU, RAM).

    Returns:
        SystemInfo object with CPU and RAM details.

    Raises:
        PlatformNotSupportedError: If the current platform is not supported.
    """
    if sys.platform == "darwin":
        return _get_system_info_darwin()
    if sys.platform == "linux":
        return _get_system_info_linux()
    raise PlatformNotSupportedError(sys.platform)


def get_disks() -> list[DiskInfo]:
    """Get list of disk devices.

    Returns:
        List of DiskInfo objects for all detected disks.

    Raises:
        PlatformNotSupportedError: If the current platform is not supported.
    """
    if sys.platform == "darwin":
        return _get_disks_darwin()
    if sys.platform == "linux":
        return _get_disks_linux()
    raise PlatformNotSupportedError(sys.platform)


def get_network_interfaces() -> list[NetworkInterface]:
    """Get list of network interfaces.

    Returns:
        List of NetworkInterface objects for all detected interfaces.

    Raises:
        PlatformNotSupportedError: If the current platform is not supported.
    """
    if sys.platform == "darwin":
        return _get_network_interfaces_darwin()
    if sys.platform == "linux":
        return _get_network_interfaces_linux()
    raise PlatformNotSupportedError(sys.platform)


# -----------------------------------------------------------------------------
# Darwin (macOS) implementations
# -----------------------------------------------------------------------------


def _get_system_info_darwin() -> SystemInfo:
    """Get system info on macOS using sysctl."""
    # Get CPU model
    cpu_result = subprocess.run(
        ["sysctl", "-n", "machdep.cpu.brand_string"],
        capture_output=True,
        text=True,
        check=False,
    )
    cpu_model = cpu_result.stdout.strip() if cpu_result.returncode == 0 else "Unknown"

    # Fallback for Apple Silicon which doesn't have machdep.cpu.brand_string
    if not cpu_model or cpu_model == "Unknown":
        # Try to get chip name from sysctl
        chip_result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            check=False,
        )
        if chip_result.returncode != 0:
            # Use system_profiler for Apple Silicon
            sp_result = subprocess.run(
                ["system_profiler", "SPHardwareDataType", "-json"],
                capture_output=True,
                text=True,
                check=False,
            )
            if sp_result.returncode == 0:
                import json

                try:
                    data = json.loads(sp_result.stdout)
                    hw_data = data.get("SPHardwareDataType", [{}])[0]
                    cpu_model = hw_data.get("chip_type", "Apple Silicon")
                except (json.JSONDecodeError, KeyError, IndexError):
                    cpu_model = "Apple Silicon"
            else:
                cpu_model = "Unknown"
        else:
            cpu_model = chip_result.stdout.strip()

    # Get CPU core count
    cores_result = subprocess.run(
        ["sysctl", "-n", "hw.ncpu"],
        capture_output=True,
        text=True,
        check=False,
    )
    cpu_cores = int(cores_result.stdout.strip()) if cores_result.returncode == 0 else 0

    # Get total RAM
    ram_result = subprocess.run(
        ["sysctl", "-n", "hw.memsize"],
        capture_output=True,
        text=True,
        check=False,
    )
    ram_total = int(ram_result.stdout.strip()) if ram_result.returncode == 0 else 0

    return SystemInfo(
        cpu_model=cpu_model,
        cpu_cores=cpu_cores,
        ram_total_bytes=ram_total,
    )


def _get_disks_darwin() -> list[DiskInfo]:
    """Get disk information on macOS using diskutil."""
    import plistlib

    disks: list[DiskInfo] = []

    # Get list of all disks
    list_result = subprocess.run(
        ["diskutil", "list", "-plist"],
        capture_output=True,
        text=True,
        check=False,
    )

    if list_result.returncode != 0:
        return disks

    try:
        plist_data = plistlib.loads(list_result.stdout.encode())
    except plistlib.InvalidFileException:
        return disks

    all_disks = plist_data.get("AllDisksAndPartitions", [])

    for disk_entry in all_disks:
        device_id = disk_entry.get("DeviceIdentifier", "")
        if not device_id:
            continue

        # Get detailed info for this disk
        info_result = subprocess.run(
            ["diskutil", "info", "-plist", device_id],
            capture_output=True,
            text=True,
            check=False,
        )

        if info_result.returncode != 0:
            continue

        try:
            info_data = plistlib.loads(info_result.stdout.encode())
        except plistlib.InvalidFileException:
            continue

        # Determine disk type
        is_internal = info_data.get("Internal", False)
        is_removable = info_data.get("Removable", False) or info_data.get("RemovableMedia", False)
        is_network = info_data.get("Protocol", "") == "Network"
        is_virtual = info_data.get("VirtualOrPhysical", "") == "Virtual"

        if is_virtual:
            disk_type = DiskType.VIRTUAL
        elif is_network:
            disk_type = DiskType.NETWORK
        elif is_removable or not is_internal:
            disk_type = DiskType.REMOVABLE
        else:
            disk_type = DiskType.INTERNAL

        disk = DiskInfo(
            name=device_id,
            size_bytes=info_data.get("Size", 0),
            disk_type=disk_type,
            mount_point=info_data.get("MountPoint") or None,
            filesystem=info_data.get("FilesystemType") or None,
        )
        disks.append(disk)

    return disks


def _get_network_interfaces_darwin() -> list[NetworkInterface]:
    """Get network interfaces on macOS using ifconfig."""
    interfaces: list[NetworkInterface] = []

    # Get interface info from ifconfig
    result = subprocess.run(
        ["ifconfig", "-a"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return interfaces

    # Parse ifconfig output
    current_iface: str | None = None
    current_mac: str | None = None
    current_ip: str | None = None

    for line in result.stdout.split("\n"):
        # New interface starts at beginning of line (no whitespace)
        iface_match = re.match(r"^(\w+):", line)
        if iface_match:
            # Save previous interface if any
            if current_iface is not None:
                iface_type = _get_interface_type_darwin(current_iface)
                category = infer_interface_category(iface_type)
                interfaces.append(
                    NetworkInterface(
                        name=current_iface,
                        interface_type=iface_type,
                        category=category,
                        mac_address=current_mac,
                        ip_address=current_ip,
                    )
                )

            current_iface = iface_match.group(1)
            current_mac = None
            current_ip = None
            continue

        # Parse MAC address (ether line)
        ether_match = re.search(r"ether\s+([0-9a-f:]+)", line)
        if ether_match:
            current_mac = ether_match.group(1)
            continue

        # Parse IPv4 address (inet line, not inet6)
        inet_match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", line)
        if inet_match and current_ip is None:  # Take first IPv4
            current_ip = inet_match.group(1)
            continue

    # Don't forget the last interface
    if current_iface is not None:
        iface_type = _get_interface_type_darwin(current_iface)
        category = infer_interface_category(iface_type)
        interfaces.append(
            NetworkInterface(
                name=current_iface,
                interface_type=iface_type,
                category=category,
                mac_address=current_mac,
                ip_address=current_ip,
            )
        )

    return interfaces


def _get_interface_type_darwin(name: str) -> NetworkInterfaceType:
    """Determine the type of a network interface on macOS.

    Uses name pattern matching and networksetup when available.
    """
    # First try name-based classification
    classified = _classify_interface_name_darwin(name)
    if classified != NetworkInterfaceType.UNKNOWN:
        return classified

    # For en* interfaces, try to determine if WiFi or Ethernet via networksetup
    if name.startswith("en"):
        try:
            result = subprocess.run(
                ["networksetup", "-listallhardwareports"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                # Parse output to find this interface
                lines = result.stdout.split("\n")
                for i, line in enumerate(lines):
                    if f"Device: {name}" in line:
                        # Look at previous lines for hardware port type
                        for j in range(max(0, i - 2), i):
                            port_line = lines[j]
                            if "Wi-Fi" in port_line:
                                return NetworkInterfaceType.WIFI
                            if "Ethernet" in port_line or "Thunderbolt" in port_line:
                                return NetworkInterfaceType.ETHERNET
                            if "Bluetooth" in port_line:
                                return NetworkInterfaceType.BLUETOOTH
        except (subprocess.SubprocessError, OSError):
            pass

    return NetworkInterfaceType.UNKNOWN


def _classify_interface_name_darwin(name: str) -> NetworkInterfaceType:
    """Classify interface type based on macOS naming conventions.

    Args:
        name: Interface name (e.g., "en0", "lo0", "utun0").

    Returns:
        NetworkInterfaceType based on name pattern.
    """
    # Loopback
    if name.startswith("lo"):
        return NetworkInterfaceType.LOOPBACK

    # Bridge interfaces
    if name.startswith("bridge"):
        return NetworkInterfaceType.BRIDGE

    # Virtual tunnel interfaces
    if name.startswith(("utun", "ipsec", "gif", "stf")):
        return NetworkInterfaceType.VIRTUAL

    # Apple Wireless Direct Link (peer-to-peer WiFi for AirDrop etc)
    if name.startswith("awdl"):
        return NetworkInterfaceType.VIRTUAL

    # Low Latency WLAN (for WiFi Calling etc)
    if name.startswith("llw"):
        return NetworkInterfaceType.VIRTUAL

    # Apple proprietary interfaces
    if name.startswith(("ap", "anpi", "pktap", "iptap")):
        return NetworkInterfaceType.VIRTUAL

    # Bluetooth PAN
    if name.startswith(("p2p", "XHC")):
        return NetworkInterfaceType.BLUETOOTH

    # en* interfaces need further classification (could be WiFi or Ethernet)
    # Return UNKNOWN to trigger networksetup lookup
    if name.startswith("en"):
        return NetworkInterfaceType.UNKNOWN

    return NetworkInterfaceType.UNKNOWN


# -----------------------------------------------------------------------------
# Linux implementations (psutil-based)
# -----------------------------------------------------------------------------


def _get_system_info_linux() -> SystemInfo:
    """Get system info on Linux using psutil and platform."""
    import psutil

    cpu_model = platform.processor() or "Unknown"

    # /proc/cpuinfo gives better model names on Linux
    if cpu_model in ("", "Unknown"):
        try:
            result = subprocess.run(
                ["grep", "-m1", "model name", "/proc/cpuinfo"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and ":" in result.stdout:
                cpu_model = result.stdout.split(":", 1)[1].strip()
        except (subprocess.SubprocessError, OSError):
            cpu_model = platform.machine() or "Unknown"

    cpu_cores = psutil.cpu_count(logical=True) or 0
    ram_total = psutil.virtual_memory().total

    return SystemInfo(
        cpu_model=cpu_model,
        cpu_cores=cpu_cores,
        ram_total_bytes=ram_total,
    )


def _get_disks_linux() -> list[DiskInfo]:
    """Get disk information on Linux using psutil."""
    import psutil

    disks: list[DiskInfo] = []

    for partition in psutil.disk_partitions(all=False):
        # Determine disk type from device path and fstype
        device = partition.device
        mountpoint = partition.mountpoint
        fstype = partition.fstype

        if "loop" in device or fstype == "squashfs":
            disk_type = DiskType.VIRTUAL
        elif device.startswith("/dev/sr") or "cdrom" in mountpoint.lower():
            disk_type = DiskType.REMOVABLE
        elif fstype in ("nfs", "nfs4", "cifs", "smbfs", "9p"):
            disk_type = DiskType.NETWORK
        elif "usb" in device.lower() or mountpoint.startswith("/media"):
            disk_type = DiskType.REMOVABLE
        else:
            disk_type = DiskType.INTERNAL

        # Get size via disk_usage
        try:
            usage = psutil.disk_usage(mountpoint)
            size_bytes = usage.total
        except (PermissionError, OSError):
            size_bytes = 0

        name = device.split("/")[-1] if "/" in device else device

        disks.append(
            DiskInfo(
                name=name,
                size_bytes=size_bytes,
                disk_type=disk_type,
                mount_point=mountpoint,
                filesystem=fstype or None,
            )
        )

    return disks


def _get_network_interfaces_linux() -> list[NetworkInterface]:
    """Get network interfaces on Linux using psutil."""
    import psutil

    interfaces: list[NetworkInterface] = []
    addrs = psutil.net_if_addrs()

    for name, addr_list in addrs.items():
        mac_address: str | None = None
        ip_address: str | None = None

        for addr in addr_list:
            # AF_LINK / AF_PACKET = MAC address (family 17 on Linux)
            if addr.family.name in ("AF_LINK", "AF_PACKET"):
                mac_address = addr.address
            # AF_INET = IPv4
            elif addr.family.name == "AF_INET" and ip_address is None:
                ip_address = addr.address

        iface_type = _classify_interface_name_linux(name)
        category = infer_interface_category(iface_type)

        interfaces.append(
            NetworkInterface(
                name=name,
                interface_type=iface_type,
                category=category,
                mac_address=mac_address,
                ip_address=ip_address,
            )
        )

    return interfaces


def _classify_interface_name_linux(name: str) -> NetworkInterfaceType:
    """Classify interface type based on Linux naming conventions."""
    if name == "lo" or name.startswith("lo:"):
        return NetworkInterfaceType.LOOPBACK

    if name.startswith(("eth", "enp", "ens", "eno")):
        return NetworkInterfaceType.ETHERNET

    if name.startswith(("wlan", "wlp", "wls")):
        return NetworkInterfaceType.WIFI

    if name.startswith(("br", "docker", "virbr")):
        return NetworkInterfaceType.BRIDGE

    if name.startswith(("veth", "tun", "tap", "wg", "tailscale")):
        return NetworkInterfaceType.VIRTUAL

    if name.startswith(("hci", "bnep", "bt")):
        return NetworkInterfaceType.BLUETOOTH

    if name.startswith("bat"):
        return NetworkInterfaceType.VIRTUAL

    return NetworkInterfaceType.UNKNOWN
