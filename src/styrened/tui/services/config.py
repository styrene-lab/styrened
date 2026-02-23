"""Configuration management service for Styrene TUI.

This module provides functions to load, save, and validate the TUI
configuration. Configuration is stored in YAML format.

Typical usage:
    from styrened.tui.services.config import load_config, save_config

    # Load configuration (creates defaults if missing)
    config = load_config()

    # Modify and save
    config.tui.log_level = LogLevel.DEBUG
    save_config(config)
"""

import contextlib
from pathlib import Path
from typing import Any

import yaml

from styrened import paths
from styrened.models.config import ConfigFieldError
from styrened.tui.models.config import (
    ConfigLoadError,
    ConfigValidationErrors,
    DeploymentMode,
    GatewayMode,
    LogLevel,
    PeerConfig,
    StyreneConfig,
    ThemeMode,
)

# Application identifiers for platformdirs
APP_NAME = "styrene"
APP_AUTHOR: None | str = None  # No author subdirectory

# Current configuration schema version
CURRENT_CONFIG_VERSION = 1


# -----------------------------------------------------------------------------
# Directory path functions
# -----------------------------------------------------------------------------


def get_config_dir() -> Path:
    """Return the configuration directory path.

    .. deprecated::
        Use ``paths.config_dir()`` directly.
    """
    return paths.config_dir()


def get_data_dir() -> Path:
    """Return the data directory path.

    .. deprecated::
        Use ``paths.data_dir()`` directly.
    """
    return paths.data_dir()


def get_cache_dir() -> Path:
    """Return the cache directory path.

    .. deprecated::
        Use ``paths.cache_dir()`` directly.
    """
    return paths.cache_dir()


def get_log_dir() -> Path:
    """Return the log directory path.

    .. deprecated::
        Use ``paths.log_dir()`` directly.
    """
    return paths.log_dir()


def get_config_path() -> Path:
    """Return the full path to the TUI configuration file."""
    return paths.tui_config_file()


def config_exists() -> bool:
    """Check if a TUI configuration file exists."""
    return get_config_path().exists()


def ensure_directories() -> None:
    """Ensure all application directories exist.

    .. deprecated::
        Use ``paths.ensure_directories()`` directly.
    """
    paths.ensure_directories()


# -----------------------------------------------------------------------------
# Default configuration
# -----------------------------------------------------------------------------


def get_default_config() -> StyreneConfig:
    """Return a StyreneConfig with all default values.

    Auto-detects common SSH key paths and includes them if they exist.
    Pre-configures the Styrene Community Hub for fleet coordination.

    Returns:
        StyreneConfig instance with sensible defaults.
    """
    config = StyreneConfig()

    # Auto-detect common SSH key paths
    home = Path.home()
    common_keys = [
        home / ".ssh" / "id_ed25519.pub",
        home / ".ssh" / "id_rsa.pub",
    ]
    config.provisioning.ssh_key_paths = [k for k in common_keys if k.exists()]

    # Pre-configure Styrene Community Hub connection
    # Hub details retrieved from brutus K3s cluster:
    #   Host: 192.168.0.102:4242 (LoadBalancer)
    #   Identity: 559c71c512c7376a5202e4c5b7043113
    #   LXMF Propagation Destination: 6fc8bf22aa293588c9bf8d7488102e95
    config.reticulum.hub_enabled = True
    config.reticulum.hub_address = "6fc8bf22aa293588c9bf8d7488102e95"
    config.reticulum.hub_announce_interval = 60

    # Add TCP client interface to connect to hub
    hub_peer = PeerConfig(
        host="192.168.0.102",
        port=4242,
        name="Styrene Community Hub"
    )
    config.reticulum.interfaces.peers.append(hub_peer)

    return config


# -----------------------------------------------------------------------------
# YAML serialization helpers
# -----------------------------------------------------------------------------


def _parse_config_dict(data: dict[str, Any]) -> StyreneConfig:
    """Parse a dictionary into a StyreneConfig.

    Handles partial configs by merging with defaults. Unknown keys are
    silently ignored for forward compatibility.

    Args:
        data: Dictionary from YAML parsing.

    Returns:
        StyreneConfig populated from data.
    """
    config = get_default_config()

    # TUI settings
    if "tui" in data and isinstance(data["tui"], dict):
        tui_data = data["tui"]
        if "theme" in tui_data:
            with contextlib.suppress(ValueError):
                config.tui.theme = ThemeMode(tui_data["theme"])
        if "log_level" in tui_data:
            with contextlib.suppress(ValueError):
                config.tui.log_level = LogLevel(tui_data["log_level"])
        if "show_hardware_panel" in tui_data:
            config.tui.show_hardware_panel = bool(tui_data["show_hardware_panel"])
        if "confirm_destructive" in tui_data:
            config.tui.confirm_destructive = bool(tui_data["confirm_destructive"])
        if "use_ipc" in tui_data:
            val = tui_data["use_ipc"]
            config.tui.use_ipc = None if val is None else bool(val)

    # Fleet settings
    if "fleet" in data and isinstance(data["fleet"], dict):
        fleet_data = data["fleet"]
        if fleet_data.get("edge_fleet_path"):
            config.fleet.edge_fleet_path = Path(fleet_data["edge_fleet_path"]).expanduser()
        if "inventory_file" in fleet_data:
            config.fleet.inventory_file = str(fleet_data["inventory_file"])
        if "auto_sync_inventory" in fleet_data:
            config.fleet.auto_sync_inventory = bool(fleet_data["auto_sync_inventory"])

    # Provisioning defaults
    if "provisioning" in data and isinstance(data["provisioning"], dict):
        prov_data = data["provisioning"]
        if "default_device_type" in prov_data:
            config.provisioning.default_device_type = prov_data["default_device_type"]
        if "ssh_key_paths" in prov_data and isinstance(prov_data["ssh_key_paths"], list):
            config.provisioning.ssh_key_paths = [
                Path(p).expanduser() for p in prov_data["ssh_key_paths"] if p
            ]
        if "default_hostname_prefix" in prov_data:
            config.provisioning.default_hostname_prefix = str(prov_data["default_hostname_prefix"])

    # Mesh defaults
    if "mesh" in data and isinstance(data["mesh"], dict):
        mesh_data = data["mesh"]
        if "enable" in mesh_data:
            config.mesh.enable = bool(mesh_data["enable"])
        if "mesh_id" in mesh_data:
            config.mesh.mesh_id = str(mesh_data["mesh_id"])
        if "channel" in mesh_data:
            config.mesh.channel = int(mesh_data["channel"])
        if "gateway_mode" in mesh_data:
            with contextlib.suppress(ValueError):
                config.mesh.gateway_mode = GatewayMode(mesh_data["gateway_mode"])
        if "interface" in mesh_data:
            config.mesh.interface = mesh_data["interface"]

    # Reticulum settings
    if "reticulum" in data and isinstance(data["reticulum"], dict):
        ret_data = data["reticulum"]
        if ret_data.get("config_path_override"):
            config.reticulum.config_path_override = Path(
                ret_data["config_path_override"]
            ).expanduser()
        if "auto_initialize" in ret_data:
            config.reticulum.auto_initialize = bool(ret_data["auto_initialize"])
        if "mode" in ret_data:
            with contextlib.suppress(ValueError):
                config.reticulum.mode = DeploymentMode(ret_data["mode"])
        if "enable_transport" in ret_data and ret_data["enable_transport"] is not None:
            config.reticulum.enable_transport = bool(ret_data["enable_transport"])
        if ret_data.get("operator_identity_path"):
            config.reticulum.operator_identity_path = Path(
                ret_data["operator_identity_path"]
            ).expanduser()
        if "announce_interval" in ret_data:
            config.reticulum.announce_interval = int(ret_data["announce_interval"])

        # Parse interfaces
        if "interfaces" in ret_data and isinstance(ret_data["interfaces"], dict):
            int_data = ret_data["interfaces"]
            if "auto" in int_data:
                config.reticulum.interfaces.auto = bool(int_data["auto"])

            # Server interface
            if "server" in int_data and isinstance(int_data["server"], dict):
                srv_data = int_data["server"]
                if "enabled" in srv_data:
                    config.reticulum.interfaces.server.enabled = bool(srv_data["enabled"])
                if "listen_ip" in srv_data:
                    config.reticulum.interfaces.server.listen_ip = str(srv_data["listen_ip"])
                if "port" in srv_data:
                    config.reticulum.interfaces.server.port = int(srv_data["port"])

            # Peers
            if "peers" in int_data and isinstance(int_data["peers"], list):
                peers = []
                for peer_data in int_data["peers"]:
                    if isinstance(peer_data, dict) and "host" in peer_data:
                        peers.append(
                            PeerConfig(
                                host=str(peer_data["host"]),
                                port=int(peer_data.get("port", 4242)),
                                name=peer_data.get("name"),
                            )
                        )
                config.reticulum.interfaces.peers = peers

        if "hub_enabled" in ret_data:
            config.reticulum.hub_enabled = bool(ret_data["hub_enabled"])
        if "hub_address" in ret_data:
            config.reticulum.hub_address = ret_data["hub_address"]

    # RPC settings
    if "rpc" in data and isinstance(data["rpc"], dict):
        rpc_data = data["rpc"]
        if "enabled" in rpc_data:
            config.rpc.enabled = bool(rpc_data["enabled"])
        if "relay_mode" in rpc_data:
            config.rpc.relay_mode = bool(rpc_data["relay_mode"])
        if "allow_command_execution" in rpc_data:
            config.rpc.allow_command_execution = bool(rpc_data["allow_command_execution"])

    # Discovery settings
    if "discovery" in data and isinstance(data["discovery"], dict):
        discovery_data = data["discovery"]
        if "enabled" in discovery_data:
            config.discovery.enabled = bool(discovery_data["enabled"])
        if "auto_announce" in discovery_data:
            config.discovery.auto_announce = bool(discovery_data["auto_announce"])

    # API settings
    if "api" in data and isinstance(data["api"], dict):
        api_data = data["api"]
        if "enabled" in api_data:
            config.api.enabled = bool(api_data["enabled"])
        if "host" in api_data:
            config.api.host = str(api_data["host"])
        if "port" in api_data:
            config.api.port = int(api_data["port"])

    # Advanced settings
    if "advanced" in data and isinstance(data["advanced"], dict):
        adv_data = data["advanced"]
        if "debug_mode" in adv_data:
            config.advanced.debug_mode = bool(adv_data["debug_mode"])
        if "telemetry_enabled" in adv_data:
            config.advanced.telemetry_enabled = bool(adv_data["telemetry_enabled"])
        if "headless" in adv_data:
            config.advanced.headless = bool(adv_data["headless"])
        if "config_version" in adv_data:
            config.advanced.config_version = int(adv_data["config_version"])

    return config


def _config_to_dict(config: StyreneConfig) -> dict[str, Any]:
    """Convert a StyreneConfig to a dictionary for YAML serialization.

    Args:
        config: Configuration to serialize.

    Returns:
        Dictionary suitable for YAML dump.
    """
    return {
        "tui": {
            "theme": config.tui.theme.value,
            "log_level": config.tui.log_level.value,
            "show_hardware_panel": config.tui.show_hardware_panel,
            "confirm_destructive": config.tui.confirm_destructive,
            "use_ipc": config.tui.use_ipc,
        },
        "fleet": {
            "edge_fleet_path": (
                str(config.fleet.edge_fleet_path) if config.fleet.edge_fleet_path else None
            ),
            "inventory_file": config.fleet.inventory_file,
            "auto_sync_inventory": config.fleet.auto_sync_inventory,
        },
        "provisioning": {
            "default_device_type": config.provisioning.default_device_type,
            "ssh_key_paths": [str(p) for p in config.provisioning.ssh_key_paths],
            "default_hostname_prefix": config.provisioning.default_hostname_prefix,
        },
        "mesh": {
            "enable": config.mesh.enable,
            "mesh_id": config.mesh.mesh_id,
            "channel": config.mesh.channel,
            "gateway_mode": config.mesh.gateway_mode.value,
            "interface": config.mesh.interface,
        },
        "reticulum": {
            "config_path_override": (
                str(config.reticulum.config_path_override)
                if config.reticulum.config_path_override
                else None
            ),
            "auto_initialize": config.reticulum.auto_initialize,
            "mode": config.reticulum.mode.value,
            "enable_transport": config.reticulum.enable_transport,
            "operator_identity_path": (
                str(config.reticulum.operator_identity_path)
                if config.reticulum.operator_identity_path
                else None
            ),
            "announce_interval": config.reticulum.announce_interval,
            "interfaces": {
                "auto": config.reticulum.interfaces.auto,
                "server": {
                    "enabled": config.reticulum.interfaces.server.enabled,
                    "listen_ip": config.reticulum.interfaces.server.listen_ip,
                    "port": config.reticulum.interfaces.server.port,
                },
                "peers": [
                    {
                        "host": peer.host,
                        "port": peer.port,
                        "name": peer.name,
                    }
                    for peer in config.reticulum.interfaces.peers
                ],
            },
            "hub_enabled": config.reticulum.hub_enabled,
            "hub_address": config.reticulum.hub_address,
        },
        "rpc": {
            "enabled": config.rpc.enabled,
            "relay_mode": config.rpc.relay_mode,
            "allow_command_execution": config.rpc.allow_command_execution,
        },
        "discovery": {
            "enabled": config.discovery.enabled,
            "auto_announce": config.discovery.auto_announce,
        },
        "api": {
            "enabled": config.api.enabled,
            "host": config.api.host,
            "port": config.api.port,
        },
        "advanced": {
            "debug_mode": config.advanced.debug_mode,
            "telemetry_enabled": config.advanced.telemetry_enabled,
            "headless": config.advanced.headless,
            "config_version": config.advanced.config_version,
        },
    }


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------


def validate_config(config: StyreneConfig) -> list[ConfigFieldError]:
    """Validate a configuration and return any errors.

    Checks for:
    - Paths that exist (when set)
    - Valid value ranges (channel 1-14)
    - Valid enum values
    - LXMF address format (32 hex chars)

    Args:
        config: Configuration to validate.

    Returns:
        List of validation errors (empty if valid).
    """
    errors: list[ConfigFieldError] = []

    # Validate edge_fleet_path if set
    if config.fleet.edge_fleet_path:
        if not config.fleet.edge_fleet_path.exists():
            errors.append(
                ConfigFieldError(
                    field="fleet.edge_fleet_path",
                    message="Directory does not exist",
                    value=str(config.fleet.edge_fleet_path),
                )
            )
        elif not config.fleet.edge_fleet_path.is_dir():
            errors.append(
                ConfigFieldError(
                    field="fleet.edge_fleet_path",
                    message="Path is not a directory",
                    value=str(config.fleet.edge_fleet_path),
                )
            )

    # Validate SSH key paths
    for i, key_path in enumerate(config.provisioning.ssh_key_paths):
        if not key_path.exists():
            errors.append(
                ConfigFieldError(
                    field=f"provisioning.ssh_key_paths[{i}]",
                    message="SSH key file does not exist",
                    value=str(key_path),
                )
            )

    # Validate mesh channel (standard 2.4GHz channels)
    if not 1 <= config.mesh.channel <= 14:
        errors.append(
            ConfigFieldError(
                field="mesh.channel",
                message="Channel must be between 1 and 14",
                value=str(config.mesh.channel),
            )
        )

    # Validate reticulum config path override if set
    if config.reticulum.config_path_override and not config.reticulum.config_path_override.exists():
        errors.append(
            ConfigFieldError(
                field="reticulum.config_path_override",
                message="Directory does not exist",
                value=str(config.reticulum.config_path_override),
            )
        )

    # Validate hub address format if provided (Phase 2)
    if config.reticulum.hub_address:
        addr = config.reticulum.hub_address
        if len(addr) != 32:
            errors.append(
                ConfigFieldError(
                    field="reticulum.hub_address",
                    message="LXMF address must be 32 hexadecimal characters",
                    value=addr[:8] + "..." if len(addr) > 8 else addr,
                )
            )
        elif not all(c in "0123456789abcdefABCDEF" for c in addr):
            errors.append(
                ConfigFieldError(
                    field="reticulum.hub_address",
                    message="LXMF address must contain only hexadecimal characters",
                    value=addr[:8] + "...",
                )
            )

    return errors


# -----------------------------------------------------------------------------
# Load and save
# -----------------------------------------------------------------------------


def load_config() -> StyreneConfig:
    """Load configuration from file, creating defaults if needed.

    This is the primary entry point for loading configuration.
    If no config exists, returns defaults (does not create file).

    Returns:
        StyreneConfig loaded from file or defaults.

    Raises:
        ConfigLoadError: If config file exists but cannot be parsed.
        ConfigValidationErrors: If config is invalid.
    """
    config_path = get_config_path()

    if not config_path.exists():
        return get_default_config()

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ConfigLoadError(f"Invalid YAML syntax: {e}", config_path) from e
    except OSError as e:
        raise ConfigLoadError(f"Cannot read config file: {e}", config_path) from e

    config = _parse_config_dict(data)

    # Migrate if needed
    if config.advanced.config_version < CURRENT_CONFIG_VERSION:
        config = _migrate_config(config)

    # Validate
    errors = validate_config(config)
    if errors:
        raise ConfigValidationErrors(errors)

    return config


def save_config(config: StyreneConfig) -> None:
    """Save configuration to file.

    Creates the configuration directory if it doesn't exist.
    Validates before saving to prevent writing invalid config.

    Args:
        config: Configuration to save.

    Raises:
        ConfigValidationErrors: If config is invalid.
        OSError: If file cannot be written.
    """
    # Validate before saving
    errors = validate_config(config)
    if errors:
        raise ConfigValidationErrors(errors)

    # Ensure config directory exists
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict and save
    data = _config_to_dict(config)

    with open(config_path, "w") as f:
        # Add header comment
        f.write("# Styrene TUI Configuration\n")
        f.write(f"# Location: {config_path}\n")
        f.write("#\n")
        f.write("# Edit this file or use the Settings screen (press 's').\n")
        f.write("# See documentation for all available options.\n\n")
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)


def create_default_config() -> StyreneConfig:
    """Create and save a default configuration file.

    This is useful for first-time setup or resetting to defaults.

    Returns:
        The newly created default configuration.
    """
    config = get_default_config()
    save_config(config)
    return config


# -----------------------------------------------------------------------------
# Migration
# -----------------------------------------------------------------------------


def _migrate_config(config: StyreneConfig) -> StyreneConfig:
    """Migrate configuration to current version.

    Called automatically when loading a config with an older version.
    Migration happens incrementally through each version.

    Args:
        config: Configuration from older version.

    Returns:
        Configuration updated to current version.
    """
    version = config.advanced.config_version

    # Version 0 -> 1: Initial version, no migration needed
    if version < 1:
        pass

    # Future migrations would be added here:
    # if version < 2:
    #     # Migration from v1 to v2
    #     config.new_field = derive_from_old(config)

    config.advanced.config_version = CURRENT_CONFIG_VERSION
    return config


# -----------------------------------------------------------------------------
# Reticulum config persistence
# -----------------------------------------------------------------------------


def get_rns_config_dir() -> Path:
    """Get or determine Reticulum config directory.

    Priority:
    1. ~/.config/reticulum (XDG-compliant, preferred)
    2. ~/.reticulum (legacy fallback)
    3. /etc/reticulum (system-wide, read-only for users)

    Returns:
        Path to use for RNS config.
    """
    # Check XDG location first (preferred)
    xdg_path = Path.home() / ".config" / "reticulum"
    if xdg_path.exists():
        return xdg_path

    # Check legacy location
    legacy_path = Path.home() / ".reticulum"
    if legacy_path.exists():
        return legacy_path

    # Default to XDG for new installations
    return xdg_path


def rns_config_exists() -> bool:
    """Check if Reticulum config exists at any standard location.

    Returns:
        True if RNS config file exists.
    """
    search_paths = [
        Path("/etc/reticulum/config"),
        Path.home() / ".config" / "reticulum" / "config",
        Path.home() / ".reticulum" / "config",
    ]

    return any(path.exists() for path in search_paths)


def save_rns_config(config: StyreneConfig) -> Path:
    """Generate and save Reticulum config based on Styrene settings.

    Creates RNS config at ~/.config/reticulum/config if it doesn't exist.

    Args:
        config: Styrene configuration with deployment mode and interface settings.

    Returns:
        Path where RNS config was written.

    Raises:
        OSError: If config cannot be written.
    """
    from styrened.tui.services.reticulum import generate_rns_config

    # Determine where to write
    rns_dir = get_rns_config_dir()
    rns_config_path = rns_dir / "config"

    # Create directory if needed
    rns_dir.mkdir(parents=True, exist_ok=True)

    # Generate RNS config content
    config_content = generate_rns_config(config)

    # Write config
    with open(rns_config_path, "w") as f:
        f.write("# Reticulum Configuration\n")
        f.write("# Generated by Styrene\n")
        f.write(f"# Mode: {config.reticulum.mode.value}\n")
        f.write("#\n")
        f.write("# Edit this file or use Styrene CLI flags to change settings.\n\n")
        f.write(config_content)

    return rns_config_path


def update_styrene_config_from_cli(
    config: StyreneConfig,
    mode: DeploymentMode | None = None,
    server_port: int | None = None,
    peers: list[PeerConfig] | None = None,
    api_port: int | None = None,
    headless: bool = False,
) -> StyreneConfig:
    """Update config with CLI overrides and persist changes.

    Args:
        config: Base configuration to update.
        mode: Deployment mode override.
        server_port: TCP server port override.
        peers: Peer list override.
        api_port: API port override.
        headless: Headless mode flag.

    Returns:
        Updated configuration.
    """
    # Apply overrides
    if mode:
        config.reticulum.mode = mode

    if headless:
        config.advanced.headless = True

    if server_port:
        config.reticulum.interfaces.server.port = server_port
        if config.reticulum.mode == DeploymentMode.HUB:
            config.reticulum.interfaces.server.enabled = True

    if peers:
        config.reticulum.interfaces.peers.extend(peers)

    if api_port:
        config.api.enabled = True
        config.api.port = api_port

    # Auto-enable server in hub mode
    if config.reticulum.mode == DeploymentMode.HUB:
        config.reticulum.interfaces.server.enabled = True

    # Save updated config
    save_config(config)

    return config
