"""Base screen class for all Styrene TUI screens.

Provides a consistent lifecycle contract with loading indicator,
retry logic, and bridge access.
"""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Generic, TypeVar

from textual.screen import Screen
from textual.widgets import LoadingIndicator
from textual.worker import Worker, WorkerState

if TYPE_CHECKING:
    from styrened.ipc.bridge import IPCBridge

log = logging.getLogger(__name__)

T = TypeVar("T")

__all__ = ["StyreneScreen", "StyreneLoadingIndicator", "BridgeUnavailableError"]

_RETRY_DELAYS = (0.5, 1.0, 2.0)
_MAX_ATTEMPTS = 3


class BridgeUnavailableError(Exception):
    """Raised when the IPC bridge is not connected."""


class StyreneLoadingIndicator(LoadingIndicator):
    """LoadingIndicator with Styrene theming."""

    DEFAULT_CSS = """
    StyreneLoadingIndicator {
        height: 1;
        color: $accent;
    }
    """

    def __init__(self, message: str = "Loading…", **kwargs):
        super().__init__(**kwargs)
        self._message = message

    @property
    def message(self) -> str:
        return self._message


class StyreneScreen(Screen[T], Generic[T]):
    """Base class for all Styrene TUI screens.

    Lifecycle contract:
    - compose() is pure structure — no I/O
    - on_mount() calls _start_load() which runs _load_data() in an exclusive worker
    - on_screen_resume() calls _start_load() again (always refreshes on re-entry)
    - on_screen_suspend() cancels the active load worker and calls _cleanup()
    - on_unmount() cancels all tracked workers and calls _cleanup()
    - _load_data() (abstract) — subclasses implement this to fetch data via self.bridge
    - _cleanup() (optional hook) — subclasses override to cancel screen-specific resources
    - _on_error(error, attempt) (optional hook) — called after retry exhaustion
    - _loading_message() -> str (optional hook) — label for StyreneLoadingIndicator
    - self.bridge property — returns app.services.bridge, raises BridgeUnavailableError if None
    - Retry logic: up to 3 attempts with exponential backoff (0.5s, 1s, 2s)
    - Shows StyreneLoadingIndicator before first successful load, hides after
    - After first successful load, stale data is kept visible on error
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._load_worker: Worker | None = None
        self._first_load_done: bool = False
        self._loading_indicator: StyreneLoadingIndicator | None = None

    # ------------------------------------------------------------------
    # Public hooks — subclasses implement / override these
    # ------------------------------------------------------------------

    @abstractmethod
    async def _load_data(self) -> None:
        """Fetch data and populate the screen. Called with retry logic.

        Access the daemon via self.bridge.  Raise any exception to trigger
        a retry.
        """

    def _cleanup(self) -> None:
        """Called on suspend and unmount. Override to cancel timers/resources."""

    async def _on_error(self, error: Exception, attempt: int) -> None:
        """Called after retry exhaustion. Default notifies the user."""
        screen_name = type(self).__name__
        log.error("%s: load failed after %d attempts: %s", screen_name, attempt, error)
        self.notify(f"Failed to load data: {error}", severity="error")

    def _loading_message(self) -> str:
        """Return the label shown in the loading indicator."""
        return "Loading…"

    # ------------------------------------------------------------------
    # Bridge property
    # ------------------------------------------------------------------

    @property
    def bridge(self) -> IPCBridge:
        """Return the IPC bridge. Raises BridgeUnavailableError if not connected."""
        app = self.app
        # Access services via duck-typing to avoid a circular import on StyreneApp.
        # All screens run inside StyreneApp so .services is always present.
        services = getattr(app, "services", None)
        if services is None:
            raise BridgeUnavailableError("App has no services")
        b = getattr(services, "bridge", None)
        if b is None:
            raise BridgeUnavailableError("IPC bridge is not connected")
        # b is IPCBridge at this point; cast to satisfy mypy
        from styrened.ipc.bridge import IPCBridge as _IPCBridge

        assert isinstance(b, _IPCBridge)
        return b

    # ------------------------------------------------------------------
    # Internal lifecycle
    # ------------------------------------------------------------------

    def _start_load(self) -> None:
        """Cancel any existing load worker and start a fresh one."""
        screen_name = type(self).__name__
        if self._load_worker is not None and self._load_worker.state in (WorkerState.PENDING, WorkerState.RUNNING):
            log.debug("%s: cancelling previous load worker", screen_name)
            self._load_worker.cancel()
        log.debug("%s: starting load worker", screen_name)
        self._load_worker = self.run_worker(
            self._run_load(), exclusive=True, group="screen-load"
        )

    async def _run_load(self) -> None:
        """Internal: run _load_data() with retry and backoff."""
        screen_name = type(self).__name__

        # Show loading indicator before first successful load
        if not self._first_load_done:
            await self._show_loading_indicator()

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            log.debug("%s: _load_data attempt %d/%d", screen_name, attempt, _MAX_ATTEMPTS)
            try:
                await self._load_data()
                self._first_load_done = True
                await self._hide_loading_indicator()
                return
            except Exception as exc:
                last_error = exc
                log.debug(
                    "%s: attempt %d failed: %s", screen_name, attempt, exc
                )
                if attempt < _MAX_ATTEMPTS:
                    delay = _RETRY_DELAYS[attempt - 1]
                    log.debug("%s: retrying in %.1fs", screen_name, delay)
                    await asyncio.sleep(delay)

        # Exhausted all attempts
        if last_error is not None:
            await self._on_error(last_error, _MAX_ATTEMPTS)
        if not self._first_load_done:
            await self._hide_loading_indicator()

    async def _show_loading_indicator(self) -> None:
        """Mount the loading indicator if not already present."""
        if self._loading_indicator is None:
            self._loading_indicator = StyreneLoadingIndicator(self._loading_message())
            await self.mount(self._loading_indicator)

    async def _hide_loading_indicator(self) -> None:
        """Remove the loading indicator."""
        if self._loading_indicator is not None:
            await self._loading_indicator.remove()
            self._loading_indicator = None

    # ------------------------------------------------------------------
    # Textual lifecycle hooks
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        log.debug("%s: on_mount — starting load", type(self).__name__)
        self._start_load()

    def on_screen_resume(self) -> None:
        log.debug("%s: on_screen_resume — refreshing", type(self).__name__)
        self._start_load()

    def on_screen_suspend(self) -> None:
        screen_name = type(self).__name__
        log.debug("%s: on_screen_suspend — cancelling worker", screen_name)
        if self._load_worker is not None and self._load_worker.state in (WorkerState.PENDING, WorkerState.RUNNING):
            self._load_worker.cancel()
        self._cleanup()

    def on_unmount(self) -> None:
        screen_name = type(self).__name__
        log.debug("%s: on_unmount — cancelling all workers", screen_name)
        if self._load_worker is not None and self._load_worker.state in (WorkerState.PENDING, WorkerState.RUNNING):
            self._load_worker.cancel()
        self._cleanup()
