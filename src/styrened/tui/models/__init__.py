"""Data models for Styrene TUI.

This package contains dataclasses representing the various data
structures used throughout the application.
"""

# Re-export from styrene-core (duplicates migrated)
from styrened.models.messages import Base, Message, get_session, init_db
from styrened.models.reticulum import (
    ReticulumIdentity,
    ReticulumInterface,
    ReticulumNotConfiguredError,
)
from styrened.models.reticulum import (
    ReticulumState as ReticulumStateConfig,
)
from styrened.rpc.messages import (
    ExecResult,
    StatusResponse,
)
from styrened.tui.models.config import (
    AdvancedConfig,
    ConfigLoadError,
    ConfigValidationError,
    ConfigValidationErrors,
    FleetConfig,
    GatewayMode,
    LogLevel,
    MeshDefaults,
    ProvisioningDefaults,
    ReticulumConfig,
    StyreneConfig,
    ThemeMode,
    TUIConfig,
)
from styrened.tui.models.device_hardware import Hardware
from styrened.tui.models.fleet import Device, DeviceStatus
from styrened.tui.models.hardware import (
    DiskInfo,
    DiskType,
    InterfaceCategory,
    NetworkInterface,
    NetworkInterfaceType,
    SystemInfo,
)
from styrened.tui.models.profiles import Profile
from styrened.tui.models.roles import Role

__all__ = [
    "AdvancedConfig",
    "Base",
    "ConfigLoadError",
    "ConfigValidationError",
    "ConfigValidationErrors",
    "Device",
    "DeviceStatus",
    "DiskInfo",
    "DiskType",
    "ExecResult",
    "FleetConfig",
    "GatewayMode",
    "Hardware",
    "InterfaceCategory",
    "LogLevel",
    "MeshDefaults",
    "Message",
    "NetworkInterface",
    "NetworkInterfaceType",
    "Profile",
    "ProvisioningDefaults",
    "ReticulumConfig",
    "ReticulumIdentity",
    "ReticulumInterface",
    "ReticulumNotConfiguredError",
    "ReticulumStateConfig",
    "Role",
    "StatusResponse",
    "StyreneConfig",
    "SystemInfo",
    "TUIConfig",
    "ThemeMode",
    "get_session",
    "init_db",
]
