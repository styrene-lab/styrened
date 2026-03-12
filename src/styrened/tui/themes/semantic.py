"""Semantic visual differentiation for theme-independent UX.

Provides symbols, patterns, and formatting for semantic states (success, warning,
danger, status) that remain distinguishable regardless of the active phosphex theme.

The visual differentiation uses three layers:
1. Symbol: Geometric Unicode shapes (●○◐◓)
2. Text style: CSS text-style (bold, italic, underline, reverse, strike)
3. Shade pattern: Block element fill characters (▓▒░)
"""
from __future__ import annotations


from enum import Enum
from typing import NamedTuple


class SemanticSymbols:
    """Unicode symbols for semantic state indication.

    Geometric shapes provide instant visual recognition independent of color.
    """

    # Status indicators (filled/hollow/partial circles)
    ONLINE = "●"  # U+25CF Filled circle - active/present
    OFFLINE = "○"  # U+25CB Hollow circle - inactive/absent
    PENDING = "◐"  # U+25D0 Half circle - transitioning
    SCANNING = "◓"  # U+25D3 Quarter circle - processing

    # Action indicators (for buttons)
    SUCCESS = "▓"  # U+2593 Dark shade (75%) - confirmed/approved
    WARNING = "▒"  # U+2592 Medium shade (50%) - caution
    DANGER = "░"  # U+2591 Light shade (25%) - alarming/destructive
    INFO = "□"  # U+25A1 Hollow square - informational

    # Mechanicum-style binary indicators
    APPROVED = "⊕"  # Circled plus - blessed by the Omnissiah
    REJECTED = "⊗"  # Circled times - corrupted/denied
    PROCESSING = "⊙"  # Circled dot - machine spirit active
    IDLE = "⊚"  # Circled ring - waiting

    # Directional indicators
    UP = "▲"  # Triangle up - increase/success
    DOWN = "▼"  # Triangle down - decrease/failure
    DIAMOND = "◆"  # Diamond - warning/important


class StatusState(Enum):
    """Connection/device status states."""

    ONLINE = "online"
    OFFLINE = "offline"
    PENDING = "pending"
    SCANNING = "scanning"
    INFO = "info"


class ActionSeverity(Enum):
    """Action/button severity levels."""

    SUCCESS = "success"
    WARNING = "warning"
    DANGER = "danger"
    INFO = "info"
    PRIMARY = "primary"
    DEFAULT = "default"


class StatusFormat(NamedTuple):
    """Formatting specification for a status state."""

    symbol: str
    css_class: str
    description: str


class ButtonFormat(NamedTuple):
    """Formatting specification for a button severity."""

    shade_char: str
    css_class: str
    description: str


# Status formatting lookup
STATUS_FORMATS: dict[StatusState, StatusFormat] = {
    StatusState.ONLINE: StatusFormat(
        SemanticSymbols.ONLINE, "status-online", "Active/connected"
    ),
    StatusState.OFFLINE: StatusFormat(
        SemanticSymbols.OFFLINE, "status-offline", "Inactive/disconnected"
    ),
    StatusState.PENDING: StatusFormat(
        SemanticSymbols.PENDING, "status-pending", "Transitioning/waiting"
    ),
    StatusState.SCANNING: StatusFormat(
        SemanticSymbols.SCANNING, "status-scanning", "Processing/discovering"
    ),
    StatusState.INFO: StatusFormat(
        SemanticSymbols.INFO, "status-info", "Informational"
    ),
}

# Button formatting lookup
BUTTON_FORMATS: dict[ActionSeverity, ButtonFormat] = {
    ActionSeverity.SUCCESS: ButtonFormat(
        SemanticSymbols.SUCCESS, "-success", "Confirmation/approval"
    ),
    ActionSeverity.WARNING: ButtonFormat(
        SemanticSymbols.WARNING, "-warning", "Caution/attention needed"
    ),
    ActionSeverity.DANGER: ButtonFormat(
        SemanticSymbols.DANGER, "-danger", "Destructive/irreversible"
    ),
    ActionSeverity.INFO: ButtonFormat(
        SemanticSymbols.INFO, "-info", "Informational action"
    ),
    ActionSeverity.PRIMARY: ButtonFormat("", "-primary", "Primary action"),
    ActionSeverity.DEFAULT: ButtonFormat("", "", "Standard action"),
}


def format_status(state: StatusState | str, label: str) -> str:
    """Format a status label with semantic symbol prefix.

    Args:
        state: Status state (enum or string like "online")
        label: The status text to display

    Returns:
        Formatted string with symbol prefix, e.g. "● ONLINE"

    Example:
        >>> format_status("online", "CONNECTED")
        '● CONNECTED'
        >>> format_status(StatusState.OFFLINE, "DISCONNECTED")
        '○ DISCONNECTED'
    """
    if isinstance(state, str):
        try:
            state = StatusState(state.lower())
        except ValueError:
            # Unknown state, return label without symbol
            return label

    fmt = STATUS_FORMATS.get(state)
    if fmt:
        return f"{fmt.symbol} {label}"
    return label


def format_button_label(severity: ActionSeverity | str, label: str) -> str:
    """Format a button label with semantic shade pattern.

    Adds shade characters around the label for visual texture differentiation.
    Only applies to success/warning/danger buttons.

    Args:
        severity: Action severity (enum or string like "danger")
        label: The button text

    Returns:
        Formatted string with shade pattern, e.g. "░ Delete ░"

    Example:
        >>> format_button_label("danger", "Delete")
        '░ Delete ░'
        >>> format_button_label(ActionSeverity.SUCCESS, "Confirm")
        '▓ Confirm ▓'
        >>> format_button_label("primary", "Submit")  # No shade for primary
        'Submit'
    """
    if isinstance(severity, str):
        try:
            severity = ActionSeverity(severity.lower())
        except ValueError:
            return label

    fmt = BUTTON_FORMATS.get(severity)
    if fmt and fmt.shade_char:
        return f"{fmt.shade_char} {label} {fmt.shade_char}"
    return label


def get_status_class(state: StatusState | str) -> str:
    """Get the CSS class for a status state.

    Args:
        state: Status state (enum or string)

    Returns:
        CSS class name, e.g. "status-online"
    """
    if isinstance(state, str):
        try:
            state = StatusState(state.lower())
        except ValueError:
            return "status-info"

    fmt = STATUS_FORMATS.get(state)
    return fmt.css_class if fmt else "status-info"


def get_button_class(severity: ActionSeverity | str) -> str:
    """Get the CSS class for a button severity.

    Args:
        severity: Action severity (enum or string)

    Returns:
        CSS class name, e.g. "-danger"
    """
    if isinstance(severity, str):
        try:
            severity = ActionSeverity(severity.lower())
        except ValueError:
            return ""

    fmt = BUTTON_FORMATS.get(severity)
    return fmt.css_class if fmt else ""
