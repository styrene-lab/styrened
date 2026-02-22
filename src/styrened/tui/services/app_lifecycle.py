"""Application lifecycle management (TUI wrapper).

This module provides TUI-specific lifecycle management that wraps the core
lifecycle with additional features like hub connection and Styrene node
announcements.

Supports three modes:
    ipc:    Daemon subprocess managed via DaemonManager + IPCBridge.
    legacy: In-process CoreLifecycle (existing behavior, no daemon).
    auto:   Try IPC first, fall back to legacy if daemon unavailable.

Usage:
    from styrened.tui.services.app_lifecycle import StyreneLifecycle
    from styrened.tui.services.config import load_config

    # Initialize Styrene services
    config = load_config()
    lifecycle = StyreneLifecycle(config)

    # Start services (sync for legacy, async for IPC)
    lifecycle.initialize()

    # Or async initialization (required for IPC mode)
    await lifecycle.initialize_async()

    # Use services...
    from styrened.services.rns_service import get_rns_service
    rns = get_rns_service()
    print(f"RNS initialized: {rns.is_initialized}")

    # Cleanup
    lifecycle.shutdown()
    # Or: await lifecycle.shutdown_async()
"""

import logging
from enum import Enum
from importlib.metadata import version as get_version
from typing import Any

from styrened.models.rns_error import RNSErrorState
from styrened.services.hub_connection import STYRENE_HUB_ADDRESS, get_hub_connection
from styrened.services.lifecycle import CoreLifecycle
from styrened.services.rns_service import get_rns_service
from styrened.tui.models.config import DeploymentMode, StyreneConfig
from styrened.tui.services.config import get_default_config
from styrened.tui.services.reticulum import get_operator_identity_object

logger = logging.getLogger(__name__)


class LifecycleMode(Enum):
    """How the TUI initializes services."""

    IPC = "ipc"
    LEGACY = "legacy"
    AUTO = "auto"


class StyreneLifecycle:
    """Manages Styrene TUI application lifecycle.

    This class wraps CoreLifecycle and adds TUI-specific features:
    - Hub connection
    - Styrene node announcements with version info
    - TUI-specific configuration handling
    - IPC mode for daemon-backed operation

    Core functionality (RNS/LXMF initialization, shutdown) is delegated
    to CoreLifecycle from styrene-core in legacy mode, or to the daemon
    via IPC in IPC mode.
    """

    def __init__(
        self,
        config: StyreneConfig | None = None,
        mode: LifecycleMode | None = None,
    ) -> None:
        """Initialize lifecycle manager.

        Args:
            config: Application configuration. If None, uses default config.
            mode: Lifecycle mode override. If None, determined from config.
        """
        self.config = config or get_default_config()

        # Determine mode from explicit parameter, config, or default
        if mode is not None:
            self._mode = mode
        elif self.config.tui.use_ipc is True:
            self._mode = LifecycleMode.IPC
        elif self.config.tui.use_ipc is False:
            self._mode = LifecycleMode.LEGACY
        else:
            self._mode = LifecycleMode.AUTO

        self._core = CoreLifecycle(self.config.core)
        self._initialized = False
        self._active_mode: LifecycleMode | None = None

        # IPC components (created lazily in async init)
        self._daemon_manager = None
        self._ipc_bridge = None

    @property
    def mode(self) -> LifecycleMode:
        """Configured lifecycle mode."""
        return self._mode

    @property
    def active_mode(self) -> LifecycleMode | None:
        """Mode that was actually used for initialization.

        None if not yet initialized. In AUTO mode, this reveals
        whether IPC or legacy was selected.
        """
        return self._active_mode

    @property
    def rns_error_state(self) -> RNSErrorState:
        """Get the RNS initialization error state.

        Returns:
            RNSErrorState with category and recovery guidance.
            If initialized successfully, returns NONE category.
        """
        return self._core.rns_error_state

    @property
    def is_initialized(self) -> bool:
        """Check if services are initialized.

        Returns:
            True if initialized, False otherwise.
        """
        return self._initialized

    @property
    def ipc_bridge(self):
        """Access the IPC bridge (only available in IPC mode)."""
        return self._ipc_bridge

    @property
    def daemon_manager(self):
        """Access the daemon manager (only available in IPC mode)."""
        return self._daemon_manager

    def initialize(self) -> bool:
        """Initialize all Styrene services (synchronous, legacy mode only).

        For IPC mode, use initialize_async() instead.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            logger.warning("Already initialized")
            return True

        if self._mode == LifecycleMode.IPC:
            logger.warning(
                "IPC mode requires async initialization — "
                "call initialize_async() from on_mount()"
            )
            return False

        # Legacy or AUTO mode — try legacy path
        return self._initialize_legacy()

    async def initialize_async(self) -> bool:
        """Initialize services asynchronously.

        Supports all modes: IPC, legacy, and auto.
        In auto mode, tries IPC first and falls back to legacy.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            logger.warning("Already initialized")
            return True

        if self._mode == LifecycleMode.IPC:
            return await self._initialize_ipc()

        if self._mode == LifecycleMode.AUTO:
            # Try IPC first
            if await self._initialize_ipc():
                return True
            logger.info("IPC initialization failed, falling back to legacy mode")

        # Legacy fallback
        return self._initialize_legacy()

    async def _initialize_ipc(self) -> bool:
        """Initialize via IPC — spawn daemon, connect bridge."""
        try:
            from styrened.tui.services.daemon_manager import DaemonManager, DaemonMode
            from styrened.tui.services.ipc_bridge import IPCBridge

            self._daemon_manager = DaemonManager(mode=DaemonMode.MANAGED)
            if not await self._daemon_manager.ensure_running():
                logger.warning("Failed to start daemon")
                self._daemon_manager = None
                return False

            self._ipc_bridge = IPCBridge(
                socket_path=self._daemon_manager.socket_path,
            )
            if not await self._ipc_bridge.connect():
                logger.warning("Failed to connect IPC bridge")
                await self._daemon_manager.shutdown()
                self._daemon_manager = None
                self._ipc_bridge = None
                return False

            self._initialized = True
            self._active_mode = LifecycleMode.IPC
            logger.info("Styrene TUI services initialized (IPC mode)")
            return True

        except Exception as e:
            logger.error(f"IPC initialization failed: {e}")
            # Clean up partial state
            if self._ipc_bridge is not None:
                await self._ipc_bridge.disconnect()
                self._ipc_bridge = None
            if self._daemon_manager is not None:
                await self._daemon_manager.shutdown()
                self._daemon_manager = None
            return False

    def _initialize_legacy(self) -> bool:
        """Initialize via legacy in-process CoreLifecycle."""
        try:
            # Initialize core services (RNS, LXMF)
            if not self._core.initialize():
                logger.warning("Core initialization failed - running in offline mode")
                # Don't fail entirely - allow offline mode
                self._initialized = True
                self._active_mode = LifecycleMode.LEGACY
                return True

            # Announce as Styrene node (TUI-specific)
            self._announce_styrene_node()

            # Connect to hub if configured (but not if we ARE the hub)
            if self.config.reticulum.hub_enabled:
                if self.config.reticulum.mode == DeploymentMode.HUB:
                    logger.info("Running in hub mode - skipping hub connection (we are the hub)")
                else:
                    self._connect_to_hub()

            self._initialized = True
            self._active_mode = LifecycleMode.LEGACY
            logger.info("Styrene TUI services initialized (legacy mode)")
            return True

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            return False

    def _announce_styrene_node(self) -> None:
        """Announce this node as a Styrene node (TUI-specific).

        Sends announce with Styrene node format including version and capabilities.
        """
        try:
            import socket

            # Get operator destination
            identity = get_operator_identity_object()
            if not identity:
                logger.warning("No operator identity for announce")
                return

            rns_service = get_rns_service()
            destination = rns_service.get_or_create_destination(
                identity, app_name="styrene_node", aspect="operator"
            )

            if not destination:
                logger.warning("Failed to get destination for announce")
                return

            # Build announce data: styrene:<hostname>:<version>:<capabilities>:<lxmf_dest>
            hostname = socket.gethostname()
            try:
                version = get_version("styrened")
            except Exception:
                version = "unknown"

            # Capabilities
            capabilities = []
            if self.config.rpc.enabled:
                capabilities.append("rpc")
            if self.config.discovery.enabled:
                capabilities.append("discovery")
            capabilities_str = ",".join(capabilities) if capabilities else "none"

            # LXMF destination (if available)
            lxmf_dest = "none"
            try:
                from styrened.services.lxmf_service import get_lxmf_service

                lxmf_service = get_lxmf_service()
                if lxmf_service.is_initialized and lxmf_service.delivery_destination:
                    lxmf_dest = lxmf_service.delivery_destination.hash.hex()
            except Exception:
                pass

            # Short name and system fingerprint
            from styrened.services.system_info import get_system_fingerprint

            short_name = hostname[:2].upper() if hostname else "SN"
            fingerprint = get_system_fingerprint()

            # Format: styrene:<hostname>:<version>:<caps>:<lxmf_dest>:<short_name>:<fingerprint>
            announce_data = f"styrene:{hostname}:{version}:{capabilities_str}:{lxmf_dest}:{short_name}:{fingerprint}"

            # Send announce
            destination.announce(announce_data.encode("utf-8"))
            logger.info(f"Announced as Styrene node: {hostname} (v{version})")

        except Exception as e:
            logger.warning(f"Failed to announce Styrene node: {e}")

    def _connect_to_hub(self) -> bool:
        """Connect to Styrene hub for fleet coordination (TUI-specific).

        Returns:
            True if connected successfully, False otherwise.
        """
        try:
            hub_connection = get_hub_connection()

            # Determine hub address
            hub_address = self.config.reticulum.hub_address or STYRENE_HUB_ADDRESS

            if not hub_address:
                logger.warning("Hub enabled but no address configured")
                return False

            logger.info(f"Connecting to hub at {hub_address[:16]}...")

            if hub_connection.connect(hub_address=hub_address):
                logger.info(f"Connected to hub at {hub_address[:16]}...")
                return True
            else:
                logger.warning("Hub connection failed")
                return False

        except Exception as e:
            logger.error(f"Hub connection error: {e}")
            return False

    def shutdown(self) -> None:
        """Shutdown all services and clean up resources (synchronous).

        For IPC mode, prefer shutdown_async().
        """
        if not self._initialized:
            logger.debug("Not initialized, nothing to shutdown")
            return

        try:
            logger.info("Shutting down Styrene TUI services...")

            if self._active_mode == LifecycleMode.LEGACY:
                # Disconnect from hub (TUI-specific)
                get_hub_connection().disconnect()

                # Shutdown core services (RNS, LXMF, discovery)
                self._core.shutdown()

            # IPC cleanup requires async — log warning if called sync
            if self._active_mode == LifecycleMode.IPC:
                logger.warning(
                    "IPC mode requires async shutdown — "
                    "call shutdown_async() for clean cleanup"
                )

            self._initialized = False
            logger.info("Styrene TUI services shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    async def shutdown_async(self) -> None:
        """Shutdown all services asynchronously."""
        if not self._initialized:
            logger.debug("Not initialized, nothing to shutdown")
            return

        try:
            logger.info("Shutting down Styrene TUI services...")

            if self._active_mode == LifecycleMode.IPC:
                if self._ipc_bridge is not None:
                    await self._ipc_bridge.disconnect()
                    self._ipc_bridge = None
                if self._daemon_manager is not None:
                    await self._daemon_manager.shutdown()
                    self._daemon_manager = None
            else:
                # Legacy path
                get_hub_connection().disconnect()
                self._core.shutdown()

            self._initialized = False
            self._active_mode = None
            logger.info("Styrene TUI services shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")


def get_status() -> dict[str, Any]:
    """Get current status of all Styrene services.

    Returns:
        Dictionary with status information for all services.
    """
    from styrened.tui.services.reticulum import get_reticulum_status

    hub_connection = get_hub_connection()
    reticulum_status = get_reticulum_status()

    return {
        "rns_initialized": reticulum_status.get("running", False),
        "hub_connected": hub_connection.is_connected,
        "hub_address": hub_connection.hub_address,
        "operator_identity": reticulum_status.get("identity"),
        "transport_enabled": reticulum_status.get("transport_enabled"),
        "interface_count": reticulum_status.get("interfaces"),
    }


# Backward compatibility aliases
get_service_status = get_status


def initialize_styrene(config: StyreneConfig | None = None) -> StyreneLifecycle:
    """Initialize Styrene services (backward compatibility wrapper).

    Args:
        config: Application configuration. If None, uses default config.

    Returns:
        Initialized StyreneLifecycle instance.
    """
    lifecycle = StyreneLifecycle(config)
    lifecycle.initialize()
    return lifecycle
