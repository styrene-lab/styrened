"""Reticulum TUI service - wrappers for core functionality.

This module provides TUI-specific wrappers around styrene-core's Reticulum
functionality. Most core functions are re-exported from styrened.

TUI-specific additions:
- get_reticulum_status() - integrates with TUI's RNS service
- generate_rns_config() - wrapper accepting StyreneConfig
- initialize_reticulum_with_config() - wrapper accepting StyreneConfig
- First-run wizard helpers for config generation
"""

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Local MeshDevice type (during migration phase, both exist)
from styrened.models.mesh_device import MeshDevice

# Re-export core functions (use 'as' pattern for mypy export visibility)
from styrened.services.reticulum import (
    OPERATOR_IDENTITY_PATH as OPERATOR_IDENTITY_PATH,
)
from styrened.services.reticulum import (
    StyreneAnnounceHandler as StyreneAnnounceHandler,
)
from styrened.services.reticulum import (
    discover_devices as discover_devices_core,
)
from styrened.services.reticulum import (
    ensure_operator_identity as ensure_operator_identity,
)
from styrened.services.reticulum import (
    find_reticulum_config as find_reticulum_config,
)
from styrened.services.reticulum import (
    generate_rns_config as generate_rns_config_from_core,
)
from styrened.services.reticulum import (
    get_operator_identity as get_operator_identity,
)
from styrened.services.reticulum import (
    get_operator_identity_object as get_operator_identity_object,
)
from styrened.services.reticulum import (
    get_reticulum_config_paths as get_reticulum_config_paths,
)
from styrened.services.reticulum import (
    get_reticulum_config_state,
)
from styrened.services.reticulum import (
    get_rnodes as get_rnodes_core,
)
from styrened.services.reticulum import (
    get_styrene_devices as get_styrene_devices_core,
)
from styrened.services.reticulum import (
    is_reticulum_configured as is_reticulum_configured,
)
from styrened.services.reticulum import (
    start_discovery as start_discovery_core,
)
from styrened.services.reticulum import (
    stop_discovery as stop_discovery,
)

# Backward compatibility alias (was get_reticulum_config, now get_reticulum_config_state)
get_reticulum_config = get_reticulum_config_state


# Type-compatible wrappers for discovery functions (migration phase)
# During Phases 2-8, TUI uses styrene.models.mesh_device.MeshDevice
# Core uses styrened.models.mesh_device.MeshDevice
# These wrappers bridge the type gap until Phase 9 updates all imports


def discover_devices() -> list[MeshDevice]:
    """Discover devices on the Reticulum mesh (TUI wrapper).

    Returns all discovered devices with TUI's MeshDevice type.

    Returns:
        List of MeshDevice objects for all discovered devices.
    """
    # Core returns styrened.models.mesh_device.MeshDevice
    # Cast to TUI's type (they're identical during migration)
    return discover_devices_core()


def get_styrene_devices() -> list[MeshDevice]:
    """Get list of discovered Styrene nodes (TUI wrapper).

    Returns only devices identified as Styrene nodes via announce data.

    Returns:
        List of MeshDevice objects for Styrene nodes only.
    """
    return get_styrene_devices_core()


def get_rnodes() -> list[MeshDevice]:
    """Get list of discovered RNode devices (TUI wrapper).

    Returns only devices identified as RNodes via announce data.

    Returns:
        List of MeshDevice objects for RNodes only.
    """
    return get_rnodes_core()


def start_discovery(callback: Callable[[MeshDevice], None] | None = None) -> None:
    """Start device discovery via RNS announces (TUI wrapper).

    Registers an announce handler with RNS.Transport to listen for all
    device announces on the network.

    Args:
        callback: Optional callback to invoke when devices are discovered/updated.
                  Receives a MeshDevice object (TUI type).
    """
    # Inject node_store from core
    try:
        from styrened.services.node_store import get_node_store
        node_store = get_node_store()
    except ImportError:
        node_store = None

    # Callback type cast (TUI MeshDevice is identical to core MeshDevice during migration)
    start_discovery_core(
        callback=callback,
        node_store=node_store,
    )


# Conditional RNS import
if TYPE_CHECKING:
    import RNS

    from styrened.tui.models.config import StyreneConfig
else:
    # Try to import RNS at runtime, but don't fail if not available
    try:
        import RNS  # type: ignore[import-untyped]
    except ImportError:
        RNS = None  # type: ignore[assignment]

# Setup logger
logger = logging.getLogger(__name__)


# Import real RNS service
try:
    from styrened.services.rns_service import get_rns_service as _get_rns_service

    def get_rns_service() -> Any:
        """Get RNS service instance.

        Returns:
            RNSService instance with is_initialized() and is_transport_enabled() methods.
        """
        return _get_rns_service()
except ImportError:
    # Fallback stub if rns_service not available
    def get_rns_service() -> Any:
        """Get RNS service instance (stub fallback).

        Returns:
            Stub service with is_initialized() and is_transport_enabled() methods.
        """

        class StubRNSService:
            def is_initialized(self) -> bool:
                return False

            def is_transport_enabled(self) -> bool:
                return False

        return StubRNSService()


def get_reticulum_status() -> dict[str, bool | int | str | None]:
    """Get Reticulum mesh status (TUI-specific).

    Returns a dictionary containing:
    - running: Whether RNS service is initialized
    - interfaces: Number of configured interfaces
    - identity: Operator identity hex string (or None)
    - transport_enabled: Whether RNS transport is enabled

    Returns:
        Dictionary with Reticulum status information.
    """
    from styrened.models.reticulum import ReticulumNotConfiguredError

    status: dict[str, bool | int | str | None] = {
        "running": False,
        "interfaces": 0,
        "identity": None,
        "transport_enabled": False,
    }

    # Check RNS service status
    rns_service = get_rns_service()
    status["running"] = rns_service.is_initialized
    status["identity"] = get_operator_identity()

    if rns_service.is_initialized:
        status["transport_enabled"] = rns_service.is_transport_enabled()

    # Try to get interface count from Reticulum config
    try:
        config = get_reticulum_config_state()
        status["interfaces"] = config.enabled_interface_count
    except ReticulumNotConfiguredError:
        pass

    return status


def generate_rns_config(config: "StyreneConfig") -> str:
    """Generate Reticulum configuration from StyreneConfig (TUI wrapper).

    Converts StyreneConfig to CoreConfig and delegates to core implementation.

    Args:
        config: StyreneConfig object with deployment mode and interface settings.

    Returns:
        INI-formatted config string for RNS.
    """
    # Convert StyreneConfig → CoreConfig (using backward compatibility property)
    return generate_rns_config_from_core(config.core)


def initialize_reticulum_with_config(config: "StyreneConfig") -> bool:
    """Initialize RNS with configuration from StyreneConfig (TUI wrapper).

    Prefers existing RNS config if available, otherwise creates temporary
    config based on deployment mode and interface settings.

    Args:
        config: StyreneConfig object with deployment mode and interface settings.

    Returns:
        True if initialization succeeded, False otherwise.
    """
    if not RNS:
        logger.error("RNS library not available. Install with: pip install rns")
        return False

    try:
        # Check if RNS config exists at standard locations
        rns_config_path = find_reticulum_config()

        if rns_config_path:
            # Use existing RNS config
            logger.info(f"Using existing Reticulum config at {rns_config_path}")
            logger.info(f"Initializing RNS in {config.reticulum.mode.value} mode")

            rns_service = get_rns_service()
            result: bool = rns_service.initialize()
            return result

        else:
            # No existing config - use temporary config based on Styrene settings
            # Generate RNS config using core function via wrapper
            config_content = generate_rns_config(config)

            # Create temporary config directory
            with tempfile.TemporaryDirectory() as tmpdir:
                config_dir = Path(tmpdir)
                config_file = config_dir / "config"
                config_file.write_text(config_content)

                logger.info(
                    f"Initializing RNS in {config.reticulum.mode.value} mode (temporary config)"
                )
                logger.debug(f"RNS config:\n{config_content}")

                # Initialize RNS with temporary config
                rns_service = get_rns_service()
                result2: bool = rns_service.initialize(config_override=config_dir)
                return result2

    except Exception as e:
        logger.error(f"Failed to initialize Reticulum: {e}")
        return False


def get_device_identity(device_name: str) -> str | None:
    """Get Reticulum identity for a named device.

    Phase 2A: Returns mock data.
    Phase 2B+: Will query device registry or announces.

    Args:
        device_name: Device hostname to look up.

    Returns:
        Hex-encoded Reticulum identity, or None if not found.
    """
    # Mock identity mapping for Phase 2A
    mock_identities = {
        "rpi-01": "a3f5d8e9b1c2",
        "rpi-02": "b4e6c7d8a2f3",
        "t100ta-01": "c5d7a8e9f3b4",
    }

    return mock_identities.get(device_name)


# First-Run Configuration Generation


def create_default_reticulum_config(interface_type: str = "auto") -> Path:
    """Create a default Reticulum configuration for first-run setup.

    This creates a minimal working Reticulum configuration in the
    standard location (~/.reticulum/config) with sensible defaults.

    Args:
        interface_type: Type of interface to configure.
            - "auto": AutoInterface (UDP multicast, local network)
            - "tcp": TCP Client Interface (connect to specific host)
            - "tcp-server": TCP Server Interface (listen for connections)

    Returns:
        Path to the created config file.

    Raises:
        OSError: If config directory creation or file writing fails.
    """
    config_dir = Path.home() / ".reticulum"
    config_file = config_dir / "config"
    storage_dir = config_dir / "storage"

    # Create directories
    config_dir.mkdir(parents=True, exist_ok=True)
    storage_dir.mkdir(parents=True, exist_ok=True)

    # Generate config content
    config_content = _generate_config_content(interface_type)

    # Write config file
    config_file.write_text(config_content)

    logger.info(f"Created Reticulum config at {config_file}")

    return config_file


def _generate_config_content(interface_type: str) -> str:
    """Generate Reticulum config file content.

    Args:
        interface_type: Type of interface ("auto", "tcp", or "tcp-server").

    Returns:
        Config file content as string.
    """
    # Base config (common to all setups)
    config = """# Reticulum Configuration
# Generated by Styrene TUI

[reticulum]
  # Run as a client node (not a transport/routing node)
  enable_transport = False

  # Use shared RNS instance for multiple programs
  share_instance = Yes
  instance_name = default

  # Log level (4 = info, 5 = verbose, 6 = debug)
  loglevel = 4

[logging]
  loglevel = 4

[interfaces]
"""

    # Add interface configuration based on selection
    if interface_type == "auto":
        config += """
  # AutoInterface - Local network discovery via UDP multicast
  # Automatically discovers other Reticulum nodes on the same LAN
  [[Default Interface]]
    type = AutoInterface
    enabled = Yes
"""

    elif interface_type == "tcp":
        config += """
  # TCP Client Interface - Connect to a specific Reticulum node
  # Replace the target_host and target_port with your gateway details
  [[TCP Interface]]
    type = TCPClientInterface
    enabled = Yes
    target_host = 127.0.0.1
    target_port = 4242
"""

    elif interface_type == "tcp-server":
        config += """
  # TCP Server Interface - Listen for incoming connections
  # Other nodes can connect to this system as a gateway
  [[TCP Server Interface]]
    type = TCPServerInterface
    enabled = Yes
    listen_ip = 0.0.0.0
    listen_port = 4242
"""

    else:
        # Fallback to AutoInterface
        config += """
  [[Default Interface]]
    type = AutoInterface
    enabled = Yes
"""

    return config
