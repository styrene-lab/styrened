"""Daemon event messages for TUI consumption.

When the daemon's EventBus emits an event, the IPC bridge receives it
and posts a ``DaemonEvent`` Textual message to the app.  Screens that
care about real-time updates handle this message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.message import Message


@dataclass
class DaemonEvent(Message):
    """A daemon event bridged to the TUI via IPC.

    Attributes:
        event_type: Coarse category (node_changed, message_changed, etc.).
        action: Specific action (announced, received, connected, etc.).
        data: Minimal payload dict.
    """

    event_type: str
    action: str
    data: dict[str, Any] = field(default_factory=dict)
