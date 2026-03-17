"""Application lifecycle management (TUI wrapper).

This module provides TUI-specific lifecycle management that wraps the
daemon via IPC.  The TUI is a pure IPC client — all RNS/LXMF initialization
is the daemon's responsibility.

Usage:
    from styrened.tui.services.app_lifecycle import StyreneLifecycle
    from styrened.tui.services.config import load_config

    config = load_config()
    lifecycle = StyreneLifecycle(config)

    # Async initialization (required — IPC mode)
    await lifecycle.initialize_async()

    # Use services via IPC bridge...
    bridge = lifecycle.ipc_bridge

    # Cleanup
    await lifecycle.shutdown_async()
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

from styrened.tui.models.config import StyreneConfig

if TYPE_CHECKING:
    from styrened.ipc.bridge import IPCBridge
from styrened.tui.services.config import get_default_config

logger = logging.getLogger(__name__)


class LifecycleMode(Enum):
    """How the TUI initializes services."""

    IPC = "ipc"


class StyreneLifecycle:
    """Manages Styrene TUI application lifecycle.

    The TUI is an IPC-only daemon client.  All mesh services (RNS, LXMF,
    discovery, hub) run inside the daemon process.  This class manages
    the daemon connection via DaemonManager and IPCBridge.
    """

    def __init__(
        self,
        config: StyreneConfig | None = None,
        mode: LifecycleMode | None = None,
    ) -> None:
        """Initialize lifecycle manager.

        Args:
            config: Application configuration. If None, uses default config.
            mode: Lifecycle mode override (only IPC is supported).
        """
        self.config = config or get_default_config()
        self._mode = LifecycleMode.IPC
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

        None if not yet initialized.
        """
        return self._active_mode

    @property
    def is_initialized(self) -> bool:
        """Check if services are initialized.

        Returns:
            True if initialized, False otherwise.
        """
        return self._initialized

    @property
    def ipc_bridge(self) -> IPCBridge | None:
        """Access the IPC bridge (available after initialization)."""
        return self._ipc_bridge

    @property
    def daemon_manager(self):
        """Access the daemon manager (available after initialization)."""
        return self._daemon_manager

    def initialize(self) -> bool:
        """Initialize services (synchronous).

        IPC mode requires async initialization — call initialize_async()
        from on_mount() instead.

        Returns:
            False — IPC mode requires async initialization.
        """
        if self._initialized:
            logger.warning("Already initialized")
            return True

        logger.warning(
            "IPC mode requires async initialization — "
            "call initialize_async() from on_mount()"
        )
        return False

    async def initialize_async(self) -> bool:
        """Initialize services asynchronously via IPC.

        Spawns the daemon and connects the IPC bridge.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            logger.warning("Already initialized")
            return True

        return await self._initialize_ipc()

    async def _initialize_ipc(self) -> bool:
        """Initialize via IPC — spawn daemon, connect bridge."""
        try:
            from styrened.ipc.bridge import IPCBridge
            from styrened.tui.services.daemon_manager import DaemonManager, DaemonMode

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

    def shutdown(self) -> None:
        """Shutdown all services and clean up resources (synchronous).

        Prefer shutdown_async() for proper IPC cleanup.
        """
        if not self._initialized:
            logger.debug("Not initialized, nothing to shutdown")
            return

        try:
            logger.info("Shutting down Styrene TUI services...")

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

            if self._ipc_bridge is not None:
                await self._ipc_bridge.disconnect()
                self._ipc_bridge = None
            if self._daemon_manager is not None:
                await self._daemon_manager.shutdown()
                self._daemon_manager = None

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
    from styrened.services.hub_connection import get_hub_connection
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

    Note: IPC mode requires async initialization. This function creates
    the lifecycle but cannot fully initialize IPC. Use initialize_async()
    for proper initialization.

    Args:
        config: Application configuration. If None, uses default config.

    Returns:
        StyreneLifecycle instance (not fully initialized in IPC mode).
    """
    lifecycle = StyreneLifecycle(config)
    lifecycle.initialize()
    return lifecycle
