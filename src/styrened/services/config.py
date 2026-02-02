"""Core configuration service for headless Styrene applications.

This module provides functions to load and save CoreConfig for headless
applications. For TUI applications, use styrene.services.config instead.
"""

from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir

from styrened.models.config import (
    ConfigLoadError,
    CoreConfig,
    DeploymentMode,
    PropagationNodeConfig,
)


def _parse_bool(value: Any) -> bool:
    """Parse boolean from YAML value, handling string representations.

    YAML can represent booleans as actual bools or strings. Python's bool()
    incorrectly converts non-empty strings to True (e.g., bool("false") == True).
    This function handles common string representations correctly.

    Args:
        value: Value to parse (bool, str, or other).

    Returns:
        Boolean interpretation of the value.

    Examples:
        >>> _parse_bool(True)
        True
        >>> _parse_bool("false")
        False
        >>> _parse_bool("yes")
        True
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "on")
    return bool(value)


def get_config_dir() -> Path:
    """Return the configuration directory path.

    Returns:
        Path to configuration directory (~/.styrene/).
    """
    return Path(user_config_dir("styrene"))


def get_data_dir() -> Path:
    """Return the data directory path.

    Returns:
        Path to data directory (~/.local/share/styrene/).
    """
    from platformdirs import user_data_dir

    return Path(user_data_dir("styrene", "styrene-lab"))


def get_cache_dir() -> Path:
    """Return the cache directory path.

    Returns:
        Path to cache directory (~/.cache/styrene/).
    """
    from platformdirs import user_cache_dir

    return Path(user_cache_dir("styrene", "styrene-lab"))


def get_log_dir() -> Path:
    """Return the log directory path.

    Returns:
        Path to log directory (~/.local/share/styrene/logs/).
    """
    return get_data_dir() / "logs"


def ensure_directories() -> None:
    """Create necessary directories if they don't exist."""
    get_config_dir().mkdir(parents=True, exist_ok=True)
    get_data_dir().mkdir(parents=True, exist_ok=True)
    get_cache_dir().mkdir(parents=True, exist_ok=True)
    get_log_dir().mkdir(parents=True, exist_ok=True)


def get_default_core_config() -> CoreConfig:
    """Return a CoreConfig with default values.

    Returns:
        CoreConfig instance with sensible defaults for headless mode.
    """
    config = CoreConfig()
    # Headless mode defaults
    config.reticulum.mode = DeploymentMode.STANDALONE
    config.rpc.enabled = True
    config.discovery.enabled = True
    config.discovery.auto_announce = True
    config.chat.enabled = True
    config.chat.auto_reply_enabled = True
    return config


def load_core_config(config_path: Path | None = None) -> CoreConfig:
    """Load core configuration from YAML file.

    Looks for config in this order:
    1. Explicit config_path argument
    2. STYRENE_CONFIG_DIR env var + "config.yaml"
    3. Default location: ~/.config/styrene/core-config.yaml

    Args:
        config_path: Optional path to config file. If None, uses default location.

    Returns:
        CoreConfig instance loaded from file, or defaults if file doesn't exist.

    Raises:
        ConfigLoadError: If config file exists but cannot be parsed.
    """
    import os

    from styrened.models.config import (
        PeerConfig,
        ServerInterfaceConfig,
    )

    if config_path is None:
        # Check for STYRENE_CONFIG_DIR env var (used in K8s deployments)
        env_config_dir = os.environ.get("STYRENE_CONFIG_DIR")
        if env_config_dir:
            config_path = Path(env_config_dir) / "config.yaml"
        else:
            config_path = get_config_dir() / "core-config.yaml"

    if not config_path.exists():
        return get_default_core_config()

    try:
        with config_path.open() as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise ConfigLoadError(f"Failed to load config from {config_path}: {e}", config_path) from e

    if not isinstance(data, dict):
        return get_default_core_config()

    # Parse CoreConfig from dictionary
    config = CoreConfig()

    # Parse reticulum section
    if "reticulum" in data and isinstance(data["reticulum"], dict):
        ret = data["reticulum"]
        if "mode" in ret:
            try:
                config.reticulum.mode = DeploymentMode(ret["mode"])
            except ValueError:
                pass  # Keep default
        if "announce_interval" in ret:
            config.reticulum.announce_interval = int(ret["announce_interval"])
        if "enable_transport" in ret:
            config.reticulum.enable_transport = _parse_bool(ret["enable_transport"])

        # Parse config_path_override (new in v0.3.5)
        if "config_path_override" in ret:
            override = ret["config_path_override"]
            # Handle null, empty string, whitespace-only, or "null" string as None
            # Also handle non-string types (e.g., YAML integers) gracefully
            if override is None:
                config.reticulum.config_path_override = None
            elif not isinstance(override, str):
                # Non-string types (int, float, etc.) - ignore with warning
                import logging

                logging.getLogger(__name__).warning(
                    f"config_path_override has invalid type {type(override).__name__}, ignoring"
                )
                config.reticulum.config_path_override = None
            elif override.strip() == "" or override.strip().lower() == "null":
                config.reticulum.config_path_override = None
            else:
                # Expand ~ to home directory
                config.reticulum.config_path_override = Path(override).expanduser()

        # Parse interfaces
        if "interfaces" in ret and isinstance(ret["interfaces"], dict):
            ifaces = ret["interfaces"]
            if "auto" in ifaces:
                config.reticulum.interfaces.auto = _parse_bool(ifaces["auto"])

            # Parse server interface
            if "server" in ifaces and isinstance(ifaces["server"], dict):
                srv = ifaces["server"]
                config.reticulum.interfaces.server = ServerInterfaceConfig(
                    enabled=_parse_bool(srv.get("enabled", False)),
                    listen_ip=str(srv.get("listen_ip", "0.0.0.0")),
                    port=int(srv.get("port", 4242)),
                )

            # Parse peers list
            if "peers" in ifaces and isinstance(ifaces["peers"], list):
                peers = []
                for p in ifaces["peers"]:
                    if isinstance(p, dict) and "host" in p:
                        peers.append(
                            PeerConfig(
                                host=str(p["host"]),
                                port=int(p.get("port", 4242)),
                                name=p.get("name"),
                            )
                        )
                config.reticulum.interfaces.peers = peers

    # Parse rpc section
    if "rpc" in data and isinstance(data["rpc"], dict):
        rpc = data["rpc"]
        if "enabled" in rpc:
            config.rpc.enabled = _parse_bool(rpc["enabled"])
        if "relay_mode" in rpc:
            config.rpc.relay_mode = _parse_bool(rpc["relay_mode"])
        if "allow_command_execution" in rpc:
            config.rpc.allow_command_execution = _parse_bool(rpc["allow_command_execution"])

    # Parse discovery section
    if "discovery" in data and isinstance(data["discovery"], dict):
        disc = data["discovery"]
        if "enabled" in disc:
            config.discovery.enabled = _parse_bool(disc["enabled"])
        if "auto_announce" in disc:
            config.discovery.auto_announce = _parse_bool(disc["auto_announce"])

    # Parse chat section
    if "chat" in data and isinstance(data["chat"], dict):
        chat = data["chat"]
        if "enabled" in chat:
            config.chat.enabled = _parse_bool(chat["enabled"])
        if "auto_reply_enabled" in chat:
            config.chat.auto_reply_enabled = _parse_bool(chat["auto_reply_enabled"])
        if "auto_reply_message" in chat:
            config.chat.auto_reply_message = str(chat["auto_reply_message"])
        if "auto_reply_cooldown" in chat:
            config.chat.auto_reply_cooldown = int(chat["auto_reply_cooldown"])
        if "persist_messages" in chat:
            config.chat.persist_messages = _parse_bool(chat["persist_messages"])

    # Parse api section
    if "api" in data and isinstance(data["api"], dict):
        api = data["api"]
        if "enabled" in api:
            config.api.enabled = _parse_bool(api["enabled"])
        if "host" in api:
            config.api.host = str(api["host"])
        if "port" in api:
            config.api.port = int(api["port"])

    # Parse identity section (ecosystem appearance)
    if "identity" in data and isinstance(data["identity"], dict):
        ident = data["identity"]
        if "display_name" in ident and ident["display_name"]:
            config.identity.display_name = str(ident["display_name"])
        if "icon" in ident and ident["icon"]:
            config.identity.icon = str(ident["icon"])

    # Parse lxmf section
    if "lxmf" in data and isinstance(data["lxmf"], dict):
        lxmf = data["lxmf"]

        # Parse propagation_node subsection
        if "propagation_node" in lxmf and isinstance(lxmf["propagation_node"], dict):
            pn = lxmf["propagation_node"]
            config.lxmf.propagation_node = PropagationNodeConfig(
                enabled=_parse_bool(pn.get("enabled", False)),
                name=pn.get("name"),
            )

        # Parse propagation destination
        if "propagation_destination" in lxmf:
            dest = lxmf["propagation_destination"]
            if dest and isinstance(dest, str) and len(dest) == 32:
                config.lxmf.propagation_destination = dest

        # Parse sync limits
        if "propagation_limit" in lxmf:
            config.lxmf.propagation_limit = int(lxmf["propagation_limit"])
        if "sync_limit" in lxmf:
            config.lxmf.sync_limit = int(lxmf["sync_limit"])
        if "delivery_limit" in lxmf:
            config.lxmf.delivery_limit = int(lxmf["delivery_limit"])

        # Parse peer management
        if "autopeer" in lxmf:
            config.lxmf.autopeer = _parse_bool(lxmf["autopeer"])
        if "autopeer_maxdepth" in lxmf:
            config.lxmf.autopeer_maxdepth = int(lxmf["autopeer_maxdepth"])
        if "max_peers" in lxmf:
            config.lxmf.max_peers = int(lxmf["max_peers"])
        if "from_static_only" in lxmf:
            config.lxmf.from_static_only = _parse_bool(lxmf["from_static_only"])

        # Parse static peers list
        if "static_peers" in lxmf and isinstance(lxmf["static_peers"], list):
            static_peers = []
            for peer in lxmf["static_peers"]:
                if isinstance(peer, str) and len(peer) == 32:
                    static_peers.append(peer)
            config.lxmf.static_peers = static_peers

        # Parse cost settings
        if "propagation_cost" in lxmf:
            config.lxmf.propagation_cost = int(lxmf["propagation_cost"])
        if "propagation_cost_flexibility" in lxmf:
            config.lxmf.propagation_cost_flexibility = int(lxmf["propagation_cost_flexibility"])
        if "peering_cost" in lxmf:
            config.lxmf.peering_cost = int(lxmf["peering_cost"])
        if "max_peering_cost" in lxmf:
            config.lxmf.max_peering_cost = int(lxmf["max_peering_cost"])

    return config


def save_core_config(config: CoreConfig, config_path: Path | None = None) -> None:
    """Save core configuration to YAML file.

    Args:
        config: CoreConfig instance to save.
        config_path: Optional path to config file. If None, uses default location.

    Raises:
        ConfigLoadError: If config cannot be written.
    """
    if config_path is None:
        config_path = get_config_dir() / "core-config.yaml"

    ensure_directories()

    # Convert CoreConfig to dictionary
    # For now, minimal implementation - full serialization can be added later
    reticulum_dict: dict[str, Any] = {
        "mode": config.reticulum.mode.value,
        "announce_interval": config.reticulum.announce_interval,
    }
    # Include config_path_override if set
    if config.reticulum.config_path_override is not None:
        reticulum_dict["config_path_override"] = str(config.reticulum.config_path_override)

    config_dict: dict[str, Any] = {
        "reticulum": reticulum_dict,
        "rpc": {
            "enabled": config.rpc.enabled,
        },
        "discovery": {
            "enabled": config.discovery.enabled,
            "auto_announce": config.discovery.auto_announce,
        },
        "chat": {
            "enabled": config.chat.enabled,
            "auto_reply_enabled": config.chat.auto_reply_enabled,
        },
        "api": {
            "enabled": config.api.enabled,
            "host": config.api.host,
            "port": config.api.port,
        },
    }

    try:
        with config_path.open("w") as f:
            yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        raise ConfigLoadError(f"Failed to save config to {config_path}: {e}", config_path) from e
