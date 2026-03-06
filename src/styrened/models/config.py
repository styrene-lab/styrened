"""Core configuration models for Styrene.

This module contains configuration models that are shared between
headless (core) and TUI applications. TUI-specific config is in
styrene-tui/src/styrene/models/config.py.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

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

    Attributes:
        enabled: Whether to require authentication for API access.
        authorized_identities: Set of 32-char hex identity hashes allowed to authenticate.
            If empty and allow_unauthenticated is False, only localhost is allowed.
        allow_unauthenticated: Skip whitelist check — any identity that completes
            the challenge-response is granted a session.
        exempt_localhost: Requests from loopback addresses bypass auth entirely.
        session_ttl: Session token lifetime in seconds (default 24 hours).
    """

    enabled: bool = False
    authorized_identities: set[str] = field(default_factory=set)
    allow_unauthenticated: bool = False
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

    Attributes:
        enabled: Whether to enable terminal service.
        authorized_identities: Set of identity hashes allowed to connect.
            If empty and allow_unauthenticated=False, all connections rejected.
        allow_unauthenticated: Allow connections from any identity.
            WARNING: This grants remote shell access - use with caution.
        default_shell: Shell to spawn for sessions (default: user's shell).
        session_idle_timeout: Seconds of inactivity before session close (0=disabled).
        max_sessions_per_identity: Maximum concurrent sessions per identity.
        max_total_sessions: Maximum total concurrent sessions.
        rate_limit_requests: Maximum session requests per minute per identity.
    """

    enabled: bool = False
    authorized_identities: set[str] = field(default_factory=set)
    allow_unauthenticated: bool = False
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
    banned_peers: list[str] = field(default_factory=list)
    rbac: "RBACPolicy | None" = None  # Lazy import to avoid circular deps
