"""Styrene brand theme definition.

The brand theme uses an intentional teal/cyan palette designed on tweakcn.com.
Unlike forge world presets (algorithmically derived from a single phosphex color),
the brand theme uses explicit hand-tuned values that can't be produced by
ColorCascade's single-phosphex algorithm.

Dark mode is implemented for the TUI. Light mode values are preserved as
reference for future web UI and documentation work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.theme import Theme

    from styrened.tui.themes.color_cascade import ColorCascade

STYRENE_THEME_KEY = "styrene"

# =============================================================================
# Brand Colors — Dark Mode (TUI implementation)
# =============================================================================

STYRENE_DARK: dict[str, str] = {
    "primary": "#00f0d3",
    "foreground": "#cbf4ed",
    "background": "#16171d",
    "card": "#202b30",
    "secondary": "#304345",
    "muted": "#1f2b30",
    "accent": "#374151",
    "destructive": "#e98100",
    "border": "#4a6767",
    "input": "#375656",
    "ring": "#00f0d3",
    "chart1": "#00f0e3",
    "chart2": "#00c4b8",
    "chart3": "#00968e",
    "chart4": "#2a5c5c",
    "chart5": "#1c3a3a",
}

# =============================================================================
# Brand Colors — Light Mode (reference only, not used in TUI)
# =============================================================================

STYRENE_LIGHT: dict[str, str] = {
    "primary": "#009e8b",
    "foreground": "#0a1a16",
    "background": "#f0faf7",
    "card": "#ffffff",
    "secondary": "#e0efed",
    "muted": "#e0efed",
    "accent": "#e0efed",
    "destructive": "#e98100",
    "border": "#b0d0cc",
    "input": "#b0d0cc",
    "ring": "#009e8b",
}

# =============================================================================
# Typography (web/docs reference, not used in TUI)
# =============================================================================

BRAND_TYPOGRAPHY: dict[str, str] = {
    "sans": "Tomorrow",
    "serif": "BioRhyme",
    "mono": "JetBrains Mono",
}


def create_styrene_cascade() -> ColorCascade:
    """Create a ColorCascade with explicit brand values.

    Bypasses the algorithmic palette derivation by constructing the cascade
    via __new__ and setting all attributes directly from the brand spec.
    """
    from styrened.tui.themes.color_cascade import ColorCascade

    cascade = ColorCascade.__new__(ColorCascade)
    cascade.phosphex = STYRENE_DARK["primary"]
    cascade.preset_name = "Styrene Dark"

    # Phosphor shades — mapped from brand tokens
    cascade.bright = STYRENE_DARK["primary"]  # #00f0d3
    cascade.medium = STYRENE_DARK["foreground"]  # #cbf4ed
    cascade.dim = STYRENE_DARK["secondary"]  # #304345
    cascade.dark = STYRENE_DARK["muted"]  # #1f2b30

    # Backgrounds
    cascade.bg_screen = STYRENE_DARK["background"]  # #16171d
    cascade.bg_panel = STYRENE_DARK["card"]  # #202b30
    cascade.bg_panel_elevated = STYRENE_DARK["muted"]  # #1f2b30
    cascade.bg_hover = STYRENE_DARK["accent"]  # #374151

    # Borders
    cascade.border_dim = STYRENE_DARK["input"]  # #375656
    cascade.border_medium = STYRENE_DARK["border"]  # #4a6767
    cascade.border_bright = STYRENE_DARK["secondary"]  # #304345
    cascade.corner_highlight = STYRENE_DARK["ring"]  # #00f0d3

    # Status colors
    cascade.status_online = STYRENE_DARK["primary"]  # #00f0d3
    cascade.status_offline = STYRENE_DARK["muted"]  # #1f2b30
    cascade.status_pending = STYRENE_DARK["foreground"]  # #cbf4ed
    cascade.status_scanning = STYRENE_DARK["secondary"]  # #304345
    cascade.status_info = STYRENE_DARK["foreground"]  # #cbf4ed

    # Semantic colors
    cascade.color_success = STYRENE_DARK["primary"]  # #00f0d3
    cascade.color_warning = STYRENE_DARK["destructive"]  # #e98100
    cascade.color_danger = STYRENE_DARK["destructive"]  # #e98100
    cascade.color_info = STYRENE_DARK["foreground"]  # #cbf4ed

    return cascade


def create_styrene_theme() -> Theme:
    """Create a Textual Theme from the brand cascade."""
    cascade = create_styrene_cascade()
    return cascade.to_textual_theme(name=STYRENE_THEME_KEY)
