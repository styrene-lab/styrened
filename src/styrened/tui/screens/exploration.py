"""Nodes workspace for Reticulum discovery and peer browsing.

Categorized tabbed interface for current network discovery:
- Styrene tab: canonical Styrene peer browsing with version, capabilities, hops
- LXMF tab: messaging peers (Sideband, MeshChat, NomadNet users)
- Pages tab: NomadNet page services with inline page browser
- Infrastructure tab: propagation nodes, RNodes
- Other tab: generic/unknown announces
"""

from __future__ import annotations

from typing import Any, ClassVar

from textual.app import ComposeResult
from textual import events
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Static,
    TabbedContent,
    TabPane,
)

from styrened.ipc.protocol import IPCMessageType
from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.services.reticulum import discover_devices, start_discovery
from styrened.tui.screens.exploration_projection import build_styrene_fleet_projection
from styrened.tui.widgets.activity_feed import ActivityFeedWidget
from styrened.tui.widgets.highlighted_panel import get_color_cascade
from styrened.ui_state import WorkspaceId

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
_STYRENE_TYPES = frozenset({DeviceType.STYRENE_NODE})
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
        self._hide_lost: bool = True  # Hide LOST by default
        self._hide_stale: bool = False

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
        # Load historical data — prefer live discovery, no direct daemon import
        stored_nodes: list[MeshDevice] = []

        # Get live discovered devices from cache (populated by async worker)
        live_nodes = getattr(self, "_live_nodes_cache", [])

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

    @property
    def status_counts(self) -> dict[str, int]:
        """Count devices by status (pre-text-filter, post-type-filter)."""
        counts = {"active": 0, "stale": 0, "lost": 0}
        for d in self._all_devices:
            counts[d.status.value] = counts.get(d.status.value, 0) + 1
        return counts

    def toggle_hide_lost(self) -> bool:
        """Toggle hide-lost filter. Returns new state."""
        self._hide_lost = not self._hide_lost
        self._rebuild_table()
        return self._hide_lost

    def toggle_hide_stale(self) -> bool:
        """Toggle hide-stale filter. Returns new state."""
        self._hide_stale = not self._hide_stale
        self._rebuild_table()
        return self._hide_stale

    @property
    def hiding_lost(self) -> bool:
        return self._hide_lost

    @property
    def hiding_stale(self) -> bool:
        return self._hide_stale

    def _rebuild_table(self) -> None:
        """Rebuild the visible table rows from stored devices, applying filter and sort."""
        devices = self._all_devices

        # Apply status filters
        if self._hide_lost:
            devices = [d for d in devices if d.status != NodeStatus.LOST]
        if self._hide_stale:
            devices = [d for d in devices if d.status != NodeStatus.STALE]

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
                f"[{cascade.dim}]{msg}[/]", "", "", "", "", "", ""
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
            # Stale rows get full dim treatment
            is_stale = device.status == NodeStatus.STALE
            is_lost = device.status == NodeStatus.LOST
            dim = is_stale or is_lost
            c = cascade.dim if dim else cascade.medium

            type_text = type_icons.get(device.device_type, f"[{cascade.dim}]?[/]")
            if dim:
                # Override type icon to dim
                type_label = {
                    DeviceType.RNODE: "RNODE",
                    DeviceType.LXMF_PEER: "LXMF",
                    DeviceType.PROPAGATION_NODE: "PROPNODE",
                    DeviceType.NOMADNET_NODE: "NOMAD",
                    DeviceType.GENERIC: "GENERIC",
                    DeviceType.UNKNOWN: "UNKNOWN",
                }.get(device.device_type, "?")
                type_text = f"[{cascade.dim}]{type_label}[/]"

            status_color = status_colors.get(device.status, cascade.medium)
            status_icon = {
                NodeStatus.ACTIVE: "●",
                NodeStatus.STALE: "◐",
                NodeStatus.LOST: "○",
            }.get(device.status, "?")
            status_text = f"[{status_color}]{status_icon} {device.status.value.upper()}[/]"

            identity_text = f"[{c}]{device.destination_hash[:16]}...[/]"

            # Name styling: active=bright, stale/lost=dim
            if device.status == NodeStatus.ACTIVE:
                name_text = f"[{cascade.bright}]{device.name}[/]"
            elif is_stale:
                name_text = f"[{cascade.dim}]{device.name}[/]"
            else:
                name_text = f"[{c}]{device.name}[/]"

            last_seen_text = device.last_seen_display
            if device.announce_count > 1:
                last_seen_text += f" ({device.announce_count})"
            last_seen_text = f"[{c}]{last_seen_text}[/]"

            # Hops display
            if device.hops is not None:
                if device.hops == 0:
                    hops_text = f"[{c}]direct[/]"
                else:
                    hops_text = f"[{c}]{device.hops}[/]"
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
                key=device.identity_hash,
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


class StyreneFleetTable(DataTable[str]):
    """Styrene fleet node listing with version, capabilities, and hop info.

    Shows only STYRENE_NODE devices, deduplicated by identity hash
    (prefers the entry with the most recent announce).
    """

    COLUMN_KEYS = ("name", "version", "caps", "hops", "via", "status", "last_announce")

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._all_devices: list[MeshDevice] = []
        self._filter_text: str = ""
        self._sort_column: str = "last_announce"
        self._sort_reverse: bool = True
        self._hide_lost: bool = True
        self._hide_stale: bool = False

    @property
    def device_count(self) -> int:
        return len(self._all_devices)

    @property
    def status_counts(self) -> dict[str, int]:
        counts = {"active": 0, "stale": 0, "lost": 0}
        for d in self._all_devices:
            counts[d.status.value] = counts.get(d.status.value, 0) + 1
        return counts

    def toggle_hide_lost(self) -> bool:
        self._hide_lost = not self._hide_lost
        self._rebuild_table()
        return self._hide_lost

    def toggle_hide_stale(self) -> bool:
        self._hide_stale = not self._hide_stale
        self._rebuild_table()
        return self._hide_stale

    @property
    def hiding_lost(self) -> bool:
        return self._hide_lost

    @property
    def hiding_stale(self) -> bool:
        return self._hide_stale

    def on_mount(self) -> None:
        self.add_columns(
            ("name", "NAME"),
            ("version", "VERSION"),
            ("caps", "CAPABILITIES"),
            ("hops", "HOPS"),
            ("via", "VIA"),
            ("status", "STATUS"),
            ("last_announce", "LAST ANNOUNCE"),
        )
        self.cursor_type = "row"

    def load_from_devices(self, devices: list[MeshDevice]) -> None:
        """Accept full device list and rebuild from canonical node projection."""
        from styrened.ui_state.nodes import NodeCatalogInputs, build_node_catalog

        styrene = [d for d in devices if d.device_type == DeviceType.STYRENE_NODE]
        inputs = NodeCatalogInputs(devices=tuple(styrene))
        catalog = build_node_catalog(inputs)
        rows = build_styrene_fleet_projection(catalog=catalog, devices=styrene)
        self._all_devices = [row.device for row in rows]
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        devices = self._all_devices

        # Status filters
        if self._hide_lost:
            devices = [d for d in devices if d.status != NodeStatus.LOST]
        if self._hide_stale:
            devices = [d for d in devices if d.status != NodeStatus.STALE]

        if self._filter_text:
            query = self._filter_text.lower()
            devices = [
                d for d in devices
                if query in d.name.lower()
                or query in (d.version or "").lower()
                or query in d.destination_hash.lower()
                or query in " ".join(d.capabilities or []).lower()
            ]

        devices = self._sort_devices(devices)

        # Track selection
        selected_key: str | None = None
        if self.cursor_row is not None and self.row_count > 0:
            try:
                cell_key = self.coordinate_to_cell_key(Coordinate(self.cursor_row, 0))
                if cell_key and cell_key.row_key:
                    selected_key = str(cell_key.row_key.value)
            except Exception:
                pass

        self.clear()

        if not devices:
            cascade = get_color_cascade()
            msg = f"No matches for '{self._filter_text}'" if self._filter_text else "No Styrene nodes discovered"
            self.add_row(f"[{cascade.dim}]{msg}[/]", "", "", "", "", "", "")
            self._post_count_update(0, len(self._all_devices))
            return

        cascade = get_color_cascade()

        for device in devices:
            # Status
            status_colors = {
                NodeStatus.ACTIVE: cascade.medium,
                NodeStatus.STALE: cascade.dim,
                NodeStatus.LOST: cascade.dim,
            }
            status_color = status_colors.get(device.status, cascade.medium)
            status_icon = {
                NodeStatus.ACTIVE: "●",
                NodeStatus.STALE: "◐",
                NodeStatus.LOST: "○",
            }.get(device.status, "?")
            status_text = f"[{status_color}]{status_icon} {device.status.value.upper()}[/]"

            # Name — bright for active
            if device.status == NodeStatus.ACTIVE:
                name_text = f"[{cascade.bright} bold]{device.name}[/]"
            else:
                name_text = f"[{cascade.medium}]{device.name}[/]"

            # Version
            ver = device.version or "—"
            version_text = f"[{cascade.medium}]{ver}[/]"

            # Capabilities — icons for key caps
            caps = device.capabilities or []
            cap_parts = []
            if "autoreply" in caps:
                cap_parts.append("📨")
            if "exec" in caps:
                cap_parts.append("⚡")
            if "rpc" in caps:
                cap_parts.append("🔌")
            if "transport" in caps:
                cap_parts.append("🔀")
            # Show any remaining caps as text
            known = {"autoreply", "exec", "rpc", "transport"}
            extras = [c for c in caps if c not in known]
            if extras:
                cap_parts.append(f"[{cascade.dim}]{','.join(extras)}[/]")
            caps_text = " ".join(cap_parts) if cap_parts else f"[{cascade.dim}]—[/]"

            # Hops
            if device.hops is not None:
                if device.hops == 0:
                    hops_text = f"[{cascade.medium}]direct[/]"
                else:
                    hops_text = f"[{cascade.dim}]{device.hops}[/]"
            else:
                hops_text = f"[{cascade.dim}]—[/]"

            # Via
            via_text = f"[{cascade.dim}]{device.discovered_via}[/]" if device.discovered_via else f"[{cascade.dim}]—[/]"

            # Last seen
            last_seen_text = device.last_seen_display
            if device.announce_count > 1:
                last_seen_text += f" ({device.announce_count})"

            self.add_row(
                name_text,
                version_text,
                caps_text,
                hops_text,
                via_text,
                status_text,
                last_seen_text,
                key=device.identity_hash,
            )

        # Restore selection
        if selected_key and self.row_count > 0:
            for row_idx in range(self.row_count):
                try:
                    cell_key = self.coordinate_to_cell_key(Coordinate(row_idx, 0))
                    if cell_key and cell_key.row_key and str(cell_key.row_key.value) == selected_key:
                        self.cursor_coordinate = Coordinate(row_idx, 0)
                        break
                except Exception:
                    pass

        self._post_count_update(len(devices), len(self._all_devices))

    def _post_count_update(self, visible: int, total: int) -> None:
        try:
            screen = self.screen
            if isinstance(screen, ExplorationScreen):
                screen.update_count(visible, total)
        except Exception:
            pass

    def _sort_devices(self, devices: list[MeshDevice]) -> list[MeshDevice]:
        key_funcs = {
            "name": lambda d: d.name.lower(),
            "version": lambda d: (d.version or "").lower(),
            "caps": lambda d: len(d.capabilities or []),
            "hops": lambda d: d.hops if d.hops is not None else 999,
            "via": lambda d: (d.discovered_via or "").lower(),
            "status": lambda d: d.status.value,
            "last_announce": lambda d: d.last_announce,
        }
        key_fn = key_funcs.get(self._sort_column, key_funcs["last_announce"])
        return sorted(devices, key=key_fn, reverse=self._sort_reverse)

    def set_filter(self, text: str) -> None:
        self._filter_text = text
        self._rebuild_table()

    def sort_by(self, column_key: str) -> None:
        if self._sort_column == column_key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column_key
            self._sort_reverse = column_key in ("last_announce", "status", "caps")
        self._rebuild_table()

    def refresh_data(self) -> None:
        """Standalone fallback refresh using cached discovery data."""
        try:
            live = getattr(self.screen, "_live_nodes_cache", [])
            self.load_from_devices(list(live))
        except Exception:
            pass


class ExplorationScreen(Screen[None]):
    """Canonical Nodes workspace for discovery and peer browsing.

    Categorized tabs:
    - Styrene: current Styrene nodes with version, capabilities, hops
    - LXMF: messaging destinations
    - Pages: NomadNet page services with inline browser
    - Infrastructure: propagation nodes, RNodes
    - Other: generic/unknown announces
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._refresh_timer: Timer | None = None
        self._node_refresh_worker = None
        self._stored_nodes_worker = None
        self._diagnostics_subscribed: bool = False

    CSS = """
    #exploration-container {
        height: 1fr;
        border: round $border;
        border-title-color: $primary;
        border-title-style: bold;
        border-title-align: left;
        background: $background;
        padding: 0 1;
    }

    #explore-search-bar {
        height: auto;
        max-height: 3;
        padding: 0 1;
        background: $background;
    }

    #explore-search-bar.hidden {
        display: none;
    }

    #explore-status-bar {
        height: 1;
        padding: 0 1;
        color: $panel;
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
        Binding("n", "go_home", "Home", show=True),
        Binding("h", "toggle_hide_lost", "Hide Lost"),
        Binding("H", "toggle_hide_stale", "Hide Stale", key_display="shift+h"),
        Binding("slash", "show_search", "Search", key_display="/", priority=True),

    ]

    # Debounce settings for discovery callbacks
    _last_discovery_refresh: float = 0.0
    _discovery_debounce_seconds: float = 2.0

    def _start_node_refresh(self):
        """Start or replace the live node refresh worker."""
        self._node_refresh_worker = self.run_worker(
            self._async_load_all_nodes(),
            group="node-discovery",
            exclusive=True,
        )
        return self._node_refresh_worker

    def _start_stored_node_load(self):
        """Start or replace the deferred stored-node hydration worker."""
        self._stored_nodes_worker = self.run_worker(
            self._async_load_stored_nodes(),
            group="stored-nodes",
            exclusive=True,
        )
        return self._stored_nodes_worker

    def on_mount(self) -> None:
        """Start device discovery and load initial data."""
        try:
            self.query_one("#exploration-container", Container).border_title = "MESH NODES"
        except Exception:
            pass

        # Try IPC-based discovery first, fallback to direct discovery
        app = self.app
        bridge = getattr(getattr(app, "services", None), "bridge", None)
        if bridge is not None:
            # IPC-managed mode: use periodic bridge calls instead of direct discovery
            self._refresh_timer = self.set_interval(15.0, self._refresh_via_bridge)
            # Fetch initial data via IPC
            self._start_node_refresh()
        else:
            # Legacy/non-managed mode: use direct discovery
            start_discovery(callback=self._on_device_discovered)
            self._refresh_timer = self.set_interval(15.0, self._refresh_announce_tables)
            # Fetch stored nodes via IPC (async), then refresh tables
            self._start_stored_node_load()
            # Initial load with live-only (stored nodes arrive async)
            self._refresh_announce_tables()
        # Focus active table after TabbedContent is ready
        self.call_later(self._focus_active_table)

    def on_screen_suspend(self, event: events.ScreenSuspend) -> None:
        """Pause periodic refresh while Nodes is not the active workspace."""
        if self._refresh_timer is not None:
            self._refresh_timer.pause()
        if self._node_refresh_worker is not None:
            self._node_refresh_worker.cancel()
            self._node_refresh_worker = None
        if self._stored_nodes_worker is not None:
            self._stored_nodes_worker.cancel()
            self._stored_nodes_worker = None

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Resume periodic refresh and fetch fresh node data."""
        if self._refresh_timer is not None:
            self._refresh_timer.resume()
        self._start_node_refresh()

    def on_unmount(self) -> None:
        """Stop periodic refresh when the Nodes workspace is removed."""
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
            self._refresh_timer = None
        if self._node_refresh_worker is not None:
            self._node_refresh_worker.cancel()
            self._node_refresh_worker = None
        if self._stored_nodes_worker is not None:
            self._stored_nodes_worker.cancel()
            self._stored_nodes_worker = None

    async def _async_load_stored_nodes(self) -> None:
        """Historical node hydration is deferred during Nodes migration.

        Exploration is currently kept live-biased so the in-progress Nodes
        workspace reflects current discovery rather than daemon history.
        """
        self._stored_nodes_cache = []
    
    async def _async_load_all_nodes(self) -> None:
        """Refresh nodes — prefer IPC bridge, fallback to direct discovery."""
        try:
            bridge = getattr(getattr(self.app, "services", None), "bridge", None)
            if bridge is not None:
                from styrened.tui.utils import device_info_to_mesh

                device_infos = await bridge.get_devices()
                devices = [device_info_to_mesh(d) for d in device_infos]
                self._stored_nodes_cache = []
                self._live_nodes_cache = devices
            else:
                live_nodes = discover_devices()
                self._stored_nodes_cache = []
                self._live_nodes_cache = live_nodes
            self._refresh_announce_tables()
        except Exception:
            pass
    
    def _refresh_via_bridge(self) -> None:
        """Periodic refresh using IPC bridge data."""
        self._start_node_refresh()

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
            yield Static("", id="explore-status-bar")
            with TabbedContent(id="explore-tabs"):
                with TabPane("Styrene", id="tab-styrene"):
                    yield StyreneFleetTable(
                        id="table-styrene",
                        classes="explore-tab-table",
                    )
                with TabPane("LXMF", id="tab-lxmf"):
                    yield ReticumAnnounceTable(
                        id="table-lxmf",
                        device_types=_LXMF_TYPES,
                        classes="explore-tab-table",
                    )
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
                with TabPane("Diagnostics", id="tab-diagnostics"):
                    yield ActivityFeedWidget(id="explore-activity-feed")
            yield Static("", id="explore-count")
        yield Footer()

    def _get_all_tables(self) -> list[DataTable]:
        """Get all announce tables across tabs (both ReticumAnnounceTable and StyreneFleetTable)."""
        table_ids = ["#table-styrene", "#table-lxmf", "#table-infra", "#table-other"]
        tables = []
        for tid in table_ids:
            try:
                tables.append(self.query_one(tid, DataTable))
            except Exception:
                pass
        return tables

    def _get_active_table(self) -> DataTable | None:
        """Get the announce table in the currently active tab."""
        try:
            tabs = self.query_one("#explore-tabs", TabbedContent)
            active_id = tabs.active
            table_map = {
                "tab-styrene": "#table-styrene",
                "tab-lxmf": "#table-lxmf",
                "tab-infra": "#table-infra",
                "tab-other": "#table-other",
            }
            table_id = table_map.get(active_id)
            if table_id:
                return self.query_one(table_id, DataTable)
        except Exception:
            pass
        return None

    def _load_all_devices(self) -> tuple[list[MeshDevice], list[MeshDevice]]:
        """Load and deduplicate all devices, returning (exploration, all_merged).

        Uses cached stored nodes from the last async IPC fetch (populated
        by ``_async_load_stored_nodes``).  Falls back to live-only when
        the cache is empty.

        Returns:
            Tuple of (exploration devices with LXMF shadows filtered, all merged devices).
        """
        # Exploration/Nodes is currently live-biased; broader stored history is
        # being pushed toward canonical node browsing flows incrementally.
        live_nodes = getattr(self, "_live_nodes_cache", [])

        all_merged = list({n.destination_hash: n for n in live_nodes}.values())

        styrene_identities = {
            d.identity_hash
            for d in all_merged
            if d.device_type == DeviceType.STYRENE_NODE
        }

        exploration = [
            d for d in all_merged
            if d.device_type in _EXPLORATION_TYPES
            and d.identity_hash not in styrene_identities
        ]

        return exploration, all_merged

    def _refresh_announce_tables(self) -> None:
        """Load all devices once and distribute to category tables."""
        exploration_devices, all_devices = self._load_all_devices()

        # Feed Styrene table from all devices (it filters internally)
        try:
            styrene_table = self.query_one("#table-styrene", StyreneFleetTable)
            styrene_table.load_from_devices(all_devices)
        except Exception:
            pass

        # Feed exploration tables from filtered list
        for table in self._get_all_tables():
            if isinstance(table, ReticumAnnounceTable):
                table.load_from_devices(exploration_devices)

        self._update_tab_labels()
        self._update_status_bar()

    def _update_tab_labels(self) -> None:
        """Update tab labels with device counts."""
        label_map = {
            "#table-styrene": ("tab-styrene", "Styrene"),
            "#table-lxmf": ("tab-lxmf", "LXMF"),
            "#table-infra": ("tab-infra", "Infra"),
            "#table-other": ("tab-other", "Other"),
        }
        try:
            tabs_widget = self.query_one("#explore-tabs", TabbedContent)
            for table_id, (pane_id, base_label) in label_map.items():
                try:
                    table = self.query_one(table_id, DataTable)
                    total = getattr(table, "device_count", 0)
                    visible = table.row_count
                    tab = tabs_widget.get_tab(pane_id)
                    if total > 0:
                        if visible < total:
                            tab.label = f"{base_label} ({visible}/{total})"
                        else:
                            tab.label = f"{base_label} ({total})"
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
        # Start activity subscription when Diagnostics tab is first activated
        if getattr(event.tab, "id", None) == "tab-diagnostics":
            if not self._diagnostics_subscribed:
                self._diagnostics_subscribed = True
                self.run_worker(self._subscribe_activity(), exclusive=False)
        self._update_status_bar()

    def _find_device_by_identity(self, identity: str) -> MeshDevice | None:
        """Look up a MeshDevice from the active table's device list."""
        table = self._get_active_table()
        if table and hasattr(table, "_all_devices"):
            for d in table._all_devices:
                if d.identity_hash == identity:
                    return d
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle DataTable enter key — navigate to device detail screen."""
        if event.row_key and event.row_key.value and event.row_key.value != "-":
            device_identity = str(event.row_key.value)
            device = self._find_device_by_identity(device_identity)
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

            self.app.push_screen(MeshDeviceDetailScreen(
                device_identity=device_identity,
                device=device,
                origin_workspace=WorkspaceId.NODES,
            ))

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Handle column header click — sort by that column."""
        column_key = str(event.column_key.value) if event.column_key else None
        if column_key:
            table = event.data_table
            if isinstance(table, (ReticumAnnounceTable, StyreneFleetTable)):
                if column_key in table.COLUMN_KEYS:
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

    def action_go_home(self) -> None:
        """Return to the dashboard."""
        self.app.switch_screen("dashboard")

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
            self.app.switch_screen("dashboard")

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
            device = self._find_device_by_identity(device_identity)
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

            self.app.push_screen(
                MeshDeviceDetailScreen(
                    device_identity=device_identity,
                    device=device,
                    origin_workspace=WorkspaceId.NODES,
                )
            )

    def action_open_chat(self) -> None:
        """Open chat tab directly for the selected device."""
        device_identity = self._get_selected_identity()
        if device_identity:
            device = self._find_device_by_identity(device_identity)
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

            self.app.push_screen(
                MeshDeviceDetailScreen(
                    device_identity=device_identity,
                    initial_tab="chat",
                    device=device,
                    origin_workspace=WorkspaceId.NODES,
                )
            )

    def action_toggle_hide_lost(self) -> None:
        """Toggle visibility of LOST nodes."""
        table = self._get_active_table()
        if table and hasattr(table, "toggle_hide_lost"):
            now_hiding = table.toggle_hide_lost()
            verb = "hidden" if now_hiding else "shown"
            self.notify(f"Lost nodes {verb}", severity="information")
            self._update_status_bar()
            self._update_tab_labels()

    def action_toggle_hide_stale(self) -> None:
        """Toggle visibility of STALE nodes."""
        table = self._get_active_table()
        if table and hasattr(table, "toggle_hide_stale"):
            now_hiding = table.toggle_hide_stale()
            verb = "hidden" if now_hiding else "shown"
            self.notify(f"Stale nodes {verb}", severity="information")
            self._update_status_bar()
            self._update_tab_labels()

    def _update_status_bar(self) -> None:
        """Update the status filter bar with counts and filter state."""
        table = self._get_active_table()
        if not table or not hasattr(table, "status_counts"):
            return

        cascade = get_color_cascade()
        counts = table.status_counts
        hiding_lost = getattr(table, "hiding_lost", False)
        hiding_stale = getattr(table, "hiding_stale", False)

        parts = []
        # Active — always bright
        n_active = counts.get("active", 0)
        parts.append(f"[{cascade.bright}]● {n_active} active[/]")

        # Stale
        n_stale = counts.get("stale", 0)
        if hiding_stale:
            parts.append(f"[{cascade.dim}]◐ {n_stale} stale (hidden)[/]")
        else:
            parts.append(f"[{cascade.medium}]◐ {n_stale} stale[/]")

        # Lost
        n_lost = counts.get("lost", 0)
        if hiding_lost:
            parts.append(f"[{cascade.dim}]○ {n_lost} lost (hidden)[/]")
        else:
            parts.append(f"[{cascade.medium}]○ {n_lost} lost[/]")

        try:
            bar = self.query_one("#explore-status-bar", Static)
            bar.update("  ".join(parts))
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Refresh all data on the exploration screen."""
        self.notify("Refreshing...", title="Refresh")
        self._refresh_announce_tables()

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge via typed services protocol."""
        try:
            return self.app.services.bridge  # type: ignore[union-attr,attr-defined]
        except Exception:
            return None

    async def _subscribe_activity(self) -> None:
        """Subscribe to activity events via IPC and push into ActivityFeedWidget."""
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            await bridge.subscribe_activity()
            async for event_type, event in bridge.iter_events(IPCMessageType.EVENT_ACTIVITY):
                if event_type != IPCMessageType.EVENT_ACTIVITY:
                    continue
                try:
                    activity_widget = self.query_one("#explore-activity-feed", ActivityFeedWidget)
                    activity_widget.add_event(event.get("event_type", "unknown"), event)
                except Exception:
                    pass
        except Exception:
            pass
