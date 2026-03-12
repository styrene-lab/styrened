"""Styrene TUI widgets.

Custom Textual widgets for the fleet management interface.
"""
from __future__ import annotations


from styrened.tui.widgets.chat_widget import ChatWidget
from styrened.tui.widgets.color_picker import ColorPickerDialog
from styrened.tui.widgets.comms_summary import CommsSummaryWidget
from styrened.tui.widgets.hardware_panel import HardwarePanel
from styrened.tui.widgets.message_bubble import MessageBubble

__all__ = [
    "ChatWidget",
    "ColorPickerDialog",
    "CommsSummaryWidget",
    "CopActivitySummary",
    "HardwarePanel",
    "MessageBubble",
]
