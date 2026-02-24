"""Integration tests for IPC lifecycle — real Unix sockets.

Tests actual socket communication between styrened's ControlServer
and styrene-tui's IPCBridge/DaemonManager. Requires styrened to be
importable (editable install or sys.path).
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.ipc.messages import DaemonStatus
from styrened.ipc.server import ControlServer
from styrened.tui.services.daemon_manager import DaemonManager, DaemonMode
from styrened.tui.services.ipc_bridge import IPCBridge

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def socket_path():
    """Create a short temporary socket path (macOS limit is 104 chars)."""
    socket_dir = Path(tempfile.mkdtemp(prefix="ipc", dir="/tmp"))
    path = socket_dir / "ctrl.sock"
    yield path
    if path.exists():
        path.unlink()
    socket_dir.rmdir()


@pytest.fixture
def mock_daemon():
    """Create a mock StyreneDaemon for the ControlServer."""
    daemon = MagicMock()
    daemon._start_time = 0.0
    daemon._operator_destination = MagicMock()
    daemon._operator_destination.hexhash = "abc123def456"
    daemon._rpc_client = MagicMock()
    daemon._rpc_client.pending_count = 0
    daemon._lxmf_service = MagicMock()

    daemon.config = MagicMock()
    daemon.config.reticulum.mode.value = "standalone"
    daemon.config.reticulum.announce_interval = 300
    daemon.config.reticulum.hub_enabled = False
    daemon.config.rpc.enabled = True
    daemon.config.rpc.relay_mode = False
    daemon.config.rpc.allow_command_execution = True
    daemon.config.discovery.enabled = True
    daemon.config.discovery.auto_announce = True
    daemon.config.chat.enabled = True
    daemon.config.chat.auto_reply_mode = MagicMock()
    daemon.config.chat.auto_reply_mode.value = "disabled"
    daemon.config.chat.auto_reply_cooldown = 60
    daemon.config.chat.persist_messages = True
    daemon.config.api.enabled = False
    daemon.config.api.port = 8080

    daemon.lifecycle = MagicMock()
    daemon.lifecycle._initialized = True

    daemon._announce = MagicMock()

    return daemon


@pytest.fixture
async def running_server(mock_daemon, socket_path):
    """Start a real ControlServer on a temp socket with service patches."""
    with (
        patch("styrened.services.reticulum.discover_devices", return_value=[]),
        patch("styrened.services.node_store.get_node_store", return_value=None),
        patch("styrened.services.lxmf_service.get_lxmf_service", return_value=None),
        patch("styrened.services.reticulum.get_operator_identity", return_value="test_identity"),
    ):
        server = ControlServer(mock_daemon, socket_path)
        await server.start()
        yield server
        await server.stop()


# ===================================================================
# IPCBridge integration
# ===================================================================


class TestIPCBridgeIntegration:
    """Test IPCBridge connecting to a real ControlServer."""

    @pytest.mark.asyncio
    async def test_bridge_connects_to_real_server(self, socket_path, running_server):
        """IPCBridge successfully connects to running ControlServer."""
        bridge = IPCBridge(socket_path=socket_path)
        result = await bridge.connect()

        assert result is True
        assert bridge.connected is True

        await bridge.disconnect()

    @pytest.mark.asyncio
    async def test_get_status_over_socket(self, socket_path, running_server):
        """get_status() returns real DaemonStatus from server."""
        bridge = IPCBridge(socket_path=socket_path)
        await bridge.connect()

        status = await bridge.get_status()
        assert isinstance(status, DaemonStatus)
        assert status.rns_initialized is True

        await bridge.disconnect()

    @pytest.mark.asyncio
    async def test_get_devices_over_socket(self, socket_path, running_server):
        """get_devices() returns list from server (empty with mocked daemon)."""
        bridge = IPCBridge(socket_path=socket_path)
        await bridge.connect()

        devices = await bridge.get_devices()
        assert isinstance(devices, list)
        assert devices == []

        await bridge.disconnect()

    @pytest.mark.asyncio
    async def test_get_config_over_socket(self, socket_path, running_server):
        """get_config() returns config dict from server."""
        bridge = IPCBridge(socket_path=socket_path)
        await bridge.connect()

        config = await bridge.get_config()
        assert isinstance(config, dict)
        assert "reticulum" in config

        await bridge.disconnect()

    @pytest.mark.asyncio
    async def test_announce_over_socket(self, socket_path, running_server, mock_daemon):
        """announce() calls through to daemon and returns hash."""
        bridge = IPCBridge(socket_path=socket_path)
        await bridge.connect()

        dest_hash = await bridge.announce()
        assert dest_hash == "abc123def456"
        mock_daemon._announce.assert_called_once()

        await bridge.disconnect()


# ===================================================================
# DaemonManager external mode integration
# ===================================================================


class TestDaemonManagerExternalMode:
    """Test DaemonManager in EXTERNAL mode with real server."""

    @pytest.mark.asyncio
    async def test_connects_to_running_server(self, socket_path, running_server):
        """External mode detects running server and reports running."""
        mgr = DaemonManager(mode=DaemonMode.EXTERNAL, socket_path=socket_path)

        with patch.object(mgr, "_start_health_monitor"):
            result = await mgr.ensure_running()

        assert result is True
        assert mgr.is_running is True

        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_fails_when_no_server(self, socket_path):
        """External mode fails when no server is running."""
        mgr = DaemonManager(mode=DaemonMode.EXTERNAL, socket_path=socket_path)
        result = await mgr.ensure_running()

        assert result is False
        assert mgr.is_running is False


# ===================================================================
# Lifecycle IPC integration
# ===================================================================


class TestLifecycleIPCIntegration:
    """Test StyreneLifecycle IPC mode with real socket."""

    @pytest.mark.asyncio
    async def test_lifecycle_ipc_init_with_running_server(
        self, socket_path, running_server,
    ):
        """Full IPC lifecycle init succeeds with real server."""
        from unittest.mock import Mock

        from styrened.tui.models.config import DeploymentMode, StyreneConfig
        from styrened.tui.services.app_lifecycle import LifecycleMode, StyreneLifecycle

        config = Mock(spec=StyreneConfig)
        config.core = Mock()
        config.reticulum = Mock()
        config.reticulum.hub_enabled = False
        config.reticulum.mode = DeploymentMode.PEER
        config.api = Mock()
        config.api.enabled = False
        config.tui = Mock()
        config.tui.use_ipc = True

        lifecycle = StyreneLifecycle(config)

        # Patch DaemonManager to use EXTERNAL mode pointing at our socket
        with (
            patch("styrened.tui.services.daemon_manager.DaemonManager") as mock_dm_cls,
            patch("styrened.tui.services.ipc_bridge.IPCBridge") as mock_bridge_cls,
        ):
            mock_dm = AsyncMock()
            mock_dm.ensure_running = AsyncMock(return_value=True)
            mock_dm.shutdown = AsyncMock()
            mock_dm_cls.return_value = mock_dm

            # Use real IPCBridge pointed at the socket
            real_bridge = IPCBridge(socket_path=socket_path)
            mock_bridge_cls.return_value = real_bridge

            result = await lifecycle.initialize_async()

        assert result is True
        assert lifecycle.active_mode == LifecycleMode.IPC
        assert lifecycle.is_initialized is True

        # Cleanup
        await lifecycle.shutdown_async()

    @pytest.mark.asyncio
    async def test_shutdown_disconnects(self, socket_path, running_server):
        """Shutdown disconnects bridge cleanly."""
        bridge = IPCBridge(socket_path=socket_path)
        await bridge.connect()
        assert bridge.connected is True

        await bridge.disconnect()
        assert bridge.connected is False


# ===================================================================
# Bridge reconnection
# ===================================================================


class TestBridgeReconnection:
    """Test IPCBridge reconnection after server restart."""

    @pytest.mark.asyncio
    async def test_reconnects_after_server_restart(self, mock_daemon, socket_path):
        """Bridge reconnects after server restart."""
        with (
            patch("styrened.services.reticulum.discover_devices", return_value=[]),
            patch("styrened.services.node_store.get_node_store", return_value=None),
            patch("styrened.services.lxmf_service.get_lxmf_service", return_value=None),
            patch("styrened.services.reticulum.get_operator_identity", return_value="test_identity"),
        ):
            # Start server
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            # Connect bridge
            bridge = IPCBridge(socket_path=socket_path, auto_reconnect=True)
            await bridge.connect()
            assert bridge.connected is True

            # Stop server
            await server.stop()
            await asyncio.sleep(0.1)

            # Bridge should detect disconnection
            # (connected may still be True until next operation)

            # Restart server
            server2 = ControlServer(mock_daemon, socket_path)
            await server2.start()

            # Manually reconnect
            result = await bridge._reconnect()
            assert result is True
            assert bridge.connected is True

            # Verify it works
            status = await bridge.get_status()
            assert isinstance(status, DaemonStatus)

            await bridge.disconnect()
            await server2.stop()
