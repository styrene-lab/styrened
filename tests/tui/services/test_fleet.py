"""Tests for fleet inventory management service."""

from datetime import datetime

import pytest

from styrened.tui.models.fleet import Device
from styrened.tui.services.fleet import (
    InventoryLoadError,
    add_device,
    create_sample_inventory,
    get_device,
    get_fleet_summary,
    load_inventory,
    save_inventory,
    update_device_status,
)


@pytest.fixture
def temp_inventory_file(tmp_path):
    """Create a temporary inventory file path (does not create the file)."""
    path = tmp_path / "test_inventory.yaml"
    yield path
    # Cleanup
    if path.exists():
        path.unlink()


@pytest.fixture
def sample_devices():
    """Create sample device list."""
    return [
        Device(
            name="test-device-1",
            profile="node",
            hardware="rpi-zero2w",
            status="online",
            last_seen=datetime(2024, 1, 15, 10, 30),
            reticulum_identity="abc123",
            ip_address="192.168.0.101",
        ),
        Device(
            name="test-device-2",
            profile="workstation",
            hardware="t100ta",
            status="offline",
            last_seen=datetime(2024, 1, 14, 15, 45),
        ),
        Device(
            name="test-device-3",
            profile="edge-router",
            hardware="libre-board",
            status="pending",
        ),
    ]


def test_load_inventory_empty_file(temp_inventory_file):
    """Test loading inventory from non-existent file returns empty list."""
    # Don't create the file
    inventory = load_inventory(temp_inventory_file)
    assert inventory == []


def test_save_and_load_inventory_roundtrip(temp_inventory_file, sample_devices):
    """Test saving and loading inventory preserves data."""
    # Save inventory
    save_inventory(sample_devices, temp_inventory_file)

    # Load it back
    loaded = load_inventory(temp_inventory_file)

    assert len(loaded) == len(sample_devices)

    # Check first device
    assert loaded[0].name == "test-device-1"
    assert loaded[0].profile == "node"
    assert loaded[0].hardware == "rpi-zero2w"
    assert loaded[0].status == "online"
    assert loaded[0].reticulum_identity == "abc123"
    assert loaded[0].ip_address == "192.168.0.101"

    # Check second device
    assert loaded[1].name == "test-device-2"
    assert loaded[1].status == "offline"

    # Check third device
    assert loaded[2].name == "test-device-3"
    assert loaded[2].status == "pending"


def test_load_inventory_malformed_yaml(temp_inventory_file):
    """Test loading malformed YAML raises error."""
    temp_inventory_file.write_text("{ this is not: valid: yaml ]")

    with pytest.raises(InventoryLoadError):
        load_inventory(temp_inventory_file)


def test_load_inventory_invalid_structure(temp_inventory_file):
    """Test loading inventory with invalid structure raises error."""
    # Write a list instead of dict
    temp_inventory_file.write_text("- item1\n- item2")

    with pytest.raises(InventoryLoadError):
        load_inventory(temp_inventory_file)


def test_add_device_to_empty_inventory(temp_inventory_file):
    """Test adding device to empty inventory."""
    device = Device(
        name="new-device",
        profile="node",
        hardware="rpi4",
        status="pending",
    )

    add_device(device, temp_inventory_file)

    loaded = load_inventory(temp_inventory_file)
    assert len(loaded) == 1
    assert loaded[0].name == "new-device"


def test_add_device_replaces_existing(temp_inventory_file, sample_devices):
    """Test adding device with existing name replaces it."""
    save_inventory(sample_devices, temp_inventory_file)

    # Add device with same name as first sample device
    updated_device = Device(
        name="test-device-1",
        profile="updated-profile",
        hardware="updated-hardware",
        status="error",
    )

    add_device(updated_device, temp_inventory_file)

    loaded = load_inventory(temp_inventory_file)
    assert len(loaded) == 3  # Still 3 devices

    # Find the updated device
    device = next(d for d in loaded if d.name == "test-device-1")
    assert device.profile == "updated-profile"
    assert device.hardware == "updated-hardware"
    assert device.status == "error"


def test_update_device_status(temp_inventory_file, sample_devices):
    """Test updating device status."""
    save_inventory(sample_devices, temp_inventory_file)

    # Update status to online
    update_device_status("test-device-2", "online", temp_inventory_file)

    loaded = load_inventory(temp_inventory_file)
    device = next(d for d in loaded if d.name == "test-device-2")
    assert device.status == "online"
    assert device.last_seen is not None  # Should be updated


def test_update_device_status_not_found(temp_inventory_file, sample_devices):
    """Test updating non-existent device raises error."""
    save_inventory(sample_devices, temp_inventory_file)

    with pytest.raises(ValueError):
        update_device_status("non-existent-device", "online", temp_inventory_file)


def test_get_device(temp_inventory_file, sample_devices):
    """Test retrieving specific device."""
    save_inventory(sample_devices, temp_inventory_file)

    device = get_device("test-device-2", temp_inventory_file)
    assert device is not None
    assert device.name == "test-device-2"
    assert device.profile == "workstation"


def test_get_device_not_found(temp_inventory_file, sample_devices):
    """Test retrieving non-existent device returns None."""
    save_inventory(sample_devices, temp_inventory_file)

    device = get_device("non-existent", temp_inventory_file)
    assert device is None


def test_get_fleet_summary(temp_inventory_file, sample_devices):
    """Test fleet summary counts."""
    save_inventory(sample_devices, temp_inventory_file)

    summary = get_fleet_summary(temp_inventory_file)

    assert summary["total"] == 3
    assert summary["online"] == 1
    assert summary["offline"] == 1
    assert summary["pending"] == 1
    assert summary["error"] == 0


def test_get_fleet_summary_empty(temp_inventory_file):
    """Test fleet summary with empty inventory."""
    summary = get_fleet_summary(temp_inventory_file)

    assert summary["total"] == 0
    assert summary["online"] == 0
    assert summary["offline"] == 0
    assert summary["pending"] == 0
    assert summary["error"] == 0


def test_create_sample_inventory(temp_inventory_file):
    """Test creating sample inventory."""
    create_sample_inventory(temp_inventory_file)

    loaded = load_inventory(temp_inventory_file)
    assert len(loaded) > 0

    # Check that devices have expected structure
    device = loaded[0]
    assert device.name
    assert device.profile
    assert device.hardware
    assert device.status in ["online", "offline", "pending", "error"]


def test_device_model_properties():
    """Test Device model properties."""
    device = Device(
        name="test",
        profile="node",
        hardware="rpi4",
        status="online",
        last_seen=datetime.now(),
    )

    assert device.is_online
    assert not device.is_offline
    assert not device.is_pending
    assert not device.has_error


def test_device_last_seen_display():
    """Test Device last_seen_display property."""
    # No last_seen
    device = Device(name="test", profile="node", hardware="rpi4", status="pending")
    assert device.last_seen_display == "-"

    # Recent timestamp
    device.last_seen = datetime.now()
    assert "ago" in device.last_seen_display or device.last_seen_display == "just now"
