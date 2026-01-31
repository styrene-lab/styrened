"""Styrened - Styrene headless daemon.

Lightweight daemon for running Styrene services without the TUI,
optimized for edge deployments and NixOS.

Usage:
    styrened                    # Run daemon with default config

The daemon includes:
    - RPC server for incoming fleet management requests
    - Auto-reply handler for LXMF messages from NomadNet/MeshChat users
    - Device discovery and mesh status logging
    - Optional HTTP API

RPC commands:
    - status_request: Returns system status (uptime, IP, disk, services)
    - exec: Executes whitelisted commands
    - reboot: Schedules system reboot
    - update_config: Updates local configuration

Dependencies:
    - styrene-core only (no textual, lightweight)
"""

import asyncio
import logging
import signal
import sys
import time
from typing import TYPE_CHECKING, Any

import RNS  # type: ignore

if TYPE_CHECKING:
    from styrened.models.mesh_device import MeshDevice

from styrened.models.config import CoreConfig
from styrened.services.auto_reply import AutoReplyHandler
from styrened.services.config import get_default_core_config, load_core_config
from styrened.services.lifecycle import CoreLifecycle
from styrened.services.reticulum import discover_devices, start_discovery

logger = logging.getLogger(__name__)


class StyreneDaemon:
    """Headless Styrene service daemon.

    Runs Styrene services without TUI for server/edge deployments.
    Includes RPC server for handling incoming fleet management requests.
    """

    def __init__(self, config: CoreConfig):
        """Initialize daemon.

        Args:
            config: Core configuration.
        """
        self.config = config
        self.lifecycle = CoreLifecycle(config)
        self._running = False
        self._start_time = time.time()
        self._api_server: Any = None
        self._api_task: asyncio.Task[None] | None = None
        self._rpc_server: Any = None
        self._auto_reply_handler: AutoReplyHandler | None = None
        self._operator_destination: RNS.Destination | None = None

    async def start(self) -> None:
        """Start the daemon services."""
        logger.info("Starting Styrene daemon...")

        # Initialize Styrene services
        if not self.lifecycle.initialize():
            logger.error("Failed to initialize services")
            sys.exit(1)

        # Create and cache the operator destination once
        self._init_operator_destination()

        # Start RPC server for incoming requests
        self._start_rpc_server()

        # Start auto-reply handler for chat messages
        self._start_auto_reply()

        # Start device discovery
        start_discovery(callback=self._on_device_discovered)

        # Start HTTP API if enabled
        if self.config.api.enabled:
            await self._start_api()

        self._running = True
        logger.info("Styrene daemon running")

        # Main loop with periodic announces
        await self._run_loop()

    def _on_device_discovered(self, device: "MeshDevice") -> None:
        """Handle discovered device.

        Args:
            device: Discovered MeshDevice.
        """
        logger.info(
            f"Discovered: {device.name} ({device.device_type.value}) - {device.status.value}"
        )

    def _init_operator_destination(self) -> None:
        """Initialize and cache the operator destination.

        Creates the operator destination once during startup using the
        RNS service's destination caching. This avoids "already registered"
        errors when re-announcing in the main loop.
        """
        try:
            from styrened.services.reticulum import get_operator_identity_object
            from styrened.services.rns_service import get_rns_service

            identity = get_operator_identity_object()
            if identity:
                rns_service = get_rns_service()
                self._operator_destination = rns_service.get_or_create_destination(
                    identity, app_name="styrene_node", aspect="operator"
                )
                if self._operator_destination:
                    logger.info("Operator destination initialized and cached")
                else:
                    logger.warning("Failed to create operator destination")
            else:
                logger.warning("No operator identity available")
        except Exception as e:
            logger.error(f"Failed to initialize operator destination: {e}")

    def _start_rpc_server(self) -> None:
        """Start the RPC server for handling incoming requests."""
        # Check if RPC is enabled in config
        if not self.config.rpc.enabled:
            logger.info("RPC server disabled in configuration")
            return

        try:
            from styrened.rpc import RPCServer
            from styrened.services.lxmf_service import get_lxmf_service

            lxmf_service = get_lxmf_service()
            if not lxmf_service.is_initialized:
                logger.warning("LXMF not initialized, RPC server not started")
                return

            self._rpc_server = RPCServer(lxmf_service)

            # Configure based on deployment mode
            if self.config.rpc.relay_mode:
                logger.info("RPC server starting in relay mode (no command execution)")
                # In relay mode, we don't register command handlers
                # The server will still receive and could forward messages
            else:
                # Normal mode - register command handlers if allowed
                if self.config.rpc.allow_command_execution:
                    logger.info("RPC server starting with command execution enabled")
                else:
                    logger.warning("RPC server starting but command execution is disabled")

            self._rpc_server.start()
            mode_str = "relay mode" if self.config.rpc.relay_mode else "execute mode"
            logger.info(f"RPC server started - {mode_str}")

        except ImportError as e:
            logger.warning(f"RPC server not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start RPC server: {e}")

    def _start_auto_reply(self) -> None:
        """Start the auto-reply handler for LXMF chat messages.

        This handler responds to messages from NomadNet, MeshChat, or other
        LXMF clients with a configurable auto-reply when no operator is available.
        """
        if not self.config.chat.enabled:
            logger.info("Chat disabled in configuration")
            return

        if not self.config.chat.auto_reply_enabled:
            logger.info("Auto-reply disabled in configuration")
            return

        try:
            from styrened.services.auto_reply import AutoReplyHandler
            from styrened.services.lxmf_service import get_lxmf_service
            from styrened.services.reticulum import get_operator_identity_object

            lxmf_service = get_lxmf_service()
            if not lxmf_service.is_initialized or not lxmf_service.router:
                logger.warning("LXMF not initialized, auto-reply not started")
                return

            identity = get_operator_identity_object()
            if not identity:
                logger.warning("No operator identity, auto-reply not started")
                return

            self._auto_reply_handler = AutoReplyHandler(
                config=self.config.chat,
                identity=identity,
                router=lxmf_service.router,
                start_time=self._start_time,
            )

            # Register the handler with LXMF router
            lxmf_service.router.register_delivery_callback(self._auto_reply_handler.handle_message)

            logger.info(
                f"Auto-reply handler started (cooldown: {self.config.chat.auto_reply_cooldown}s)"
            )

        except ImportError as e:
            logger.warning(f"Auto-reply not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start auto-reply: {e}")

    async def _start_api(self) -> None:
        """Start HTTP API server."""
        try:
            # Import here to avoid dependency when API not enabled
            from styrene.api import create_app

            fastapi_app = create_app(self.config)

            # Import uvicorn for serving
            import uvicorn  # type: ignore[import-not-found]

            # Run in background
            uvicorn_config = uvicorn.Config(
                fastapi_app,
                host=self.config.api.host,
                port=self.config.api.port,
                log_level="info",
            )
            self._api_server = uvicorn.Server(uvicorn_config)

            logger.info(f"Starting API on {self.config.api.host}:{self.config.api.port}")

            # Run server in background task
            self._api_task = asyncio.create_task(self._api_server.serve())

        except ImportError:
            logger.error("API server requires: pip install uvicorn fastapi")
        except Exception as e:
            logger.error(f"Failed to start API: {e}")

    async def _run_loop(self) -> None:
        """Main daemon loop with periodic announces."""
        announce_interval = self.config.reticulum.announce_interval
        logger.info(f"Starting run loop with announce_interval={announce_interval}s")

        while self._running:
            logger.debug(f"Run loop sleeping for {announce_interval}s...")
            await asyncio.sleep(announce_interval)
            logger.info(f"Run loop woke up, _running={self._running}")

            # Re-announce presence using cached destination
            try:
                # Use cached destination if available, otherwise try to recover
                destination = self._operator_destination
                if destination is None:
                    # Recovery: try to get/create destination if not cached
                    logger.debug("No cached destination, attempting recovery")
                    self._init_operator_destination()
                    destination = self._operator_destination

                if destination:
                    # Re-announce with LXMF destination
                    import socket

                    hostname = socket.gethostname()
                    version = "0.1.0"
                    capabilities = []
                    if self.config.reticulum.mode.value == "hub":
                        capabilities.append("hub")
                    if self.config.api.enabled:
                        capabilities.append("api")

                    caps_str = ",".join(capabilities) if capabilities else "node"

                    # Include LXMF delivery destination in announce
                    lxmf_dest = ""
                    try:
                        from styrened.services.lxmf_service import get_lxmf_service

                        lxmf_service = get_lxmf_service()
                        if lxmf_service.is_initialized and lxmf_service.delivery_destination:
                            lxmf_dest = lxmf_service.delivery_destination.hash.hex()
                            logger.info(f"Including LXMF dest in re-announce: {lxmf_dest[:16]}...")
                        else:
                            logger.warning(
                                "LXMF not initialized or no delivery destination for re-announce"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Could not get LXMF destination for re-announce: {e}", exc_info=True
                        )

                    app_data = f"styrene:{hostname}:{version}:{caps_str}:{lxmf_dest}".encode()
                    destination.announce(app_data=app_data)
                    logger.info(f"Re-announced as Styrene node: {hostname}")

                    # Also re-announce LXMF delivery destination so clients can send to us
                    try:
                        from styrened.services.lxmf_service import get_lxmf_service

                        lxmf_service = get_lxmf_service()
                        if lxmf_service.is_initialized and lxmf_service.router:
                            lxmf_service.router.announce(lxmf_service.delivery_destination.hash)
                            logger.info(f"Re-announced LXMF delivery destination")
                    except Exception as e:
                        logger.warning(f"LXMF re-announce failed: {e}")

            except Exception as e:
                logger.warning(f"Announce failed: {e}")

            # Log discovered device count
            devices = discover_devices()
            if devices:
                logger.info(
                    f"Mesh status: {len(devices)} devices discovered "
                    f"({len([d for d in devices if d.is_styrene_node])} Styrene nodes)"
                )

            # Cleanup stale auto-reply cooldowns to prevent memory growth
            if self._auto_reply_handler:
                self._auto_reply_handler.cleanup_stale_cooldowns()

    async def stop(self) -> None:
        """Stop the daemon services."""
        logger.info("Stopping Styrene daemon...")
        self._running = False

        # Stop RPC server
        if self._rpc_server:
            self._rpc_server.stop()

        # Stop API server
        if self._api_server:
            self._api_server.should_exit = True
            await asyncio.sleep(1)

        # Shutdown services
        self.lifecycle.shutdown()
        logger.info("Daemon stopped")


async def run_daemon(config: CoreConfig) -> None:
    """Run the Styrene daemon.

    Args:
        config: Core configuration.
    """
    daemon = StyreneDaemon(config)
    _shutdown_task: asyncio.Task[None] | None = None

    # Setup signal handlers
    def signal_handler(signum: int, frame: Any) -> None:
        nonlocal _shutdown_task
        logger.info(f"Received signal {signum}, shutting down...")
        _shutdown_task = asyncio.create_task(daemon.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await daemon.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        await daemon.stop()
    except Exception as e:
        logger.error(f"Daemon error: {e}")
        await daemon.stop()
        sys.exit(1)


def main() -> None:
    """Entry point for headless daemon."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Load config (try core config, fallback to default)
    try:
        config = load_core_config()
    except FileNotFoundError:
        logger.info("No config file found, using defaults")
        config = get_default_core_config()
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)

    # Run daemon
    asyncio.run(run_daemon(config))


if __name__ == "__main__":
    main()
