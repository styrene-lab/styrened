"""Core configuration models for Styrene.

This module contains configuration models that are shared between
headless (core) and TUI applications. TUI-specific config is in
styrene-tui/src/styrene/models/config.py.
"""
from __future__ import annotations


import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from styrened.models.rbac import RBACPolicy
from styrened.models.daemon_mode import DaemonMode

if TYPE_CHECKING:
    from styrened.models.relay import RelayConfig

if TYPE_CHECKING:
    from styrened.models.relay import RelayConfig

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class LogLevel(Enum):
    """Logging verbosity levels.

    Maps to standard Python logging levels for consistency.
    """

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DeploymentMode(Enum):
    """Styrene deployment modes.

    Determines how Styrene participates in the Reticulum mesh.
    """

    STANDALONE = "standalone"  # Local only, no external connections
    HUB = "hub"  # Act as transport node, accept connections
    PEER = "peer"  # Connect to specific hubs


class GatewayMode(Enum):
    """Mesh gateway operating modes.

    Determines how a device participates in mesh internet sharing.
    """

    OFF = "off"  # No gateway functionality
    CLIENT = "client"  # Use mesh gateway for internet
    SERVER = "server"  # Provide internet to mesh clients


class Profile(Enum):
    """Node operational profile.

    Determines service defaults independent of network topology (mode).
    Profile controls "what to run"; mode controls "how to connect".
    """

    OPERATOR = "operator"  # Human-facing: sends commands, reads chat
    ENDPOINT = "endpoint"  # Machine-facing: accepts commands, managed remotely
    HUB = "hub"  # Public infrastructure: routes, propagates, read-only web dashboard


class AutoReplyMode(Enum):
    """Auto-reply operating mode.

    Controls how the node responds to incoming chat messages when no
    operator is available.
    """

    DISABLED = "disabled"  # No automatic responses
    TEMPLATE = "template"  # Static template with {hostname}, {uptime}, etc.
    CHATBOT = "chatbot"  # LLM-backed conversational responses


# -----------------------------------------------------------------------------
# Configuration validation errors
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigFieldError:
    """Represents a single configuration field validation error.

    Attributes:
        field: Dot-notation path to the problematic field (e.g., "mesh.channel").
        message: Human-readable error description.
        value: The invalid value (if safe to display).
    """

    field: str
    message: str
    value: str | None = None

    def __str__(self) -> str:
        if self.value:
            return f"{self.field}: {self.message} (got: {self.value})"
        return f"{self.field}: {self.message}"


class ConfigLoadError(Exception):
    """Raised when configuration cannot be loaded.

    Attributes:
        path: Path to the config file that failed to load.
    """

    def __init__(self, message: str, path: Path | None = None) -> None:
        self.path = path
        super().__init__(message)


class ConfigValidationError(Exception):
    """Raised when configuration validation fails.

    Contains a list of all validation errors encountered.

    Attributes:
        errors: List of ConfigFieldError instances.
    """

    def __init__(self, errors: list[ConfigFieldError]) -> None:
        self.errors = errors
        messages = [str(e) for e in errors]
        super().__init__(f"Configuration validation failed: {'; '.join(messages)}")


# -----------------------------------------------------------------------------
# Configuration section dataclasses
# -----------------------------------------------------------------------------


@dataclass
class PeerConfig:
    """Configuration for a peer hub connection.

    Attributes:
        host: Hostname or IP address of peer hub.
        port: TCP port for connection.
        name: Optional human-readable name for this peer.
        enabled: Whether this peer interface is active. Disabled peers are
            preserved in config but not written to ~/.reticulum/config.
    """

    host: str
    port: int = 4242
    name: str | None = None
    enabled: bool = True


# Well-known public Reticulum transport hubs maintained by the community.
# Source: https://github.com/markqvist/Reticulum/wiki/Community-Node-List
# These are offered as optional peers during first-run setup and in
# Settings > Network > Peers alongside the Styrene Community Hub.
# LXMF propagation destination hash for the Styrene Community Hub.
# Derived from the hub's persistent LXMF identity (/app/.lxmf on PVC).
# Stable across pod restarts. Update only if the hub identity is rotated.
COMMUNITY_HUB_PROPAGATION_HASH: str = "0db6cb465cb2bb3279f32e27ac7da24b"

WELL_KNOWN_HUBS: list[PeerConfig] = [
    PeerConfig(host="rns.styrene.io", port=4242, name="Styrene Community Hub", enabled=True),
    PeerConfig(host="dublin.connect.reticulum.network", port=4965, name="RNS Dublin", enabled=False),
    PeerConfig(host="reticulum.betweentheborders.com", port=4242, name="BetweenTheBorders", enabled=False),
    PeerConfig(host="istanbul.reserve.network", port=9034, name="Istanbul Reserve", enabled=False),
    PeerConfig(host="sydney.reticulum.au", port=4242, name="RNS Sydney", enabled=False),
]


@dataclass
class ServerInterfaceConfig:
    """Configuration for TCP server interface.

    Attributes:
        enabled: Whether to enable TCP server interface.
        listen_ip: IP address to bind to (0.0.0.0 = all interfaces).
        port: TCP port to listen on.
    """

    enabled: bool = False
    listen_ip: str = "0.0.0.0"
    port: int = 4242


@dataclass
class InterfaceConfig:
    """RNS interface configuration.

    Attributes:
        auto: Enable AutoInterface for local UDP discovery.
              Disabled by default due to platform compatibility issues.
              See generate_rns_config() for details on Linux/macOS errors.
        server: TCP server interface configuration.
        peers: List of peer hubs to connect to.
    """

    auto: bool = False
    server: ServerInterfaceConfig = field(default_factory=ServerInterfaceConfig)
    peers: list[PeerConfig] = field(default_factory=list)


@dataclass
class ReticulumConfig:
    """Reticulum integration settings.

    Controls how Styrene interacts with Reticulum. Note that Reticulum
    itself stores its config in its own location following the priority:
    /etc/reticulum -> ~/.config/reticulum -> ~/.reticulum

    Attributes:
        config_path_override: Force a specific Reticulum config directory.
        auto_initialize: Offer to initialize Reticulum if not configured.
        mode: Deployment mode (standalone, hub, peer).
        enable_transport: Override transport setting (None = auto from mode).
        interfaces: Interface configuration.
        operator_identity_path: Path to operator identity file.
        announce_interval: Seconds between announces (default 300).
        hub_enabled: Whether to connect to Hub (Phase 2).
        hub_address: Hub LXMF address for fleet coordination (Phase 2).
        hub_announce_interval: Hub's announce interval in seconds (default 60).
    """

    config_path_override: Path | None = None
    auto_initialize: bool = True
    mode: DeploymentMode = DeploymentMode.STANDALONE
    enable_transport: bool | None = None  # None = auto-determine from mode
    interfaces: InterfaceConfig = field(default_factory=InterfaceConfig)
    operator_identity_path: Path | None = None
    announce_interval: int = 300
    # Phase 2 settings - hub connectivity
    hub_enabled: bool = False
    hub_address: str | None = None  # 32-char hex LXMF address
    hub_announce_interval: int = 60  # Hub's announce interval in seconds

    def resolve_transport_enabled(self) -> bool:
        """Determine if transport should be enabled based on mode.

        Returns:
            True if transport should be enabled, False otherwise.
        """
        if self.enable_transport is not None:
            return self.enable_transport

        # Auto-determine based on mode
        # HUB: transport enabled for routing
        # STANDALONE: transport enabled to use our own interfaces
        # CLIENT: transport disabled, connects to shared instance
        return self.mode in (DeploymentMode.HUB, DeploymentMode.STANDALONE)


@dataclass
class YubiKeyConfig:
    """YubiKey-backed identity derivation configuration.

    Used when identity.provider is "yubikey". The FIDO2 hmac-secret extension
    derives deterministic key material from a hardware token, making the
    operator's mesh identity portable across machines.

    Attributes:
        credential_id: Base64-encoded FIDO2 credential ID from setup.
        rp_id: Relying party ID used during credential creation.
        require_touch: Whether to require physical touch for each derivation.
    """

    credential_id: str = ""
    rp_id: str = "styrene.mesh"
    require_touch: bool = False


_SHORT_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,18}[a-z0-9]$")


def validate_short_name(name: str) -> bool:
    """Validate a short-name identifier.

    3-20 chars, lowercase alphanumeric + hyphens, no leading/trailing hyphens.
    """
    return bool(_SHORT_NAME_PATTERN.match(name))


@dataclass
class IdentityConfig:
    """Identity appearance and provider configuration.

    Controls how this node appears to other LXMF clients (Sideband, NomadNet, MeshChat).
    These fields are included in announces and message metadata.

    The provider field selects how the operator identity is sourced:
    - "file" (default): Read from disk (existing behavior)
    - "yubikey": Derive from YubiKey FIDO2 hmac-secret PRF

    Attributes:
        display_name: Human-readable name shown in chat clients.
            Defaults to "Anonymous Styrene".
        icon: Emoji or short string displayed as identity icon.
            Defaults to 🔗. Common alternatives: 🖥️ (server), 📱 (mobile), 🏠 (home).
        short_name: Optional human-readable identifier for discovery (e.g., "alice").
            Claimed by the node, not globally unique. 3-20 chars, lowercase alphanumeric + hyphens.
        provider: Identity provider type ("file" or "yubikey").
        yubikey: YubiKey-specific configuration (used when provider is "yubikey").
    """

    display_name: str = "Anonymous Styrene"
    icon: str = "🔗"
    short_name: str | None = None
    provider: str = "file"
    yubikey: YubiKeyConfig = field(default_factory=YubiKeyConfig)


@dataclass
class MetricsConfig:
    """Prometheus metrics endpoint configuration.

    Attributes:
        enabled: Whether to enable the /metrics endpoint.
    """

    enabled: bool = False


@dataclass
class WebAuthConfig:
    """RNS identity-based authentication for the web API.

    Uses Ed25519 challenge-response with RNS identities.  A phone or
    remote client proves possession of an authorized RNS identity by
    signing a server-issued nonce, then receives a session token.

    Authorization is handled by the RBAC policy on CoreConfig — identities
    need WEB_READ capability to authenticate and WEB_WRITE for mutations.

    Attributes:
        enabled: Whether to require authentication for API access.
        exempt_localhost: Requests from loopback addresses bypass auth entirely.
        session_ttl: Session token lifetime in seconds (default 24 hours).
    """

    enabled: bool = False
    exempt_localhost: bool = True
    session_ttl: int = 86400


@dataclass
class APIConfig:
    """HTTP API configuration for headless mode.

    Attributes:
        enabled: Whether to enable HTTP API.
        host: IP address to bind to.
        port: TCP port for API server.
        public_mode: If true, reject all write operations via the web API (read-only dashboard).
        metrics: Prometheus metrics endpoint configuration.
        auth: RNS identity-based authentication configuration.
    """

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    public_mode: bool = False
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    auth: WebAuthConfig = field(default_factory=WebAuthConfig)


@dataclass
class RPCConfig:
    """RPC server configuration.

    Attributes:
        enabled: Whether to enable the RPC server.
        relay_mode: If true, relay RPC messages without executing commands.
        allow_command_execution: If true, execute received RPC commands (edge devices only).
    """

    enabled: bool = True
    relay_mode: bool = False
    allow_command_execution: bool = True


class MeshAccessMode(Enum):
    """Mesh admission control policy.

    Controls which announcing nodes are admitted to the device list.

    OPEN     — default; every announcing node is accepted (legacy behaviour).
    ALLOWLIST — only nodes whose *identity hash* appears in
               ``DiscoveryConfig.allowed_peers`` are admitted.  All others are
               silently dropped at the announce-handler boundary.
    """

    OPEN = "open"
    ALLOWLIST = "allowlist"


@dataclass
class DiscoveryConfig:
    """Device discovery configuration.

    Attributes:
        enabled: Whether to enable device discovery.
        auto_announce: Automatically announce presence on startup.
        access_mode: Mesh admission policy.  ``OPEN`` (default) admits every
            announcing node; ``ALLOWLIST`` enforces a default-deny policy where
            only identity hashes listed in *allowed_peers* are accepted.
        allowed_peers: Set of 32-char hex identity hashes permitted to appear
            in the device list.  Only consulted when *access_mode* is
            ``ALLOWLIST``.  Hashes are matched case-insensitively.
        info_respond: Whether to respond to /info requests from unknown nodes.
            False (default) — deny all /info requests silently.
            True — respond with identifiable metadata (name, operator_label).
            Even when True, the RBAC roster controls which identities receive
            a response once RBAC Phase 3 is wired; this flag is the master
            on/off switch.
        operator_label: Optional short label included in /info responses when
            info_respond is True.  Not included in /meta responses.
    """

    enabled: bool = True
    auto_announce: bool = True
    access_mode: MeshAccessMode = MeshAccessMode.OPEN
    allowed_peers: set[str] = field(default_factory=set)
    info_respond: bool = False
    operator_label: str = ""


@dataclass
class ChatbotConfig:
    """LLM chatbot configuration for auto-reply chatbot mode.

    Used when auto_reply_mode is CHATBOT. Connects to any OpenAI-compatible
    chat completions endpoint (ollama, OpenRouter, vLLM, etc.).

    Attributes:
        endpoint: Base URL of the OpenAI-compatible API.
        model: Model name to use for chat completions.
        api_key: API key for authentication. Falls back to
            $STYRENED_CHATBOT_API_KEY environment variable.
        system_prompt: System prompt template. Supports same placeholders
            as auto_reply_message: {hostname}, {identity}, {uptime}, {version}.
        max_tokens: Maximum tokens in the LLM response.
        temperature: Sampling temperature (0.0-2.0).
        max_context_messages: Maximum conversation history messages to include.
    """

    endpoint: str = "http://localhost:11434/v1"
    model: str = "llama3"
    api_key: str = ""
    system_prompt: str = (
        "You are an automated assistant running on {hostname}, a Reticulum mesh "
        "network node (styrened {version}, up {uptime}). You are NOT a human "
        "operator — be upfront about that if asked.\n\n"
        "Guidelines:\n"
        "- Be friendly and conversational. Match the tone of the person messaging you.\n"
        "- Keep responses short (1-3 sentences). This is a low-bandwidth mesh link.\n"
        "- Only share node status (uptime, version) when specifically asked.\n"
        "- For casual messages (greetings, small talk), respond naturally — "
        "don't pivot to technical info unprompted.\n"
        "- If you don't know something, say so. Don't fabricate node data."
    )
    max_tokens: int = 256
    temperature: float = 0.7
    max_context_messages: int = 10


@dataclass
class ChatConfig:
    """Chat and messaging configuration.

    Attributes:
        enabled: Whether to enable chat/LXMF messaging.
        auto_reply_mode: How the node handles incoming messages automatically.
        auto_reply_message: Message to send as auto-reply in template mode.
            Supports placeholders: {hostname}, {identity}, {uptime}, {version}
        auto_reply_cooldown: Minimum seconds between auto-replies to same sender.
            Prevents spam loops with other auto-reply bots.
        persist_messages: Store messages in database (requires SQLite).
        chatbot: LLM chatbot configuration (used when mode is CHATBOT).
    """

    enabled: bool = True
    auto_reply_mode: AutoReplyMode = AutoReplyMode.DISABLED
    auto_reply_message: str = (
        "This is {hostname}, a Styrene mesh node running in headless mode. "
        "No operator is currently available to respond. "
        "For more information about Styrene, visit: https://github.com/styrene-lab"
    )
    auto_reply_cooldown: int = 300  # 5 minutes between replies to same sender
    persist_messages: bool = True
    chatbot: ChatbotConfig = field(default_factory=ChatbotConfig)


@dataclass
class NotificationsConfig:
    """Notification delivery configuration.

    Controls how and when notifications are dispatched for incoming
    messages, delivery status changes, and other events.

    Attributes:
        enabled: Whether notifications are enabled globally.
        quiet_hours_start: Hour (0-23) when quiet hours begin (None = disabled).
        quiet_hours_end: Hour (0-23) when quiet hours end (None = disabled).
    """

    enabled: bool = True
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None


@dataclass
class IPCConfig:
    """IPC control socket configuration.

    Configures the Unix socket used for CLI/TUI communication with the daemon.

    Attributes:
        enabled: Whether to enable the IPC control socket.
        socket_path: Path to Unix socket (None = auto-detect).
            Auto-detection order:
            1. $STYRENED_SOCKET environment variable
            2. /run/styrened/control.sock (system daemon)
            3. $XDG_RUNTIME_DIR/styrened/control.sock (user session)
            4. ~/.local/run/styrened/control.sock (fallback)
        socket_mode: File permissions for socket (default: 0o660).
    """

    enabled: bool = True
    socket_path: Path | None = None
    socket_mode: int = 0o660


@dataclass
class PropagationNodeConfig:
    """Configuration for acting as an LXMF propagation node.

    When enabled, this node will store and forward messages for other nodes
    in the mesh, improving message delivery reliability.

    Attributes:
        enabled: Whether to enable propagation node mode.
        name: Display name for propagation node announces.
    """

    enabled: bool = False
    name: str | None = None


@dataclass
class LXMFConfig:
    """LXMF messaging and propagation configuration.

    Controls LXMF router behavior including propagation node settings,
    peer management, and sync limits. These settings expose the underlying
    LXMRouter configuration options for advanced mesh deployments.

    Attributes:
        propagation_node: Configuration for acting as a propagation node.
        propagation_destination: Hex hash of preferred outbound propagation node.
            If set, messages without a direct path will be sent via this node.
        propagation_limit: Maximum message size for propagation in KB (default: 256).
        sync_limit: Maximum sync size in KB (default: 10240).
        delivery_limit: Maximum messages per transfer (default: 1000).
        autopeer: Enable automatic peering with other propagation nodes.
        autopeer_maxdepth: Maximum depth for automatic peering (default: 4).
        max_peers: Maximum number of propagation peers (default: 20).
        static_peers: List of static peer addresses (32-char hex hashes).
        from_static_only: Only connect to static peers (ignore discovered peers).
        propagation_cost: Stamp cost for propagation (default: 16).
        propagation_cost_flexibility: Cost flexibility (default: 3).
        peering_cost: Cost for peering (default: 18).
        max_peering_cost: Maximum peering cost (default: 26).
    """

    # Propagation node mode (act as a propagation node)
    propagation_node: PropagationNodeConfig = field(default_factory=PropagationNodeConfig)

    # Outbound propagation (use a specific propagation node)
    propagation_destination: str | None = None  # 32-char hex hash

    # Sync limits
    propagation_limit: int = 256  # KB per transfer
    sync_limit: int = 10240  # KB total sync
    delivery_limit: int = 1000  # messages per transfer

    # Peer management
    autopeer: bool = True
    autopeer_maxdepth: int = 4
    max_peers: int = 20
    static_peers: list[str] = field(default_factory=list)
    from_static_only: bool = False

    # Cost settings (for propagation node mode)
    propagation_cost: int = 16
    propagation_cost_flexibility: int = 3
    peering_cost: int = 18
    max_peering_cost: int = 26


# -----------------------------------------------------------------------------
# Core configuration root
# -----------------------------------------------------------------------------


@dataclass
class TerminalConfig:
    """Terminal session configuration.

    Controls remote terminal access to this node via the Styrene terminal protocol.
    Terminal sessions use a two-plane architecture:
    - LXMF control plane for session establishment/teardown
    - RNS Link data plane for I/O streaming

    Authorization is handled by the RBAC policy on CoreConfig — identities
    need TERMINAL_RESTRICTED or TERMINAL_FULL capability.

    Attributes:
        enabled: Whether to enable terminal service.
        default_shell: Shell to spawn for sessions (default: user's shell).
        session_idle_timeout: Seconds of inactivity before session close (0=disabled).
        max_sessions_per_identity: Maximum concurrent sessions per identity.
        max_total_sessions: Maximum total concurrent sessions.
        rate_limit_requests: Maximum session requests per minute per identity.
    """

    enabled: bool = False
    default_shell: str | None = None
    allowed_shells: set[str] = field(default_factory=set)  # Empty = use defaults
    session_idle_timeout: int = 3600  # 1 hour default
    max_sessions_per_identity: int = 3
    max_total_sessions: int = 10
    rate_limit_requests: int = 10  # requests per minute per identity


@dataclass
class PageServerConfig:
    """NomadNet page server configuration.

    Controls serving NomadNet-compatible pages over RNS, optionally enhanced
    with Styrene structured data directives.  The page server creates the
    ``("nomadnetwork", "node")`` destination unless NomadNet already owns it
    (hub guard).

    Attributes:
        enabled: Whether to enable the page server service.
        pages_dir: Directory containing ``.mu`` page files.
            Defaults to ``~/.styrene/pages/`` if None.
        node_name: Display name included in NomadNet announces.
        demo: Whether to register demo/test pages on startup.
    """

    enabled: bool = False
    pages_dir: Path | None = None
    node_name: str | None = None
    demo: bool = False


@dataclass
class PQCConfig:
    """Post-quantum cryptographic session layer configuration.

    Controls hybrid PQC session negotiation with Styrene peers.
    Uses X25519 + ML-KEM-768 combined via HKDF for key exchange.

    Attributes:
        enabled: Whether to auto-negotiate PQC sessions with capable peers.
        rekey_interval_hours: Hours between time-based session rekeying.
        require_pqc_for_rpc: Reject RPC commands from non-PQC peers.
        auto_initiate: Automatically initiate PQC handshake on device discovery.
    """

    enabled: bool = True
    rekey_interval_hours: int = 24
    require_pqc_for_rpc: bool = False
    auto_initiate: bool = True


@dataclass
class MeshVPNConfig:
    """Mesh VPN configuration.

    WireGuard tunnels bootstrapped over RNS.Link for IP connectivity
    across the Styrene mesh. Gateway nodes bridge VPN into bat0.

    Attributes:
        enable: Whether the mesh VPN service is active.
        listen_port: WireGuard listen port.
        subnet_prefix: ULA IPv6 prefix (default: fd73:7479:7265:6e65).
        gateway: Whether this node bridges VPN traffic into bat0.
        endpoint: Public WireGuard endpoint (IP:port). Auto-detected if empty.
    """

    enable: bool = False
    listen_port: int = 51820
    subnet_prefix: str = "fd73:7479:7265:6e65"
    gateway: bool = False
    endpoint: str = ""
    peer_discovery: str = "lazy"  # "eager" | "lazy" — when to fetch /meta for Ygg address


class PeerDiscovery(str, Enum):
    """Controls when /meta is fetched for Yggdrasil peer bootstrapping.

    - EAGER: fetch /meta and call add_peer() immediately on each announce
      that carries CAPABILITY_YGGDRASIL (when bootstrap_from_rns=True).
    - LAZY: only bootstrap when the user explicitly requests a connection.
    """

    EAGER = "eager"
    LAZY = "lazy"


@dataclass
class YggdrasilConfig:
    """Configuration for Yggdrasil overlay network integration.

    Attributes:
        mode: How styrened interacts with Yggdrasil (disabled/adopt/managed).
        binary_path: Path to the yggdrasil binary (used in MANAGED mode).
        listen_port: Port for the managed Yggdrasil instance (distinct from
            the system default of 9001 to avoid conflicts).
        admin_socket: Path to the admin Unix socket. Empty means auto-detect.
        multicast: Enable multicast peer discovery on the local network.
        bootstrap_from_rns: Advertise and discover Yggdrasil peers via RNS
            announces so mesh-connected nodes can peer automatically.
        peer_discovery: Whether to bootstrap peers eagerly (on every announce)
            or lazily (only on explicit request).
        initial_peers: Static list of Yggdrasil peer URIs to connect to.
    """

    mode: DaemonMode = DaemonMode.DISABLED
    binary_path: str = "yggdrasil"
    listen_port: int = 9002
    admin_socket: str = ""
    multicast: bool = True
    bootstrap_from_rns: bool = True
    peer_discovery: PeerDiscovery = PeerDiscovery.EAGER
    initial_peers: list = field(default_factory=list)


@dataclass
class I2PConfig:
    """Configuration for I2P (i2pd) integration.

    Attributes:
        mode: How styrened interacts with i2pd (disabled/adopt/managed).
        http_proxy_host: Host where the I2P HTTP proxy is listening.
        http_proxy_port: Port used when adopting an existing i2pd instance.
        managed_http_proxy_port: Port used for the managed i2pd instance
            (distinct from the default 4444 to avoid conflicts).
        managed_i2pcontrol_port: I2PControl API port for the managed instance.
        b32_address: Static b32 address override. Leave empty for auto-detect.
        cache_ttl: Seconds to cache resolved I2P addresses.
        fetch_timeout: Seconds before an I2P fetch request times out.
    """

    mode: DaemonMode = DaemonMode.DISABLED
    http_proxy_host: str = "127.0.0.1"
    http_proxy_port: int = 4444
    managed_http_proxy_port: int = 4445
    managed_i2pcontrol_port: int = 7651
    b32_address: str = ""
    cache_ttl: int = 3600
    fetch_timeout: float = 45.0


class GroupThreadFeatureTierConfig(str, Enum):
    """Local feature/storage tier for group-thread support."""

    MINIMAL = "minimal"
    BALANCED = "balanced"
    FULL = "full"


@dataclass
class GroupThreadsConfig:
    """Configuration for group-thread footprint and richer-room behavior."""

    enabled: bool = True
    feature_tier: GroupThreadFeatureTierConfig = GroupThreadFeatureTierConfig.BALANCED
    bounded_retention: bool = False
    auto_media_fetch: bool = True
    metadata_first_sync: bool = False
    background_catchup: bool = True
    first_run_auto_tier: bool = True


@dataclass
class SecurityConfig:
    """Security-related configuration.

    Attributes:
        strict_binary_verification: When True, refuse to start managed
            adapters whose binary SHA-256 doesn't match the manifest.
            When False (default), log a WARNING but start anyway.
    """

    strict_binary_verification: bool = False


@dataclass
class LoggingConfig:
    """Logging subsystem configuration.

    Attributes:
        boundary_sink: When True, boundary-tagged log records are also written
            as NDJSON lines to ~/.local/share/styrene/boundary.log
            (size-rotated, 1 MB max, 3 backups).  Defaults to False so the
            ring-buffer-only mode is used out of the box.
    """

    boundary_sink: bool = False


@dataclass
class CoreConfig:
    """Core Styrene configuration for headless applications.

    This is the root configuration object for headless/daemon mode,
    containing only core mesh and messaging settings.

    Attributes:
        profile: Operational profile (operator or endpoint).
        reticulum: Reticulum integration settings.
        identity: Identity appearance configuration.
        rpc: RPC server configuration.
        discovery: Device discovery configuration.
        chat: Chat and messaging configuration.
        api: HTTP API configuration.
        ipc: IPC control socket configuration.
        notifications: Notification delivery configuration.
        lxmf: LXMF messaging and propagation configuration.
        terminal: Terminal session configuration.
        page_server: NomadNet page server configuration.
        pqc: Post-quantum cryptographic session layer configuration.
        mesh_vpn: WireGuard mesh VPN configuration.
        yggdrasil: Yggdrasil overlay network integration.
        i2p: I2P network integration.
        group_threads: Group-thread footprint and feature-tier policy.
    """

    profile: Profile = Profile.OPERATOR
    reticulum: ReticulumConfig = field(default_factory=ReticulumConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    rpc: RPCConfig = field(default_factory=RPCConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    api: APIConfig = field(default_factory=APIConfig)
    ipc: IPCConfig = field(default_factory=IPCConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    lxmf: LXMFConfig = field(default_factory=LXMFConfig)
    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    page_server: PageServerConfig = field(default_factory=PageServerConfig)
    pqc: PQCConfig = field(default_factory=PQCConfig)
    mesh_vpn: MeshVPNConfig = field(default_factory=MeshVPNConfig)
    relay: RelayConfig = field(default_factory=lambda: _default_relay_config())
    rbac: RBACPolicy = field(default_factory=RBACPolicy)
    yggdrasil: YggdrasilConfig = field(default_factory=YggdrasilConfig)
    i2p: I2PConfig = field(default_factory=I2PConfig)
    group_threads: GroupThreadsConfig = field(default_factory=GroupThreadsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    def to_dict(self) -> dict[str, Any]:
        """Serialize CoreConfig to a dictionary suitable for YAML output.

        This is used by the IPC layer, TUI settings screen, and any consumer
        that needs to round-trip CoreConfig through a dict representation.

        Returns:
            Nested dictionary matching the YAML config file structure.
        """
        # Reticulum section
        reticulum_dict: dict[str, Any] = {
            "mode": self.reticulum.mode.value,
            "auto_initialize": self.reticulum.auto_initialize,
            "announce_interval": self.reticulum.announce_interval,
            "hub_enabled": self.reticulum.hub_enabled,
            "hub_announce_interval": self.reticulum.hub_announce_interval,
        }
        if self.reticulum.enable_transport is not None:
            reticulum_dict["enable_transport"] = self.reticulum.enable_transport
        if self.reticulum.config_path_override is not None:
            reticulum_dict["config_path_override"] = str(self.reticulum.config_path_override)
        if self.reticulum.operator_identity_path is not None:
            reticulum_dict["operator_identity_path"] = str(self.reticulum.operator_identity_path)
        if self.reticulum.hub_address is not None:
            reticulum_dict["hub_address"] = self.reticulum.hub_address

        # Interfaces sub-section
        interfaces_dict: dict[str, Any] = {
            "auto": self.reticulum.interfaces.auto,
            "server": {
                "enabled": self.reticulum.interfaces.server.enabled,
                "listen_ip": self.reticulum.interfaces.server.listen_ip,
                "port": self.reticulum.interfaces.server.port,
            },
        }
        if self.reticulum.interfaces.peers:
            interfaces_dict["peers"] = [
                {
                    "host": p.host,
                    "port": p.port,
                    **({"name": p.name} if p.name else {}),
                    "enabled": p.enabled,
                }
                for p in self.reticulum.interfaces.peers
            ]
        reticulum_dict["interfaces"] = interfaces_dict

        # Identity section
        identity_dict: dict[str, Any] = {
            "display_name": self.identity.display_name,
            "icon": self.identity.icon,
            "provider": self.identity.provider,
        }
        if self.identity.short_name:
            identity_dict["short_name"] = self.identity.short_name
        if self.identity.provider == "yubikey" or self.identity.yubikey.credential_id:
            identity_dict["yubikey"] = {
                "credential_id": self.identity.yubikey.credential_id,
                "rp_id": self.identity.yubikey.rp_id,
                "require_touch": self.identity.yubikey.require_touch,
            }

        # RPC section
        rpc_dict: dict[str, Any] = {
            "enabled": self.rpc.enabled,
            "relay_mode": self.rpc.relay_mode,
            "allow_command_execution": self.rpc.allow_command_execution,
        }

        # Discovery section
        discovery_dict: dict[str, Any] = {
            "enabled": self.discovery.enabled,
            "auto_announce": self.discovery.auto_announce,
            "access_mode": self.discovery.access_mode.value,
            "allowed_peers": sorted(self.discovery.allowed_peers),
            "info_respond": self.discovery.info_respond,
        }
        if self.discovery.operator_label:
            discovery_dict["operator_label"] = self.discovery.operator_label

        # Chat section
        chat_dict: dict[str, Any] = {
            "enabled": self.chat.enabled,
            "auto_reply_mode": self.chat.auto_reply_mode.value,
            "auto_reply_message": self.chat.auto_reply_message,
            "auto_reply_cooldown": self.chat.auto_reply_cooldown,
            "persist_messages": self.chat.persist_messages,
        }
        # Include chatbot config
        chatbot_dict: dict[str, Any] = {
            "endpoint": self.chat.chatbot.endpoint,
            "model": self.chat.chatbot.model,
            "system_prompt": self.chat.chatbot.system_prompt,
            "max_tokens": self.chat.chatbot.max_tokens,
            "temperature": self.chat.chatbot.temperature,
            "max_context_messages": self.chat.chatbot.max_context_messages,
        }
        if self.chat.chatbot.api_key:
            chatbot_dict["api_key"] = self.chat.chatbot.api_key
        chat_dict["chatbot"] = chatbot_dict

        # API section
        auth_dict: dict[str, Any] = {
            "enabled": self.api.auth.enabled,
            "exempt_localhost": self.api.auth.exempt_localhost,
            "session_ttl": self.api.auth.session_ttl,
        }

        api_dict: dict[str, Any] = {
            "enabled": self.api.enabled,
            "host": self.api.host,
            "port": self.api.port,
            "public_mode": self.api.public_mode,
            "metrics": {
                "enabled": self.api.metrics.enabled,
            },
            "auth": auth_dict,
        }

        # IPC section
        ipc_dict: dict[str, Any] = {
            "enabled": self.ipc.enabled,
            "socket_mode": self.ipc.socket_mode,
        }
        if self.ipc.socket_path is not None:
            ipc_dict["socket_path"] = str(self.ipc.socket_path)

        # Notifications section
        notifications_dict: dict[str, Any] = {
            "enabled": self.notifications.enabled,
        }
        if self.notifications.quiet_hours_start is not None:
            notifications_dict["quiet_hours_start"] = self.notifications.quiet_hours_start
        if self.notifications.quiet_hours_end is not None:
            notifications_dict["quiet_hours_end"] = self.notifications.quiet_hours_end

        # LXMF section
        lxmf_dict: dict[str, Any] = {
            "propagation_node": {
                "enabled": self.lxmf.propagation_node.enabled,
            },
            "propagation_limit": self.lxmf.propagation_limit,
            "sync_limit": self.lxmf.sync_limit,
            "delivery_limit": self.lxmf.delivery_limit,
            "autopeer": self.lxmf.autopeer,
            "autopeer_maxdepth": self.lxmf.autopeer_maxdepth,
            "max_peers": self.lxmf.max_peers,
            "from_static_only": self.lxmf.from_static_only,
            "propagation_cost": self.lxmf.propagation_cost,
            "propagation_cost_flexibility": self.lxmf.propagation_cost_flexibility,
            "peering_cost": self.lxmf.peering_cost,
            "max_peering_cost": self.lxmf.max_peering_cost,
        }
        if self.lxmf.propagation_node.name is not None:
            lxmf_dict["propagation_node"]["name"] = self.lxmf.propagation_node.name
        if self.lxmf.propagation_destination is not None:
            lxmf_dict["propagation_destination"] = self.lxmf.propagation_destination
        if self.lxmf.static_peers:
            lxmf_dict["static_peers"] = list(self.lxmf.static_peers)

        # Terminal section
        terminal_dict: dict[str, Any] = {
            "enabled": self.terminal.enabled,
            "session_idle_timeout": self.terminal.session_idle_timeout,
            "max_sessions_per_identity": self.terminal.max_sessions_per_identity,
            "max_total_sessions": self.terminal.max_total_sessions,
            "rate_limit_requests": self.terminal.rate_limit_requests,
        }
        if self.terminal.default_shell is not None:
            terminal_dict["default_shell"] = self.terminal.default_shell
        if self.terminal.allowed_shells:
            terminal_dict["allowed_shells"] = sorted(self.terminal.allowed_shells)

        # Page server section
        page_server_dict: dict[str, Any] = {
            "enabled": self.page_server.enabled,
        }
        if self.page_server.pages_dir is not None:
            page_server_dict["pages_dir"] = str(self.page_server.pages_dir)
        if self.page_server.node_name is not None:
            page_server_dict["node_name"] = self.page_server.node_name
        if self.page_server.demo:
            page_server_dict["demo"] = True

        # PQC section
        pqc_dict: dict[str, Any] = {
            "enabled": self.pqc.enabled,
            "rekey_interval_hours": self.pqc.rekey_interval_hours,
            "require_pqc_for_rpc": self.pqc.require_pqc_for_rpc,
            "auto_initiate": self.pqc.auto_initiate,
        }

        result: dict[str, Any] = {
            "profile": self.profile.value,
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
            "page_server": page_server_dict,
            "pqc": pqc_dict,
            "mesh_vpn": {
                "enable": self.mesh_vpn.enable,
                "listen_port": self.mesh_vpn.listen_port,
                "subnet_prefix": self.mesh_vpn.subnet_prefix,
                "gateway": self.mesh_vpn.gateway,
                "endpoint": self.mesh_vpn.endpoint,
            },
            "relay": {
                "enabled": self.relay.enabled,
                "max_sessions": self.relay.max_sessions,
                "max_per_identity": self.relay.max_per_identity,
                "max_bytes_per_session": self.relay.max_bytes_per_session,
                "idle_timeout": self.relay.idle_timeout,
                "allow_permanent": self.relay.allow_permanent,
                "allowed_identities": self.relay.allowed_identities,
            },
            "yggdrasil": {
                "mode": self.yggdrasil.mode.value,
                "binary_path": self.yggdrasil.binary_path,
                "listen_port": self.yggdrasil.listen_port,
                "admin_socket": self.yggdrasil.admin_socket,
                "multicast": self.yggdrasil.multicast,
                "bootstrap_from_rns": self.yggdrasil.bootstrap_from_rns,
                "peer_discovery": self.yggdrasil.peer_discovery.value,
                "initial_peers": list(self.yggdrasil.initial_peers),
            },
            "i2p": {
                "mode": self.i2p.mode.value,
                "http_proxy_host": self.i2p.http_proxy_host,
                "http_proxy_port": self.i2p.http_proxy_port,
                "managed_http_proxy_port": self.i2p.managed_http_proxy_port,
                "managed_i2pcontrol_port": self.i2p.managed_i2pcontrol_port,
                "b32_address": self.i2p.b32_address,
                "cache_ttl": self.i2p.cache_ttl,
                "fetch_timeout": self.i2p.fetch_timeout,
            },
            "group_threads": {
                "enabled": self.group_threads.enabled,
                "feature_tier": self.group_threads.feature_tier.value,
                "bounded_retention": self.group_threads.bounded_retention,
                "auto_media_fetch": self.group_threads.auto_media_fetch,
                "metadata_first_sync": self.group_threads.metadata_first_sync,
                "background_catchup": self.group_threads.background_catchup,
                "first_run_auto_tier": self.group_threads.first_run_auto_tier,
            },
        }

        # Security section
        result["security"] = {
            "strict_binary_verification": self.security.strict_binary_verification,
        }

        # Logging section
        result["logging"] = {
            "boundary_sink": self.logging.boundary_sink,
        }

        # Serialize RBAC policy
        rbac_roster = []
        for entry in sorted(self.rbac.roster.values(), key=lambda e: e.identity_hash):
            d: dict[str, Any] = {
                "identity": entry.identity_hash,
                "role": entry.role.name.lower(),
            }
            if entry.label:
                d["label"] = entry.label
            if entry.grants:
                d["grants"] = sorted(entry.grants)
            rbac_roster.append(d)

        result["rbac"] = {
            "default_role": self.rbac.default_role.name.lower(),
            "roster": rbac_roster,
            "blocked": self.rbac.blocked,
        }

        return result


def _default_relay_config():
    from styrened.models.relay import RelayConfig
    return RelayConfig()
