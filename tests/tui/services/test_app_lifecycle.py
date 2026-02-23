"""Tests for application lifecycle management.

These tests verify:
- Service initialization order (RNS -> LXMF -> Discovery)
- Configuration handling and directory creation
- Error propagation and recovery
- Graceful shutdown
- Concurrent initialization prevention
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from styrened.models.rns_error import RNSErrorCategory, RNSErrorState
from styrened.tui.models.config import DeploymentMode, StyreneConfig
from styrened.tui.services.app_lifecycle import (
    LifecycleMode,
    StyreneLifecycle,
    get_service_status,
    initialize_styrene,
)


@pytest.fixture
def mock_config():
    """Create mock Styrene configuration."""
    config = Mock(spec=StyreneConfig)
    config.core = Mock()
    config.reticulum = Mock()
    config.reticulum.hub_enabled = False
    config.reticulum.mode = DeploymentMode.PEER
    config.api = Mock()
    config.api.enabled = False
    config.tui = Mock()
    config.tui.use_ipc = False
    return config


# =============================================================================
# Focused Per-Service Fixtures (replacing tautological mock_dependencies)
# =============================================================================


@pytest.fixture
def mock_rns_service():
    """Mock RNS service only."""
    with patch("styrened.tui.services.app_lifecycle.get_rns_service") as mock_get_rns:
        mock_service = Mock()
        mock_service.is_initialized = True
        mock_service.error_state = RNSErrorState.none()
        mock_service.create_operator_destination = Mock(return_value=Mock())
        mock_service.shutdown = Mock()
        mock_get_rns.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_lxmf_service():
    """Mock LXMF service only."""
    with patch("styrened.services.lxmf_service.get_lxmf_service") as mock_get_lxmf:
        mock_service = Mock()
        mock_service.initialize = Mock(return_value=True)
        mock_service.shutdown = Mock()
        mock_service.is_initialized = True
        mock_service.delivery_destination = None
        mock_get_lxmf.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_hub_connection():
    """Mock hub connection only."""
    with patch("styrened.tui.services.app_lifecycle.get_hub_connection") as mock_get_hub:
        mock_conn = Mock()
        mock_conn.is_connected = False
        mock_conn.hub_address = None
        mock_conn.disconnect = Mock()
        mock_get_hub.return_value = mock_conn
        yield mock_conn


@pytest.fixture
def mock_discovery():
    """Mock discovery service (called inside CoreLifecycle.shutdown)."""
    with patch("styrened.services.reticulum.stop_discovery") as mock_stop:
        yield mock_stop


@pytest.fixture
def mock_dependencies(mock_rns_service, mock_lxmf_service, mock_hub_connection, mock_discovery):
    """Compose all service mocks for tests that need full mocking.

    StyreneLifecycle delegates to CoreLifecycle for init/shutdown, so we mock
    CoreLifecycle.initialize (returns True) and CoreLifecycle.shutdown (no-op)
    plus the TUI-layer functions still imported in app_lifecycle.
    """
    with (
        patch(
            "styrened.services.lifecycle.CoreLifecycle.initialize", return_value=True
        ) as mock_core_init,
        patch(
            "styrened.services.lifecycle.CoreLifecycle.shutdown"
        ) as mock_core_shutdown,
        patch(
            "styrened.tui.services.app_lifecycle.get_operator_identity_object"
        ) as mock_get_id,
    ):
        # Setup default successful behaviors
        mock_identity = Mock()
        mock_identity.hexhash = "test_identity_hash"
        mock_get_id.return_value = mock_identity

        # Mock destination for announce
        mock_dest = Mock()
        mock_dest.announce = Mock()
        mock_rns_service.get_or_create_destination = Mock(return_value=mock_dest)

        yield {
            "core_initialize": mock_core_init,
            "core_shutdown": mock_core_shutdown,
            "get_operator_identity_object": mock_get_id,
            "rns_service": mock_rns_service,
            "lxmf_service": mock_lxmf_service,
            "hub_connection": mock_hub_connection,
            "stop_discovery": mock_discovery,
            "announce_destination": mock_dest,
        }


@pytest.fixture
def real_rns_with_bad_config(tmp_path: Path):
    """Create real RNS config that will fail initialization."""
    config_dir = tmp_path / ".reticulum_bad"
    config_dir.mkdir()

    # Write intentionally malformed config
    (config_dir / "config").write_text("[reticulum\n# Missing closing bracket")

    storage_dir = config_dir / "storage"
    storage_dir.mkdir()

    return config_dir


@pytest.fixture
def real_rns_initialized(tmp_path: Path):
    """Create real RNS config that will succeed initialization."""
    import RNS

    config_dir = tmp_path / ".reticulum_good"
    config_dir.mkdir()

    # Write minimal valid config
    config_content = """[reticulum]
enable_transport = false
share_instance = false

[interfaces]

[[Test Interface]]
type = AutoInterface
enabled = true
"""
    (config_dir / "config").write_text(config_content)

    # Create storage directory with identity
    storage_dir = config_dir / "storage"
    storage_dir.mkdir()
    identity = RNS.Identity(create_keys=True)
    identity.to_file(str(storage_dir / "identity"))

    return config_dir


# =============================================================================
# Initialization Tests
# =============================================================================


class TestInitialization:
    """Test service initialization behavior."""

    def test_styrene_lifecycle_initializes_services_in_order(
        self, mock_config, mock_dependencies
    ):
        """Test that services initialize in correct order: core init -> announce -> hub."""
        lifecycle = StyreneLifecycle(mock_config)
        result = lifecycle.initialize()

        assert result is True, f"Initialization failed with error: {lifecycle.rns_error_state}"
        assert lifecycle.is_initialized is True, "Lifecycle not marked as initialized after successful init"

        # Verify CoreLifecycle.initialize was called
        assert mock_dependencies["core_initialize"].call_count == 1, "CoreLifecycle.initialize not called exactly once"

    def test_initialization_with_custom_config(self, mock_dependencies):
        """Test initialization accepts custom configuration."""
        custom_config = Mock(spec=StyreneConfig)
        custom_config.core = Mock()
        custom_config.reticulum = Mock()
        custom_config.reticulum.hub_enabled = False
        custom_config.reticulum.mode = DeploymentMode.PEER
        custom_config.api = Mock()
        custom_config.api.enabled = False
        custom_config.tui = Mock()
        custom_config.tui.use_ipc = False

        lifecycle = StyreneLifecycle(custom_config)
        result = lifecycle.initialize()

        assert result is True, "Initialization with custom config failed"
        assert lifecycle.config is custom_config, "Custom config not preserved in lifecycle"

    def test_initialization_delegates_to_core_lifecycle(self, mock_config, mock_dependencies):
        """Test initialization delegates to CoreLifecycle which handles config creation."""
        lifecycle = StyreneLifecycle(mock_config)
        result = lifecycle.initialize()

        assert result is True, "Initialization failed"
        mock_dependencies["core_initialize"].assert_called_once()

    def test_initialization_handles_missing_config(self, mock_dependencies):
        """Test initialization uses default config when none provided."""
        lifecycle = StyreneLifecycle(config=None, mode=LifecycleMode.LEGACY)
        result = lifecycle.initialize()

        assert result is True, "Initialization with None config failed"
        assert lifecycle.config is not None, "Default config was not created"

    def test_initialization_fails_gracefully_on_rns_error(self, mock_config, mock_dependencies):
        """Test initialization handles RNS errors and continues in offline mode."""
        # Make CoreLifecycle.initialize return False (simulating RNS failure)
        mock_dependencies["core_initialize"].return_value = False

        lifecycle = StyreneLifecycle(mock_config)

        # Set error state on the core lifecycle to simulate RNS error
        error_state = RNSErrorState(
            category=RNSErrorCategory.CONFIG_PARSE_ERROR, message="Test error"
        )
        lifecycle._core._rns_error_state = error_state

        result = lifecycle.initialize()

        # Should still succeed (offline mode)
        assert result is True, "Initialization should succeed in offline mode even with RNS error"
        assert lifecycle.rns_error_state.category == RNSErrorCategory.CONFIG_PARSE_ERROR, \
            f"Error state not preserved: got {lifecycle.rns_error_state.category}"


# =============================================================================
# Integration Tests (Real RNS Behavior)
# =============================================================================


class TestIntegrationRNSBehavior:
    """Integration tests with CoreLifecycle delegation."""

    def test_integration_rns_failure_preserves_error_state(
        self, mock_hub_connection, mock_discovery
    ):
        """Test that core init failure preserves error state in offline mode."""
        with (
            patch(
                "styrened.services.lifecycle.CoreLifecycle.initialize", return_value=False
            ),
            patch(
                "styrened.tui.services.app_lifecycle.get_operator_identity_object",
                return_value=None,
            ),
        ):
            lifecycle = StyreneLifecycle(mode=LifecycleMode.LEGACY)

            # Simulate error state set by CoreLifecycle during failed init
            lifecycle._core._rns_error_state = RNSErrorState(
                category=RNSErrorCategory.CONFIG_PARSE_ERROR,
                message="Could not parse config file",
            )

            result = lifecycle.initialize()

            # Should succeed in offline mode
            assert result is True, "Lifecycle should handle RNS failure gracefully"

            # Error state should be preserved
            assert lifecycle.rns_error_state.is_error, \
                "Error state should indicate RNS failure"
            assert lifecycle.rns_error_state.category != RNSErrorCategory.NONE, \
                f"Error category should not be NONE, got {lifecycle.rns_error_state.category}"

    def test_integration_shutdown_releases_resources(
        self, mock_hub_connection, mock_discovery
    ):
        """Test that shutdown delegates to CoreLifecycle.shutdown and disconnects hub."""
        with (
            patch(
                "styrened.services.lifecycle.CoreLifecycle.initialize", return_value=True
            ),
            patch(
                "styrened.services.lifecycle.CoreLifecycle.shutdown"
            ) as mock_core_shutdown,
            patch(
                "styrened.tui.services.app_lifecycle.get_operator_identity_object",
                return_value=None,
            ),
        ):
            lifecycle = StyreneLifecycle(mode=LifecycleMode.LEGACY)
            init_result = lifecycle.initialize()

            assert init_result is True, "Initialization failed"
            assert lifecycle.is_initialized is True, "Lifecycle not initialized"

            # Perform shutdown
            lifecycle.shutdown()

            # Verify shutdown methods were called
            assert mock_core_shutdown.call_count == 1, "CoreLifecycle.shutdown not called during shutdown"
            assert mock_hub_connection.disconnect.call_count == 1, "Hub disconnect not called during shutdown"

            # Verify lifecycle state is cleared
            assert lifecycle.is_initialized is False, "Lifecycle still marked as initialized after shutdown"


# =============================================================================
# Service Startup/Shutdown Tests (Refactored)
# =============================================================================


class TestServiceStartupShutdown:
    """Test service startup and shutdown order."""

    def test_startup_core_init_before_announce(self, mock_config, mock_dependencies):
        """Test CoreLifecycle.initialize runs before TUI-layer announce."""
        call_order = []

        def track_core_init(*args, **kwargs):
            call_order.append("core_init")
            return True

        def track_announce(*args, **kwargs):
            call_order.append("announce")

        mock_dependencies["core_initialize"].side_effect = track_core_init
        mock_dependencies["announce_destination"].announce = Mock(side_effect=track_announce)

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        assert "core_init" in call_order, "CoreLifecycle.initialize not called"
        assert "announce" in call_order, "Announce not called"
        assert call_order.index("core_init") < call_order.index("announce"), \
            f"Core init did not run before announce: {call_order}"

    def test_startup_order_core_init_before_announce(self, mock_config, mock_dependencies):
        """Test core initialization happens before Styrene node announcement."""
        call_order = []

        def track_core_init(*args, **kwargs):
            call_order.append("core_init")
            return True

        mock_dependencies["core_initialize"].side_effect = track_core_init

        # Track announce via the destination mock
        mock_dest = mock_dependencies["announce_destination"]

        def track_announce(*args, **kwargs):
            call_order.append("announce")

        mock_dest.announce = Mock(side_effect=track_announce)

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Core init should happen before announce
        assert "core_init" in call_order, "Core init not called"
        assert "announce" in call_order, "Announce not called"
        assert call_order.index("core_init") < call_order.index("announce"), \
            f"Core init did not run before announce: {call_order}"

    def test_shutdown_calls_core_and_hub(self, mock_config, mock_dependencies):
        """Test shutdown delegates to CoreLifecycle.shutdown and disconnects hub."""
        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Reset call counts to verify shutdown
        mock_dependencies["core_shutdown"].reset_mock()
        mock_dependencies["hub_connection"].disconnect.reset_mock()

        lifecycle.shutdown()

        # Verify shutdown methods were called
        assert mock_dependencies["core_shutdown"].call_count == 1, "CoreLifecycle.shutdown not called"
        assert mock_dependencies["hub_connection"].disconnect.call_count == 1, "Hub not disconnected during shutdown"

        # Verify lifecycle state cleared
        assert lifecycle.is_initialized is False, "Lifecycle still initialized after shutdown"

    def test_partial_startup_continues_on_core_failure(self, mock_config, mock_dependencies):
        """Test initialization enters offline mode when core init fails."""
        # Make CoreLifecycle.initialize return False
        mock_dependencies["core_initialize"].return_value = False

        lifecycle = StyreneLifecycle(mock_config)
        result = lifecycle.initialize()

        # Should still succeed (offline mode)
        assert result is True, "Initialization should succeed in offline mode even if core init fails"
        assert mock_dependencies["core_initialize"].call_count == 1, \
            "CoreLifecycle.initialize should have been attempted"

    def test_shutdown_is_idempotent(self, mock_config, mock_dependencies):
        """Test multiple shutdown calls don't cause errors."""
        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Shutdown twice
        lifecycle.shutdown()
        shutdown_calls_after_first = mock_dependencies["core_shutdown"].call_count

        lifecycle.shutdown()
        shutdown_calls_after_second = mock_dependencies["core_shutdown"].call_count

        # No errors should occur
        assert lifecycle.is_initialized is False, "Lifecycle should be marked as not initialized"
        # Second shutdown should not call shutdown again (already not initialized)
        assert shutdown_calls_after_first == shutdown_calls_after_second, \
            "Shutdown was called again even though already shut down"


# =============================================================================
# Error Propagation Tests (Refactored to Reduce Mock Depth)
# =============================================================================


class TestErrorPropagation:
    """Test error handling and propagation with reduced mock depth."""

    def test_rns_initialization_failure_propagates(self, mock_config, mock_lxmf_service, mock_hub_connection, mock_discovery):
        """Test RNS initialization failure is captured with real error state propagation."""
        with (
            patch(
                "styrened.services.lifecycle.CoreLifecycle.initialize", return_value=False
            ),
            patch(
                "styrened.tui.services.app_lifecycle.get_operator_identity_object",
                return_value=None,
            ),
        ):
            lifecycle = StyreneLifecycle(mock_config)

            # Simulate error state set by CoreLifecycle during failed init
            real_error = RNSErrorState(
                category=RNSErrorCategory.INTERFACE_FAILURE,
                exception_type="RuntimeError",
                message="No interfaces could be initialized"
            )
            lifecycle._core._rns_error_state = real_error

            result = lifecycle.initialize()

            # Should succeed but preserve error state
            assert result is True, "Lifecycle should continue in offline mode when RNS fails"
            assert lifecycle.rns_error_state.is_error, "Error state should indicate failure"
            assert lifecycle.rns_error_state.category == RNSErrorCategory.INTERFACE_FAILURE, \
                f"Expected INTERFACE_FAILURE, got {lifecycle.rns_error_state.category}"
            assert lifecycle.rns_error_state.message == "No interfaces could be initialized", \
                "Error message not preserved from RNS service"

    def test_core_init_failure_does_not_crash_startup(self, mock_config, mock_dependencies):
        """Test core initialization failure enters offline mode without crashing."""
        mock_dependencies["core_initialize"].return_value = False

        lifecycle = StyreneLifecycle(mock_config)
        result = lifecycle.initialize()

        # Should still succeed (offline mode)
        assert result is True, "Initialization should succeed in offline mode even when core init fails"

    def test_error_state_preserved_after_failure(self, mock_config, mock_dependencies):
        """Test error state is preserved for inspection after core init failure."""
        # Make CoreLifecycle.initialize return False
        mock_dependencies["core_initialize"].return_value = False

        lifecycle = StyreneLifecycle(mock_config)

        # Simulate RNS error state set by CoreLifecycle during failed init
        error_state = RNSErrorState(
            category=RNSErrorCategory.IDENTITY_PERMISSION,
            message="Cannot read operator identity file",
        )
        lifecycle._core._rns_error_state = error_state

        result = lifecycle.initialize()

        # Should succeed in offline mode but preserve error state
        assert result is True, "Should succeed in offline mode despite core failure"
        assert lifecycle.rns_error_state.is_error, "Error state should indicate failure"
        assert lifecycle.rns_error_state.category == RNSErrorCategory.IDENTITY_PERMISSION, \
            f"Unexpected error category: {lifecycle.rns_error_state.category}"

    def test_recovery_after_transient_failure(self, mock_config, mock_dependencies):
        """Test recovery from transient failures with failure/recovery cycle."""
        # First call fails, second succeeds
        mock_dependencies["core_initialize"].side_effect = [False, True]

        lifecycle = StyreneLifecycle(mock_config)

        # Simulate error state from first failure
        error_state = RNSErrorState(
            category=RNSErrorCategory.INTERFACE_FAILURE,
            message="Transient network error",
        )
        lifecycle._core._rns_error_state = error_state

        # First attempt enters offline mode
        result1 = lifecycle.initialize()
        assert result1 is True, "First initialization should succeed in offline mode"
        assert lifecycle.rns_error_state.is_error, "First attempt should have error state"

        # Reset for second attempt
        lifecycle._initialized = False
        lifecycle._core._rns_error_state = RNSErrorState.none()

        # Second attempt should succeed
        result2 = lifecycle.initialize()
        assert result2 is True, "Second initialization should succeed"
        assert not lifecycle.rns_error_state.is_error, \
            f"Second attempt should clear error state, got {lifecycle.rns_error_state.category}"

    def test_concurrent_initialization_attempts_rejected(
        self, mock_config, mock_dependencies
    ):
        """Test concurrent initialization attempts are rejected without re-initializing."""
        lifecycle = StyreneLifecycle(mock_config)

        # First initialization
        result1 = lifecycle.initialize()
        assert result1 is True, "First initialization failed"
        first_init_count = mock_dependencies["core_initialize"].call_count

        # Second initialization should be rejected
        result2 = lifecycle.initialize()
        assert result2 is True, "Second initialization should return True (already initialized)"
        second_init_count = mock_dependencies["core_initialize"].call_count

        # Should only initialize once
        assert first_init_count == 1, "First initialization should call core init once"
        assert second_init_count == 1, \
            f"Concurrent initialization should not re-initialize (call count: {second_init_count})"


# =============================================================================
# Hub Connection Tests
# =============================================================================


class TestHubConnection:
    """Test hub connection behavior."""

    def test_no_hub_connection_when_disabled(self, mock_config, mock_dependencies):
        """Test no hub connection when hub is disabled."""
        mock_config.reticulum.hub_enabled = False

        mock_hub = mock_dependencies["hub_connection"]
        mock_hub.connect = Mock()

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Hub connection should not be attempted
        mock_hub.connect.assert_not_called()

    def test_no_hub_connection_when_running_as_hub(
        self, mock_config, mock_dependencies
    ):
        """Test no hub connection when running in hub mode."""
        mock_config.reticulum.hub_enabled = True
        mock_config.reticulum.mode = DeploymentMode.HUB

        mock_hub = mock_dependencies["hub_connection"]
        mock_hub.connect = Mock()

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Hub connection should not be attempted (we are the hub)
        mock_hub.connect.assert_not_called()


# =============================================================================
# Utility Functions Tests
# =============================================================================


class TestUtilityFunctions:
    """Test module-level utility functions."""

    def test_initialize_styrene_convenience_function(self, mock_config, mock_dependencies):
        """Test initialize_styrene creates and initializes lifecycle."""
        lifecycle = initialize_styrene(mock_config)

        assert isinstance(lifecycle, StyreneLifecycle), \
            f"Expected StyreneLifecycle instance, got {type(lifecycle)}"
        assert lifecycle.is_initialized is True, "Lifecycle not initialized by convenience function"

    def test_get_service_status_returns_status(self, mock_dependencies):
        """Test get_service_status returns service information."""
        with patch(
            "styrened.tui.services.reticulum.get_reticulum_status"
        ) as mock_get_status:
            mock_get_status.return_value = {
                "running": True,
                "identity": "test_identity",
                "transport_enabled": True,
                "interfaces": 2,
            }

            mock_hub = mock_dependencies["hub_connection"]
            mock_hub.is_connected = False
            mock_hub.hub_address = None

            status = get_service_status()

            assert status["rns_initialized"] is True, "RNS should be initialized"
            assert status["hub_connected"] is False, "Hub should not be connected"
            assert status["operator_identity"] == "test_identity", \
                f"Unexpected operator identity: {status['operator_identity']}"
            assert status["transport_enabled"] is True, "Transport should be enabled"
            assert status["interface_count"] == 2, \
                f"Expected 2 interfaces, got {status['interface_count']}"


# =============================================================================
# Announce Tests
# =============================================================================


class TestAnnounce:
    """Test node announcement behavior."""

    def test_announce_includes_hostname(self, mock_config, mock_dependencies):
        """Test that node announces itself on initialization."""
        mock_dest = mock_dependencies["announce_destination"]
        mock_dest.announce = Mock()

        # Configure LXMF mock
        mock_lxmf_service = mock_dependencies["lxmf_service"]
        mock_lxmf_service.is_initialized = True
        mock_lxmf_service.delivery_destination = None

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Verify announce was called
        mock_dest.announce.assert_called_once()

        # Verify announce data is bytes (app_data passed as positional arg)
        call_args = mock_dest.announce.call_args
        assert len(call_args.args) > 0 or "app_data" in call_args.kwargs, \
            "announce data not provided to announce"
        announce_data = call_args.args[0] if call_args.args else call_args.kwargs.get("app_data")
        assert isinstance(announce_data, bytes), \
            f"announce data should be bytes, got {type(announce_data)}"

    def test_announce_includes_capabilities(self, mock_config, mock_dependencies):
        """Test that node announces with capabilities when in hub mode."""
        mock_config.reticulum.mode = DeploymentMode.HUB
        mock_config.api.enabled = True
        mock_config.rpc = Mock()
        mock_config.rpc.enabled = True
        mock_config.discovery = Mock()
        mock_config.discovery.enabled = True

        mock_dest = mock_dependencies["announce_destination"]
        mock_dest.announce = Mock()

        # Configure LXMF mock
        mock_lxmf_service = mock_dependencies["lxmf_service"]
        mock_lxmf_service.is_initialized = True
        mock_lxmf_service.delivery_destination = None

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Verify announce was called (hub mode still announces)
        mock_dest.announce.assert_called_once()

        # Verify announce data contains capability keywords
        call_args = mock_dest.announce.call_args
        announce_data = call_args.args[0] if call_args.args else call_args.kwargs.get("app_data", b"")
        assert b"rpc" in announce_data, "Announce should include 'rpc' capability"
        assert b"discovery" in announce_data, "Announce should include 'discovery' capability"


# =============================================================================
# IPC Mode Tests
# =============================================================================


@pytest.fixture
def mock_daemon_manager():
    """Mock DaemonManager for IPC tests."""
    mgr = AsyncMock()
    mgr.ensure_running = AsyncMock(return_value=True)
    mgr.shutdown = AsyncMock()
    mgr.socket_path = Path("/tmp/test.sock")
    return mgr


@pytest.fixture
def mock_ipc_bridge():
    """Mock IPCBridge for IPC tests."""
    bridge = AsyncMock()
    bridge.connect = AsyncMock(return_value=True)
    bridge.disconnect = AsyncMock()
    return bridge


@pytest.fixture
def ipc_config():
    """Config with use_ipc=True."""
    config = Mock(spec=StyreneConfig)
    config.core = Mock()
    config.reticulum = Mock()
    config.reticulum.hub_enabled = False
    config.reticulum.mode = DeploymentMode.PEER
    config.api = Mock()
    config.api.enabled = False
    config.tui = Mock()
    config.tui.use_ipc = True
    return config


@pytest.fixture
def auto_config():
    """Config with use_ipc=None (auto mode)."""
    config = Mock(spec=StyreneConfig)
    config.core = Mock()
    config.reticulum = Mock()
    config.reticulum.hub_enabled = False
    config.reticulum.mode = DeploymentMode.PEER
    config.api = Mock()
    config.api.enabled = False
    config.tui = Mock()
    config.tui.use_ipc = None
    return config


@pytest.fixture
def legacy_config():
    """Config with use_ipc=False."""
    config = Mock(spec=StyreneConfig)
    config.core = Mock()
    config.reticulum = Mock()
    config.reticulum.hub_enabled = False
    config.reticulum.mode = DeploymentMode.PEER
    config.api = Mock()
    config.api.enabled = False
    config.tui = Mock()
    config.tui.use_ipc = False
    return config


class TestLifecycleModeSelection:
    """Test lifecycle mode determined from config and explicit override."""

    def test_ipc_from_config(self, ipc_config):
        lifecycle = StyreneLifecycle(ipc_config)
        assert lifecycle.mode == LifecycleMode.IPC

    def test_legacy_from_config(self, legacy_config):
        lifecycle = StyreneLifecycle(legacy_config)
        assert lifecycle.mode == LifecycleMode.LEGACY

    def test_ipc_from_config_none(self, auto_config):
        """use_ipc=None defaults to IPC mode (TUI is a pure daemon client)."""
        lifecycle = StyreneLifecycle(auto_config)
        assert lifecycle.mode == LifecycleMode.IPC

    def test_explicit_mode_overrides_config(self, ipc_config):
        lifecycle = StyreneLifecycle(ipc_config, mode=LifecycleMode.LEGACY)
        assert lifecycle.mode == LifecycleMode.LEGACY


class TestIPCInitialization:
    """Test IPC mode async initialization."""

    @pytest.mark.asyncio
    async def test_creates_daemon_manager_and_bridge(
        self, ipc_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        with (
            patch(
                "styrened.tui.services.daemon_manager.DaemonManager",
                return_value=mock_daemon_manager,
            ),
            patch(
                "styrened.tui.services.ipc_bridge.IPCBridge",
                return_value=mock_ipc_bridge,
            ),
        ):
            lifecycle = StyreneLifecycle(ipc_config)
            result = await lifecycle.initialize_async()

        assert result is True
        assert lifecycle.active_mode == LifecycleMode.IPC
        assert lifecycle.is_initialized is True
        mock_daemon_manager.ensure_running.assert_called_once()
        mock_ipc_bridge.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_fails_if_daemon_not_running(
        self, ipc_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        mock_daemon_manager.ensure_running.return_value = False

        with (
            patch(
                "styrened.tui.services.daemon_manager.DaemonManager",
                return_value=mock_daemon_manager,
            ),
            patch(
                "styrened.tui.services.ipc_bridge.IPCBridge",
                return_value=mock_ipc_bridge,
            ),
        ):
            lifecycle = StyreneLifecycle(ipc_config)
            result = await lifecycle.initialize_async()

        assert result is False
        assert lifecycle.is_initialized is False
        assert lifecycle._daemon_manager is None

    @pytest.mark.asyncio
    async def test_fails_if_bridge_connect_fails(
        self, ipc_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        mock_ipc_bridge.connect.return_value = False

        with (
            patch(
                "styrened.tui.services.daemon_manager.DaemonManager",
                return_value=mock_daemon_manager,
            ),
            patch(
                "styrened.tui.services.ipc_bridge.IPCBridge",
                return_value=mock_ipc_bridge,
            ),
        ):
            lifecycle = StyreneLifecycle(ipc_config)
            result = await lifecycle.initialize_async()

        assert result is False
        assert lifecycle._ipc_bridge is None
        assert lifecycle._daemon_manager is None
        mock_daemon_manager.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleans_up_on_exception(
        self, ipc_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        mock_ipc_bridge.connect.side_effect = RuntimeError("boom")

        with (
            patch(
                "styrened.tui.services.daemon_manager.DaemonManager",
                return_value=mock_daemon_manager,
            ),
            patch(
                "styrened.tui.services.ipc_bridge.IPCBridge",
                return_value=mock_ipc_bridge,
            ),
        ):
            lifecycle = StyreneLifecycle(ipc_config)
            result = await lifecycle.initialize_async()

        assert result is False
        assert lifecycle._ipc_bridge is None
        assert lifecycle._daemon_manager is None

    def test_sync_initialize_rejects_ipc_mode(self, ipc_config):
        lifecycle = StyreneLifecycle(ipc_config)
        result = lifecycle.initialize()
        assert result is False
        assert lifecycle.is_initialized is False


class TestAutoMode:
    """Test AUTO mode: tries IPC first, falls back to legacy.

    AUTO mode is no longer the default (IPC is), but remains accessible
    via explicit mode override.
    """

    @pytest.mark.asyncio
    async def test_uses_ipc_when_available(
        self, auto_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        with (
            patch(
                "styrened.tui.services.daemon_manager.DaemonManager",
                return_value=mock_daemon_manager,
            ),
            patch(
                "styrened.tui.services.ipc_bridge.IPCBridge",
                return_value=mock_ipc_bridge,
            ),
        ):
            lifecycle = StyreneLifecycle(auto_config, mode=LifecycleMode.AUTO)
            result = await lifecycle.initialize_async()

        assert result is True
        assert lifecycle.active_mode == LifecycleMode.IPC

    @pytest.mark.asyncio
    async def test_falls_back_to_legacy(
        self, auto_config, mock_daemon_manager, mock_dependencies,
    ):
        mock_daemon_manager.ensure_running.return_value = False

        with (
            patch(
                "styrened.tui.services.daemon_manager.DaemonManager",
                return_value=mock_daemon_manager,
            ),
        ):
            lifecycle = StyreneLifecycle(auto_config, mode=LifecycleMode.AUTO)
            result = await lifecycle.initialize_async()

        assert result is True
        assert lifecycle.active_mode == LifecycleMode.LEGACY


class TestIPCShutdown:
    """Test IPC mode shutdown."""

    @pytest.mark.asyncio
    async def test_disconnects_bridge_and_daemon(
        self, ipc_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        with (
            patch(
                "styrened.tui.services.daemon_manager.DaemonManager",
                return_value=mock_daemon_manager,
            ),
            patch(
                "styrened.tui.services.ipc_bridge.IPCBridge",
                return_value=mock_ipc_bridge,
            ),
        ):
            lifecycle = StyreneLifecycle(ipc_config)
            await lifecycle.initialize_async()
            await lifecycle.shutdown_async()

        mock_ipc_bridge.disconnect.assert_called_once()
        mock_daemon_manager.shutdown.assert_called_once()
        assert lifecycle.is_initialized is False
        assert lifecycle._ipc_bridge is None
        assert lifecycle._daemon_manager is None

    @pytest.mark.asyncio
    async def test_clears_active_mode(
        self, ipc_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        with (
            patch(
                "styrened.tui.services.daemon_manager.DaemonManager",
                return_value=mock_daemon_manager,
            ),
            patch(
                "styrened.tui.services.ipc_bridge.IPCBridge",
                return_value=mock_ipc_bridge,
            ),
        ):
            lifecycle = StyreneLifecycle(ipc_config)
            await lifecycle.initialize_async()
            await lifecycle.shutdown_async()

        assert lifecycle.active_mode is None

    def test_sync_shutdown_warns_for_ipc(
        self, ipc_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        """Sync shutdown with IPC mode logs warning."""
        lifecycle = StyreneLifecycle(ipc_config)
        lifecycle._initialized = True
        lifecycle._active_mode = LifecycleMode.IPC
        lifecycle._ipc_bridge = mock_ipc_bridge
        lifecycle._daemon_manager = mock_daemon_manager

        lifecycle.shutdown()
        # Should not crash, just warn
        assert lifecycle.is_initialized is False


class TestIPCProperties:
    """Test IPC component property accessors."""

    def test_ipc_bridge_none_before_init(self, ipc_config):
        lifecycle = StyreneLifecycle(ipc_config)
        assert lifecycle.ipc_bridge is None

    def test_daemon_manager_none_before_init(self, ipc_config):
        lifecycle = StyreneLifecycle(ipc_config)
        assert lifecycle.daemon_manager is None

    @pytest.mark.asyncio
    async def test_ipc_bridge_accessible_after_init(
        self, ipc_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        with (
            patch(
                "styrened.tui.services.daemon_manager.DaemonManager",
                return_value=mock_daemon_manager,
            ),
            patch(
                "styrened.tui.services.ipc_bridge.IPCBridge",
                return_value=mock_ipc_bridge,
            ),
        ):
            lifecycle = StyreneLifecycle(ipc_config)
            await lifecycle.initialize_async()

        assert lifecycle.ipc_bridge is mock_ipc_bridge
        assert lifecycle.daemon_manager is mock_daemon_manager
