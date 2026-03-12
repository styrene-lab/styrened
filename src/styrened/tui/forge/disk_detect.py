"""Disk detection service for macOS and Linux.

Extracted from styrene-edge. Detects external removable disks
(USB drives and SD cards) using platform-native tools.
"""
from __future__ import annotations


import json
import re
import subprocess

from styrened.tui.forge.models import DiskInfo


def detect_external_disks() -> list[DiskInfo]:
    """Detect external removable disks."""
    try:
        return _detect_macos()
    except FileNotFoundError:
        pass

    try:
        return _detect_linux()
    except FileNotFoundError:
        pass

    return []


def _detect_macos() -> list[DiskInfo]:
    """Detect external disks using diskutil on macOS."""
    result = subprocess.run(
        ["diskutil", "list", "external"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        return []

    disks: list[DiskInfo] = []

    # Get device names from output
    disk_devices = re.findall(r"(/dev/disk\d+)\s+\(external", result.stdout)

    for device in disk_devices:
        info = _get_disk_info_macos(device)
        if info:
            disks.append(info)

    return disks


def _get_disk_info_macos(device: str) -> DiskInfo | None:
    """Get detailed info for a single disk on macOS."""
    try:
        result = subprocess.run(
            ["diskutil", "info", device],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None

    name = "Unknown"
    size = "Unknown"
    media_type = "USB"

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("Media Name:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("Disk Size:") or line.startswith("Total Size:"):
            size_match = re.search(r"(\d+\.?\d*\s*[KMGT]B)", line)
            if size_match:
                size = size_match.group(1)
        elif line.startswith("Protocol:"):
            proto = line.split(":", 1)[1].strip().lower()
            if "usb" in proto:
                media_type = "USB"
            elif "sd" in proto or "mmc" in proto:
                media_type = "SD"

    return DiskInfo(device=device, name=name, size=size, media_type=media_type)


def _detect_linux() -> list[DiskInfo]:
    """Detect external disks using lsblk on Linux."""
    result = subprocess.run(
        ["lsblk", "-d", "-o", "NAME,SIZE,MODEL,TYPE,TRAN", "--json"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    disks: list[DiskInfo] = []
    for dev in data.get("blockdevices", []):
        tran = (dev.get("tran") or "").lower()
        if tran in ("usb", "mmc"):
            media_type = "USB" if tran == "usb" else "SD"
            model = (dev.get("model") or "").strip()
            disks.append(
                DiskInfo(
                    device=f"/dev/{dev['name']}",
                    name=model or "Unknown",
                    size=dev.get("size", "Unknown"),
                    media_type=media_type,
                )
            )

    return disks
