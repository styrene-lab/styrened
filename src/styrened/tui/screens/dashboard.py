"""Dashboard Screen - Main fleet overview."""

from typing import TYPE_CHECKING, Any, ClassVar

from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Tree
from textual.widgets.tree import TreeNode

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.services.reticulum import discover_devices, start_discovery
from styrened.tui.utils import _deduplicate_by_identity
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
        # Bounded to _CACHE_MAX entries (FIFO eviction on overflow).
        self._meta_cache: dict[str, dict[str, Any]] = {}
        # Cache: identity_hash → info dict from /info responses.
        # None = node declined (info_respond=False).  Absent key = not yet queried.
        self._info_cache: dict[str, dict[str, Any] | None] = {}
        # Pending /meta probes (identity_hash) — avoid duplicate in-flight requests
        self._meta_pending: set[str] = set()
        # Failure counter per identity_hash — give up after META_MAX_RETRIES failures
        self._meta_fail_count: dict[str, int] = {}
        # Device cache: destination_hash → MeshDevice, populated by _async_load_data.
        self._device_cache: dict[str, MeshDevice] = {}

    # Maximum number of entries in each identity-keyed cache.  In a large
    # observable mesh (public hub scenario), the OTHER section could grow
    # arbitrarily.  FIFO eviction keeps memory stable over long TUI sessions.
    _CACHE_MAX: int = 512

    def _cache_put(self, cache: dict, key: str, value: Any) -> None:
        """Insert into a bounded cache dict.  Evicts the oldest entry (FIFO)
        when the cache is full.  Python 3.7+ dicts maintain insertion order.
        """
        if key in cache:
            # Update existing — no eviction needed
            cache[key] = value
            return
        while len(cache) >= self._CACHE_MAX:
            evicted = next(iter(cache))
            del cache[evicted]
        cache[key] = value

    def _evict_stale_fail_counts(self) -> None:
        """Keep _meta_fail_count bounded to _CACHE_MAX entries (FIFO eviction)."""
        while len(self._meta_fail_count) >= self._CACHE_MAX:
            del self._meta_fail_count[next(iter(self._meta_fail_count))]

    def on_mount(self) -> None:
        self.run_worker(self._async_load_data(), group="tree-load")

    async def _async_get_unread_counts(self) -> dict[str, int]:
        """Get unread message counts per device identity via IPC."""
        try:
            app: StyreneApp = self.app  # type: ignore[assignment]
            bridge = app.services.bridge
            if bridge is None:
                return {}
            return await bridge.get_unread_counts()
        except Exception:
            return {}

    def _is_my_mesh(self, device: MeshDevice, rbac: Any = None) -> bool:
        """Return True if this device is in the local RBAC roster with role ≥ PEER.

        Args:
            device: The MeshDevice to check.
            rbac: Pre-loaded RBACPolicy.  Must be provided — no fallback to
                  disk reads.  Returns False if rbac is None.
        """
        if rbac is None:
            return False
        try:
            from styrened.models.rbac import Role
            return rbac.resolve_role(device.identity_hash) >= Role.PEER
        except Exception:
            return False

    async def _async_load_data(self) -> None:
        """Load device data via IPC and rebuild tree into MY MESH / OTHER."""
        app: StyreneApp = self.app  # type: ignore[assignment]
        bridge = app.services.bridge

        # Fetch stored nodes via IPC + live discovery nodes
        stored_nodes: list[MeshDevice] = []
        if bridge is not None:
            try:
                stored_raw = await bridge.get_nodes(styrene_only=True)
                stored_nodes = [self._device_info_to_mesh(d) for d in stored_raw]
            except Exception:
                pass

        live_nodes = discover_devices()

        all_devices_dict = {n.destination_hash: n for n in stored_nodes}
        all_devices_dict.update({n.destination_hash: n for n in live_nodes})

        devices = [
            d for d in all_devices_dict.values()
            if d.device_type == DeviceType.STYRENE_NODE
        ]
        devices = _deduplicate_by_identity(devices)

        unread_counts = await self._async_get_unread_counts()
        cascade = get_color_cascade()

        # Load RBAC policy once via IPC
        rbac = None
        if bridge is not None:
            try:
                config_dict = await bridge.get_core_config()
                rbac_dict = config_dict.get("rbac", {})
                from styrened.models.rbac import RBACPolicy
                rbac = RBACPolicy.from_dict(rbac_dict)
            except Exception:
                pass

        # Cache for sync lookups (_device_by_destination_hash, _refresh_other_labels)
        self._device_cache = {d.destination_hash: d for d in devices}
        self._last_rbac = rbac

        self._render_tree(devices, unread_counts, cascade, rbac)

    @staticmethod
    def _device_info_to_mesh(info: Any) -> MeshDevice:
        """Convert a DeviceInfo dataclass from IPC to a MeshDevice."""
        from styrened.tui.utils import device_info_to_mesh

        return device_info_to_mesh(info)

    def _render_tree(
        self,
        devices: list[MeshDevice],
        unread_counts: dict[str, int],
        cascade: Any,
        rbac: Any,
    ) -> None:
        """Rebuild the tree widget with device data. Called after async fetch."""

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

        # Compute display fragments first (needed by all code paths)
        unread = unread_counts.get(device.destination_hash, 0)
        unread_text = f" [{cascade.bright} bold]✉{unread}[/]" if unread > 0 else ""

        seen = device.last_seen_display
        if device.announce_count > 1:
            seen += f" ×{device.announce_count}"
        last_seen = f"[{cascade.dim}]{seen}[/]"

        # Role badge — use pre-loaded rbac (no disk fallback)
        role_badge = ""
        if rbac is not None:
            try:
                role = rbac.resolve_role(device.identity_hash)
                if role >= Role.ADMIN:
                    role_badge = f" [{cascade.bright}][ADMIN][/]"
                elif role >= Role.OPERATOR:
                    role_badge = f" [{cascade.medium}][OP][/]"
                elif role >= Role.MONITOR:
                    role_badge = f" [{cascade.dim}][MON][/]"
            except Exception:
                pass

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

        Uses the same retry limit as services.direct_link.META_MAX_RETRIES.
        """
        from styrened.services.direct_link import META_MAX_RETRIES as _META_MAX_RETRIES
        for device in devices:
            if not device.identity_hash or not device.destination_hash:
                continue
            ih = device.identity_hash
            if ih in self._meta_cache:
                continue  # already have it
            if ih in self._meta_pending:
                continue  # in-flight
            if self._meta_fail_count.get(ih, 0) >= _META_MAX_RETRIES:
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
            bridge = app.services.bridge
            if bridge is None:
                return
            meta = await bridge.datalink_meta(destination_hash)
            if meta:
                self._cache_put(self._meta_cache, identity_hash, meta)
            else:
                # Probe returned nothing — count as a failure
                if identity_hash not in self._meta_fail_count:
                    self._evict_stale_fail_counts()
                self._meta_fail_count[identity_hash] = (
                    self._meta_fail_count.get(identity_hash, 0) + 1
                )
        except Exception as exc:
            logger.debug(
                "Datalink /meta probe failed for %s: %s",
                identity_hash[:12],
                exc,
            )
            if identity_hash not in self._meta_fail_count:
                self._evict_stale_fail_counts()
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
            # Use cached RBAC from last _async_load_data (avoid sync IPC call)
            rbac = getattr(self, "_last_rbac", None)

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
        """Look up a MeshDevice by destination_hash from the device cache.

        Note: node.data stores destination_hash.  Do NOT pass identity_hash
        here — use _is_my_mesh(device) to check RBAC membership instead.

        Uses the last-loaded device list rather than hitting IPC synchronously.
        """
        return self._device_cache.get(destination_hash)

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
        # Only valid for OTHER nodes — use cached rbac from last load
        if self._is_my_mesh(device, getattr(self, "_last_rbac", None)):
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
            bridge = app.services.bridge
            if bridge is None:
                return
            info = await bridge.datalink_info(destination_hash)
            # Store result under identity_hash — None = declined (not an error)
            self._cache_put(self._info_cache, identity_hash, info)
        except Exception as exc:
            logger.debug(
                "Datalink /info request failed for %s: %s",
                identity_hash[:12],
                exc,
            )
            self._cache_put(self._info_cache, identity_hash, None)
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
        self.run_worker(self._async_load_data(), group="tree-load")
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
        """Get IPCBridge via typed services protocol."""
        try:
            return self.app.services.bridge  # type: ignore[union-attr]
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
        """Periodically refresh hub status via IPC.

        Hub connection is managed by the daemon — we just poll status.
        """
        if self._ipc_bridge is not None:
            self.run_worker(self._refresh_hub_status(), group="hub-status")

    async def _refresh_hub_status(self) -> None:
        """Fetch hub status from daemon and update the info panel."""
        try:
            app: StyreneApp = self.app  # type: ignore[assignment]
            bridge = app.services.bridge
            if bridge is None:
                return
            hub_data = await bridge.get_hub_status()
            if hub_data:
                try:
                    panel = self.query_one(NodeInfoPanel)
                    panel.daemon_connected = hub_data.get("is_connected", False)
                except Exception:
                    pass
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
