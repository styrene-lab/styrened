"""Device Detail Screen - Device information and actions."""

import logging
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from styrened.tui.models.fleet import Device
from styrened.tui.widgets.highlighted_panel import HighlightedPanel
from styrened.tui.widgets.safe_header import Header

logger = logging.getLogger(__name__)


class DeviceInfoPanel(Static):
    """Device information display panel."""

    def __init__(self, device: Device) -> None:
        super().__init__()
        self.device = device

    def compose(self) -> ComposeResult:
        yield Static(f"[bold]Name:[/] {self.device.name}")
        yield Static(f"[bold]Profile:[/] {self.device.profile}")
        yield Static(f"[bold]Hardware:[/] {self.device.hardware}")
        yield Static(f"[bold]Status:[/] {self._format_status(self.device.status)}")

        if self.device.ip_address:
            yield Static(f"[bold]IP Address:[/] {self.device.ip_address}")
        else:
            yield Static("[bold]IP Address:[/] [dim]not assigned[/]")

        if self.device.reticulum_identity:
            yield Static(f"[bold]Reticulum ID:[/] {self.device.reticulum_identity}")
        else:
            yield Static("[bold]Reticulum ID:[/] [dim]not assigned[/]")

        if self.device.last_seen:
            yield Static(f"[bold]Last Seen:[/] {self.device.last_seen_display}")
        else:
            yield Static("[bold]Last Seen:[/] [dim]never[/]")

        if self.device.notes:
            yield Static(f"[bold]Notes:[/] {self.device.notes}")

    def _format_status(self, status: str) -> str:
        """Format status with color."""
        color_map = {
            "online": "green",
            "offline": "red",
            "pending": "yellow",
            "error": "red",
        }
        color = color_map.get(status, "white")
        return f"[{color}]{status.upper()}[/]"


class DeviceActionsPanel(Static):
    """Device action buttons panel."""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="action-buttons"):
            yield Button("[S]hell", id="action-shell", variant="primary")
            yield Button("[L]ogs", id="action-logs", variant="primary")
            yield Button("[R]eboot", id="action-reboot", variant="warning")
            yield Button("[U]pdate", id="action-update", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle action button presses."""
        if event.button.id is None:
            return

        action_messages = {
            "action-shell": "rnsh integration coming in Phase 2B",
            "action-logs": "Log viewer coming in Phase 2B",
            "action-reboot": "Remote reboot coming in Phase 2B",
            "action-update": "Config rebuild coming in Phase 2B",
        }

        message = action_messages.get(event.button.id, "Action not implemented")
        self.notify(message, title="Coming Soon", severity="information")


class DeviceScreen(Screen[None]):
    """Device detail screen showing device information and actions.

    Accepts a pre-resolved ``Device`` object so the screen never issues
    direct fleet-service I/O calls on the event loop thread.  The caller
    is responsible for loading the device from the fleet inventory (via the
    IPC bridge or any other mechanism) before pushing this screen.

    This screen is usable standalone (reachable from mesh_device_detail or
    the Exchange/Provision screen).
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("s", "action_shell", "Shell", show=False),
        Binding("l", "action_logs", "Logs", show=False),
        Binding("r", "action_reboot", "Reboot", show=False),
        Binding("u", "action_update", "Update", show=False),
    ]

    def __init__(self, device: Device) -> None:
        """Initialize device screen.

        Args:
            device: Pre-resolved fleet Device to display.  The caller is
                responsible for fetching this from the inventory; this screen
                does no fleet I/O of its own.
        """
        super().__init__()
        self.device: Device = device

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="device-container"):
            yield HighlightedPanel(
                DeviceInfoPanel(self.device),
                title=f"DEVICE: {self.device.name}",
                id="device-info-panel",
            )
            yield HighlightedPanel(
                DeviceActionsPanel(),
                title="ACTIONS",
                id="device-actions-panel",
            )
        yield Footer()

    def action_action_shell(self) -> None:
        """Stub for shell action (Phase 2B)."""
        self.notify("rnsh integration coming in Phase 2B", title="Coming Soon")

    def action_action_logs(self) -> None:
        """Stub for logs action (Phase 2B)."""
        self.notify("Log viewer coming in Phase 2B", title="Coming Soon")

    def action_action_reboot(self) -> None:
        """Stub for reboot action (Phase 2B)."""
        self.notify("Remote reboot coming in Phase 2B", title="Coming Soon")

    def action_action_update(self) -> None:
        """Stub for update action (Phase 2B)."""
        self.notify("Config rebuild coming in Phase 2B", title="Coming Soon")
