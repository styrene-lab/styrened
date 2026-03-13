"""COP Activity Summary — presentation-only widget for the Home COP panel.

This widget has no state.  It renders whatever ``CopSituationSnapshot`` was
last pushed via ``apply_snapshot()``.  All situation logic lives in
``CopSituationTracker`` (``styrened.tui.models.cop_situation``), which is
owned by ``DashboardScreen``.

Usage::

    # In DashboardScreen.on_daemon_event / _fetch_daemon_status:
    self._situation_tracker.ingest(event)          # or update_from_state(...)
    self.query_one(CopActivitySummary).apply_snapshot(
        self._situation_tracker.snapshot()
    )
"""
from __future__ import annotations

from typing import Any

from textual.widget import Widget

from styrened.tui.models.cop_situation import (
    CopSituationSnapshot,
    SituationPriority,
    transport_label,  # re-exported for callers that imported it from here
)
from styrened.tui.widgets.highlighted_panel import get_color_cascade

__all__ = ["CopActivitySummary", "transport_label"]

_PRIORITY_COLORS = {
    SituationPriority.ANOMALY: "bright",
    SituationPriority.ACTIONABLE: "bright",
    SituationPriority.FILE: "medium",
    SituationPriority.SECURITY: "medium",
    SituationPriority.HUB: "medium",
    SituationPriority.INFO: "medium",
}


class CopActivitySummary(Widget):
    """Presentation-only COP activity summary.

    Call ``apply_snapshot()`` to update.  The widget calls
    ``self.refresh()``; no internal state beyond the last snapshot.
    """

    DEFAULT_CSS = """
    CopActivitySummary {
        height: auto;
        min-height: 3;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._snapshot: CopSituationSnapshot | None = None

    def apply_snapshot(self, snapshot: CopSituationSnapshot) -> None:
        """Accept a new snapshot and re-render."""
        self._snapshot = snapshot
        self.refresh()

    def render(self) -> str:
        """Render priority-sorted situation lines as Rich markup."""
        cascade = get_color_cascade()

        if self._snapshot is None or self._snapshot.is_empty:
            return f"[{cascade.dim}]  no recent activity[/]"

        lines: list[str] = []
        for sit in self._snapshot.lines:
            if sit.dim:
                color = cascade.dim
            elif _PRIORITY_COLORS.get(sit.priority) == "bright":
                color = cascade.bright
            else:
                color = cascade.medium
            lines.append(f"[{color}]  {sit.icon} {sit.message}[/]")

        return "\n".join(lines)
