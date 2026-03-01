"""Dashboard Screen - Main fleet overview."""

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy.orm import Session

# Import events for screen lifecycle
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Tree
from textual.widgets.tree import TreeNode

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.models.messages import Message
from styrened.tui.services.reticulum import discover_devices, start_discovery
from styrened.tui.widgets.activity_feed import ActivityFeedWidget
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade
from styrened.tui.widgets.node_info_panel import NodeInfoPanel

if TYPE_CHECKING:
    from styrened.tui.app import StyreneApp


class MeshDeviceTree(Tree[str]):
    """Mesh device tree — groups discovered devices by receiving interface."""

    DEFAULT_CSS = """
    MeshDeviceTree {
        height: 1fr;
        min-height: 5;
        background: transparent;
        scrollbar-background: transparent;
        scrollbar-color: $border;
        scrollbar-size-vertical: 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("Mesh Devices", **kwargs)
        self.show_root = False
        self.guide_depth = 3

    def on_mount(self) -> None:
        self._load_data()

    def _get_unread_counts(self) -> dict[str, int]:
        """Get unread message counts per device identity."""
        unread_counts: dict[str, int] = {}
        try:
            app: StyreneApp = self.app  # type: ignore[assignment]
            if app.db_engine is None or not app.local_identity_hash:
                return unread_counts
        except Exception:
            return unread_counts

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
            for msg in messages:
                source = msg.source_hash
                unread_counts[source] = unread_counts.get(source, 0) + 1

        return unread_counts

    def _load_data(self) -> None:
        """Load device data and rebuild tree grouped by interface."""
        # Load historical + live data
        try:
            from styrened.services.node_store import get_node_store
            stored_nodes = get_node_store().get_styrene_nodes()
        except Exception:
            stored_nodes = []

        live_nodes = discover_devices()

        all_devices_dict = {n.destination_hash: n for n in stored_nodes}
        all_devices_dict.update({n.destination_hash: n for n in live_nodes})

        # Filter to Styrene nodes only
        devices = [
            d for d in all_devices_dict.values()
            if d.device_type == DeviceType.STYRENE_NODE
        ]

        from styrened.services.reticulum import _deduplicate_by_identity
        devices = _deduplicate_by_identity(devices)

        unread_counts = self._get_unread_counts()
        cascade = get_color_cascade()

        # Track selected node to restore after rebuild
        selected_identity: str | None = None
        if self.cursor_node and self.cursor_node.data:
            selected_identity = self.cursor_node.data

        # Clear and rebuild
        self.clear()

        if not devices:
            self.root.add_leaf(
                f"[{cascade.dim}]No Styrene nodes discovered[/]",
                data=None,
            )
            return

        # Group devices by discovered_via interface
        groups: dict[str, list[MeshDevice]] = {}
        for device in devices:
            key = device.discovered_via or "_direct"
            groups.setdefault(key, []).append(device)

        # Sort groups: named interfaces first (alpha), _direct last
        sorted_keys = sorted(
            groups.keys(),
            key=lambda k: (k == "_direct", k.lower()),
        )

        for group_key in sorted_keys:
            group_devices = sorted(
                groups[group_key],
                key=lambda d: d.last_announce,
                reverse=True,
            )

            # Interface header node
            if group_key == "_direct":
                label = f"[{cascade.dim}]Direct / Unknown[/]"
            else:
                label = f"[{cascade.medium} bold]{group_key}[/]"

            branch = self.root.add(label, data=None, expand=True)

            for device in group_devices:
                line = self._format_device_line(device, cascade, unread_counts)
                branch.add_leaf(line, data=device.identity)

        # Restore selection
        if selected_identity:
            self._select_by_identity(selected_identity)

    def _format_device_line(
        self,
        device: MeshDevice,
        cascade: Any,
        unread_counts: dict[str, int],
    ) -> str:
        """Format a single device as a rich-text tree leaf label."""
        # Status indicator
        status_syms = {
            NodeStatus.ACTIVE: f"[{cascade.bright}]●[/]",
            NodeStatus.STALE: f"[{cascade.dim}]◐[/]",
            NodeStatus.LOST: f"[{cascade.dim}]○[/]",
        }
        status = status_syms.get(device.status, f"[{cascade.dim}]?[/]")

        # Name
        name = f"[{cascade.bright} bold]{device.name}[/]"

        # Unread badge
        unread = unread_counts.get(device.identity, 0)
        unread_text = f" [{cascade.bright} bold]✉{unread}[/]" if unread > 0 else ""

        # Last seen (compact)
        seen = device.last_seen_display
        if device.announce_count > 1:
            seen += f"×{device.announce_count}"
        last_seen = f"[{cascade.dim}]{seen}[/]"

        return f"{status} {name}  {last_seen}{unread_text}"

    def _select_by_identity(self, identity: str) -> None:
        """Move cursor to the node matching the given identity."""
        for node in self._tree_walk(self.root):
            if node.data == identity:
                self.select_node(node)
                return

    def _tree_walk(self, node: TreeNode[str]) -> list[TreeNode[str]]:
        """Recursively walk all tree nodes."""
        result = [node]
        for child in node.children:
            result.extend(self._tree_walk(child))
        return result

    def get_selected_identity(self) -> str | None:
        """Get the identity of the currently selected leaf node."""
        if self.cursor_node and self.cursor_node.data:
            return str(self.cursor_node.data)
        return None

    def refresh_data(self) -> None:
        """Refresh device data."""
        self._load_data()
        self._clear_line_cache()
        self.refresh(layout=True)


class DashboardScreen(Screen[None]):
    """Main dashboard screen showing fleet overview."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "select_device", "Details"),
        Binding("c", "open_chat", "Chat"),
        Binding("r", "refresh", "Refresh"),
        Binding("e", "open_exploration", "Explore", show=True),
    ]

    _last_discovery_refresh: float = 0.0
    _discovery_debounce_seconds: float = 2.0

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
        except Exception:
            return None

    def on_mount(self) -> None:
        """Start device discovery when dashboard mounts."""
        start_discovery(callback=self._on_device_discovered)
        self.set_interval(15.0, self._refresh_device_table)
        self.set_interval(30.0, self._retry_hub_connection)

        if self._ipc_bridge is not None:
            try:
                panel = self.query_one(NodeInfoPanel)
                panel.ipc_managed = True
                panel.daemon_connected = False
            except Exception:
                pass
            self.run_worker(self._fetch_daemon_status())
            self.run_worker(self._subscribe_activity())

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Handle screen resume - refresh themed panels."""
        for panel in self.query(HighlightedPanel):
            panel.refresh_theme()

        node_info_panel = self.query_one(NodeInfoPanel)
        node_info_panel.refresh_data()

        for tree in self.query(MeshDeviceTree):
            tree.refresh_data()

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status())

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
                    hub_connection.connect(config.reticulum.hub_address)
        except Exception:
            pass

    def _on_device_discovered(self, device: MeshDevice) -> None:
        """Handle newly discovered device - refresh table with debounce."""
        import time
        now = time.time()
        if now - self._last_discovery_refresh >= self._discovery_debounce_seconds:
            self._last_discovery_refresh = now
            self.call_from_thread(self._refresh_device_table)

    def _refresh_device_table(self) -> None:
        """Refresh the device tree."""
        try:
            tree_widget = self.query_one("#mesh-device-tree", MeshDeviceTree)
            tree_widget.refresh_data()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Tree refresh failed: {e}", exc_info=True)

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status())

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="dashboard-container"):
            yield HighlightedPanel(
                NodeInfoPanel(id="node-info-panel-widget"),
                title="NODE INFO",
                id="node-info-panel",
            )
            yield HighlightedPanel(
                MeshDeviceTree(id="mesh-device-tree"),
                title="MESH DEVICES",
                id="mesh-devices-panel",
            )
            yield HighlightedPanel(
                ActivityFeedWidget(id="activity-feed-widget"),
                title="ACTIVITY",
                id="activity-feed-panel",
            )
        yield Footer()

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        """Handle tree node selection (enter key on a leaf)."""
        if event.node.data:
            device_identity = str(event.node.data)
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
            self.app.push_screen(MeshDeviceDetailScreen(device_identity=device_identity))

    def _get_selected_identity(self) -> str | None:
        """Get the identity of the currently selected tree node."""
        tree = self.query_one("#mesh-device-tree", MeshDeviceTree)
        return tree.get_selected_identity()

    def action_select_device(self) -> None:
        """Handle device selection."""
        device_identity = self._get_selected_identity()
        if device_identity:
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
            self.app.push_screen(MeshDeviceDetailScreen(device_identity=device_identity))

    def action_open_chat(self) -> None:
        """Open chat tab directly for the selected device."""
        device_identity = self._get_selected_identity()
        if device_identity:
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
            self.app.push_screen(
                MeshDeviceDetailScreen(device_identity=device_identity, initial_tab="chat")
            )

    def action_open_exploration(self) -> None:
        """Open exploration screen for all Reticulum announces."""
        from styrened.tui.screens.exploration import ExplorationScreen
        self.app.push_screen(ExplorationScreen())

    def action_refresh(self) -> None:
        """Refresh all data on the dashboard."""
        self._refresh_device_table()

        try:
            node_info = self.query_one(NodeInfoPanel)
            node_info.refresh_data()
        except Exception:
            pass

        try:
            activity = self.query_one(ActivityFeedWidget)
            activity.clear()
        except Exception:
            pass

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status())

    async def _fetch_daemon_status(self) -> None:
        """Fetch daemon status via IPC bridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            status = await bridge.get_status()
            try:
                panel = self.query_one(NodeInfoPanel)
                panel.daemon_connected = True
                if hasattr(status, "uptime"):
                    panel.daemon_uptime = status.uptime
            except Exception:
                pass
        except Exception:
            try:
                panel = self.query_one(NodeInfoPanel)
                panel.daemon_connected = False
            except Exception:
                pass

    async def _subscribe_activity(self) -> None:
        """Subscribe to activity events via IPC."""
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            async for event in bridge.subscribe_events():
                try:
                    activity_widget = self.query_one(ActivityFeedWidget)
                    activity_widget.add_event(
                        event.get("type", "unknown"),
                        event,
                    )
                except Exception:
                    pass
        except Exception:
            pass
