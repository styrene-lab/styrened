"""Theme system for Styrene TUI.

Provides the ColorCascade system for deriving all UI colors from a single
"phosphex" root color, plus semantic visual differentiation utilities.
"""

from .color_cascade import (
    FORGE_WORLD_ORDER,
    FORGE_WORLD_PRESETS,
    IMPERIAL_CRT_CASCADE,
    LUCIUS_CASCADE,
    MARS_CASCADE,
    METALICA_CASCADE,
    RYZA_CASCADE,
    STYGIES_CASCADE,
    ColorCascade,
    generate_all_themes,
    get_preset,
    list_presets,
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

__all__ = [
    "FORGE_WORLD_ORDER",
    "FORGE_WORLD_PRESETS",
    "IMPERIAL_CRT_CASCADE",
    "LUCIUS_CASCADE",
    "MARS_CASCADE",
    "METALICA_CASCADE",
    "RYZA_CASCADE",
    "STYGIES_CASCADE",
    "ActionSeverity",
    "ColorCascade",
    "SemanticSymbols",
    "StatusState",
    "format_button_label",
    "format_status",
    "generate_all_themes",
    "get_button_class",
    "get_preset",
    "get_status_class",
    "list_presets",
]
