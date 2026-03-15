"""Tests for composable widget resource-scope helpers."""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, Mock

import pytest

from styrened.tui.lifecycle.widget_resources import WidgetResourceScope


class _DummyOwner:
    def __init__(self) -> None:
        self.run_worker = Mock()
        self.set_interval = Mock()
        self.set_timer = Mock()


def test_run_worker_passes_callable_instead_of_eager_coroutine() -> None:
    """run_worker should receive a callable/partial, not a bare coroutine object."""
    owner = _DummyOwner()
    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]

    async def sample(value: str) -> str:
        return value

    scope.run_worker(sample, "abc", group="sample")

    scheduled = owner.run_worker.call_args.args[0]
    assert callable(scheduled)
    assert not inspect.iscoroutine(scheduled)

    coroutine = scheduled()
    assert inspect.iscoroutine(coroutine)
    coroutine.close()


def test_stop_timer_stops_and_clears_owner_attribute() -> None:
    """Tracked timers should stop and clear their widget attribute."""
    owner = _DummyOwner()
    timer = Mock()
    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]

    scope.adopt_timer("_poll_timer", timer)
    scope.stop_timer("_poll_timer")

    timer.stop.assert_called_once_with()
    assert owner._poll_timer is None


@pytest.mark.asyncio
async def test_aclose_runs_subscription_cleanup_and_disconnects_auxiliary_lane() -> None:
    """Immediate async teardown should run sync/async cleanup and disconnect lanes."""
    owner = _DummyOwner()
    remove_handler = Mock()
    unsubscribe = AsyncMock()
    lane = Mock()
    lane.disconnect = AsyncMock()

    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]
    scope.own_subscription(remove=remove_handler, unsubscribe=unsubscribe)
    scope.adopt_auxiliary_lane("_page_bridge", lane, shared_lane=object())

    await scope.aclose()

    remove_handler.assert_called_once_with()
    unsubscribe.assert_awaited_once_with()
    lane.disconnect.assert_awaited_once_with()
    assert owner._page_bridge is None


@pytest.mark.asyncio
async def test_aclose_skips_disconnect_for_shared_lane() -> None:
    """Shared control lanes should not be disconnected during widget teardown."""
    owner = _DummyOwner()
    shared_lane = Mock()
    shared_lane.disconnect = AsyncMock()

    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]
    scope.adopt_auxiliary_lane("_page_bridge", shared_lane, shared_lane=shared_lane)

    await scope.aclose()

    shared_lane.disconnect.assert_not_called()
    assert owner._page_bridge is None


@pytest.mark.asyncio
async def test_release_executes_sync_cleanup_and_schedules_async_teardown() -> None:
    """release() should run sync cleanup now and async cleanup on the event loop."""
    owner = _DummyOwner()
    remove_handler = Mock()
    unsubscribe = AsyncMock()
    lane = Mock()
    lane.disconnect = AsyncMock()

    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]
    scope.own_subscription(remove=remove_handler, unsubscribe=unsubscribe)
    scope.adopt_auxiliary_lane("_page_bridge", lane, shared_lane=object())

    scope.release(group="widget-cleanup")
    await asyncio.sleep(0)

    remove_handler.assert_called_once_with()
    unsubscribe.assert_awaited_once_with()
    lane.disconnect.assert_awaited_once_with()
    assert owner._page_bridge is None


# ---------------------------------------------------------------------------
# Worker sequencing tests
# ---------------------------------------------------------------------------


def test_own_worker_returns_worker() -> None:
    """own_worker() should return the worker unchanged for one-liner use."""
    owner = _DummyOwner()
    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]

    worker = Mock()
    result = scope.own_worker(worker)
    assert result is worker


def test_cancel_workers_cancels_all_tracked_workers() -> None:
    """cancel_workers() should cancel every worker registered via own_worker()."""
    owner = _DummyOwner()
    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]

    w1 = Mock()
    w2 = Mock()
    scope.own_worker(w1)
    scope.own_worker(w2)

    scope.cancel_workers()

    w1.cancel.assert_called_once_with()
    w2.cancel.assert_called_once_with()


def test_cancel_workers_clears_worker_list() -> None:
    """After cancel_workers(), re-calling it should not double-cancel."""
    owner = _DummyOwner()
    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]

    worker = Mock()
    scope.own_worker(worker)

    scope.cancel_workers()
    scope.cancel_workers()  # second call — nothing to cancel

    worker.cancel.assert_called_once_with()


@pytest.mark.asyncio
async def test_aclose_cancels_workers_before_disconnecting_lanes() -> None:
    """Workers must be cancelled before auxiliary lanes are disconnected during aclose()."""
    owner = _DummyOwner()
    call_order: list[str] = []

    worker = Mock()
    worker.cancel = Mock(side_effect=lambda: call_order.append("worker_cancel"))

    lane = Mock()
    async_disconnect = AsyncMock(side_effect=lambda: call_order.append("lane_disconnect"))
    lane.disconnect = async_disconnect

    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]
    scope.own_worker(worker)
    scope.adopt_auxiliary_lane("_aux_lane", lane, shared_lane=object())

    await scope.aclose()

    assert call_order == ["worker_cancel", "lane_disconnect"], (
        f"Expected [worker_cancel, lane_disconnect], got {call_order}"
    )
    assert owner._aux_lane is None


@pytest.mark.asyncio
async def test_aclose_workers_cancelled_even_when_no_lanes() -> None:
    """Workers should be cancelled during aclose() even when there are no lanes."""
    owner = _DummyOwner()

    worker = Mock()
    scope = WidgetResourceScope(owner)  # type: ignore[arg-type]
    scope.own_worker(worker)

    await scope.aclose()

    worker.cancel.assert_called_once_with()
