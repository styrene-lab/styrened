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
        self._delivery_destination: "RNS.Destination | None" = None
        self._initialized = False
        self._message_callback: Callable[[str, dict[str, object]], None] | None = None

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

            # Register message received callback
            self._router.register_delivery_callback(self._handle_lxmf_message)

            self._identity = identity
            self._initialized = True

            # Announce our LXMF delivery destination so others can send to us
            # Create the delivery destination to get its hash for announcing
            self._delivery_destination = RNS.Destination(
                identity, RNS.Destination.IN, RNS.Destination.SINGLE, "lxmf", "delivery"
            )
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

        Args:
            destination_hash: Hex-encoded destination hash string (can be either
                            destination hash or identity hash - we'll look up
                            the identity hash from NodeStore if needed).
            payload: JSON-serializable message payload.

        Returns:
            True if message was queued for delivery, False otherwise.
        """
        if not self.is_initialized or self._router is None or self._identity is None:
            logger.warning("Cannot send message: LXMF not initialized")
            return False

        try:
            # First, try to recall directly with the provided hash (as destination hash)
            dest_bytes = bytes.fromhex(destination_hash)
            dest_identity = RNS.Identity.recall(dest_bytes)
            logger.debug(f"Direct recall({destination_hash[:16]}): {dest_identity is not None}")

            # If not found, check if we have the identity hash in NodeStore
            if dest_identity is None:
                try:
                    from styrened.services.node_store import get_node_store

                    store = get_node_store()

                    # Try looking up by operator destination hash first
                    identity_hash = store.get_identity_for_destination(destination_hash)
                    logger.debug(
                        f"NodeStore.get_identity_for_destination({destination_hash[:16]}): {identity_hash[:16] if identity_hash else None}"
                    )

                    # If not found, try looking up by LXMF destination hash
                    if not identity_hash:
                        identity_hash = store.get_identity_for_lxmf_destination(destination_hash)
                        logger.debug(
                            f"NodeStore.get_identity_for_lxmf_destination({destination_hash[:16]}): {identity_hash[:16] if identity_hash else None}"
                        )

                    if identity_hash and identity_hash != destination_hash:
                        logger.info(
                            f"Found identity hash {identity_hash[:16]}... for destination {destination_hash[:16]}..."
                        )
                        identity_bytes = bytes.fromhex(identity_hash)
                        # Use from_identity_hash=True since we're looking up by identity hash
                        dest_identity = RNS.Identity.recall(identity_bytes, from_identity_hash=True)
                        logger.info(f"Recall by identity hash: {dest_identity is not None}")
                except Exception as e:
                    logger.warning(f"NodeStore lookup failed: {e}")

            if dest_identity is None:
                logger.warning(
                    f"Cannot send to {destination_hash}: identity not known. "
                    "Destination must announce before receiving messages."
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

            # Validate path exists before attempting to send
            if not self._ensure_path(dest_destination.hash):
                logger.warning(
                    f"No path to {destination_hash[:16]}..., message not sent. "
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
                f"Sent LXMF message to {dest_destination.hash.hex()[:16]}... (type={payload.get('type')}, protocol={payload.get('protocol')})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

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

        Args:
            destination_hash: Hex-encoded destination hash string.
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
            # First, try to recall directly with the provided hash (as destination hash)
            dest_bytes = bytes.fromhex(destination_hash)
            dest_identity = RNS.Identity.recall(dest_bytes)

            # If not found, check if we have the identity hash in NodeStore
            if dest_identity is None:
                try:
                    from styrened.services.node_store import get_node_store

                    store = get_node_store()

                    # Try looking up by operator destination hash first
                    identity_hash = store.get_identity_for_destination(destination_hash)

                    # If not found, try looking up by LXMF destination hash
                    if not identity_hash:
                        identity_hash = store.get_identity_for_lxmf_destination(destination_hash)

                    if identity_hash and identity_hash != destination_hash:
                        logger.info(
                            f"Found identity hash {identity_hash[:16]}... for destination {destination_hash[:16]}..."
                        )
                        identity_bytes = bytes.fromhex(identity_hash)
                        # Use from_identity_hash=True since we're looking up by identity hash
                        dest_identity = RNS.Identity.recall(identity_bytes, from_identity_hash=True)
                        logger.info(f"Recall by identity hash: {dest_identity is not None}")
                except Exception as e:
                    logger.warning(f"NodeStore lookup failed: {e}")

            if dest_identity is None:
                logger.warning(
                    f"Cannot send to {destination_hash}: identity not known. "
                    "Destination must announce before receiving messages."
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
                f"Dest destination hash: {dest_destination.hash.hex()[:16]}... (from identity {dest_identity.hash.hex()[:16]}...)"
            )
            start_time = time.monotonic()
            path_available = self._ensure_path(dest_destination.hash)

            while not path_available and (time.monotonic() - start_time) < max_wait:
                time.sleep(check_interval)
                path_available = RNS.Transport.has_path(dest_destination.hash)
                elapsed = time.monotonic() - start_time
                logger.info(f"Path check: has_path={path_available}, elapsed={elapsed:.1f}s")

            if not path_available:
                logger.warning(
                    f"Timeout waiting for path to {destination_hash[:16]}... after {max_wait}s"
                )
                return False

            logger.debug(
                f"Path to {destination_hash[:16]}... available after "
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
                f"Sent LXMF message (with retry) to {dest_destination.hash.hex()[:16]}... (type={payload.get('type')}, protocol={payload.get('protocol')})"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False

    def register_callback(self, callback: Callable[[str, dict[str, object]], None]) -> None:
        """Register callback for incoming messages.

        The callback will be invoked when a message is received with the
        source hash and deserialized payload.

        Args:
            callback: Function called with (source_hash: str, payload: dict).
        """
        self._message_callback = callback
        logger.debug("Registered message callback")

    def _handle_lxmf_message(self, message: "LXMF.LXMessage") -> None:
        """Handle incoming LXMF message.

        This is called by the LXMF router when a message is received.

        Args:
            message: LXMF.LXMessage instance.
        """
        try:
            # Extract source hash
            source_hash = message.source_hash.hex()

            # Decode content
            content = message.content.decode("utf-8")
            payload = json.loads(content)

            logger.info(
                f"LXMF received from {source_hash[:16]}...: type={payload.get('type')}, protocol={payload.get('protocol')}"
            )

            # Invoke callback if registered
            if self._message_callback is not None:
                self._message_callback(source_hash, payload)
            else:
                logger.warning("No message callback registered - message will be dropped")

        except Exception as e:
            logger.error(f"Error handling LXMF message: {e}")

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
