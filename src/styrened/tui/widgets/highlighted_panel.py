"""StyrenePanel — bordered panel widget for the Styrene TUI.

Design
------
Inherits directly from ``Widget`` (NOT ``Vertical``) so Textual's
``Vertical { height: 1fr }`` DEFAULT_CSS never applies.  ``Widget`` already
uses ``VerticalLayout`` by default, so children stack top-to-bottom without
any extra CSS.

Sizing contract
---------------
* Default: ``height: auto`` — the panel shrinks to fit its content.
* To make a panel fill remaining space, add an explicit height override on
  the **widget's ID** in the TCSS::

      #my-panel { height: 1fr; }

Both composition patterns work correctly:

    # Positional children
    yield StyrenePanel(Label("a"), Button("b"), title="PANEL")

    # Context-manager children
    with StyrenePanel(title="PANEL", id="p"):
        yield Label("a")
        yield Button("b")

HighlightedPanel
----------------
``HighlightedPanel`` is kept as a public alias so every existing import
continues to work without changes.
"""
from __future__ import annotations

from textual.widget import Widget

from styrened.tui.themes.color_cascade import ColorCascade

# ---------------------------------------------------------------------------
# Module-level color cascade (used by widgets that render Rich hex markup)
# ---------------------------------------------------------------------------

_current_cascade: ColorCascade = ColorCascade.from_preset("styrene")


def get_color_cascade() -> ColorCascade:
    """Return the active ColorCascade for Rich markup rendering."""
    return _current_cascade


def set_color_cascade(cascade: ColorCascade) -> None:
    """Replace the active ColorCascade."""
    global _current_cascade
    _current_cascade = cascade


# ---------------------------------------------------------------------------
# StyrenePanel
# ---------------------------------------------------------------------------


class StyrenePanel(Widget):
    """Bordered panel with an optional title — the standard Styrene TUI panel.

    Uses ``$background`` for the panel fill so there is no color mismatch
    at the ``solid`` border corners.  The thin line-drawing border provides
    grouping without the heavy look of ``tall`` / ``wide`` borders.
    """

    DEFAULT_CSS = """
    StyrenePanel {
        height: auto;
        width: 1fr;
        background: transparent;
        margin-bottom: 1;
        padding: 0 1;
        border: round $border;
        border-title-color: $border;
        border-title-style: bold;
        border-title-align: left;
    }
    """

    def __init__(
        self,
        *children: Widget,
        title: str = "",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        if title:
            self.border_title = title

    def refresh_theme(self) -> None:
        """No-op — kept for call-site compatibility.

        Previously triggered manual Rich border re-render.  Textual's native
        border re-renders automatically on theme change.
        """


# ---------------------------------------------------------------------------
# Backward-compat alias — all existing imports of HighlightedPanel continue
# to work unchanged.
# ---------------------------------------------------------------------------

HighlightedPanel = StyrenePanel
