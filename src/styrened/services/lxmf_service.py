"""LXMF service for fleet RPC communication.

This module provides a singleton LXMFService for managing the LXMF
(Lightweight eXtensible Message Format) messaging protocol in headless
and TUI applications.

The service handles:
- Initializing LXMF router with RNS identity
- Sending messages to destination hashes
- Receiving messages via callbacks
- Graceful shutdown and cleanup

Usage:
    from styrened.services.lxmf_service import get_lxmf_service
    from styrened.services.reticulum import get_operator_identity_object

    # Initialize LXMF on app startup
    service = get_lxmf_service()
    identity = get_operator_identity_object()
    if identity and not service.initialize(identity):
        logger.error("Failed to initialize LXMF")

    # Register callback for incoming messages
    def handle_message(source_hash: str, payload: dict):
        logger.info(f"Received message from {source_hash}: {payload}")

    service.register_callback(handle_message)

    # Send message
    service.send_message(
        destination_hash="a1b2c3d4e5f6",
        payload={"type": "status_request"}
    )

    # Shutdown on app exit
    service.shutdown()
"""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from styrened.models.config import LXMFConfig

import platformdirs

try:
    import LXMF
    import RNS

    LXMF_AVAILABLE = True
except ImportError:
    LXMF_AVAILABLE = False

from styrened.services.rns_service import get_rns_service


class DeliveryMethod:
    """LXMF delivery method constants."""

    DIRECT = "direct"
    PROPAGATED = "propagated"
    AUTO = "auto"


class SendMessageResult(TypedDict):
    """Result of send_message operation."""

    hash: bytes
    method: str  # DeliveryMethod.DIRECT or DeliveryMethod.PROPAGATED
    destination_hash: str  # Full 32-char hex LXMF destination hash


# Setup logger
logger = logging.getLogger(__name__)

# Singleton instance
_lxmf_service: "LXMFService | None" = None


class LXMFService:
    """Singleton service for managing LXMF lifecycle.

    This service manages the initialization and cleanup of the LXMF router
    instance. It ensures only one instance is created and provides helpers
    for sending and receiving messages.
    """

    def __init__(self) -> None:
        """Initialize the LXMFService (not the LXMF router yet)."""
        self._router: LXMF.LXMRouter | None = None
        self._identity: RNS.Identity | None = None
        self._delivery_destination: RNS.Destination | None = None
        self._initialized = False
        # Support multiple callbacks - list of (callback, raw_mode) tuples
        # raw_mode=True means callback receives raw LXMF.LXMessage
        # raw_mode=False means callback receives (source_hash, payload_dict)
        self._message_callbacks: list[tuple[Callable, bool]] = []

    @property
    def is_initialized(self) -> bool:
        """Check if LXMF is initialized.

        Returns:
            True if LXMF router instance is created and ready.
        """
        return self._initialized and self._router is not None

    @property
    def router(self) -> "LXMF.LXMRouter | None":
        """Get the LXMF router instance.

        Returns:
            LXMF.LXMRouter instance, or None if not initialized.
        """
        return self._router

    @property
    def delivery_destination(self) -> "RNS.Destination | None":
        """Get the LXMF delivery destination.

        Returns:
            RNS.Destination for LXMF delivery, or None if not initialized.
        """
        return self._delivery_destination

    # Alias for backward compatibility
    @property
    def _destination(self) -> "RNS.Destination | None":
        """Alias for delivery_destination (backward compatibility)."""
        return self._delivery_destination

    def initialize(
        self,
        identity: "RNS.Identity",
        lxmf_config: "LXMFConfig | None" = None,
        display_name: str | None = None,
    ) -> bool:
        """Initialize LXMF router instance.

        This creates the LXMF router instance which handles message
        routing and delivery over the Reticulum network.

        Args:
            identity: RNS.Identity to use for the router.
            lxmf_config: Optional LXMFConfig with propagation and peer settings.
            display_name: Display name for LXMF announces. When set, the delivery
                         destination will include this name in announces using the
                         standard LXMF msgpack format [name, stamp_cost]. This enables
                         proper display in ecosystem clients (Sideband, NomadNet, MeshChat).

        Returns:
            True if initialization succeeded, False otherwise.
        """
        # If already initialized, return success
        if self._initialized and self._router is not None:
            logger.debug("LXMF already initialized")
            return True

        if not LXMF_AVAILABLE:
            logger.error("LXMF library not available")
            return False

        # Ensure RNS is initialized
        rns_service = get_rns_service()
        if not rns_service.is_initialized:
            logger.error("RNS must be initialized before LXMF")
            return False

        try:
            # Get LXMF storage path
            data_dir = platformdirs.user_data_dir("styrene", "styrene-lab")
            lxmf_storage = Path(data_dir) / "lxmf"
            lxmf_storage.mkdir(parents=True, exist_ok=True)

            logger.info(f"Initializing LXMF with storage: {lxmf_storage}")

            # Build router kwargs from config
            router_kwargs: dict[str, Any] = {
                "identity": identity,
                "storagepath": str(lxmf_storage),
            }

            # Apply config if provided
            if lxmf_config is not None:
                # Peer management
                router_kwargs["autopeer"] = lxmf_config.autopeer
                router_kwargs["autopeer_maxdepth"] = lxmf_config.autopeer_maxdepth
                router_kwargs["max_peers"] = lxmf_config.max_peers
                router_kwargs["from_static_only"] = lxmf_config.from_static_only

                # Sync limits
                router_kwargs["propagation_limit"] = lxmf_config.propagation_limit
                router_kwargs["sync_limit"] = lxmf_config.sync_limit
                router_kwargs["delivery_limit"] = lxmf_config.delivery_limit

                # Static peers
                if lxmf_config.static_peers:
                    router_kwargs["static_peers"] = [
                        bytes.fromhex(p) for p in lxmf_config.static_peers
                    ]

                # Propagation node mode cost settings
                if lxmf_config.propagation_node.enabled:
                    router_kwargs["propagation_cost"] = lxmf_config.propagation_cost
                    router_kwargs["propagation_cost_flexibility"] = (
                        lxmf_config.propagation_cost_flexibility
                    )
                    router_kwargs["peering_cost"] = lxmf_config.peering_cost
                    router_kwargs["max_peering_cost"] = lxmf_config.max_peering_cost
                    if lxmf_config.propagation_node.name:
                        router_kwargs["name"] = lxmf_config.propagation_node.name

                logger.info(
                    f"LXMF config: autopeer={lxmf_config.autopeer}, "
                    f"max_peers={lxmf_config.max_peers}, "
                    f"propagation_node={lxmf_config.propagation_node.enabled}"
                )

            # Create LXMF router
            # TODO(upstream): LXMRouter.process_deferred_stamps() throws TypeError when
            # RNS.Transport.identity is None. Triggered by propagated delivery which spawns
            # a background thread calling get_outbound_propagation_cost() -> request_path().
            # The root cause is that LXMF's get_outbound_propagation_cost() doesn't check
            # if Transport.identity is initialized before calling Transport.request_path().
            # Error: TypeError: unsupported operand type(s) for +: 'NoneType' and 'bytes'
            # at RNS/Transport.py:2556. We cannot catch this - it's in LXMF's internal thread.
            # The daemon continues running but errors pollute logs. This needs an upstream
            # fix in LXMF to guard against None identity. See: https://github.com/markqvist/LXMF
            self._router = LXMF.LXMRouter(**router_kwargs)

            # Set outbound propagation node if configured
            if lxmf_config is not None and lxmf_config.propagation_destination:
                try:
                    dest_bytes = bytes.fromhex(lxmf_config.propagation_destination)
                    self._router.set_outbound_propagation_node(dest_bytes)
                    logger.info(
                        f"Set outbound propagation node: "
                        f"{lxmf_config.propagation_destination[:16]}..."
                    )
                except Exception as e:
                    logger.warning(f"Failed to set propagation destination: {e}")

            # Enable propagation node mode if configured
            if lxmf_config is not None and lxmf_config.propagation_node.enabled:
                self._router.enable_propagation()
                logger.info("Enabled propagation node mode")

            # Register our identity for receiving messages - this creates the actual
            # delivery destination that will receive incoming LXMF messages
            # Pass display_name to register_delivery_identity for proper LXMF announce format
            self._delivery_destination = self._router.register_delivery_identity(
                identity, display_name=display_name
            )

            # Log the display_name setting for debugging ecosystem compatibility
            if display_name:
                logger.info(f"LXMF delivery destination display_name set to: {display_name}")

            # Register message received callback
            self._router.register_delivery_callback(self._handle_lxmf_message)

            self._identity = identity
            self._initialized = True

            # Register for reconnection events to clear LXMF state on LocalInterface drop
            rns_service.register_reconnect_callback(self._handle_reconnection)

            # Announce our LXMF delivery destination so others can send to us
            self._router.announce(self._delivery_destination.hash)
            logger.info(
                f"LXMF initialized and announced (delivery: {self._delivery_destination.hexhash[:16]}...)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to initialize LXMF: {e}")
            self._router = None
            self._identity = None
            self._initialized = False
            return False

    def _ensure_path(self, destination_hash: bytes) -> bool:
        """Check if path exists to destination, request if missing.

        Args:
            destination_hash: Raw bytes of the destination hash.

        Returns:
            True if path exists, False if path was requested (not yet available).
        """
        if RNS.Transport.has_path(destination_hash):
            logger.debug(f"Path exists to {destination_hash.hex()[:16]}...")
            return True

        logger.info(f"No path to {destination_hash.hex()[:16]}..., requesting path")
        RNS.Transport.request_path(destination_hash)
        return False

    def send_message(
        self,
        destination_hash: str,
        payload: dict[str, object],
        on_delivery: "Callable[[LXMF.LXMessage], None] | None" = None,
        on_failed: "Callable[[LXMF.LXMessage], None] | None" = None,
        delivery_method: str = DeliveryMethod.AUTO,
        lxmf_fields: dict[int, Any] | None = None,
    ) -> "SendMessageResult | None":
        """Send LXMF message to destination.

        This method handles the complexity of looking up the correct identity
        for sending messages. The destination_hash can be:
        1. An operator destination hash (styrene_node:operator)
        2. An LXMF delivery destination hash (lxmf:delivery)
        3. An identity hash (direct public key hash)

        We try multiple lookup strategies to find the identity needed for sending.

        Args:
            destination_hash: Hex-encoded destination hash string. Can be:
                            - Operator destination hash (from device discovery)
                            - LXMF destination hash (from announce app_data)
                            - Identity hash (direct identity lookup)
            payload: JSON-serializable message payload.
            on_delivery: Optional callback invoked when message is delivered.
            on_failed: Optional callback invoked when delivery fails.
            delivery_method: Delivery method to use. One of:
                            - DeliveryMethod.DIRECT: Direct delivery only
                            - DeliveryMethod.PROPAGATED: Store-and-forward via propagation nodes
                            - DeliveryMethod.AUTO: Try direct first, fall back to propagated
            lxmf_fields: Optional dict of LXMF fields (integer keys like FIELD_RENDERER,
                        FIELD_THREAD) to include in the message. These are standard LXMF
                        fields that enable ecosystem interoperability.

        Returns:
            SendMessageResult dict with 'hash' (bytes) and 'method' (str) if queued
            successfully, None otherwise. The hash can be used to correlate delivery
            callbacks.
        """
        if not self.is_initialized or self._router is None or self._identity is None:
            logger.warning("Cannot send message: LXMF not initialized")
            return None

        try:
            dest_identity = self._resolve_identity(destination_hash)

            if dest_identity is None:
                logger.warning(
                    f"[HASH] Cannot send to {destination_hash[:16]}...: identity not known. "
                    "Destination must announce before receiving messages. "
                    "Check that the target node has announced its LXMF destination."
                )
                return None

            # Create outbound LXMF delivery destination
            dest_destination = RNS.Destination(
                dest_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                LXMF.APP_NAME,
                "delivery",
            )

            logger.debug(
                f"[HASH] Created LXMF destination: "
                f"lxmf_dest={dest_destination.hash.hex()[:16]}... "
                f"(from identity {dest_identity.hash.hex()[:16]}...)"
            )

            # Check path availability (used for delivery method selection)
            # Note: We no longer block here - propagated delivery can work without direct path
            has_direct_path = self._ensure_path(dest_destination.hash)

            # For explicit direct delivery without a path, warn but don't block
            # (the LXMF library will handle the failure)
            if delivery_method == DeliveryMethod.DIRECT and not has_direct_path:
                logger.warning(
                    f"No direct path to {dest_destination.hash.hex()[:16]}... "
                    "Direct delivery requested but may fail. "
                    "Consider using 'auto' or 'propagated' delivery method."
                )

            # Create our source destination for signing
            source_destination = RNS.Destination(
                self._identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                LXMF.APP_NAME,
                "delivery",
            )

            # Serialize payload to JSON
            content = json.dumps(payload).encode("utf-8")

            # Build LXMF fields dict for ecosystem interoperability
            # Start with provided fields or empty dict
            fields: dict[int, Any] = lxmf_fields.copy() if lxmf_fields else {}

            # Default to plain text renderer if not specified (FIELD_RENDERER = 0x0F)
            # This helps ecosystem clients (Sideband, NomadNet, MeshChat) render correctly
            if LXMF.FIELD_RENDERER not in fields:
                fields[LXMF.FIELD_RENDERER] = LXMF.RENDERER_PLAIN

            # Create LXMF message with proper destination objects and fields
            message = LXMF.LXMessage(
                destination=dest_destination,
                source=source_destination,
                content=content,
                fields=fields if fields else None,
            )

            # Set native LXMF title for ecosystem compatibility (MeshChat/Sideband)
            if isinstance(payload, dict) and payload.get("title"):
                message.title = str(payload["title"])
                logger.debug(f"[LXMF] Set native title: {message.title[:50]}...")

            # Determine and set delivery method
            # LXMF constants: DIRECT = 2, PROPAGATED = 3
            method_used = DeliveryMethod.DIRECT  # Default

            if delivery_method == DeliveryMethod.PROPAGATED:
                # Force propagated delivery
                message.desired_method = LXMF.LXMessage.PROPAGATED
                method_used = DeliveryMethod.PROPAGATED
                logger.debug(
                    f"[DELIVERY] Using propagated delivery for {dest_destination.hash.hex()[:16]}..."
                )
            elif delivery_method == DeliveryMethod.DIRECT:
                # Force direct delivery
                message.desired_method = LXMF.LXMessage.DIRECT
                method_used = DeliveryMethod.DIRECT
                logger.debug(
                    f"[DELIVERY] Using direct delivery for {dest_destination.hash.hex()[:16]}..."
                )
            else:
                # AUTO mode: try direct if path exists, otherwise propagated
                if has_direct_path:
                    message.desired_method = LXMF.LXMessage.DIRECT
                    method_used = DeliveryMethod.DIRECT
                    logger.debug(
                        f"[DELIVERY] Auto mode: using direct delivery (path exists) for "
                        f"{dest_destination.hash.hex()[:16]}..."
                    )
                else:
                    message.desired_method = LXMF.LXMessage.PROPAGATED
                    method_used = DeliveryMethod.PROPAGATED
                    logger.debug(
                        f"[DELIVERY] Auto mode: using propagated delivery (no direct path) for "
                        f"{dest_destination.hash.hex()[:16]}..."
                    )

            # Register delivery callbacks if provided
            if on_delivery is not None:
                message.register_delivery_callback(on_delivery)
            if on_failed is not None:
                message.register_failed_callback(on_failed)

            # Send via router - this computes the message hash
            self._router.handle_outbound(message)

            # Get the message hash after sending (LXMF computes it during handle_outbound)
            message_hash: bytes = message.hash if message.hash else b""

            if message_hash:
                logger.info(
                    f"[HASH] Sent LXMF message to {dest_destination.hash.hex()[:16]}... "
                    f"(type={payload.get('type')}, protocol={payload.get('protocol')}, "
                    f"method={method_used}, msg_hash={message_hash.hex()[:16]}...)"
                )
            else:
                logger.info(
                    f"[HASH] Queued LXMF message to {dest_destination.hash.hex()[:16]}... "
                    f"(type={payload.get('type')}, protocol={payload.get('protocol')}, "
                    f"method={method_used})"
                )

            return SendMessageResult(
                hash=message_hash,
                method=method_used,
                destination_hash=dest_destination.hash.hex(),
            )

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return None

    def _resolve_identity(self, destination_hash: str) -> "RNS.Identity | None":
        """Resolve a destination hash to an RNS Identity.

        This method implements a multi-strategy lookup to find the identity:
        1. Try direct RNS.Identity.recall() with destination_hash
        2. Try NodeStore lookup by operator destination hash
        3. Try NodeStore lookup by LXMF destination hash
        4. Try direct identity hash recall (from_identity_hash=True)

        Args:
            destination_hash: Hex-encoded hash (could be destination or identity).

        Returns:
            RNS.Identity if found, None otherwise.
        """
        dest_bytes = bytes.fromhex(destination_hash)

        # Strategy 1: Direct recall (RNS may have it from announce processing)
        dest_identity = RNS.Identity.recall(dest_bytes)
        if dest_identity:
            logger.debug(
                f"[HASH] Strategy 1 success: direct recall({destination_hash[:16]}...) -> "
                f"identity_hash={dest_identity.hash.hex()[:16]}..."
            )
            return dest_identity

        logger.debug(f"[HASH] Strategy 1 failed: direct recall({destination_hash[:16]}...) -> None")

        # Strategy 2 & 3: NodeStore lookup
        identity_hash = None
        try:
            from styrened.services.node_store import get_node_store

            store = get_node_store()

            # Strategy 2: Try operator destination hash
            identity_hash = store.get_identity_for_destination(destination_hash)
            if identity_hash:
                logger.debug(
                    f"[HASH] Strategy 2 success: operator_dest lookup -> "
                    f"identity_hash={identity_hash[:16]}..."
                )
            else:
                logger.debug(
                    f"[HASH] Strategy 2 failed: no identity for dest {destination_hash[:16]}..."
                )

            # Strategy 3: Try LXMF destination hash
            if not identity_hash:
                identity_hash = store.get_identity_for_lxmf_destination(destination_hash)
                if identity_hash:
                    logger.debug(
                        f"[HASH] Strategy 3 success: lxmf_dest lookup -> "
                        f"identity_hash={identity_hash[:16]}..."
                    )
                else:
                    logger.debug(
                        f"[HASH] Strategy 3 failed: no identity for lxmf_dest {destination_hash[:16]}..."
                    )

        except Exception as e:
            logger.warning(f"[HASH] NodeStore lookup failed: {e}")

        # If we found an identity hash in NodeStore, recall it
        if identity_hash:
            identity_bytes = bytes.fromhex(identity_hash)
            # MUST use from_identity_hash=True since this is an identity hash
            dest_identity = RNS.Identity.recall(identity_bytes, from_identity_hash=True)
            if dest_identity:
                logger.info(
                    f"[HASH] Identity resolved: destination={destination_hash[:16]}... -> "
                    f"identity_hash={identity_hash[:16]}... -> Identity OK"
                )
                return dest_identity
            else:
                # RNS cache doesn't have it - try to load from persistent storage
                # RNS stores identity files in ~/.reticulum/storage/identities/
                logger.debug(
                    f"[HASH] NodeStore had identity_hash={identity_hash[:16]}... "
                    f"but RNS cache empty. Trying persistent storage..."
                )
                dest_identity = self._load_identity_from_storage(identity_hash)
                if dest_identity:
                    logger.info(f"[HASH] Identity loaded from storage: {identity_hash[:16]}...")
                    return dest_identity
                else:
                    logger.warning(
                        f"[HASH] NodeStore had identity_hash={identity_hash[:16]}... "
                        f"but identity not in RNS cache or storage. "
                        f"Target node must re-announce."
                    )

        # Strategy 4: Maybe destination_hash IS the identity hash
        dest_identity = RNS.Identity.recall(dest_bytes, from_identity_hash=True)
        if dest_identity:
            logger.debug(
                f"[HASH] Strategy 4 success: destination WAS identity hash "
                f"({destination_hash[:16]}...)"
            )
            return dest_identity

        logger.debug(
            f"[HASH] All strategies failed for {destination_hash[:16]}... - identity not found"
        )
        return None

    def _load_identity_from_storage(self, identity_hash: str) -> "RNS.Identity | None":
        """Attempt to load an identity from RNS persistent storage.

        RNS stores known identities in ~/.reticulum/storage/identities/.
        This method tries to load an identity file and re-register it with RNS.

        Args:
            identity_hash: Hex-encoded identity hash string.

        Returns:
            RNS.Identity if found and loaded, None otherwise.
        """
        try:
            # RNS stores identities in storage/identities/<hash> under the config path
            # The path is typically ~/.reticulum/storage/identities/
            rns_config_path = (
                RNS.Reticulum.configdir if RNS.Reticulum.configdir else Path.home() / ".reticulum"
            )
            identity_storage_path = Path(rns_config_path) / "storage" / "identities" / identity_hash

            if not identity_storage_path.exists():
                logger.debug(f"[HASH] Identity file not found: {identity_storage_path}")
                return None

            # Load the identity from file
            identity = RNS.Identity.from_file(str(identity_storage_path))
            if identity:
                # Verify the hash matches
                if identity.hash.hex() == identity_hash:
                    logger.debug(f"[HASH] Loaded identity from storage: {identity_hash[:16]}...")
                    return identity
                else:
                    logger.warning(
                        f"[HASH] Identity file hash mismatch: expected {identity_hash[:16]}..., "
                        f"got {identity.hash.hex()[:16]}..."
                    )
                    return None
            else:
                logger.debug(f"[HASH] Failed to load identity from {identity_storage_path}")
                return None

        except Exception as e:
            logger.debug(f"[HASH] Error loading identity from storage: {e}")
            return None

    def send_with_retry(
        self,
        destination_hash: str,
        payload: dict[str, object],
        max_wait: float = 30.0,
        check_interval: float = 2.0,
    ) -> bool:
        """Send LXMF message with retry, waiting for path discovery.

        This method will wait for a path to become available before sending.
        Useful when the destination may not have an established path yet.

        Uses the same multi-strategy identity lookup as send_message().

        Args:
            destination_hash: Hex-encoded destination hash string. Can be:
                            - Operator destination hash (from device discovery)
                            - LXMF destination hash (from announce app_data)
                            - Identity hash (direct identity lookup)
            payload: JSON-serializable message payload.
            max_wait: Maximum time to wait for path discovery (seconds).
            check_interval: Time between path checks (seconds).

        Returns:
            True if message was sent, False if path timeout or other failure.
        """
        if not self.is_initialized or self._router is None or self._identity is None:
            logger.warning("Cannot send message: LXMF not initialized")
            return False

        try:
            # Use shared identity resolution logic
            dest_identity = self._resolve_identity(destination_hash)

            if dest_identity is None:
                logger.warning(
                    f"[HASH] Cannot send to {destination_hash[:16]}...: identity not known. "
                    "Destination must announce before receiving messages. "
                    "Check that the target node has announced its LXMF destination."
                )
                return False

            # Create outbound LXMF delivery destination
            dest_destination = RNS.Destination(
                dest_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                LXMF.APP_NAME,
                "delivery",
            )

            # Wait for path to become available
            logger.info(
                f"[HASH] Waiting for path to LXMF destination: "
                f"lxmf_dest={dest_destination.hash.hex()[:16]}... "
                f"(from identity {dest_identity.hash.hex()[:16]}...)"
            )
            start_time = time.monotonic()
            path_available = self._ensure_path(dest_destination.hash)

            while not path_available and (time.monotonic() - start_time) < max_wait:
                time.sleep(check_interval)
                path_available = RNS.Transport.has_path(dest_destination.hash)
                elapsed = time.monotonic() - start_time
                logger.debug(
                    f"[HASH] Path check: has_path={path_available}, elapsed={elapsed:.1f}s"
                )

            if not path_available:
                logger.warning(
                    f"[HASH] Timeout waiting for path to {dest_destination.hash.hex()[:16]}... "
                    f"after {max_wait}s"
                )
                return False

            logger.debug(
                f"[HASH] Path to {dest_destination.hash.hex()[:16]}... available after "
                f"{time.monotonic() - start_time:.1f}s"
            )

            # Create our source destination for signing
            source_destination = RNS.Destination(
                self._identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                LXMF.APP_NAME,
                "delivery",
            )

            # Serialize payload to JSON
            content = json.dumps(payload).encode("utf-8")

            # Create LXMF message with proper destination objects
            message = LXMF.LXMessage(
                destination=dest_destination,
                source=source_destination,
                content=content,
            )

            # Send via router
            self._router.handle_outbound(message)

            logger.info(
                f"[HASH] Sent LXMF message (with retry) to {dest_destination.hash.hex()[:16]}... "
                f"(type={payload.get('type')}, protocol={payload.get('protocol')})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    def register_callback(
        self,
        callback: Callable[..., None],
        raw_mode: bool = False,
    ) -> None:
        """Register callback for incoming messages.

        Multiple callbacks can be registered - all will be invoked for each message.

        Args:
            callback: Function to call when message received.
                     If raw_mode=False: called with (source_hash: str, payload: dict)
                     If raw_mode=True: called with (LXMF.LXMessage)
            raw_mode: If True, callback receives raw LXMF.LXMessage instead of
                     parsed (source_hash, payload) tuple.
        """
        self._message_callbacks.append((callback, raw_mode))
        logger.debug(
            f"Registered message callback (raw_mode={raw_mode}), total: {len(self._message_callbacks)}"
        )

    def _handle_reconnection(self) -> None:
        """Handle RNS interface reconnection by clearing LXMF state.

        Called by RNSService when a LocalInterface reconnects after disconnect.
        Clears cached delivery destination to prevent "already registered" errors
        when LXMF router tries to re-register on next operation.
        """
        logger.info("[RECONNECT] LXMF handling interface reconnection")

        # Clear the cached delivery destination - it's now stale
        if self._delivery_destination is not None:
            old_hash = self._delivery_destination.hexhash[:16]
            self._delivery_destination = None
            logger.info(f"[RECONNECT] Cleared stale LXMF delivery destination: {old_hash}...")

        # Note: We don't clear the router itself - it should handle reconnection
        # internally. If we need to reinitialize, the daemon will need to restart.

        # The next announce or message send will need to re-register the destination
        logger.info("[RECONNECT] LXMF reconnection handling complete")

    def _normalize_message_payload(self, message: "LXMF.LXMessage") -> dict[str, Any] | None:
        """Normalize LXMF message content into a payload dict.

        Handles both JSON payloads (from styrened/internal protocols) and plain
        text messages (from Sideband, NomadNet, MeshChat, and other LXMF clients).

        For plain text messages, creates a normalized payload:
            {"type": "chat", "content": "<text>", "protocol": ""}

        For JSON messages, returns the parsed dict as-is.

        Args:
            message: LXMF.LXMessage instance.

        Returns:
            Normalized payload dict, or None if content cannot be decoded.
        """
        if not message.content:
            return None

        try:
            content = message.content.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.debug(f"LXMF message content is not UTF-8: {e}")
            return None

        # Try JSON first (styrened internal protocol)
        try:
            payload = json.loads(content)
            if isinstance(payload, dict):
                return payload
            # JSON but not a dict (e.g., plain string in JSON quotes)
            # Fall through to plain text handling
        except json.JSONDecodeError:
            pass

        # Plain text message (Sideband/NomadNet/MeshChat compatibility)
        # Normalize to a payload dict for consistent callback handling
        fields = message.fields or {}
        protocol = fields.get("protocol", "")

        # Extract title if present (LXMF standard field)
        title = None
        if hasattr(message, "title") and message.title:
            title = str(message.title)
        elif fields.get("title"):
            title = str(fields["title"])

        payload = {
            "type": "chat",
            "content": content,
            "protocol": protocol,  # May be empty for Sideband
        }

        if title:
            payload["title"] = title

        logger.debug(
            f"Normalized plain text LXMF message: {len(content)} chars, "
            f"protocol={protocol or 'none'}"
        )

        return payload

    def _handle_lxmf_message(self, message: "LXMF.LXMessage") -> None:
        """Handle incoming LXMF message.

        This is called by the LXMF router when a message is received.
        Dispatches to all registered callbacks.

        Args:
            message: LXMF.LXMessage instance.
        """
        if not self._message_callbacks:
            logger.warning("No message callbacks registered - message will be dropped")
            return

        # Extract source hash for logging
        source_hash = message.source_hash.hex()

        # Normalize message content for non-raw callbacks
        # Handles both JSON payloads (styrened) and plain text (Sideband/NomadNet)
        payload = self._normalize_message_payload(message)

        if payload:
            msg_type = payload.get("type", "chat")
            msg_protocol = payload.get("protocol", "")
            logger.info(
                f"LXMF received from {source_hash[:16]}...: type={msg_type}, protocol={msg_protocol or 'plain'}"
            )

        # Dispatch to all callbacks
        for callback, raw_mode in self._message_callbacks:
            try:
                if raw_mode:
                    # Raw mode - pass the LXMF message directly
                    callback(message)
                elif payload is not None:
                    # Parsed mode - pass source_hash and payload dict
                    callback(source_hash, payload)
                # If not raw_mode and payload is None, skip this callback
            except Exception as e:
                logger.error(f"Error in message callback: {e}")

    def request_messages_from_propagation_node(self, identity: "RNS.Identity | None" = None) -> bool:
        """Request pending messages from the configured propagation node.

        Triggers the LXMF router to sync with the outbound propagation node,
        pulling any messages stored for us.

        Args:
            identity: Identity to request messages for. Defaults to our own.

        Returns:
            True if the sync request was sent, False on error.
        """
        if not self.is_initialized or self._router is None:
            logger.warning("Cannot sync: LXMF not initialized")
            return False

        try:
            request_identity = identity or self._identity
            if request_identity is None:
                logger.warning("Cannot sync: no identity available")
                return False

            self._router.request_messages_from_propagation_node(request_identity)
            logger.info("Requested messages from propagation node")
            return True
        except Exception as e:
            logger.error(f"Failed to request messages from propagation node: {e}")
            return False

    def shutdown(self) -> None:
        """Shutdown the LXMF instance and clean up resources.

        This should be called when the application exits to properly
        close the router and clean up the LXMF instance.
        """
        if not self._initialized:
            logger.debug("LXMF not initialized, nothing to shutdown")
            return

        try:
            if self._router:
                # LXMF doesn't have an explicit shutdown method, but we can
                # set it to None to allow garbage collection
                logger.info("Shutting down LXMF")
                self._router = None

            self._identity = None
            self._message_callbacks.clear()
            self._initialized = False
            logger.info("LXMF shutdown complete")

        except Exception as e:
            logger.error(f"Error during LXMF shutdown: {e}")
            self._router = None
            self._identity = None
            self._message_callbacks.clear()
            self._initialized = False


def get_lxmf_service() -> LXMFService:
    """Get the singleton LXMFService instance.

    This function returns the global LXMFService instance, creating it
    if it doesn't exist yet.

    Returns:
        The singleton LXMFService instance.
    """
    global _lxmf_service

    if _lxmf_service is None:
        _lxmf_service = LXMFService()

    return _lxmf_service


class MockLXMFService:
    """Mock LXMF service for testing.

    Provides a minimal implementation of LXMFService interface for testing
    without requiring actual LXMF/RNS dependencies.

    Attributes:
        sent_messages: List of (destination, payload, method) tuples for sent messages.
        send_should_fail: If True, send_message will return None.
        _callback: Registered message callback function.
    """

    def __init__(self) -> None:
        """Initialize mock LXMF service."""
        self.sent_messages: list[tuple[str, dict[str, Any], str]] = []
        self.send_should_fail = False
        self._callback: Callable[[str, dict[str, Any]], None] | None = None

    def send_message(
        self,
        destination: str,
        payload: dict[str, Any],
        on_delivery: Callable[[Any], None] | None = None,
        on_failed: Callable[[Any], None] | None = None,
        delivery_method: str = DeliveryMethod.AUTO,
    ) -> SendMessageResult | None:
        """Mock send message.

        Args:
            destination: Destination hash.
            payload: Message payload.
            on_delivery: Optional callback invoked when message is delivered.
            on_failed: Optional callback invoked when delivery fails.
            delivery_method: Delivery method (direct, propagated, or auto).

        Returns:
            None if send_should_fail is True, otherwise SendMessageResult.
        """
        if self.send_should_fail:
            return None

        # Simulate method selection: auto defaults to direct in mock
        method_used = (
            DeliveryMethod.DIRECT if delivery_method == DeliveryMethod.AUTO else delivery_method
        )
        self.sent_messages.append((destination, payload, method_used))

        # Generate a mock hash and simulate full destination hash
        mock_hash = bytes.fromhex("a" * 32)
        # If destination is truncated, simulate resolving to full 32-char hex hash.
        # Validate input is hex before padding to avoid creating invalid hashes.
        if len(destination) == 32 and all(c in "0123456789abcdefABCDEF" for c in destination):
            full_destination = destination
        elif all(c in "0123456789abcdefABCDEF" for c in destination):
            # Valid hex prefix - pad with zeros
            full_destination = destination + "0" * (32 - len(destination))
        else:
            # Invalid input - use a deterministic mock hash
            full_destination = "0" * 32
        return SendMessageResult(
            hash=mock_hash,
            method=method_used,
            destination_hash=full_destination,
        )

    def register_handler(
        self,
        message_type: Any,
        handler: Any,
    ) -> None:
        """Register a handler for a message type (no-op for mock).

        This satisfies the StyreneProtocol interface used by RPCServer/RPCClient
        during initialization. Handlers are silently accepted but not invoked.

        Args:
            message_type: Message type to handle.
            handler: Handler function.
        """
        pass

    def register_callback(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """Register message callback.

        Args:
            callback: Function to call when message received.
        """
        self._callback = callback

    def simulate_receive(self, source: str, payload: dict[str, Any]) -> None:
        """Simulate receiving a message.

        Args:
            source: Source hash.
            payload: Message payload.
        """
        if self._callback:
            self._callback(source, payload)
