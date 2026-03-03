"""Exploration Screen - Reticulum network discovery.

Categorized tabbed interface for non-Styrene announces on the Reticulum network:
- LXMF tab: messaging peers (Sideband, MeshChat, NomadNet users)
- Pages tab: NomadNet page services with inline page browser
- Infrastructure tab: propagation nodes, RNodes
- Other tab: generic/unknown announces
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Static,
    TabbedContent,
    TabPane,
)

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.services.reticulum import discover_devices, start_discovery
from styrened.tui.widgets.highlighted_panel import get_color_cascade

# Device types shown on the exploration screen (non-Styrene announces)
_EXPLORATION_TYPES = frozenset({
    DeviceType.RNODE,
    DeviceType.GENERIC,
    DeviceType.UNKNOWN,
    DeviceType.LXMF_PEER,
    DeviceType.PROPAGATION_NODE,
    DeviceType.NOMADNET_NODE,
})

# Category groupings for tabs
_LXMF_TYPES = frozenset({DeviceType.LXMF_PEER})
_PAGES_TYPES = frozenset({DeviceType.NOMADNET_NODE})
_INFRA_TYPES = frozenset({DeviceType.PROPAGATION_NODE, DeviceType.RNODE})
_OTHER_TYPES = frozenset({DeviceType.GENERIC, DeviceType.UNKNOWN})


class ReticumAnnounceTable(DataTable[str]):
    """Reticulum announce listing — filterable by device type categories."""

    # Column keys for sorting
    COLUMN_KEYS = ("name", "type", "identity", "status", "last_announce")

    def __init__(
        self,
        *args,  # noqa: ANN002
        device_types: frozenset[DeviceType] | None = None,
        **kwargs,  # noqa: ANN003
    ) -> None:
        super().__init__(*args, **kwargs)
        self._device_types = device_types or _EXPLORATION_TYPES
        self._all_devices: list[MeshDevice] = []
        self._filter_text: str = ""
        self._sort_column: str = "last_announce"
        self._sort_reverse: bool = True  # Most recent first by default

    def on_mount(self) -> None:
        self.add_columns(
            ("name", "NAME"),
            ("type", "TYPE"),
            ("identity", "IDENTITY"),
            ("hops", "HOPS"),
            ("via", "VIA"),
            ("status", "STATUS"),
            ("last_announce", "LAST ANNOUNCE"),
        )
        self.cursor_type = "row"

    @property
    def device_count(self) -> int:
        """Number of devices in this table (pre-filter)."""
        return len(self._all_devices)

    def load_from_devices(self, devices: list[MeshDevice]) -> None:
        """Accept pre-fetched device list, filter to this table's types, and rebuild.

        Args:
            devices: Full list of exploration devices (already LXMF-shadow-filtered).
        """
        self._all_devices = [
            d for d in devices if d.device_type in self._device_types
        ]
        self._rebuild_table()

    def _load_data(self) -> None:
        """Load all non-Styrene device announces from mesh discovery.

        Standalone fallback — primary path uses load_from_devices().
        """
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
        all_exploration = [
            d for d in all_devices_dict.values()
            if d.device_type in _EXPLORATION_TYPES
            and d.identity_hash not in styrene_identities
        ]

        # Further filter to this table's device types
        self._all_devices = [
            d for d in all_exploration if d.device_type in self._device_types
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
                "-", "-", "-", "-", "-", f"[{cascade.dim}]{msg}[/]", "-"
            )
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

            # Hops display
            if device.hops is not None:
                if device.hops == 0:
                    hops_text = f"[{cascade.medium}]direct[/]"
                else:
                    hops_text = f"[{cascade.dim}]{device.hops}[/]"
            else:
                hops_text = f"[{cascade.dim}]—[/]"

            # Interface/via display
            via_text = f"[{cascade.dim}]{device.discovered_via}[/]" if device.discovered_via else f"[{cascade.dim}]—[/]"

            self.add_row(
                name_text,
                type_text,
                identity_text,
                hops_text,
                via_text,
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
            "hops": lambda d: d.hops if d.hops is not None else 999,
            "via": lambda d: (d.discovered_via or "").lower(),
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
        """Refresh announce data (standalone mode)."""
        self._load_data()


class ExplorationScreen(Screen[None]):
    """Reticulum network exploration screen.

    Categorized tabs for non-Styrene announces:
    - LXMF: messaging destinations
    - Pages: NomadNet page services with inline browser
    - Infrastructure: propagation nodes, RNodes
    - Other: generic/unknown announces
    """

    CSS = """
    #exploration-container {
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

    #explore-tabs {
        height: 1fr;
    }

    .explore-tab-table {
        height: 1fr;
    }

    #pages-pane-content {
        height: 1fr;
    }

    #pages-table-section {
        height: 2fr;
        min-height: 5;
    }

    #pages-browser-section {
        height: 3fr;
    }

    #pages-browser-section.hidden {
        display: none;
    }

    #pages-browser-placeholder {
        height: 3;
        padding: 1;
        color: $panel;
        text-style: italic;
    }

    #pages-browser-placeholder.hidden {
        display: none;
    }

    .explore-inline-browser {
        height: 1fr;
        border-top: solid $border;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "dismiss_search", "Back", priority=True),
        Binding("enter", "select_device", "Select"),
        Binding("c", "open_chat", "Chat"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "show_search", "Search", key_display="/", priority=True),
        Binding("v", "preview_page", "Preview", show=True),
    ]

    # Debounce settings for discovery callbacks
    _last_discovery_refresh: float = 0.0
    _discovery_debounce_seconds: float = 2.0

    def on_mount(self) -> None:
        """Start device discovery and load initial data."""
        start_discovery(callback=self._on_device_discovered)
        self.set_interval(15.0, self._refresh_announce_tables)
        # Initial load
        self._refresh_announce_tables()
        # Focus active table after TabbedContent is ready
        self.call_later(self._focus_active_table)

    def _focus_active_table(self) -> None:
        """Focus the table in the currently active tab."""
        table = self._get_active_table()
        if table:
            table.focus()

    def _on_device_discovered(self, device: MeshDevice) -> None:
        """Called when new device discovered via announce.

        This runs in RNS callback thread — use call_from_thread for UI updates.
        """
        try:
            self.app.call_from_thread(self._add_discovered_device, device)
        except RuntimeError:
            self._add_discovered_device(device)

    def _add_discovered_device(self, device: MeshDevice) -> None:
        """Add discovered device (runs on main thread).

        Debounces refresh to avoid constant table rebuilds.
        """
        import time

        if device.is_rnode:
            self.notify(
                f"RNode: {device.name}",
                severity="information",
            )

        now = time.time()
        if now - self._last_discovery_refresh >= self._discovery_debounce_seconds:
            self._last_discovery_refresh = now
            self._refresh_announce_tables()

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="exploration-container"):
            yield Input(
                placeholder="Search announces...",
                id="explore-search-bar",
                classes="hidden",
            )
            with TabbedContent(id="explore-tabs"):
                with TabPane("LXMF", id="tab-lxmf"):
                    yield ReticumAnnounceTable(
                        id="table-lxmf",
                        device_types=_LXMF_TYPES,
                        classes="explore-tab-table",
                    )
                with TabPane("Pages", id="tab-pages"):
                    with Vertical(id="pages-pane-content"):
                        with Vertical(id="pages-table-section"):
                            yield ReticumAnnounceTable(
                                id="table-pages",
                                device_types=_PAGES_TYPES,
                                classes="explore-tab-table",
                            )
                        yield Static(
                            "Press [bold]v[/bold] on a node to preview pages",
                            id="pages-browser-placeholder",
                        )
                        with Vertical(id="pages-browser-section", classes="hidden"):
                            pass  # PageBrowserWidget mounted dynamically
                with TabPane("Infra", id="tab-infra"):
                    yield ReticumAnnounceTable(
                        id="table-infra",
                        device_types=_INFRA_TYPES,
                        classes="explore-tab-table",
                    )
                with TabPane("Other", id="tab-other"):
                    yield ReticumAnnounceTable(
                        id="table-other",
                        device_types=_OTHER_TYPES,
                        classes="explore-tab-table",
                    )
            yield Static("", id="explore-count")
        yield Footer()

    def _get_all_tables(self) -> list[ReticumAnnounceTable]:
        """Get all announce tables across tabs."""
        table_ids = ["#table-lxmf", "#table-pages", "#table-infra", "#table-other"]
        tables = []
        for tid in table_ids:
            try:
                tables.append(self.query_one(tid, ReticumAnnounceTable))
            except Exception:
                pass
        return tables

    def _get_active_table(self) -> ReticumAnnounceTable | None:
        """Get the announce table in the currently active tab."""
        try:
            tabs = self.query_one("#explore-tabs", TabbedContent)
            active_id = tabs.active
            # Map tab pane ID to table ID
            table_map = {
                "tab-lxmf": "#table-lxmf",
                "tab-pages": "#table-pages",
                "tab-infra": "#table-infra",
                "tab-other": "#table-other",
            }
            table_id = table_map.get(active_id)
            if table_id:
                return self.query_one(table_id, ReticumAnnounceTable)
        except Exception:
            pass
        return None

    def _load_all_devices(self) -> list[MeshDevice]:
        """Load and deduplicate all exploration devices, filtering LXMF shadows."""
        try:
            from styrened.services.node_store import get_node_store
            stored_nodes = get_node_store().get_all_nodes()
        except Exception:
            stored_nodes = []

        live_nodes = discover_devices()

        all_devices_dict = {n.destination_hash: n for n in stored_nodes}
        all_devices_dict.update({n.destination_hash: n for n in live_nodes})

        styrene_identities = {
            d.identity_hash
            for d in all_devices_dict.values()
            if d.device_type == DeviceType.STYRENE_NODE
        }

        return [
            d for d in all_devices_dict.values()
            if d.device_type in _EXPLORATION_TYPES
            and d.identity_hash not in styrene_identities
        ]

    def _refresh_announce_tables(self) -> None:
        """Load all devices once and distribute to category tables."""
        devices = self._load_all_devices()
        for table in self._get_all_tables():
            table.load_from_devices(devices)
        self._update_tab_labels()

    def _update_tab_labels(self) -> None:
        """Update tab labels with device counts."""
        label_map = {
            "#table-lxmf": ("tab-lxmf", "LXMF"),
            "#table-pages": ("tab-pages", "Pages"),
            "#table-infra": ("tab-infra", "Infra"),
            "#table-other": ("tab-other", "Other"),
        }
        try:
            tabs_widget = self.query_one("#explore-tabs", TabbedContent)
            for table_id, (pane_id, base_label) in label_map.items():
                try:
                    table = self.query_one(table_id, ReticumAnnounceTable)
                    count = table.device_count
                    tab = tabs_widget.get_tab(pane_id)
                    if count > 0:
                        tab.label = f"{base_label} ({count})"
                    else:
                        tab.label = base_label
                except Exception:
                    pass
        except Exception:
            pass

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Clear search bar when switching tabs.

        Does NOT auto-focus the table — focus stays on the tab bar so
        arrow keys continue navigating between tabs.  Press Tab to enter
        the table content.
        """
        try:
            search = self.query_one("#explore-search-bar", Input)
            if not search.has_class("hidden"):
                search.value = ""
                for table in self._get_all_tables():
                    table.set_filter("")
        except Exception:
            pass

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
            # Use the specific table that emitted the event
            table = event.data_table
            if isinstance(table, ReticumAnnounceTable):
                table.sort_by(column_key)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes — filter the active tab's table."""
        if event.input.id == "explore-search-bar":
            table = self._get_active_table()
            if table:
                table.set_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submitted — hide search, keep filter active."""
        if event.input.id == "explore-search-bar":
            self._hide_search()

    def _get_selected_identity(self) -> str | None:
        """Get the identity of the currently selected row in the active tab."""
        table = self._get_active_table()
        if table and table.cursor_row is not None:
            try:
                cell_key = table.coordinate_to_cell_key(
                    Coordinate(table.cursor_row, 0)
                )
                if cell_key and cell_key.row_key and cell_key.row_key.value != "-":
                    return str(cell_key.row_key.value)
            except Exception:
                pass
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
            search.value = ""
            self._hide_search()
            table = self._get_active_table()
            if table:
                table.set_filter("")
        else:
            self.app.pop_screen()

    def _hide_search(self) -> None:
        """Hide the search input and return focus to the active tab's table."""
        search = self.query_one("#explore-search-bar", Input)
        search.add_class("hidden")
        table = self._get_active_table()
        if table:
            table.focus()

    def update_count(self, visible: int, total: int) -> None:
        """Update the count indicator below the tabs."""
        try:
            count_widget = self.query_one("#explore-count", Static)
            if visible == total:
                count_widget.update(f"{total} announces")
            else:
                count_widget.update(f"{visible} / {total} announces")
        except Exception:
            pass

    def action_select_device(self) -> None:
        """Handle device selection — navigate to device detail screen."""
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

    def action_preview_page(self) -> None:
        """Load selected NomadNet node's index page in the inline browser."""
        try:
            tabs = self.query_one("#explore-tabs", TabbedContent)
            if tabs.active != "tab-pages":
                return
        except Exception:
            return

        dest_hash = self._get_selected_identity()
        if not dest_hash:
            return

        from styrened.tui.widgets.page_browser import PageBrowserWidget

        try:
            # Hide placeholder, show browser section
            placeholder = self.query_one("#pages-browser-placeholder", Static)
            placeholder.add_class("hidden")

            browser_section = self.query_one("#pages-browser-section", Vertical)
            browser_section.remove_class("hidden")

            # Check if browser already exists
            existing = browser_section.query(PageBrowserWidget)
            if existing:
                existing.first().set_destination(dest_hash)
            else:
                browser = PageBrowserWidget(
                    destination_hash=dest_hash,
                    classes="explore-inline-browser",
                )
                browser_section.mount(browser)
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Refresh all data on the exploration screen."""
        self.notify("Refreshing...", title="Refresh")
        self._refresh_announce_tables()
