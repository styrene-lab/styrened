"""Configuration data models for Styrene TUI.

This module defines the hierarchical configuration structure used by
the TUI. Configuration is stored in YAML format at the XDG-compliant
location ~/.config/styrene/config.yaml.

The configuration follows a nested structure:
- TUIConfig: Display and interaction preferences
- FleetConfig: Fleet management settings
- ProvisioningDefaults: Default provisioning values
- MeshDefaults: Mesh network defaults
- CoreConfig: Core mesh and messaging settings (from styrene-core)
- AdvancedConfig: Debug and developer settings

All nested configs are combined into StyreneConfig as the root object.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Import core config models from styrene-core
from styrened.models.config import (
    APIConfig,
    ChatConfig,
    ConfigFieldError,
    ConfigLoadError,
    ConfigValidationError,
    CoreConfig,
    DeploymentMode,
    DiscoveryConfig,
    GatewayMode,
    InterfaceConfig,
    LogLevel,
    PeerConfig,
    ReticulumConfig,
    RPCConfig,
    ServerInterfaceConfig,
)


class ConfigValidationErrors(Exception):
    """Collection of validation errors from config loading.

    Defined locally since styrened dropped this class post-v0.3.0.
    """

    def __init__(self, errors: list[ConfigFieldError]) -> None:
        self.errors = errors
        messages = [str(e) for e in errors]
        super().__init__(f"Config validation failed: {'; '.join(messages)}")

# Re-export core config components for backward compatibility
__all__ = [
    # Core models (re-exported)
    "APIConfig",
    "ChatConfig",
    "ConfigFieldError",
    "ConfigLoadError",
    "ConfigValidationError",
    "ConfigValidationErrors",
    "CoreConfig",
    "DeploymentMode",
    "DiscoveryConfig",
    "GatewayMode",
    "InterfaceConfig",
    "LogLevel",
    "PeerConfig",
    "ReticulumConfig",
    "RPCConfig",
    "ServerInterfaceConfig",
    # TUI-specific models
    "ThemeMode",
    "TUIConfig",
    "FleetConfig",
    "ProvisioningDefaults",
    "MeshDefaults",
    "AdvancedConfig",
    "StyreneConfig",
]


# -----------------------------------------------------------------------------
# TUI-specific enums
# -----------------------------------------------------------------------------


class ThemeMode(Enum):
    """Available visual themes."""

    STYRENE = "styrene"


# -----------------------------------------------------------------------------
# TUI-specific configuration sections
# -----------------------------------------------------------------------------


@dataclass
class TUIConfig:
    """TUI display and interaction preferences.

    Attributes:
        theme: Visual theme for the interface.
        log_level: Logging verbosity.
        show_hardware_panel: Whether to show hardware info panel on dashboard.
        confirm_destructive: Require confirmation for destructive operations.
        use_ipc: Whether to use IPC mode (daemon subprocess) instead of in-process.
            None means auto-detect (try IPC first, fall back to legacy).
    """

    theme: ThemeMode = ThemeMode.STYRENE
    log_level: LogLevel = LogLevel.INFO
    show_hardware_panel: bool = True
    confirm_destructive: bool = True
    use_ipc: bool | None = None


@dataclass
class FleetConfig:
    """Fleet management settings.

    Attributes:
        edge_fleet_path: Path to edge-fleet repository clone.
            If set, enables fleet inventory integration.
        inventory_file: Relative path to inventory file within edge-fleet.
        auto_sync_inventory: Auto-update inventory after provisioning.
    """

    edge_fleet_path: Path | None = None
    inventory_file: str = "inventory/devices.yaml"
    auto_sync_inventory: bool = True


@dataclass
class ProvisioningDefaults:
    """Default values for device provisioning.

    Attributes:
        default_device_type: Default device type ID to pre-select.
        ssh_key_paths: SSH public key files to include on devices.
        default_hostname_prefix: Prefix for auto-generated hostnames.
    """

    default_device_type: str | None = None
    ssh_key_paths: list[Path] = field(default_factory=list)
    default_hostname_prefix: str = "node"


@dataclass
class MeshDefaults:
    """Default mesh network settings for provisioning.

    These values are used as defaults when provisioning new devices.
    They can be overridden per-device during provisioning.

    Attributes:
        enable: Whether mesh is enabled by default.
        mesh_id: Mesh network identifier (devices with same ID communicate).
        channel: Wireless channel (1-14, must match across mesh).
        gateway_mode: Default gateway mode.
        interface: Explicit interface or None for auto-detection.
    """

    enable: bool = True
    mesh_id: str = "styrene"
    channel: int = 6
    gateway_mode: GatewayMode = GatewayMode.CLIENT
    interface: str | None = None  # None = auto-detect at runtime


@dataclass
class AdvancedConfig:
    """Advanced and developer settings.

    Attributes:
        debug_mode: Enable debug features and verbose output.
        telemetry_enabled: Send anonymous usage statistics (future).
        config_version: Schema version for migration support.
        headless: Run in headless mode (no TUI).
    """

    debug_mode: bool = False
    telemetry_enabled: bool = False
    config_version: int = 1
    headless: bool = False


# -----------------------------------------------------------------------------
# Root configuration
# -----------------------------------------------------------------------------


@dataclass
class StyreneConfig:
    """Complete Styrene TUI configuration.

    This is the root configuration object containing all settings.
    It is serialized to/from ~/.config/styrene/config.yaml.

    The configuration is composed of:
    - Core settings (from CoreConfig in styrene-core)
    - TUI-specific settings (theme, fleet, provisioning, etc.)

    Attributes:
        core: Core mesh and messaging settings.
        tui: Display and interaction preferences.
        fleet: Fleet management settings.
        provisioning: Provisioning default values.
        mesh: Mesh network defaults.
        advanced: Debug and developer settings.
    """

    core: CoreConfig = field(default_factory=CoreConfig)
    tui: TUIConfig = field(default_factory=TUIConfig)
    fleet: FleetConfig = field(default_factory=FleetConfig)
    provisioning: ProvisioningDefaults = field(default_factory=ProvisioningDefaults)
    mesh: MeshDefaults = field(default_factory=MeshDefaults)
    advanced: AdvancedConfig = field(default_factory=AdvancedConfig)

    # Backward compatibility properties for accessing core config sections
    @property
    def reticulum(self) -> ReticulumConfig:
        """Access reticulum config (backward compatibility)."""
        return self.core.reticulum

    @property
    def rpc(self) -> RPCConfig:
        """Access RPC config (backward compatibility)."""
        return self.core.rpc

    @property
    def discovery(self) -> DiscoveryConfig:
        """Access discovery config (backward compatibility)."""
        return self.core.discovery

    @property
    def chat(self) -> ChatConfig:
        """Access chat config (backward compatibility)."""
        return self.core.chat

    @property
    def api(self) -> APIConfig:
        """Access API config (backward compatibility)."""
        return self.core.api
