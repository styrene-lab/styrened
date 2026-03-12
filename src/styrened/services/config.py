"""Core configuration service for headless Styrene applications.

This module provides functions to load and save CoreConfig for headless
applications. For TUI applications, use styrene.services.config instead.
"""
from __future__ import annotations


import logging
from pathlib import Path
from typing import Any

import yaml

from styrened import paths
from styrened.models.config import (
    AutoReplyMode,
    ChatbotConfig,
    ConfigFieldError,
    ConfigLoadError,
    ConfigValidationError,
    CoreConfig,
    DeploymentMode,
    MeshAccessMode,
    NotificationsConfig,
    PeerConfig,
    PQCConfig,
    Profile,
    PropagationNodeConfig,
    WebAuthConfig,
    YubiKeyConfig,
    validate_short_name,
)

logger = logging.getLogger(__name__)


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


def get_log_dir() -> Path:
    """Return the log directory path.

    .. deprecated::
        Use ``paths.log_dir()`` directly.
    """
    return paths.log_dir()


def ensure_directories() -> None:
    """Create necessary directories if they don't exist.

    .. deprecated::
        Use ``paths.ensure_directories()`` directly.
    """
    paths.ensure_directories()


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

    # Well-known public hubs — Styrene hub enabled by default, others
    # available for operator to enable in Settings > Network > Peers.
    import copy

    from styrened.models.config import COMMUNITY_HUB_PROPAGATION_HASH, WELL_KNOWN_HUBS
    config.reticulum.interfaces.peers = copy.deepcopy(WELL_KNOWN_HUBS)

    if profile == Profile.OPERATOR:
        config.rpc.enabled = True
        config.rpc.allow_command_execution = False
        config.chat.enabled = True
        config.chat.auto_reply_mode = AutoReplyMode.DISABLED
        config.discovery.enabled = True
        config.discovery.auto_announce = True
        config.ipc.enabled = True
        config.terminal.enabled = False
        config.notifications.enabled = True
        config.reticulum.announce_interval = 300
        # Use the Styrene Community Hub as the default LXMF propagation node.
        # This enables store-and-forward delivery when recipients are offline.
        config.lxmf.propagation_destination = COMMUNITY_HUB_PROPAGATION_HASH

    elif profile == Profile.ENDPOINT:
        config.rpc.enabled = True
        config.rpc.allow_command_execution = True
        config.chat.enabled = True
        config.chat.auto_reply_mode = AutoReplyMode.TEMPLATE
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
        config.chat.auto_reply_mode = AutoReplyMode.TEMPLATE
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


def _parse_rbac(data: dict):  # -> RBACPolicy
    """Parse RBAC policy from config data.

    Args:
        data: Raw YAML config dict.

    Returns:
        RBACPolicy instance.
    """
    from styrened.models.rbac import Capability, RBACPolicy, Role, RosterEntry

    rbac_data = data.get("rbac", {})

    # Parse default_role
    default_role_str = str(rbac_data.get("default_role", "peer")).upper()
    try:
        default_role = Role[default_role_str]
    except KeyError:
        logger.warning(f"Unknown RBAC default_role '{default_role_str}', using PEER")
        default_role = Role.PEER

    # Parse roster
    roster: dict[str, RosterEntry] = {}
    for entry_data in rbac_data.get("roster", []):
        identity = str(entry_data.get("identity", "")).lower().strip()
        if not identity:
            continue
        role_str = str(entry_data.get("role", "peer")).upper()
        try:
            role = Role[role_str]
        except KeyError:
            logger.warning(f"Unknown role '{role_str}' for {identity[:16]}..., skipping")
            continue
        label = str(entry_data.get("label", ""))
        grants_raw = entry_data.get("grants", [])
        grants: set[str] = set()
        for g in grants_raw:
            g_str = str(g).strip()
            if g_str in Capability.ALL:
                grants.add(g_str)
            else:
                logger.warning(f"Unknown capability grant '{g_str}' for {identity[:16]}...")
        roster[identity] = RosterEntry(
            identity_hash=identity,
            role=role,
            label=label,
            grants=frozenset(grants),
        )

    # Parse blocked list
    blocked: list[str] = [
        str(h).lower().strip()
        for h in rbac_data.get("blocked", [])
        if h
    ]

    return RBACPolicy(default_role=default_role, roster=roster, blocked=blocked)


def load_core_config(config_path: Path | None = None) -> CoreConfig:
    """Load core configuration from YAML file.

    Looks for config in this order:
    1. Explicit config_path argument
    2. STYRENE_CONFIG_DIR env var + "config.yaml"
    3. Default location via paths.config_file()

    Args:
        config_path: Optional path to config file. If None, uses default location.

    Returns:
        CoreConfig instance loaded from file, or defaults if file doesn't exist.

    Raises:
        ConfigLoadError: If config file exists but cannot be parsed.
    """
    from styrened.models.config import (
        ServerInterfaceConfig,
    )

    if config_path is None:
        config_path = paths.config_file()

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
                                enabled=_parse_bool(p.get("enabled", True)),
                            )
                        )
                config.reticulum.interfaces.peers = peers

            # Merge any missing well-known hubs so existing installs see them
            # in Settings > Network > Peers without manual addition.
            # Community hub keeps its default enabled state; third-party hubs
            # are added disabled so operators opt in explicitly.
            from styrened.models.config import WELL_KNOWN_HUBS
            existing_hosts = {(p.host, p.port) for p in config.reticulum.interfaces.peers}
            for hub in WELL_KNOWN_HUBS:
                if (hub.host, hub.port) not in existing_hosts:
                    import copy
                    new_hub = copy.deepcopy(hub)
                    # Styrene Community Hub stays enabled (it's our hub);
                    # third-party hubs added disabled for explicit opt-in.
                    # hub.enabled from WELL_KNOWN_HUBS carries the intent.
                    config.reticulum.interfaces.peers.append(new_hub)

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
        if "access_mode" in disc:
            raw_mode = str(disc["access_mode"]).lower()
            try:
                config.discovery.access_mode = MeshAccessMode(raw_mode)
            except ValueError:
                import logging

                logging.getLogger(__name__).warning(
                    f"Unknown discovery.access_mode '{raw_mode}', using 'open'"
                )
        if "allowed_peers" in disc and isinstance(disc["allowed_peers"], list):
            config.discovery.allowed_peers = {
                str(h).lower() for h in disc["allowed_peers"] if h
            }
        if "info_respond" in disc:
            config.discovery.info_respond = _parse_bool(disc["info_respond"])
        if "operator_label" in disc:
            config.discovery.operator_label = str(disc["operator_label"]).strip()

    # Parse chat section
    if "chat" in data and isinstance(data["chat"], dict):
        chat = data["chat"]
        if "enabled" in chat:
            config.chat.enabled = _parse_bool(chat["enabled"])
        if "auto_reply_mode" in chat:
            try:
                config.chat.auto_reply_mode = AutoReplyMode(chat["auto_reply_mode"])
            except ValueError:
                pass  # Keep default
        if "auto_reply_message" in chat:
            config.chat.auto_reply_message = str(chat["auto_reply_message"])
        if "auto_reply_cooldown" in chat:
            config.chat.auto_reply_cooldown = int(chat["auto_reply_cooldown"])
        if "persist_messages" in chat:
            config.chat.persist_messages = _parse_bool(chat["persist_messages"])

        # Parse chatbot subsection
        if "chatbot" in chat and isinstance(chat["chatbot"], dict):
            cb = chat["chatbot"]
            config.chat.chatbot = ChatbotConfig(
                endpoint=str(cb.get("endpoint", "http://localhost:11434/v1")),
                model=str(cb.get("model", "llama3")),
                api_key=str(cb.get("api_key", "")),
                system_prompt=str(cb.get("system_prompt", config.chat.chatbot.system_prompt)),
                max_tokens=int(cb.get("max_tokens", 256)),
                temperature=float(cb.get("temperature", 0.7)),
                max_context_messages=int(cb.get("max_context_messages", 10)),
            )

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

        # Parse auth subsection
        if "auth" in api and isinstance(api["auth"], dict):
            auth = api["auth"]
            config.api.auth = WebAuthConfig(
                enabled=_parse_bool(auth.get("enabled", False)),
                exempt_localhost=_parse_bool(auth.get("exempt_localhost", True)),
                session_ttl=int(auth.get("session_ttl", 86400)),
            )

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
    # Parse page_server section
    if "page_server" in data and isinstance(data["page_server"], dict):
        ps = data["page_server"]
        if "enabled" in ps:
            config.page_server.enabled = _parse_bool(ps["enabled"])
        if "pages_dir" in ps and ps["pages_dir"]:
            config.page_server.pages_dir = Path(str(ps["pages_dir"])).expanduser()
        if "node_name" in ps and ps["node_name"]:
            config.page_server.node_name = str(ps["node_name"])
        if "demo" in ps:
            config.page_server.demo = _parse_bool(ps["demo"])

    # Parse pqc section
    if "pqc" in data and isinstance(data["pqc"], dict):
        pqc = data["pqc"]

        # Parse rekey_interval_hours with error handling for non-numeric values
        rekey_interval_hours = 24  # default
        try:
            rekey_interval_hours = int(pqc.get("rekey_interval_hours", 24))
        except (ValueError, TypeError):
            import logging as _logging

            _logging.getLogger(__name__).warning(
                f"Invalid pqc.rekey_interval_hours value "
                f"{pqc.get('rekey_interval_hours')!r}, using default 24"
            )

        config.pqc = PQCConfig(
            enabled=_parse_bool(pqc.get("enabled", True)),
            rekey_interval_hours=rekey_interval_hours,
            require_pqc_for_rpc=_parse_bool(pqc.get("require_pqc_for_rpc", False)),
            auto_initiate=_parse_bool(pqc.get("auto_initiate", True)),
        )

    # Parse mesh_vpn section
    if "mesh_vpn" in data and isinstance(data["mesh_vpn"], dict):
        from styrened.models.config import MeshVPNConfig

        mvpn = data["mesh_vpn"]
        config.mesh_vpn = MeshVPNConfig(
            enable=_parse_bool(mvpn.get("enable", False)),
            listen_port=int(mvpn.get("listen_port", 51820)),
            subnet_prefix=str(mvpn.get("subnet_prefix", "fd73:7479:7265:6e65")),
            gateway=_parse_bool(mvpn.get("gateway", False)),
            endpoint=str(mvpn.get("endpoint", "")),
        )

    # Parse relay section
    _parse_relay(config, data)

    # Parse yggdrasil section
    _parse_yggdrasil(config, data)

    # Parse i2p section
    _parse_i2p(config, data)

    # Parse group thread footprint policy
    _parse_group_threads(config, data)

    # Parse RBAC policy
    config.rbac = _parse_rbac(data)

    return config


def _parse_relay(config: CoreConfig, data: dict) -> None:
    """Parse relay section from config data into config.relay."""
    if "relay" in data and isinstance(data["relay"], dict):
        from styrened.models.relay import RelayConfig

        r = data["relay"]
        config.relay = RelayConfig(
            enabled=_parse_bool(r.get("enabled", False)),
            max_sessions=int(r.get("max_sessions", 16)),
            max_per_identity=int(r.get("max_per_identity", 2)),
            max_bytes_per_session=int(r.get("max_bytes_per_session", 52_428_800)),
            idle_timeout=int(r.get("idle_timeout", 900)),
            allow_permanent=_parse_bool(r.get("allow_permanent", False)),
            allowed_identities=list(r.get("allowed_identities", [])),
        )


def _parse_yggdrasil(config: CoreConfig, data: dict) -> None:
    """Parse yggdrasil section from config data into config.yggdrasil."""
    if "yggdrasil" not in data or not isinstance(data["yggdrasil"], dict):
        return
    from styrened.models.config import YggdrasilConfig
    from styrened.services.daemon_adapter import DaemonMode

    y = data["yggdrasil"]
    raw_mode = y.get("mode", DaemonMode.DISABLED.value)
    try:
        mode = DaemonMode(raw_mode)
    except ValueError:
        mode = DaemonMode.DISABLED
    peers = y.get("initial_peers", [])
    if not isinstance(peers, list):
        peers = []
    config.yggdrasil = YggdrasilConfig(
        mode=mode,
        binary_path=str(y.get("binary_path", "yggdrasil")),
        listen_port=int(y.get("listen_port", 9002)),
        admin_socket=str(y.get("admin_socket", "")),
        multicast=_parse_bool(y.get("multicast", True)),
        bootstrap_from_rns=_parse_bool(y.get("bootstrap_from_rns", True)),
        initial_peers=[str(p) for p in peers],
    )


def _parse_i2p(config: CoreConfig, data: dict) -> None:
    """Parse i2p section from config data into config.i2p."""
    if "i2p" not in data or not isinstance(data["i2p"], dict):
        return
    from styrened.models.config import I2PConfig
    from styrened.services.daemon_adapter import DaemonMode

    i = data["i2p"]
    raw_mode = i.get("mode", DaemonMode.DISABLED.value)
    try:
        mode = DaemonMode(raw_mode)
    except ValueError:
        mode = DaemonMode.DISABLED
    config.i2p = I2PConfig(
        mode=mode,
        http_proxy_host=str(i.get("http_proxy_host", "127.0.0.1")),
        http_proxy_port=int(i.get("http_proxy_port", 4444)),
        managed_http_proxy_port=int(i.get("managed_http_proxy_port", 4445)),
        managed_i2pcontrol_port=int(i.get("managed_i2pcontrol_port", 7651)),
        b32_address=str(i.get("b32_address", "")),
        cache_ttl=int(i.get("cache_ttl", 3600)),
        fetch_timeout=float(i.get("fetch_timeout", 45.0)),
    )


def _parse_group_threads(config: CoreConfig, data: dict) -> None:
    """Parse group_threads section from config data into config.group_threads."""
    if "group_threads" not in data or not isinstance(data["group_threads"], dict):
        return
    from styrened.models.config import GroupThreadFeatureTierConfig, GroupThreadsConfig

    g = data["group_threads"]
    raw_tier = str(g.get("feature_tier", GroupThreadFeatureTierConfig.BALANCED.value)).lower()
    try:
        feature_tier = GroupThreadFeatureTierConfig(raw_tier)
    except ValueError:
        feature_tier = GroupThreadFeatureTierConfig.BALANCED
    config.group_threads = GroupThreadsConfig(
        enabled=_parse_bool(g.get("enabled", True)),
        feature_tier=feature_tier,
        bounded_retention=_parse_bool(g.get("bounded_retention", False)),
        auto_media_fetch=_parse_bool(g.get("auto_media_fetch", True)),
        metadata_first_sync=_parse_bool(g.get("metadata_first_sync", False)),
        background_catchup=_parse_bool(g.get("background_catchup", True)),
        first_run_auto_tier=_parse_bool(g.get("first_run_auto_tier", True)),
    )


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
        config_path = paths.config_file()

    paths.ensure_directories()

    config_dict = serialize_config(config)

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w") as f:
            yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        raise ConfigLoadError(f"Failed to save config to {config_path}: {e}", config_path) from e


def serialize_config(config: CoreConfig) -> dict[str, Any]:
    """Serialize CoreConfig to a dictionary suitable for YAML output.

    This is a public API — used by the IPC handler (SAVE_CORE_CONFIG)
    and any consumer that needs to round-trip CoreConfig through a dict
    representation.

    Args:
        config: CoreConfig instance to serialize.

    Returns:
        Nested dictionary matching the YAML config file structure.
    """
    return config.to_dict()


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

    # API auth
    if config.api.auth.session_ttl < 60:
        errors.append(
            ConfigFieldError(
                "api.auth.session_ttl",
                "Must be >= 60 seconds",
                str(config.api.auth.session_ttl),
            )
        )
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

    # Chatbot validation (only when chatbot mode is active)
    if config.chat.auto_reply_mode == AutoReplyMode.CHATBOT:
        if not config.chat.chatbot.endpoint:
            errors.append(
                ConfigFieldError(
                    "chat.chatbot.endpoint",
                    "Endpoint is required when auto_reply_mode is 'chatbot'",
                )
            )
    if not 0.0 <= config.chat.chatbot.temperature <= 2.0:
        errors.append(
            ConfigFieldError(
                "chat.chatbot.temperature",
                "Must be between 0.0 and 2.0",
                str(config.chat.chatbot.temperature),
            )
        )
    if config.chat.chatbot.max_tokens < 1:
        errors.append(
            ConfigFieldError(
                "chat.chatbot.max_tokens",
                "Must be >= 1",
                str(config.chat.chatbot.max_tokens),
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

    for peer_hash in config.lxmf.static_peers:
        if len(peer_hash) != 32:
            errors.append(
                ConfigFieldError(
                    "lxmf.static_peers",
                    "Each peer must be a 32-character hex hash",
                    peer_hash,
                )
            )

    # --- RBAC ---
    for identity_hash, _entry in config.rbac.roster.items():
        if len(identity_hash) != 32:
            errors.append(
                ConfigFieldError(
                    "rbac.roster",
                    "Identity hash must be 32 hex characters",
                    identity_hash,
                )
            )
    for prefix in config.rbac.blocked:
        if len(prefix) < 4:
            errors.append(
                ConfigFieldError(
                    "rbac.blocked",
                    "Blocked prefix should be at least 4 chars to avoid collisions",
                    prefix,
                )
            )

    # --- PQC ---
    if config.pqc.rekey_interval_hours < 1:
        errors.append(
            ConfigFieldError(
                "pqc.rekey_interval_hours",
                "Must be >= 1",
                str(config.pqc.rekey_interval_hours),
            )
        )

    if raise_on_error and errors:
        raise ConfigValidationError(errors)

    return errors

# Backward-compat alias (was private, now public)
_serialize_config = serialize_config
