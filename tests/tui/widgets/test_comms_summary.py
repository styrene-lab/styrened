"""Tests for CommsSummaryWidget lifecycle helpers."""

from __future__ import annotations

import inspect
from unittest.mock import Mock

from styrened.tui.widgets.comms_summary import CommsSummaryWidget


def test_refresh_schedules_callable_worker() -> None:
    """_refresh should pass a callable into run_worker, not a coroutine object."""
    widget = CommsSummaryWidget()
    widget.run_worker = Mock()

    widget._refresh()

    scheduled = widget.run_worker.call_args.args[0]
    assert callable(scheduled)
    assert not inspect.iscoroutine(scheduled)

    coroutine = scheduled()
    assert inspect.iscoroutine(coroutine)
    coroutine.close()


def test_on_unmount_stops_poll_timer() -> None:
    """Widget teardown should stop the owned poll timer."""
    widget = CommsSummaryWidget()
    timer = Mock()
    widget._resources.adopt_timer("_poll_timer", timer)

    widget.on_unmount()

    timer.stop.assert_called_once_with()
    assert widget._poll_timer is None
