"""Comms workspace screen.

Initial aggregate shell for synchronous/direct/live communication. This first
slice focuses on stable workspace structure and capability-gated empty states.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Static, TabbedContent, TabPane

from styrened.ui_state import CommsMode, CommsWorkspaceInputs, build_comms_workspace_state


class CommsScreen(Screen[None]):
    """Aggregate workspace for synchronous and live communication."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        state = build_comms_workspace_state(CommsWorkspaceInputs())
        yield Header()
        with Container(id="comms-container"):
            yield Static("COMMS", id="comms-title")
            with TabbedContent(initial=state.active_mode.value, id="comms-tabs"):
                with TabPane("Direct", id=CommsMode.DIRECT.value):
                    yield Static(
                        "Direct synchronous communication will appear here.",
                        id="comms-direct-placeholder",
                    )
                with TabPane("Active", id=CommsMode.ACTIVE.value):
                    yield Static(
                        "Active sessions will appear here.",
                        id="comms-active-placeholder",
                    )
                with TabPane("Bridges", id=CommsMode.BRIDGES.value):
                    yield Static(
                        "Bridge-backed communication surfaces will appear here when authoritative daemon capability data exists.",
                        id="comms-bridges-placeholder",
                    )
                with TabPane("Presence", id=CommsMode.PRESENCE.value):
                    yield Static(
                        "Live presence and reachability will appear here.",
                        id="comms-presence-placeholder",
                    )
        yield Footer()
