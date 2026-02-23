"""Core application lifecycle management.

This module provides lifecycle management for headless Styrene applications.
Handles initialization and shutdown of core services (RNS, LXMF) without
TUI dependencies.

Usage:
    from styrened.services.lifecycle import CoreLifecycle
    from styrened.services.config import get_default_core_config

    # Initialize core services
    config = get_default_core_config()
    lifecycle = CoreLifecycle(config)

    # Start services
    lifecycle.initialize()

    # Use services...
    from styrened.services.rns_service import get_rns_service
    rns = get_rns_service()
    print(f"RNS initialized: {rns.is_initialized}")

    # Cleanup
    lifecycle.shutdown()
"""

import atexit
import logging
import shutil
from pathlib import Path

from styrened.models.config import CoreConfig
from styrened.models.rns_error import RNSErrorState
from styrened.services.reticulum import (
    ensure_operator_identity,
    get_operator_identity_object,
)
from styrened.services.rns_service import get_rns_service

# Track temp directories for atexit cleanup (backup for crash/SIGKILL scenarios)
_temp_config_dirs: set[Path] = set()


def _cleanup_temp_dirs() -> None:
    """Atexit handler to clean up any remaining temp config directories."""
    for temp_dir in list(_temp_config_dirs):
        try:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
                logging.getLogger(__name__).debug(f"Atexit cleanup: {temp_dir}")
        except Exception:
            pass  # Best effort cleanup
    _temp_config_dirs.clear()


# Register atexit handler
atexit.register(_cleanup_temp_dirs)

logger = logging.getLogger(__name__)


class CoreLifecycle:
    """Manages core Styrene lifecycle for headless applications.

    This class handles:
    - Reticulum initialization
    - LXMF initialization (optional)
    - Graceful shutdown
    - Error state tracking

    It does NOT include TUI-specific features like hub connection
    or Styrene node announcements.
    """

    def __init__(self, config: CoreConfig, client_only: bool = False) -> None:
        """Initialize lifecycle manager.

        Args:
            config: Core configuration.
            client_only: If True, don't start server interfaces (for CLI tools).
        """
        self.config = config
        self._client_only = client_only
        self._initialized = False
        self._rns_error_state: RNSErrorState = RNSErrorState.none()
        self._rns_config_dir: Path | None = None

    @property
    def rns_error_state(self) -> RNSErrorState:
        """Get the RNS initialization error state.

        Returns:
            RNSErrorState with category and recovery guidance.
            If initialized successfully, returns NONE category.
        """
        return self._rns_error_state

    @property
    def is_initialized(self) -> bool:
        """Check if services are initialized.

        Returns:
            True if initialized, False otherwise.
        """
        return self._initialized

    def initialize(self) -> bool:
        """Initialize core Styrene services.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            logger.warning("Already initialized")
            return True

        try:
            # Initialize Reticulum
            if not self._initialize_reticulum():
                logger.warning("Reticulum initialization failed - running in offline mode")
                # Don't fail entirely - allow offline mode
                self._initialized = True
                return True

            # Initialize LXMF if enabled
            if self.config.rpc.enabled:
                self._initialize_lxmf()

            self._initialized = True
            logger.info("Core services initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            return False

    def _initialize_reticulum(self) -> bool:
        """Initialize Reticulum networking.

        Returns:
            True if RNS initialized successfully, False otherwise.
        """
        # Try to ensure operator identity exists
        try:
            # Pass only the explicit config override (None if not set).
            # _resolve_identity_path handles the full resolution chain:
            # config override -> /etc/styrene/identity -> ~/.config/styrene/operator.key
            ensure_operator_identity(
                config_path=self.config.reticulum.operator_identity_path,
                identity_config=self.config.identity,
            )
            logger.info(f"Operator identity ready (mode: {self.config.reticulum.mode.value})")
        except Exception as e:
            logger.error(f"Failed to load operator identity: {e}")
            self._rns_error_state = RNSErrorState.from_exception(e)
            return False

        try:
            # Initialize RNS with proper config precedence
            import tempfile
            from pathlib import Path

            from styrened.services.reticulum import (
                find_reticulum_config,
                generate_rns_config,
                get_reticulum_config_paths,
            )

            # Config precedence:
            # 1. Explicit override from config.yaml (config_path_override)
            # 2. Standard RNS paths: /etc/reticulum, ~/.config/reticulum, ~/.reticulum
            # 3. Generate temp config if none found
            override = self.config.reticulum.config_path_override
            existing_config = find_reticulum_config(override=override)

            if existing_config:
                logger.info(f"Using existing RNS config: {existing_config / 'config'}")
                if override and existing_config == override:
                    logger.debug(f"Config from explicit override: {override}")
                config_dir = existing_config
                self._rns_config_dir = None  # Don't cleanup existing config
            else:
                # Log what we searched
                searched_paths = []
                if override:
                    searched_paths.append(str(override))
                searched_paths.extend(str(p) for p in get_reticulum_config_paths())
                logger.info(f"No existing RNS config found (searched: {', '.join(searched_paths)})")
                logger.info("Generating temporary RNS config from config.yaml interfaces")

                # Generate RNS config from CoreConfig
                config_content = generate_rns_config(self.config, client_only=self._client_only)
                logger.debug(f"Generated RNS config:\n{config_content}")

                # Create temporary config directory that persists for daemon lifetime
                # Note: We use mkdtemp instead of TemporaryDirectory context manager
                # because RNS needs the config to remain accessible while running
                config_dir = Path(tempfile.mkdtemp(prefix="styrened_rns_"))
                self._rns_config_dir = config_dir  # Store reference for cleanup
                _temp_config_dirs.add(config_dir)  # Register for atexit cleanup
                config_file = config_dir / "config"
                config_file.write_text(config_content)

            logger.info(f"Initializing RNS in {self.config.reticulum.mode.value} mode")
            logger.debug(f"RNS config dir: {config_dir}")

            # Initialize RNS with temporary config
            rns_service = get_rns_service()
            if not rns_service.initialize(config_override=config_dir):
                logger.warning("RNS service initialization failed")
                self._rns_error_state = rns_service.error_state
                return False

            # Success - clear any error state
            self._rns_error_state = RNSErrorState.none()
            logger.info("RNS service initialized")

            # Create operator destination
            identity = get_operator_identity_object()
            if identity:
                destination = rns_service.create_operator_destination(
                    identity, app_name="styrene_core", aspect="operator"
                )
                if destination:
                    logger.info(f"Operator destination: {destination.hash.hex()[:16]}...")
                else:
                    logger.warning("Failed to create operator destination")

            return True

        except Exception as e:
            logger.error(f"Reticulum initialization error: {e}")
            self._rns_error_state = RNSErrorState.from_exception(e)
            return False

    def _initialize_lxmf(self) -> bool:
        """Initialize LXMF messaging for RPC.

        Returns:
            True if LXMF initialized successfully, False otherwise.
        """
        try:
            from styrened.services.lxmf_service import get_lxmf_service

            identity = get_operator_identity_object()
            if not identity:
                logger.warning("No operator identity available for LXMF")
                return False

            lxmf_service = get_lxmf_service()
            # Pass LXMF config if available in CoreConfig
            lxmf_config = getattr(self.config, "lxmf", None)
            # Pass display_name from identity config for proper LXMF announce format
            # This enables ecosystem clients (Sideband, NomadNet, MeshChat) to display
            # the configured name instead of showing "Unknown"
            display_name = None
            if hasattr(self.config, "identity") and self.config.identity:
                display_name = self.config.identity.display_name
            if lxmf_service.initialize(
                identity, lxmf_config=lxmf_config, display_name=display_name
            ):
                logger.info("LXMF service initialized")
                return True
            else:
                logger.warning("LXMF initialization failed")
                return False

        except ImportError:
            logger.info("LXMF library not available - RPC features disabled")
            return False
        except Exception as e:
            logger.error(f"LXMF initialization error: {e}")
            return False

    def shutdown(self) -> None:
        """Shutdown all core services and clean up resources."""
        if not self._initialized:
            logger.debug("Not initialized, nothing to shutdown")
            return

        try:
            logger.info("Shutting down core services...")

            # Stop device discovery
            from styrened.services.reticulum import stop_discovery

            stop_discovery()

            # Shutdown LXMF service
            try:
                from styrened.services.lxmf_service import get_lxmf_service

                lxmf_service = get_lxmf_service()
                lxmf_service.shutdown()
            except Exception as e:
                logger.warning(f"LXMF shutdown error: {e}")

            # Shutdown RNS service
            rns_service = get_rns_service()
            rns_service.shutdown()

            # Clean up temporary RNS config directory
            if self._rns_config_dir and self._rns_config_dir.exists():
                try:
                    shutil.rmtree(self._rns_config_dir, ignore_errors=True)
                    logger.debug(f"Cleaned up RNS config dir: {self._rns_config_dir}")
                except Exception as e:
                    logger.warning(f"Failed to clean up RNS config dir: {e}")
                # Remove from atexit tracker
                _temp_config_dirs.discard(self._rns_config_dir)
                self._rns_config_dir = None

            self._initialized = False
            logger.info("Core services shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
