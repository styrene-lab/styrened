"""Composable lifecycle helpers for widget-owned runtime resources."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from textual.timer import Timer
from textual.widget import Widget

logger = logging.getLogger(__name__)


CleanupCallback = Callable[[], Any]


@dataclass(slots=True)
class _AuxiliaryLaneEntry:
    shared_lane: Any | None
    disconnect_method: str = "disconnect"


@dataclass(slots=True)
class _CloseState:
    timers: dict[str, Timer]
    cleanups: list[CleanupCallback]
    async_cleanups: list[CleanupCallback]
    auxiliary_lanes: list[tuple[str, Any | None, _AuxiliaryLaneEntry]]
    workers: list[Any] = field(default_factory=list)


class WidgetResourceScope:
    """Own timers, teardown callbacks, workers, and auxiliary IPC lanes for a widget.

    The scope is composition-first: widgets keep their own state and error handling,
    while the scope centralizes the repetitive lifecycle bookkeeping.
    """

    def __init__(self, owner: Widget, *, owner_logger: logging.Logger | None = None) -> None:
        self._owner = owner
        self._logger = owner_logger or logger
        self._timers: dict[str, Timer] = {}
        self._cleanups: list[CleanupCallback] = []
        self._async_cleanups: list[CleanupCallback] = []
        self._auxiliary_lanes: dict[str, _AuxiliaryLaneEntry] = {}
        self._workers: list[Any] = []

    def run_worker(self, fn: Any, *args: Any, **worker_kwargs: Any) -> Any:
        """Schedule async work without eagerly creating coroutine objects."""
        work = partial(fn, *args) if args else fn
        return self._owner.run_worker(work, **worker_kwargs)

    def set_interval(
        self,
        attr_name: str,
        interval: float,
        callback: Callable[..., Any],
        **timer_kwargs: Any,
    ) -> Timer:
        """Create and track an interval timer on the widget."""
        timer = self._owner.set_interval(interval, callback, **timer_kwargs)
        self.adopt_timer(attr_name, timer)
        return timer

    def set_timer(
        self,
        attr_name: str,
        delay: float,
        callback: Callable[..., Any],
        **timer_kwargs: Any,
    ) -> Timer:
        """Create and track a one-shot timer on the widget."""
        timer = self._owner.set_timer(delay, callback, **timer_kwargs)
        self.adopt_timer(attr_name, timer)
        return timer

    def adopt_timer(self, attr_name: str, timer: Timer | None) -> Timer | None:
        """Track an existing widget timer under the given attribute name."""
        self.stop_timer(attr_name)
        setattr(self._owner, attr_name, timer)
        if timer is not None:
            self._timers[attr_name] = timer
        return timer

    def stop_timer(self, attr_name: str) -> None:
        """Stop and clear a tracked timer if present."""
        timer = self._timers.pop(attr_name, None)
        if timer is None:
            timer = getattr(self._owner, attr_name, None)

        if timer is not None:
            try:
                timer.stop()
            except Exception:
                self._logger.debug("Failed to stop timer %s", attr_name, exc_info=True)

        try:
            setattr(self._owner, attr_name, None)
        except Exception:
            self._logger.debug("Failed to clear timer attribute %s", attr_name, exc_info=True)

    def own_cleanup(self, callback: CleanupCallback) -> CleanupCallback:
        """Register synchronous cleanup that should run during teardown."""
        self._cleanups.append(callback)
        return callback

    def own_async_cleanup(self, callback: CleanupCallback) -> CleanupCallback:
        """Register async cleanup without eagerly creating a coroutine object."""
        self._async_cleanups.append(callback)
        return callback

    def own_worker(self, worker: Any) -> Any:
        """Track a Textual Worker so it is cancelled before auxiliary lanes are disconnected.

        The worker must have a ``.cancel()`` method (all Textual ``Worker``
        objects do).  Cancelled workers are removed from tracking automatically
        during the next teardown cycle.

        Returns the worker unchanged so callers can use this as a one-liner::

            self._resources.own_worker(self.run_worker(self._fetch))
        """
        self._workers.append(worker)
        return worker

    def cancel_workers(self) -> None:
        """Cancel all tracked workers without disconnecting auxiliary lanes.

        Useful when a suspend/pause event should halt in-flight work but lanes
        should remain connected for a subsequent resume.
        """
        workers, self._workers = self._workers, []
        for worker in workers:
            try:
                worker.cancel()
            except Exception:
                self._logger.debug("Failed to cancel tracked worker", exc_info=True)

    def own_subscription(
        self,
        *,
        remove: CleanupCallback | None = None,
        unsubscribe: CleanupCallback | None = None,
    ) -> None:
        """Register paired subscription cleanup callbacks."""
        if remove is not None:
            self.own_cleanup(remove)
        if unsubscribe is not None:
            self.own_async_cleanup(unsubscribe)

    def adopt_auxiliary_lane(
        self,
        attr_name: str,
        lane: Any | None,
        *,
        shared_lane: Any | None = None,
        disconnect_method: str = "disconnect",
    ) -> Any | None:
        """Track a widget-owned auxiliary lane for disconnect on teardown."""
        setattr(self._owner, attr_name, lane)
        self._auxiliary_lanes[attr_name] = _AuxiliaryLaneEntry(
            shared_lane=shared_lane,
            disconnect_method=disconnect_method,
        )
        return lane

    def release(self, *, exclusive: bool = False, group: str | None = None) -> None:
        """Release all tracked resources, scheduling async teardown if needed."""
        state = self._drain_close_state()
        self._close_sync(state)
        if not state.async_cleanups and not state.auxiliary_lanes:
            return

        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._close_async(state.async_cleanups, state.auxiliary_lanes))
            task.add_done_callback(self._consume_task_exception)
            return
        except Exception:
            self._logger.debug("Falling back to worker-scheduled widget teardown", exc_info=True)

        try:
            self.run_worker(
                self._close_async,
                state.async_cleanups,
                state.auxiliary_lanes,
                exclusive=exclusive,
                group=group,
            )
        except Exception:
            self._logger.debug("Failed to schedule async widget teardown", exc_info=True)

    async def aclose(self) -> None:
        """Release all tracked resources immediately in the current task."""
        state = self._drain_close_state()
        self._close_sync(state)
        await self._close_async(state.async_cleanups, state.auxiliary_lanes)

    def _drain_close_state(self) -> _CloseState:
        timers = self._timers
        self._timers = {}

        cleanups = self._cleanups
        self._cleanups = []

        async_cleanups = self._async_cleanups
        self._async_cleanups = []

        workers = self._workers
        self._workers = []

        auxiliary_lanes: list[tuple[str, Any | None, _AuxiliaryLaneEntry]] = []
        for attr_name, entry in self._auxiliary_lanes.items():
            auxiliary_lanes.append((attr_name, getattr(self._owner, attr_name, None), entry))
            try:
                setattr(self._owner, attr_name, None)
            except Exception:
                self._logger.debug(
                    "Failed to clear auxiliary lane attribute %s",
                    attr_name,
                    exc_info=True,
                )
        self._auxiliary_lanes = {}

        for attr_name in timers:
            try:
                setattr(self._owner, attr_name, None)
            except Exception:
                self._logger.debug("Failed to clear timer attribute %s", attr_name, exc_info=True)

        return _CloseState(
            timers=timers,
            cleanups=cleanups,
            async_cleanups=async_cleanups,
            auxiliary_lanes=auxiliary_lanes,
            workers=workers,
        )

    def _close_sync(self, state: _CloseState) -> None:
        # Cancel tracked workers first — they may hold references to auxiliary
        # lanes and must be stopped before those lanes are disconnected.
        for worker in state.workers:
            try:
                worker.cancel()
            except Exception:
                self._logger.debug("Failed to cancel tracked worker", exc_info=True)

        for attr_name, timer in state.timers.items():
            try:
                timer.stop()
            except Exception:
                self._logger.debug("Failed to stop timer %s", attr_name, exc_info=True)

        for callback in state.cleanups:
            try:
                callback()
            except Exception:
                self._logger.debug("Widget cleanup callback failed", exc_info=True)

    async def _close_async(
        self,
        async_cleanups: list[CleanupCallback],
        auxiliary_lanes: list[tuple[str, Any | None, _AuxiliaryLaneEntry]],
    ) -> None:
        for callback in async_cleanups:
            await self._await_cleanup(callback)

        for attr_name, lane, entry in auxiliary_lanes:
            if lane is None or lane is entry.shared_lane:
                continue
            disconnect = getattr(lane, entry.disconnect_method, None)
            if not callable(disconnect):
                continue
            try:
                result = disconnect()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                self._logger.debug(
                    "Failed to disconnect auxiliary lane %s",
                    attr_name,
                    exc_info=True,
                )

    async def _await_cleanup(self, callback: CleanupCallback) -> None:
        try:
            result = callback()
            if inspect.isawaitable(result):
                await result
        except Exception:
            self._logger.debug("Async widget cleanup callback failed", exc_info=True)

    def _consume_task_exception(self, task: asyncio.Task[Any]) -> None:
        try:
            _ = task.exception()
        except Exception:
            pass
