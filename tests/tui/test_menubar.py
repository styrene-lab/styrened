"""Tests for the macOS menu bar agent module."""
from __future__ import annotations


import time

from styrened.tui.menubar.agent import MenuBarState, _relative_time


class TestMenuBarState:
    """Tests for thread-safe MenuBarState."""

    def test_initial_state(self):
        state = MenuBarState()
        assert state.unread_total == 0
        assert state.daemon_connected is False
        assert state.conversations == []

    def test_update_unread(self):
        state = MenuBarState()
        state.update(unread=5)
        unread, connected, convs = state.snapshot()
        assert unread == 5
        assert connected is False

    def test_update_connected(self):
        state = MenuBarState()
        state.update(connected=True)
        _, connected, _ = state.snapshot()
        assert connected is True

    def test_update_conversations(self):
        state = MenuBarState()
        convs = [{"peer_hash": "abc", "unread_count": 2}]
        state.update(conversations=convs)
        _, _, result = state.snapshot()
        assert len(result) == 1
        assert result[0]["peer_hash"] == "abc"

    def test_snapshot_returns_copy(self):
        state = MenuBarState()
        convs = [{"peer_hash": "abc"}]
        state.update(conversations=convs)
        _, _, result = state.snapshot()
        result.append({"peer_hash": "xyz"})
        _, _, result2 = state.snapshot()
        assert len(result2) == 1

    def test_update_sets_last_update(self):
        state = MenuBarState()
        before = time.time()
        state.update(unread=1)
        assert state.last_update >= before


class TestRelativeTime:
    """Tests for _relative_time helper."""

    def test_zero_timestamp(self):
        assert _relative_time(0) == ""

    def test_recent(self):
        assert _relative_time(time.time() - 10) == "now"

    def test_minutes(self):
        assert _relative_time(time.time() - 300) == "5m"

    def test_hours(self):
        assert _relative_time(time.time() - 7200) == "2h"

    def test_days(self):
        assert _relative_time(time.time() - 172800) == "2d"
