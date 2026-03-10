"""Dashboard Screen - Main fleet overview."""

from typing import TYPE_CHECKING, Any, ClassVar

from textual import events, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Tree
from textual.widgets.tree import TreeNode
from textual.worker import Worker

from styrened.ipc.protocol import IPCMessageType
from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.services.hardware import (
    PlatformNotSupportedError,
    get_disks,
    get_network_interfaces,
    get_system_info,
)
from styrened.tui.services.config import load_config
from styrened.tui.services.reticulum import discover_devices, start_discovery
from styrened.tui.screens.dashboard_projection import (
    DashboardTreeProjection,
    build_dashboard_tree_projection,
)
from styrened.tui.widgets.activity_feed import ActivityFeedWidget
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade
from styrened.tui.widgets.node_info_panel import NodeInfoPanel

if TYPE_CHECKING:
    from styrened.tui.app import StyreneApp
from styrened.ui_state import WorkspaceId
from styrened.ui_state.daemon import (
    LocalDaemonInputs,
    build_home_node_info_state,
    build_home_node_local_state,
    build_local_daemon_state,
)


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
            result = await bridge.get_unread_counts()
            return result if isinstance(result, dict) else {}
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

        # Dashboard stays live-biased: current discovery belongs here, while
        # broader stored history is moving toward the Nodes/Exploration workspace.
        live_nodes = discover_devices()

        # Filter for Styrene nodes only and drop very old lost nodes so the
        # home dashboard does not fill with stale history.
        import time

        now = time.time()
        styrene_devices = [
            d for d in live_nodes
            if d.device_type == DeviceType.STYRENE_NODE
            and not (
                d.status == NodeStatus.LOST and (now - float(d.last_announce or 0)) > 1800
            )
        ]
        
        # Use canonical shared node-catalog normalization instead of screen helper
        from styrened.ui_state.nodes import NodeCatalogInputs, build_node_catalog
        
        inputs = NodeCatalogInputs(devices=tuple(styrene_devices))
        catalog = build_node_catalog(inputs)
        
        # Convert back to MeshDevice list for tree population
        devices = [
            # Find the representative device for each identity
            next(d for d in styrene_devices if d.identity_hash == node.identity_hash)
            for node in catalog.nodes
        ]

        unread_counts = await self._async_get_unread_counts()
        cascade = get_color_cascade()

        # Load RBAC policy once via IPC
        rbac = None
        if bridge is not None:
            try:
                config_dict = await bridge.get_core_config()
                if isinstance(config_dict, dict):
                    rbac_dict = config_dict.get("rbac", {})
                    from styrened.models.rbac import RBACPolicy
                    rbac = RBACPolicy.from_dict(rbac_dict)
            except Exception:
                pass

        devices_by_identity = {
            d.identity_hash: d
            for d in devices
            if d.identity_hash
        }
        projection = build_dashboard_tree_projection(
            catalog=catalog,
            devices_by_identity=devices_by_identity,
            unread_counts=unread_counts,
            rbac=rbac,
        )

        # Cache for sync lookups (_device_by_destination_hash, _refresh_other_labels)
        self._device_cache = {
            destination_hash: row.device
            for destination_hash, row in projection.by_destination.items()
        }
        self._last_rbac = rbac

        self._render_tree(projection, cascade, rbac)

    @staticmethod
    def _device_info_to_mesh(info: Any) -> MeshDevice:
        """Convert a DeviceInfo dataclass from IPC to a MeshDevice."""
        from styrened.tui.utils import device_info_to_mesh

        return device_info_to_mesh(info)

    def _render_tree(
        self,
        projection: DashboardTreeProjection,
        cascade: Any,
        rbac: Any,
    ) -> None:
        """Rebuild the tree widget from a thin dashboard projection snapshot."""

        # Restore cursor position
        selected_identity: str | None = None
        if self.cursor_node and self.cursor_node.data:
            selected_identity = self.cursor_node.data

        self.clear()

        if not projection.my_mesh and not projection.other_nodes:
            self.root.add_leaf(
                f"[{cascade.dim}]No Styrene nodes discovered[/]",
                data=None,
            )
            return

        my_rows = projection.my_mesh
        other_rows = projection.other_nodes

        # --- MY MESH section ---
        my_label = f"[{cascade.bright} bold]MY MESH[/]"
        my_branch = self.root.add(my_label, data=None, expand=True)

        if my_rows:
            # Sub-group by interface within MY MESH
            groups: dict[str, list[Any]] = {}
            for row in my_rows:
                groups.setdefault(row.interface_group, []).append(row)

            sorted_keys = sorted(groups.keys(), key=lambda k: (k == "_direct", k.lower()))
            for group_key in sorted_keys:
                group_rows = sorted(
                    groups[group_key], key=lambda row: row.device.last_announce, reverse=True
                )
                if group_key == "_direct":
                    iface_label = f"[{cascade.dim}]direct[/]"
                else:
                    iface_label = f"[{cascade.medium}]{group_key}[/]"
                iface_branch = my_branch.add(iface_label, data=None, expand=True)
                for row in group_rows:
                    line = self._format_my_mesh_line(row, cascade, rbac)
                    # node.data stores destination_hash — used for all navigation.
                    iface_branch.add_leaf(line, data=row.destination_hash)
        else:
            my_branch.add_leaf(
                f"[{cascade.dim}]No trusted nodes — add nodes via Settings > Security[/]",
                data=None,
            )

        # --- OTHER STYRENE NODES section ---
        other_label = f"[{cascade.dim} bold]OTHER STYRENE NODES[/]"
        other_branch = self.root.add(other_label, data=None, expand=False)

        if other_rows:
            sorted_other = sorted(other_rows, key=lambda row: row.device.last_announce, reverse=True)
            for row in sorted_other:
                line = self._format_other_line(row, cascade)
                # node.data stores destination_hash — used for all navigation.
                other_branch.add_leaf(line, data=row.destination_hash)
            # Queue meta requests for any other nodes we haven't queried yet
            self._queue_meta_requests([row.device for row in other_rows])
        else:
            other_branch.add_leaf(
                f"[{cascade.dim}]No other nodes visible[/]",
                data=None,
            )

        if selected_identity:
            self._select_by_identity(selected_identity)

    def _format_my_mesh_line(
        self,
        row: Any,
        cascade: Any,
        rbac: Any = None,
    ) -> str:
        """Format a trusted mesh node — full detail with role badge.

        Args:
            rbac: Pre-loaded RBACPolicy (avoids disk read per device).
        """
        from styrened.models.rbac import Role
        device = row.device
        status_syms = {
            NodeStatus.ACTIVE: f"[{cascade.bright}]●[/]",
            NodeStatus.STALE: f"[{cascade.dim}]◐[/]",
            NodeStatus.LOST: f"[{cascade.dim}]○[/]",
        }
        status = status_syms.get(device.status, f"[{cascade.dim}]?[/]")
        name = f"[{cascade.bright} bold]{device.name}[/]"

        unread_text = (
            f" [{cascade.bright} bold]✉{row.unread_count}[/]"
            if row.unread_count > 0
            else ""
        )

        seen = device.last_seen_display
        if device.announce_count > 1:
            seen += f" ×{device.announce_count}"
        last_seen = f"[{cascade.dim}]{seen}[/]"

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

    def _format_other_line(self, row: Any, cascade: Any) -> str:
        """Format an unknown/foreign node — minimal, shows meta if available."""
        device = row.device
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

        Uses the same retry limit as DirectLink service (3 attempts).
        """
        _META_MAX_RETRIES = 3  # Same as services.direct_link.META_MAX_RETRIES
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
    """Home workspace with local summaries, current nodes, and activity."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("enter", "select_device", "Details"),
        Binding("c", "open_chat", "Chat"),
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("n", "open_exploration", "Nodes", show=True),
        Binding("e", "open_exploration", "Nodes", show=False),
        Binding("i", "request_identity", "Request ID", show=False),
    ]

    _last_discovery_refresh: float = 0.0
    _discovery_debounce_seconds: float = 2.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._device_refresh_timer: Timer | None = None
        self._hub_retry_timer: Timer | None = None
        self._activity_worker: Worker | None = None

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
        self._device_refresh_timer = self.set_interval(15.0, self._refresh_device_table)
        self._hub_retry_timer = self.set_interval(30.0, self._retry_hub_connection)

        try:
            panel = self.query_one(NodeInfoPanel)
            panel.ipc_managed = self._ipc_bridge is not None
            self._apply_local_panel_snapshot(panel)
            if self._ipc_bridge is not None:
                panel.daemon_connected = False
        except Exception:
            pass

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")
            self._activity_worker = self.run_worker(
                self._subscribe_activity(),
                group="dashboard-activity",
                exclusive=True,
            )

    def on_screen_suspend(self, event: events.ScreenSuspend) -> None:
        """Pause periodic refresh while Home is not the active screen."""
        if self._device_refresh_timer is not None:
            self._device_refresh_timer.pause()
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.pause()
        if self._activity_worker is not None:
            self._activity_worker.cancel()
            self._activity_worker = None

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Handle screen resume - refresh themed panels."""
        if self._device_refresh_timer is not None:
            self._device_refresh_timer.resume()
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.resume()

        for panel in self.query(HighlightedPanel):
            panel.refresh_theme()

        node_info_panel = self.query_one(NodeInfoPanel)
        self._apply_local_panel_snapshot(node_info_panel)
        if self._ipc_bridge is None:
            node_info_panel.refresh_data()

        for tree in self.query(MeshDeviceTree):
            tree.refresh_data()

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")
            self._activity_worker = self.run_worker(
                self._subscribe_activity(),
                group="dashboard-activity",
                exclusive=True,
            )

    def on_unmount(self) -> None:
        """Stop periodic refresh timers when Home is removed."""
        if self._device_refresh_timer is not None:
            self._device_refresh_timer.stop()
            self._device_refresh_timer = None
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.stop()
            self._hub_retry_timer = None
        if self._activity_worker is not None:
            self._activity_worker.cancel()
            self._activity_worker = None

    def _retry_hub_connection(self) -> None:
        """Periodically refresh hub status via IPC.

        Hub connection is managed by the daemon — we just poll status.
        """
        if self._ipc_bridge is not None:
            self.run_worker(self._refresh_hub_status(), group="hub-status")

    def _apply_local_panel_snapshot(self, panel: NodeInfoPanel) -> None:
        """Push local hardware/config Home snapshot into NodeInfoPanel."""
        system_info = None
        primary_interface = None
        removable_count = 0
        hardware_error = None
        mode = "standalone"
        identity_display_name = ""
        identity_icon = ""
        identity_short_name = None
        identity_provider = "file"

        try:
            system_info = get_system_info()
            interfaces = get_network_interfaces()
            hardware_ifaces = [i for i in interfaces if i.is_hardware and i.is_up and i.ip_address]
            primary_interface = hardware_ifaces[0] if hardware_ifaces else None
            disks = get_disks()
            removable_count = len([d for d in disks if d.is_removable])
        except PlatformNotSupportedError as exc:
            hardware_error = str(exc)

        try:
            config = load_config()
            mode = config.reticulum.mode.value
            if hasattr(config, "identity"):
                identity_display_name = config.identity.display_name
                identity_icon = config.identity.icon
                identity_short_name = config.identity.short_name
                identity_provider = getattr(config.identity, "provider", "file")
        except Exception:
            pass

        panel.apply_home_local_snapshot(
            build_home_node_local_state(
                system_info=system_info,
                primary_interface=primary_interface,
                removable_count=removable_count,
                hardware_error=hardware_error,
                mode=mode,
                identity_display_name=identity_display_name,
                identity_icon=identity_icon,
                identity_short_name=identity_short_name,
                identity_provider=identity_provider,
            )
        )

    def _apply_local_daemon_snapshot(
        self,
        panel: NodeInfoPanel,
        *,
        daemon_state: object,
        mesh_device_infos: tuple[object, ...],
        raw_status: object | None = None,
    ) -> None:
        """Push dashboard-owned daemon state into the Home status panel."""
        mesh_node_count = panel._apply_mesh_catalog_count(mesh_device_infos)
        home_snapshot = build_home_node_info_state(
            daemon_state=daemon_state,
            daemon_status=raw_status,
            mesh_node_count=mesh_node_count,
        )
        panel.apply_home_snapshot(home_snapshot)

    async def _refresh_hub_status(self) -> None:
        """Refresh the Home status snapshot from dashboard-owned daemon state."""
        await self._fetch_daemon_status()

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
                title="HOME STATUS",
                id="node-info-panel",
            )
            yield HighlightedPanel(
                MeshDeviceTree(id="mesh-device-tree"),
                title="CURRENT NODES",
                id="mesh-devices-panel",
            )
            yield HighlightedPanel(
                ActivityFeedWidget(id="activity-feed-widget"),
                title="RECENT ACTIVITY",
                id="activity-feed-panel",
            )
        yield Footer()

    def on_tree_node_selected(self, event: Tree.NodeSelected[str]) -> None:
        """Handle tree node selection (enter key on a leaf)."""
        if event.node.data:
            device_identity = str(event.node.data)
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
            self.app.push_screen(
                MeshDeviceDetailScreen(
                    device_identity=device_identity,
                    origin_workspace=WorkspaceId.HOME,
                )
            )

    def _get_selected_identity(self) -> str | None:
        """Get the identity of the currently selected tree node."""
        tree = self.query_one("#mesh-device-tree", MeshDeviceTree)
        return tree.get_selected_identity()

    def action_select_device(self) -> None:
        """Handle device selection."""
        device_identity = self._get_selected_identity()
        if device_identity:
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
            self.app.push_screen(
                MeshDeviceDetailScreen(
                    device_identity=device_identity,
                    origin_workspace=WorkspaceId.HOME,
                )
            )

    def action_open_chat(self) -> None:
        """Open chat tab directly for the selected device."""
        device_identity = self._get_selected_identity()
        if device_identity:
            from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
            self.app.push_screen(
                MeshDeviceDetailScreen(
                    device_identity=device_identity,
                    initial_tab="chat",
                    origin_workspace=WorkspaceId.HOME,
                )
            )
        else:
            self.app.notify("Select a device in the mesh tree first.", severity="warning")

    def action_open_exploration(self) -> None:
        """Open the canonical Nodes workspace from Home."""
        self.app.action_open_nodes()

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
            self._apply_local_panel_snapshot(node_info)
            if self._ipc_bridge is None:
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
        """Fetch dashboard-owned Home status and push it into NodeInfoPanel."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            panel = self.query_one(NodeInfoPanel)
        except Exception:
            return

        import asyncio

        tasks = {
            "status": asyncio.create_task(bridge.get_status()),
            "identity": asyncio.create_task(bridge.get_identity()),
            "hub": asyncio.create_task(bridge.get_hub_status()),
            "config": asyncio.create_task(bridge.get_core_config()),
            "mesh_devices": asyncio.create_task(bridge.get_devices(styrene_only=True)),
            "conversations": asyncio.create_task(bridge.get_conversations()),
            "contacts": asyncio.create_task(bridge.get_contacts()),
            "auto_reply": asyncio.create_task(bridge.get_auto_reply()),
        }

        try:
            try:
                status = await tasks["status"]
                identity = await tasks["identity"]
                hub_data = await tasks["hub"]
                core_config = await tasks["config"]
                mesh_devices = tuple(await tasks["mesh_devices"])
            except Exception:
                panel.daemon_connected = False
                return

            daemon_state = build_local_daemon_state(
                LocalDaemonInputs(
                    daemon_status=status,
                    identity_info=identity,
                    hub_status=hub_data if isinstance(hub_data, dict) else None,
                    core_config=core_config if isinstance(core_config, dict) else None,
                )
            )
            self._apply_local_daemon_snapshot(
                panel,
                daemon_state=daemon_state,
                mesh_device_infos=mesh_devices,
                raw_status=status,
            )

            convs: list[dict[str, Any]] = []
            contacts: list[dict[str, Any]] = []
            auto_reply: dict[str, Any] = {}

            try:
                convs = await tasks["conversations"]
            except Exception:
                pass

            try:
                contacts = await tasks["contacts"]
            except Exception:
                pass

            try:
                auto_reply = await tasks["auto_reply"]
            except Exception:
                pass

            mesh_node_count = panel.styrene_mesh_count
            home_snapshot = build_home_node_info_state(
                daemon_state=daemon_state,
                daemon_status=status,
                mesh_node_count=mesh_node_count,
                conversations=convs,
                contacts=contacts,
                auto_reply=auto_reply,
            )
            panel.apply_home_snapshot(home_snapshot)
        finally:
            pending_tasks = [task for task in tasks.values() if not task.done()]
            for task in pending_tasks:
                task.cancel()
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)

    async def _subscribe_activity(self) -> None:
        """Subscribe to dashboard activity events via IPC."""
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            await bridge.subscribe_activity()
            async for event_type, event in bridge.iter_events(IPCMessageType.EVENT_ACTIVITY):
                if event_type != IPCMessageType.EVENT_ACTIVITY:
                    continue
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
