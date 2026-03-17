"""Tests for AdapterStatusBar widget and AdapterStatusTracker model.

Validates:
- Per-state Rich markup (icon, colour keywords present in rendered output)
- DISABLED dim/dashed visual language
- Empty snapshot placeholder
- Tracker ingest → snapshot round-trip
- Tracker situation line generation for transitions
- No situation line for DISABLED-origin transitions
"""
from __future__ import annotations

import io

import pytest
from rich.console import Console
from rich.text import Text

from styrened.tui.models.adapter_status import (
    AdapterDisplayState,
    AdapterEntry,
    AdapterStatusSnapshot,
    AdapterStatusTracker,
)
from styrened.tui.models.cop_situation import SituationPriority
from styrened.tui.models.events import DaemonEvent
from styrened.tui.widgets.adapter_status_bar import AdapterStatusBar

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(*adapters: tuple[str, AdapterDisplayState, str]) -> AdapterStatusSnapshot:
    entries = [AdapterEntry(name=n, state=s, detail=d) for n, s, d in adapters]
    return AdapterStatusSnapshot(adapters=entries)


def _make_bar(snapshot: AdapterStatusSnapshot | None = None) -> AdapterStatusBar:
    bar = AdapterStatusBar()
    if snapshot is not None:
        bar._snapshot = snapshot
    return bar


def _render_plain(bar: AdapterStatusBar) -> str:
    renderable = bar.render()
    buf = io.StringIO()
    console = Console(file=buf, highlight=False, markup=False, width=200)
    console.print(renderable)
    return buf.getvalue().strip()


def _render_rich(bar: AdapterStatusBar) -> Text:
    return bar.render()


def _make_event(adapter_name: str, state: str, detail: str = "") -> DaemonEvent:
    return DaemonEvent(
        event_type="adapter_changed",
        action="state_changed",
        data={"adapter_name": adapter_name, "state": state, "detail": detail},
    )


# ---------------------------------------------------------------------------
# AdapterStatusBar — rendering tests
# ---------------------------------------------------------------------------

class TestEmptySnapshot:
    def test_no_snapshot_renders_placeholder(self) -> None:
        bar = _make_bar()
        text = _render_plain(bar)
        assert "no adapters registered" in text

    def test_empty_snapshot_renders_placeholder(self) -> None:
        bar = _make_bar(AdapterStatusSnapshot(adapters=[]))
        text = _render_plain(bar)
        assert "no adapters registered" in text


class TestDisabledState:
    """DISABLED renders dim dashed language."""

    def test_disabled_shows_dashes(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.DISABLED, "")))
        text = _render_plain(bar)
        assert "I2P" in text
        assert "---" in text

    def test_disabled_icon_is_dim(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.DISABLED, "")))
        rich_text = _render_rich(bar)
        # Find the span containing "---" and verify it's styled dim
        for span in rich_text._spans:
            start, end = span.start, span.end
            fragment = rich_text.plain[start:end]
            if "---" in fragment:
                assert "dim" in str(span.style).lower()
                break
        else:
            pytest.fail("'---' span not found in rendered output")


class TestProbingState:
    def test_probing_shows_circle_icon(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.PROBING, "")))
        text = _render_plain(bar)
        assert "I2P" in text
        assert "◌" in text

    def test_probing_icon_is_amber(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.PROBING, "")))
        rich_text = _render_rich(bar)
        found_amber = False
        for span in rich_text._spans:
            fragment = rich_text.plain[span.start:span.end]
            if "◌" in fragment:
                style_str = str(span.style).lower()
                assert "orange" in style_str or "amber" in style_str, (
                    f"Expected amber/orange, got: {span.style}"
                )
                found_amber = True
                break
        assert found_amber, "No ◌ span found"


class TestWarmingState:
    """WARMING shares amber circle visual with PROBING."""

    def test_warming_shows_circle_icon(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.WARMING, "")))
        text = _render_plain(bar)
        assert "◌" in text

    def test_warming_icon_is_amber(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.WARMING, "")))
        rich_text = _render_rich(bar)
        for span in rich_text._spans:
            fragment = rich_text.plain[span.start:span.end]
            if "◌" in fragment:
                style_str = str(span.style).lower()
                assert "orange" in style_str or "amber" in style_str
                return
        pytest.fail("No ◌ span found for WARMING state")


class TestReadyState:
    def test_ready_shows_green_dot(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.READY, "")))
        text = _render_plain(bar)
        assert "●" in text

    def test_ready_icon_is_green(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.READY, "")))
        rich_text = _render_rich(bar)
        for span in rich_text._spans:
            fragment = rich_text.plain[span.start:span.end]
            if "●" in fragment:
                assert "green" in str(span.style).lower()
                return
        pytest.fail("No ● span found for READY state")


class TestDegradedState:
    def test_degraded_shows_red_x(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.DEGRADED, "")))
        text = _render_plain(bar)
        assert "✕" in text

    def test_degraded_icon_is_red(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.DEGRADED, "")))
        rich_text = _render_rich(bar)
        for span in rich_text._spans:
            fragment = rich_text.plain[span.start:span.end]
            if "✕" in fragment:
                assert "red" in str(span.style).lower()
                return
        pytest.fail("No ✕ span found for DEGRADED state")


class TestMultipleAdapters:
    def test_multiple_adapters_separated_by_pipe(self) -> None:
        bar = _make_bar(_make_snapshot(
            ("I2P", AdapterDisplayState.READY, ""),
            ("Ygg", AdapterDisplayState.PROBING, ""),
        ))
        text = _render_plain(bar)
        assert "I2P" in text
        assert "Ygg" in text
        assert "│" in text

    def test_adapter_with_detail_shows_detail(self) -> None:
        bar = _make_bar(_make_snapshot(("I2P", AdapterDisplayState.READY, "12ms")))
        text = _render_plain(bar)
        assert "12ms" in text


# ---------------------------------------------------------------------------
# AdapterStatusTracker — unit tests
# ---------------------------------------------------------------------------

class TestTrackerIngest:
    def test_ingest_creates_adapter_record(self) -> None:
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("I2P", "ready"))
        snap = tracker.snapshot()
        assert len(snap.adapters) == 1
        assert snap.adapters[0].name == "I2P"
        assert snap.adapters[0].state == AdapterDisplayState.READY

    def test_ingest_updates_existing_adapter(self) -> None:
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("I2P", "warming"))
        tracker.ingest(_make_event("I2P", "ready"))
        snap = tracker.snapshot()
        assert len(snap.adapters) == 1
        assert snap.adapters[0].state == AdapterDisplayState.READY

    def test_ingest_multiple_adapters(self) -> None:
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("I2P", "ready"))
        tracker.ingest(_make_event("Ygg", "probing"))
        snap = tracker.snapshot()
        assert len(snap.adapters) == 2

    def test_non_adapter_event_ignored(self) -> None:
        tracker = AdapterStatusTracker()
        event = DaemonEvent(event_type="node_changed", action="announced", data={})
        tracker.ingest(event)
        snap = tracker.snapshot()
        assert snap.is_empty

    def test_ingest_with_detail(self) -> None:
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("I2P", "ready", "12ms"))
        snap = tracker.snapshot()
        assert snap.adapters[0].detail == "12ms"


class TestTrackerSnapshot:
    def test_empty_tracker_returns_empty_snapshot(self) -> None:
        tracker = AdapterStatusTracker()
        snap = tracker.snapshot()
        assert snap.is_empty

    def test_snapshot_has_degraded(self) -> None:
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("I2P", "degraded"))
        snap = tracker.snapshot()
        assert snap.has_degraded

    def test_snapshot_all_disabled(self) -> None:
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("I2P", "disabled"))
        snap = tracker.snapshot()
        assert snap.all_disabled


class TestTrackerSituationLines:
    """Test get_situation_line() for all meaningful transitions."""

    def _transition(self, old: str, new: str) -> object:
        """Apply two events; return the situation line from the second."""
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("I2P", old))
        tracker.get_situation_line()  # consume any initial line
        tracker.ingest(_make_event("I2P", new))
        return tracker.get_situation_line()

    def test_warming_to_ready_is_informational(self) -> None:
        line = self._transition("warming", "ready")
        assert line is not None
        assert line.priority == SituationPriority.INFO
        assert "ready" in line.message.lower()

    def test_ready_to_degraded_is_anomaly(self) -> None:
        line = self._transition("ready", "degraded")
        assert line is not None
        assert line.priority == SituationPriority.ANOMALY
        assert "degraded" in line.message.lower()

    def test_degraded_to_ready_is_informational(self) -> None:
        line = self._transition("degraded", "ready")
        assert line is not None
        assert line.priority == SituationPriority.INFO
        assert "recover" in line.message.lower()

    def test_disabled_to_any_produces_no_line(self) -> None:
        for new_state in ("probing", "warming", "ready", "degraded"):
            line = self._transition("disabled", new_state)
            assert line is None, f"Expected None for disabled→{new_state}, got {line}"

    def test_probing_to_warming_produces_no_line(self) -> None:
        line = self._transition("probing", "warming")
        assert line is None

    def test_probing_to_ready_produces_no_line(self) -> None:
        line = self._transition("probing", "ready")
        assert line is None

    def test_first_event_produces_no_line(self) -> None:
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("I2P", "ready"))
        line = tracker.get_situation_line()
        assert line is None

    def test_situation_line_is_consumed_on_read(self) -> None:
        """get_situation_line() returns None on second call for same transition."""
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("I2P", "warming"))
        tracker.ingest(_make_event("I2P", "ready"))
        first = tracker.get_situation_line()
        second = tracker.get_situation_line()
        assert first is not None
        assert second is None

    def test_situation_line_includes_adapter_name(self) -> None:
        tracker = AdapterStatusTracker()
        tracker.ingest(_make_event("Ygg", "ready"))   # first — no line
        tracker.get_situation_line()
        tracker.ingest(_make_event("Ygg", "degraded"))
        line = tracker.get_situation_line()
        assert line is not None
        assert "Ygg" in line.message


class TestAdapterDisplayStateEnum:
    def test_unknown_value_maps_to_probing(self) -> None:
        state = AdapterDisplayState("bananas")
        assert state == AdapterDisplayState.PROBING

    def test_case_insensitive_via_lower(self) -> None:
        state = AdapterDisplayState("READY".lower())
        assert state == AdapterDisplayState.READY
