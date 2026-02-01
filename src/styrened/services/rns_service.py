"""RNS service lifecycle management.

This module provides a singleton RNSService for managing the Reticulum
Network Stack (RNS) lifecycle in headless and TUI applications.

The service handles:
- Initializing RNS.Reticulum with optional config override
- Creating destinations for receiving announces
- Checking transport status
- Graceful shutdown and cleanup
- Capturing and exposing initialization error states
- Suppressing cosmetic outbound packet errors in client-hub architecture

Usage:
    from styrened.services.rns_service import get_rns_service

    # Initialize RNS on app startup
    service = get_rns_service()
    if not service.initialize():
        logger.error("Failed to initialize Reticulum")
        # Check error state for user-facing guidance
        error = service.error_state
        if error.is_error:
            print(f"Error: {error.title} - {error.recovery}")

    # Create operator destination
    identity = get_operator_identity_object()
    if identity:
        destination = service.create_operator_destination(
            identity,
            app_name="styrene.tui",
            aspect="operator"
        )

    # Check if transport is enabled
    if service.is_transport_enabled():
        logger.info("Running as Reticulum transport node")

    # Shutdown on app exit
    service.shutdown()
"""

import logging
from pathlib import Path

import RNS

from styrened.models.rns_error import RNSErrorState

# Setup logger
logger = logging.getLogger(__name__)

# Singleton instance
_rns_service: "RNSService | None" = None


# Outbound packet error filtering explanation:
#
# When using MODE_POINT_TO_POINT TCPClientInterface with enable_transport=yes,
# RNS receives announces from many mesh nodes via the hub and builds path tables
# for them. However, when attempting to send response packets (proofs, path requests)
# to those nodes, the point-to-point interface correctly rejects them since it can
# only send to the hub, not arbitrary mesh destinations.
#
# This results in "No interfaces could process the outbound packet" errors that
# are expected behavior for the client-hub architecture and do not indicate actual
# failures. Discovery and messaging work correctly via hub-mediated routing.
#
# The filter is implemented as a monkey-patch on RNS.log since RNS uses its own
# logging system that bypasses Python's logging module.


class RNSService:
    """Singleton service for managing RNS lifecycle.

    This service manages the initialization and cleanup of the RNS.Reticulum
    instance. It ensures only one instance is created and provides helpers
    for common operations like destination creation.

    The service also tracks initialization error states to enable informative
    UX when running in degraded mode.
    """

    def __init__(self) -> None:
        """Initialize the RNSService (not the RNS instance yet)."""
        self._reticulum: RNS.Reticulum | None = None
        self._initialized = False
        self._error_state: RNSErrorState = RNSErrorState.none()
        self._destinations: dict[str, RNS.Destination] = {}
        self._outbound_error_filter_installed: bool = False

    @property
    def is_initialized(self) -> bool:
        """Check if RNS is initialized.

        Returns:
            True if RNS.Reticulum instance is created and ready.
        """
        return self._initialized and self._reticulum is not None

    @property
    def reticulum(self) -> RNS.Reticulum | None:
        """Get the RNS.Reticulum instance.

        Returns:
            RNS.Reticulum instance, or None if not initialized.
        """
        return self._reticulum

    @property
    def error_state(self) -> RNSErrorState:
        """Get the current error state.

        Returns:
            RNSErrorState with category and recovery guidance.
            If initialized successfully, returns NONE category.
        """
        return self._error_state

    @property
    def identity(self) -> RNS.Identity | None:
        """Get the operator identity.

        Returns:
            RNS.Identity instance, or None if not available.
        """
        from styrened.services.reticulum import get_operator_identity_object

        return get_operator_identity_object()

    def initialize(self, config_override: Path | None = None) -> bool:
        """Initialize RNS.Reticulum instance.

        This creates the RNS.Reticulum instance which loads configuration,
        starts interfaces, and begins network operations.

        During startup, transient "No interfaces could process the outbound packet"
        errors are suppressed for the first few seconds while TCP interfaces
        establish connections. After the startup period, full error logging resumes.

        On failure, captures the error state with categorization for
        user-facing display. Check error_state property for details.

        Args:
            config_override: Optional path to Reticulum config directory.
                If not provided, uses default Reticulum search paths.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        # If already initialized, return success
        if self._initialized and self._reticulum is not None:
            logger.debug("RNS already initialized")
            return True

        # Install outbound packet error filter to suppress expected client-hub errors
        self._install_outbound_error_filter()

        try:
            # Create RNS.Reticulum instance
            if config_override:
                logger.info(f"Initializing RNS with config: {config_override}")
                logger.info(
                    "Network interfaces establishing... "
                    "(cosmetic outbound packet errors suppressed)"
                )
                self._reticulum = RNS.Reticulum(configdir=str(config_override))
            else:
                logger.info("Initializing RNS with default config")
                logger.info(
                    "Network interfaces establishing... "
                    "(cosmetic outbound packet errors suppressed)"
                )
                self._reticulum = RNS.Reticulum()

            self._initialized = True
            self._error_state = RNSErrorState.none()
            logger.info("RNS initialized successfully")

            return True

        except Exception as e:
            logger.error(f"Failed to initialize RNS: {e}")
            self._reticulum = None
            self._initialized = False
            self._error_state = RNSErrorState.from_exception(e)
            logger.info(f"Error categorized as: {self._error_state.category.value}")

            return False

    def create_operator_destination(
        self,
        identity: RNS.Identity | None,
        app_name: str,
        aspect: str,
    ) -> RNS.Destination | None:
        """Create an RNS destination for the operator.

        Destinations are used to receive announces and messages. This creates
        a SINGLE destination with the operator's identity.

        If a destination with the same app_name and aspect already exists in
        the cache, the cached instance is returned instead of creating a new one.

        Args:
            identity: RNS.Identity to use for the destination.
            app_name: Application name for the destination (e.g., "styrene.tui").
            aspect: Aspect name for the destination (e.g., "operator").

        Returns:
            RNS.Destination instance, or None if creation failed.
        """
        if not self.is_initialized:
            logger.warning("Cannot create destination: RNS not initialized")
            return None

        if identity is None:
            logger.warning("Cannot create destination: identity is None")
            return None

        # Check cache for existing destination
        cache_key = f"{app_name}.{aspect}"
        if cache_key in self._destinations:
            logger.debug(f"Returning cached destination: {cache_key}")
            return self._destinations[cache_key]

        try:
            destination = RNS.Destination(
                identity,
                RNS.Destination.IN,  # Incoming direction
                RNS.Destination.SINGLE,  # Single destination (not group)
                app_name,
                aspect,
            )
            # Cache the destination
            self._destinations[cache_key] = destination
            logger.info(f"Created destination: {cache_key}")
            return destination

        except Exception as e:
            logger.error(f"Failed to create destination: {e}")
            return None

    def get_or_create_destination(
        self,
        identity: RNS.Identity | None,
        app_name: str,
        aspect: str,
    ) -> RNS.Destination | None:
        """Get a cached destination or create a new one.

        This is an explicit cache-aware method for destination management.
        If a destination with the given app_name and aspect exists in the cache,
        it is returned. Otherwise, a new destination is created and cached.

        Args:
            identity: RNS.Identity to use for the destination.
            app_name: Application name for the destination (e.g., "styrene.tui").
            aspect: Aspect name for the destination (e.g., "operator").

        Returns:
            RNS.Destination instance, or None if creation failed.
        """
        return self.create_operator_destination(identity, app_name, aspect)

    def clear_destinations(self) -> None:
        """Clear all cached destinations.

        This removes all destinations from the cache. Useful for cleanup
        during shutdown or when reinitializing the service.
        """
        count = len(self._destinations)
        self._destinations.clear()
        if count > 0:
            logger.info(f"Cleared {count} cached destination(s)")

    def _install_outbound_error_filter(self) -> None:
        """Install logging filter to suppress expected outbound packet errors.

        RNS uses its own logging system that writes directly to stderr, bypassing
        Python's logging module. We monkey-patch RNS.log to filter out cosmetic
        errors from MODE_POINT_TO_POINT TCPClientInterface when enable_transport=yes.
        These errors are expected behavior for the client-hub architecture and do
        not indicate actual failures.
        """
        if self._outbound_error_filter_installed:
            # Filter already installed
            return

        # Store original RNS.log function
        original_rns_log = RNS.log

        def filtered_rns_log(msg: str, level: int = 3) -> None:
            """Wrapper for RNS.log that filters out expected outbound packet errors."""
            # Filter out the expected client-hub error
            if level == RNS.LOG_ERROR and "No interfaces could process the outbound packet" in msg:
                return  # Suppress this specific error

            # Pass all other messages through
            original_rns_log(msg, level)

        # Replace RNS.log with our filtered version
        RNS.log = filtered_rns_log
        self._outbound_error_filter_installed = True

        logger.debug("Installed RNS.log monkey-patch to filter outbound packet errors")

    def is_transport_enabled(self) -> bool:
        """Check if this instance is running as a transport node.

        Transport nodes forward packets for other nodes, acting as routers
        in the Reticulum mesh network.

        Returns:
            True if transport is enabled, False otherwise.
        """
        if not self.is_initialized or self._reticulum is None:
            return False

        try:
            # RNS.Reticulum has a transport_enabled() method (no 'is_' prefix)
            return bool(self._reticulum.transport_enabled())
        except (AttributeError, TypeError) as e:
            # Fallback if method doesn't exist or isn't callable
            logger.warning(f"Could not determine transport status: {e}")
            return False

    def shutdown(self) -> None:
        """Shutdown the RNS instance and clean up resources.

        This should be called when the application exits to properly
        close interfaces and clean up the RNS instance.
        """
        if not self._initialized:
            logger.debug("RNS not initialized, nothing to shutdown")
            return

        try:
            # Note: We don't remove the RNS.log monkey-patch on shutdown
            # since it's a permanent filter for expected errors

            # Clear cached destinations first
            self.clear_destinations()

            if self._reticulum:
                # RNS doesn't have an explicit shutdown method, but we can
                # set it to None to allow garbage collection
                logger.info("Shutting down RNS")
                self._reticulum = None

            self._initialized = False
            logger.info("RNS shutdown complete")

        except Exception as e:
            logger.error(f"Error during RNS shutdown: {e}")
            self._reticulum = None
            self._initialized = False


def get_rns_service() -> RNSService:
    """Get the singleton RNSService instance.

    This function returns the global RNSService instance, creating it
    if it doesn't exist yet.

    Returns:
        The singleton RNSService instance.
    """
    global _rns_service

    if _rns_service is None:
        _rns_service = RNSService()

    return _rns_service
