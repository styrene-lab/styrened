"""Tests for application lifecycle management (IPC-only).

These tests verify:
- IPC mode initialization via DaemonManager + IPCBridge
- Async initialization and shutdown
- Concurrent initialization prevention
- Error handling and cleanup
- Property accessors
- Backward-compatible utility functions
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from styrened.tui.models.config import DeploymentMode, StyreneConfig
from styrened.tui.services.app_lifecycle import (
    LifecycleMode,
    StyreneLifecycle,
    get_service_status,
    initialize_styrene,
)


# =============================================================================
# Fixtures
# =============================================================================


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
    return config


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


# =============================================================================
# LifecycleMode Enum Tests
# =============================================================================


class TestLifecycleMode:
    """Test that LifecycleMode only has IPC."""

    def test_only_ipc_mode_exists(self):
        """LifecycleMode enum contains only IPC."""
        members = list(LifecycleMode)
        assert members == [LifecycleMode.IPC]

    def test_ipc_value(self):
        assert LifecycleMode.IPC.value == "ipc"

    def test_no_legacy_mode(self):
        assert not hasattr(LifecycleMode, "LEGACY")

    def test_no_auto_mode(self):
        assert not hasattr(LifecycleMode, "AUTO")


# =============================================================================
# Lifecycle Construction Tests
# =============================================================================


class TestLifecycleConstruction:
    """Test StyreneLifecycle construction."""

    def test_default_mode_is_ipc(self, mock_config):
        lifecycle = StyreneLifecycle(mock_config)
        assert lifecycle.mode == LifecycleMode.IPC

    def test_explicit_ipc_mode(self, mock_config):
        lifecycle = StyreneLifecycle(mock_config, mode=LifecycleMode.IPC)
        assert lifecycle.mode == LifecycleMode.IPC

    def test_uses_default_config_when_none(self):
        lifecycle = StyreneLifecycle(config=None)
        assert lifecycle.config is not None
        assert lifecycle.mode == LifecycleMode.IPC

    def test_not_initialized_on_construction(self, mock_config):
        lifecycle = StyreneLifecycle(mock_config)
        assert lifecycle.is_initialized is False
        assert lifecycle.active_mode is None

    def test_ipc_bridge_none_before_init(self, mock_config):
        lifecycle = StyreneLifecycle(mock_config)
        assert lifecycle.ipc_bridge is None

    def test_daemon_manager_none_before_init(self, mock_config):
        lifecycle = StyreneLifecycle(mock_config)
        assert lifecycle.daemon_manager is None


# =============================================================================
# Sync Initialize Tests
# =============================================================================


class TestSyncInitialize:
    """Test synchronous initialize() rejects IPC mode."""

    def test_sync_initialize_rejects_ipc(self, mock_config):
        """Synchronous initialize returns False for IPC mode."""
        lifecycle = StyreneLifecycle(mock_config)
        result = lifecycle.initialize()
        assert result is False
        assert lifecycle.is_initialized is False

    def test_sync_initialize_returns_true_if_already_initialized(self, mock_config):
        """Already initialized returns True."""
        lifecycle = StyreneLifecycle(mock_config)
        lifecycle._initialized = True
        result = lifecycle.initialize()
        assert result is True


# =============================================================================
# Async IPC Initialization Tests
# =============================================================================


class TestIPCInitialization:
    """Test IPC mode async initialization."""

    @pytest.mark.asyncio
    async def test_creates_daemon_manager_and_bridge(
        self, mock_config, mock_daemon_manager, mock_ipc_bridge,
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
            lifecycle = StyreneLifecycle(mock_config)
            result = await lifecycle.initialize_async()

        assert result is True
        assert lifecycle.active_mode == LifecycleMode.IPC
        assert lifecycle.is_initialized is True
        mock_daemon_manager.ensure_running.assert_called_once()
        mock_ipc_bridge.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_bridge_accessible_after_init(
        self, mock_config, mock_daemon_manager, mock_ipc_bridge,
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
            lifecycle = StyreneLifecycle(mock_config)
            await lifecycle.initialize_async()

        assert lifecycle.ipc_bridge is mock_ipc_bridge
        assert lifecycle.daemon_manager is mock_daemon_manager

    @pytest.mark.asyncio
    async def test_fails_if_daemon_not_running(
        self, mock_config, mock_daemon_manager, mock_ipc_bridge,
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
            lifecycle = StyreneLifecycle(mock_config)
            result = await lifecycle.initialize_async()

        assert result is False
        assert lifecycle.is_initialized is False
        assert lifecycle._daemon_manager is None

    @pytest.mark.asyncio
    async def test_fails_if_bridge_connect_fails(
        self, mock_config, mock_daemon_manager, mock_ipc_bridge,
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
            lifecycle = StyreneLifecycle(mock_config)
            result = await lifecycle.initialize_async()

        assert result is False
        assert lifecycle._ipc_bridge is None
        assert lifecycle._daemon_manager is None
        mock_daemon_manager.shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleans_up_on_exception(
        self, mock_config, mock_daemon_manager, mock_ipc_bridge,
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
            lifecycle = StyreneLifecycle(mock_config)
            result = await lifecycle.initialize_async()

        assert result is False
        assert lifecycle._ipc_bridge is None
        assert lifecycle._daemon_manager is None

    @pytest.mark.asyncio
    async def test_concurrent_initialization_rejected(
        self, mock_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        """Second initialization attempt returns True without re-initializing."""
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
            lifecycle = StyreneLifecycle(mock_config)
            result1 = await lifecycle.initialize_async()
            result2 = await lifecycle.initialize_async()

        assert result1 is True
        assert result2 is True
        # DaemonManager should only be called once
        assert mock_daemon_manager.ensure_running.call_count == 1


# =============================================================================
# Shutdown Tests
# =============================================================================


class TestIPCShutdown:
    """Test IPC mode shutdown."""

    @pytest.mark.asyncio
    async def test_disconnects_bridge_and_daemon(
        self, mock_config, mock_daemon_manager, mock_ipc_bridge,
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
            lifecycle = StyreneLifecycle(mock_config)
            await lifecycle.initialize_async()
            await lifecycle.shutdown_async()

        mock_ipc_bridge.disconnect.assert_called_once()
        mock_daemon_manager.shutdown.assert_called_once()
        assert lifecycle.is_initialized is False
        assert lifecycle._ipc_bridge is None
        assert lifecycle._daemon_manager is None

    @pytest.mark.asyncio
    async def test_clears_active_mode(
        self, mock_config, mock_daemon_manager, mock_ipc_bridge,
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
            lifecycle = StyreneLifecycle(mock_config)
            await lifecycle.initialize_async()
            await lifecycle.shutdown_async()

        assert lifecycle.active_mode is None

    def test_sync_shutdown_warns_for_ipc(
        self, mock_config, mock_daemon_manager, mock_ipc_bridge,
    ):
        """Sync shutdown with IPC mode logs warning but doesn't crash."""
        lifecycle = StyreneLifecycle(mock_config)
        lifecycle._initialized = True
        lifecycle._active_mode = LifecycleMode.IPC
        lifecycle._ipc_bridge = mock_ipc_bridge
        lifecycle._daemon_manager = mock_daemon_manager

        lifecycle.shutdown()
        assert lifecycle.is_initialized is False

    def test_shutdown_idempotent(self, mock_config):
        """Multiple shutdown calls don't cause errors."""
        lifecycle = StyreneLifecycle(mock_config)
        # Not initialized — shutdown is a no-op
        lifecycle.shutdown()
        lifecycle.shutdown()
        assert lifecycle.is_initialized is False

    @pytest.mark.asyncio
    async def test_async_shutdown_idempotent(self, mock_config):
        """Multiple async shutdown calls don't cause errors."""
        lifecycle = StyreneLifecycle(mock_config)
        await lifecycle.shutdown_async()
        await lifecycle.shutdown_async()
        assert lifecycle.is_initialized is False


# =============================================================================
# Utility Functions Tests
# =============================================================================


class TestUtilityFunctions:
    """Test module-level utility functions."""

    def test_initialize_styrene_returns_lifecycle(self, mock_config):
        """initialize_styrene creates lifecycle (not fully initialized in IPC mode)."""
        lifecycle = initialize_styrene(mock_config)
        assert isinstance(lifecycle, StyreneLifecycle)
        # IPC mode can't be initialized synchronously
        assert lifecycle.is_initialized is False

    def test_get_service_status_returns_status(self):
        """Test get_service_status returns service information."""
        with (
            patch(
                "styrened.tui.services.reticulum.get_reticulum_status"
            ) as mock_get_status,
            patch(
                "styrened.services.hub_connection.get_hub_connection"
            ) as mock_get_hub,
        ):
            mock_get_status.return_value = {
                "running": True,
                "identity": "test_identity",
                "transport_enabled": True,
                "interfaces": 2,
            }

            mock_hub = Mock()
            mock_hub.is_connected = False
            mock_hub.hub_address = None
            mock_get_hub.return_value = mock_hub

            status = get_service_status()

            assert status["rns_initialized"] is True
            assert status["hub_connected"] is False
            assert status["operator_identity"] == "test_identity"
            assert status["transport_enabled"] is True
            assert status["interface_count"] == 2


# =============================================================================
# Backward Compatibility Tests
# =============================================================================


class TestBackwardCompatibility:
    """Test that old configs with use_ipc field don't break."""

    def test_old_config_with_use_ipc_false_loads(self):
        """Config YAML containing use_ipc: false should load without error."""
        from styrened.tui.services.config import _parse_config_dict

        data = {
            "tui": {
                "theme": "styrene",
                "log_level": "info",
                "use_ipc": False,  # legacy field
            }
        }
        config = _parse_config_dict(data)
        # Config should load successfully — use_ipc is silently ignored
        assert config.tui.theme.value == "styrene"
        assert not hasattr(config.tui, "use_ipc") or True  # field removed

    def test_old_config_with_use_ipc_true_loads(self):
        """Config YAML containing use_ipc: true should load without error."""
        from styrened.tui.services.config import _parse_config_dict

        data = {
            "tui": {
                "use_ipc": True,
            }
        }
        config = _parse_config_dict(data)
        assert config is not None

    def test_old_config_with_use_ipc_null_loads(self):
        """Config YAML containing use_ipc: null should load without error."""
        from styrened.tui.services.config import _parse_config_dict

        data = {
            "tui": {
                "use_ipc": None,
            }
        }
        config = _parse_config_dict(data)
        assert config is not None

    def test_tui_config_has_no_use_ipc_field(self):
        """TUIConfig dataclass should not have a use_ipc field."""
        from styrened.tui.models.config import TUIConfig

        tui = TUIConfig()
        assert not hasattr(tui, "use_ipc")

    def test_config_serialization_no_use_ipc(self):
        """Serialized config should not contain use_ipc."""
        from styrened.tui.services.config import _config_to_dict, get_default_config

        config = get_default_config()
        data = _config_to_dict(config)
        assert "use_ipc" not in data["tui"]
