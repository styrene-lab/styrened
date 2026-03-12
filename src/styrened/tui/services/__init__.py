"""Service layer for Styrene TUI.

This package contains service modules that handle business logic,
data loading, and external interactions.
"""
from __future__ import annotations


from styrened.tui.services.config import (
    config_exists,
    create_default_config,
    ensure_directories,
    get_config_dir,
    get_config_path,
    get_data_dir,
    get_default_config,
    get_log_dir,
    load_config,
    save_config,
    validate_config,
)
from styrened.tui.services.fleet import (
    FleetInventoryError,
    InventoryLoadError,
    InventoryNotFoundError,
    add_device,
    create_sample_inventory,
    get_device,
    get_fleet_summary,
    load_inventory,
    save_inventory,
    update_device_status,
)
from styrened.tui.services.hardware import (
    PlatformNotSupportedError,
    get_disks,
    get_network_interfaces,
    get_system_info,
)
from styrened.tui.services.reticulum import (
    discover_devices,
    ensure_operator_identity,
    get_operator_identity,
    get_reticulum_config,
    get_reticulum_status,
    is_reticulum_configured,
)

__all__ = [
    # Fleet service
    "FleetInventoryError",
    "InventoryLoadError",
    "InventoryNotFoundError",
    # Hardware service
    "PlatformNotSupportedError",
    "add_device",
    # Config service
    "config_exists",
    "create_default_config",
    "create_sample_inventory",
    # Reticulum service
    "discover_devices",
    "ensure_directories",
    "ensure_operator_identity",
    "get_config_dir",
    "get_config_path",
    "get_data_dir",
    "get_default_config",
    "get_device",
    "get_disks",
    "get_fleet_summary",
    "get_log_dir",
    "get_network_interfaces",
    "get_operator_identity",
    "get_reticulum_config",
    "get_reticulum_status",
    "get_system_info",
    "is_reticulum_configured",
    "load_config",
    "load_inventory",
    "save_config",
    "save_inventory",
    "update_device_status",
    "validate_config",
]
