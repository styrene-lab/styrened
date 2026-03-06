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
import json
import logging
import signal
import sys
import time
import uuid
from collections import deque
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

try:
    from styrened.crypto.pqc_crypto import pqc_available
except ImportError:
    pqc_available = lambda: False  # noqa: E731
from styrened.models.config import CoreConfig
from styrened.models.mesh_device import DeviceType
from styrened.services.auto_reply import AutoReplyHandler
from styrened.services.config import get_default_core_config, load_core_config
from styrened.services.lifecycle import CoreLifecycle
from styrened.services.node_store import get_node_store
from styrened.services.path_snapshot import PathSnapshotService
from styrened.services.reticulum import discover_devices, start_discovery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Datalink security constants
# ---------------------------------------------------------------------------

# Maximum speedtest payload accepted from a remote (avoids memory exhaustion
# from a malicious node sending arbitrarily large payloads).
_SPEEDTEST_MAX_PAYLOAD_BYTES = 1_048_576  # 1 MiB

# Datalink per-identity rate limits (requests per minute).
# Light endpoints (meta/info/ping/status): cheap to serve.
# Heavy endpoints (speedtest): CPU and memory cost per call.
_DL_LIGHT_LIMIT = 20
_DL_HEAVY_LIMIT = 3
_DL_WINDOW_SECONDS = 60.0
# Maximum number of unique identities tracked in the rate limiter.
# Old entries are evicted (FIFO) when this limit is reached to bound memory.
_DL_MAX_TRACKED = 512


class _DataLinkRateLimiter:
    """Per-identity token-bucket rate limiter for DataLink request handlers.

    Maintains a sliding-window counter per identity.  Two tiers:
    - ``light``: for low-cost endpoints (/meta, /info, /ping, /status)
    - ``heavy``: for expensive endpoints (/speedtest)

    Thread-safety: not needed — all datalink handlers are called from
    the RNS thread pool synchronously, so contention is limited.
    However, the dict is bounded to avoid unbounded memory growth.
    """

    def __init__(self) -> None:
        # identity_hex → deque of call timestamps (float, seconds)
        self._ts: dict[str, deque[float]] = {}
        # Insertion-order tracking for FIFO eviction
        self._order: deque[str] = deque()

    def _evict_if_needed(self) -> None:
        while len(self._order) >= _DL_MAX_TRACKED:
            old = self._order.popleft()
            self._ts.pop(old, None)

    def _prune(self, identity: str, now: float) -> deque[float]:
        """Prune timestamps outside the window and return the remaining queue."""
        cutoff = now - _DL_WINDOW_SECONDS
        ts = self._ts.get(identity)
        if ts is None:
            self._evict_if_needed()
            ts = deque()
            self._ts[identity] = ts
            self._order.append(identity)
        while ts and ts[0] <= cutoff:
            ts.popleft()
        return ts

    def check(self, identity: str, heavy: bool = False) -> bool:
        """Return True if the request is within limits, False if rate-limited.

        Args:
            identity: Hex identity hash of the remote caller.
            heavy: True for the speedtest endpoint.
        """
        if not identity:
            # Unknown identity — allow (RNS link was established but identify()
            # not called; restrict at Phase 3 when ALLOW_LIST is enforced).
            return True
        now = time.time()
        limit = _DL_HEAVY_LIMIT if heavy else _DL_LIGHT_LIMIT
        ts = self._prune(identity, now)
        if len(ts) >= limit:
            return False
        ts.append(now)
        return True


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
        self._eager_start_time: float = 0.0  # Reset in _run_loop and on reconnect
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
        self._contact_service: Any = None  # Contact address book service
        self._notification_service: Any = None  # Notification dispatch service
        self._callback_backend: Any = None  # For TUI/GUI callback registration
        self._page_browser_service: Any = None  # NomadNet page browsing service
        self._page_cache_service: Any = None  # NomadNet page caching service
        self._page_server_service: Any = None  # NomadNet page server service
        self._pqc_service: Any = None  # PQC session layer service
        self._direct_link_service: Any = None  # Direct data link service
        self._datalink_destination: Any = None  # Incoming datalink RNS.Destination
        self._mesh_vpn_service: Any = None  # WireGuard mesh VPN service
        self._datalink_rl: _DataLinkRateLimiter = _DataLinkRateLimiter()

    async def start(self) -> None:
        """Start the daemon services."""
        logger.info("Starting Styrene daemon...")
        self._event_loop = asyncio.get_running_loop()

        # Migrate legacy paths (copies files, idempotent)
        from styrened import paths

        actions = paths.migrate_legacy_paths()
        for action in actions:
            logger.info(f"[paths] {action}")

        # Initialize Styrene services
        if not self.lifecycle.initialize():
            logger.error("Failed to initialize services")
            sys.exit(1)

        # Create and cache the operator destination once
        self._init_operator_destination()

        # Start RPC server for incoming requests
        self._start_rpc_server()

        # Inject RBAC policy into LXMF service — must happen before any
        # message processing begins, regardless of chat.enabled state.
        # LXMF receives both chat AND Styrene RPC messages; without RBAC
        # injection, BLOCKED identities can still deliver LXMF messages.
        self._inject_lxmf_rbac()

        # Initialize conversation service for chat backend (creates DB tables)
        self._init_conversation_service()

        # Seed blocklist from config (for hub operators)
        # Must run AFTER _init_conversation_service() which calls init_db()
        if self.config.banned_peers:
            self._seed_config_bans()

        # Wire conversation service into RPC server for remote inbox queries
        if self._rpc_server and self._conversation_service:
            self._rpc_server.set_conversation_service(self._conversation_service)

        # Initialize PQC session layer (after StyreneProtocol is available)
        self._init_pqc_service()

        # Start auto-reply handler for chat messages
        self._start_auto_reply()

        # Start device discovery with NodeStore for persistence
        # This ensures discovered devices are persisted and their identity_hash
        # mappings are available for identity resolution when sending messages
        self._node_store = get_node_store()
        start_discovery(
            callback=self._on_device_discovered,
            node_store=self._node_store,
            access_mode=self.config.discovery.access_mode,
            allowed_peers=self.config.discovery.allowed_peers,
        )

        # Start path table snapshot service for topology edge data
        self._path_snapshot = PathSnapshotService(self._node_store)
        self._path_snapshot.start()

        # Start HTTP API if enabled
        if self.config.api.enabled:
            await self._start_api()

        # Start IPC control server if enabled
        if self.config.ipc.enabled:
            await self._start_control_server()

        # Initialize notification service (after control server for IPC backend)
        self._init_notification_service()

        # Start terminal service if enabled
        if self.config.terminal.enabled:
            self._start_terminal_service()

        # Start page browser service for NomadNet page fetching
        await self._start_page_browser()

        # Start page server service if enabled
        self._start_page_server()

        # Start direct data link service + listener
        await self._start_direct_link()

        self._running = True
        logger.info("Styrene daemon running")

        # Main loop with periodic announces
        await self._run_loop()

    def _inject_lxmf_rbac(self) -> None:
        """Inject RBAC policy into LXMFService for unified blocklist checks.

        Called from start() independently of chat.enabled, because LXMF
        receives both chat AND Styrene RPC messages. Without this, BLOCKED
        identities could still deliver LXMF messages even when the RPC
        server has RBAC active.

        Also seeds contacts-DB blocks into the RBAC blocked list so that
        runtime blocks (via IPC block_peer) survive daemon restart.
        """
        try:
            from styrened.services.lxmf_service import get_lxmf_service

            lxmf_service = get_lxmf_service()
            if not lxmf_service.is_initialized:
                logger.debug("LXMF not initialized, skipping RBAC injection")
                return

            if self.config.rbac is not None:
                lxmf_service.set_rbac_policy(self.config.rbac)
                self._seed_contacts_blocks_to_rbac(lxmf_service)
            else:
                logger.info(
                    "No RBAC policy configured — LXMF using legacy blocklist"
                )
        except Exception as e:
            logger.error(f"Failed to inject RBAC into LXMF service: {e}")

    def _seed_config_bans(self) -> None:
        """Block peers listed in config.banned_peers (hub operator banlist).

        Ensures the contacts table exists even if chat is disabled,
        because block_peer() writes directly to the contacts table.
        """
        try:
            from styrened.models.messages import init_db

            # Guarantee contacts table exists — _init_conversation_service
            # skips init_db() when chat.enabled=False
            init_db()

            from styrened.services.lxmf_service import get_lxmf_service

            svc = get_lxmf_service()
            for peer_hash in self.config.banned_peers:
                svc.block_peer(peer_hash)
            logger.info(
                f"Seeded {len(self.config.banned_peers)} banned peers from config"
            )
        except Exception as e:
            logger.error(f"Failed to seed config bans: {e}")

    def _seed_contacts_blocks_to_rbac(self, lxmf_service: Any) -> None:
        """Load blocked peers from contacts DB into the RBAC blocked list.

        On startup, the RBAC policy is rebuilt from core-config.yaml which
        only contains config-file blocks. Runtime blocks created via IPC
        block_peer() live in the contacts DB. This method loads them into
        the in-memory RBAC policy so they survive daemon restart.

        Calls init_db() first to ensure the contacts table exists — this
        is idempotent and safe to call multiple times.
        """
        try:
            from styrened.models.messages import init_db

            init_db()  # Ensure contacts table exists before querying
            blocked_set = lxmf_service._load_blocklist()
            if not blocked_set or self.config.rbac is None:
                return
            seeded = 0
            for peer_hash in blocked_set:
                if peer_hash not in self.config.rbac.blocked:
                    self.config.rbac.block(peer_hash)
                    seeded += 1
            if seeded:
                logger.info(
                    f"Seeded {seeded} contacts-DB blocks into RBAC policy"
                )
        except Exception as e:
            logger.error(f"Failed to seed contacts blocks to RBAC: {e}")

    def _emit_activity_event(
        self,
        event_type: str,
        peer_hash: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Emit a NotificationEvent for the unified activity feed.

        Dispatches through NotificationService which routes to both
        targeted IPC event types and EVENT_ACTIVITY.

        Args:
            event_type: Event category string.
            peer_hash: LXMF hash of the peer (if applicable).
            metadata: Additional event-specific data.
        """
        if self._notification_service is None:
            return

        from styrened.services.notifications import NotificationEvent

        event = NotificationEvent(
            event_type=event_type,
            peer_hash=peer_hash,
            timestamp=time.time(),
            metadata=metadata or {},
        )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._notification_service.notify(event))
        except RuntimeError:
            pass

    def _on_device_discovered(self, device: "MeshDevice") -> None:
        """Handle discovered device.

        Args:
            device: Discovered MeshDevice.
        """
        logger.info(
            f"Discovered: {device.name} ({device.device_type.value}) - {device.status.value}"
        )

        try:
            from styrened.web.metrics import devices_discovered_total

            devices_discovered_total.inc()
        except ImportError:
            pass

        # Broadcast to web UI SSE clients
        if self._api_server is not None:
            try:
                from styrened.web.events import SSEBroadcaster

                app = getattr(self, "_web_app", None)
                if app is not None:
                    broadcaster: SSEBroadcaster = app.state.broadcaster
                    broadcaster.broadcast_device_event(device)
            except Exception:
                pass

        # Emit activity event for dashboard feed
        self._emit_activity_event(
            "device_discovered",
            peer_hash=device.destination_hash,
            metadata={
                "name": device.name,
                "device_type": device.device_type.value,
                "status": device.status.value,
            },
        )

        # Auto-initiate PQC session with Styrene nodes
        self._maybe_initiate_pqc(device)

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

        # Clear stale cached destination from both daemon and RNS service
        from styrened.services.rns_service import get_rns_service
        rns_service = get_rns_service()
        rns_service.clear_destinations()
        self._operator_destination = None

        # Re-initialize operator destination
        self._init_operator_destination()

        # Clear stale page browser links and force path re-discovery
        if self._page_browser_service is not None:
            self._page_browser_service.handle_reconnection()

        # Flag direct link service for path re-discovery
        if self._direct_link_service is not None:
            self._direct_link_service.handle_reconnection()

        # Re-enter eager discovery phase (15s intervals for 2 minutes)
        # so peers rediscover us quickly after network change
        import time as _time
        self._eager_start_time = _time.monotonic()
        logger.info("[RECONNECT] Re-entering eager discovery phase")

        # Trigger a re-announce to make ourselves visible again
        if self._operator_destination:
            try:
                self._announce()
                logger.info("[RECONNECT] Daemon re-announced after reconnection")
            except Exception as e:
                logger.warning(f"[RECONNECT] Failed to re-announce: {e}")

    def _init_pqc_service(self) -> None:
        """Initialize PQC session layer if enabled and liboqs is available."""
        if not self.config.pqc.enabled:
            logger.info("PQC session layer disabled in configuration")
            return

        if not self._styrene_protocol:
            logger.warning("PQC enabled but StyreneProtocol not available")
            return

        if not pqc_available():
            logger.warning("PQC enabled but liboqs not installed — running RNS-only")
            return

        try:
            from styrened.services.pqc_session import PQCSessionService

            self._pqc_service = PQCSessionService(self._styrene_protocol, self.config.pqc)
            logger.info("PQC session layer initialized (ML-KEM-768 + X25519)")
        except Exception as e:
            logger.error(f"Failed to initialize PQC session service: {e}")

    def _maybe_initiate_pqc(self, device: "MeshDevice") -> None:
        """Auto-initiate PQC session with a newly discovered Styrene node.

        Args:
            device: Discovered MeshDevice.
        """
        if not self._pqc_service:
            return
        if not self.config.pqc.auto_initiate:
            return
        if device.device_type != DeviceType.STYRENE_NODE:
            return

        try:
            # initiate_session_sync() is non-blocking: it schedules the async
            # handshake via loop.create_task(), so it is safe to call from this
            # synchronous discovery callback without blocking the event loop.
            self._pqc_service.initiate_session_sync(device.destination_hash)
        except Exception as e:
            logger.warning(f"PQC auto-initiate failed for {device.destination_hash[:16]}...: {e}")

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

            # Create contact service (shares db_engine and node_store)
            from styrened.services.contacts import ContactService

            self._contact_service = ContactService(
                db_engine=db_engine,
                node_store=self._node_store,
            )

            # Create conversation service
            self._conversation_service = ConversationService(
                db_engine=db_engine,
                local_identity_hash=local_lxmf_dest_hash,  # Actually LXMF dest hash
                node_store=self._node_store,
                contact_service=self._contact_service,
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
                if isinstance(image_field, (list, tuple)) and len(image_field) >= 2:
                    # Format: (mime_type, data) — msgpack deserializes tuples as lists
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
                    if isinstance(audio_field, (list, tuple)) and len(audio_field) >= 2:
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
                        if isinstance(first_file, (list, tuple)) and len(first_file) >= 2:
                            # Format: (filename, data) or (filename, data, mime_type)
                            attachment_name = str(first_file[0]) if first_file[0] else None
                            attachment_size = (
                                len(first_file[1]) if isinstance(first_file[1], bytes) else None
                            )
                            if len(first_file) >= 3 and first_file[2]:
                                attachment_mime = str(first_file[2])

            # Extract and store raw attachment binary data
            attachment_path: str | None = None
            if has_attachment:
                try:
                    from styrened.services.attachment_store import get_attachment_store

                    raw_data: bytes | None = None
                    att_filename = attachment_name or f"{attachment_type or 'file'}_attachment"

                    if attachment_type == "image" and image_field:
                        if isinstance(image_field, (list, tuple)) and len(image_field) >= 2:
                            raw_data = image_field[1] if isinstance(image_field[1], bytes) else None
                        elif isinstance(image_field, bytes):
                            raw_data = image_field
                        if not attachment_name:
                            # Derive extension from mime
                            ext = ".jpg"
                            if attachment_mime:
                                mime_ext = attachment_mime.split("/")[-1].split(";")[0]
                                if mime_ext in ("png", "gif", "webp", "bmp", "tiff"):
                                    ext = f".{mime_ext}"
                            att_filename = f"image{ext}"

                    elif attachment_type == "audio":
                        audio_field_val = fields.get(LXMF.FIELD_AUDIO) if LXMF_AVAILABLE else fields.get(0x07)
                        if audio_field_val:
                            if isinstance(audio_field_val, (list, tuple)) and len(audio_field_val) >= 2:
                                raw_data = audio_field_val[1] if isinstance(audio_field_val[1], bytes) else None
                            elif isinstance(audio_field_val, bytes):
                                raw_data = audio_field_val
                        if not attachment_name:
                            att_filename = "audio.opus"

                    elif attachment_type == "file":
                        file_field_val = fields.get(LXMF.FIELD_FILE_ATTACHMENTS) if LXMF_AVAILABLE else fields.get(0x05)
                        if file_field_val and isinstance(file_field_val, list) and len(file_field_val) > 0:
                            if len(file_field_val) > 1:
                                logger.info(
                                    f"Multi-file message from {source_hash[:8]}: "
                                    f"{len(file_field_val)} files"
                                )
                            first = file_field_val[0]
                            if isinstance(first, (list, tuple)) and len(first) >= 2:
                                raw_data = first[1] if isinstance(first[1], bytes) else None

                    store = get_attachment_store()
                    # Use a UUID-based temp identifier instead of message_id=0
                    # to avoid filename collisions when multiple attachments
                    # arrive concurrently.  The file is renamed to the real
                    # msg_id after the DB commit returns it.
                    temp_msg_id = uuid.uuid4().int & 0x7FFFFFFF  # positive 31-bit int

                    if raw_data is not None:
                        saved_path = store.save(
                            source_hash, temp_msg_id, att_filename, raw_data, mime=attachment_mime
                        )
                        attachment_path = str(saved_path)
                        logger.debug(f"Saved attachment: {att_filename} ({len(raw_data)} bytes)")

                    # Save additional files from multi-file messages
                    if attachment_type == "file":
                        file_field_val = fields.get(LXMF.FIELD_FILE_ATTACHMENTS) if LXMF_AVAILABLE else fields.get(0x05)
                        if file_field_val and isinstance(file_field_val, list) and len(file_field_val) > 1:
                            for idx, extra_file in enumerate(file_field_val[1:], start=1):
                                if isinstance(extra_file, (list, tuple)) and len(extra_file) >= 2:
                                    extra_name = str(extra_file[0]) if extra_file[0] else f"file_{idx}"
                                    extra_data = extra_file[1] if isinstance(extra_file[1], bytes) else None
                                    extra_mime = str(extra_file[2]) if len(extra_file) >= 3 and extra_file[2] else None
                                    if extra_data is not None:
                                        try:
                                            store.save(
                                                source_hash, temp_msg_id, extra_name, extra_data, mime=extra_mime
                                            )
                                            logger.debug(
                                                f"Saved additional attachment {idx}: "
                                                f"{extra_name} ({len(extra_data)} bytes)"
                                            )
                                        except Exception as e:
                                            logger.warning(f"Failed to save additional attachment {idx}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to save attachment data: {e}")

            try:
                from styrened.web.metrics import messages_total

                messages_total.labels(direction="incoming", status="received").inc()
            except ImportError:
                pass

            # Build a JSON-safe fields dict for persistence.
            # Raw LXMF fields contain binary blobs (image data, audio data, file
            # contents) under integer keys that cannot be JSON-serialized.
            # Attachment metadata is already extracted into dedicated columns, so
            # we only keep serializable scalar/string values.
            safe_fields: dict[str, Any] = {}
            for k, v in fields.items():
                str_key = str(k)
                if isinstance(v, (str, int, float, bool, type(None))):
                    safe_fields[str_key] = v
                elif isinstance(v, bytes):
                    # Binary blob — record presence/size, not data
                    safe_fields[str_key] = f"<bytes:{len(v)}>"
                elif isinstance(v, (list, tuple)):
                    # Attachment tuples (mime, data) — summarize
                    safe_fields[str_key] = f"<{type(v).__name__}:{len(v)}>"
                elif isinstance(v, dict):
                    # Nested dicts (e.g. thread info) — try to keep if safe
                    try:
                        json.dumps(v)
                        safe_fields[str_key] = v
                    except (TypeError, ValueError):
                        safe_fields[str_key] = f"<dict:{len(v)}>"

            # Save to conversation service
            msg_id = self._conversation_service.save_incoming_message(
                source_hash=source_hash,
                content=content,
                timestamp=timestamp,
                title=title,
                fields=safe_fields,
                thread_id=thread_id,
                reply_to_hash=reply_to_hash,
                has_attachment=has_attachment,
                attachment_type=attachment_type,
                attachment_name=attachment_name,
                attachment_size=attachment_size,
                attachment_mime=attachment_mime,
                attachment_path=attachment_path,
            )

            # Rename attachment file to include real message_id
            if attachment_path:
                try:
                    from pathlib import Path

                    from styrened.services.attachment_store import get_attachment_store

                    store = get_attachment_store()
                    new_path = store.rename_for_message(Path(attachment_path), msg_id)
                    if str(new_path) != attachment_path:
                        # Update the DB record with the new path
                        self._conversation_service.update_attachment_path(msg_id, str(new_path))
                except Exception as e:
                    logger.warning(f"Failed to rename attachment for msg {msg_id}: {e}")

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

        Dispatches through NotificationService when available, which fans out
        to all backends (IPC, SSE, callbacks). Falls back to direct broadcast.

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
        # Determine default status based on direction
        if status is None:
            status = "received" if not is_outgoing else "pending"

        # Dispatch through notification service if available
        if self._notification_service is not None:
            try:
                from styrened.services.notifications import NotificationEvent

                event = NotificationEvent(
                    event_type="new_message",
                    peer_hash=peer_hash,
                    message_id=msg_id,
                    content=content,
                    timestamp=timestamp,
                    status=status,
                    is_outgoing=is_outgoing,
                    metadata={
                        "delivery_method": delivery_method,
                        "signature_valid": signature_valid,
                        "transport_encrypted": transport_encrypted,
                        "fields": fields or {},
                    },
                )

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._notification_service.notify(event))
                except RuntimeError:
                    logger.debug("No event loop for notification dispatch")
                return
            except Exception as e:
                logger.warning(f"Notification dispatch failed, falling back: {e}")

        # Fallback: direct IPC broadcast
        if not self._control_server:
            return

        try:
            from styrened.ipc.protocol import IPCMessageType

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

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._control_server.broadcast_event(
                        IPCMessageType.EVENT_MESSAGE, event_payload
                    )
                )
            except RuntimeError:
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

        Dispatches through NotificationService when available.

        Args:
            msg_id: Database message ID
            peer_hash: LXMF hash of the peer
            status: New message status (sent, delivered, failed)
            delivery_method: How message was delivered (direct, propagated, or None)
        """
        # Dispatch through notification service if available
        if self._notification_service is not None:
            try:
                from styrened.services.notifications import NotificationEvent

                event = NotificationEvent(
                    event_type="delivery_status",
                    peer_hash=peer_hash,
                    message_id=msg_id,
                    status=status,
                    is_outgoing=True,
                    metadata={"delivery_method": delivery_method},
                )

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._notification_service.notify(event))
                except RuntimeError:
                    logger.debug("No event loop for notification dispatch")
                return
            except Exception as e:
                logger.warning(f"Notification dispatch failed, falling back: {e}")

        # Fallback: direct IPC broadcast
        if not self._control_server:
            return

        try:
            from styrened.ipc.protocol import IPCMessageType

            event_payload = {
                "event_type": "status_changed",
                "message_id": msg_id,
                "peer_hash": peer_hash,
                "status": status,
                "delivery_method": delivery_method,
            }

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._control_server.broadcast_event(
                        IPCMessageType.EVENT_MESSAGE, event_payload
                    )
                )
            except RuntimeError:
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

            self._rpc_server = RPCServer(
                self._styrene_protocol,
                enable_dangerous_commands=self.config.rpc.allow_command_execution,
                rbac_policy=self.config.rbac,
            )
            self._rpc_server._daemon = self

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

        The handler is always created (even when disabled) so it can be
        toggled at runtime without a daemon restart. The handler itself
        gates on config.auto_reply_mode in handle_message().
        """
        if not self.config.chat.enabled:
            logger.info("Chat disabled in configuration")
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
                config_accessor=lambda: self.config.chat,
                identity=identity,
                router=lxmf_service.router,
                start_time=self._start_time,
                conversation_service=self._conversation_service,
                broadcast_callback=self._broadcast_chat_event,
                event_loop=getattr(self, "_event_loop", None),
            )

            # Register the handler with LXMF service (not directly with router)
            # Use raw_mode=True since AutoReplyHandler expects LXMF.LXMessage
            lxmf_service.register_callback(self._auto_reply_handler.handle_message, raw_mode=True)

            state = self.config.chat.auto_reply_mode.value
            logger.info(
                f"Auto-reply handler registered (mode={state}, "
                f"cooldown: {self.config.chat.auto_reply_cooldown}s)"
            )

        except ImportError as e:
            logger.warning(f"Auto-reply not available: {e}")
        except Exception as e:
            logger.error(f"Failed to start auto-reply: {e}")

    async def _start_page_browser(self) -> None:
        """Start the page browser service for NomadNet page fetching.

        Creates the PageBrowserService which manages outgoing RNS.Links
        to NomadNet nodes for browsing their served pages.  Also starts
        the PageCacheService for write-through caching and saved sites.
        """
        try:
            from styrened.services.page_browser import PageBrowserService
            from styrened.services.page_cache import PageCacheService

            self._page_browser_service = PageBrowserService()
            await self._page_browser_service.start()

            # Start cache service with the message DB engine
            try:
                from styrened.models.messages import init_db

                db_engine = init_db()
                self._page_cache_service = PageCacheService(db_engine)
                self._page_cache_service.set_page_browser(self._page_browser_service)
                await self._page_cache_service.start()
                logger.info("Page cache service started")
            except Exception as e:
                logger.warning(f"Failed to start page cache service: {e}")

            logger.info("Page browser service started")

        except Exception as e:
            logger.error(f"Failed to start page browser service: {e}")

    def _start_page_server(self) -> None:
        """Start the NomadNet page server service.

        The page server creates the ("nomadnetwork", "node") destination
        and serves .mu pages with optional Styrene directive enhancement.
        Skips destination creation if NomadNet already owns it (hub guard).
        """
        if not self.config.page_server.enabled:
            return

        try:
            from styrened.services.page_server import PageServerService

            self._page_server_service = PageServerService(self.config.page_server)
            self._page_server_service.start()

            # Register demo pages if enabled
            if self.config.page_server.demo:
                from styrened.pages.demo_host import register_demo_pages

                register_demo_pages(self._page_server_service)

            logger.info(
                "[METRICS] page_server_started "
                f"owns_destination={self._page_server_service.owns_destination} "
                f"static_pages={len(self._page_server_service.static_pages)}"
            )

        except Exception as e:
            logger.error(f"Failed to start page server: {e}")

    def _stop_page_server(self) -> None:
        """Stop the page server service gracefully."""
        if self._page_server_service:
            try:
                self._page_server_service.stop()
                logger.info("[METRICS] page_server_stopped")
            except Exception as e:
                logger.error(f"Error stopping page server: {e}")
            finally:
                self._page_server_service = None

    async def _start_direct_link(self) -> None:
        """Start the direct data link service and register incoming listener.

        Sets up:
        1. DirectLinkService for outgoing links to peers
        2. ("styrene", "datalink") IN destination for accepting incoming links
        3. Request handlers for /status, /ping, /speedtest on the destination
        4. MeshVPNService for WireGuard tunnel management (if enabled)
        """
        try:
            from styrened.services.direct_link import DirectLinkService

            self._direct_link_service = DirectLinkService()
            await self._direct_link_service.start()

            # Register incoming datalink destination
            self._setup_datalink_destination()

            # Start mesh VPN service if enabled
            await self._start_mesh_vpn()

            logger.info("Direct link service started")
        except Exception as e:
            logger.error(f"Failed to start direct link service: {e}")

    def _datalink_identity_hex(self, remote_identity: Any) -> str:
        """Extract the hex identity hash from a remote RNS.Identity object.

        Returns empty string if the identity is None or has no hash —
        callers treat empty-string identity as unknown/unauthenticated.
        The rate limiter allows unknown identities through; Phase 3 will
        enforce ALLOW_LIST which requires a valid identity on the link.
        """
        try:
            if remote_identity is not None and hasattr(remote_identity, "hash"):
                return remote_identity.hash.hex()
        except Exception:
            pass
        return ""

    def _datalink_rbac_role(self, remote_identity_hex: str) -> int:
        """Resolve the RBAC role for a datalink caller.

        Returns the integer Role value.  Returns Role.NONE (1) on error,
        which is the most restrictive non-blocked default — callers that
        cannot be looked up get no elevated privileges.

        Note: Loading config per-request has low overhead (config is
        typically cached by the OS page cache) and ensures we always
        reflect the latest roster without a restart.
        """
        try:
            from styrened.models.rbac import Role
            rbac = self.config.rbac
            if rbac is None:
                # No RBAC configured — fall back to configured default_role.
                # With default_role=PEER (built-in default), all callers are
                # considered peers.  Operators must set default_role=NONE to
                # make this restrictive.
                return int(Role.PEER)
            return int(rbac.resolve_role(remote_identity_hex))
        except Exception:
            return 1  # Role.NONE

    def _setup_datalink_destination(self) -> None:
        """Register ("styrene", "datalink") destination for incoming links."""
        try:
            import RNS

            from styrened.services.direct_link import DATALINK_APP, DATALINK_ASPECT
            from styrened.services.reticulum import get_operator_identity_object

            identity = get_operator_identity_object()
            if not identity:
                logger.warning("No identity for datalink destination")
                return

            self._datalink_destination = RNS.Destination(
                identity,
                RNS.Destination.IN,
                RNS.Destination.SINGLE,
                DATALINK_APP,
                DATALINK_ASPECT,
            )

            # Register request handlers
            self._datalink_destination.register_request_handler(
                "/status",
                response_generator=self._serve_datalink_status,
                allow=RNS.Destination.ALLOW_ALL,
            )
            self._datalink_destination.register_request_handler(
                "/ping",
                response_generator=self._serve_datalink_ping,
                allow=RNS.Destination.ALLOW_ALL,
            )
            self._datalink_destination.register_request_handler(
                "/speedtest",
                response_generator=self._serve_datalink_speedtest,
                allow=RNS.Destination.ALLOW_ALL,
            )
            self._datalink_destination.register_request_handler(
                "/meta",
                response_generator=self._serve_datalink_meta,
                allow=RNS.Destination.ALLOW_ALL,
            )
            self._datalink_destination.register_request_handler(
                "/info",
                response_generator=self._serve_datalink_info,
                allow=RNS.Destination.ALLOW_ALL,
            )

            # Note: VPN handshake now uses LXMF (StyreneProtocol), not datalink

            # Set link established callback for logging
            self._datalink_destination.set_link_established_callback(
                self._on_datalink_established
            )

            # Announce the datalink destination so remote peers can discover
            # a path to it and establish RNS Links for status/speedtest/etc.
            self._datalink_destination.announce()

            logger.info(
                f"Datalink destination registered and announced: {self._datalink_destination.hash.hex()[:16]}..."
            )
        except Exception as e:
            logger.error(f"Failed to setup datalink destination: {e}")

    async def _start_mesh_vpn(self) -> None:
        """Start the mesh VPN service if enabled in config."""
        try:
            from styrened.services.mesh_vpn import MeshVPNService
            from styrened.services.reticulum import get_operator_identity_object

            vpn_config = getattr(self.config, "mesh_vpn", None)
            if vpn_config is None:
                return

            # Get identity hash from operator identity
            identity = get_operator_identity_object()
            identity_hash = identity.hash.hex() if identity else ""

            self._mesh_vpn_service = MeshVPNService(
                config=vpn_config,
                identity_hash=identity_hash,
            )

            if vpn_config.enable:
                await self._mesh_vpn_service.start(
                    identity_hash=identity_hash,
                )

                # Register LXMF handlers on StyreneProtocol
                if self._styrene_protocol:
                    from styrened.models.styrene_wire import StyreneMessageType
                    self._mesh_vpn_service._styrene_protocol = self._styrene_protocol
                    self._styrene_protocol.register_handler(
                        StyreneMessageType.VPN_HANDSHAKE_REQUEST,
                        self._mesh_vpn_service.handle_handshake_request,
                    )
                    self._styrene_protocol.register_handler(
                        StyreneMessageType.VPN_HANDSHAKE_RESPONSE,
                        self._mesh_vpn_service.handle_handshake_response,
                    )
                    logger.info("VPN handshake handlers registered on StyreneProtocol")
                else:
                    logger.warning("StyreneProtocol not available — VPN handshakes won't work")

                logger.info("Mesh VPN service started")
        except Exception as e:
            logger.error(f"Failed to start mesh VPN: {e}")

    def _on_datalink_established(self, link: Any) -> None:
        """Log when a peer establishes a direct data link to us."""
        logger.info(f"Incoming datalink established (link_id={link.link_id.hex()[:16]}...)")

    def _serve_datalink_status(
        self,
        path: str,
        data: Any,
        request_id: Any,
        link_id: Any,
        remote_identity: Any,
        requested_at: Any,
    ) -> bytes:
        """Serve /status over direct link — RBAC-gated identifiable data.

        Access tiers:
        - MONITOR+ (role ≥ 20): full status (uptime, ip, hostname, disk, etc.)
        - PEER / NONE (role 1–19): non-identifiable meta only (same as /meta)
        - BLOCKED (role 0): empty response

        Rate limited (light tier: 20 req/min).
        This replaces the previous ALLOW_ALL-with-no-gating behaviour.
        """
        identity_hex = self._datalink_identity_hex(remote_identity)
        if not self._datalink_rl.check(identity_hex):
            logger.warning("Datalink /status rate-limited for %s", identity_hex[:16] or "unknown")
            return json.dumps({"error": "rate_limited"}).encode("utf-8")

        role = self._datalink_rbac_role(identity_hex)
        try:
            from styrened.models.rbac import Role
            if role <= int(Role.BLOCKED):
                logger.info("Datalink /status blocked for %s", identity_hex[:16] or "unknown")
                return json.dumps({}).encode("utf-8")
            if role >= int(Role.MONITOR):
                # Full status — caller is a trusted monitor or operator
                status_data = self._rpc_server._gather_status() if self._rpc_server else {}
                logger.debug(
                    "Datalink /status (full) served to %s (role=%d)",
                    identity_hex[:16] or "unknown",
                    role,
                )
                return json.dumps(status_data).encode("utf-8")
            else:
                # PEER/NONE — return only non-identifiable meta (same as /meta)
                meta = self._rpc_server._gather_meta(self.config) if self._rpc_server else {}
                return json.dumps(meta).encode("utf-8")
        except Exception:
            logger.exception("Datalink /status handler error")
            return json.dumps({"error": "internal_error"}).encode("utf-8")

    def _serve_datalink_speedtest(
        self,
        path: str,
        data: Any,
        request_id: Any,
        link_id: Any,
        remote_identity: Any,
        requested_at: Any,
    ) -> bytes:
        """Serve /speedtest — receive payload, return ack with byte count.

        Rate limited (heavy tier: 3 req/min) to prevent bandwidth flooding.
        Payload size is capped at _SPEEDTEST_MAX_PAYLOAD_BYTES to prevent
        memory exhaustion from malicious oversized submissions.
        """
        identity_hex = self._datalink_identity_hex(remote_identity)
        if not self._datalink_rl.check(identity_hex, heavy=True):
            logger.warning(
                "Datalink /speedtest rate-limited for %s", identity_hex[:16] or "unknown"
            )
            return json.dumps({"error": "rate_limited"}).encode("utf-8")

        t0 = time.time()
        raw_bytes = data if data else b""
        if len(raw_bytes) > _SPEEDTEST_MAX_PAYLOAD_BYTES:
            logger.warning(
                "Datalink /speedtest payload too large (%d bytes) from %s — truncating",
                len(raw_bytes),
                identity_hex[:16] or "unknown",
            )
            raw_bytes = raw_bytes[:_SPEEDTEST_MAX_PAYLOAD_BYTES]
        received = len(raw_bytes)
        process_ms = (time.time() - t0) * 1000
        return json.dumps({
            "bytes_received": received,
            "process_ms": process_ms,
            "timestamp": time.time(),
        }).encode("utf-8")

    def _serve_datalink_ping(
        self,
        path: str,
        data: Any,
        request_id: Any,
        link_id: Any,
        remote_identity: Any,
        requested_at: Any,
    ) -> bytes:
        """Serve /ping request over direct link.

        Rate limited (light tier: 20 req/min).
        """
        identity_hex = self._datalink_identity_hex(remote_identity)
        if not self._datalink_rl.check(identity_hex):
            return json.dumps({"error": "rate_limited"}).encode("utf-8")
        return json.dumps({"pong": True, "timestamp": time.time()}).encode("utf-8")

    def _serve_datalink_meta(
        self,
        path: str,
        data: Any,
        request_id: Any,
        link_id: Any,
        remote_identity: Any,
        requested_at: Any,
    ) -> bytes:
        """Serve /meta — non-identifiable node metadata.

        Safe to serve to any caller (no identity or RBAC required).
        Returns styrene_version, profile, capabilities, arch, os_id.
        Deliberately excludes hostname, IP, uptime, disk, operator identity.

        Rate limited (light tier: 20 req/min) to prevent stat-flooding.
        """
        identity_hex = self._datalink_identity_hex(remote_identity)
        if not self._datalink_rl.check(identity_hex):
            return json.dumps({"error": "rate_limited"}).encode("utf-8")

        try:
            meta = self._rpc_server._gather_meta(self.config) if self._rpc_server else {}
        except Exception:
            logger.exception("Datalink /meta handler error")
            meta = {}
        return json.dumps(meta).encode("utf-8")

    def _serve_datalink_info(
        self,
        path: str,
        data: Any,
        request_id: Any,
        link_id: Any,
        remote_identity: Any,
        requested_at: Any,
    ) -> bytes:
        """Serve /info — opt-in operator identification.

        Returns name and operator_label only when discovery.info_respond=True.
        Silently returns {} when declined — this is intentional and not an error.
        The caller cannot distinguish "node declined" from "node doesn't support /info".

        Rate limited (light tier: 20 req/min).

        Phase 3 TODO: also gate /info on RBAC role of the requester — only
        PEER+ should receive the identity response even when info_respond=True.
        """
        identity_hex = self._datalink_identity_hex(remote_identity)
        if not self._datalink_rl.check(identity_hex):
            return json.dumps({"error": "rate_limited"}).encode("utf-8")

        try:
            if not self.config.discovery.info_respond:
                return json.dumps({}).encode("utf-8")
            info = self._rpc_server._gather_info(self.config) if self._rpc_server else {}
            if info:
                logger.debug(
                    "Datalink /info served to %s", identity_hex[:16] or "unknown"
                )
        except Exception:
            logger.exception("Datalink /info handler error")
            info = {}
        return json.dumps(info).encode("utf-8")

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
            from styrened.web import create_app

            fastapi_app = create_app(self)
            self._web_app = fastapi_app

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

    def _init_notification_service(self) -> None:
        """Initialize the notification service with appropriate backends.

        Creates NotificationService and registers:
        - IPCEventBackend if control server is running
        - CallbackBackend always (for TUI/GUI embedding)
        - SSE backend if web API is running
        """
        try:
            from styrened.services.notifications import (
                CallbackBackend,
                IPCEventBackend,
                NotificationService,
            )

            self._notification_service = NotificationService(
                config=self.config.notifications
            )

            # Always add callback backend for TUI/GUI embedding
            self._callback_backend = CallbackBackend()
            self._notification_service.add_backend(self._callback_backend)

            # Add IPC event backend if control server is running
            if self._control_server is not None:
                ipc_backend = IPCEventBackend(self._control_server)
                self._notification_service.add_backend(ipc_backend)

            # Add SSE backend if web API is running
            if self._api_server is not None:
                app = getattr(self, "_web_app", None)
                if app is not None:
                    try:
                        from styrened.services.notifications import (
                            NotificationBackend,
                        )
                        from styrened.services.notifications import (
                            NotificationEvent as _NotificationEvent,
                        )
                        from styrened.web.events import SSEBroadcaster

                        broadcaster: SSEBroadcaster = app.state.broadcaster

                        class SSENotificationBackend(NotificationBackend):
                            """Inline backend bridging to SSE broadcaster."""

                            def __init__(self, sse_broadcaster: SSEBroadcaster) -> None:
                                self._broadcaster = sse_broadcaster

                            async def dispatch(
                                self, event: _NotificationEvent
                            ) -> bool:
                                self._broadcaster.broadcast_message_event(
                                    {
                                        "event_type": event.event_type,
                                        "message_id": event.message_id,
                                        "peer_hash": event.peer_hash,
                                        "content": event.content,
                                        "timestamp": event.timestamp,
                                        "status": event.status,
                                        "is_outgoing": event.is_outgoing,
                                    }
                                )
                                return True

                        sse_backend = SSENotificationBackend(broadcaster)
                        self._notification_service.add_backend(sse_backend)
                    except Exception:
                        pass  # Web module not available

            logger.info("Notification service initialized")

        except Exception as e:
            logger.error(f"Failed to initialize notification service: {e}")

    def _build_announce_data(self) -> bytes:
        """Build announce app_data bytes from current config.

        Format: styrene:{display_name}:{version}:{caps}:{lxmf_dest}:{short_name}:{sys_fingerprint}

        Returns:
            Encoded announce app_data.
        """
        import socket

        from styrened import __version__
        from styrened.services.system_info import get_system_fingerprint

        hostname = socket.gethostname()
        version = __version__
        capabilities = []
        if self.config.reticulum.mode.value == "hub":
            capabilities.append("hub")
        if self.config.api.enabled:
            capabilities.append("api")
        if self.config.page_server.enabled:
            capabilities.append("pages")
        from styrened.models.config import AutoReplyMode

        if self.config.chat.auto_reply_mode != AutoReplyMode.DISABLED:
            capabilities.append("autoreply")

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

        short_name = self.config.identity.short_name or ""
        fingerprint = get_system_fingerprint()

        # Include NomadNet page destination hash so remote TUIs can show
        # a Pages tab. Two sources:
        # 1. styrened's own page server is running (edge mode or bridge mode)
        # 2. NomadNet is installed and has an identity file (hub co-location)
        nomadnet_dest = ""
        try:
            # Check if styrened's page server owns the destination
            if self._page_server_service and self._page_server_service.is_started:
                if self._page_server_service.owns_destination:
                    dest = self._page_server_service._destination
                    if dest:
                        nomadnet_dest = dest.hash.hex()

            # If no page server destination, probe for NomadNet's identity file
            if not nomadnet_dest:
                from pathlib import Path

                import RNS

                nn_identity_paths = [
                    Path.home() / ".nomadnetwork" / "storage" / "identity",
                    Path.home() / ".config" / "nomadnetwork" / "storage" / "identity",
                    Path("/etc/nomadnetwork/storage/identity"),
                    # Container paths
                    Path("/app/.nomadnetwork/storage/identity"),
                ]
                for path in nn_identity_paths:
                    if path.exists():
                        nn_identity = RNS.Identity.from_file(str(path))
                        if nn_identity:
                            nn_dest_hash = RNS.Destination.hash(
                                nn_identity, "nomadnetwork", "node"
                            )
                            nomadnet_dest = nn_dest_hash.hex()
                            if "pages" not in capabilities:
                                capabilities.append("pages")
                            break
        except Exception as e:
            logger.debug(f"Could not resolve NomadNet destination: {e}")

        caps_str = ",".join(capabilities) if capabilities else "node"
        return f"styrene:{display_name}:{version}:{caps_str}:{lxmf_dest}:{short_name}:{fingerprint}:{nomadnet_dest}".encode()

    def _announce(self) -> None:
        """Trigger an announce of the local operator destination.

        Called by IPC handlers and the main loop.
        """
        if not self._operator_destination:
            logger.warning("Cannot announce: no operator destination")
            return

        try:
            app_data = self._build_announce_data()
            self._operator_destination.announce(app_data=app_data)

            # Extract display_name for logging
            display_name = app_data.decode("utf-8").split(":")[1]
            logger.info(f"Announced as Styrene node: {display_name}")

            try:
                from styrened.web.metrics import announces_total

                announces_total.labels(result="success").inc()
            except ImportError:
                pass

            # Emit activity event for dashboard feed
            self._emit_activity_event("announce_sent")

            # Also announce LXMF delivery destination
            try:
                from styrened.services.lxmf_service import get_lxmf_service

                lxmf_service = get_lxmf_service()
                if (
                    lxmf_service.is_initialized
                    and lxmf_service.router
                    and lxmf_service.delivery_destination
                ):
                    # Sync display_name onto the LXMF delivery destination so
                    # the router's announce app_data reflects the current config.
                    # register_delivery_identity() only sets this once at init;
                    # without this, identity changes never propagate to LXMF peers.
                    lxmf_service.delivery_destination.display_name = (
                        f"[styrene] {self.config.identity.display_name}"
                    )
                    lxmf_service.router.announce(lxmf_service.delivery_destination.hash)
                    logger.debug("Announced LXMF delivery destination")
            except Exception as e:
                logger.warning(f"LXMF announce failed: {e}")

            # Re-announce datalink destination so paths stay fresh
            if self._datalink_destination:
                try:
                    self._datalink_destination.announce()
                except Exception as e:
                    logger.debug(f"Datalink announce failed: {e}")

        except Exception as e:
            logger.warning(f"Announce failed: {e}")
            try:
                from styrened.web.metrics import announces_total

                announces_total.labels(result="failure").inc()
            except ImportError:
                pass

    async def _run_loop(self) -> None:
        """Main daemon loop with periodic announces."""
        announce_interval = self.config.reticulum.announce_interval
        logger.info(f"Starting run loop with announce_interval={announce_interval}s")

        # Announce immediately on startup so peers discover us without
        # waiting for the first interval to elapse.
        try:
            if self._operator_destination:
                self._announce()
                logger.info("Initial announce sent on startup")
        except Exception as e:
            logger.warning(f"Initial announce failed: {e}")

        # Eager discovery: re-announce at short intervals for the first
        # 2 minutes so newly-connected peers see us quickly, then fall
        # back to the normal interval.  Also re-enters eager mode after
        # network reconnection (startup_time is reset by reconnect handler).
        eager_interval = 15  # seconds
        eager_duration = 120  # seconds
        import time as _time
        self._eager_start_time = _time.monotonic()

        while self._running:
            elapsed = _time.monotonic() - self._eager_start_time
            if elapsed < eager_duration:
                sleep_time = eager_interval
            else:
                sleep_time = announce_interval
            logger.debug(f"Run loop sleeping for {sleep_time}s...")
            await asyncio.sleep(sleep_time)
            logger.info(f"Run loop woke up, _running={self._running}")

            # Re-announce presence using _announce() (shared with IPC/API)
            try:
                # Use cached destination if available, otherwise try to recover
                if self._operator_destination is None:
                    logger.debug("No cached destination, attempting recovery")
                    self._init_operator_destination()

                self._announce()

            except Exception as e:
                logger.warning(f"Re-announce failed: {e}")
                try:
                    from styrened.web.metrics import announces_total

                    announces_total.labels(result="failure").inc()
                except ImportError:
                    pass

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

            # Check for PQC session rekeying
            if self._pqc_service:
                try:
                    await self._pqc_service.check_rekey()
                except Exception as e:
                    logger.warning(f"PQC rekey check failed: {e}")

            # Periodic attachment storage budget enforcement
            try:
                from styrened.services.attachment_store import get_attachment_store

                get_attachment_store().enforce_budget()
            except Exception as e:
                logger.debug(f"Attachment budget enforcement skipped: {e}")

    async def stop(self) -> None:
        """Stop the daemon services."""
        logger.info("Stopping Styrene daemon...")
        self._running = False

        # Stop terminal service (closes all sessions)
        self._stop_terminal_service()

        # Stop mesh VPN service
        if self._mesh_vpn_service:
            try:
                await self._mesh_vpn_service.stop()
            except Exception as e:
                logger.error(f"Error stopping mesh VPN service: {e}")
            self._mesh_vpn_service = None

        # Stop direct link service
        if self._direct_link_service:
            try:
                await self._direct_link_service.stop()
            except Exception as e:
                logger.error(f"Error stopping direct link service: {e}")
            self._direct_link_service = None

        # Stop page server service
        self._stop_page_server()

        # Stop page cache service
        if self._page_cache_service:
            try:
                await self._page_cache_service.stop()
            except Exception as e:
                logger.error(f"Error stopping page cache service: {e}")
            self._page_cache_service = None

        # Stop page browser service
        if self._page_browser_service:
            try:
                await self._page_browser_service.stop()
            except Exception as e:
                logger.error(f"Error stopping page browser service: {e}")
            self._page_browser_service = None

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
