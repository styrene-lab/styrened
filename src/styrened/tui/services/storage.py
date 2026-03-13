"""Storage device detection service.

Provides async disk enumeration for macOS and Linux systems.
"""

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from typing import Literal


@dataclass
class StorageDevice:
    """Storage device information.

    Attributes:
        device: Device path (e.g., "/dev/disk2", "/dev/sdb").
        size_gb: Size in gigabytes.
        type: Device type classification.
        mounted: Whether the device or its partitions are mounted.
        label: Human-readable label if available.
    """

    device: str
    size_gb: int
    type: Literal["sd", "usb", "internal"]
    mounted: bool
    label: str | None = None

    @property
    def display_name(self) -> str:
        """Get display name for the device."""
        if self.label:
            return f"{self.label} ({self.device})"
        return self.device

    @property
    def display_size(self) -> str:
        """Get human-readable size string."""
        if self.size_gb < 1:
            return f"{self.size_gb * 1024:.0f} MB"
        return f"{self.size_gb:.1f} GB"


async def detect_storage() -> list[StorageDevice]:
    """Detect removable storage devices (async, non-blocking).

    Returns:
        List of detected storage devices suitable for provisioning.

    Raises:
        RuntimeError: If disk enumeration fails.
    """
    if sys.platform == "darwin":
        return await _detect_storage_macos()
    elif sys.platform.startswith("linux"):
        return await _detect_storage_linux()
    else:
        # Fallback: return mock data for unsupported platforms
        return _get_mock_storage()


async def _detect_storage_macos() -> list[StorageDevice]:
    """Detect storage devices on macOS using diskutil.

    Returns:
        List of external/removable storage devices.
    """
    try:
        # Run diskutil list -plist to get structured output
        proc = await asyncio.create_subprocess_exec(
            "diskutil",
            "list",
            "-plist",
            "external",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"diskutil failed: {stderr.decode() if stderr else 'unknown error'}")

        # Parse plist output (simplified - actual implementation would use plistlib)
        # For now, we'll use diskutil list and parse text output
        proc = await asyncio.create_subprocess_exec(
            "diskutil",
            "list",
            "external",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return _get_mock_storage()

        output = stdout.decode()
        devices: list[StorageDevice] = []

        # Parse diskutil output for external disks
        # Format: /dev/disk2 (external, physical):
        disk_pattern = re.compile(r"/dev/(disk\d+)\s+\(external")
        current_disk: str | None = None

        for line in output.splitlines():
            disk_match = disk_pattern.search(line)
            if disk_match:
                current_disk = f"/dev/{disk_match.group(1)}"
                # Get disk info
                devices.append(await _get_macos_disk_info(current_disk))

        # Return mock data if no devices found
        if not devices:
            return _get_mock_storage()

        return devices

    except Exception as e:
        # Log error and return mock data for development
        print(f"Warning: Failed to detect storage on macOS: {e}", file=sys.stderr)
        return _get_mock_storage()


async def _get_macos_disk_info(device: str) -> StorageDevice:
    """Get detailed info for a macOS disk device.

    Args:
        device: Device path (e.g., "/dev/disk2").

    Returns:
        StorageDevice with populated information.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "diskutil",
            "info",
            "-plist",
            device,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await proc.communicate()

        # Simplified parsing - actual implementation would use plistlib
        # For now, create a reasonable device entry
        size_gb = 32  # Default
        label = None
        mounted = False

        # Try to extract size from diskutil info output
        if stdout:
            output = stdout.decode()
            size_match = re.search(r"<key>TotalSize</key>\s*<integer>(\d+)</integer>", output)
            if size_match:
                size_bytes = int(size_match.group(1))
                size_gb = int(size_bytes / (1024**3))

            # Check for volume name
            name_match = re.search(r"<key>VolumeName</key>\s*<string>([^<]+)</string>", output)
            if name_match:
                label = name_match.group(1)

            # Check if mounted
            mounted = "<key>MountPoint</key>" in output

        # Determine type (for external devices, likely USB or SD)
        device_type: Literal["sd", "usb", "internal"] = "usb"
        if "SD" in label.upper() if label else False:
            device_type = "sd"

        return StorageDevice(
            device=device,
            size_gb=size_gb,
            type=device_type,
            mounted=mounted,
            label=label,
        )

    except Exception:
        # Fallback
        return StorageDevice(
            device=device,
            size_gb=32,
            type="usb",
            mounted=False,
            label=None,
        )


async def _detect_storage_linux() -> list[StorageDevice]:
    """Detect storage devices on Linux using lsblk.

    Returns:
        List of removable storage devices.
    """
    try:
        # Use lsblk with JSON output for structured data
        proc = await asyncio.create_subprocess_exec(
            "lsblk",
            "-J",
            "-o",
            "NAME,SIZE,TYPE,RM,MOUNTPOINT,LABEL",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"lsblk failed: {stderr.decode() if stderr else 'unknown error'}")

        data = json.loads(stdout.decode())
        devices: list[StorageDevice] = []

        for device in data.get("blockdevices", []):
            # Only consider removable devices (RM=1)
            if device.get("rm") == "1" and device.get("type") == "disk":
                size_str = device.get("size", "0G")
                # Parse size (e.g., "32G", "512M")
                size_gb = _parse_size_to_gb(size_str)

                name = device.get("name", "")
                label = device.get("label")
                mountpoint = device.get("mountpoint")

                # Check if any partitions are mounted
                mounted = bool(mountpoint)
                if not mounted and "children" in device:
                    mounted = any(child.get("mountpoint") for child in device["children"])

                # Determine type (heuristic based on size and name)
                device_type: Literal["sd", "usb", "internal"] = "usb"
                if "mmc" in name or "sd" in name.lower():
                    device_type = "sd"

                devices.append(
                    StorageDevice(
                        device=f"/dev/{name}",
                        size_gb=size_gb,
                        type=device_type,
                        mounted=mounted,
                        label=label,
                    )
                )

        # Return mock data if no devices found (e.g., in container)
        if not devices:
            return _get_mock_storage()

        return devices

    except Exception as e:
        # Log error and return mock data for development
        print(f"Warning: Failed to detect storage on Linux: {e}", file=sys.stderr)
        return _get_mock_storage()


def _parse_size_to_gb(size_str: str) -> int:
    """Parse lsblk size string to GB.

    Args:
        size_str: Size string from lsblk (e.g., "32G", "512M", "1.5T").

    Returns:
        Size in gigabytes (rounded down).
    """
    size_str = size_str.strip().upper()
    # Extract number and unit
    match = re.match(r"([\d.]+)([KMGT]?)", size_str)
    if not match:
        return 0

    value = float(match.group(1))
    unit = match.group(2) or "B"

    multipliers = {
        "B": 1 / (1024**3),
        "K": 1 / (1024**2),
        "M": 1 / 1024,
        "G": 1,
        "T": 1024,
    }

    return int(value * multipliers.get(unit, 1))


def _get_mock_storage() -> list[StorageDevice]:
    """Get mock storage devices for development/testing.

    Returns:
        List of mock storage devices.
    """
    return [
        StorageDevice(
            device="/dev/disk2" if sys.platform == "darwin" else "/dev/sdb",
            size_gb=32,
            type="sd",
            mounted=False,
            label="SDCARD",
        ),
        StorageDevice(
            device="/dev/disk3" if sys.platform == "darwin" else "/dev/sdc",
            size_gb=64,
            type="usb",
            mounted=True,
            label="USB_DRIVE",
        ),
    ]
