"""Fleet inventory management service.

Manages the fleet device inventory, providing functions to load, save,
query, and update device information.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from styrened import paths
from styrened.tui.models.fleet import Device, DeviceStatus

# Default inventory location
DEFAULT_INVENTORY_PATH = paths.fleet_inventory()


class FleetInventoryError(Exception):
    """Base exception for fleet inventory errors."""

    pass


class InventoryNotFoundError(FleetInventoryError):
    """Raised when inventory file is not found."""

    pass


class InventoryLoadError(FleetInventoryError):
    """Raised when inventory file cannot be loaded or parsed."""

    pass


def _get_inventory_path(path: Path | None = None) -> Path:
    """Get the inventory file path, using default if not specified.

    Args:
        path: Optional explicit path to inventory file.

    Returns:
        Path to inventory file.
    """
    if path is not None:
        return path
    return DEFAULT_INVENTORY_PATH


def _parse_datetime(value: Any) -> datetime | None:
    """Parse datetime from various formats.

    Args:
        value: Value to parse (datetime, str, int, or None).

    Returns:
        Parsed datetime or None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # Try ISO format
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        # Unix timestamp
        return datetime.fromtimestamp(value)
    return None


def _device_to_dict(device: Device) -> dict[str, Any]:
    """Convert Device to dictionary for serialization.

    Args:
        device: Device to convert.

    Returns:
        Dictionary representation.
    """
    return {
        "name": device.name,
        "profile": device.profile,
        "hardware": device.hardware,
        "status": device.status,
        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
        "reticulum_identity": device.reticulum_identity,
        "ip_address": device.ip_address,
        "notes": device.notes,
    }


def _dict_to_device(data: dict[str, Any]) -> Device:
    """Convert dictionary to Device object.

    Args:
        data: Dictionary with device data.

    Returns:
        Device object.
    """
    return Device(
        name=data["name"],
        profile=data["profile"],
        hardware=data["hardware"],
        status=data.get("status", "pending"),
        last_seen=_parse_datetime(data.get("last_seen")),
        reticulum_identity=data.get("reticulum_identity"),
        ip_address=data.get("ip_address"),
        notes=data.get("notes"),
    )


def load_inventory(path: Path | None = None) -> list[Device]:
    """Load fleet inventory from file.

    The inventory file can be in YAML or JSON format. If the file doesn't
    exist, returns an empty list.

    Args:
        path: Optional path to inventory file. Uses default if not specified.

    Returns:
        List of Device objects.

    Raises:
        InventoryLoadError: If the file exists but cannot be loaded or parsed.
    """
    inventory_path = _get_inventory_path(path)

    if not inventory_path.exists():
        # Return empty inventory if file doesn't exist
        return []

    try:
        content = inventory_path.read_text()

        # Try YAML first, fall back to JSON
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                raise InventoryLoadError(f"Failed to parse inventory file: {e}") from e

        if not isinstance(data, dict):
            raise InventoryLoadError("Inventory file must contain a dictionary")

        devices_data = data.get("devices", [])
        if not isinstance(devices_data, list):
            raise InventoryLoadError("'devices' must be a list")

        devices = [_dict_to_device(device_data) for device_data in devices_data]
        return devices

    except OSError as e:
        raise InventoryLoadError(f"Failed to read inventory file: {e}") from e


def save_inventory(inventory: list[Device], path: Path | None = None) -> None:
    """Save fleet inventory to file.

    Args:
        inventory: List of Device objects to save.
        path: Optional path to inventory file. Uses default if not specified.

    Raises:
        InventoryLoadError: If the file cannot be written.
    """
    inventory_path = _get_inventory_path(path)

    # Ensure parent directory exists
    inventory_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = {
            "version": "1.0",
            "devices": [_device_to_dict(device) for device in inventory],
        }

        # Write as YAML for human readability
        content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
        inventory_path.write_text(content)

    except OSError as e:
        raise InventoryLoadError(f"Failed to write inventory file: {e}") from e


def add_device(device: Device, path: Path | None = None) -> None:
    """Add device to inventory.

    Loads the current inventory, adds the device, and saves it back.
    If a device with the same name exists, it will be replaced.

    Args:
        device: Device to add.
        path: Optional path to inventory file.

    Raises:
        InventoryLoadError: If the inventory cannot be loaded or saved.
    """
    inventory = load_inventory(path)

    # Remove existing device with same name if present
    inventory = [d for d in inventory if d.name != device.name]

    # Add new device
    inventory.append(device)

    save_inventory(inventory, path)


def update_device_status(name: str, status: DeviceStatus, path: Path | None = None) -> None:
    """Update device status in inventory.

    Args:
        name: Device name to update.
        status: New status.
        path: Optional path to inventory file.

    Raises:
        InventoryLoadError: If the inventory cannot be loaded or saved.
        ValueError: If device with given name is not found.
    """
    inventory = load_inventory(path)

    # Find and update device
    found = False
    for device in inventory:
        if device.name == name:
            device.status = status
            if status == "online":
                device.last_seen = datetime.now()
            found = True
            break

    if not found:
        raise ValueError(f"Device '{name}' not found in inventory")

    save_inventory(inventory, path)


def get_device(name: str, path: Path | None = None) -> Device | None:
    """Get a specific device from inventory.

    Args:
        name: Device name to retrieve.
        path: Optional path to inventory file.

    Returns:
        Device object or None if not found.

    Raises:
        InventoryLoadError: If the inventory cannot be loaded.
    """
    inventory = load_inventory(path)
    for device in inventory:
        if device.name == name:
            return device
    return None


def get_fleet_summary(path: Path | None = None) -> dict[str, int]:
    """Get fleet status summary counts.

    Args:
        path: Optional path to inventory file.

    Returns:
        Dictionary with counts: online, offline, pending, error, total.

    Raises:
        InventoryLoadError: If the inventory cannot be loaded.
    """
    inventory = load_inventory(path)

    summary = {
        "online": 0,
        "offline": 0,
        "pending": 0,
        "error": 0,
        "total": len(inventory),
    }

    for device in inventory:
        if device.is_online:
            summary["online"] += 1
        elif device.is_offline:
            summary["offline"] += 1
        elif device.is_pending:
            summary["pending"] += 1
        elif device.has_error:
            summary["error"] += 1

    return summary


def create_sample_inventory(path: Path | None = None) -> None:
    """Create a sample inventory file for testing.

    Args:
        path: Optional path to inventory file. Uses default if not specified.
    """
    sample_devices = [
        Device(
            name="rpi-01",
            profile="node",
            hardware="rpi-zero2w",
            status="online",
            last_seen=datetime.now(),
            reticulum_identity="a3f5d8e9b1c2",
            ip_address="192.168.0.101",
            notes="Test device 1",
        ),
        Device(
            name="rpi-02",
            profile="node",
            hardware="rpi-zero2w",
            status="online",
            last_seen=datetime.now(),
            reticulum_identity="b4e6c7d8a2f3",
            ip_address="192.168.0.102",
        ),
        Device(
            name="t100ta-01",
            profile="workstation",
            hardware="t100ta",
            status="offline",
            last_seen=datetime.now(),
            reticulum_identity="c5d7a8e9f3b4",
            ip_address="192.168.0.110",
        ),
        Device(
            name="x86-dev",
            profile="workstation",
            hardware="x86-generic",
            status="online",
            last_seen=datetime.now(),
            ip_address="192.168.0.120",
        ),
        Device(
            name="libre-01",
            profile="edge-router",
            hardware="libre-board",
            status="pending",
            notes="Awaiting provisioning",
        ),
    ]

    save_inventory(sample_devices, path)
