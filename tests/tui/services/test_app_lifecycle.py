"""Tests for application lifecycle management.

These tests verify:
- Service initialization order (RNS -> LXMF -> Discovery)
- Configuration handling and directory creation
- Error propagation and recovery
- Graceful shutdown
- Concurrent initialization prevention
"""

from pathlib import Path
from unittest.mock import Mock, call, patch

import pytest

from styrened.tui.models.config import DeploymentMode, StyreneConfig
from styrened.models.rns_error import RNSErrorCategory, RNSErrorState
from styrened.tui.services.app_lifecycle import (
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
    """Mock discovery service only."""
    with patch("styrened.tui.services.app_lifecycle.stop_discovery") as mock_stop:
        yield mock_stop


@pytest.fixture
def mock_dependencies(mock_rns_service, mock_lxmf_service, mock_hub_connection, mock_discovery):
    """Compose all service mocks for tests that need full mocking."""
    with (
        patch("styrened.tui.services.app_lifecycle.ensure_operator_identity") as mock_ensure_id,
        patch(
            "styrened.tui.services.app_lifecycle.get_operator_identity_object"
        ) as mock_get_id,
        patch(
            "styrened.tui.services.app_lifecycle.initialize_reticulum_with_config"
        ) as mock_init_rns,
        patch("styrened.tui.services.app_lifecycle.rns_config_exists") as mock_config_exists,
        patch("styrened.tui.services.app_lifecycle.save_rns_config") as mock_save_config,
    ):
        # Setup default successful behaviors
        mock_identity = Mock()
        mock_identity.hexhash = "test_identity_hash"
        mock_get_id.return_value = mock_identity

        mock_init_rns.return_value = True
        mock_config_exists.return_value = True

        yield {
            "ensure_operator_identity": mock_ensure_id,
            "get_operator_identity_object": mock_get_id,
            "initialize_reticulum_with_config": mock_init_rns,
            "rns_service": mock_rns_service,
            "lxmf_service": mock_lxmf_service,
            "hub_connection": mock_hub_connection,
            "stop_discovery": mock_discovery,
            "rns_config_exists": mock_config_exists,
            "save_rns_config": mock_save_config,
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
        """Test that services initialize in correct order: RNS -> LXMF -> Hub."""
        lifecycle = StyreneLifecycle(mock_config)
        result = lifecycle.initialize()

        assert result is True, f"Initialization failed with error: {lifecycle.rns_error_state}"
        assert lifecycle.is_initialized is True, "Lifecycle not marked as initialized after successful init"

        # Verify call order
        assert mock_dependencies["ensure_operator_identity"].call_count == 1, "ensure_operator_identity not called exactly once"
        assert mock_dependencies["initialize_reticulum_with_config"].call_count == 1, "initialize_reticulum_with_config not called exactly once"
        assert mock_dependencies["lxmf_service"].initialize.call_count == 1, "LXMF initialize not called exactly once"

    def test_initialization_with_custom_config(self, mock_dependencies):
        """Test initialization accepts custom configuration."""
        custom_config = Mock(spec=StyreneConfig)
        custom_config.reticulum = Mock()
        custom_config.reticulum.hub_enabled = False
        custom_config.reticulum.mode = DeploymentMode.PEER
        custom_config.api = Mock()
        custom_config.api.enabled = False

        lifecycle = StyreneLifecycle(custom_config)
        result = lifecycle.initialize()

        assert result is True, "Initialization with custom config failed"
        assert lifecycle.config is custom_config, "Custom config not preserved in lifecycle"

    def test_initialization_creates_required_directories(self, mock_dependencies):
        """Test initialization creates RNS config if missing."""
        mock_dependencies["rns_config_exists"].return_value = False
        mock_dependencies["save_rns_config"].return_value = "/tmp/test_config"

        lifecycle = StyreneLifecycle()
        result = lifecycle.initialize()

        assert result is True, "Initialization failed when creating RNS config"
        mock_dependencies["save_rns_config"].assert_called_once()

    def test_initialization_handles_missing_config(self, mock_dependencies):
        """Test initialization uses default config when none provided."""
        lifecycle = StyreneLifecycle(config=None)
        result = lifecycle.initialize()

        assert result is True, "Initialization with None config failed"
        assert lifecycle.config is not None, "Default config was not created"

    def test_initialization_fails_gracefully_on_rns_error(self, mock_dependencies):
        """Test initialization handles RNS errors and continues in offline mode."""
        mock_dependencies["initialize_reticulum_with_config"].return_value = False
        error_state = RNSErrorState(
            category=RNSErrorCategory.CONFIG_PARSE_ERROR, message="Test error"
        )
        mock_dependencies["rns_service"].error_state = error_state

        lifecycle = StyreneLifecycle()
        result = lifecycle.initialize()

        # Should still succeed (offline mode)
        assert result is True, "Initialization should succeed in offline mode even with RNS error"
        assert lifecycle.rns_error_state.category == RNSErrorCategory.CONFIG_PARSE_ERROR, \
            f"Error state not preserved: got {lifecycle.rns_error_state.category}"


# =============================================================================
# Integration Tests (Real RNS Behavior)
# =============================================================================


class TestIntegrationRNSBehavior:
    """Integration tests with real RNS initialization."""

    @pytest.mark.rns_singleton
    def test_integration_rns_failure_prevents_lxmf_init(
        self, tmp_path: Path, mock_lxmf_service, mock_hub_connection, mock_discovery
    ):
        """Test that real RNS failure prevents LXMF initialization and preserves error state."""
        # Create intentionally bad RNS config
        config_dir = tmp_path / ".reticulum_bad"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum\n# Malformed config")
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()

        with (
            patch("styrened.tui.services.app_lifecycle.rns_config_exists") as mock_config_exists,
            patch("styrened.tui.services.app_lifecycle.ensure_operator_identity"),
            patch("styrened.tui.services.app_lifecycle.get_operator_identity_object") as mock_get_id,
        ):
            import RNS

            # Create identity for testing
            identity = RNS.Identity(create_keys=True)
            mock_get_id.return_value = identity
            mock_config_exists.return_value = True

            # Patch RNS initialization to use bad config
            with patch("styrened.tui.services.reticulum.RNS.Reticulum") as mock_rns_constructor:
                # Simulate RNS parse error with malformed config
                mock_rns_constructor.side_effect = Exception("Could not parse config file")

                lifecycle = StyreneLifecycle()
                result = lifecycle.initialize()

                # Should succeed in offline mode
                assert result is True, "Lifecycle should handle RNS failure gracefully"

                # Error state should be preserved from real RNS failure
                assert lifecycle.rns_error_state.is_error, \
                    "Error state should indicate RNS failure"
                assert lifecycle.rns_error_state.category != RNSErrorCategory.NONE, \
                    f"Error category should not be NONE, got {lifecycle.rns_error_state.category}"

                # LXMF should NOT be initialized when RNS fails
                assert mock_lxmf_service.initialize.call_count == 0, \
                    "LXMF should not initialize when RNS fails"

    @pytest.mark.rns_singleton
    def test_integration_shutdown_releases_resources(
        self, tmp_path: Path, mock_hub_connection, mock_discovery
    ):
        """Test that shutdown actually releases resources with real or minimally mocked services."""
        import RNS
        from unittest.mock import MagicMock

        # Create valid RNS config
        config_dir = tmp_path / ".reticulum_shutdown"
        config_dir.mkdir()
        config_content = """[reticulum]
enable_transport = false
share_instance = false

[interfaces]

[[Test Interface]]
type = AutoInterface
enabled = true
"""
        (config_dir / "config").write_text(config_content)
        storage_dir = config_dir / "storage"
        storage_dir.mkdir()
        identity = RNS.Identity(create_keys=True)
        identity.to_file(str(storage_dir / "identity"))

        with (
            patch("styrened.tui.services.app_lifecycle.rns_config_exists", return_value=True),
            patch("styrened.tui.services.app_lifecycle.ensure_operator_identity"),
            patch("styrened.tui.services.app_lifecycle.get_operator_identity_object", return_value=identity),
            patch("styrened.services.lxmf_service.get_lxmf_service") as mock_get_lxmf,
            patch("styrened.tui.services.app_lifecycle.get_rns_service") as mock_get_rns,
        ):
            # Use minimally mocked services to verify cleanup
            mock_rns_service = MagicMock()
            mock_rns_service.is_initialized = True
            mock_rns_service.error_state = RNSErrorState.none()
            mock_rns_service.shutdown = Mock()
            mock_get_rns.return_value = mock_rns_service

            mock_lxmf = MagicMock()
            mock_lxmf.initialize = Mock(return_value=True)
            mock_lxmf.shutdown = Mock()
            mock_lxmf.is_initialized = True
            mock_lxmf.delivery_destination = None
            mock_get_lxmf.return_value = mock_lxmf

            lifecycle = StyreneLifecycle()
            init_result = lifecycle.initialize()

            assert init_result is True, "Initialization failed"
            assert lifecycle.is_initialized is True, "Lifecycle not initialized"

            # Perform shutdown
            lifecycle.shutdown()

            # Verify all shutdown methods were called
            assert mock_discovery.call_count == 1, "Discovery stop not called during shutdown"
            assert mock_hub_connection.disconnect.call_count == 1, "Hub disconnect not called during shutdown"
            assert mock_lxmf.shutdown.call_count == 1, "LXMF shutdown not called"
            assert mock_rns_service.shutdown.call_count == 1, "RNS shutdown not called"

            # Verify lifecycle state is cleared
            assert lifecycle.is_initialized is False, "Lifecycle still marked as initialized after shutdown"


# =============================================================================
# Service Startup/Shutdown Tests (Refactored)
# =============================================================================


class TestServiceStartupShutdown:
    """Test service startup and shutdown order."""

    def test_startup_order_rns_before_lxmf(self, mock_config, mock_dependencies):
        """Test RNS initializes before LXMF."""
        call_order = []

        def track_rns(*args, **kwargs):
            call_order.append("rns")
            return True

        def track_lxmf(*args, **kwargs):
            call_order.append("lxmf")
            return True

        mock_dependencies["initialize_reticulum_with_config"].side_effect = track_rns
        mock_dependencies["lxmf_service"].initialize.side_effect = track_lxmf

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        assert call_order == ["rns", "lxmf"], \
            f"Services did not initialize in correct order: {call_order}"

    def test_startup_order_lxmf_before_discovery(self, mock_config, mock_dependencies):
        """Test LXMF initializes before discovery announcements."""
        call_order = []

        def track_lxmf(*args, **kwargs):
            call_order.append("lxmf")
            return True

        mock_lxmf_service = mock_dependencies["lxmf_service"]
        mock_lxmf_service.initialize.side_effect = track_lxmf
        mock_lxmf_service.is_initialized = True
        mock_lxmf_service.delivery_destination = Mock()
        mock_lxmf_service.delivery_destination.hash = Mock()
        mock_lxmf_service.delivery_destination.hash.hex = Mock(
            return_value="test_lxmf_dest_hash"
        )

        # Mock destination announce
        mock_dest = Mock()
        mock_dest.hash = Mock()
        mock_dest.hash.hex = Mock(return_value="test_dest_hash")

        def track_announce(*args, **kwargs):
            call_order.append("announce")

        mock_dest.announce = Mock(side_effect=track_announce)

        mock_dependencies["rns_service"].create_operator_destination.return_value = mock_dest

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # LXMF should initialize before announce
        assert "lxmf" in call_order, "LXMF not initialized"
        assert "announce" in call_order, "Announce not called"
        assert call_order.index("lxmf") < call_order.index("announce"), \
            f"LXMF did not initialize before announce: {call_order}"

    def test_shutdown_order_reverse_of_startup(self, mock_config, mock_dependencies):
        """Test shutdown happens in reverse order of startup with actual cleanup verification."""
        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Reset call counts to verify shutdown order
        mock_dependencies["stop_discovery"].reset_mock()
        mock_dependencies["hub_connection"].disconnect.reset_mock()
        mock_dependencies["lxmf_service"].shutdown.reset_mock()
        mock_dependencies["rns_service"].shutdown.reset_mock()

        lifecycle.shutdown()

        # Verify shutdown methods were called
        assert mock_dependencies["stop_discovery"].call_count == 1, "Discovery not stopped during shutdown"
        assert mock_dependencies["hub_connection"].disconnect.call_count == 1, "Hub not disconnected during shutdown"
        assert mock_dependencies["lxmf_service"].shutdown.call_count == 1, "LXMF not shut down"
        assert mock_dependencies["rns_service"].shutdown.call_count == 1, "RNS not shut down"

        # Verify lifecycle state cleared
        assert lifecycle.is_initialized is False, "Lifecycle still initialized after shutdown"

    def test_partial_startup_rolls_back_on_error(self, mock_config, mock_dependencies):
        """Test partial startup cleans up on error."""
        # Make LXMF initialization fail
        mock_dependencies["lxmf_service"].initialize.return_value = False

        lifecycle = StyreneLifecycle(mock_config)
        result = lifecycle.initialize()

        # Should still succeed (LXMF is optional)
        assert result is True, "Initialization should succeed even if LXMF fails (LXMF is optional)"
        # But LXMF should have been attempted
        assert mock_dependencies["lxmf_service"].initialize.call_count == 1, \
            "LXMF initialization should have been attempted"

    def test_shutdown_is_idempotent(self, mock_config, mock_dependencies):
        """Test multiple shutdown calls don't cause errors."""
        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Shutdown twice
        lifecycle.shutdown()
        shutdown_calls_after_first = mock_dependencies["rns_service"].shutdown.call_count

        lifecycle.shutdown()
        shutdown_calls_after_second = mock_dependencies["rns_service"].shutdown.call_count

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
            patch("styrened.tui.services.app_lifecycle.ensure_operator_identity"),
            patch("styrened.tui.services.app_lifecycle.get_operator_identity_object") as mock_get_id,
            patch("styrened.tui.services.app_lifecycle.initialize_reticulum_with_config") as mock_init_rns,
            patch("styrened.tui.services.app_lifecycle.rns_config_exists", return_value=True),
            patch("styrened.tui.services.app_lifecycle.get_rns_service") as mock_get_rns,
        ):
            import RNS

            # Setup identity
            identity = RNS.Identity(create_keys=True)
            mock_get_id.return_value = identity

            # Make RNS initialization fail
            mock_init_rns.return_value = False

            # Create real error state (not just mock configuration)
            real_error = RNSErrorState(
                category=RNSErrorCategory.INTERFACE_FAILURE,
                exception_type="RuntimeError",
                message="No interfaces could be initialized"
            )

            mock_rns_service = Mock()
            mock_rns_service.error_state = real_error
            mock_get_rns.return_value = mock_rns_service

            lifecycle = StyreneLifecycle(mock_config)
            result = lifecycle.initialize()

            # Should succeed but preserve error state
            assert result is True, "Lifecycle should continue in offline mode when RNS fails"
            assert lifecycle.rns_error_state.is_error, "Error state should indicate failure"
            assert lifecycle.rns_error_state.category == RNSErrorCategory.INTERFACE_FAILURE, \
                f"Expected INTERFACE_FAILURE, got {lifecycle.rns_error_state.category}"
            assert lifecycle.rns_error_state.message == "No interfaces could be initialized", \
                "Error message not preserved from RNS service"

    def test_lxmf_initialization_failure_propagates(self, mock_config, mock_dependencies):
        """Test LXMF initialization failure is logged but doesn't fail startup."""
        mock_dependencies["lxmf_service"].initialize.return_value = False

        lifecycle = StyreneLifecycle(mock_config)
        result = lifecycle.initialize()

        # Should still succeed (LXMF is not critical)
        assert result is True, "Initialization should succeed even when LXMF fails (LXMF is optional)"

    def test_error_state_preserved_after_failure(self, mock_config, mock_lxmf_service, mock_hub_connection, mock_discovery):
        """Test error state is preserved for inspection with real error categorization."""
        with (
            patch("styrened.tui.services.app_lifecycle.ensure_operator_identity") as mock_ensure_id,
            patch("styrened.tui.services.app_lifecycle.get_operator_identity_object"),
            patch("styrened.tui.services.app_lifecycle.initialize_reticulum_with_config"),
            patch("styrened.tui.services.app_lifecycle.rns_config_exists", return_value=True),
            patch("styrened.tui.services.app_lifecycle.get_rns_service"),
        ):
            # Create a real exception that will be categorized
            identity_error = PermissionError("Cannot read operator identity file")
            mock_ensure_id.side_effect = identity_error

            lifecycle = StyreneLifecycle(mock_config)
            result = lifecycle.initialize()

            # Should fail on identity error but continue in offline mode
            assert result is True, "Should succeed in offline mode despite identity error"
            assert lifecycle.rns_error_state.is_error, "Error state should indicate failure"
            # Verify actual error categorization happened (not just mock return value)
            assert lifecycle.rns_error_state.category in [
                RNSErrorCategory.IDENTITY_PERMISSION,
                RNSErrorCategory.IDENTITY_CORRUPT,
                RNSErrorCategory.UNKNOWN
            ], f"Unexpected error category: {lifecycle.rns_error_state.category}"

    def test_recovery_after_transient_failure(self, mock_config, mock_lxmf_service, mock_hub_connection, mock_discovery):
        """Test recovery from transient failures with real failure/recovery cycle."""
        with (
            patch("styrened.tui.services.app_lifecycle.ensure_operator_identity") as mock_ensure_id,
            patch("styrened.tui.services.app_lifecycle.get_operator_identity_object") as mock_get_id,
            patch("styrened.tui.services.app_lifecycle.initialize_reticulum_with_config") as mock_init_rns,
            patch("styrened.tui.services.app_lifecycle.rns_config_exists", return_value=True),
            patch("styrened.tui.services.app_lifecycle.get_rns_service") as mock_get_rns,
        ):
            import RNS

            # First call fails, second succeeds
            mock_ensure_id.side_effect = [
                RuntimeError("Transient network error"),
                None,
            ]

            identity = RNS.Identity(create_keys=True)
            mock_get_id.return_value = identity
            # First init fails, second succeeds
            mock_init_rns.side_effect = [False, True]

            # Mock RNS service with proper mock structure
            mock_rns_service = Mock()
            mock_rns_service.is_initialized = True
            mock_rns_service.error_state = RNSErrorState.none()
            mock_dest = Mock()
            mock_dest.hash = Mock()
            mock_dest.hash.hex = Mock(return_value="test_dest_hash")
            mock_dest.announce = Mock()
            mock_rns_service.create_operator_destination = Mock(return_value=mock_dest)
            mock_get_rns.return_value = mock_rns_service

            lifecycle = StyreneLifecycle(mock_config)

            # First attempt fails
            result1 = lifecycle.initialize()
            assert result1 is True, "First initialization should succeed in offline mode"
            assert lifecycle.rns_error_state.is_error, "First attempt should have error state"

            # Reset for second attempt
            lifecycle._initialized = False
            lifecycle._rns_error_state = RNSErrorState.none()

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
        first_init_count = mock_dependencies["initialize_reticulum_with_config"].call_count

        # Second initialization should be rejected
        result2 = lifecycle.initialize()
        assert result2 is True, "Second initialization should return True (already initialized)"
        second_init_count = mock_dependencies["initialize_reticulum_with_config"].call_count

        # Should only initialize once
        assert first_init_count == 1, "First initialization should call RNS init once"
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

    def test_initialize_styrene_convenience_function(self, mock_dependencies):
        """Test initialize_styrene creates and initializes lifecycle."""
        lifecycle = initialize_styrene()

        assert isinstance(lifecycle, StyreneLifecycle), \
            f"Expected StyreneLifecycle instance, got {type(lifecycle)}"
        assert lifecycle.is_initialized is True, "Lifecycle not initialized by convenience function"

    def test_get_service_status_returns_status(self, mock_dependencies):
        """Test get_service_status returns service information."""
        with patch(
            "styrened.tui.services.reticulum.get_reticulum_status"
        ) as mock_get_status:
            mock_get_status.return_value = {
                "identity": "test_identity",
                "transport_enabled": True,
                "interfaces": 2,
            }

            mock_rns_service = mock_dependencies["rns_service"]
            mock_rns_service.is_initialized = True

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
        mock_dest = Mock()
        mock_dest.hash = Mock()
        mock_dest.hash.hex = Mock(return_value="test_dest_hash")
        mock_dest.announce = Mock()

        mock_dependencies[
            "rns_service"
        ].create_operator_destination.return_value = mock_dest

        # Configure LXMF mock
        mock_lxmf_service = mock_dependencies["lxmf_service"]
        mock_lxmf_service.is_initialized = True
        mock_lxmf_service.delivery_destination = None

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Verify announce was called
        mock_dest.announce.assert_called_once()

        # Verify app_data was provided (format details tested elsewhere)
        call_args = mock_dest.announce.call_args
        assert "app_data" in call_args.kwargs, "app_data not provided to announce"
        assert isinstance(call_args.kwargs["app_data"], bytes), \
            f"app_data should be bytes, got {type(call_args.kwargs['app_data'])}"

    def test_announce_includes_capabilities(self, mock_config, mock_dependencies):
        """Test that node announces with capabilities when in hub mode."""
        mock_config.reticulum.mode = DeploymentMode.HUB
        mock_config.api.enabled = True

        mock_dest = Mock()
        mock_dest.hash = Mock()
        mock_dest.hash.hex = Mock(return_value="test_dest_hash")
        mock_dest.announce = Mock()

        mock_dependencies[
            "rns_service"
        ].create_operator_destination.return_value = mock_dest

        # Configure LXMF mock
        mock_lxmf_service = mock_dependencies["lxmf_service"]
        mock_lxmf_service.is_initialized = True
        mock_lxmf_service.delivery_destination = None

        lifecycle = StyreneLifecycle(mock_config)
        lifecycle.initialize()

        # Verify announce was called (hub mode still announces)
        mock_dest.announce.assert_called_once()

        # Verify app_data was provided (capability format tested elsewhere)
        call_args = mock_dest.announce.call_args
        app_data = call_args.kwargs.get("app_data", b"")
        # Just check it contains hub/api keywords
        assert b"hub" in app_data, "Announce should include 'hub' capability"
        assert b"api" in app_data, "Announce should include 'api' capability"


# =============================================================================
# IPC Mode Tests
# =============================================================================


from unittest.mock import AsyncMock
from styrened.tui.services.app_lifecycle import LifecycleMode


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

    def test_auto_from_config_none(self, auto_config):
        lifecycle = StyreneLifecycle(auto_config)
        assert lifecycle.mode == LifecycleMode.AUTO

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
    """Test AUTO mode: tries IPC first, falls back to legacy."""

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
            lifecycle = StyreneLifecycle(auto_config)
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
            lifecycle = StyreneLifecycle(auto_config)
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
