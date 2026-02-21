"""Core configuration service for headless Styrene applications.

This module provides functions to load and save CoreConfig for headless
applications. For TUI applications, use styrene.services.config instead.
"""

from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir

from styrened.models.config import (
    ConfigFieldError,
    ConfigLoadError,
    ConfigValidationError,
    CoreConfig,
    DeploymentMode,
    NotificationsConfig,
    Profile,
    PropagationNodeConfig,
    YubiKeyConfig,
    validate_short_name,
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


def get_profile_defaults(profile: Profile = Profile.OPERATOR) -> CoreConfig:
    """Return a CoreConfig with profile-appropriate defaults.

    Profile controls which services run and with what defaults, independent
    of network topology (mode). Every individual setting can still be
    overridden by YAML.

    Args:
        profile: Operational profile (operator or endpoint).

    Returns:
        CoreConfig instance with profile-appropriate defaults.
    """
    config = CoreConfig()
    config.profile = profile
    config.reticulum.mode = DeploymentMode.STANDALONE

    if profile == Profile.OPERATOR:
        config.rpc.enabled = True
        config.rpc.allow_command_execution = False
        config.chat.enabled = True
        config.chat.auto_reply_enabled = False
        config.discovery.enabled = True
        config.discovery.auto_announce = True
        config.ipc.enabled = True
        config.terminal.enabled = False
        config.notifications.enabled = True
        config.reticulum.announce_interval = 300

    elif profile == Profile.ENDPOINT:
        config.rpc.enabled = True
        config.rpc.allow_command_execution = True
        config.chat.enabled = True
        config.chat.auto_reply_enabled = True
        config.discovery.enabled = True
        config.discovery.auto_announce = True
        config.api.enabled = False
        config.ipc.enabled = False
        config.terminal.enabled = True
        config.notifications.enabled = False
        config.reticulum.announce_interval = 600

    elif profile == Profile.HUB:
        config.reticulum.mode = DeploymentMode.HUB
        config.reticulum.enable_transport = True
        config.reticulum.announce_interval = 3600
        config.rpc.enabled = True
        config.rpc.relay_mode = True
        config.rpc.allow_command_execution = False
        config.chat.enabled = True
        config.chat.auto_reply_enabled = True
        config.chat.auto_reply_cooldown = 600
        config.discovery.enabled = True
        config.discovery.auto_announce = True
        config.api.enabled = True
        config.api.public_mode = True
        config.ipc.enabled = False
        config.terminal.enabled = False
        config.notifications.enabled = False
        config.lxmf.propagation_node.enabled = True
        config.lxmf.autopeer = True

    return config


def get_default_core_config() -> CoreConfig:
    """Return default config. Backward-compatible wrapper.

    Returns:
        CoreConfig instance with operator profile defaults.
    """
    return get_profile_defaults(Profile.OPERATOR)


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

    # Two-pass: extract profile first, then build config from profile defaults
    profile = Profile.OPERATOR
    if "profile" in data:
        try:
            profile = Profile(data["profile"])
        except ValueError:
            pass  # Keep default

    config = get_profile_defaults(profile)

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
        if "auto_initialize" in ret:
            config.reticulum.auto_initialize = _parse_bool(ret["auto_initialize"])
        if "enable_transport" in ret:
            config.reticulum.enable_transport = _parse_bool(ret["enable_transport"])
        if "hub_enabled" in ret:
            config.reticulum.hub_enabled = _parse_bool(ret["hub_enabled"])
        if "hub_address" in ret and ret["hub_address"]:
            addr = str(ret["hub_address"])
            if len(addr) == 32:
                config.reticulum.hub_address = addr
        if "hub_announce_interval" in ret:
            config.reticulum.hub_announce_interval = int(ret["hub_announce_interval"])

        # Parse operator_identity_path
        if "operator_identity_path" in ret and ret["operator_identity_path"]:
            config.reticulum.operator_identity_path = Path(
                str(ret["operator_identity_path"])
            ).expanduser()

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
        if "public_mode" in api:
            config.api.public_mode = _parse_bool(api["public_mode"])
        if "metrics" in api and isinstance(api["metrics"], dict):
            metrics = api["metrics"]
            if "enabled" in metrics:
                config.api.metrics.enabled = _parse_bool(metrics["enabled"])

    # Parse identity section (ecosystem appearance + provider)
    if "identity" in data and isinstance(data["identity"], dict):
        ident = data["identity"]
        if "display_name" in ident and ident["display_name"]:
            config.identity.display_name = str(ident["display_name"])
        if "icon" in ident and ident["icon"]:
            config.identity.icon = str(ident["icon"])
        if "provider" in ident and ident["provider"]:
            provider = str(ident["provider"]).lower()
            if provider in ("file", "yubikey"):
                config.identity.provider = provider
            else:
                import logging

                logging.getLogger(__name__).warning(
                    f"Unknown identity provider '{provider}', falling back to 'file'"
                )
        if "short_name" in ident and ident["short_name"]:
            from styrened.models.config import validate_short_name

            candidate = str(ident["short_name"])
            if validate_short_name(candidate):
                config.identity.short_name = candidate
            else:
                import logging

                logging.getLogger(__name__).warning(
                    f"Invalid short_name '{candidate}' in config, ignoring"
                )

        if "yubikey" in ident and isinstance(ident["yubikey"], dict):
            yk = ident["yubikey"]
            config.identity.yubikey = YubiKeyConfig(
                credential_id=str(yk.get("credential_id", "")),
                rp_id=str(yk.get("rp_id", "styrene.mesh")),
                require_touch=_parse_bool(yk.get("require_touch", False)),
            )

    # Parse notifications section
    if "notifications" in data and isinstance(data["notifications"], dict):
        notif = data["notifications"]
        notif_config = NotificationsConfig()
        if "enabled" in notif:
            notif_config.enabled = _parse_bool(notif["enabled"])
        if "quiet_hours_start" in notif and notif["quiet_hours_start"] is not None:
            val = int(notif["quiet_hours_start"])
            if 0 <= val <= 23:
                notif_config.quiet_hours_start = val
        if "quiet_hours_end" in notif and notif["quiet_hours_end"] is not None:
            val = int(notif["quiet_hours_end"])
            if 0 <= val <= 23:
                notif_config.quiet_hours_end = val
        config.notifications = notif_config

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

    # Parse ipc section
    if "ipc" in data and isinstance(data["ipc"], dict):
        ipc = data["ipc"]
        if "enabled" in ipc:
            config.ipc.enabled = _parse_bool(ipc["enabled"])
        if "socket_path" in ipc and ipc["socket_path"]:
            config.ipc.socket_path = Path(str(ipc["socket_path"])).expanduser()
        if "socket_mode" in ipc:
            config.ipc.socket_mode = int(ipc["socket_mode"])

    # Parse terminal section
    if "terminal" in data and isinstance(data["terminal"], dict):
        term = data["terminal"]
        if "enabled" in term:
            config.terminal.enabled = _parse_bool(term["enabled"])
        if "allow_unauthenticated" in term:
            config.terminal.allow_unauthenticated = _parse_bool(term["allow_unauthenticated"])
        if "default_shell" in term and term["default_shell"]:
            config.terminal.default_shell = str(term["default_shell"])
        # Parse allowed_shells as a set of paths
        if "allowed_shells" in term and isinstance(term["allowed_shells"], list):
            shells = set()
            for shell in term["allowed_shells"]:
                if isinstance(shell, str) and shell.startswith("/"):
                    shells.add(shell)
            config.terminal.allowed_shells = shells
        if "session_idle_timeout" in term:
            config.terminal.session_idle_timeout = int(term["session_idle_timeout"])
        if "max_sessions_per_identity" in term:
            config.terminal.max_sessions_per_identity = int(term["max_sessions_per_identity"])
        if "max_total_sessions" in term:
            config.terminal.max_total_sessions = int(term["max_total_sessions"])
        if "rate_limit_requests" in term:
            config.terminal.rate_limit_requests = int(term["rate_limit_requests"])
        # Parse authorized_identities as a set of hex strings
        if "authorized_identities" in term and isinstance(term["authorized_identities"], list):
            authorized = set()
            for ident in term["authorized_identities"]:
                if isinstance(ident, str) and len(ident) == 32:
                    authorized.add(ident)
            config.terminal.authorized_identities = authorized

    return config


def save_core_config(config: CoreConfig, config_path: Path | None = None) -> None:
    """Save core configuration to YAML file.

    Serializes ALL 10 CoreConfig sections with ALL fields. The round-trip
    invariant is: load_core_config(save_core_config(config)) == config.

    Args:
        config: CoreConfig instance to save.
        config_path: Optional path to config file. If None, uses default location.

    Raises:
        ConfigLoadError: If config cannot be written.
    """
    if config_path is None:
        config_path = get_config_dir() / "core-config.yaml"

    ensure_directories()

    config_dict = _serialize_config(config)

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w") as f:
            yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        raise ConfigLoadError(f"Failed to save config to {config_path}: {e}", config_path) from e


def _serialize_config(config: CoreConfig) -> dict[str, Any]:
    """Serialize CoreConfig to a dictionary suitable for YAML output.

    Args:
        config: CoreConfig instance to serialize.

    Returns:
        Nested dictionary matching the YAML config file structure.
    """
    # Reticulum section
    reticulum_dict: dict[str, Any] = {
        "mode": config.reticulum.mode.value,
        "auto_initialize": config.reticulum.auto_initialize,
        "announce_interval": config.reticulum.announce_interval,
        "hub_enabled": config.reticulum.hub_enabled,
        "hub_announce_interval": config.reticulum.hub_announce_interval,
    }
    if config.reticulum.enable_transport is not None:
        reticulum_dict["enable_transport"] = config.reticulum.enable_transport
    if config.reticulum.config_path_override is not None:
        reticulum_dict["config_path_override"] = str(config.reticulum.config_path_override)
    if config.reticulum.operator_identity_path is not None:
        reticulum_dict["operator_identity_path"] = str(config.reticulum.operator_identity_path)
    if config.reticulum.hub_address is not None:
        reticulum_dict["hub_address"] = config.reticulum.hub_address

    # Interfaces sub-section
    interfaces_dict: dict[str, Any] = {
        "auto": config.reticulum.interfaces.auto,
        "server": {
            "enabled": config.reticulum.interfaces.server.enabled,
            "listen_ip": config.reticulum.interfaces.server.listen_ip,
            "port": config.reticulum.interfaces.server.port,
        },
    }
    if config.reticulum.interfaces.peers:
        interfaces_dict["peers"] = [
            {"host": p.host, "port": p.port, **({"name": p.name} if p.name else {})}
            for p in config.reticulum.interfaces.peers
        ]
    reticulum_dict["interfaces"] = interfaces_dict

    # Identity section
    identity_dict: dict[str, Any] = {
        "display_name": config.identity.display_name,
        "icon": config.identity.icon,
        "provider": config.identity.provider,
    }
    if config.identity.short_name:
        identity_dict["short_name"] = config.identity.short_name
    if config.identity.provider == "yubikey" or config.identity.yubikey.credential_id:
        identity_dict["yubikey"] = {
            "credential_id": config.identity.yubikey.credential_id,
            "rp_id": config.identity.yubikey.rp_id,
            "require_touch": config.identity.yubikey.require_touch,
        }

    # RPC section
    rpc_dict: dict[str, Any] = {
        "enabled": config.rpc.enabled,
        "relay_mode": config.rpc.relay_mode,
        "allow_command_execution": config.rpc.allow_command_execution,
    }

    # Discovery section
    discovery_dict: dict[str, Any] = {
        "enabled": config.discovery.enabled,
        "auto_announce": config.discovery.auto_announce,
    }

    # Chat section
    chat_dict: dict[str, Any] = {
        "enabled": config.chat.enabled,
        "auto_reply_enabled": config.chat.auto_reply_enabled,
        "auto_reply_message": config.chat.auto_reply_message,
        "auto_reply_cooldown": config.chat.auto_reply_cooldown,
        "persist_messages": config.chat.persist_messages,
    }

    # API section
    api_dict: dict[str, Any] = {
        "enabled": config.api.enabled,
        "host": config.api.host,
        "port": config.api.port,
        "public_mode": config.api.public_mode,
        "metrics": {
            "enabled": config.api.metrics.enabled,
        },
    }

    # IPC section
    ipc_dict: dict[str, Any] = {
        "enabled": config.ipc.enabled,
        "socket_mode": config.ipc.socket_mode,
    }
    if config.ipc.socket_path is not None:
        ipc_dict["socket_path"] = str(config.ipc.socket_path)

    # Notifications section
    notifications_dict: dict[str, Any] = {
        "enabled": config.notifications.enabled,
    }
    if config.notifications.quiet_hours_start is not None:
        notifications_dict["quiet_hours_start"] = config.notifications.quiet_hours_start
    if config.notifications.quiet_hours_end is not None:
        notifications_dict["quiet_hours_end"] = config.notifications.quiet_hours_end

    # LXMF section
    lxmf_dict: dict[str, Any] = {
        "propagation_node": {
            "enabled": config.lxmf.propagation_node.enabled,
        },
        "propagation_limit": config.lxmf.propagation_limit,
        "sync_limit": config.lxmf.sync_limit,
        "delivery_limit": config.lxmf.delivery_limit,
        "autopeer": config.lxmf.autopeer,
        "autopeer_maxdepth": config.lxmf.autopeer_maxdepth,
        "max_peers": config.lxmf.max_peers,
        "from_static_only": config.lxmf.from_static_only,
        "propagation_cost": config.lxmf.propagation_cost,
        "propagation_cost_flexibility": config.lxmf.propagation_cost_flexibility,
        "peering_cost": config.lxmf.peering_cost,
        "max_peering_cost": config.lxmf.max_peering_cost,
    }
    if config.lxmf.propagation_node.name is not None:
        lxmf_dict["propagation_node"]["name"] = config.lxmf.propagation_node.name
    if config.lxmf.propagation_destination is not None:
        lxmf_dict["propagation_destination"] = config.lxmf.propagation_destination
    if config.lxmf.static_peers:
        lxmf_dict["static_peers"] = list(config.lxmf.static_peers)

    # Terminal section
    terminal_dict: dict[str, Any] = {
        "enabled": config.terminal.enabled,
        "allow_unauthenticated": config.terminal.allow_unauthenticated,
        "session_idle_timeout": config.terminal.session_idle_timeout,
        "max_sessions_per_identity": config.terminal.max_sessions_per_identity,
        "max_total_sessions": config.terminal.max_total_sessions,
        "rate_limit_requests": config.terminal.rate_limit_requests,
    }
    if config.terminal.default_shell is not None:
        terminal_dict["default_shell"] = config.terminal.default_shell
    if config.terminal.allowed_shells:
        terminal_dict["allowed_shells"] = sorted(config.terminal.allowed_shells)
    if config.terminal.authorized_identities:
        terminal_dict["authorized_identities"] = sorted(config.terminal.authorized_identities)

    return {
        "profile": config.profile.value,
        "reticulum": reticulum_dict,
        "identity": identity_dict,
        "rpc": rpc_dict,
        "discovery": discovery_dict,
        "chat": chat_dict,
        "api": api_dict,
        "ipc": ipc_dict,
        "notifications": notifications_dict,
        "lxmf": lxmf_dict,
        "terminal": terminal_dict,
    }


def validate_core_config(
    config: CoreConfig, *, raise_on_error: bool = False
) -> list[ConfigFieldError]:
    """Validate a CoreConfig instance for semantic correctness.

    Checks port ranges, enum values, string constraints, and cross-field
    dependencies. Does NOT check file existence or network reachability.

    Args:
        config: CoreConfig instance to validate.
        raise_on_error: If True, raise ConfigValidationError on first batch of errors.

    Returns:
        List of ConfigFieldError instances (empty = valid).

    Raises:
        ConfigValidationError: If raise_on_error is True and errors are found.
    """
    errors: list[ConfigFieldError] = []

    def _check_port(field: str, port: int) -> None:
        if not 1 <= port <= 65535:
            errors.append(ConfigFieldError(field, "Port must be 1-65535", str(port)))

    # --- Profile ---
    try:
        Profile(config.profile.value)
    except ValueError:
        errors.append(
            ConfigFieldError("profile", "Must be 'operator', 'endpoint', or 'hub'", str(config.profile))
        )

    # --- Reticulum ---
    try:
        DeploymentMode(config.reticulum.mode.value)
    except ValueError:
        errors.append(
            ConfigFieldError("reticulum.mode", "Invalid deployment mode", str(config.reticulum.mode))
        )

    if config.reticulum.announce_interval <= 0:
        errors.append(
            ConfigFieldError(
                "reticulum.announce_interval",
                "Must be > 0",
                str(config.reticulum.announce_interval),
            )
        )

    if config.reticulum.hub_announce_interval <= 0:
        errors.append(
            ConfigFieldError(
                "reticulum.hub_announce_interval",
                "Must be > 0",
                str(config.reticulum.hub_announce_interval),
            )
        )

    if config.reticulum.hub_address is not None and len(config.reticulum.hub_address) != 32:
        errors.append(
            ConfigFieldError(
                "reticulum.hub_address",
                "Must be a 32-character hex hash",
                config.reticulum.hub_address,
            )
        )

    # Interfaces
    _check_port("reticulum.interfaces.server.port", config.reticulum.interfaces.server.port)
    for i, peer in enumerate(config.reticulum.interfaces.peers):
        _check_port(f"reticulum.interfaces.peers[{i}].port", peer.port)
        if not peer.host:
            errors.append(
                ConfigFieldError(f"reticulum.interfaces.peers[{i}].host", "Host cannot be empty")
            )

    # Cross-field: hub mode should have connectivity
    if config.reticulum.mode == DeploymentMode.HUB:
        has_server = config.reticulum.interfaces.server.enabled
        has_peers = len(config.reticulum.interfaces.peers) > 0
        if not has_server and not has_peers:
            errors.append(
                ConfigFieldError(
                    "reticulum.mode",
                    "Hub mode requires at least a server interface or peer connections",
                    "hub",
                )
            )

    # --- Identity ---
    if not config.identity.display_name or len(config.identity.display_name) > 100:
        errors.append(
            ConfigFieldError(
                "identity.display_name",
                "Must be 1-100 characters",
                config.identity.display_name[:20] if config.identity.display_name else "",
            )
        )

    if config.identity.short_name is not None and not validate_short_name(
        config.identity.short_name
    ):
        errors.append(
            ConfigFieldError(
                "identity.short_name",
                "Must be 3-20 lowercase alphanumeric + hyphens, no leading/trailing hyphens",
                config.identity.short_name,
            )
        )

    if config.identity.provider not in ("file", "yubikey"):
        errors.append(
            ConfigFieldError(
                "identity.provider",
                "Must be 'file' or 'yubikey'",
                config.identity.provider,
            )
        )

    # --- API ---
    _check_port("api.port", config.api.port)

    # --- IPC ---
    if not 0 <= config.ipc.socket_mode <= 0o777:
        errors.append(
            ConfigFieldError(
                "ipc.socket_mode",
                "Must be a valid Unix permission (0-0o777)",
                oct(config.ipc.socket_mode),
            )
        )

    # --- Chat ---
    if config.chat.auto_reply_cooldown < 0:
        errors.append(
            ConfigFieldError(
                "chat.auto_reply_cooldown",
                "Must be >= 0",
                str(config.chat.auto_reply_cooldown),
            )
        )

    # --- Notifications ---
    for field_name, val in [
        ("notifications.quiet_hours_start", config.notifications.quiet_hours_start),
        ("notifications.quiet_hours_end", config.notifications.quiet_hours_end),
    ]:
        if val is not None and not 0 <= val <= 23:
            errors.append(
                ConfigFieldError(field_name, "Must be 0-23", str(val))
            )

    # --- LXMF ---
    if config.lxmf.propagation_node.enabled and not config.lxmf.propagation_node.name:
        errors.append(
            ConfigFieldError(
                "lxmf.propagation_node.name",
                "Propagation node requires a name when enabled",
            )
        )

    if config.lxmf.propagation_destination is not None:
        if len(config.lxmf.propagation_destination) != 32:
            errors.append(
                ConfigFieldError(
                    "lxmf.propagation_destination",
                    "Must be a 32-character hex hash",
                    config.lxmf.propagation_destination,
                )
            )

    for peer in config.lxmf.static_peers:
        if len(peer) != 32:
            errors.append(
                ConfigFieldError(
                    "lxmf.static_peers",
                    "Each peer must be a 32-character hex hash",
                    peer,
                )
            )

    # --- Terminal ---
    for ident in config.terminal.authorized_identities:
        if len(ident) != 32:
            errors.append(
                ConfigFieldError(
                    "terminal.authorized_identities",
                    "Each identity must be a 32-character hex hash",
                    ident,
                )
            )

    if raise_on_error and errors:
        raise ConfigValidationError(errors)

    return errors
