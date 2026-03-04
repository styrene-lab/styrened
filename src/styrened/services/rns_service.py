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
- Monitoring LocalInterface connection state and handling reconnections

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
import threading
import time
from collections.abc import Callable
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

    Connection State Monitoring:
        When using LocalInterface to connect to a shared rnsd instance,
        the socket may drop and reconnect. This service monitors interface
        states and clears destination caches on disconnect to prevent
        "already registered" errors during reconnection.
    """

    # Minimum interval between interface status checks (seconds)
    INTERFACE_CHECK_INTERVAL = 5.0
    _RECONNECT_DEBOUNCE = 30.0  # Suppress repeated reconnect handling for 30s

    def __init__(self) -> None:
        """Initialize the RNSService (not the RNS instance yet)."""
        self._reticulum: RNS.Reticulum | None = None
        self._initialized = False
        self._error_state: RNSErrorState = RNSErrorState.none()
        self._destinations: dict[str, RNS.Destination] = {}
        self._outbound_error_filter_installed: bool = False

        # Connection state monitoring
        self._interface_monitor_thread: threading.Thread | None = None
        self._monitor_stop_event = threading.Event()
        self._last_interface_states: dict[str, bool] = {}
        self._last_interface_ids: dict[str, int] = {}  # Track object identity for reconnect detection
        # Track disconnect time per interface to avoid cross-interface confusion
        self._disconnect_times: dict[str, float] = {}
        self._reconnect_callbacks: list[Callable[[], None]] = []

        # Thread safety lock for shared state (_destinations, _reconnect_callbacks)
        self._lock = threading.Lock()

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

            # Log interface status and capture initial states
            self._log_interface_status()
            self._capture_interface_states()

            # Start interface monitoring thread for LocalInterface reconnection handling
            self._start_interface_monitor()

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

        Thread-safe: Uses internal lock for cache access.

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

        cache_key = f"{app_name}.{aspect}"

        # Thread-safe cache check and update
        with self._lock:
            # Check cache for existing destination
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
                if "already registered" in str(e).lower():
                    # RNS still has the destination from before reconnect.
                    # Find it in RNS.Transport.destinations and cache it.
                    for d in RNS.Transport.destinations:
                        if d.hash == RNS.Destination.hash(identity, app_name, aspect):
                            self._destinations[cache_key] = d
                            logger.info(f"Recovered existing destination: {cache_key}")
                            return d
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

        Thread-safe: Uses internal lock for cache access.
        """
        with self._lock:
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

    def register_reconnect_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to be invoked after interface reconnection.

        Callbacks are invoked after destination caches have been cleared
        and the interface has stabilized. Use this to re-register destinations
        or reinitialize LXMF routers.

        Thread-safe: Uses internal lock for callback list access.

        Args:
            callback: Function to call after reconnection. Called with no arguments.
        """
        with self._lock:
            self._reconnect_callbacks.append(callback)
            count = len(self._reconnect_callbacks)
        logger.debug(f"Registered reconnect callback, total: {count}")

    def _capture_interface_states(self) -> None:
        """Capture current interface online states for change detection."""
        try:
            interfaces = RNS.Transport.interfaces
            if not interfaces:
                return

            for iface in interfaces:
                name = getattr(iface, "name", str(id(iface)))
                online = getattr(iface, "online", True)
                self._last_interface_states[name] = online

            logger.debug(f"Captured interface states: {self._last_interface_states}")

        except Exception as e:
            logger.debug(f"Could not capture interface states: {e}")

    def _start_interface_monitor(self) -> None:
        """Start background thread to monitor interface connection states."""
        if self._interface_monitor_thread is not None:
            logger.debug("Interface monitor already running")
            return

        self._monitor_stop_event.clear()
        self._interface_monitor_thread = threading.Thread(
            target=self._interface_monitor_loop,
            name="rns-interface-monitor",
            daemon=True,
        )
        self._interface_monitor_thread.start()
        logger.info("Started interface connection monitor")

    def _stop_interface_monitor(self) -> None:
        """Stop the interface monitoring thread."""
        if self._interface_monitor_thread is None:
            return

        self._monitor_stop_event.set()
        self._interface_monitor_thread.join(timeout=2.0)
        self._interface_monitor_thread = None
        logger.debug("Stopped interface monitor")

    def _interface_monitor_loop(self) -> None:
        """Background loop to monitor interface states and handle reconnections.

        Detects LocalInterface disconnects and clears destination caches
        to prevent 'already registered' errors on reconnection.
        """
        logger.debug("Interface monitor loop started")

        while not self._monitor_stop_event.is_set():
            try:
                self._check_interface_states()
            except Exception as e:
                logger.warning(f"Interface monitor error: {e}")

            # Wait for next check interval or stop event
            self._monitor_stop_event.wait(timeout=self.INTERFACE_CHECK_INTERVAL)

        logger.debug("Interface monitor loop exited")

    def _check_interface_states(self) -> None:
        """Check interface states and handle disconnections.

        Compares current states to last known states and triggers
        cache clearing when LocalInterface goes offline.
        """
        try:
            interfaces = RNS.Transport.interfaces
            if not interfaces:
                return

            for iface in interfaces:
                name = getattr(iface, "name", str(id(iface)))
                online = getattr(iface, "online", True)
                iface_type = type(iface).__name__

                # Get previous state (default to True for new interfaces)
                prev_online = self._last_interface_states.get(name, True)

                # Detect state change
                if prev_online and not online:
                    # Interface went offline
                    logger.warning(f"[RECONNECT] Interface offline: [{iface_type}] {name}")
                    self._disconnect_times[name] = time.monotonic()

                    # For LocalInterface, this is the critical case
                    if "LocalInterface" in iface_type:
                        logger.warning(
                            "[RECONNECT] LocalInterface disconnect detected - "
                            "will clear caches on reconnection"
                        )

                elif not prev_online and online:
                    # Interface came back online
                    logger.info(f"[RECONNECT] Interface online: [{iface_type}] {name}")

                    # Check if THIS interface had a disconnect that needs handling
                    disconnect_time = self._disconnect_times.get(name)
                    if disconnect_time is not None:
                        elapsed = time.monotonic() - disconnect_time
                        logger.info(f"[RECONNECT] {name} reconnected after {elapsed:.1f}s offline")

                        # Clear caches and invoke callbacks
                        self._handle_reconnection(iface_type, name)
                        del self._disconnect_times[name]

                # Track TCP interface reconnection via object identity change.
                # RNS TCPClientInterface recreates the socket on reconnect,
                # so we also track the object id to detect silent reconnects
                # that don't toggle the online flag (e.g., network switch).
                # Debounced: skip if we handled a reconnection within the
                # cooldown period to avoid reconnection storms when multiple
                # TCP peers cycle rapidly.
                if "TCPClientInterface" in iface_type:
                    obj_id = id(iface)
                    prev_id = self._last_interface_ids.get(name)
                    if prev_id is not None and prev_id != obj_id:
                        now = time.monotonic()
                        last_reconnect = getattr(self, "_last_reconnect_time", 0.0)
                        if now - last_reconnect > self._RECONNECT_DEBOUNCE:
                            logger.info(
                                f"[RECONNECT] TCP interface object changed: {name} "
                                f"(id {prev_id} -> {obj_id}) — triggering re-announce"
                            )
                            self._handle_reconnection(iface_type, name)
                            self._last_reconnect_time = now
                        else:
                            logger.debug(
                                f"[RECONNECT] TCP interface churn suppressed for {name} "
                                f"(debounce {self._RECONNECT_DEBOUNCE}s)"
                            )
                    self._last_interface_ids[name] = obj_id

                # Update tracked state
                self._last_interface_states[name] = online

        except Exception as e:
            logger.debug(f"Interface state check failed: {e}")

    def _handle_reconnection(self, iface_type: str, iface_name: str) -> None:
        """Handle interface reconnection by clearing caches and notifying listeners.

        Thread-safe: Uses internal lock for cache and callback list access.
        Callbacks are invoked outside the lock to prevent deadlocks.

        Args:
            iface_type: Type name of the reconnected interface.
            iface_name: Name of the reconnected interface.
        """
        logger.info(f"[RECONNECT] Handling reconnection for [{iface_type}] {iface_name}")

        # Thread-safe: clear caches and copy callback list while holding lock
        with self._lock:
            dest_count = len(self._destinations)
            if dest_count > 0:
                logger.info(
                    f"[RECONNECT] Clearing {dest_count} cached destination(s) to allow re-registration"
                )
                self._destinations.clear()

            # Copy callback list to avoid holding lock during invocation
            callbacks = list(self._reconnect_callbacks)

        # Invoke callbacks outside the lock to prevent deadlocks
        for callback in callbacks:
            try:
                logger.debug(f"[RECONNECT] Invoking callback: {callback}")
                callback()
            except Exception as e:
                logger.error(f"[RECONNECT] Callback error: {e}")

        logger.info("[RECONNECT] Reconnection handling complete")

    def _log_interface_status(self) -> None:
        """Log status of all configured RNS interfaces.

        Called after RNS initialization to provide visibility into which
        interfaces are active. This helps diagnose connectivity issues
        on bare-metal deployments.
        """
        if not self._initialized:
            return

        try:
            interfaces = RNS.Transport.interfaces
            if not interfaces:
                logger.info("RNS interfaces: none configured")
                return

            logger.info(f"RNS interfaces ({len(interfaces)} active):")
            for iface in interfaces:
                iface_type = type(iface).__name__
                name = getattr(iface, "name", "unnamed")

                # Build status string
                status_parts = []

                # Check if interface is online
                if hasattr(iface, "online"):
                    status = "UP" if iface.online else "DOWN"
                    status_parts.append(status)

                # Get connection details for TCP interfaces
                if hasattr(iface, "target_ip") and hasattr(iface, "target_port"):
                    status_parts.append(f"target={iface.target_ip}:{iface.target_port}")
                elif hasattr(iface, "bind_ip") and hasattr(iface, "bind_port"):
                    status_parts.append(f"listen={iface.bind_ip}:{iface.bind_port}")

                # Get bitrate if available
                if hasattr(iface, "bitrate") and iface.bitrate:
                    bitrate_mbps = iface.bitrate / 1_000_000
                    status_parts.append(f"{bitrate_mbps:.1f}Mbps")

                status_str = ", ".join(status_parts) if status_parts else "initializing"
                logger.info(f"  [{iface_type}] {name}: {status_str}")

        except Exception as e:
            logger.debug(f"Could not enumerate interfaces: {e}")

    def shutdown(self) -> None:
        """Shutdown the RNS instance and clean up resources.

        This should be called when the application exits to properly
        close interfaces and clean up the RNS instance.
        """
        if not self._initialized:
            logger.debug("RNS not initialized, nothing to shutdown")
            return

        try:
            # Stop interface monitor thread first
            self._stop_interface_monitor()

            # Note: We don't remove the RNS.log monkey-patch on shutdown
            # since it's a permanent filter for expected errors

            # Clear cached destinations first
            self.clear_destinations()

            # Clear reconnect callbacks
            self._reconnect_callbacks.clear()

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
