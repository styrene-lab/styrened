"""Adapter Status Bar widget — compact per-adapter SCADA-style indicator.

Renders a single-line pipe-delimited bar showing the state of each
registered adapter.  Visual language:

  DISABLED  — dim dashed placeholder  (---)
  PROBING   — amber circle            (◌ amber)
  WARMING   — amber circle            (◌ amber)
  READY     — green dot               (● green)
  DEGRADED  — red X                   (✕ red)

Usage::

    bar = AdapterStatusBar()
    bar.apply_snapshot(tracker.snapshot())
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from styrened.tui.models.adapter_status import AdapterDisplayState, AdapterStatusSnapshot

# ---------------------------------------------------------------------------
# Colour constants (Rich colour names)
# ---------------------------------------------------------------------------

_COLOR_DIM = "dim"
_COLOR_GREEN = "green"
_COLOR_AMBER = "dark_orange"
_COLOR_RED = "red"

# Per-state icon and colour
_STATE_ICON: dict[AdapterDisplayState, tuple[str, str]] = {
    AdapterDisplayState.DISABLED: ("---", _COLOR_DIM),
    AdapterDisplayState.PROBING:  ("◌", _COLOR_AMBER),
    AdapterDisplayState.WARMING:  ("◌", _COLOR_AMBER),
    AdapterDisplayState.READY:    ("●", _COLOR_GREEN),
    AdapterDisplayState.DEGRADED: ("✕", _COLOR_RED),
}


class AdapterStatusBar(Static):
    """Compact horizontal bar showing per-adapter states.

    Stateless: all display state comes from the most recently applied
    ``AdapterStatusSnapshot``.  Call ``apply_snapshot()`` then
    ``refresh()`` (or rely on the caller to call ``update()``) to
    trigger a re-render.
    """

    DEFAULT_CSS = """
    AdapterStatusBar {
        height: auto;
        width: 1fr;
    }
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._snapshot: AdapterStatusSnapshot | None = None

    # ---- Public API --------------------------------------------------------

    def apply_snapshot(self, snapshot: AdapterStatusSnapshot) -> None:
        """Accept a new snapshot and trigger a re-render."""
        self._snapshot = snapshot
        self.refresh()

    # ---- Rendering ---------------------------------------------------------

    def render(self) -> Text:
        """Return a Rich Text object representing the current snapshot."""
        if self._snapshot is None or self._snapshot.is_empty:
            return Text("ADAPTERS ─ no adapters registered", style=_COLOR_DIM)

        result = Text()
        result.append("ADAPTERS ", style=_COLOR_DIM)

        for i, entry in enumerate(self._snapshot.adapters):
            if i > 0:
                result.append(" │ ", style=_COLOR_DIM)

            icon, colour = _STATE_ICON.get(
                entry.state,
                ("◌", _COLOR_AMBER),
            )

            if entry.state == AdapterDisplayState.DISABLED:
                # Dim dashed — name and placeholder rendered dim
                result.append(f"{entry.name} ", style=_COLOR_DIM)
                result.append(icon, style=_COLOR_DIM)
            else:
                result.append(f"{entry.name} ", style=_COLOR_DIM)
                result.append(icon, style=colour)

            if entry.detail:
                result.append(f" {entry.detail}", style=_COLOR_DIM)

        return result
