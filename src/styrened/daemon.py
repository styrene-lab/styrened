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

try:
    import LXMF

    LXMF_AVAILABLE = True
except ImportError:
    LXMF_AVAILABLE = False

if TYPE_CHECKING:
    from styrened.models.mesh_device import MeshDevice

from styrened.models.config import CoreConfig
from styrened.services.auto_reply import AutoReplyHandler
from styrened.services.config import get_default_core_config, load_core_config
from styrened.services.lifecycle import CoreLifecycle
from styrened.services.node_store import get_node_store
from styrened.services.path_snapshot import PathSnapshotService
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
        self._read_receipt_protocol: Any = None  # Read receipt protocol handler
        self._auto_reply_handler: AutoReplyHandler | None = None
        self._operator_destination: RNS.Destination | None = None
        self._node_store: Any = None  # NodeStore for device persistence
        self._path_snapshot: PathSnapshotService | None = None
        self._terminal_service: Any = None  # Terminal session service
        self._styrene_protocol: Any = None  # Styrene protocol for RPC/terminal

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

        # Start path table snapshot service for topology edge data
        self._path_snapshot = PathSnapshotService(self._node_store)
        self._path_snapshot.start()

        # Start HTTP API if enabled
        if self.config.api.enabled:
            await self._start_api()

        # Start IPC control server if enabled
        if self.config.ipc.enabled:
            await self._start_control_server()

        # Start terminal service if enabled
        if self.config.terminal.enabled:
            self._start_terminal_service()

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

            # Initialize read receipt protocol for ecosystem compatibility
            self._init_read_receipt_protocol(lxmf_service)

            logger.info("Conversation service initialized")

        except Exception as e:
            logger.error(f"Failed to initialize conversation service: {e}")

    def _init_read_receipt_protocol(self, lxmf_service: Any) -> None:
        """Initialize the read receipt protocol handler.

        Creates and registers the ReadReceiptProtocol for handling incoming
        read receipts and sending outgoing receipts when messages are marked read.

        Args:
            lxmf_service: Initialized LXMFService instance.
        """
        if not self._conversation_service:
            logger.warning("Conversation service not available, skipping read receipt protocol")
            return

        try:
            from styrened.protocols.read_receipt import ReadReceiptProtocol

            self._read_receipt_protocol = ReadReceiptProtocol(
                conversation_service=self._conversation_service,
                lxmf_service=lxmf_service,
            )

            # Register callback for incoming read receipt messages
            lxmf_service.register_callback(
                self._handle_read_receipt_message,
                raw_mode=True,
            )

            logger.info("Read receipt protocol initialized")

        except Exception as e:
            logger.error(f"Failed to initialize read receipt protocol: {e}")

    def _handle_read_receipt_message(self, lxmf_message: "LXMF.LXMessage") -> None:
        """Handle incoming LXMF message that might be a read receipt.

        Routes read receipt protocol messages to the ReadReceiptProtocol handler.

        Args:
            lxmf_message: Raw LXMF message from the library.
        """
        if not self._read_receipt_protocol:
            return

        try:
            # Check if this is a read receipt protocol message
            fields = lxmf_message.fields or {}
            protocol = fields.get("protocol", "")
            if protocol != "read_receipt":
                # Not a read receipt, skip
                return

            # Create an LXMFMessage wrapper for the protocol handler
            from styrened.protocols.base import LXMFMessage

            wrapped_message = LXMFMessage(
                source_hash=lxmf_message.source_hash.hex(),
                destination_hash=lxmf_message.destination_hash.hex()
                if hasattr(lxmf_message, "destination_hash")
                else "",
                content=lxmf_message.content.decode("utf-8")
                if isinstance(lxmf_message.content, bytes)
                else (lxmf_message.content or ""),
                fields=fields,
                timestamp=float(lxmf_message.timestamp)
                if hasattr(lxmf_message, "timestamp") and lxmf_message.timestamp is not None
                else 0.0,
            )

            # Handle asynchronously
            asyncio.create_task(self._read_receipt_protocol.handle_message(wrapped_message))

            logger.debug(f"Routed read receipt from {wrapped_message.source_hash[:16]}...")

        except Exception as e:
            logger.warning(f"Failed to handle read receipt message: {e}")

    async def send_read_receipts(self, peer_hash: str) -> bool:
        """Send read receipts for messages we've read from a peer.

        Called when marking a conversation as read. Collects message hashes
        that haven't had receipts sent yet and sends a batched read receipt.

        Args:
            peer_hash: LXMF destination hash of the peer.

        Returns:
            True if receipts were sent (or none needed), False on error.
        """
        if not self._read_receipt_protocol or not self._conversation_service:
            return False

        try:
            # Get hashes of messages we've read but haven't sent receipts for
            hashes = self._conversation_service.get_unread_hashes_for_receipt(peer_hash)

            if not hashes:
                logger.debug(f"No pending read receipts for {peer_hash[:16]}...")
                return True

            # Send the read receipt
            success: bool = self._read_receipt_protocol.send_read_receipt(peer_hash, hashes)

            if success:
                # Mark these messages as having receipts sent
                self._conversation_service.mark_receipts_sent(hashes)
                logger.info(f"Sent read receipts for {len(hashes)} messages to {peer_hash[:16]}...")

            return success

        except Exception as e:
            logger.error(f"Failed to send read receipts: {e}")
            return False

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
            # Sideband/NomadNet/MeshChat send messages WITHOUT a protocol field
            # We treat missing/empty protocol as "chat" for ecosystem compatibility
            fields = lxmf_message.fields or {}
            protocol = fields.get("protocol", "")

            # Skip non-chat protocols (styrene RPC, read receipts, etc.)
            # But treat empty protocol as chat (Sideband compatibility)
            if protocol and protocol != "chat":
                # Explicit non-chat protocol, skip
                return

            # Check for StyreneProtocol custom fields (binary protocol, not chat)
            # FIELD_CUSTOM_TYPE = 0xFB
            if fields.get(0xFB) or fields.get("custom_type"):
                return

            # Extract message data
            source_hash = lxmf_message.source_hash.hex()
            content = (
                lxmf_message.content.decode("utf-8")
                if isinstance(lxmf_message.content, bytes)
                else (lxmf_message.content or "")
            )
            timestamp = lxmf_message.timestamp if hasattr(lxmf_message, "timestamp") else None

            # Extract title from native LXMF field or fields dict (for ecosystem compatibility)
            title: str | None = None
            if hasattr(lxmf_message, "title") and lxmf_message.title:
                title = str(lxmf_message.title)
            elif fields.get("title"):
                title = str(fields["title"])

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

            # Extract threading information (LXMF FIELD_THREAD = 0x08)
            # Supports dict format {thread_id, reply_to} or list format [thread_id, reply_to]
            thread_id: str | None = None
            reply_to_hash: str | None = None
            thread_field = fields.get(LXMF.FIELD_THREAD) if LXMF_AVAILABLE else fields.get(0x08)
            if thread_field:
                if isinstance(thread_field, dict):
                    # Dict format: {"thread_id": "...", "reply_to": "..."}
                    thread_id = thread_field.get("thread_id") or thread_field.get("t")
                    reply_to_hash = thread_field.get("reply_to") or thread_field.get("r")
                elif isinstance(thread_field, (list, tuple)) and len(thread_field) >= 2:
                    # List format: [thread_id, reply_to]
                    thread_id = str(thread_field[0]) if thread_field[0] else None
                    reply_to_hash = str(thread_field[1]) if thread_field[1] else None
                # Convert bytes to hex string if needed
                if isinstance(thread_id, bytes):
                    thread_id = thread_id.hex()
                if isinstance(reply_to_hash, bytes):
                    reply_to_hash = reply_to_hash.hex()

            # Extract attachment information from LXMF fields
            # FIELD_IMAGE = 0x06, FIELD_AUDIO = 0x07, FIELD_FILE_ATTACHMENTS = 0x05
            has_attachment = False
            attachment_type: str | None = None
            attachment_name: str | None = None
            attachment_size: int | None = None
            attachment_mime: str | None = None

            # Check for image (FIELD_IMAGE = 0x06)
            image_field = fields.get(LXMF.FIELD_IMAGE) if LXMF_AVAILABLE else fields.get(0x06)
            if image_field:
                has_attachment = True
                attachment_type = "image"
                if isinstance(image_field, tuple) and len(image_field) >= 2:
                    # Format: (mime_type, data)
                    attachment_mime = str(image_field[0]) if image_field[0] else None
                    attachment_size = (
                        len(image_field[1]) if isinstance(image_field[1], bytes) else None
                    )
                elif isinstance(image_field, bytes):
                    attachment_size = len(image_field)

            # Check for audio (FIELD_AUDIO = 0x07)
            if not has_attachment:
                audio_field = fields.get(LXMF.FIELD_AUDIO) if LXMF_AVAILABLE else fields.get(0x07)
                if audio_field:
                    has_attachment = True
                    attachment_type = "audio"
                    if isinstance(audio_field, tuple) and len(audio_field) >= 2:
                        # Format: (codec_mode, data) or (mime_type, data)
                        # The first element may be an integer codec mode or a mime string
                        first_elem = audio_field[0]
                        if isinstance(first_elem, int):
                            # Codec mode - map to mime type if needed
                            attachment_mime = f"audio/codec2;mode={first_elem}"
                        elif first_elem:
                            attachment_mime = str(first_elem)
                        attachment_size = (
                            len(audio_field[1]) if isinstance(audio_field[1], bytes) else None
                        )
                    elif isinstance(audio_field, bytes):
                        attachment_size = len(audio_field)

            # Check for file attachments (FIELD_FILE_ATTACHMENTS = 0x05)
            if not has_attachment:
                file_field = (
                    fields.get(LXMF.FIELD_FILE_ATTACHMENTS) if LXMF_AVAILABLE else fields.get(0x05)
                )
                if file_field:
                    has_attachment = True
                    attachment_type = "file"
                    if isinstance(file_field, list) and len(file_field) > 0:
                        first_file = file_field[0]
                        if isinstance(first_file, tuple) and len(first_file) >= 2:
                            # Format: (filename, data) or (filename, data, mime_type)
                            attachment_name = str(first_file[0]) if first_file[0] else None
                            attachment_size = (
                                len(first_file[1]) if isinstance(first_file[1], bytes) else None
                            )
                            if len(first_file) >= 3 and first_file[2]:
                                attachment_mime = str(first_file[2])

            # Save to conversation service
            msg_id = self._conversation_service.save_incoming_message(
                source_hash=source_hash,
                content=content,
                timestamp=timestamp,
                title=title,
                fields=fields,
                thread_id=thread_id,
                reply_to_hash=reply_to_hash,
                has_attachment=has_attachment,
                attachment_type=attachment_type,
                attachment_name=attachment_name,
                attachment_size=attachment_size,
                attachment_mime=attachment_mime,
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
            self._styrene_protocol = StyreneProtocol(
                router=lxmf_service.router,
                identity=lxmf_service._identity,
                db_engine=db_engine,
            )

            # Register StyreneProtocol as a callback handler for LXMF messages
            # so it can dispatch incoming Styrene messages to RPC handlers
            lxmf_service.register_callback(
                self._handle_styrene_message_dispatch(self._styrene_protocol),
                raw_mode=True,
            )

            self._rpc_server = RPCServer(self._styrene_protocol)

            # Create RPC client for outgoing requests (used by IPC handlers)
            from styrened.rpc import RPCClient

            self._rpc_client = RPCClient(self._styrene_protocol)
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

    def _start_terminal_service(self) -> None:
        """Start the terminal session service.

        The terminal service enables remote shell access via the Styrene
        terminal protocol. It uses:
        - LXMF control plane for session establishment/teardown
        - RNS Link data plane for I/O streaming
        """
        try:
            from styrened.services.rns_service import get_rns_service
            from styrened.terminal.service import TerminalService

            rns_service = get_rns_service()
            if not rns_service.is_initialized:
                logger.warning("RNS not initialized, terminal service not started")
                return

            if not self._styrene_protocol:
                logger.warning("Styrene protocol not available, terminal service not started")
                return

            # Build kwargs for terminal service
            terminal_kwargs: dict[str, Any] = {
                "rns_service": rns_service,
                "styrene_protocol": self._styrene_protocol,
                "authorized_identities": self.config.terminal.authorized_identities,
                "allow_unauthenticated": self.config.terminal.allow_unauthenticated,
                "session_idle_timeout": self.config.terminal.session_idle_timeout,
                "max_sessions_per_identity": self.config.terminal.max_sessions_per_identity,
                "max_total_sessions": self.config.terminal.max_total_sessions,
            }

            # Only pass default_shell if configured
            if self.config.terminal.default_shell:
                terminal_kwargs["default_shell"] = self.config.terminal.default_shell

            # Only pass allowed_shells if configured (otherwise use defaults)
            if self.config.terminal.allowed_shells:
                terminal_kwargs["allowed_shells"] = self.config.terminal.allowed_shells

            # Create terminal service with config
            self._terminal_service = TerminalService(**terminal_kwargs)

            # Start the service (registers handlers, creates destination)
            self._terminal_service.start()

            logger.info(
                f"[METRICS] terminal_service_started "
                f"authorized_identities={len(self.config.terminal.authorized_identities)} "
                f"allow_unauthenticated={self.config.terminal.allow_unauthenticated} "
                f"max_sessions={self.config.terminal.max_total_sessions}"
            )

        except ImportError as e:
            logger.warning(f"Terminal service not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start terminal service: {e}")

    def _stop_terminal_service(self) -> None:
        """Stop the terminal session service gracefully."""
        if self._terminal_service:
            try:
                self._terminal_service.stop()
                logger.info("[METRICS] terminal_service_stopped")
            except Exception as e:
                logger.error(f"Error stopping terminal service: {e}")
            finally:
                self._terminal_service = None

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

            # Use display_name from config, fall back to hostname
            display_name = self.config.identity.display_name or hostname
            # Include icon in display_name if configured
            if self.config.identity.icon:
                display_name = f"{self.config.identity.icon} {display_name}"

            # Include LXMF delivery destination in announce
            lxmf_dest = ""
            try:
                from styrened.services.lxmf_service import get_lxmf_service

                lxmf_service = get_lxmf_service()
                if lxmf_service.is_initialized and lxmf_service.delivery_destination:
                    lxmf_dest = lxmf_service.delivery_destination.hash.hex()
            except Exception as e:
                logger.warning(f"Could not get LXMF destination for announce: {e}")

            # Format: styrene:{display_name}:{version}:{caps}:{lxmf_dest}
            app_data = f"styrene:{display_name}:{version}:{caps_str}:{lxmf_dest}".encode()
            self._operator_destination.announce(app_data=app_data)
            logger.info(f"Announced as Styrene node: {display_name}")

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

                    # Use display_name from config, fall back to hostname
                    display_name = self.config.identity.display_name or hostname
                    # Include icon in display_name if configured
                    if self.config.identity.icon:
                        display_name = f"{self.config.identity.icon} {display_name}"

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

                    # Format: styrene:{display_name}:{version}:{caps}:{lxmf_dest}
                    app_data = f"styrene:{display_name}:{version}:{caps_str}:{lxmf_dest}".encode()
                    destination.announce(app_data=app_data)
                    logger.info(f"Re-announced as Styrene node: {display_name}")

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

            # Cleanup stale delivery trackers to prevent memory leaks
            # (for messages where LXMF callbacks never fired)
            if self._conversation_service:
                self._conversation_service.cleanup_stale_deliveries()

    async def stop(self) -> None:
        """Stop the daemon services."""
        logger.info("Stopping Styrene daemon...")
        self._running = False

        # Stop terminal service (closes all sessions)
        self._stop_terminal_service()

        # Stop IPC control server
        if self._control_server:
            await self._control_server.stop()
            self._control_server = None

        # Shutdown conversation service
        if self._conversation_service:
            self._conversation_service.shutdown()
            self._conversation_service = None

        # Stop path snapshot service
        if self._path_snapshot:
            self._path_snapshot.stop()
            self._path_snapshot = None

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
