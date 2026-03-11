"""Tweakcn registry theme → Textual Theme bridge.

Converts a tweakcn shared theme (https://tweakcn.com/themes/<id>) into a
Textual Theme that can be registered with App.register_theme().

Usage
-----
Quick fetch + apply::

    profile = TweakcnProfile.from_url("https://tweakcn.com/themes/cmly8fsie000204l8fqt54s1p")
    app.register_theme(profile.to_textual_theme("dark"))
    app.theme = profile.theme_name("dark")

Built-in profiles::

    profile = TweakcnProfile.from_registry_json("styrene", STYRENE_REGISTRY_JSON)
    theme = profile.to_textual_theme("dark")

Color format
------------
Tweakcn uses OKLCH (``oklch(L C H)``) with L in [0,1], C >= 0, H in degrees.
This module converts OKLCH → Oklab → linear sRGB → sRGB → hex without any
third-party colour libraries.
"""

from __future__ import annotations

import json
import math
import re
import urllib.request
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from textual.theme import Theme

# ---------------------------------------------------------------------------
# OKLCH → hex conversion (no external deps)
# ---------------------------------------------------------------------------

# Oklab → linear sRGB matrix (Bradford-adapted D65)
_M1 = [
    [1.2270138511, -0.5577999807,  0.2812561490],
    [-0.0405801784,  1.1122568696, -0.0716766787],
    [-0.0763812845, -0.4214819784,  1.5861632204],
]

# Oklab → LMS cube root intermediate
_M0_INV = [
    [1.0000000000,  0.3963377774,  0.2158037573],
    [1.0000000000, -0.1055613458, -0.0638541728],
    [1.0000000000, -0.0894841775, -1.2914855480],
]


def _oklch_to_hex(l: float, c: float, h_deg: float) -> str:
    """Convert OKLCH colour to #rrggbb hex string."""
    h = math.radians(h_deg)
    a = c * math.cos(h)
    b = c * math.sin(h)

    # Oklab → LMS (via cube-root intermediate)
    ll = l + 0.3963377774 * a + 0.2158037573 * b
    mm = l - 0.1055613458 * a - 0.0638541728 * b
    ss = l - 0.0894841775 * a - 1.2914855480 * b

    llin = ll ** 3
    mlin = mm ** 3
    slin = ss ** 3

    # LMS → linear sRGB
    r_lin = 4.0767416621 * llin - 3.3077115913 * mlin + 0.2309699292 * slin
    g_lin = -1.2684380046 * llin + 2.6097574011 * mlin - 0.3413193965 * slin
    b_lin = -0.0041960863 * llin - 0.7034186147 * mlin + 1.7076147010 * slin

    def _to_srgb(v: float) -> int:
        v = max(0.0, min(1.0, v))
        if v <= 0.0031308:
            v = 12.92 * v
        else:
            v = 1.055 * (v ** (1.0 / 2.4)) - 0.055
        return round(v * 255)

    return f"#{_to_srgb(r_lin):02x}{_to_srgb(g_lin):02x}{_to_srgb(b_lin):02x}"


_OKLCH_RE = re.compile(
    r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)",
    re.IGNORECASE,
)


def parse_color(value: str) -> str:
    """Convert a tweakcn CSS colour value to #rrggbb hex.

    Handles:
    - ``oklch(L C H)``  → converted to hex
    - ``#rrggbb`` / ``#rgb`` → returned as-is (normalised to 6-digit lowercase)
    - Anything else → returned unchanged (Textual handles named colours)
    """
    value = value.strip()
    m = _OKLCH_RE.match(value)
    if m:
        return _oklch_to_hex(float(m.group(1)), float(m.group(2)), float(m.group(3)))
    if value.startswith("#"):
        v = value[1:]
        if len(v) == 3:
            v = "".join(c * 2 for c in v)
        return f"#{v.lower()}"
    return value


# ---------------------------------------------------------------------------
# Tweakcn registry schema
# ---------------------------------------------------------------------------

#: The CSS variable names that are colours (not font strings, radii, etc.)
_COLOUR_KEYS = frozenset({
    "background", "foreground",
    "card", "card-foreground",
    "popover", "popover-foreground",
    "primary", "primary-foreground",
    "secondary", "secondary-foreground",
    "muted", "muted-foreground",
    "accent", "accent-foreground",
    "destructive", "destructive-foreground",
    "border", "input", "ring",
    "chart-1", "chart-2", "chart-3", "chart-4", "chart-5",
    "sidebar", "sidebar-foreground",
    "sidebar-primary", "sidebar-primary-foreground",
    "sidebar-accent", "sidebar-accent-foreground",
    "sidebar-border", "sidebar-ring",
    "shadow-color",
})


@dataclass
class TweakcnProfile:
    """A tweakcn shared theme, ready to produce Textual Themes.

    Attributes
    ----------
    name:
        Display name (from registry JSON ``name`` field or supplied by caller).
    dark:
        ``cssVars.dark`` dict from the tweakcn registry JSON. Values are raw
        CSS strings (OKLCH, hex, etc.); ``parse_color`` normalises them on
        first call.
    light:
        ``cssVars.light`` dict.  May be empty if the theme is dark-only.
    meta:
        ``cssVars.theme`` dict — non-colour settings (fonts, radius).
    source_url:
        Original tweakcn URL (for display / config persistence).
    """

    name: str
    dark: dict[str, str]
    light: dict[str, str]
    meta: dict[str, str] = field(default_factory=dict)
    source_url: str = ""

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_registry_json(
        cls,
        data: dict,
        *,
        name: str | None = None,
        source_url: str = "",
    ) -> "TweakcnProfile":
        """Build a profile from a parsed tweakcn registry JSON dict."""
        css_vars = data.get("cssVars", {})
        return cls(
            name=name or data.get("name", "custom"),
            dark=dict(css_vars.get("dark", {})),
            light=dict(css_vars.get("light", {})),
            meta=dict(css_vars.get("theme", {})),
            source_url=source_url,
        )

    @classmethod
    def from_url(cls, url: str, *, timeout: int = 10) -> "TweakcnProfile":
        """Fetch a tweakcn theme by URL and parse it.

        Accepts either the human-readable URL
        (``https://tweakcn.com/themes/<id>``) or the registry URL
        (``https://tweakcn.com/r/themes/<id>``).  Raises
        ``urllib.error.URLError`` on network failure and ``ValueError`` if
        the URL doesn't look like a tweakcn theme.
        """
        registry_url = _to_registry_url(url)
        req = urllib.request.Request(
            registry_url,
            headers={"Accept": "application/json", "User-Agent": "styrened-tui/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        return cls.from_registry_json(data, source_url=url)

    # ------------------------------------------------------------------
    # Textual theme conversion
    # ------------------------------------------------------------------

    def theme_name(self, mode: Literal["dark", "light"] = "dark") -> str:
        """Return the Textual theme registration key for this profile.

        Returns just ``self.name`` — mode suffix is omitted since the TUI is
        dark-only and a single registration name per profile is cleaner.
        """
        return self.name

    def to_textual_theme(
        self, mode: Literal["dark", "light"] = "dark"
    ) -> "Theme":
        """Convert this profile to a Textual ``Theme``.

        Parameters
        ----------
        mode:
            Which set of ``cssVars`` to use.  Falls back to the other mode if
            the requested set is empty.
        """
        from textual.theme import Theme

        tokens = self.dark if mode == "dark" else self.light
        if not tokens:
            # Fall back to the other mode if one side is absent
            tokens = self.light if mode == "dark" else self.dark

        def c(key: str, fallback: str = "") -> str:
            raw = tokens.get(key, fallback)
            return parse_color(raw) if raw else fallback

        primary = c("primary")
        background = c("background")
        foreground = c("foreground")
        surface = c("card", c("muted"))
        panel = c("popover", c("card"))
        secondary = c("secondary")
        accent = c("accent", primary)
        destructive = c("destructive")
        muted_fg = c("muted-foreground")
        border = c("border")
        border_input = c("input", border)
        ring = c("ring", primary)
        muted_bg = c("muted")
        card_fg = c("card-foreground", foreground)
        primary_fg = c("primary-foreground", background)

        return Theme(
            name=self.theme_name(mode),
            primary=primary,
            secondary=secondary,
            accent=accent,
            foreground=foreground,
            background=background,
            surface=surface,
            panel=panel,
            success=primary,          # tweakcn has no success token; use primary
            warning=destructive,
            error=destructive,
            dark=(mode == "dark"),
            variables={
                "border": border,
                "border-blurred": border_input,
                "block-cursor-background": primary,
                "block-cursor-foreground": primary_fg,
                "footer-key-foreground": primary,
                "footer-background": surface,
                "input-selection-background": f"{primary} 25%",
                "input-cursor-background": ring,
                "scrollbar": muted_bg,
                "scrollbar-hover": secondary,
                "scrollbar-active": border,
                "text-muted": muted_fg,
                # Expose raw tokens for TCSS custom properties
                "card": surface,
                "card-foreground": card_fg,
                "ring": ring,
                "muted": muted_bg,
                "muted-foreground": muted_fg,
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_THEME_ID_RE = re.compile(r"tweakcn\.com(?:/r)?/themes/([a-z0-9]+)", re.IGNORECASE)


def _to_registry_url(url: str) -> str:
    """Normalise any tweakcn URL to the registry JSON endpoint."""
    m = _THEME_ID_RE.search(url)
    if not m:
        raise ValueError(
            f"Not a recognised tweakcn theme URL: {url!r}\n"
            "Expected: https://tweakcn.com/themes/<id>"
        )
    theme_id = m.group(1)
    return f"https://tweakcn.com/r/themes/{theme_id}"


def extract_theme_id(url: str) -> str | None:
    """Return the theme ID from a tweakcn URL, or None if not recognised."""
    m = _THEME_ID_RE.search(url)
    return m.group(1) if m else None
