"""Dashboard Screen - Main fleet overview."""

from typing import TYPE_CHECKING, ClassVar

from sqlalchemy.orm import Session

# Import events for screen lifecycle
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.models.messages import Message
from styrened.tui.services.reticulum import discover_devices, start_discovery
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade
from styrened.tui.widgets.node_info_panel import NodeInfoPanel

if TYPE_CHECKING:
    from styrened.tui.app import StyreneApp


class MeshDeviceTable(DataTable[str]):
    """Mesh device listing table - shows discovered devices."""

    def on_mount(self) -> None:
        self.add_columns("NAME", "TYPE", "IDENTITY", "STATUS", "UNREAD", "LAST ANNOUNCE")
        self.cursor_type = "row"
        self._load_data()

    def _get_unread_counts(self) -> dict[str, int]:
        """Get unread message counts per device identity.

        Returns:
            Dictionary mapping device identity to unread count.
        """
        unread_counts: dict[str, int] = {}

        # Get app reference for database access
        try:
            app: StyreneApp = self.app  # type: ignore[assignment]
            if app.db_engine is None or not app.local_identity_hash:
                return unread_counts
        except Exception:
            return unread_counts

        # Query unread messages (status="pending" and destination is local)
        with Session(app.db_engine) as session:
            messages = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    Message.status == "pending",
                    Message.destination_hash == app.local_identity_hash,
                )
                .all()
            )

            # Count by source (the sender's identity)
            for msg in messages:
                source = msg.source_hash
                unread_counts[source] = unread_counts.get(source, 0) + 1

        return unread_counts

    def _load_data(self) -> None:
        """Load device data from mesh discovery.

        Uses incremental updates to preserve cursor selection:
        1. Track current selection before update
        2. Build new row data without clearing
        3. Update existing rows, add new ones, remove stale ones
        4. Restore cursor position
        """
        # Load historical data from NodeStore first
        try:
            from styrened.services.node_store import get_node_store

            stored_nodes = get_node_store().get_styrene_nodes()
        except Exception:
            stored_nodes = []

        # Get live discovered devices
        live_nodes = discover_devices()

        # Merge historical and live data (live takes precedence for duplicates)
        all_devices_dict = {n.destination_hash: n for n in stored_nodes}
        all_devices_dict.update({n.destination_hash: n for n in live_nodes})

        # Filter to ONLY Styrene mesh devices
        # All other device types (RNODE, GENERIC, UNKNOWN) belong in the Exploration screen
        devices = [
            d
            for d in all_devices_dict.values()
            if d.device_type == DeviceType.STYRENE_NODE
        ]

        # Get unread message counts
        unread_counts = self._get_unread_counts()

        # Track current selection to restore after update
        selected_key: str | None = None
        if self.cursor_row is not None and self.row_count > 0:
            try:
                cell_key = self.coordinate_to_cell_key(Coordinate(self.cursor_row, 0))
                if cell_key and cell_key.row_key:
                    selected_key = str(cell_key.row_key.value)
            except Exception:
                pass

        # Clear and rebuild (simpler than incremental for now, but preserves selection)
        self.clear()

        if not devices:
            # Add a message row if no Styrene devices discovered
            cascade = get_color_cascade()
            self.add_row(
                "-",
                "-",
                "-",
                f"[{cascade.dim}]No Styrene nodes discovered[/]",
                "-",
                "-",
            )
            return

        # Sort by last announce (most recent first)
        devices_sorted = sorted(devices, key=lambda d: d.last_announce, reverse=True)

        # Get cascade for dynamic theming
        cascade = get_color_cascade()

        for device in devices_sorted:
            # Device type display - use cascade colors
            # bright for important (styrene), medium for normal, dim for generic
            type_icons = {
                DeviceType.STYRENE_NODE: f"[{cascade.bright}]STYRENE[/]",
                DeviceType.RNODE: f"[{cascade.medium}]RNODE[/]",
                DeviceType.GENERIC: f"[{cascade.dim}]GENERIC[/]",
                DeviceType.UNKNOWN: f"[{cascade.dim}]UNKNOWN[/]",
            }
            type_text = type_icons.get(device.device_type, f"[{cascade.dim}]?[/]")

            # Status using cascade colors
            # Active = medium, Stale = dim, Lost = dim (symbols differentiate)
            status_colors = {
                NodeStatus.ACTIVE: cascade.medium,
                NodeStatus.STALE: cascade.dim,
                NodeStatus.LOST: cascade.dim,
            }
            status_color = status_colors.get(device.status, cascade.medium)
            status_text = f"[{status_color}]{device.status.value.upper()}[/]"

            # Identity with more characters for uniqueness (first 16 chars instead of 8)
            identity_text = device.destination_hash[:16] + "..."

            # Name styling based on type - use cascade colors
            if device.is_styrene_node:
                name_text = f"[{cascade.bright} bold]{device.name}[/]"
            elif device.is_rnode:
                name_text = f"[{cascade.medium}]{device.name}[/]"
            else:
                name_text = f"[{cascade.dim}]{device.name}[/]"

            # Unread message count
            unread = unread_counts.get(device.identity, 0)
            unread_text = (
                f"[{cascade.bright} bold]{unread}[/]" if unread > 0 else f"[{cascade.dim}]-[/]"
            )

            # Show announce count in last seen if > 1
            last_seen_text = device.last_seen_display
            if device.announce_count > 1:
                last_seen_text += f" ({device.announce_count})"

            self.add_row(
                name_text,
                type_text,
                identity_text,
                status_text,
                unread_text,
                last_seen_text,
                key=device.identity,
            )

        # Restore cursor selection if possible
        if selected_key and self.row_count > 0:
            # Find the row with the previously selected key
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

    def refresh_data(self) -> None:
        """Refresh device data."""
        self._load_data()


class DashboardScreen(Screen[None]):
    """Main dashboard screen showing fleet overview."""

    # Screen-specific bindings - see docs/KEYMAP.md
    # Note: 'p' for Provision is inherited from App, listed here for footer display
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "select_device", "Select"),
        Binding("s", "request_status", "Status"),
        Binding("c", "open_chat", "Chat"),
        Binding("r", "refresh", "Refresh"),
        Binding("e", "open_exploration", "Explore", show=True),
    ]

    # Debounce settings for discovery callbacks
    _last_discovery_refresh: float = 0.0
    _discovery_debounce_seconds: float = 2.0  # Min time between discovery-triggered refreshes

    def on_mount(self) -> None:
        """Start device discovery when dashboard mounts."""
        # Start announce listener for device discovery
        start_discovery(callback=self._on_device_discovered)

        # Set up periodic refresh of device table (15s is enough for status updates)
        # Discovery callbacks handle new devices immediately (with debounce)
        self.set_interval(15.0, self._refresh_device_table)

        # Set up periodic hub connection retry
        self.set_interval(30.0, self._retry_hub_connection)

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Handle screen resume - refresh themed panels.

        When returning from another screen (like settings), the theme may have
        changed. Refresh all panels that use Rich markup with cascade colors.
        """
        # Refresh HighlightedPanel borders
        for panel in self.query(HighlightedPanel):
            panel.refresh_theme()

        # Refresh content panels that use cascade colors in Rich markup
        node_info_panel = self.query_one(NodeInfoPanel)
        node_info_panel.refresh_data()

        for table in self.query(MeshDeviceTable):
            table.refresh_data()

    def _retry_hub_connection(self) -> None:
        """Periodically retry hub connection if not connected."""
        try:
            from styrened.services.hub_connection import get_hub_connection
            from styrened.tui.services.config import load_config

            config = load_config()
            if config.reticulum.hub_enabled and config.reticulum.hub_address:
                hub_connection = get_hub_connection()
                hub_connection.set_announce_interval(config.reticulum.hub_announce_interval)

                if not hub_connection.is_connected:
                    hub_connection.retry_connection()
        except Exception:
            pass

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
        """Add discovered device to mesh (runs on main thread).

        Debounces refresh to avoid constant table rebuilds when many
        announces arrive in quick succession.

        Args:
            device: MeshDevice object.
        """
        import time

        # Notify for important device types (always show these)
        if device.is_styrene_node:
            self.notify(
                f"Styrene node: {device.name}",
                severity="information",
            )
        elif device.is_rnode:
            self.notify(
                f"RNode: {device.name}",
                severity="information",
            )

        # Debounce table refresh to avoid constant rebuilds
        now = time.time()
        if now - self._last_discovery_refresh >= self._discovery_debounce_seconds:
            self._last_discovery_refresh = now
            self._refresh_device_table()

    def _refresh_device_table(self) -> None:
        """Refresh the device table with current mesh discoveries."""
        try:
            table_widget = self.query_one("#mesh-device-table", MeshDeviceTable)
            table_widget.refresh_data()
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="dashboard-container"):
            yield HighlightedPanel(
                NodeInfoPanel(id="node-info-panel-widget"),
                title="NODE INFO",
                id="node-info-panel",
            )
            yield HighlightedPanel(
                MeshDeviceTable(id="mesh-device-table"),
                title="MESH DEVICES",
                id="mesh-devices-panel",
            )
        yield Footer()

    def action_select_device(self) -> None:
        """Handle device selection - navigate to device detail screen."""
        table = self.query_one("#mesh-device-table", DataTable)
        if table.cursor_row is not None:
            # Get device identity from the row key
            cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
            if cell_key and cell_key.row_key and cell_key.row_key.value != "-":
                device_identity = str(cell_key.row_key.value)
                # Navigate to mesh device detail screen
                from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

                self.app.push_screen(MeshDeviceDetailScreen(device_identity=device_identity))

    async def action_request_status(self) -> None:
        """Request status from selected mesh device via RPC."""
        table = self.query_one("#mesh-device-table", DataTable)
        if table.cursor_row is None:
            self.notify("No device selected", severity="warning")
            return

        # Get device identity from row key
        cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
        if not cell_key or not cell_key.row_key or cell_key.row_key.value == "-":
            return

        device_identity = str(cell_key.row_key.value)

        # Show requesting notification
        self.notify("Requesting status...", title="Status")

        try:
            # Import RPC types
            from styrened.rpc import RPCTimeoutError, RPCTransportError

            # Make RPC call
            app: StyreneApp = self.app  # type: ignore[assignment]
            response = await app.rpc_client.call_status(
                device_identity,
                timeout=30.0,
            )

            # Navigate to device detail with status
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

            self.app.push_screen(
                MeshDeviceDetailScreen(
                    device_identity=device_identity,
                    initial_status=response,
                )
            )

        except RPCTimeoutError:
            self.notify(
                "Device did not respond - it may be offline or unreachable",
                title="Timeout",
                severity="warning",
                timeout=5,
            )
        except RPCTransportError as e:
            self.notify(
                f"Failed to send message: {e}",
                title="Transport Error",
                severity="error",
                timeout=5,
            )
        except Exception as e:
            self.notify(
                f"Error: {e}",
                title="Error",
                severity="error",
                timeout=5,
            )

    def action_open_chat(self) -> None:
        """Open chat conversation with selected device."""
        table = self.query_one("#mesh-device-table", DataTable)
        if table.cursor_row is None:
            self.notify("No device selected", severity="warning")
            return

        # Get device identity from row key
        cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
        if not cell_key or not cell_key.row_key or cell_key.row_key.value == "-":
            self.notify("Invalid device selection", severity="warning")
            return

        device_identity = str(cell_key.row_key.value)

        # Get app reference for chat protocol access
        app: StyreneApp = self.app  # type: ignore[assignment]

        if app.chat_protocol is None:
            self.notify("Chat not available (no protocol initialized)", severity="warning")
            return

        if not app.local_identity_hash:
            self.notify("Chat not available (no local identity)", severity="warning")
            return

        # Push conversation screen with callback to refresh on return
        from styrened.tui.screens.conversation import ConversationScreen

        self.app.push_screen(
            ConversationScreen(
                destination_hash=device_identity,
                local_identity_hash=app.local_identity_hash,
                chat_protocol=app.chat_protocol,
            ),
            callback=self._on_chat_return,
        )

    def _on_chat_return(self, result: None) -> None:
        """Callback when returning from chat screen - refresh unread counts."""
        self._refresh_device_table()

    def action_open_exploration(self) -> None:
        """Open exploration screen for all Reticulum announces."""
        from styrened.tui.screens.exploration import ExplorationScreen

        self.app.push_screen(ExplorationScreen())

    def action_refresh(self) -> None:
        """Refresh all data on the dashboard."""
        self.notify("Refreshing...", title="Refresh")

        # Refresh node info panel
        try:
            node_info_widget = self.query_one("#node-info-panel-widget", NodeInfoPanel)
            node_info_widget.refresh_data()
        except Exception:
            pass

        # Refresh device table
        try:
            table_widget = self.query_one("#mesh-device-table", MeshDeviceTable)
            table_widget.refresh_data()
        except Exception:
            pass

