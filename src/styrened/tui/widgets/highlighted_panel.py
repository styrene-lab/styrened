"""Panel widget with highlighted corners for CRT aesthetic."""
from __future__ import annotations


from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from styrened.tui.themes.color_cascade import ColorCascade

# Module-level cascade for Rich markup colors
# Use get_color_cascade() to access, set_color_cascade() to change
_current_cascade: ColorCascade = ColorCascade.from_preset("styrene")


def get_color_cascade() -> ColorCascade:
    """Get the current color cascade for Rich markup.

    Returns:
        The active ColorCascade instance.
    """
    return _current_cascade


def set_color_cascade(cascade: ColorCascade) -> None:
    """Set the color cascade for Rich markup.

    Args:
        cascade: The ColorCascade to use for panel rendering.
    """
    global _current_cascade
    _current_cascade = cascade


class HighlightedPanel(Vertical):
    """A panel container with corner-highlighted borders.

    Renders box-drawing borders with brighter corner characters
    extending along edges for a CRT terminal aesthetic.

    Uses Textual theme CSS classes for colors, making it theme-aware.
    The corner highlights use the 'accent' color and borders use 'panel' color.
    """

    DEFAULT_CSS = """
    HighlightedPanel {
        background: $surface;
        height: auto;
        max-height: 100%;
        margin-bottom: 1;
        padding: 0;
    }

    HighlightedPanel > .hp-top-border {
        height: 1;
        width: 100%;
        background: transparent;
        color: $panel;
    }

    HighlightedPanel > .hp-bottom-border {
        height: 1;
        width: 100%;
        background: transparent;
        color: $panel;
    }

    HighlightedPanel > .hp-content {
        height: auto;
        width: 100%;
        padding: 0 1;
        border-left: solid $panel;
        border-right: solid $panel;
    }

    /* Corner highlight styling - uses accent for bright corners */
    HighlightedPanel > .hp-top-border .hp-corner {
        color: $accent;
    }

    HighlightedPanel > .hp-bottom-border .hp-corner {
        color: $accent;
    }
    """

    # Box-drawing characters
    HORIZONTAL = "─"
    TOP_LEFT = "┌"
    TOP_RIGHT = "┐"
    BOTTOM_LEFT = "└"
    BOTTOM_RIGHT = "┘"

    # Corner extension config
    CORNER_EXTEND = 0.1
    CORNER_MAX = 5

    def __init__(
        self,
        *children: Widget,
        title: str = "",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._panel_title = title
        self._child_widgets = children
        self._last_width = 0

    def compose(self) -> ComposeResult:
        yield Static("", classes="hp-top-border", id="hp-top")
        with Vertical(classes="hp-content"):
            yield from self._child_widgets
        yield Static("", classes="hp-bottom-border", id="hp-bottom")

    def on_mount(self) -> None:
        # call_after_refresh ensures layout is settled before we read size.width.
        # Calling _update_borders() directly here hits width=0 (widget not yet
        # laid out) and returns early, leaving borders unrendered.
        self.call_after_refresh(self._update_borders)

    def on_resize(self) -> None:
        new_width = self.size.width
        # Re-render when width changes. Also re-render when width is newly
        # non-zero (first valid layout after mount-time zero-size).
        if new_width != self._last_width or (new_width > 0 and self._last_width == 0):
            self._last_width = new_width
            self._update_borders()

    def _update_borders(self) -> None:
        """Render horizontal borders with corner highlights.

        Uses Rich markup with $accent for corners and $panel for borders,
        which will be resolved by Textual's theme system.
        """
        width = self.size.width
        if width < 4:
            return

        inner_width = width - 2
        corner_len = max(1, min(self.CORNER_MAX, int(inner_width * self.CORNER_EXTEND)))

        # Top border with optional title
        top = self._render_top_border(inner_width, corner_len)
        bottom = self._render_bottom_border(inner_width, corner_len)

        try:
            self.query_one("#hp-top", Static).update(top)
            self.query_one("#hp-bottom", Static).update(bottom)
        except Exception:
            pass  # Not yet composed

    def refresh_theme(self) -> None:
        """Refresh borders with current cascade colors.

        Call this after changing the color cascade via set_color_cascade().
        """
        self._update_borders()

    def _render_top_border(self, inner_width: int, corner_len: int) -> str:
        """Render top border with optional title.

        Uses cascade hex colors for Rich markup.
        - bright: corner highlights
        - dim: border lines
        - medium: title text
        """
        cascade = get_color_cascade()

        # Build corner sections (bright color for accent)
        left_corner = f"[{cascade.bright}]{self.TOP_LEFT}{self.HORIZONTAL * corner_len}[/]"
        right_corner = f"[{cascade.bright}]{self.HORIZONTAL * corner_len}{self.TOP_RIGHT}[/]"

        if self._panel_title:
            title_text = f" {self._panel_title} "
            middle_width = inner_width - (corner_len * 2) - len(title_text)
            if middle_width >= 0:
                left_mid = middle_width // 2
                right_mid = middle_width - left_mid
                # Title in medium, border lines in dim
                middle = (
                    f"[{cascade.dim}]{self.HORIZONTAL * left_mid}[/]"
                    f"[{cascade.medium}]{title_text}[/]"
                    f"[{cascade.dim}]{self.HORIZONTAL * right_mid}[/]"
                )
            else:
                # Title too long, truncate
                middle = f"[{cascade.medium}]{title_text[: inner_width - corner_len * 2]}[/]"
        else:
            middle_width = inner_width - (corner_len * 2)
            middle = f"[{cascade.dim}]{self.HORIZONTAL * middle_width}[/]"

        return f"{left_corner}{middle}{right_corner}"

    def _render_bottom_border(self, inner_width: int, corner_len: int) -> str:
        """Render bottom border.

        Uses cascade hex colors: bright for corners, dim for border lines.
        """
        cascade = get_color_cascade()

        left_corner = f"[{cascade.bright}]{self.BOTTOM_LEFT}{self.HORIZONTAL * corner_len}[/]"
        right_corner = f"[{cascade.bright}]{self.HORIZONTAL * corner_len}{self.BOTTOM_RIGHT}[/]"
        middle_width = inner_width - (corner_len * 2)
        middle = f"[{cascade.dim}]{self.HORIZONTAL * middle_width}[/]"
        return f"{left_corner}{middle}{right_corner}"
