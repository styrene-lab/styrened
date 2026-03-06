"""Dashboard Screen - Main fleet overview."""

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy.orm import Session
from textual import events, work
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
    """Mesh device tree split into MY MESH (trusted) and OTHER (unknown) sections.

    MY MESH   — nodes whose identity_hash appears in the local RBAC roster
                with role ≥ PEER.  Grouped by discovered_via interface.
    OTHER     — all other styrene nodes.  Anonymous by default.  The dashboard
                auto-queries /meta on these to retrieve non-identifiable info
                (version, profile, capabilities) without asking them to identify.
    """

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
        # Cache: identity_hash → meta dict from /meta responses
        self._meta_cache: dict[str, dict[str, Any]] = {}
        # Cache: identity_hash → info dict from /info responses (may be None = declined)
        self._info_cache: dict[str, dict[str, Any] | None] = {}
        # Track pending meta queries to avoid duplicate in-flight requests
        self._meta_pending: set[str] = set()

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

    def _is_my_mesh(self, device: MeshDevice) -> bool:
        """Return True if this device is in the local RBAC roster with role ≥ PEER."""
        try:
            from styrened.models.rbac import Role
            from styrened.services.config import load_core_config
            config = load_core_config()
            if config.rbac is None:
                return False
            role = config.rbac.resolve_role(device.identity_hash)
            return role >= Role.PEER
        except Exception:
            return False

    def _load_data(self) -> None:
        """Load device data and rebuild tree into MY MESH / OTHER sections."""
        try:
            from styrened.services.node_store import get_node_store
            stored_nodes = get_node_store().get_styrene_nodes()
        except Exception:
            stored_nodes = []

        live_nodes = discover_devices()

        all_devices_dict = {n.destination_hash: n for n in stored_nodes}
        all_devices_dict.update({n.destination_hash: n for n in live_nodes})

        devices = [
            d for d in all_devices_dict.values()
            if d.device_type == DeviceType.STYRENE_NODE
        ]

        from styrened.services.reticulum import _deduplicate_by_identity
        devices = _deduplicate_by_identity(devices)

        unread_counts = self._get_unread_counts()
        cascade = get_color_cascade()

        # Restore cursor position
        selected_identity: str | None = None
        if self.cursor_node and self.cursor_node.data:
            selected_identity = self.cursor_node.data

        self.clear()

        if not devices:
            self.root.add_leaf(
                f"[{cascade.dim}]No Styrene nodes discovered[/]",
                data=None,
            )
            return

        # Split into my mesh vs other
        my_devices = [d for d in devices if self._is_my_mesh(d)]
        other_devices = [d for d in devices if not self._is_my_mesh(d)]

        # --- MY MESH section ---
        my_label = f"[{cascade.bright} bold]MY MESH[/]"
        my_branch = self.root.add(my_label, data=None, expand=True)

        if my_devices:
            # Sub-group by interface within MY MESH
            groups: dict[str, list[MeshDevice]] = {}
            for device in my_devices:
                key = device.discovered_via or "_direct"
                groups.setdefault(key, []).append(device)

            sorted_keys = sorted(groups.keys(), key=lambda k: (k == "_direct", k.lower()))
            for group_key in sorted_keys:
                group_devices = sorted(
                    groups[group_key], key=lambda d: d.last_announce, reverse=True
                )
                if group_key == "_direct":
                    iface_label = f"[{cascade.dim}]direct[/]"
                else:
                    iface_label = f"[{cascade.medium}]{group_key}[/]"
                iface_branch = my_branch.add(iface_label, data=None, expand=True)
                for device in group_devices:
                    line = self._format_my_mesh_line(device, cascade, unread_counts)
                    iface_branch.add_leaf(line, data=device.identity)
        else:
            my_branch.add_leaf(
                f"[{cascade.dim}]No trusted nodes — add nodes via Settings > Security[/]",
                data=None,
            )

        # --- OTHER STYRENE NODES section ---
        other_label = f"[{cascade.dim} bold]OTHER STYRENE NODES[/]"
        other_branch = self.root.add(other_label, data=None, expand=False)

        if other_devices:
            sorted_other = sorted(other_devices, key=lambda d: d.last_announce, reverse=True)
            for device in sorted_other:
                line = self._format_other_line(device, cascade)
                other_branch.add_leaf(line, data=device.identity)
            # Queue meta requests for any other nodes we haven't queried yet
            self._queue_meta_requests(other_devices)
        else:
            other_branch.add_leaf(
                f"[{cascade.dim}]No other nodes visible[/]",
                data=None,
            )

        if selected_identity:
            self._select_by_identity(selected_identity)

    def _format_my_mesh_line(
        self,
        device: MeshDevice,
        cascade: Any,
        unread_counts: dict[str, int],
    ) -> str:
        """Format a trusted mesh node — full detail with role badge."""
        from styrened.models.rbac import Role
        status_syms = {
            NodeStatus.ACTIVE: f"[{cascade.bright}]●[/]",
            NodeStatus.STALE: f"[{cascade.dim}]◐[/]",
            NodeStatus.LOST: f"[{cascade.dim}]○[/]",
        }
        status = status_syms.get(device.status, f"[{cascade.dim}]?[/]")
        name = f"[{cascade.bright} bold]{device.name}[/]"

        # Role badge
        role_badge = ""
        try:
            from styrened.services.config import load_core_config
            config = load_core_config()
            if config.rbac:
                role = config.rbac.resolve_role(device.identity_hash)
                if role >= Role.ADMIN:
                    role_badge = f" [{cascade.bright}][ADMIN][/]"
                elif role >= Role.OPERATOR:
                    role_badge = f" [{cascade.medium}][OP][/]"
                elif role >= Role.MONITOR:
                    role_badge = f" [{cascade.dim}][MON][/]"
        except Exception:
            pass

        unread = unread_counts.get(device.identity, 0)
        unread_text = f" [{cascade.bright} bold]✉{unread}[/]" if unread > 0 else ""

        seen = device.last_seen_display
        if device.announce_count > 1:
            seen += f" ×{device.announce_count}"
        last_seen = f"[{cascade.dim}]{seen}[/]"

        return f"{status} {name}{role_badge}  {last_seen}{unread_text}"

    def _format_other_line(self, device: MeshDevice, cascade: Any) -> str:
        """Format an unknown/foreign node — minimal, shows meta if available."""
        status_syms = {
            NodeStatus.ACTIVE: f"[{cascade.medium}]●[/]",
            NodeStatus.STALE: f"[{cascade.dim}]◐[/]",
            NodeStatus.LOST: f"[{cascade.dim}]○[/]",
        }
        status = status_syms.get(device.status, f"[{cascade.dim}]?[/]")

        # Check if we have meta (non-identifiable) or info (identifiable, opt-in)
        meta = self._meta_cache.get(device.identity_hash)
        info = self._info_cache.get(device.identity_hash)

        if info and info.get("name"):
            # Node voluntarily identified — show their name
            display_name = f"[{cascade.medium}]{info['name']}[/]"
        else:
            # Anonymous — show truncated identity hash
            short = device.identity_hash[:12] if device.identity_hash else "unknown"
            display_name = f"[{cascade.dim}]{short}…[/]"

        # Version/profile from meta
        meta_suffix = ""
        if meta:
            ver = meta.get("styrene_version", "")
            profile = meta.get("profile", "")
            if ver:
                meta_suffix = f" [{cascade.dim}]v{ver}"
                if profile:
                    meta_suffix += f" · {profile}"
                meta_suffix += "[/]"
        elif device.identity_hash in self._meta_pending:
            meta_suffix = f" [{cascade.dim}]…[/]"

        seen = device.last_seen_display
        last_seen = f"[{cascade.dim}]{seen}[/]"

        return f"{status} {display_name}{meta_suffix}  {last_seen}"

    def _queue_meta_requests(self, devices: list[MeshDevice]) -> None:
        """Fire background meta requests for unknown nodes not yet queried."""
        for device in devices:
            if (
                device.identity_hash
                and device.identity_hash not in self._meta_cache
                and device.identity_hash not in self._meta_pending
                and device.destination_hash  # need a link target
            ):
                self._meta_pending.add(device.identity_hash)
                self._fetch_meta(device.destination_hash, device.identity_hash)

    @work(thread=False, exclusive=False, group="meta-fetch")
    async def _fetch_meta(self, destination_hash: str, identity_hash: str) -> None:
        """Async worker: request /meta from an unknown node and update display."""
        try:
            app: StyreneApp = self.app  # type: ignore[assignment]
            bridge = app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
            if bridge is None:
                return
            meta = await bridge.datalink_meta(destination_hash)
            if meta:
                self._meta_cache[identity_hash] = meta
        except Exception:
            pass
        finally:
            self._meta_pending.discard(identity_hash)
        # Trigger a lightweight re-render of just this node's label
        self._refresh_other_labels()

    def _refresh_other_labels(self) -> None:
        """Re-render labels in the OTHER branch without full data reload."""
        try:
            cascade = get_color_cascade()
            # Walk tree looking for OTHER branch
            for node in self._tree_walk(self.root):
                if node.data is not None:
                    # It's a device leaf — re-format if it's an "other" node
                    identity = str(node.data)
                    if identity not in self._get_my_mesh_identities():
                        # Find the MeshDevice for this identity
                        device = self._device_by_identity(identity)
                        if device:
                            node.set_label(self._format_other_line(device, cascade))
        except Exception:
            pass

    def _get_my_mesh_identities(self) -> set[str]:
        """Get set of identity hashes in MY MESH (cached for label refresh)."""
        try:
            from styrened.models.rbac import Role
            from styrened.services.config import load_core_config
            config = load_core_config()
            if config.rbac is None:
                return set()
            return {
                ih for ih, entry in config.rbac.roster.items()
                if entry.role >= Role.PEER
            }
        except Exception:
            return set()

    def _device_by_identity(self, identity: str) -> MeshDevice | None:
        """Look up a MeshDevice by identity hash from live + stored nodes."""
        try:
            from styrened.services.node_store import get_node_store
            nodes = get_node_store().get_styrene_nodes()
            live = discover_devices()
            all_devices = {n.identity_hash: n for n in nodes}
            all_devices.update({n.identity_hash: n for n in live})
            return all_devices.get(identity)
        except Exception:
            return None

    def request_info_for_selected(self) -> str | None:
        """Fire an /info request for the currently selected OTHER node.

        Returns the identity_hash if a request was queued, None if not applicable.
        """
        if not self.cursor_node or not self.cursor_node.data:
            return None
        identity = str(self.cursor_node.data)
        # Only for other nodes (not already in my mesh)
        if identity in self._get_my_mesh_identities():
            return None
        device = self._device_by_identity(identity)
        if device and device.destination_hash:
            self._fetch_info(device.destination_hash, identity)
            return identity
        return None

    @work(thread=False, exclusive=False, group="info-fetch")
    async def _fetch_info(self, destination_hash: str, identity_hash: str) -> None:
        """Async worker: request /info from an unknown node and update display."""
        try:
            app: StyreneApp = self.app  # type: ignore[assignment]
            bridge = app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
            if bridge is None:
                return
            info = await bridge.datalink_info(destination_hash)
            # Store result whether it's a dict or None (None = declined)
            self._info_cache[identity_hash] = info
        except Exception:
            self._info_cache[identity_hash] = None
        self._refresh_other_labels()

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
        """Refresh device data (preserves meta/info caches)."""
        self._load_data()
        self.refresh(layout=True)


class DashboardScreen(Screen[None]):
    """Main dashboard screen showing fleet overview."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "select_device", "Details"),
        Binding("c", "open_chat", "Chat"),
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("e", "open_exploration", "Explore", show=True),
        Binding("i", "request_identity", "Request ID", show=False),
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
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")
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
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

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
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

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
        else:
            self.app.notify("Select a device in the mesh tree first.", severity="warning")

    def action_open_exploration(self) -> None:
        """Open exploration screen for all Reticulum announces."""
        from styrened.tui.screens.exploration import ExplorationScreen
        self.app.push_screen(ExplorationScreen())

    def action_request_identity(self) -> None:
        """Send an /info request to the selected OTHER node.

        The remote node may decline silently (default). This action only
        applies to nodes in the OTHER section — not MY MESH nodes.
        """
        try:
            tree = self.query_one("#mesh-device-tree", MeshDeviceTree)
            identity = tree.request_info_for_selected()
            if identity:
                self.notify("Identity request sent — node may decline.", severity="information")
            else:
                self.notify(
                    "Select a node in OTHER STYRENE NODES to request identity.",
                    severity="warning",
                )
        except Exception:
            pass

    def action_refresh(self) -> None:
        """Refresh all data on the dashboard and re-check for updates."""
        self._refresh_device_table()

        try:
            node_info = self.query_one(NodeInfoPanel)
            node_info.refresh_data()
        except Exception:
            pass

        self.notify("Refreshed")

        try:
            activity = self.query_one(ActivityFeedWidget)
            activity.clear()
        except Exception:
            pass

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

        self.app._check_for_updates()

    async def _fetch_daemon_status(self) -> None:
        """Fetch daemon status and comms data via IPC bridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            panel = self.query_one(NodeInfoPanel)
        except Exception:
            return

        try:
            status = await bridge.get_status()
            panel.daemon_connected = True
            if hasattr(status, "uptime"):
                panel.daemon_uptime = status.uptime
            if hasattr(status, "daemon_version") and status.daemon_version:
                panel.daemon_version = status.daemon_version
            if hasattr(status, "propagation_enabled"):
                panel.propagation_enabled = status.propagation_enabled
            if hasattr(status, "transport_enabled"):
                panel.transport_enabled = status.transport_enabled
            if hasattr(status, "active_links"):
                panel.active_links = status.active_links
            if hasattr(status, "styrene_node_count"):
                panel.styrene_mesh_count = status.styrene_node_count
            if hasattr(status, "interface_count"):
                panel.interface_count = status.interface_count
            if hasattr(status, "rns_initialized"):
                panel.rns_online = status.rns_initialized
        except Exception:
            panel.daemon_connected = False
            return

        import asyncio
        convs_task = asyncio.create_task(bridge.get_conversations())
        contacts_task = asyncio.create_task(bridge.get_contacts())
        auto_reply_task = asyncio.create_task(bridge.get_auto_reply())

        try:
            convs = await convs_task
            panel.conversation_count = len(convs)
            panel.unread_count = sum(c.get("unread_count", 0) for c in convs)
            total_messages = sum(c.get("message_count", 0) for c in convs)
            panel.messages_sent = 0
            panel.messages_received = total_messages
            panel.pending_deliveries = 0
        except Exception:
            pass

        try:
            contacts = await contacts_task
            panel.contact_count = len(contacts)
        except Exception:
            pass

        try:
            auto_reply = await auto_reply_task
            panel.auto_reply_enabled = bool(auto_reply.get("enabled", False))
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
