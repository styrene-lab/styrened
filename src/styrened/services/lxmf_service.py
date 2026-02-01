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
from typing import Any

import platformdirs

try:
    import LXMF
    import RNS

    LXMF_AVAILABLE = True
except ImportError:
    LXMF_AVAILABLE = False

from styrened.services.rns_service import get_rns_service

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

    def initialize(self, identity: "RNS.Identity") -> bool:
        """Initialize LXMF router instance.

        This creates the LXMF router instance which handles message
        routing and delivery over the Reticulum network.

        Args:
            identity: RNS.Identity to use for the router.

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

            # Create LXMF router
            self._router = LXMF.LXMRouter(
                identity=identity,
                storagepath=str(lxmf_storage),
            )

            # Register our identity for receiving messages - this creates the actual
            # delivery destination that will receive incoming LXMF messages
            self._delivery_destination = self._router.register_delivery_identity(identity)

            # Register message received callback
            self._router.register_delivery_callback(self._handle_lxmf_message)

            self._identity = identity
            self._initialized = True

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

    def send_message(self, destination_hash: str, payload: dict[str, object]) -> bool:
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

        Returns:
            True if message was queued for delivery, False otherwise.
        """
        if not self.is_initialized or self._router is None or self._identity is None:
            logger.warning("Cannot send message: LXMF not initialized")
            return False

        try:
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

            logger.debug(
                f"[HASH] Created LXMF destination: "
                f"lxmf_dest={dest_destination.hash.hex()[:16]}... "
                f"(from identity {dest_identity.hash.hex()[:16]}...)"
            )

            # Validate path exists before attempting to send
            if not self._ensure_path(dest_destination.hash):
                logger.warning(
                    f"No path to {dest_destination.hash.hex()[:16]}..., message not sent. "
                    "Use send_with_retry() to wait for path discovery."
                )
                return False

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
                f"[HASH] Sent LXMF message to {dest_destination.hash.hex()[:16]}... "
                f"(type={payload.get('type')}, protocol={payload.get('protocol')})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

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

            # Strategy 3: Try LXMF destination hash
            if not identity_hash:
                identity_hash = store.get_identity_for_lxmf_destination(destination_hash)
                if identity_hash:
                    logger.debug(
                        f"[HASH] Strategy 3 success: lxmf_dest lookup -> "
                        f"identity_hash={identity_hash[:16]}..."
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
                logger.warning(
                    f"[HASH] NodeStore had identity_hash={identity_hash[:16]}... "
                    f"but RNS.Identity.recall() failed. Identity may not be in RNS cache."
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

        # Try to parse JSON content for non-raw callbacks
        payload = None
        try:
            content = message.content.decode("utf-8")
            payload = json.loads(content)
            logger.info(
                f"LXMF received from {source_hash[:16]}...: type={payload.get('type')}, protocol={payload.get('protocol')}"
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.debug(f"LXMF message from {source_hash[:16]}... is not JSON: {e}")

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
            self._message_callback = None
            self._initialized = False
            logger.info("LXMF shutdown complete")

        except Exception as e:
            logger.error(f"Error during LXMF shutdown: {e}")
            self._router = None
            self._identity = None
            self._message_callback = None
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
        sent_messages: List of (destination, payload) tuples for sent messages.
        send_should_fail: If True, send_message will return False.
        _callback: Registered message callback function.
    """

    def __init__(self) -> None:
        """Initialize mock LXMF service."""
        self.sent_messages: list[tuple[str, dict[str, Any]]] = []
        self.send_should_fail = False
        self._callback: Callable[[str, dict[str, Any]], None] | None = None

    def send_message(self, destination: str, payload: dict[str, Any]) -> bool:
        """Mock send message.

        Args:
            destination: Destination hash.
            payload: Message payload.

        Returns:
            False if send_should_fail is True, otherwise True.
        """
        if self.send_should_fail:
            return False

        self.sent_messages.append((destination, payload))
        return True

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
