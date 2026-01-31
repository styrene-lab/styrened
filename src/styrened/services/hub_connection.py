"""Styrene hub connection management.

This module provides functionality to connect to a Styrene hub for fleet
coordination over the Reticulum mesh network.

A Styrene hub is a central coordinator that:
- Provides device discovery
- Facilitates LXMF messaging between operator and devices
- Manages fleet-wide announces and status updates

Usage:
    from styrened.services.hub_connection import get_hub_connection, STYRENE_HUB_ADDRESS

    # Connect to Styrene hub
    hub = get_hub_connection()
    if hub.connect(hub_address=STYRENE_HUB_ADDRESS):
        logger.info(f"Connected to hub at {STYRENE_HUB_ADDRESS}")

    # Disconnect when done
    hub.disconnect()
"""

import logging
import time
from enum import Enum

import RNS

from styrened.services.rns_service import get_rns_service

# Setup logger
logger = logging.getLogger(__name__)

# Path check interval for connection health monitoring (seconds)
PATH_CHECK_INTERVAL: int = 30

# Known hub addresses
# Styrene Community Hub (brutus cluster)
#
# Retrieved via scripts/get-hub-address.sh
#
# Hub details:
#   Host: 192.168.0.102:4242 (RNS transport via LoadBalancer)
#   Name: Styrene Propagation Node
#   Identity Hash: 559c71c512c7376a5202e4c5b7043113
#   LXMF Propagation Destination: 6fc8bf22aa293588c9bf8d7488102e95 (what lxmd announces)
#   LXMF Delivery Destination: 1c527ad47a10dc62406bb5d780d289ba (not announced)
STYRENE_HUB_ADDRESS: str = "6fc8bf22aa293588c9bf8d7488102e95"


class HubStatus(Enum):
    """Hub connection status states."""

    DISABLED = "disabled"  # Hub not configured
    WAITING = "waiting"  # Waiting for hub announce
    CONNECTED = "connected"  # Successfully connected
    DISCONNECTED = "disconnected"  # Missed announce window


# Singleton instance
_hub_connection: "HubConnection | None" = None


class HubConnection:
    """Manages connection to a Styrene hub for fleet coordination.

    The hub connection creates an RNS destination for the hub and
    tracks connection status.
    """

    def __init__(self) -> None:
        """Initialize the HubConnection (not connected yet)."""
        self._connected = False
        self._hub_destination: RNS.Destination | None = None
        self._hub_address: str | None = None
        self._waiting_since: float | None = None
        self._announce_interval: int = 60  # Default 60 seconds
        self._last_path_check: float = 0.0

    @property
    def is_connected(self) -> bool:
        """Check if connected to a hub.

        Periodically re-validates the path to the hub to ensure the connection
        is still viable. If the path check interval has elapsed, performs a
        fresh path check via RNS.Transport.has_path().

        Returns:
            True if connected to a hub with valid path, False otherwise.
        """
        if not self._connected:
            return False

        if self._hub_address is None:
            return False

        # Check if we need to re-validate the path
        current_time = time.time()
        if current_time - self._last_path_check > PATH_CHECK_INTERVAL:
            try:
                hub_hash = bytes.fromhex(self._hub_address)
                if not RNS.Transport.has_path(hub_hash):
                    logger.warning(
                        f"Path to hub {self._hub_address[:16]}... no longer available"
                    )
                    self._connected = False
                    return False
                self._last_path_check = current_time
            except (ValueError, TypeError) as e:
                logger.error(f"Failed to check path to hub: {e}")
                self._connected = False
                return False

        return True

    def force_path_check(self) -> bool:
        """Force an immediate path check, bypassing the interval.

        This method validates the path to the hub regardless of when the last
        check occurred. Useful for immediate connection validation.

        Returns:
            True if path is valid, False otherwise.
        """
        if not self._connected:
            return False

        if self._hub_address is None:
            return False

        try:
            hub_hash = bytes.fromhex(self._hub_address)
            if not RNS.Transport.has_path(hub_hash):
                logger.warning(
                    f"Path to hub {self._hub_address[:16]}... no longer available "
                    "(forced check)"
                )
                self._connected = False
                return False
            self._last_path_check = time.time()
            return True
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to check path to hub: {e}")
            self._connected = False
            return False

    @property
    def hub_destination(self) -> RNS.Destination | None:
        """Get the hub destination.

        Returns:
            RNS.Destination for the hub, or None if not connected.
        """
        return self._hub_destination

    @property
    def hub_address(self) -> str | None:
        """Get the hub address.

        Returns:
            Hex-encoded hub address, or None if not connected.
        """
        return self._hub_address

    def set_announce_interval(self, interval: int) -> None:
        """Set the hub's announce interval.

        Args:
            interval: Announce interval in seconds.
        """
        self._announce_interval = interval

    def start_waiting(self) -> None:
        """Start waiting timer for hub announce.

        Called when hub is configured but not yet connected.
        """
        if not self._connected and self._hub_address:
            self._waiting_since = time.time()
            logger.debug(
                f"Started waiting for hub announce at {self._hub_address[:16]}..."
            )

    def is_within_announce_window(self) -> bool:
        """Check if we're still within expected announce window.

        Returns:
            True if we're within the announce window, False if we've missed it.
        """
        if self._waiting_since is None:
            return True  # Not waiting yet

        elapsed = time.time() - self._waiting_since
        return elapsed < self._announce_interval

    @property
    def status(self) -> HubStatus:
        """Get current hub connection status.

        Uses is_connected property which periodically re-validates the path.

        Returns:
            HubStatus enum value.
        """
        if not self._hub_address:
            return HubStatus.DISABLED

        if self.is_connected:
            return HubStatus.CONNECTED

        if self.is_within_announce_window():
            return HubStatus.WAITING

        return HubStatus.DISCONNECTED

    def connect(self, hub_address: str) -> bool:
        """Connect to a Styrene hub.

        Creates an RNS destination for the hub using its destination hash. This
        allows sending messages to the hub and receiving announces from it.

        Args:
            hub_address: 32-character hex string (16 bytes) of hub's LXMF destination hash.

        Returns:
            True if connection succeeded, False otherwise.
        """
        # Check if RNS is initialized
        rns_service = get_rns_service()
        if not rns_service.is_initialized:
            logger.error("Cannot connect to hub: RNS not initialized")
            return False

        # Validate address format (32 hex chars = 16 bytes)
        if not hub_address or len(hub_address) != 32:
            logger.error(f"Invalid hub address (expected 32 hex chars): {hub_address}")
            return False

        try:
            # Convert hex address to bytes
            hub_hash = bytes.fromhex(hub_address)

            # Check if we have a path to this destination
            # If not, request it (active discovery instead of waiting for announces)
            if not RNS.Transport.has_path(hub_hash):
                logger.info(
                    f"Hub destination {hub_address[:16]}... not in path table. "
                    "Requesting path..."
                )
                # Request path to hub (active discovery)
                RNS.Transport.request_path(hub_hash)

                # Store address but mark as not connected yet
                self._hub_address = hub_address
                self._connected = False
                self.start_waiting()  # Start waiting timer
                return False

            # We have a path! Mark as connected
            # Note: We don't create an RNS.Destination object here because LXMF
            # handles message routing using destination hashes directly
            self._hub_destination = None  # Will be handled by LXMF layer
            self._hub_address = hub_address
            self._connected = True
            self._waiting_since = None  # Reset waiting timer

            hops = RNS.Transport.hops_to(hub_hash)
            logger.info(f"Connected to hub at {hub_address[:16]}... ({hops} hops)")
            return True

        except (ValueError, TypeError) as e:
            logger.error(f"Failed to parse hub address: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to hub: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from the hub.

        Clears the hub destination and connection state.
        """
        if self._connected:
            logger.info(
                f"Disconnecting from hub at {self._hub_address[:16] if self._hub_address else 'unknown'}..."
            )

        self._hub_destination = None
        self._hub_address = None
        self._connected = False
        self._waiting_since = None

    def retry_connection(self) -> bool:
        """Retry connection to the hub using the stored address.

        Useful when the hub wasn't initially available but might be now.

        Returns:
            True if connection succeeded, False otherwise.
        """
        if not self._hub_address:
            logger.warning("No hub address configured for retry")
            return False

        if self._connected:
            logger.debug(f"Already connected to hub at {self._hub_address[:16]}...")
            return True

        logger.info(f"Retrying connection to hub at {self._hub_address[:16]}...")
        return self.connect(self._hub_address)


def get_hub_connection() -> HubConnection:
    """Get the singleton HubConnection instance.

    Returns:
        The singleton HubConnection instance.
    """
    global _hub_connection

    if _hub_connection is None:
        _hub_connection = HubConnection()

    return _hub_connection
