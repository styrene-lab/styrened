"""Exploration Screen - Reticulum network discovery.

This screen displays all non-Styrene announces on the Reticulum network:
- LXMF peers and propagation nodes
- LXMS pages
- Generic Reticulum destinations
- RNodes
- Unknown/binary announces

Similar to Nomadnet's announcement exploration page.
"""

from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from styrened.models.mesh_device import DeviceType, NodeStatus
from styrened.tui.services.reticulum import discover_devices, start_discovery
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade

if TYPE_CHECKING:
    from styrened.models.mesh_device import MeshDevice


class ReticumAnnounceTable(DataTable[str]):
    """Reticulum announce listing - shows all non-Styrene devices."""

    def on_mount(self) -> None:
        self.add_columns("NAME", "TYPE", "IDENTITY", "STATUS", "LAST ANNOUNCE")
        self.cursor_type = "row"
        self._load_data()

    def _load_data(self) -> None:
        """Load all non-Styrene device announces from mesh discovery."""
        # Load historical data from NodeStore first
        try:
            from styrened.services.node_store import get_node_store

            stored_nodes = get_node_store().get_all_nodes()
        except Exception:
            stored_nodes = []

        # Get live discovered devices
        live_nodes = discover_devices()

        # Merge historical and live data (live takes precedence for duplicates)
        all_devices_dict = {n.destination_hash: n for n in stored_nodes}
        all_devices_dict.update({n.destination_hash: n for n in live_nodes})

        # Filter to non-Styrene devices (RNODE, GENERIC, UNKNOWN)
        # This is the inverse of the dashboard filter
        devices = [
            d
            for d in all_devices_dict.values()
            if d.device_type
            in [DeviceType.RNODE, DeviceType.GENERIC, DeviceType.UNKNOWN]
        ]

        # Clear and rebuild
        self.clear()

        if not devices:
            cascade = get_color_cascade()
            self.add_row(
                "-", "-", "-", f"[{cascade.dim}]No announces discovered[/]", "-"
            )
            return

        # Sort by last announce (most recent first)
        devices_sorted = sorted(devices, key=lambda d: d.last_announce, reverse=True)

        # Get cascade for dynamic theming
        cascade = get_color_cascade()

        for device in devices_sorted:
            # Device type display
            type_icons = {
                DeviceType.RNODE: f"[{cascade.medium}]RNODE[/]",
                DeviceType.GENERIC: f"[{cascade.dim}]GENERIC[/]",
                DeviceType.UNKNOWN: f"[{cascade.dim}]UNKNOWN[/]",
            }
            type_text = type_icons.get(device.device_type, f"[{cascade.dim}]?[/]")

            # Status colors
            status_colors = {
                NodeStatus.ACTIVE: cascade.medium,
                NodeStatus.STALE: cascade.dim,
                NodeStatus.LOST: cascade.dim,
            }
            status_color = status_colors.get(device.status, cascade.medium)
            status_text = f"[{status_color}]{device.status.value.upper()}[/]"

            # Identity with more characters for uniqueness (first 16 chars instead of 8)
            identity_text = device.destination_hash[:16] + "..."

            # Name styling based on type
            if device.is_rnode:
                name_text = f"[{cascade.medium}]{device.name}[/]"
            else:
                name_text = f"[{cascade.dim}]{device.name}[/]"

            # Show announce count in last seen if > 1
            last_seen_text = device.last_seen_display
            if device.announce_count > 1:
                last_seen_text += f" ({device.announce_count})"

            self.add_row(
                name_text,
                type_text,
                identity_text,
                status_text,
                last_seen_text,
                key=device.identity,
            )

    def refresh_data(self) -> None:
        """Refresh announce data."""
        self._load_data()


class ExplorationScreen(Screen[None]):
    """Reticulum network exploration screen.

    Shows all non-Styrene announces discovered on the network:
    - LXMF destinations
    - Propagation nodes
    - Generic Reticulum services
    - RNodes
    - Unknown/binary announces
    """

    CSS = """
    #exploration-container {
        height: 1fr;
    }

    #announces-panel {
        height: 1fr;
    }

    #reticulum-announce-table {
        height: 1fr;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("enter", "select_device", "Select"),
        Binding("r", "refresh", "Refresh"),
    ]

    # Debounce settings for discovery callbacks
    _last_discovery_refresh: float = 0.0
    _discovery_debounce_seconds: float = 2.0

    def on_mount(self) -> None:
        """Start device discovery when screen mounts."""
        # Start announce listener for device discovery
        start_discovery(callback=self._on_device_discovered)

        # Set up periodic refresh
        self.set_interval(15.0, self._refresh_announce_table)

    def _on_device_discovered(self, device: "MeshDevice") -> None:
        """Called when new device discovered via announce.

        This runs in RNS callback thread - use call_from_thread for UI updates.

        Args:
            device: Discovered MeshDevice object.
        """
        try:
            self.app.call_from_thread(self._add_discovered_device, device)
        except RuntimeError:
            # Already on main thread (e.g., in tests)
            self._add_discovered_device(device)

    def _add_discovered_device(self, device: "MeshDevice") -> None:
        """Add discovered device (runs on main thread).

        Debounces refresh to avoid constant table rebuilds.

        Args:
            device: MeshDevice object.
        """
        import time

        # Only notify for RNodes (interesting hardware)
        if device.is_rnode:
            self.notify(
                f"RNode: {device.name}",
                severity="information",
            )

        # Debounce table refresh
        now = time.time()
        if now - self._last_discovery_refresh >= self._discovery_debounce_seconds:
            self._last_discovery_refresh = now
            self._refresh_announce_table()

    def _refresh_announce_table(self) -> None:
        """Refresh the announce table with current discoveries."""
        try:
            table_widget = self.query_one(
                "#reticulum-announce-table", ReticumAnnounceTable
            )
            table_widget.refresh_data()
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="exploration-container"):
            yield HighlightedPanel(
                ReticumAnnounceTable(id="reticulum-announce-table"),
                title="RETICULUM ANNOUNCES",
                id="announces-panel",
            )
        yield Footer()

    def action_select_device(self) -> None:
        """Handle device selection - navigate to device detail screen."""
        table = self.query_one("#reticulum-announce-table", DataTable)
        if table.cursor_row is not None:
            # Get device identity from the row key
            cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
            if cell_key and cell_key.row_key and cell_key.row_key.value != "-":
                device_identity = str(cell_key.row_key.value)
                # Navigate to mesh device detail screen
                from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

                self.app.push_screen(
                    MeshDeviceDetailScreen(device_identity=device_identity)
                )

    def action_refresh(self) -> None:
        """Refresh all data on the exploration screen."""
        self.notify("Refreshing...", title="Refresh")

        # Refresh announce table
        try:
            table_widget = self.query_one(
                "#reticulum-announce-table", ReticumAnnounceTable
            )
            table_widget.refresh_data()
        except Exception:
            pass
