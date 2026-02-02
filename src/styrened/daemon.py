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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import RNS  # type: ignore

if TYPE_CHECKING:
    import LXMF

    from styrened.models.mesh_device import MeshDevice

from styrened.models.config import CoreConfig
from styrened.services.auto_reply import AutoReplyHandler
from styrened.services.config import get_default_core_config, load_core_config
from styrened.services.lifecycle import CoreLifecycle
from styrened.services.node_store import get_node_store
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
        self._rpc_client: Any = None  # Exposed for IPC handlers
        self._control_server: Any = None  # IPC control socket server
        self._lxmf_service: Any = None  # Cached for IPC handlers
        self._conversation_service: Any = None  # Chat backend for IPC handlers
        self._auto_reply_handler: AutoReplyHandler | None = None
        self._operator_destination: RNS.Destination | None = None
        self._node_store: Any = None  # NodeStore for device persistence

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

        # Initialize conversation service for chat backend
        self._init_conversation_service()

        # Start auto-reply handler for chat messages
        self._start_auto_reply()

        # Start device discovery with NodeStore for persistence
        # This ensures discovered devices are persisted and their identity_hash
        # mappings are available for identity resolution when sending messages
        self._node_store = get_node_store()
        start_discovery(callback=self._on_device_discovered, node_store=self._node_store)

        # Start HTTP API if enabled
        if self.config.api.enabled:
            await self._start_api()

        # Start IPC control server if enabled
        if self.config.ipc.enabled:
            await self._start_control_server()

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

        Also registers for reconnection events to refresh the destination
        if LocalInterface drops and reconnects.
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

                    # Register for reconnection events (only once)
                    if not hasattr(self, "_reconnect_registered"):
                        rns_service.register_reconnect_callback(self._handle_rns_reconnection)
                        self._reconnect_registered = True
                        logger.debug("Registered daemon reconnection callback")
                else:
                    logger.warning("Failed to create operator destination")
            else:
                logger.warning("No operator identity available")
        except Exception as e:
            logger.error(f"Failed to initialize operator destination: {e}")

    def _handle_rns_reconnection(self) -> None:
        """Handle RNS interface reconnection by refreshing cached state.

        Called by RNSService when a LocalInterface reconnects after disconnect.
        Clears cached operator destination and re-initializes it.
        """
        logger.info("[RECONNECT] Daemon handling RNS reconnection")

        # Clear stale cached destination
        self._operator_destination = None

        # Re-initialize operator destination (RNS caches will be empty)
        self._init_operator_destination()

        # Trigger a re-announce to make ourselves visible again
        if self._operator_destination:
            try:
                self._announce()
                logger.info("[RECONNECT] Daemon re-announced after reconnection")
            except Exception as e:
                logger.warning(f"[RECONNECT] Failed to re-announce: {e}")

    def _init_conversation_service(self) -> None:
        """Initialize the conversation service for chat backend.

        Creates the ConversationService which manages conversations,
        message history, and delivery tracking for the chat protocol.
        """
        if not self.config.chat.enabled:
            logger.info("Chat disabled, conversation service not started")
            return

        try:
            from styrened.models.messages import init_db
            from styrened.services.conversation_service import ConversationService
            from styrened.services.lxmf_service import get_lxmf_service

            lxmf_service = get_lxmf_service()
            if not lxmf_service.is_initialized:
                logger.warning("LXMF not initialized, conversation service not started")
                return

            # Get local LXMF destination hash for determining message direction
            # This must be the LXMF delivery destination hash, NOT the identity hash,
            # because LXMF messages use destination hashes for source/dest identification
            if not lxmf_service.delivery_destination:
                logger.warning("No LXMF delivery destination, conversation service not started")
                return
            local_lxmf_dest_hash = lxmf_service.delivery_destination.hexhash
            logger.debug(
                f"Using local LXMF dest hash for conversations: {local_lxmf_dest_hash[:16]}..."
            )

            # Initialize database
            db_engine = init_db()

            # Use the shared node_store (initialized in start() before discovery)
            # This ensures devices discovered via announces are available for
            # conversation service display name lookups
            if self._node_store is None:
                self._node_store = get_node_store()

            # Create conversation service
            self._conversation_service = ConversationService(
                db_engine=db_engine,
                local_identity_hash=local_lxmf_dest_hash,  # Actually LXMF dest hash
                node_store=self._node_store,
            )
            self._conversation_service.initialize()

            # Register callback for incoming chat messages
            lxmf_service.register_callback(
                self._handle_chat_message_for_conversation,
                raw_mode=True,
            )

            logger.info("Conversation service initialized")

        except Exception as e:
            logger.error(f"Failed to initialize conversation service: {e}")

    def _handle_chat_message_for_conversation(self, lxmf_message: "LXMF.LXMessage") -> None:
        """Handle incoming LXMF message for conversation service.

        Saves chat messages to the conversation service for history tracking,
        and broadcasts an event to connected IPC clients.

        Args:
            lxmf_message: Raw LXMF message from the library.
        """
        if not self._conversation_service:
            return

        try:
            # Check if this is a chat protocol message
            fields = lxmf_message.fields or {}
            protocol = fields.get("protocol", "")
            if protocol != "chat":
                # Not a chat message, skip
                return

            # Extract message data
            source_hash = lxmf_message.source_hash.hex()
            content = (
                lxmf_message.content.decode("utf-8")
                if isinstance(lxmf_message.content, bytes)
                else (lxmf_message.content or "")
            )
            timestamp = lxmf_message.timestamp if hasattr(lxmf_message, "timestamp") else None

            # Extract security metadata from LXMF message
            # These attributes may or may not exist depending on LXMF version
            signature_valid: bool | None = None
            transport_encrypted: bool | None = None
            if hasattr(lxmf_message, "signature_validated"):
                signature_valid = lxmf_message.signature_validated
            if hasattr(lxmf_message, "transport_encrypted"):
                transport_encrypted = lxmf_message.transport_encrypted

            # Store security metadata in fields dict for persistence
            # The conversation service will store these in the fields JSON
            fields["signature_valid"] = signature_valid
            fields["transport_encrypted"] = transport_encrypted

            # Save to conversation service
            msg_id = self._conversation_service.save_incoming_message(
                source_hash=source_hash,
                content=content,
                timestamp=timestamp,
                fields=fields,
            )

            logger.debug(f"Saved incoming chat message from {source_hash[:16]}...")

            # Broadcast event to connected IPC clients
            self._broadcast_chat_event(
                msg_id=msg_id,
                peer_hash=source_hash,
                content=content,
                timestamp=timestamp or 0.0,
                is_outgoing=False,
                fields=fields,
                signature_valid=signature_valid,
                transport_encrypted=transport_encrypted,
            )

        except Exception as e:
            logger.warning(f"Failed to save chat message to conversation service: {e}")

    def _broadcast_chat_event(
        self,
        msg_id: int,
        peer_hash: str,
        content: str,
        timestamp: float,
        is_outgoing: bool,
        fields: dict[str, object] | None = None,
        signature_valid: bool | None = None,
        transport_encrypted: bool | None = None,
        status: str | None = None,
        delivery_method: str | None = None,
    ) -> None:
        """Broadcast a chat message event to connected IPC clients.

        Args:
            msg_id: Database message ID
            peer_hash: LXMF hash of the peer
            content: Message content
            timestamp: Message timestamp
            is_outgoing: Whether this is an outgoing message
            fields: Optional LXMF fields
            signature_valid: Whether LXMF signature was validated (incoming only)
            transport_encrypted: Whether transport encryption was used (incoming only)
            status: Message status (pending, sent, delivered, failed, received)
            delivery_method: How message was delivered (direct, propagated, or None)
        """
        if not self._control_server:
            return

        try:
            import asyncio

            from styrened.ipc.protocol import IPCMessageType

            # Determine default status based on direction
            if status is None:
                status = "received" if not is_outgoing else "pending"

            event_payload = {
                "event_type": "new",
                "message_id": msg_id,
                "peer_hash": peer_hash,
                "content": content,
                "timestamp": timestamp,
                "is_outgoing": is_outgoing,
                "status": status,
                "delivery_method": delivery_method,
                "signature_valid": signature_valid,
                "transport_encrypted": transport_encrypted,
                "fields": fields or {},
            }

            # Schedule the async broadcast on the event loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._control_server.broadcast_event(
                        IPCMessageType.EVENT_MESSAGE, event_payload
                    )
                )
            except RuntimeError:
                # No running loop - skip broadcast
                logger.debug("No event loop for chat event broadcast")

        except Exception as e:
            logger.warning(f"Failed to broadcast chat event: {e}")

    def _broadcast_delivery_status_event(
        self,
        msg_id: int,
        peer_hash: str,
        status: str,
        delivery_method: str | None = None,
    ) -> None:
        """Broadcast delivery status change to IPC clients.

        This is used to notify connected clients when a message's delivery
        status changes (e.g., from pending to sent, or sent to delivered).

        Args:
            msg_id: Database message ID
            peer_hash: LXMF hash of the peer
            status: New message status (sent, delivered, failed)
            delivery_method: How message was delivered (direct, propagated, or None)
        """
        if not self._control_server:
            return

        try:
            import asyncio

            from styrened.ipc.protocol import IPCMessageType

            event_payload = {
                "event_type": "status_changed",
                "message_id": msg_id,
                "peer_hash": peer_hash,
                "status": status,
                "delivery_method": delivery_method,
            }

            # Schedule the async broadcast on the event loop
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._control_server.broadcast_event(
                        IPCMessageType.EVENT_MESSAGE, event_payload
                    )
                )
            except RuntimeError:
                # No running loop - skip broadcast
                logger.debug("No event loop for delivery status event broadcast")

        except Exception as e:
            logger.warning(f"Failed to broadcast delivery status event: {e}")

    def _start_rpc_server(self) -> None:
        """Start the RPC server for handling incoming requests."""
        # Check if RPC is enabled in config
        if not self.config.rpc.enabled:
            logger.info("RPC server disabled in configuration")
            return

        try:
            from styrened.models.messages import init_db
            from styrened.protocols.styrene import StyreneProtocol
            from styrened.rpc import RPCServer
            from styrened.services.lxmf_service import get_lxmf_service

            lxmf_service = get_lxmf_service()
            if not lxmf_service.is_initialized:
                logger.warning("LXMF not initialized, RPC server not started")
                return

            if not lxmf_service.router or not lxmf_service._identity:
                logger.warning("LXMF router or identity not available, RPC server not started")
                return

            # Initialize database for message persistence
            db_engine = init_db()

            # Create StyreneProtocol instance for RPC transport
            styrene_protocol = StyreneProtocol(
                router=lxmf_service.router,
                identity=lxmf_service._identity,
                db_engine=db_engine,
            )

            # Register StyreneProtocol as a callback handler for LXMF messages
            # so it can dispatch incoming Styrene messages to RPC handlers
            lxmf_service.register_callback(
                self._handle_styrene_message_dispatch(styrene_protocol),
                raw_mode=True,
            )

            self._rpc_server = RPCServer(styrene_protocol)

            # Create RPC client for outgoing requests (used by IPC handlers)
            from styrened.rpc import RPCClient

            self._rpc_client = RPCClient(styrene_protocol)
            logger.debug("RPC client created for IPC handlers")

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

    def _handle_styrene_message_dispatch(
        self, styrene_protocol: Any
    ) -> Callable[["LXMF.LXMessage"], None]:
        """Create a callback to dispatch LXMF messages to StyreneProtocol.

        This bridges the LXMFService callback mechanism with StyreneProtocol's
        message handling.

        Args:
            styrene_protocol: StyreneProtocol instance to dispatch messages to.

        Returns:
            Callback function for LXMFService.register_callback().
        """
        import asyncio

        from styrened.protocols.base import LXMFMessage

        def callback(lxmf_message: "LXMF.LXMessage") -> None:
            # Wrap raw LXMF message in our LXMFMessage dataclass
            wrapped = LXMFMessage(
                source_hash=lxmf_message.source_hash.hex(),
                destination_hash=lxmf_message.destination_hash.hex()
                if lxmf_message.destination_hash
                else "",
                timestamp=lxmf_message.timestamp if hasattr(lxmf_message, "timestamp") else 0.0,
                content=lxmf_message.content.decode("utf-8")
                if isinstance(lxmf_message.content, bytes)
                else (lxmf_message.content or ""),
                fields=lxmf_message.fields or {},
            )

            # Check if this is a Styrene protocol message
            if styrene_protocol.can_handle(wrapped):
                # Dispatch to StyreneProtocol (async)
                # The callback is invoked from RNS/LXMF library in a sync context,
                # so we need to schedule the coroutine on the running event loop
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(styrene_protocol.handle_message(wrapped))
                except RuntimeError:
                    # No running event loop - run synchronously in new loop
                    # This handles callbacks from non-async contexts
                    asyncio.run(styrene_protocol.handle_message(wrapped))

        return callback

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

            # Register the handler with LXMF service (not directly with router)
            # Use raw_mode=True since AutoReplyHandler expects LXMF.LXMessage
            lxmf_service.register_callback(self._auto_reply_handler.handle_message, raw_mode=True)

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

    async def _start_control_server(self) -> None:
        """Start IPC control socket server for CLI/TUI communication."""
        try:
            from styrened.ipc import ControlServer

            socket_path = self.config.ipc.socket_path
            socket_mode = self.config.ipc.socket_mode

            self._control_server = ControlServer(
                daemon=self,
                socket_path=socket_path,
                socket_mode=socket_mode,
            )
            await self._control_server.start()
            logger.info("IPC control server started")

        except Exception as e:
            logger.error(f"Failed to start IPC control server: {e}")

    def _announce(self) -> None:
        """Trigger an announce of the local operator destination.

        Called by IPC handlers and the main loop.
        """
        if not self._operator_destination:
            logger.warning("Cannot announce: no operator destination")
            return

        try:
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
            except Exception as e:
                logger.warning(f"Could not get LXMF destination for announce: {e}")

            app_data = f"styrene:{hostname}:{version}:{caps_str}:{lxmf_dest}".encode()
            self._operator_destination.announce(app_data=app_data)
            logger.info(f"Announced as Styrene node: {hostname}")

            # Also announce LXMF delivery destination
            try:
                from styrened.services.lxmf_service import get_lxmf_service

                lxmf_service = get_lxmf_service()
                if (
                    lxmf_service.is_initialized
                    and lxmf_service.router
                    and lxmf_service.delivery_destination
                ):
                    lxmf_service.router.announce(lxmf_service.delivery_destination.hash)
                    logger.debug("Announced LXMF delivery destination")
            except Exception as e:
                logger.warning(f"LXMF announce failed: {e}")

        except Exception as e:
            logger.warning(f"Announce failed: {e}")

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
                        if (
                            lxmf_service.is_initialized
                            and lxmf_service.router
                            and lxmf_service.delivery_destination
                        ):
                            lxmf_service.router.announce(lxmf_service.delivery_destination.hash)
                            logger.info("Re-announced LXMF delivery destination")
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

        # Stop IPC control server
        if self._control_server:
            await self._control_server.stop()
            self._control_server = None

        # Shutdown conversation service
        if self._conversation_service:
            self._conversation_service.shutdown()
            self._conversation_service = None

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
