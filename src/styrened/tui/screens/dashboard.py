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
        # All caches are keyed by identity_hash (NOT destination_hash).
        # identity_hash is the stable public-key hash; destination_hash
        # is app+aspect-scoped and is stored in node.data for routing.
        # Cache: identity_hash → meta dict from /meta responses
        self._meta_cache: dict[str, dict[str, Any]] = {}
        # Cache: identity_hash → info dict from /info responses.
        # None = node declined (info_respond=False).  Absent key = not yet queried.
        self._info_cache: dict[str, dict[str, Any] | None] = {}
        # Pending /meta probes (identity_hash) — avoid duplicate in-flight requests
        self._meta_pending: set[str] = set()
        # Failure counter per identity_hash — give up after META_MAX_RETRIES failures
        self._meta_fail_count: dict[str, int] = {}

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

    def _is_my_mesh(self, device: MeshDevice, rbac: Any = None) -> bool:
        """Return True if this device is in the local RBAC roster with role ≥ PEER.

        Args:
            device: The MeshDevice to check.
            rbac: Pre-loaded RBACPolicy to avoid repeated disk reads.  When
                  None, loads config from disk (use only for one-off checks).
        """
        try:
            from styrened.models.rbac import Role
            if rbac is None:
                from styrened.services.config import load_core_config
                config = load_core_config()
                rbac = config.rbac
            if rbac is None:
                return False
            return rbac.resolve_role(device.identity_hash) >= Role.PEER
        except Exception:
            return False

    def _load_data(self) -> None:
        """Load device data and rebuild tree into MY MESH / OTHER sections.

        Config is loaded once per call and passed to helpers to avoid
        repeated disk reads for every device in the list.
        """
        try:
            from styrened.services.node_store import get_node_store
            stored_nodes = get_node_store().get_styrene_nodes()
        except Exception:
            stored_nodes = []

        live_nodes = discover_devices()

        # Build by destination_hash — this is what node.data will store.
        # destination_hash is the routing identifier; identity_hash is the
        # public-key hash used for RBAC lookups.  Both fields live on MeshDevice.
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

        # Load RBAC policy once — passed to _is_my_mesh to avoid N disk reads.
        rbac = None
        try:
            from styrened.services.config import load_core_config
            rbac = load_core_config().rbac
        except Exception:
            pass

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

        # Split into my mesh vs other — single pass, single config read
        my_devices = [d for d in devices if self._is_my_mesh(d, rbac)]
        other_devices = [d for d in devices if not self._is_my_mesh(d, rbac)]

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
                    line = self._format_my_mesh_line(device, cascade, unread_counts, rbac)
                    # node.data stores destination_hash — used for all navigation.
                    iface_branch.add_leaf(line, data=device.destination_hash)
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
                # node.data stores destination_hash — used for all navigation.
                other_branch.add_leaf(line, data=device.destination_hash)
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
        rbac: Any = None,
    ) -> str:
        """Format a trusted mesh node — full detail with role badge.

        Args:
            rbac: Pre-loaded RBACPolicy (avoids disk read per device).
        """
        from styrened.models.rbac import Role
        status_syms = {
            NodeStatus.ACTIVE: f"[{cascade.bright}]●[/]",
            NodeStatus.STALE: f"[{cascade.dim}]◐[/]",
            NodeStatus.LOST: f"[{cascade.dim}]○[/]",
        }
        status = status_syms.get(device.status, f"[{cascade.dim}]?[/]")
        name = f"[{cascade.bright} bold]{device.name}[/]"

        # Role badge — use pre-loaded rbac if available, no extra disk read
        role_badge = ""
        try:
            if rbac is None:
                from styrened.services.config import load_core_config
                rbac = load_core_config().rbac
            if rbac:
                role = rbac.resolve_role(device.identity_hash)
                if role >= Role.ADMIN:
                    role_badge = f" [{cascade.bright}][ADMIN][/]"
                elif role >= Role.OPERATOR:
                    role_badge = f" [{cascade.medium}][OP][/]"
                elif role >= Role.MONITOR:
                    role_badge = f" [{cascade.dim}][MON][/]"
        except Exception:
            pass

        # unread_counts keyed by destination_hash (via device.identity alias)
        unread = unread_counts.get(device.destination_hash, 0)
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
        elif self._meta_fail_count.get(device.identity_hash, 0) > 0:
            # Node unreachable or pre-/meta version — show nothing extra
            pass

        seen = device.last_seen_display
        last_seen = f"[{cascade.dim}]{seen}[/]"

        return f"{status} {display_name}{meta_suffix}  {last_seen}"

    def _queue_meta_requests(self, devices: list[MeshDevice]) -> None:
        """Fire background /meta probes for OTHER nodes not yet queried.

        Nodes that have failed META_MAX_RETRIES times are skipped — they're
        likely running an older version without /meta support, or are
        unreachable over direct link.
        """
        from styrened.services.direct_link import META_MAX_RETRIES
        for device in devices:
            if not device.identity_hash or not device.destination_hash:
                continue
            ih = device.identity_hash
            if ih in self._meta_cache:
                continue  # already have it
            if ih in self._meta_pending:
                continue  # in-flight
            if self._meta_fail_count.get(ih, 0) >= META_MAX_RETRIES:
                continue  # gave up
            self._meta_pending.add(ih)
            self._fetch_meta(device.destination_hash, ih)

    @work(thread=False, exclusive=False, group="meta-fetch")
    async def _fetch_meta(self, destination_hash: str, identity_hash: str) -> None:
        """Async worker: request /meta from an OTHER node and update labels.

        Runs in the Textual event-loop (thread=False).  Mutations to widget
        labels are deferred via call_later to ensure they occur during the
        next message-pump cycle rather than mid-worker.
        """
        import logging
        logger = logging.getLogger(__name__)
        try:
            app: StyreneApp = self.app  # type: ignore[assignment]
            bridge = app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
            if bridge is None:
                return
            meta = await bridge.datalink_meta(destination_hash)
            if meta:
                self._meta_cache[identity_hash] = meta
            else:
                # Probe returned nothing — count as a failure
                self._meta_fail_count[identity_hash] = (
                    self._meta_fail_count.get(identity_hash, 0) + 1
                )
        except Exception as exc:
            logger.debug(
                "Datalink /meta probe failed for %s: %s",
                identity_hash[:12],
                exc,
            )
            self._meta_fail_count[identity_hash] = (
                self._meta_fail_count.get(identity_hash, 0) + 1
            )
        finally:
            self._meta_pending.discard(identity_hash)
        # Defer label refresh to the next pump cycle so we don't mutate
        # tree nodes from within a worker callback.
        self.call_later(self._refresh_other_labels)

    def _refresh_other_labels(self) -> None:
        """Re-render labels in the OTHER branch without a full data reload.

        Walks the tree and updates labels for nodes in the OTHER section.
        Must be called on the main event-loop (use call_later from workers).
        Only OTHER nodes are updated — MY MESH node labels are left intact.
        """
        try:
            # Load RBAC once for the walk
            rbac = None
            try:
                from styrened.services.config import load_core_config
                rbac = load_core_config().rbac
            except Exception:
                pass

            cascade = get_color_cascade()
            for node in self._tree_walk(self.root):
                if node.data is None:
                    continue
                # node.data stores destination_hash
                dest_hash = str(node.data)
                # Look up the device by destination_hash
                device = self._device_by_destination_hash(dest_hash)
                if device is None:
                    continue
                # Only re-render OTHER nodes — leave MY MESH labels alone
                if self._is_my_mesh(device, rbac):
                    continue
                node.set_label(self._format_other_line(device, cascade))
        except Exception:
            pass

    def _device_by_destination_hash(self, destination_hash: str) -> MeshDevice | None:
        """Look up a MeshDevice by destination_hash from live + stored nodes.

        Note: node.data stores destination_hash.  Do NOT pass identity_hash
        here — use _is_my_mesh(device) to check RBAC membership instead.
        """
        try:
            from styrened.services.node_store import get_node_store
            nodes = get_node_store().get_styrene_nodes()
            live = discover_devices()
            # Key by destination_hash to match what node.data stores
            all_devices = {n.destination_hash: n for n in nodes}
            all_devices.update({n.destination_hash: n for n in live})
            return all_devices.get(destination_hash)
        except Exception:
            return None

    def request_info_for_selected(self) -> str | None:
        """Fire an /info request for the currently selected OTHER node.

        Returns the destination_hash if a request was queued, else None.
        The /info result is stored in _info_cache keyed by identity_hash.
        Callers should use this return value only for notification display.
        """
        if not self.cursor_node or not self.cursor_node.data:
            return None
        # node.data is destination_hash
        dest_hash = str(self.cursor_node.data)
        device = self._device_by_destination_hash(dest_hash)
        if device is None:
            return None
        # Only valid for OTHER nodes
        if self._is_my_mesh(device):
            return None
        # /info result must be cached under identity_hash (matches _format_other_line read)
        self._fetch_info(device.destination_hash, device.identity_hash)
        return dest_hash

    @work(thread=False, exclusive=False, group="info-fetch")
    async def _fetch_info(self, destination_hash: str, identity_hash: str) -> None:
        """Async worker: request /info from an OTHER node and update labels.

        Cache is keyed by identity_hash — matching _format_other_line reads.
        Runs in the Textual event-loop (thread=False).
        """
        import logging
        logger = logging.getLogger(__name__)
        try:
            app: StyreneApp = self.app  # type: ignore[assignment]
            bridge = app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
            if bridge is None:
                return
            info = await bridge.datalink_info(destination_hash)
            # Store result under identity_hash — None = declined (not an error)
            self._info_cache[identity_hash] = info
        except Exception as exc:
            logger.debug(
                "Datalink /info request failed for %s: %s",
                identity_hash[:12],
                exc,
            )
            self._info_cache[identity_hash] = None
        self.call_later(self._refresh_other_labels)

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
