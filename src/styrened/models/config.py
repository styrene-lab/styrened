"""Core configuration models for Styrene.

This module contains configuration models that are shared between
headless (core) and TUI applications. TUI-specific config is in
styrene-tui/src/styrene/models/config.py.
"""

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
    """

    host: str
    port: int = 4242
    name: str | None = None


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

    def resolve_operator_identity_path(self) -> Path:
        """Get the operator identity path.

        Returns:
            Path to operator identity file.
        """
        if self.operator_identity_path:
            return self.operator_identity_path

        from platformdirs import user_config_dir

        config_dir = Path(user_config_dir("styrene"))
        return config_dir / "operator.key"


@dataclass
class IdentityConfig:
    """Identity appearance configuration for ecosystem compatibility.

    Controls how this node appears to other LXMF clients (Sideband, NomadNet, MeshChat).
    These fields are included in announces and message metadata.

    Attributes:
        display_name: Human-readable name shown in chat clients.
            Defaults to "Anonymous Styrene".
        icon: Emoji or short string displayed as identity icon.
            Defaults to 🔗. Common alternatives: 🖥️ (server), 📱 (mobile), 🏠 (home).
    """

    display_name: str = "Anonymous Styrene"
    icon: str = "🔗"


@dataclass
class APIConfig:
    """HTTP API configuration for headless mode.

    Attributes:
        enabled: Whether to enable HTTP API.
        host: IP address to bind to.
        port: TCP port for API server.
    """

    enabled: bool = False
    host: str = "0.0.0.0"
    port: int = 8000


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


@dataclass
class DiscoveryConfig:
    """Device discovery configuration.

    Attributes:
        enabled: Whether to enable device discovery.
        auto_announce: Automatically announce presence on startup.
    """

    enabled: bool = True
    auto_announce: bool = True


@dataclass
class ChatConfig:
    """Chat and messaging configuration.

    Attributes:
        enabled: Whether to enable chat/LXMF messaging.
        auto_reply_enabled: Send automatic replies when running headless.
        auto_reply_message: Message to send as auto-reply.
            Supports placeholders: {hostname}, {identity}, {uptime}, {version}
        auto_reply_cooldown: Minimum seconds between auto-replies to same sender.
            Prevents spam loops with other auto-reply bots.
        persist_messages: Store messages in database (requires SQLite).
    """

    enabled: bool = True
    auto_reply_enabled: bool = True
    auto_reply_message: str = (
        "This is {hostname}, a Styrene mesh node running in headless mode. "
        "No operator is currently available to respond. "
        "For more information about Styrene, visit: https://github.com/styrene-lab"
    )
    auto_reply_cooldown: int = 300  # 5 minutes between replies to same sender
    persist_messages: bool = True


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
class CoreConfig:
    """Core Styrene configuration for headless applications.

    This is the root configuration object for headless/daemon mode,
    containing only core mesh and messaging settings.

    Attributes:
        reticulum: Reticulum integration settings.
        identity: Identity appearance configuration.
        rpc: RPC server configuration.
        discovery: Device discovery configuration.
        chat: Chat and messaging configuration.
        api: HTTP API configuration.
        ipc: IPC control socket configuration.
        lxmf: LXMF messaging and propagation configuration.
    """

    reticulum: ReticulumConfig = field(default_factory=ReticulumConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)
    rpc: RPCConfig = field(default_factory=RPCConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    api: APIConfig = field(default_factory=APIConfig)
    ipc: IPCConfig = field(default_factory=IPCConfig)
    lxmf: LXMFConfig = field(default_factory=LXMFConfig)
