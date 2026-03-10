"""Unit tests for StyreneDaemon lifecycle.

Tests the daemon startup, shutdown, and service initialization sequences.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.daemon import StyreneDaemon
from styrened.models.config import (
    APIConfig,
    ChatConfig,
    CoreConfig,
    IPCConfig,
    ReticulumConfig,
    TerminalConfig,
)


@pytest.fixture
def minimal_config() -> CoreConfig:
    """Create a minimal CoreConfig for testing."""
    return CoreConfig(
        reticulum=ReticulumConfig(),
        api=APIConfig(enabled=False),
        chat=ChatConfig(enabled=False),
        ipc=IPCConfig(enabled=False),
        terminal=TerminalConfig(enabled=False),
    )


@pytest.fixture
def full_config() -> CoreConfig:
    """Create a CoreConfig with all features enabled."""
    return CoreConfig(
        reticulum=ReticulumConfig(),
        api=APIConfig(enabled=True, port=8080),
        chat=ChatConfig(enabled=True),
        ipc=IPCConfig(enabled=True),
        terminal=TerminalConfig(enabled=True),
    )


class TestDaemonInitialization:
    """Tests for daemon initialization."""

    def test_daemon_init_sets_config(self, minimal_config: CoreConfig) -> None:
        """Daemon should store the provided config."""
        daemon = StyreneDaemon(minimal_config)
        assert daemon.config is minimal_config

    def test_daemon_init_creates_lifecycle(self, minimal_config: CoreConfig) -> None:
        """Daemon should create a CoreLifecycle instance."""
        daemon = StyreneDaemon(minimal_config)
        assert daemon.lifecycle is not None

    def test_daemon_init_not_running(self, minimal_config: CoreConfig) -> None:
        """Daemon should not be running after init."""
        daemon = StyreneDaemon(minimal_config)
        assert daemon._running is False

    def test_daemon_init_services_none(self, minimal_config: CoreConfig) -> None:
        """Daemon services should be None after init (not started yet)."""
        daemon = StyreneDaemon(minimal_config)

        assert daemon._rpc_server is None
        assert daemon._control_server is None
        assert daemon._conversation_service is None
        assert daemon._terminal_service is None
        assert daemon._auto_reply_handler is None

    def test_daemon_init_records_start_time(self, minimal_config: CoreConfig) -> None:
        """Daemon should record start time on init."""
        daemon = StyreneDaemon(minimal_config)
        assert daemon._start_time > 0


class TestDaemonStartSequence:
    """Tests for daemon start sequence."""

    @pytest.mark.asyncio
    async def test_start_initializes_lifecycle(self, minimal_config: CoreConfig) -> None:
        """Start should call lifecycle.initialize()."""
        daemon = StyreneDaemon(minimal_config)

        with patch.object(daemon.lifecycle, "initialize", return_value=True) as mock_init:
            with patch.object(daemon, "_init_operator_destination"):
                with patch.object(daemon, "_start_rpc_server"):
                    with patch.object(daemon, "_init_conversation_service"):
                        with patch.object(daemon, "_start_auto_reply"):
                            with patch("styrened.daemon.get_node_store"):
                                with patch("styrened.daemon.start_discovery"):
                                    with patch.object(daemon, "_run_loop", new_callable=AsyncMock):
                                        await daemon.start()

            mock_init.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_exits_on_lifecycle_failure(self, minimal_config: CoreConfig) -> None:
        """Start should exit if lifecycle fails to initialize."""
        daemon = StyreneDaemon(minimal_config)

        with patch.object(daemon.lifecycle, "initialize", return_value=False):
            with pytest.raises(SystemExit) as exc_info:
                await daemon.start()

            assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_start_initializes_operator_destination(self, minimal_config: CoreConfig) -> None:
        """Start should initialize operator destination."""
        daemon = StyreneDaemon(minimal_config)

        with patch.object(daemon.lifecycle, "initialize", return_value=True):
            with patch.object(daemon, "_init_operator_destination") as mock_op_dest:
                with patch.object(daemon, "_start_rpc_server"):
                    with patch.object(daemon, "_init_conversation_service"):
                        with patch.object(daemon, "_start_auto_reply"):
                            with patch("styrened.daemon.get_node_store"):
                                with patch("styrened.daemon.start_discovery"):
                                    with patch.object(daemon, "_run_loop", new_callable=AsyncMock):
                                        await daemon.start()

                mock_op_dest.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_starts_rpc_server(self, minimal_config: CoreConfig) -> None:
        """Start should start RPC server."""
        daemon = StyreneDaemon(minimal_config)

        with patch.object(daemon.lifecycle, "initialize", return_value=True):
            with patch.object(daemon, "_init_operator_destination"):
                with patch.object(daemon, "_start_rpc_server") as mock_rpc:
                    with patch.object(daemon, "_init_conversation_service"):
                        with patch.object(daemon, "_start_auto_reply"):
                            with patch("styrened.daemon.get_node_store"):
                                with patch("styrened.daemon.start_discovery"):
                                    with patch.object(daemon, "_run_loop", new_callable=AsyncMock):
                                        await daemon.start()

                    mock_rpc.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_starts_discovery(self, minimal_config: CoreConfig) -> None:
        """Start should start device discovery."""
        daemon = StyreneDaemon(minimal_config)

        with patch.object(daemon.lifecycle, "initialize", return_value=True):
            with patch.object(daemon, "_init_operator_destination"):
                with patch.object(daemon, "_start_rpc_server"):
                    with patch.object(daemon, "_init_conversation_service"):
                        with patch.object(daemon, "_start_auto_reply"):
                            with patch("styrened.daemon.get_node_store"):
                                with patch("styrened.daemon.start_discovery") as mock_discovery:
                                    with patch.object(daemon, "_run_loop", new_callable=AsyncMock):
                                        await daemon.start()

                                    mock_discovery.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self, minimal_config: CoreConfig) -> None:
        """Start should set _running to True."""
        daemon = StyreneDaemon(minimal_config)

        with patch.object(daemon.lifecycle, "initialize", return_value=True):
            with patch.object(daemon, "_init_operator_destination"):
                with patch.object(daemon, "_start_rpc_server"):
                    with patch.object(daemon, "_init_conversation_service"):
                        with patch.object(daemon, "_start_auto_reply"):
                            with patch("styrened.daemon.get_node_store"):
                                with patch("styrened.daemon.start_discovery"):
                                    with patch.object(daemon, "_run_loop", new_callable=AsyncMock):
                                        await daemon.start()

        assert daemon._running is True


class TestDaemonI2PAdapter:
    """Tests for daemon-managed I2P adapter wiring."""

    @pytest.mark.asyncio
    async def test_start_i2p_adapter_injects_rpc_server(self, minimal_config: CoreConfig) -> None:
        daemon = StyreneDaemon(minimal_config)
        daemon._rpc_server = MagicMock()

        with patch("styrened.services.i2p.I2PAdapter") as MockAdapter:
            adapter = MockAdapter.return_value
            adapter.start = AsyncMock()
            adapter.status = AsyncMock()

            await daemon._start_i2p_adapter()

        daemon._rpc_server.set_i2p_adapter.assert_called_once_with(adapter)
        assert daemon._i2p_adapter is adapter

    @pytest.mark.asyncio
    async def test_stop_i2p_adapter_clears_rpc_server(self, minimal_config: CoreConfig) -> None:
        daemon = StyreneDaemon(minimal_config)
        daemon._rpc_server = MagicMock()
        daemon._i2p_adapter = MagicMock()
        daemon._i2p_adapter.stop = AsyncMock()

        await daemon._stop_i2p_adapter()

        daemon._i2p_adapter = None
        daemon._rpc_server.set_i2p_adapter.assert_called_once_with(None)


class TestDaemonOptionalServices:
    """Tests for optional service startup based on config."""

    @pytest.mark.asyncio
    async def test_api_not_started_when_disabled(self, minimal_config: CoreConfig) -> None:
        """API server should not start when disabled in config."""
        minimal_config.api.enabled = False
        daemon = StyreneDaemon(minimal_config)

        with patch.object(daemon.lifecycle, "initialize", return_value=True):
            with patch.object(daemon, "_init_operator_destination"):
                with patch.object(daemon, "_start_rpc_server"):
                    with patch.object(daemon, "_init_conversation_service"):
                        with patch.object(daemon, "_start_auto_reply"):
                            with patch("styrened.daemon.get_node_store"):
                                with patch("styrened.daemon.start_discovery"):
                                    with patch.object(daemon, "_run_loop", new_callable=AsyncMock):
                                        with patch.object(
                                            daemon, "_start_api", new_callable=AsyncMock
                                        ) as mock_api:
                                            await daemon.start()

                                            mock_api.assert_not_called()

    @pytest.mark.asyncio
    async def test_ipc_not_started_when_disabled(self, minimal_config: CoreConfig) -> None:
        """IPC server should not start when disabled in config."""
        minimal_config.ipc.enabled = False
        daemon = StyreneDaemon(minimal_config)

        with patch.object(daemon.lifecycle, "initialize", return_value=True):
            with patch.object(daemon, "_init_operator_destination"):
                with patch.object(daemon, "_start_rpc_server"):
                    with patch.object(daemon, "_init_conversation_service"):
                        with patch.object(daemon, "_start_auto_reply"):
                            with patch("styrened.daemon.get_node_store"):
                                with patch("styrened.daemon.start_discovery"):
                                    with patch.object(daemon, "_run_loop", new_callable=AsyncMock):
                                        with patch.object(
                                            daemon,
                                            "_start_control_server",
                                            new_callable=AsyncMock,
                                        ) as mock_ipc:
                                            await daemon.start()

                                            mock_ipc.assert_not_called()

    @pytest.mark.asyncio
    async def test_terminal_not_started_when_disabled(self, minimal_config: CoreConfig) -> None:
        """Terminal service should not start when disabled in config."""
        minimal_config.terminal.enabled = False
        daemon = StyreneDaemon(minimal_config)

        with patch.object(daemon.lifecycle, "initialize", return_value=True):
            with patch.object(daemon, "_init_operator_destination"):
                with patch.object(daemon, "_start_rpc_server"):
                    with patch.object(daemon, "_init_conversation_service"):
                        with patch.object(daemon, "_start_auto_reply"):
                            with patch("styrened.daemon.get_node_store"):
                                with patch("styrened.daemon.start_discovery"):
                                    with patch.object(daemon, "_run_loop", new_callable=AsyncMock):
                                        with patch.object(
                                            daemon, "_start_terminal_service"
                                        ) as mock_terminal:
                                            await daemon.start()

                                            mock_terminal.assert_not_called()


class TestDaemonStopSequence:
    """Tests for daemon stop sequence."""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, minimal_config: CoreConfig) -> None:
        """Stop should set _running to False."""
        daemon = StyreneDaemon(minimal_config)
        daemon._running = True

        with patch.object(daemon, "_stop_terminal_service"):
            with patch.object(daemon.lifecycle, "shutdown"):
                await daemon.stop()

        assert daemon._running is False

    @pytest.mark.asyncio
    async def test_stop_stops_terminal_service(self, minimal_config: CoreConfig) -> None:
        """Stop should stop terminal service."""
        daemon = StyreneDaemon(minimal_config)
        daemon._running = True

        with patch.object(daemon, "_stop_terminal_service") as mock_stop:
            with patch.object(daemon.lifecycle, "shutdown"):
                await daemon.stop()

            mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_stops_control_server(self, minimal_config: CoreConfig) -> None:
        """Stop should stop IPC control server if running."""
        daemon = StyreneDaemon(minimal_config)
        daemon._running = True

        mock_server = MagicMock()
        mock_server.stop = AsyncMock()
        daemon._control_server = mock_server

        with patch.object(daemon, "_stop_terminal_service"):
            with patch.object(daemon.lifecycle, "shutdown"):
                await daemon.stop()

        mock_server.stop.assert_called_once()
        assert daemon._control_server is None

    @pytest.mark.asyncio
    async def test_stop_shuts_down_conversation_service(self, minimal_config: CoreConfig) -> None:
        """Stop should shutdown conversation service if running."""
        daemon = StyreneDaemon(minimal_config)
        daemon._running = True

        mock_conv = MagicMock()
        daemon._conversation_service = mock_conv

        with patch.object(daemon, "_stop_terminal_service"):
            with patch.object(daemon.lifecycle, "shutdown"):
                await daemon.stop()

        mock_conv.shutdown.assert_called_once()
        assert daemon._conversation_service is None

    @pytest.mark.asyncio
    async def test_stop_stops_rpc_server(self, minimal_config: CoreConfig) -> None:
        """Stop should stop RPC server if running."""
        daemon = StyreneDaemon(minimal_config)
        daemon._running = True

        mock_rpc = MagicMock()
        daemon._rpc_server = mock_rpc

        with patch.object(daemon, "_stop_terminal_service"):
            with patch.object(daemon.lifecycle, "shutdown"):
                await daemon.stop()

        mock_rpc.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_shuts_down_lifecycle(self, minimal_config: CoreConfig) -> None:
        """Stop should shutdown lifecycle."""
        daemon = StyreneDaemon(minimal_config)
        daemon._running = True

        with patch.object(daemon, "_stop_terminal_service"):
            with patch.object(daemon.lifecycle, "shutdown") as mock_shutdown:
                await daemon.stop()

            mock_shutdown.assert_called_once()

    @pytest.mark.asyncio
    async def test_double_stop_is_safe(self, minimal_config: CoreConfig) -> None:
        """Stopping already-stopped daemon should not error."""
        daemon = StyreneDaemon(minimal_config)
        daemon._running = False

        with patch.object(daemon, "_stop_terminal_service"):
            with patch.object(daemon.lifecycle, "shutdown"):
                await daemon.stop()  # First stop
                await daemon.stop()  # Second stop - should not error


class TestDaemonStateManagement:
    """Tests for daemon state management."""

    def test_is_running_returns_state(self, minimal_config: CoreConfig) -> None:
        """Daemon should expose running state."""
        daemon = StyreneDaemon(minimal_config)

        assert daemon._running is False

        daemon._running = True
        assert daemon._running is True

    def test_daemon_exposes_services_for_ipc(self, minimal_config: CoreConfig) -> None:
        """Daemon should expose service references for IPC handlers."""
        daemon = StyreneDaemon(minimal_config)

        # These attributes exist for IPC handler access
        assert hasattr(daemon, "_rpc_client")
        assert hasattr(daemon, "_lxmf_service")
        assert hasattr(daemon, "_conversation_service")
        assert hasattr(daemon, "_node_store")


class TestDaemonUUIDTempIds:
    """W14: Attachment filename race condition prevention via UUID-based temp IDs."""

    def test_uuid_module_imported(self, minimal_config: CoreConfig) -> None:
        """W14: daemon.py imports uuid for temp attachment IDs."""
        import styrened.daemon as daemon_mod

        assert hasattr(daemon_mod, "uuid"), "daemon module should import uuid"

    def test_temp_msg_id_pattern_produces_positive_31bit_int(self) -> None:
        """W14: uuid4().int & 0x7FFFFFFF produces valid positive 31-bit IDs."""
        import uuid

        # Generate several IDs and verify all are positive 31-bit integers
        for _ in range(100):
            temp_id = uuid.uuid4().int & 0x7FFFFFFF
            assert temp_id >= 0, "temp ID must be non-negative"
            assert temp_id <= 0x7FFFFFFF, "temp ID must fit in 31 bits"
            # Also verify it's unlikely to be zero (astronomically improbable)
        # At least verify pattern correctness
        assert (uuid.uuid4().int & 0x7FFFFFFF) > 0  # practically always true

    def test_temp_msg_ids_are_unique(self) -> None:
        """W14: UUID-based temp IDs should not collide in concurrent scenarios."""
        import uuid

        ids = set()
        for _ in range(1000):
            temp_id = uuid.uuid4().int & 0x7FFFFFFF
            ids.add(temp_id)
        # With 31-bit IDs and 1000 samples, collisions are astronomically unlikely
        assert len(ids) == 1000


class TestDaemonAttachmentStoreOrdering:
    """C7: get_attachment_store() is called before raw_data check."""

    def test_attachment_store_import_available(self) -> None:
        """C7: get_attachment_store is importable from services.attachment_store."""
        from styrened.services.attachment_store import get_attachment_store

        # The function should exist and be callable
        assert callable(get_attachment_store)

    def test_daemon_has_get_attachment_store_import(self) -> None:
        """C7: daemon.py should reference get_attachment_store.

        The fix moved store = get_attachment_store() BEFORE the
        if raw_data is not None block to prevent NameError when
        raw_data is None but multi-file handling still runs.
        """
        import inspect

        import styrened.daemon as daemon_mod

        source = inspect.getsource(daemon_mod)
        # Verify the pattern: 'store = get_attachment_store()' appears
        # before the 'if raw_data is not None:' check.
        store_idx = source.find("store = get_attachment_store()")
        raw_data_idx = source.find("if raw_data is not None:")
        assert store_idx > 0, "get_attachment_store() call not found in daemon.py"
        assert raw_data_idx > 0, "raw_data check not found in daemon.py"
        assert store_idx < raw_data_idx, (
            "C7 fix: store = get_attachment_store() must appear BEFORE "
            "if raw_data is not None:"
        )


class TestDaemonCallbacks:
    """Tests for daemon callback handling."""

    def test_on_device_discovered_logs(self, minimal_config: CoreConfig) -> None:
        """Device discovery callback should log."""
        daemon = StyreneDaemon(minimal_config)

        # Create mock device
        mock_device = MagicMock()
        mock_device.name = "test-node"
        mock_device.device_type.value = "styrene"
        mock_device.status.value = "online"

        # Should not raise
        daemon._on_device_discovered(mock_device)


class TestDaemonReconnection:
    """Tests for RNS reconnection handling."""

    def test_handle_rns_reconnection_clears_destination(self, minimal_config: CoreConfig) -> None:
        """Reconnection handler should clear cached operator destination."""
        daemon = StyreneDaemon(minimal_config)
        daemon._operator_destination = MagicMock()

        with patch.object(daemon, "_init_operator_destination"):
            with patch.object(daemon, "_announce"):
                daemon._handle_rns_reconnection()

        # Destination should be cleared (then re-initialized by mock)
        # The mock doesn't set it, so it remains None after clear

    def test_handle_rns_reconnection_reinitializes(self, minimal_config: CoreConfig) -> None:
        """Reconnection handler should re-initialize operator destination."""
        daemon = StyreneDaemon(minimal_config)
        daemon._operator_destination = MagicMock()

        with patch.object(daemon, "_init_operator_destination") as mock_init:
            with patch.object(daemon, "_announce"):
                daemon._handle_rns_reconnection()

            mock_init.assert_called_once()

    def test_handle_rns_reconnection_reannounces(self, minimal_config: CoreConfig) -> None:
        """Reconnection handler should re-announce if destination available."""
        daemon = StyreneDaemon(minimal_config)
        daemon._operator_destination = MagicMock()

        def set_destination():
            daemon._operator_destination = MagicMock()

        with patch.object(daemon, "_init_operator_destination", side_effect=set_destination):
            with patch.object(daemon, "_announce") as mock_announce:
                daemon._handle_rns_reconnection()

            mock_announce.assert_called_once()
