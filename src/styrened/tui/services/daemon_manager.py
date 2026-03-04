"""Daemon subprocess lifecycle management.

Manages the styrened daemon process — spawning it as a subprocess when
running in managed mode, or connecting to a pre-existing system daemon.

Three modes:
    managed:  TUI spawns styrened as a subprocess, manages its lifecycle.
    external: Connects to a pre-existing daemon (systemd, etc.).
    fallback: Legacy in-process CoreLifecycle (no daemon, no IPC).
"""

import asyncio
import logging
import shutil
import signal
import sys
from enum import Enum
from pathlib import Path

from styrened.ipc import get_default_socket_path

logger = logging.getLogger(__name__)

# How long to wait for the socket to appear after spawning the daemon
_SOCKET_POLL_TIMEOUT = 15.0
_SOCKET_POLL_INTERVAL = 0.25

# Grace period before escalating SIGTERM → SIGKILL
_SHUTDOWN_GRACE_SECONDS = 5

# Health check interval for the background monitor
_HEALTH_CHECK_INTERVAL = 30.0


class DaemonMode(Enum):
    """How the TUI connects to styrened."""

    MANAGED = "managed"
    EXTERNAL = "external"
    FALLBACK = "fallback"


class DaemonManagerError(Exception):
    """Raised when daemon management operations fail."""


class DaemonManager:
    """Manages the styrened daemon subprocess lifecycle.

    Usage::

        manager = DaemonManager(mode=DaemonMode.MANAGED)
        await manager.ensure_running()
        # ... use IPC bridge ...
        await manager.shutdown()
    """

    @staticmethod
    async def detect_mode() -> DaemonMode:
        """Detect the appropriate daemon mode based on system state.

        If a system service is installed (launchd/systemd), returns EXTERNAL.
        Otherwise returns MANAGED (TUI will spawn the subprocess).

        Returns:
            DaemonMode indicating how to connect to the daemon.
        """
        from styrened.tui.services.service_installer import (
            ServiceStatus,
            get_service_status,
        )

        info = await get_service_status()
        if info.status in (ServiceStatus.RUNNING, ServiceStatus.INSTALLED_STOPPED):
            return DaemonMode.EXTERNAL
        return DaemonMode.MANAGED

    def __init__(
        self,
        mode: DaemonMode = DaemonMode.MANAGED,
        socket_path: Path | None = None,
    ) -> None:
        self._mode = mode
        self._socket_path = socket_path or get_default_socket_path()
        self._process: asyncio.subprocess.Process | None = None
        self._health_task: asyncio.Task | None = None
        self._running = False

    @property
    def mode(self) -> DaemonMode:
        return self._mode

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def is_running(self) -> bool:
        return self._running

    async def ensure_running(self) -> bool:
        """Ensure the daemon is running and reachable.

        In managed mode, spawns the subprocess if not already running.
        In external mode, verifies the socket exists and responds to ping.
        In fallback mode, returns False (caller should use legacy path).

        Returns:
            True if daemon is running and reachable, False otherwise.
        """
        if self._mode == DaemonMode.FALLBACK:
            logger.debug("Fallback mode — skipping daemon startup")
            return False

        # Check if daemon is already reachable
        if await self._ping():
            logger.info(f"Daemon already running at {self._socket_path}")
            self._running = True
            self._start_health_monitor()
            return True

        if self._mode == DaemonMode.EXTERNAL:
            logger.warning(f"External daemon not reachable at {self._socket_path}")
            return False

        # Managed mode — spawn the subprocess
        return await self._spawn()

    async def shutdown(self) -> None:
        """Stop the daemon and clean up.

        In managed mode, sends SIGTERM with a grace period, then SIGKILL.
        In external mode, just stops health monitoring (doesn't kill daemon).
        """
        self._stop_health_monitor()

        if self._mode != DaemonMode.MANAGED or self._process is None:
            self._running = False
            return

        logger.info("Shutting down managed daemon...")

        try:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(
                    self._process.wait(),
                    timeout=_SHUTDOWN_GRACE_SECONDS,
                )
                logger.info(f"Daemon exited (code {self._process.returncode})")
            except TimeoutError:
                logger.warning("Daemon did not exit in time, sending SIGKILL")
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            logger.debug("Daemon process already gone")
        except Exception as e:
            logger.error(f"Error shutting down daemon: {e}")
        finally:
            self._process = None
            self._running = False

    async def restart(self) -> bool:
        """Restart the daemon (shutdown then start).

        Returns:
            True if daemon restarted successfully, False otherwise.
        """
        logger.info("Restarting daemon...")
        await self.shutdown()
        # Brief pause for socket cleanup
        await asyncio.sleep(0.5)
        return await self.ensure_running()

    @staticmethod
    def _find_styrened_binary() -> str:
        """Locate the styrened binary.

        Search order:
            1. Same directory as the running Python interpreter (venv/bin)
            2. System PATH via shutil.which
        """
        # Check next to sys.executable (handles venv installs)
        candidate = Path(sys.executable).parent / "styrened"
        if candidate.is_file():
            return str(candidate)
        found = shutil.which("styrened")
        if found:
            return found
        raise FileNotFoundError("styrened binary not found on PATH or in venv")

    async def _spawn(self) -> bool:
        """Spawn styrened as a subprocess and wait for the socket."""
        logger.info("Spawning styrened daemon...")

        try:
            styrened_bin = self._find_styrened_binary()
            self._process = await asyncio.create_subprocess_exec(
                styrened_bin, "daemon",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            logger.error("styrened binary not found on PATH or in venv")
            return False
        except Exception as e:
            logger.error(f"Failed to spawn daemon: {e}")
            return False

        # Poll for socket to appear and daemon to respond
        elapsed = 0.0
        while elapsed < _SOCKET_POLL_TIMEOUT:
            # Check if process died during startup
            if self._process.returncode is not None:
                stderr = ""
                if self._process.stderr:
                    stderr_bytes = await self._process.stderr.read()
                    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
                logger.error(
                    f"Daemon exited during startup (code {self._process.returncode})"
                    + (f": {stderr[:500]}" if stderr else "")
                )
                self._process = None
                return False

            if await self._ping():
                logger.info(f"Daemon ready after {elapsed:.1f}s")
                self._running = True
                self._start_health_monitor()
                return True

            await asyncio.sleep(_SOCKET_POLL_INTERVAL)
            elapsed += _SOCKET_POLL_INTERVAL

        logger.error(f"Daemon did not become ready within {_SOCKET_POLL_TIMEOUT}s")
        await self.shutdown()
        return False

    async def _ping(self) -> bool:
        """Check if the daemon is responsive via IPC ping."""
        if not self._socket_path.exists():
            return False

        try:
            from styrened.ipc import ControlClient

            client = ControlClient(socket_path=self._socket_path, timeout=3.0)
            try:
                await client.connect()
                result = await client.ping(timeout=2.0)
                return result
            finally:
                await client.disconnect()
        except Exception:
            return False

    def _start_health_monitor(self) -> None:
        """Start background health check task."""
        if self._health_task is not None:
            return
        self._health_task = asyncio.create_task(self._monitor_health())

    def _stop_health_monitor(self) -> None:
        """Cancel the background health check task."""
        if self._health_task is not None:
            self._health_task.cancel()
            self._health_task = None

    async def _monitor_health(self) -> None:
        """Periodically ping the daemon to detect crashes."""
        consecutive_failures = 0
        try:
            while self._running:
                await asyncio.sleep(_HEALTH_CHECK_INTERVAL)

                if await self._ping():
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.warning(
                        f"Daemon health check failed "
                        f"({consecutive_failures} consecutive)"
                    )

                    if consecutive_failures >= 3:
                        logger.error("Daemon appears to have crashed")
                        self._running = False
                        break
        except asyncio.CancelledError:
            pass
