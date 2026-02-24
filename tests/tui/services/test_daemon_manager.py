"""Tests for DaemonManager — daemon subprocess lifecycle management.

All subprocess and IPC calls are mocked. No real daemon is spawned.
"""

import asyncio
import signal
from unittest.mock import AsyncMock, Mock, patch

import pytest

from styrened.tui.services.daemon_manager import (
    DaemonManager,
    DaemonMode,
)


@pytest.fixture
def mock_socket_path(tmp_path):
    """Temporary socket path."""
    return tmp_path / "styrened.sock"


@pytest.fixture
def mock_control_client():
    """Patch ControlClient at source module (lazy-imported in _ping())."""
    with patch("styrened.ipc.ControlClient") as mock_client_cls:
        client = AsyncMock()
        client.connect = AsyncMock()
        client.ping = AsyncMock(return_value=True)
        client.disconnect = AsyncMock()
        mock_client_cls.return_value = client
        yield client


@pytest.fixture
def mock_subprocess():
    """Patch asyncio.create_subprocess_exec for spawn tests."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.wait = AsyncMock()
        mock_proc.send_signal = Mock()
        mock_proc.kill = Mock()
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_exec.return_value = mock_proc
        yield mock_proc, mock_exec


# ===================================================================
# Init
# ===================================================================


class TestDaemonManagerInit:
    """Test DaemonManager construction."""

    def test_default_mode(self):
        mgr = DaemonManager()
        assert mgr.mode == DaemonMode.MANAGED

    def test_custom_mode(self):
        mgr = DaemonManager(mode=DaemonMode.EXTERNAL)
        assert mgr.mode == DaemonMode.EXTERNAL

    def test_custom_socket_path(self, mock_socket_path):
        mgr = DaemonManager(socket_path=mock_socket_path)
        assert mgr.socket_path == mock_socket_path

    def test_initial_not_running(self):
        mgr = DaemonManager()
        assert mgr.is_running is False


# ===================================================================
# Fallback mode
# ===================================================================


class TestEnsureRunningFallback:
    """Fallback mode always returns False — no daemon involvement."""

    @pytest.mark.asyncio
    async def test_returns_false(self):
        mgr = DaemonManager(mode=DaemonMode.FALLBACK)
        result = await mgr.ensure_running()
        assert result is False
        assert mgr.is_running is False


# ===================================================================
# External mode
# ===================================================================


class TestEnsureRunningExternal:
    """External mode checks for a pre-existing daemon."""

    @pytest.mark.asyncio
    async def test_true_when_reachable(self, mock_socket_path, mock_control_client):
        """Returns True when daemon is reachable."""
        mock_socket_path.touch()  # Socket file must exist for _ping()

        mgr = DaemonManager(mode=DaemonMode.EXTERNAL, socket_path=mock_socket_path)

        # Patch _start_health_monitor to avoid dangling task
        with patch.object(mgr, "_start_health_monitor"):
            result = await mgr.ensure_running()

        assert result is True
        assert mgr.is_running is True

    @pytest.mark.asyncio
    async def test_false_when_not_reachable(self, mock_socket_path):
        """Returns False when socket doesn't exist."""
        mgr = DaemonManager(mode=DaemonMode.EXTERNAL, socket_path=mock_socket_path)
        result = await mgr.ensure_running()

        assert result is False
        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_does_not_spawn(self, mock_socket_path, mock_control_client):
        """External mode never spawns a subprocess."""
        mock_socket_path.touch()

        mgr = DaemonManager(mode=DaemonMode.EXTERNAL, socket_path=mock_socket_path)

        with (
            patch.object(mgr, "_start_health_monitor"),
            patch.object(mgr, "_spawn") as mock_spawn,
        ):
            await mgr.ensure_running()

        mock_spawn.assert_not_called()


# ===================================================================
# Managed mode
# ===================================================================


class TestEnsureRunningManaged:
    """Managed mode spawns the daemon subprocess."""

    @pytest.mark.asyncio
    async def test_spawns_subprocess(self, mock_socket_path, mock_subprocess):
        """Spawns styrened and waits for socket."""
        mock_proc, mock_exec = mock_subprocess

        mgr = DaemonManager(mode=DaemonMode.MANAGED, socket_path=mock_socket_path)

        # Simulate: ping fails initially, then succeeds after socket appears
        call_count = 0

        async def _ping_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                return True
            return False

        with (
            patch.object(mgr, "_ping", side_effect=_ping_side_effect),
            patch.object(mgr, "_start_health_monitor"),
        ):
            result = await mgr.ensure_running()

        assert result is True
        assert mgr.is_running is True
        mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self, mock_socket_path, mock_subprocess):
        """Returns False when daemon doesn't become ready in time."""
        mock_proc, mock_exec = mock_subprocess

        mgr = DaemonManager(mode=DaemonMode.MANAGED, socket_path=mock_socket_path)

        with (
            patch.object(mgr, "_ping", return_value=False),
            patch.object(mgr, "shutdown", new_callable=AsyncMock),
            patch("styrened.tui.services.daemon_manager._SOCKET_POLL_TIMEOUT", 0.5),
            patch("styrened.tui.services.daemon_manager._SOCKET_POLL_INTERVAL", 0.1),
        ):
            result = await mgr.ensure_running()

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_process_death(self, mock_socket_path, mock_subprocess):
        """Returns False when daemon dies during startup."""
        mock_proc, mock_exec = mock_subprocess
        mock_proc.returncode = 1  # process already exited

        mgr = DaemonManager(mode=DaemonMode.MANAGED, socket_path=mock_socket_path)

        with patch.object(mgr, "_ping", return_value=False):
            result = await mgr.ensure_running()

        assert result is False
        assert mgr._process is None

    @pytest.mark.asyncio
    async def test_returns_false_on_process_stderr(self, mock_socket_path, mock_subprocess):
        """Captures stderr when daemon exits during startup."""
        mock_proc, mock_exec = mock_subprocess
        mock_proc.returncode = 1
        mock_proc.stderr.read = AsyncMock(return_value=b"Fatal: config error")

        mgr = DaemonManager(mode=DaemonMode.MANAGED, socket_path=mock_socket_path)

        with patch.object(mgr, "_ping", return_value=False):
            result = await mgr.ensure_running()

        assert result is False

    @pytest.mark.asyncio
    async def test_file_not_found_for_missing_styrened(self, mock_socket_path):
        """Returns False when styrened binary not on PATH."""
        mgr = DaemonManager(mode=DaemonMode.MANAGED, socket_path=mock_socket_path)

        with (
            patch.object(mgr, "_ping", return_value=False),
            patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError),
        ):
            result = await mgr.ensure_running()

        assert result is False


# ===================================================================
# Ping
# ===================================================================


class TestPing:
    """Test _ping() health check."""

    @pytest.mark.asyncio
    async def test_false_when_socket_missing(self, mock_socket_path):
        """Returns False when socket file doesn't exist."""
        mgr = DaemonManager(socket_path=mock_socket_path)
        result = await mgr._ping()
        assert result is False

    @pytest.mark.asyncio
    async def test_true_on_daemon_response(self, mock_socket_path, mock_control_client):
        """Returns True when daemon responds to ping."""
        mock_socket_path.touch()

        mgr = DaemonManager(socket_path=mock_socket_path)
        result = await mgr._ping()
        assert result is True

        # Should connect, ping, then disconnect
        mock_control_client.connect.assert_called_once()
        mock_control_client.ping.assert_called_once()
        mock_control_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_false_on_error(self, mock_socket_path, mock_control_client):
        """Returns False on any exception during ping."""
        mock_socket_path.touch()
        mock_control_client.connect.side_effect = ConnectionRefusedError

        mgr = DaemonManager(socket_path=mock_socket_path)
        result = await mgr._ping()
        assert result is False


# ===================================================================
# Shutdown
# ===================================================================


class TestShutdown:
    """Test shutdown behavior across modes."""

    @pytest.mark.asyncio
    async def test_sigterm_then_sigkill_escalation(self, mock_socket_path, mock_subprocess):
        """Managed mode: SIGTERM, then SIGKILL on timeout."""
        mock_proc, _ = mock_subprocess
        mock_proc.wait = AsyncMock(side_effect=TimeoutError)

        mgr = DaemonManager(mode=DaemonMode.MANAGED, socket_path=mock_socket_path)
        mgr._process = mock_proc
        mgr._running = True

        await mgr.shutdown()

        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)
        mock_proc.kill.assert_called_once()
        assert mgr.is_running is False
        assert mgr._process is None

    @pytest.mark.asyncio
    async def test_clean_exit_no_sigkill(self, mock_socket_path, mock_subprocess):
        """Managed mode: daemon exits cleanly within grace period."""
        mock_proc, _ = mock_subprocess
        mock_proc.wait = AsyncMock(return_value=0)
        mock_proc.returncode = 0

        mgr = DaemonManager(mode=DaemonMode.MANAGED, socket_path=mock_socket_path)
        mgr._process = mock_proc
        mgr._running = True

        await mgr.shutdown()

        mock_proc.send_signal.assert_called_once_with(signal.SIGTERM)
        mock_proc.kill.assert_not_called()
        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_process_lookup_error_handling(self, mock_socket_path, mock_subprocess):
        """ProcessLookupError is handled (process already gone)."""
        mock_proc, _ = mock_subprocess
        mock_proc.send_signal.side_effect = ProcessLookupError

        mgr = DaemonManager(mode=DaemonMode.MANAGED, socket_path=mock_socket_path)
        mgr._process = mock_proc
        mgr._running = True

        await mgr.shutdown()  # Should not raise
        assert mgr.is_running is False
        assert mgr._process is None

    @pytest.mark.asyncio
    async def test_noop_for_external(self, mock_socket_path):
        """External mode shutdown doesn't kill anything."""
        mgr = DaemonManager(mode=DaemonMode.EXTERNAL, socket_path=mock_socket_path)
        mgr._running = True

        await mgr.shutdown()
        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_noop_for_fallback(self):
        """Fallback mode shutdown is a no-op."""
        mgr = DaemonManager(mode=DaemonMode.FALLBACK)
        mgr._running = True

        await mgr.shutdown()
        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_stops_health_monitor(self, mock_socket_path):
        """Shutdown cancels the health monitor task."""
        mgr = DaemonManager(mode=DaemonMode.EXTERNAL, socket_path=mock_socket_path)
        mock_task = AsyncMock()
        mock_task.cancel = Mock()
        mgr._health_task = mock_task
        mgr._running = True

        await mgr.shutdown()
        mock_task.cancel.assert_called_once()
        assert mgr._health_task is None


# ===================================================================
# Health monitor
# ===================================================================


class TestHealthMonitor:
    """Test background health monitoring."""

    @pytest.mark.asyncio
    async def test_three_strike_crash_detection(self, mock_socket_path):
        """Three consecutive ping failures → marks daemon as crashed."""
        mgr = DaemonManager(socket_path=mock_socket_path)
        mgr._running = True

        with patch.object(mgr, "_ping", return_value=False):
            with patch("styrened.tui.services.daemon_manager._HEALTH_CHECK_INTERVAL", 0.01):
                await mgr._monitor_health()

        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_counter_reset_on_success(self, mock_socket_path):
        """Successful ping resets the failure counter."""
        mgr = DaemonManager(socket_path=mock_socket_path)
        mgr._running = True

        ping_results = [False, False, True, False, False, True, False, False, False]
        call_idx = 0

        async def _ping():
            nonlocal call_idx
            if call_idx >= len(ping_results):
                mgr._running = False  # stop the loop
                return False
            result = ping_results[call_idx]
            call_idx += 1
            return result

        with (
            patch.object(mgr, "_ping", side_effect=_ping),
            patch("styrened.tui.services.daemon_manager._HEALTH_CHECK_INTERVAL", 0.01),
        ):
            await mgr._monitor_health()

        # Should have gone through all results; 3 consecutive failures at end
        assert mgr.is_running is False

    @pytest.mark.asyncio
    async def test_cancel_on_stop(self, mock_socket_path):
        """Health monitor exits cleanly on CancelledError."""
        mgr = DaemonManager(socket_path=mock_socket_path)
        mgr._running = True

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            await mgr._monitor_health()  # Should not raise

    def test_start_health_monitor_idempotent(self, mock_socket_path):
        """Starting health monitor twice doesn't create duplicate tasks."""
        mgr = DaemonManager(socket_path=mock_socket_path)

        with patch("asyncio.create_task") as mock_create:
            mock_create.return_value = Mock()
            mgr._start_health_monitor()
            mgr._start_health_monitor()

        mock_create.assert_called_once()

    def test_stop_health_monitor_noop_when_none(self, mock_socket_path):
        """Stopping when no monitor is running is a no-op."""
        mgr = DaemonManager(socket_path=mock_socket_path)
        mgr._stop_health_monitor()  # Should not raise
        assert mgr._health_task is None
