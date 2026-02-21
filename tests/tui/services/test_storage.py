"""Tests for storage detection service."""

import pytest

from styrened.tui.services.storage import StorageDevice, _parse_size_to_gb, detect_storage


def test_storage_device_properties():
    """Test StorageDevice computed properties."""
    device = StorageDevice(
        device="/dev/sdb",
        size_gb=32,
        type="sd",
        mounted=False,
        label="TEST_CARD",
    )

    assert device.display_name == "TEST_CARD (/dev/sdb)"
    assert device.display_size == "32.0 GB"


def test_storage_device_no_label():
    """Test StorageDevice without label."""
    device = StorageDevice(
        device="/dev/sdb",
        size_gb=64,
        type="usb",
        mounted=True,
        label=None,
    )

    assert device.display_name == "/dev/sdb"
    assert device.display_size == "64.0 GB"


def test_storage_device_small_size():
    """Test StorageDevice with size < 1GB."""
    device = StorageDevice(
        device="/dev/sdc",
        size_gb=0.5,
        type="usb",
        mounted=False,
        label=None,
    )

    assert device.display_size == "512 MB"


def test_parse_size_to_gb():
    """Test size string parsing."""
    assert _parse_size_to_gb("32G") == 32
    assert _parse_size_to_gb("1.5T") == 1536
    assert _parse_size_to_gb("512M") == 0
    assert _parse_size_to_gb("2048K") == 0
    assert _parse_size_to_gb("64") == 0  # No unit defaults to bytes


@pytest.mark.asyncio
async def test_detect_storage():
    """Test storage detection (returns mock data)."""
    devices = await detect_storage()

    # Should return at least mock devices
    assert len(devices) >= 1
    assert all(isinstance(d, StorageDevice) for d in devices)

    # Check that devices have required attributes
    for device in devices:
        assert device.device
        assert device.size_gb > 0
        assert device.type in ["sd", "usb", "internal"]
        assert isinstance(device.mounted, bool)
