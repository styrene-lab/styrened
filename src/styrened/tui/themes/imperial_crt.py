"""Imperial CRT Theme - Green phosphor terminal aesthetic from Specularium."""
from __future__ import annotations

from textual.theme import Theme

# Color palette from Specularium's CSS
COLORS = {
    # Green phosphor shades
    "bright": "#39ff14",
    "medium": "#32cd32",
    "dim": "#228b22",
    "dark": "#1a5c1a",
    "darker": "#0d2d0d",
    "off_black": "#0a0a0a",
    # Status colors
    "info": "#74c0fc",
    "warning": "#ffa94d",
    "danger": "#ff6b6b",
    "success": "#69db7c",
}

IMPERIAL_CRT = Theme(
    name="imperial-crt",
    # Core phosphor green palette
    primary=COLORS["medium"],
    secondary=COLORS["dark"],
    accent=COLORS["bright"],
    # Text and backgrounds
    foreground=COLORS["medium"],
    background=COLORS["off_black"],
    surface=COLORS["darker"],
    panel=COLORS["dark"],
    # Status colors
    success=COLORS["success"],
    warning=COLORS["warning"],
    error=COLORS["danger"],
    dark=True,
    variables={
        # Borders
        "border": COLORS["dim"],
        "border-blurred": COLORS["dark"],
        # Cursor
        "block-cursor-background": COLORS["bright"],
        "block-cursor-foreground": COLORS["off_black"],
        # Footer
        "footer-key-foreground": COLORS["bright"],
        "footer-background": COLORS["darker"],
        # Input
        "input-selection-background": f"{COLORS['bright']} 25%",
        "input-cursor-background": COLORS["bright"],
        # Scrollbar
        "scrollbar": COLORS["dark"],
        "scrollbar-hover": COLORS["dim"],
        "scrollbar-active": COLORS["medium"],
    },
)
