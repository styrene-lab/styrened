"""Exploration Screen - Reticulum network discovery.

This screen displays all non-Styrene announces on the Reticulum network:
- LXMF peers and propagation nodes
- NomadNet nodes
- Generic Reticulum destinations
- RNodes
- Unknown/binary announces

Similar to Nomadnet's announcement exploration page.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.services.reticulum import discover_devices, start_discovery
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade

# Device types shown on the exploration screen (non-Styrene announces)
_EXPLORATION_TYPES = frozenset({
    DeviceType.RNODE,
    DeviceType.GENERIC,
    DeviceType.UNKNOWN,
    DeviceType.LXMF_PEER,
    DeviceType.PROPAGATION_NODE,
    DeviceType.NOMADNET_NODE,
})


class ReticumAnnounceTable(DataTable[str]):
    """Reticulum announce listing - shows all non-Styrene devices."""

    # Column keys for sorting
    COLUMN_KEYS = ("name", "type", "identity", "status", "last_announce")

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._all_devices: list[MeshDevice] = []
        self._filter_text: str = ""
        self._sort_column: str = "last_announce"
        self._sort_reverse: bool = True  # Most recent first by default

    def on_mount(self) -> None:
        self.add_columns(
            ("name", "NAME"),
            ("type", "TYPE"),
            ("identity", "IDENTITY"),
            ("status", "STATUS"),
            ("last_announce", "LAST ANNOUNCE"),
        )
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

        # Collect identity hashes that belong to Styrene nodes so we can
        # suppress their LXMF shadow entries (same identity, different aspect)
        styrene_identities = {
            d.identity_hash
            for d in all_devices_dict.values()
            if d.device_type == DeviceType.STYRENE_NODE
        }

        # Filter to non-Styrene devices, excluding LXMF shadows of Styrene nodes
        self._all_devices = [
            d for d in all_devices_dict.values()
            if d.device_type in _EXPLORATION_TYPES
            and d.identity_hash not in styrene_identities
        ]

        self._rebuild_table()

    def _rebuild_table(self) -> None:
        """Rebuild the visible table rows from stored devices, applying filter and sort."""
        devices = self._all_devices

        # Apply search filter
        if self._filter_text:
            query = self._filter_text.lower()
            devices = [
                d for d in devices
                if query in d.name.lower()
                or query in d.destination_hash.lower()
                or query in d.device_type.value.lower()
            ]

        # Sort
        devices_sorted = self._sort_devices(devices)

        # Track current selection to restore after update
        selected_key: str | None = None
        if self.cursor_row is not None and self.row_count > 0:
            try:
                cell_key = self.coordinate_to_cell_key(Coordinate(self.cursor_row, 0))
                if cell_key and cell_key.row_key:
                    selected_key = str(cell_key.row_key.value)
            except Exception:
                pass

        # Clear and rebuild
        self.clear()

        if not devices_sorted:
            cascade = get_color_cascade()
            if self._filter_text:
                msg = f"No matches for '{self._filter_text}'"
            else:
                msg = "No announces discovered"
            self.add_row(
                "-", "-", "-", f"[{cascade.dim}]{msg}[/]", "-"
            )
            # Update count
            self._post_count_update(0, len(self._all_devices))
            return

        # Get cascade for dynamic theming
        cascade = get_color_cascade()

        type_icons = {
            DeviceType.RNODE: f"[{cascade.medium}]RNODE[/]",
            DeviceType.LXMF_PEER: f"[{cascade.medium}]LXMF[/]",
            DeviceType.PROPAGATION_NODE: f"[{cascade.medium}]PROPNODE[/]",
            DeviceType.NOMADNET_NODE: f"[{cascade.medium}]NOMAD[/]",
            DeviceType.GENERIC: f"[{cascade.dim}]GENERIC[/]",
            DeviceType.UNKNOWN: f"[{cascade.dim}]UNKNOWN[/]",
        }

        status_colors = {
            NodeStatus.ACTIVE: cascade.medium,
            NodeStatus.STALE: cascade.dim,
            NodeStatus.LOST: cascade.dim,
        }

        for device in devices_sorted:
            type_text = type_icons.get(device.device_type, f"[{cascade.dim}]?[/]")

            status_color = status_colors.get(device.status, cascade.medium)
            status_text = f"[{status_color}]{device.status.value.upper()}[/]"

            identity_text = device.destination_hash[:16] + "..."

            # Name styling: brighter for typed devices
            if device.device_type in (
                DeviceType.RNODE, DeviceType.LXMF_PEER,
                DeviceType.PROPAGATION_NODE, DeviceType.NOMADNET_NODE,
            ):
                name_text = f"[{cascade.medium}]{device.name}[/]"
            else:
                name_text = f"[{cascade.dim}]{device.name}[/]"

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

        # Restore cursor selection if possible
        if selected_key and self.row_count > 0:
            for row_idx in range(self.row_count):
                try:
                    cell_key = self.coordinate_to_cell_key(Coordinate(row_idx, 0))
                    if (
                        cell_key
                        and cell_key.row_key
                        and str(cell_key.row_key.value) == selected_key
                    ):
                        self.cursor_coordinate = Coordinate(row_idx, 0)
                        break
                except Exception:
                    pass

        self._post_count_update(len(devices_sorted), len(self._all_devices))

    def _post_count_update(self, visible: int, total: int) -> None:
        """Post a message to update the count indicator."""
        try:
            screen = self.screen
            if isinstance(screen, ExplorationScreen):
                screen.update_count(visible, total)
        except Exception:
            pass

    def _sort_devices(self, devices: list[MeshDevice]) -> list[MeshDevice]:
        """Sort devices by the current sort column."""
        key_funcs = {
            "name": lambda d: d.name.lower(),
            "type": lambda d: d.device_type.value,
            "identity": lambda d: d.destination_hash,
            "status": lambda d: d.status.value,
            "last_announce": lambda d: d.last_announce,
        }
        key_fn = key_funcs.get(self._sort_column, key_funcs["last_announce"])
        return sorted(devices, key=key_fn, reverse=self._sort_reverse)

    def set_filter(self, text: str) -> None:
        """Set the search filter text and rebuild the table."""
        self._filter_text = text
        self._rebuild_table()

    def sort_by(self, column_key: str) -> None:
        """Sort by the given column, toggling direction if same column."""
        if self._sort_column == column_key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column_key
            # Default to ascending for name/type/identity, descending for time
            self._sort_reverse = column_key in ("last_announce", "status")
        self._rebuild_table()

    def refresh_data(self) -> None:
        """Refresh announce data."""
        self._load_data()


class ExplorationScreen(Screen[None]):
    """Reticulum network exploration screen.

    Shows all non-Styrene announces discovered on the network:
    - LXMF destinations
    - Propagation nodes
    - NomadNet nodes
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

    #explore-search-bar {
        height: auto;
        max-height: 3;
        padding: 0 1;
        background: $surface;
    }

    #explore-search-bar.hidden {
        display: none;
    }

    #explore-count {
        height: 1;
        padding: 0 1;
        color: $panel;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_search", "Back", priority=True),
        Binding("enter", "select_device", "Select"),
        Binding("c", "open_chat", "Chat"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "show_search", "Search", key_display="/"),
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

    def _on_device_discovered(self, device: MeshDevice) -> None:
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

    def _add_discovered_device(self, device: MeshDevice) -> None:
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
                Input(
                    placeholder="Search announces...",
                    id="explore-search-bar",
                    classes="hidden",
                ),
                Static("", id="explore-count"),
                title="RETICULUM ANNOUNCES",
                id="announces-panel",
            )
        yield Footer()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle DataTable enter key — navigate to device detail screen."""
        if event.row_key and event.row_key.value and event.row_key.value != "-":
            device_identity = str(event.row_key.value)
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

            self.app.push_screen(MeshDeviceDetailScreen(device_identity=device_identity))

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header click — sort by that column."""
        column_key = str(event.column_key.value) if event.column_key else None
        if column_key and column_key in ReticumAnnounceTable.COLUMN_KEYS:
            try:
                table = self.query_one("#reticulum-announce-table", ReticumAnnounceTable)
                table.sort_by(column_key)
            except Exception:
                pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes — filter the table."""
        if event.input.id == "explore-search-bar":
            try:
                table = self.query_one("#reticulum-announce-table", ReticumAnnounceTable)
                table.set_filter(event.value)
            except Exception:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submitted — hide search, keep filter active."""
        if event.input.id == "explore-search-bar":
            self._hide_search()

    def _get_selected_identity(self) -> str | None:
        """Get the identity of the currently selected row."""
        table = self.query_one("#reticulum-announce-table", DataTable)
        if table.cursor_row is not None:
            cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
            if cell_key and cell_key.row_key and cell_key.row_key.value != "-":
                return str(cell_key.row_key.value)
        return None

    def action_show_search(self) -> None:
        """Show and focus the search input."""
        search = self.query_one("#explore-search-bar", Input)
        search.remove_class("hidden")
        search.focus()

    def action_dismiss_search(self) -> None:
        """Dismiss search or pop screen."""
        search = self.query_one("#explore-search-bar", Input)
        if not search.has_class("hidden"):
            # Clear filter and hide search
            search.value = ""
            self._hide_search()
            try:
                table = self.query_one("#reticulum-announce-table", ReticumAnnounceTable)
                table.set_filter("")
            except Exception:
                pass
        else:
            self.app.pop_screen()

    def _hide_search(self) -> None:
        """Hide the search input and return focus to the table."""
        search = self.query_one("#explore-search-bar", Input)
        search.add_class("hidden")
        try:
            table = self.query_one("#reticulum-announce-table", ReticumAnnounceTable)
            table.focus()
        except Exception:
            pass

    def update_count(self, visible: int, total: int) -> None:
        """Update the count indicator below the table."""
        try:
            count_widget = self.query_one("#explore-count", Static)
            if visible == total:
                count_widget.update(f"{total} announces")
            else:
                count_widget.update(f"{visible} / {total} announces")
        except Exception:
            pass

    def action_select_device(self) -> None:
        """Handle device selection - navigate to device detail screen."""
        device_identity = self._get_selected_identity()
        if device_identity:
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

            self.app.push_screen(
                MeshDeviceDetailScreen(device_identity=device_identity)
            )

    def action_open_chat(self) -> None:
        """Open chat tab directly for the selected device."""
        device_identity = self._get_selected_identity()
        if device_identity:
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

            self.app.push_screen(
                MeshDeviceDetailScreen(device_identity=device_identity, initial_tab="chat")
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
