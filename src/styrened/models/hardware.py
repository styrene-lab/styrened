"""Hardware detection models.

Data models for system hardware information including CPU, RAM, disks,
and network interfaces.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DiskType(Enum):
    """Type classification for disk devices."""

    INTERNAL = "internal"
    REMOVABLE = "removable"
    NETWORK = "network"
    VIRTUAL = "virtual"


class NetworkInterfaceType(Enum):
    """Type classification for network interfaces."""

    ETHERNET = "ethernet"
    WIFI = "wifi"
    BLUETOOTH = "bluetooth"
    LOOPBACK = "loopback"
    VIRTUAL = "virtual"
    BRIDGE = "bridge"
    UNKNOWN = "unknown"


class InterfaceCategory(Enum):
    """Category for network interfaces: hardware or virtual."""

    HARDWARE = "hardware"
    VIRTUAL = "virtual"


def infer_interface_category(interface_type: NetworkInterfaceType) -> InterfaceCategory:
    """Infer the category of an interface from its type.

    Args:
        interface_type: The type of network interface.

    Returns:
        InterfaceCategory.HARDWARE for physical interfaces,
        InterfaceCategory.VIRTUAL for virtual/software interfaces.
    """
    hardware_types = {
        NetworkInterfaceType.ETHERNET,
        NetworkInterfaceType.WIFI,
        NetworkInterfaceType.BLUETOOTH,
    }
    if interface_type in hardware_types:
        return InterfaceCategory.HARDWARE
    return InterfaceCategory.VIRTUAL


@dataclass
class SystemInfo:
    """System information including CPU and RAM.

    Attributes:
        cpu_model: CPU model name/brand string.
        cpu_cores: Number of CPU cores.
        ram_total_bytes: Total RAM in bytes.
    """

    cpu_model: str
    cpu_cores: int
    ram_total_bytes: int

    @property
    def ram_total_gb(self) -> float:
        """Return total RAM in gigabytes."""
        return self.ram_total_bytes / (1024**3)

    def __repr__(self) -> str:
        return (
            f"SystemInfo(cpu_model={self.cpu_model!r}, "
            f"cpu_cores={self.cpu_cores}, "
            f"ram_total_gb={self.ram_total_gb:.1f})"
        )


@dataclass
class DiskInfo:
    """Disk device information.

    Attributes:
        name: Device identifier (e.g., "disk0", "sda").
        size_bytes: Total size in bytes.
        disk_type: Type classification (internal, removable, etc.).
        mount_point: Filesystem mount point, if mounted.
        filesystem: Filesystem type (e.g., "apfs", "ext4").
    """

    name: str
    size_bytes: int
    disk_type: DiskType
    mount_point: str | None
    filesystem: str | None

    @property
    def size_gb(self) -> float:
        """Return size in gigabytes."""
        return self.size_bytes / (1024**3)

    @property
    def is_removable(self) -> bool:
        """Return True if disk is removable."""
        return self.disk_type == DiskType.REMOVABLE

    @property
    def size_human(self) -> str:
        """Return human-readable size string."""
        size: float = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"


@dataclass
class NetworkInterface:
    """Network interface information.

    Attributes:
        name: Interface name (e.g., "en0", "eth0").
        interface_type: Type classification (ethernet, wifi, etc.).
        category: Whether interface is hardware or virtual.
        mac_address: MAC address if available.
        ip_address: Primary IPv4 address if configured.
    """

    name: str
    interface_type: NetworkInterfaceType
    category: InterfaceCategory
    mac_address: str | None
    ip_address: str | None

    @property
    def is_hardware(self) -> bool:
        """Return True if interface is a physical hardware interface."""
        return self.category == InterfaceCategory.HARDWARE

    @property
    def is_up(self) -> bool:
        """Return True if interface appears to be up (has an IP address)."""
        return self.ip_address is not None
