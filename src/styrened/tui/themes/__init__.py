"""Theme system for Styrene TUI.

Provides the ColorCascade system for deriving UI colors from a root color,
the Styrene brand theme, and semantic visual differentiation utilities.
"""
from __future__ import annotations


from .color_cascade import (
    ColorCascade,
)
from .semantic import (
    ActionSeverity,
    SemanticSymbols,
    StatusState,
    format_button_label,
    format_status,
    get_button_class,
    get_status_class,
)
from .styrene_brand import (
    STYRENE_DARK,
    STYRENE_LIGHT,
    STYRENE_THEME_KEY,
    create_styrene_cascade,
    create_styrene_theme,
)

__all__ = [
    "STYRENE_DARK",
    "STYRENE_LIGHT",
    "STYRENE_THEME_KEY",
    "ActionSeverity",
    "ColorCascade",
    "SemanticSymbols",
    "StatusState",
    "create_styrene_cascade",
    "create_styrene_theme",
    "format_button_label",
    "format_status",
    "get_button_class",
    "get_status_class",
]
