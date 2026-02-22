"""Local Dashboard Screen - compact single-column device status."""

from __future__ import annotations

import contextlib
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header

from styrened.tui.widgets.highlighted_panel import HighlightedPanel
from styrened.tui.widgets.node_info_panel import NodeInfoPanel
from styrened.tui.widgets.uptime_panel import UptimePanel


class LocalDashboardScreen(Screen[None]):
    """Compact dashboard showing local device status.

    Designed for Zellij pane use: single-column, minimal chrome,
    auto-refreshing. Reuses existing NodeInfoPanel for system/RNS/styrene
    status and adds UptimePanel for uptime and load.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="dashboard-local-container"):
            yield HighlightedPanel(
                NodeInfoPanel(id="dashboard-node-info"),
                title="NODE STATUS",
                id="dashboard-node-panel",
            )
            yield HighlightedPanel(
                UptimePanel(id="dashboard-uptime"),
                title="LOAD",
                id="dashboard-uptime-panel",
            )
        yield Footer()

    def on_mount(self) -> None:
        """Set up periodic refresh."""
        self.set_interval(5.0, self._refresh_all)

    def _refresh_all(self) -> None:
        """Refresh all dashboard panels."""
        with contextlib.suppress(Exception):
            self.query_one("#dashboard-node-info", NodeInfoPanel).refresh_data()
        with contextlib.suppress(Exception):
            self.query_one("#dashboard-uptime", UptimePanel).refresh_data()

    def action_refresh(self) -> None:
        """Manual refresh all panels."""
        self._refresh_all()
        self.notify("Refreshed", timeout=2)
