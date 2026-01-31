"""Reticulum configuration and device discovery service.

This module provides core Reticulum functionality for headless applications:

- Detecting if Reticulum is configured
- Reading identity from storage/identity
- Parsing interface configuration from config file
- Following Reticulum's config path priority order
- Managing operator identity
- Device discovery via RNS announces

Config path priority (matches Reticulum behavior):
1. Explicit override from config
2. /etc/reticulum (system-wide)
3. ~/.config/reticulum (XDG compliant)
4. ~/.reticulum (legacy default)
"""

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from styrened.models.config import CoreConfig, DeploymentMode
from styrened.models.mesh_device import MeshDevice, create_mesh_device
from styrened.models.reticulum import (
    ReticulumIdentity,
    ReticulumInterface,
    ReticulumNotConfiguredError,
)

# Conditional RNS import
if TYPE_CHECKING:
    import RNS
else:
    # Try to import RNS at runtime, but don't fail if not available
    try:
        import RNS  # type: ignore[import-untyped]
    except ImportError:
        RNS = None  # type: ignore[assignment]

# Setup logger
logger = logging.getLogger(__name__)

# Operator identity storage
OPERATOR_IDENTITY_PATH = Path.home() / ".styrene" / "operator.key"


def get_reticulum_config_paths() -> list[Path]:
    """Return Reticulum config search paths in priority order.

    Reticulum searches these locations for configuration:
    1. /etc/reticulum (system-wide)
    2. ~/.config/reticulum (XDG compliant)
    3. ~/.reticulum (legacy default)

    Returns:
        List of paths to check, in priority order.
    """
    return [
        Path("/etc/reticulum"),
        Path.home() / ".config" / "reticulum",
        Path.home() / ".reticulum",
    ]


def find_reticulum_config(override: Path | None = None) -> Path | None:
    """Find the active Reticulum configuration directory.

    Checks the override path first (if provided), then searches
    standard locations in priority order.

    Args:
        override: If provided, check this path first.

    Returns:
        Path to Reticulum config directory, or None if not found.
    """
    # Check override first
    if override and is_reticulum_configured(config_dir=override):
        return override

    # Search standard paths in priority order
    for path in get_reticulum_config_paths():
        if is_reticulum_configured(config_dir=path):
            return path

    return None


def _get_default_config_dir() -> Path:
    """Return the default Reticulum configuration directory.

    This returns the legacy default (~/.reticulum). For proper
    priority-based lookup, use find_reticulum_config() instead.
    """
    return Path.home() / ".reticulum"


def is_reticulum_configured(config_dir: Path | None = None) -> bool:
    """Check if Reticulum is properly configured.

    A proper configuration requires:
    1. The configuration directory exists
    2. The config file exists

    Note: We only check for the config file, not identity files, because:
    - RNS daemon creates storage/transport_identity automatically
    - Per-app identities are created on first use
    - Presence of config indicates intentional RNS setup

    Args:
        config_dir: Path to Reticulum config directory. Defaults to ~/.reticulum.

    Returns:
        True if Reticulum is configured, False otherwise.
    """
    if config_dir is None:
        config_dir = _get_default_config_dir()

    if not config_dir.exists():
        return False

    config_file = config_dir / "config"
    return config_file.exists()


def _read_identity(config_dir: Path) -> ReticulumIdentity:
    """Read and parse the Reticulum identity file.

    The identity file contains binary key material. We read a portion
    of it and convert to hex for display purposes.

    Args:
        config_dir: Path to Reticulum config directory.

    Returns:
        ReticulumIdentity with the hex-encoded address.

    Raises:
        ReticulumNotConfiguredError: If identity file doesn't exist.
    """
    identity_file = config_dir / "storage" / "identity"

    if not identity_file.exists():
        raise ReticulumNotConfiguredError()

    try:
        identity_bytes = identity_file.read_bytes()
    except OSError as e:
        raise ReticulumNotConfiguredError() from e

    # Convert to hex string for the address
    # Reticulum identities are typically 32+ bytes
    address = identity_bytes[:32].hex()

    return ReticulumIdentity(address=address)


def _parse_interfaces(config_file: Path) -> list[ReticulumInterface]:
    """Parse interface definitions from Reticulum config file.

    Reticulum uses a ConfigParser-like format with [[interface_name]] sections
    for interfaces. We parse these to extract interface information.

    Args:
        config_file: Path to the Reticulum config file.

    Returns:
        List of ReticulumInterface objects.
    """
    interfaces: list[ReticulumInterface] = []

    try:
        content = config_file.read_text()
    except OSError:
        return interfaces

    # Reticulum config uses [[section]] for interfaces
    # We need to parse this non-standard format
    # Pattern: [[interface_name]] followed by key=value pairs
    interface_pattern = re.compile(
        r"\[\[([^\]]+)\]\]\s*\n((?:[^[\n].*\n)*)",
        re.MULTILINE,
    )

    for match in interface_pattern.finditer(content):
        name = match.group(1).strip()
        block = match.group(2)

        # Parse key=value pairs in the block
        interface_type = "Unknown"
        enabled = True

        for line in block.split("\n"):
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip().lower()
                value = value.strip()

                if key == "type":
                    interface_type = value
                elif key == "enabled":
                    enabled = value.lower() in ("true", "yes", "1")

        interfaces.append(
            ReticulumInterface(
                name=name,
                interface_type=interface_type,
                enabled=enabled,
            )
        )

    return interfaces


def get_reticulum_config_state(config_dir: Path | None = None) -> Any:
    """Read and return the complete Reticulum configuration.

    This function reads the Reticulum configuration directory and returns
    a ReticulumState object containing the identity and interface information.

    If config_dir is not specified, searches standard locations in priority
    order: /etc/reticulum, ~/.config/reticulum, ~/.reticulum

    Note: Returns ReticulumState (from models/reticulum.py), not ReticulumConfig
    (from models/config.py). Different concepts.

    Args:
        config_dir: Path to Reticulum config directory, or None to auto-detect.

    Returns:
        ReticulumState with identity, interfaces, and config path.

    Raises:
        ReticulumNotConfiguredError: If Reticulum is not properly configured.
    """
    from styrened.models.reticulum import ReticulumState

    # If explicit path given, use it; otherwise search standard locations
    resolved_dir = config_dir if config_dir is not None else find_reticulum_config()

    if resolved_dir is None or not is_reticulum_configured(config_dir=resolved_dir):
        raise ReticulumNotConfiguredError()

    identity = _read_identity(resolved_dir)
    config_file = resolved_dir / "config"
    interfaces = _parse_interfaces(config_file)

    return ReticulumState(
        identity=identity,
        interfaces=interfaces,
        config_path=resolved_dir,
    )


# Operator Identity Management


def ensure_operator_identity() -> str:
    """Ensure operator has a Reticulum identity.

    Generates a new RNS.Identity if one doesn't exist, or loads the existing one.
    The identity is stored in ~/.styrene/operator.key.

    Returns:
        Hex-encoded identity hash (destination address) - 32 hex characters (16 bytes).

    Raises:
        ImportError: If RNS library is not available.
        ValueError: If existing identity file is corrupt or invalid.
    """
    if not RNS:
        raise ImportError("RNS library not available. Install with: pip install rns")

    if OPERATOR_IDENTITY_PATH.exists():
        # Load existing identity
        identity = RNS.Identity.from_file(str(OPERATOR_IDENTITY_PATH))
        if identity is None:
            # RNS.Identity.from_file returns None on failure (doesn't raise)
            raise ValueError(
                f"Failed to load operator identity from {OPERATOR_IDENTITY_PATH}. "
                "The identity file may be corrupt. Delete it to regenerate: "
                f"rm {OPERATOR_IDENTITY_PATH}"
            )
        return str(identity.hash.hex())

    # Generate new RNS.Identity with X25519/Ed25519 keys
    identity = RNS.Identity(create_keys=True)

    # Ensure parent directory exists
    OPERATOR_IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Save identity to file
    identity.to_file(str(OPERATOR_IDENTITY_PATH))

    return str(identity.hash.hex())


def get_operator_identity_object() -> Any:
    """Get the operator identity as RNS.Identity object.

    Returns:
        RNS.Identity object, or None if not initialized or RNS not available.
    """
    if not RNS or not OPERATOR_IDENTITY_PATH.exists():
        return None

    return RNS.Identity.from_file(str(OPERATOR_IDENTITY_PATH))


def get_operator_identity() -> str | None:
    """Get the operator identity hash if it exists.

    Returns:
        Hex-encoded identity hash (32 hex characters), or None if not initialized.
    """
    if not OPERATOR_IDENTITY_PATH.exists():
        return None

    if not RNS:
        # Fallback: read raw bytes if RNS not available
        identity_bytes = OPERATOR_IDENTITY_PATH.read_bytes()
        return identity_bytes.hex()

    try:
        identity = RNS.Identity.from_file(str(OPERATOR_IDENTITY_PATH))
        if identity is None:
            # Fallback: read raw bytes if RNS can't parse
            identity_bytes = OPERATOR_IDENTITY_PATH.read_bytes()
            return identity_bytes.hex()
        return str(identity.hash.hex())
    except Exception:
        # Fallback: read raw bytes if RNS can't parse
        identity_bytes = OPERATOR_IDENTITY_PATH.read_bytes()
        return identity_bytes.hex()


# Device Discovery via RNS Announces


class StyreneAnnounceHandler:
    """Handles Reticulum announces for mesh device discovery.

    This handler listens to ALL announces on the network (no aspect filter)
    and tracks discovered devices as MeshDevice objects. Supports Styrene nodes,
    RNodes, and generic Reticulum announces.
    """

    def __init__(
        self,
        callback: Callable[[MeshDevice], None] | None = None,
        node_store: Any | None = None,
    ):
        """Initialize announce handler.

        Args:
            callback: Optional callback to invoke when a device is discovered/updated.
            node_store: Optional node store for persistence (dependency injection).
        """
        self.callback = callback
        self.node_store = node_store
        self.aspect_filter = None  # Listen to ALL announces
        self.discovered_devices: dict[str, MeshDevice] = {}

    def received_announce(
        self,
        destination_hash: bytes,
        announced_identity: Any,  # RNS.Identity
        app_data: bytes | None,
        announce_packet_hash: bytes | None = None,
        is_path_response: bool | None = None,
    ) -> None:
        """Handle received announce from RNS.Transport.

        IMPORTANT HASH DISTINCTION:
        - destination_hash: Hash of the destination (identity + app + aspects).
                           Used for routing. This is what we display to users.
        - announced_identity.hash: Hash of just the public key (identity hash).
                                   Used for RNS.Identity.recall() when sending.

        Args:
            destination_hash: Hash of the announcing destination.
            announced_identity: RNS.Identity of the announcer.
            app_data: Optional application data from the announce.
            announce_packet_hash: Hash of the announce packet (unused).
            is_path_response: Whether this is a path response (unused).
        """
        dest_hash_hex = destination_hash.hex()

        # Extract identity hash from the announced identity
        # This is CRITICAL - we need this to send messages later
        identity_hash_hex = announced_identity.hash.hex() if announced_identity else dest_hash_hex

        # Check if we've seen this device before
        existing = self.discovered_devices.get(dest_hash_hex)
        announce_count = existing.announce_count + 1 if existing else 1

        # Create/update MeshDevice with both hashes
        device = create_mesh_device(
            destination_hash=dest_hash_hex,
            identity_hash=identity_hash_hex,
            app_data=app_data,
            announce_count=announce_count,
        )

        self.discovered_devices[dest_hash_hex] = device

        # Persist to store if available
        if self.node_store is not None:
            try:
                self.node_store.save_node(device)
            except Exception as e:
                logger.warning(f"Failed to persist node to store: {e}")

        if self.callback:
            self.callback(device)


# Global announce handler
_announce_handler: StyreneAnnounceHandler | None = None


def start_discovery(
    callback: Callable[[MeshDevice], None] | None = None,
    node_store: Any | None = None,
) -> None:
    """Start device discovery via RNS announces.

    Registers an announce handler with RNS.Transport to listen for all
    device announces on the network.

    Args:
        callback: Optional callback to invoke when devices are discovered/updated.
                  Receives a MeshDevice object.
        node_store: Optional node store for persistence (dependency injection).
    """
    global _announce_handler
    if _announce_handler:
        return

    _announce_handler = StyreneAnnounceHandler(callback, node_store)
    try:
        if not RNS:
            logger.error("RNS library not available. Install with: pip install rns")
            _announce_handler = None
            return

        RNS.Transport.register_announce_handler(_announce_handler)
        logger.info("Started device discovery (listening for all announces)")
    except Exception as e:
        logger.error(f"Failed to register announce handler: {e}")
        _announce_handler = None


def stop_discovery() -> None:
    """Stop device discovery and deregister announce handler."""
    global _announce_handler
    if _announce_handler:
        try:
            if not RNS:
                logger.error("RNS library not available")
                _announce_handler = None
                return

            RNS.Transport.deregister_announce_handler(_announce_handler)
            logger.info("Stopped device discovery")
        except Exception as e:
            logger.error(f"Failed to deregister announce handler: {e}")
        finally:
            _announce_handler = None


def discover_devices() -> list[MeshDevice]:
    """Discover devices on the Reticulum mesh.

    Returns all discovered devices from the announce handler.

    Returns:
        List of MeshDevice objects for all discovered devices.
    """
    if not _announce_handler:
        return []
    return list(_announce_handler.discovered_devices.values())


def get_styrene_devices() -> list[MeshDevice]:
    """Get list of discovered Styrene nodes.

    Returns only devices identified as Styrene nodes via announce data.

    Returns:
        List of MeshDevice objects for Styrene nodes only.
    """
    if not _announce_handler:
        return []
    return [
        device for device in _announce_handler.discovered_devices.values() if device.is_styrene_node
    ]


def get_rnodes() -> list[MeshDevice]:
    """Get list of discovered RNode devices.

    Returns only devices identified as RNodes via announce data.

    Returns:
        List of MeshDevice objects for RNodes only.
    """
    if not _announce_handler:
        return []
    return [device for device in _announce_handler.discovered_devices.values() if device.is_rnode]


def generate_rns_config(config: CoreConfig, client_only: bool = False) -> str:
    """Generate Reticulum configuration from CoreConfig.

    Creates an INI-formatted config string for RNS based on deployment mode
    and interface settings.

    Args:
        config: CoreConfig object with deployment mode and interface settings.
        client_only: If True, don't include server interfaces (for CLI tools).

    Returns:
        INI-formatted config string for RNS.
    """
    lines = []

    # [reticulum] section
    lines.append("[reticulum]")
    enable_transport = config.reticulum.resolve_transport_enabled()
    lines.append(f"enable_transport = {str(enable_transport).lower()}")

    # In standalone mode, use our own transport instead of shared instance
    share_instance = config.reticulum.mode != DeploymentMode.STANDALONE
    lines.append(f"share_instance = {str(share_instance).lower()}")
    lines.append("")

    # [interfaces] section
    lines.append("[interfaces]")
    lines.append("")

    # TCPServerInterface (hub mode) - highest priority
    # Skip server interface in client_only mode (for CLI tools)
    if config.reticulum.interfaces.server.enabled and not client_only:
        lines.append("[[TCP Server Interface]]")
        lines.append("type = TCPServerInterface")
        lines.append("enabled = true")
        lines.append(f"listen_ip = {config.reticulum.interfaces.server.listen_ip}")
        lines.append(f"listen_port = {config.reticulum.interfaces.server.port}")
        lines.append("")

    # TCPClientInterface (peers) - hub/fleet connections prioritized
    for i, peer in enumerate(config.reticulum.interfaces.peers):
        interface_name = peer.name or f"Peer {i + 1}"
        lines.append(f"[[{interface_name}]]")
        lines.append("type = TCPClientInterface")
        lines.append("enabled = true")
        lines.append(f"target_host = {peer.host}")
        lines.append(f"target_port = {peer.port}")
        lines.append("")

    # AutoInterface (local discovery) - deferred due to platform compatibility issues
    # IMPORTANT: AutoInterface is disabled by default for the following reasons:
    #   - Linux: Can error on certain network adapters (wlp3s0, etc.) blocking subsequent interfaces
    #   - macOS: Causes "No buffer space available" errors on VPN/tunnel interfaces (utun0-5)
    #   - General: Errors in AutoInterface can prevent RNS config from loading TCPClientInterface
    #
    # Enable AutoInterface only if:
    #   1. You need local multicast discovery
    #   2. Your network adapters are stable (no VPN tunnels or problematic WiFi chipsets)
    #   3. You configure ignored_interfaces to exclude problematic adapters
    #
    # Recommended: Use TCPClientInterface to connect to hub for fleet-wide discovery
    lines.append("# Local multicast discovery (disabled by default - see comments above)")
    lines.append("[[AutoInterface]]")
    lines.append("type = AutoInterface")
    lines.append(f"enabled = {str(config.reticulum.interfaces.auto).lower()}")
    if config.reticulum.interfaces.auto:
        lines.append("# To exclude problematic interfaces, add:")
        lines.append("# ignored_interfaces = utun0,utun1,utun2,utun3,utun4,utun5")
    lines.append("")

    return "\n".join(lines)
