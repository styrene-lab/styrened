"""
DaemonAdapter — abstract base class for optional system daemon integration.

Provides the three-tier model (DISABLED / ADOPT / MANAGED) for external
daemons like Yggdrasil and i2pd. All timing uses time.monotonic() exclusively.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)


class DaemonMode(str, Enum):
    """Operating mode for an optional daemon integration."""

    DISABLED = "disabled"
    ADOPT = "adopt"
    MANAGED = "managed"


@dataclass
class DaemonStatus:
    """Current status snapshot for an optional daemon."""

    mode: DaemonMode
    running: bool
    warming_up: bool
    warm_up_elapsed: float
    warm_up_expected: float
    details: dict = field(default_factory=dict)


class DaemonAdapter(ABC):
    """Abstract base class for optional system daemon integration.

    Subclasses must implement:
    - _probe()          — check if the daemon is reachable
    - _start_managed()  — start the managed process
    - _stop_managed()   — stop the managed process
    - _gather_details() — collect daemon-specific status info
    - warm_up_seconds   — expected warm-up duration (property)

    Lifecycle contract:
    - provision() is separate from start(). Call provision() first to ensure
      the binary exists before start() is ever called.
    - start() / stop() manage the process lifecycle.
    - status() returns a snapshot; _gather_details() is skipped during warm-up
      and results are cached in _cached_details.
    """

    def __init__(self, mode: DaemonMode) -> None:
        self.mode = mode
        self._process: asyncio.subprocess.Process | None = None
        self._started_at: float | None = None
        self._cached_details: dict | None = None
        self._supervision_task: asyncio.Task | None = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Abstract interface — subclasses must implement
    # ------------------------------------------------------------------

    @abstractmethod
    async def _probe(self) -> bool:
        """Return True if the daemon is reachable / responsive."""

    @abstractmethod
    async def _start_managed(self) -> None:
        """Start the daemon process (MANAGED mode only)."""

    @abstractmethod
    async def _stop_managed(self) -> None:
        """Stop the daemon process (MANAGED mode only)."""

    @abstractmethod
    async def _gather_details(self) -> dict:
        """Collect daemon-specific status info (address, peers, etc.)."""

    @property
    @abstractmethod
    def warm_up_seconds(self) -> float:
        """Expected warm-up duration for this daemon in seconds."""

    # ------------------------------------------------------------------
    # Provision — binary acquisition; separate from start()
    # ------------------------------------------------------------------

    async def provision(self) -> None:
        """Acquire the daemon binary.

        Binary acquisition belongs here, *not* in start(). Concrete
        subclasses override this method to check for / install the binary.
        """
        raise NotImplementedError(
            "binary acquisition belongs here, not in start()"
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the daemon according to its mode.

        - DISABLED: return immediately, no-op.
        - MANAGED: call _start_managed(), record _started_at, launch supervision.
        - ADOPT:   no-op (daemon was already running; probe happens on status()).
        """
        if self.mode == DaemonMode.DISABLED:
            return
        if self.mode == DaemonMode.MANAGED:
            await self._start_managed()
            self._started_at = time.monotonic()
            self._supervision_task = asyncio.ensure_future(
                self._run_supervision_loop()
            )
        # ADOPT: nothing to start

    async def stop(self) -> None:
        """Stop the daemon according to its mode.

        - MANAGED: cancel supervision task, then call _stop_managed().
        - ADOPT / DISABLED: no-op.
        """
        if self.mode != DaemonMode.MANAGED:
            return
        if self._supervision_task is not None:
            self._supervision_task.cancel()
            try:
                await self._supervision_task
            except (asyncio.CancelledError, Exception):
                pass
            self._supervision_task = None
        await self._stop_managed()

    # ------------------------------------------------------------------
    # Supervision loop (MANAGED only)
    # ------------------------------------------------------------------

    async def _run_supervision_loop(self) -> None:
        """Watch the managed process and restart it with exponential backoff.

        Backoff sequence: 1 s, 2 s, 4 s, 8 s … capped at 60 s.
        _started_at is reset with time.monotonic() on each restart so that
        is_warming_up reflects the *current* restart's age, not the first start.
        """
        backoff = 1.0
        while True:
            if self._process is not None:
                try:
                    await self._process.wait()
                    rc = self._process.returncode
                    log.warning(
                        "Managed daemon exited (rc=%s); restarting in %.0fs",
                        rc,
                        backoff,
                    )
                except Exception as exc:
                    log.warning(
                        "Supervision loop error waiting for process: %s; "
                        "restarting in %.0fs",
                        exc,
                        backoff,
                    )
            else:
                # Process is None — first iteration delay or recovery
                log.warning(
                    "Managed daemon process not found; restarting in %.0fs",
                    backoff,
                )

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

            try:
                await self._start_managed()
                self._started_at = time.monotonic()
                log.info("Managed daemon restarted successfully")
                backoff = 1.0  # reset after successful start
            except Exception as exc:
                log.error("Failed to restart managed daemon: %s", exc)
                # Keep backing off — do not reset backoff on failure

    # ------------------------------------------------------------------
    # Warm-up property
    # ------------------------------------------------------------------

    @property
    def is_warming_up(self) -> bool:
        """True if MANAGED process is still within its warm-up window.

        Uses time.monotonic() exclusively. Returns False if not MANAGED or
        if _started_at is None.
        """
        if self.mode != DaemonMode.MANAGED or self._started_at is None:
            return False
        elapsed = time.monotonic() - self._started_at
        return elapsed < self.warm_up_seconds

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    async def status(self) -> DaemonStatus:
        """Return the current status snapshot.

        - DISABLED: always not running.
        - ADOPT / MANAGED: probe, then optionally gather details.
          _gather_details() is skipped while warming_up; result is cached
          in _cached_details and served from cache during the warm-up window.
        """
        if self.mode == DaemonMode.DISABLED:
            return DaemonStatus(
                mode=self.mode,
                running=False,
                warming_up=False,
                warm_up_elapsed=0.0,
                warm_up_expected=self.warm_up_seconds,
                details={},
            )

        running = await self._probe()
        warming = self.is_warming_up
        elapsed = (
            time.monotonic() - self._started_at
            if self._started_at is not None
            else 0.0
        )

        if running and not warming:
            try:
                details = await self._gather_details()
                self._cached_details = details
            except Exception as exc:
                log.warning("_gather_details() failed: %s", exc)
                details = self._cached_details or {}
        else:
            # Warming up or not running — serve cached details (may be empty)
            details = self._cached_details or {}

        return DaemonStatus(
            mode=self.mode,
            running=running,
            warming_up=warming,
            warm_up_elapsed=elapsed,
            warm_up_expected=self.warm_up_seconds,
            details=details,
        )

    # ------------------------------------------------------------------
    # Config-directory helper
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_config_dir(path: Path) -> None:
        """Create *path* with mode 0700 (owner-only).

        Key files within *path* (files whose name contains 'key', 'private',
        or 'secret', case-insensitive) are chmod'd to 0600 if they already
        exist.  Newly created files should call chmod explicitly in the
        subclass after writing.
        """
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)

        for child in path.iterdir():
            name_lower = child.name.lower()
            if child.is_file() and any(
                kw in name_lower for kw in ("key", "private", "secret")
            ):
                child.chmod(0o600)
