"""Styrene brand theme definition.

Complete dark mode theme from tweakcn.com (cmly8fsie000204l8fqt54s1p).
Hand-tuned teal/cyan palette — these values can't be derived from
ColorCascade's single-phosphex algorithm.

Light mode values are preserved as reference for future web UI work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.theme import Theme

    from styrened.tui.themes.color_cascade import ColorCascade

STYRENE_THEME_KEY = "styrene"

# =============================================================================
# Brand Colors — Dark Mode (TUI implementation)
# Source: https://tweakcn.com/themes/cmly8fsie000204l8fqt54s1p
# =============================================================================

STYRENE_DARK: dict[str, str] = {
    # Core surfaces
    "primary": "#00f0d3",
    "primary_foreground": "#0b2821",
    "foreground": "#cbf4ed",
    "background": "#16171d",
    "card": "#202b30",
    "card_foreground": "#cbf4ed",
    "popover": "#161a1d",
    "popover_foreground": "#00f0d3",
    # Secondary surfaces
    "secondary": "#304345",
    "secondary_foreground": "#d1d5db",
    "muted": "#1f2b30",
    "muted_foreground": "#9ca3af",
    "accent": "#374151",
    "accent_foreground": "#d1d5db",
    # Semantic
    "destructive": "#e98100",
    "destructive_foreground": "#1d2725",
    # Borders and inputs
    "border": "#4a6767",
    "input": "#375656",
    "ring": "#00f0d3",
    # Chart gradient (teal → dark)
    "chart1": "#00f0e3",
    "chart2": "#5cd1be",
    "chart3": "#51958c",
    "chart4": "#42636a",
    "chart5": "#1c3a3a",
    # Sidebar
    "sidebar_background": "#1f2a2f",
    "sidebar_foreground": "#d0efe4",
    "sidebar_primary": "#afede4",
    "sidebar_primary_foreground": "#1e2827",
    "sidebar_accent": "#303d3e",
    "sidebar_border": "#4c5f61",
    "sidebar_ring": "#a9f0ea",
    # Effects
    "shadow_color": "#b8fff9",
}

# =============================================================================
# Brand Colors — Light Mode (reference only, not used in TUI)
# =============================================================================

STYRENE_LIGHT: dict[str, str] = {
    "primary": "#009e8b",
    "primary_foreground": "#e8f5f2",
    "foreground": "#0a1a16",
    "background": "#f0faf7",
    "card": "#ffffff",
    "card_foreground": "#0a1a16",
    "popover": "#ffffff",
    "popover_foreground": "#0a1a16",
    "secondary": "#e0efed",
    "secondary_foreground": "#374151",
    "muted": "#e0efed",
    "muted_foreground": "#6b7280",
    "accent": "#e0efed",
    "accent_foreground": "#374151",
    "destructive": "#e98100",
    "destructive_foreground": "#ffffff",
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

    The cascade brightness levels map to brand tokens:
      bright  -> primary (#00f0d3)  — accent highlights, corners
      medium  -> foreground (#cbf4ed) — readable text, titles
      dim     -> border (#4a6767) — border lines, panel edges
      dark    -> secondary (#304345) — very muted, scrollbar
    """
    from styrened.tui.themes.color_cascade import ColorCascade

    cascade = ColorCascade.__new__(ColorCascade)
    cascade.phosphex = STYRENE_DARK["primary"]
    cascade.preset_name = "Styrene Dark"

    # Phosphor shades — mapped from brand tokens
    cascade.bright = STYRENE_DARK["primary"]  # #00f0d3
    cascade.medium = STYRENE_DARK["foreground"]  # #cbf4ed
    cascade.dim = STYRENE_DARK["border"]  # #4a6767
    cascade.dark = STYRENE_DARK["secondary"]  # #304345

    # Backgrounds
    cascade.bg_screen = STYRENE_DARK["background"]  # #16171d
    cascade.bg_panel = STYRENE_DARK["card"]  # #202b30
    cascade.bg_panel_elevated = STYRENE_DARK["muted"]  # #1f2b30
    cascade.bg_hover = STYRENE_DARK["accent"]  # #374151

    # Borders
    cascade.border_dim = STYRENE_DARK["input"]  # #375656
    cascade.border_medium = STYRENE_DARK["border"]  # #4a6767
    cascade.border_bright = STYRENE_DARK["foreground"]  # #cbf4ed
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
    """Create a Textual Theme directly from brand tokens.

    Constructs the Theme with explicit brand mappings rather than going
    through the cascade's generic to_textual_theme() mapper, which assumes
    single-phosphex brightness levels.
    """
    from textual.theme import Theme

    return Theme(
        name=STYRENE_THEME_KEY,
        primary=STYRENE_DARK["primary"],  # #00f0d3
        secondary=STYRENE_DARK["secondary"],  # #304345
        accent=STYRENE_DARK["primary"],  # #00f0d3 (ring/focus)
        foreground=STYRENE_DARK["foreground"],  # #cbf4ed
        background=STYRENE_DARK["background"],  # #16171d
        surface=STYRENE_DARK["card"],  # #202b30
        panel=STYRENE_DARK["border"],  # #4a6767
        success=STYRENE_DARK["primary"],  # #00f0d3
        warning=STYRENE_DARK["destructive"],  # #e98100
        error=STYRENE_DARK["destructive"],  # #e98100
        dark=True,
        variables={
            "border": STYRENE_DARK["border"],
            "border-blurred": STYRENE_DARK["input"],
            "block-cursor-background": STYRENE_DARK["primary"],
            "block-cursor-foreground": STYRENE_DARK["background"],
            "footer-key-foreground": STYRENE_DARK["primary"],
            "footer-background": STYRENE_DARK["card"],
            "input-selection-background": f"{STYRENE_DARK['primary']} 25%",
            "input-cursor-background": STYRENE_DARK["primary"],
            "scrollbar": STYRENE_DARK["muted"],
            "scrollbar-hover": STYRENE_DARK["secondary"],
            "scrollbar-active": STYRENE_DARK["border"],
            "text-muted": STYRENE_DARK["muted_foreground"],
        },
    )
