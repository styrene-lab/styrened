"""Styrene brand theme definition.

Complete dark/light theme from tweakcn.com (cmly8fsie000204l8fqt54s1p).
Hand-tuned teal/cyan palette — these values can't be derived from
ColorCascade's single-phosphex algorithm.

``create_styrene_theme()`` is now a thin wrapper over
:class:`~styrened.tui.themes.tweakcn.TweakcnProfile` — the canonical
conversion path for all tweakcn-sourced themes.

The ``STYRENE_DARK`` / ``STYRENE_LIGHT`` dicts are kept for backwards
compatibility and for use by ``create_styrene_cascade()``.
"""
from __future__ import annotations



from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.theme import Theme

    from styrened.tui.themes.color_cascade import ColorCascade

STYRENE_THEME_KEY = "styrene"
STYRENE_TWEAKCN_URL = "https://tweakcn.com/themes/cmly8fsie000204l8fqt54s1p"

# ---------------------------------------------------------------------------
# Embedded registry snapshot (cssVars from tweakcn registry JSON).
# Kept in-process so that create_styrene_theme() never needs a network call.
# Refresh by fetching: https://tweakcn.com/r/themes/cmly8fsie000204l8fqt54s1p
# ---------------------------------------------------------------------------

_STYRENE_REGISTRY: dict = {
    "name": "StyreneDark",
    "cssVars": {
        "theme": {
            "font-sans": "Tomorrow, ui-sans-serif, sans-serif, system-ui",
            "font-mono": "JetBrains Mono, monospace",
            "font-serif": "BioRhyme, ui-serif, serif",
            "radius": "0.15rem",
        },
        "dark": {
            "background":            "oklch(0.2063 0.0120 277.8347)",
            "foreground":            "oklch(0.9363 0.0433 183.9088)",
            "card":                  "oklch(0.2810 0.0177 227.3784)",
            "card-foreground":       "oklch(0.9363 0.0433 183.9088)",
            "popover":               "oklch(0.2149 0.0085 240.3030)",
            "popover-foreground":    "oklch(0.8556 0.1555 179.7932)",
            "primary":               "oklch(0.8556 0.1555 179.7932)",
            "primary-foreground":    "oklch(0.2523 0.0373 174.7008)",
            "secondary":             "oklch(0.3675 0.0243 204.2418)",
            "secondary-foreground":  "oklch(0.8717 0.0093 258.3382)",
            "muted":                 "oklch(0.2801 0.0188 225.3491)",
            "muted-foreground":      "oklch(0.7137 0.0192 261.3246)",
            "accent":                "oklch(0.3729 0.0306 259.7328)",
            "accent-foreground":     "oklch(0.8717 0.0093 258.3382)",
            "destructive":           "oklch(0.7036 0.1665 59.0920)",
            "destructive-foreground":"oklch(0.2624 0.0145 181.5879)",
            "border":                "oklch(0.4911 0.0340 196.1004)",
            "input":                 "oklch(0.4291 0.0366 195.8739)",
            "ring":                  "oklch(0.8556 0.1555 179.7932)",
            "chart-1":               "oklch(0.8605 0.1497 187.8375)",
            "chart-2":               "oklch(0.7883 0.1096 181.0760)",
            "chart-3":               "oklch(0.6223 0.0709 184.5682)",
            "chart-4":               "oklch(0.4771 0.0398 212.3551)",
            "chart-5":               "oklch(0.3253 0.0359 195.5305)",
            "sidebar":               "oklch(0.2769 0.0178 227.4018)",
            "sidebar-foreground":    "oklch(0.9267 0.0356 172.1170)",
            "sidebar-primary":       "oklch(0.9018 0.0637 185.0301)",
            "sidebar-primary-foreground": "oklch(0.2670 0.0141 188.8393)",
            "sidebar-accent":        "oklch(0.3488 0.0171 202.1737)",
            "sidebar-accent-foreground":  "oklch(0.8630 0.0329 198.9516)",
            "sidebar-border":        "oklch(0.4705 0.0233 204.2805)",
            "sidebar-ring":          "oklch(0.9067 0.0710 189.3757)",
        },
        "light": {
            "background":            "oklch(0.9842 0.0034 247.8575)",
            "foreground":            "oklch(0.3013 0.0240 238.8090)",
            "card":                  "oklch(1.0000 0 0)",
            "card-foreground":       "oklch(0.3193 0.0228 209.5983)",
            "popover":               "oklch(1.0000 0 0)",
            "popover-foreground":    "oklch(0.3249 0.0245 200.1420)",
            "primary":               "oklch(0.5200 0.0490 147.7951)",
            "primary-foreground":    "oklch(1.0000 0 0)",
            "secondary":             "oklch(0.9276 0.0058 264.5313)",
            "secondary-foreground":  "oklch(0.4070 0.0296 173.1820)",
            "muted":                 "oklch(0.9670 0.0029 264.5419)",
            "muted-foreground":      "oklch(0.3025 0.0164 156.1138)",
            "accent":                "oklch(0.9181 0.0477 145.1734)",
            "accent-foreground":     "oklch(0.4091 0.0226 200.5214)",
            "destructive":           "oklch(0.5664 0.2031 32.6994)",
            "destructive-foreground":"oklch(1.0000 0 0)",
            "border":                "oklch(0.8717 0.0093 258.3382)",
            "input":                 "oklch(0.9163 0.0250 143.4909)",
            "ring":                  "oklch(0.7099 0.0954 147.5011)",
            "sidebar":               "oklch(0.9670 0.0029 264.5419)",
            "sidebar-foreground":    "oklch(0.3277 0.0256 195.9750)",
            "sidebar-primary":       "oklch(0.5200 0.0490 147.7951)",
            "sidebar-primary-foreground": "oklch(1.0000 0 0)",
            "sidebar-accent":        "oklch(0.8971 0.0470 146.1388)",
            "sidebar-accent-foreground":  "oklch(0.4109 0.0239 188.3160)",
            "sidebar-border":        "oklch(0.8657 0.0288 199.3627)",
            "sidebar-ring":          "oklch(0.8758 0.0571 147.4218)",
        },
    },
}


def get_styrene_profile() -> "TweakcnProfile":
    """Return the built-in Styrene brand TweakcnProfile (no network call)."""
    from styrened.tui.themes.tweakcn import TweakcnProfile

    return TweakcnProfile.from_registry_json(
        _STYRENE_REGISTRY,
        name="styrene",
        source_url=STYRENE_TWEAKCN_URL,
    )

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
    # Semantic colors derived via OKLCH hue targeting from destructive/primary.
    # See tweakcn.py _derive_semantic_color() for the derivation logic.
    from styrened.tui.themes.tweakcn import _derive_semantic_color, _HUE_ERROR, _HUE_WARNING, _HUE_SUCCESS
    _destr_raw = "oklch(0.7036 0.1665 59.0920)"  # destructive
    _prim_raw = "oklch(0.8556 0.1555 179.7932)"   # primary
    cascade.color_success = _derive_semantic_color(_prim_raw, _HUE_SUCCESS, chroma_scale=0.7)
    cascade.color_warning = _derive_semantic_color(_destr_raw, _HUE_WARNING, chroma_scale=0.85)
    cascade.color_danger = _derive_semantic_color(_destr_raw, _HUE_ERROR)
    cascade.color_info = STYRENE_DARK["foreground"]  # #cbf4ed

    return cascade


def create_styrene_theme() -> "Theme":
    """Create the Styrene Textual Theme from the embedded registry snapshot.

    Delegates to :class:`~styrened.tui.themes.tweakcn.TweakcnProfile`
    so the same conversion path is used for built-in and custom themes.
    """
    return get_styrene_profile().to_textual_theme("dark")
