"""Dashboard Screen — Home workspace (COP layout).

Common Operating Picture: compact status bar, node summary table, activity feed.
Peer browsing lives in the Nodes workspace (ExplorationScreen).
"""
from __future__ import annotations

from typing import Any, ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer
from textual.worker import Worker

from styrened.ipc.protocol import IPCMessageType
from styrened.services.hub_connection import HubStatus
from styrened.tui.models.adapter_status import AdapterStatusTracker
from styrened.tui.models.cop_situation import CopSituationTracker
from styrened.tui.models.events import DaemonEvent
from styrened.tui.widgets.safe_header import Header

# Map legacy IPC activity event type strings to coarse bus event types
_IPC_TO_BUS_TYPE: dict[str, str] = {
    "device_discovered": "node_changed",
    "device_updated": "node_changed",
    "device_lost": "node_changed",
    "announce_sent": "node_changed",
    "message_received": "message_changed",
    "message_delivered": "message_changed",
    "message_read": "message_changed",
    "hub_connected": "hub_changed",
    "hub_disconnected": "hub_changed",
    "link_established": "link_changed",
    "link_lost": "link_changed",
    "config_saved": "config_changed",
    "pqc_established": "link_changed",
    "file_offer": "message_changed",
    "file_complete": "message_changed",
    "adapter_changed": "adapter_changed",
}


def _ipc_type_to_bus_type(ipc_type: str) -> str:
    """Convert IPC activity event type to coarse bus event type."""
    return _IPC_TO_BUS_TYPE.get(ipc_type, ipc_type)
from styrened.tui.services.reticulum import start_discovery
from styrened.tui.widgets.adapter_status_bar import AdapterStatusBar
from styrened.tui.widgets.cop_activity_summary import CopActivitySummary
from styrened.tui.widgets.highlighted_panel import HighlightedPanel
from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable
from styrened.tui.widgets.home_status_bar import HomeStatusBar


class DashboardScreen(Screen[None]):
    """Home workspace — COP: status bar, node summary, activity feed.

    Peer browsing and the full mesh device tree belong in the Nodes workspace
    (ExplorationScreen). Home is intentionally narrow: it shows what the
    operator needs at a glance without duplicating the Nodes workspace.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "refresh", "Refresh", priority=True),
        Binding("n", "open_exploration", "Nodes", show=True),
        Binding("e", "open_exploration", "Nodes", show=False),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._hub_retry_timer: Timer | None = None
        self._activity_worker: Worker | None = None
        self._situation_tracker = CopSituationTracker()
        self._adapter_tracker = AdapterStatusTracker()

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge via typed services protocol."""
        try:
            return self.app.services.bridge  # type: ignore[union-attr]
        except Exception:
            return None

    def _get_cached_devices(self) -> list[Any]:
        """Return cached devices without letting bare-screen app access fail status refresh."""
        try:
            cache = getattr(self.app, "device_cache", None)
        except Exception:
            return []

        if cache is None:
            return []

        try:
            devices = cache.get()
        except Exception:
            return []

        return devices if isinstance(devices, list) else []

    def on_mount(self) -> None:
        """Initialise Home: start discovery, then fetch daemon state."""
        start_discovery()
        self._hub_retry_timer = self.set_interval(30.0, self._retry_hub_connection)
        # Slow reconciliation timer — belt-and-suspenders behind event-driven updates
        self._reconcile_timer = self.set_interval(60.0, self._reconcile)

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")
            self.run_worker(self._fetch_adapter_state(), group="dashboard-adapters")
            self._activity_worker = self.run_worker(
                self._subscribe_activity(),
                group="dashboard-activity",
                exclusive=True,
            )

        # Focus a widget so Footer renders screen bindings.
        # call_after_refresh ensures the widget tree is fully composed.
        self.call_after_refresh(self._refocus_default)

    def on_screen_suspend(self, event: events.ScreenSuspend) -> None:
        """Pause periodic refresh while Home is not the active screen."""
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.pause()
        if self._activity_worker is not None:
            self._activity_worker.cancel()
            self._activity_worker = None

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Refresh Home panels when the operator returns from another workspace."""
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.resume()
        if hasattr(self, "_reconcile_timer") and self._reconcile_timer is not None:
            self._reconcile_timer.resume()

        for panel in self.query(HighlightedPanel):
            panel.refresh_theme()

        # Re-focus so Footer picks up screen bindings after switch_screen
        self.call_after_refresh(self._refocus_default)

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")
            self.run_worker(self._fetch_adapter_state(), group="dashboard-adapters")
            self._activity_worker = self.run_worker(
                self._subscribe_activity(),
                group="dashboard-activity",
                exclusive=True,
            )

    def on_unmount(self) -> None:
        """Stop timers when Home is removed from the screen stack."""
        if self._hub_retry_timer is not None:
            self._hub_retry_timer.stop()
            self._hub_retry_timer = None
        if hasattr(self, "_reconcile_timer") and self._reconcile_timer is not None:
            self._reconcile_timer.stop()
            self._reconcile_timer = None
        if self._activity_worker is not None:
            self._activity_worker.cancel()
            self._activity_worker = None

    _EVENT_COOLDOWN: float = 5.0  # seconds — absorb rapid event bursts

    def on_daemon_event(self, event: DaemonEvent) -> None:
        """Handle daemon events — ingest ephemerals immediately, debounce poll refresh.

        Ephemeral events (file transfers, PQC) are fed into the tracker and
        pushed to the COP widget immediately — no poll required.

        Store-backed events (node changes, messages, hub) debounce to avoid
        spawning redundant refresh workers during fleet-boot bursts.
        """
        # Always feed the COP tracker — it ignores events it doesn't care about
        self._situation_tracker.ingest(event)
        try:
            cop = self.query_one(CopActivitySummary)
            cop.apply_snapshot(self._situation_tracker.snapshot())
        except Exception:
            pass

        # Feed adapter tracker; push snapshot to bar; inject situation line if present
        if event.event_type == "adapter_changed":
            self._adapter_tracker.ingest(event)
            try:
                bar = self.query_one(AdapterStatusBar)
                bar.apply_snapshot(self._adapter_tracker.snapshot())
            except Exception:
                pass
            situation_line = self._adapter_tracker.get_situation_line()
            if situation_line is not None:
                self._situation_tracker._push_ephemeral(
                    situation_line.message, situation_line.priority
                )
                try:
                    cop = self.query_one(CopActivitySummary)
                    cop.apply_snapshot(self._situation_tracker.snapshot())
                except Exception:
                    pass

        # Store-backed events trigger a full poll refresh (debounced)
        if event.event_type not in ("node_changed", "message_changed", "hub_changed"):
            return

        import time as _time

        now = _time.monotonic()
        last = getattr(self, "_last_event_refresh", 0.0)
        if (now - last) < self._EVENT_COOLDOWN:
            return

        self._last_event_refresh = now
        if self._ipc_bridge is not None:
            self.run_worker(
                self._fetch_daemon_status(),
                group="dashboard-status",
                exclusive=True,
            )

    def _retry_hub_connection(self) -> None:
        """Periodically poll hub status via IPC."""
        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="hub-status")

    def _refocus_default(self) -> None:
        """Focus a widget and force Footer to pick up bindings.

        The Footer only renders after ``Screen.refresh_bindings()`` fires,
        which happens on focus change.  If nothing is focused after mount
        or screen-switch, the Footer stays blank.  We focus the node table
        (or any focusable child) AND explicitly refresh bindings.
        """
        try:
            from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable
            table = self.query_one(HomeNodeSummaryTable)
            table.focus()
        except Exception:
            # Fall back to focusing *anything*
            for widget in self.query("*"):
                if widget.focusable:
                    widget.focus()
                    break
        # Belt-and-suspenders: force bindings refresh even if focus didn't change
        self.refresh_bindings()

    def _reconcile(self) -> None:
        """Slow reconciliation — catches anything events missed."""
        if self._ipc_bridge is not None:
            self.run_worker(
                self._fetch_daemon_status(),
                group="dashboard-status",
                exclusive=True,
            )

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="dashboard-container"):
            yield HighlightedPanel(
                HomeStatusBar(id="home-status-bar-widget"),
                title="STATUS",
                id="status-bar-panel",
            )
            yield AdapterStatusBar(id="adapter-status-bar-widget")
            yield HighlightedPanel(
                HomeNodeSummaryTable(id="home-node-summary-widget"),
                title="NODES",
                id="nodes-panel",
            )
            yield HighlightedPanel(
                CopActivitySummary(id="activity-feed-widget"),
                title="ACTIVITY",
                id="activity-panel",
            )
        yield Footer()

    def on_home_node_summary_table_node_selected(
        self, event: HomeNodeSummaryTable.NodeSelected
    ) -> None:
        """Drill into peer workspace when Enter is pressed on a node row."""
        from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

        self.app.push_screen(MeshDeviceDetailScreen(device_identity=event.identity_hash))

    def on_home_node_summary_table_overflow_selected(
        self, event: HomeNodeSummaryTable.OverflowSelected
    ) -> None:
        """Navigate to the Nodes workspace when the overflow affordance is activated."""
        self.action_open_exploration()

    def action_open_exploration(self) -> None:
        """Open the canonical Nodes workspace."""
        self.app.action_open_nodes()  # type: ignore[union-attr]

    def action_refresh(self) -> None:
        """Refresh Home status panels."""
        try:
            # Clear ephemeral state on manual refresh then re-render
            self._situation_tracker = CopSituationTracker()
            cop_summary = self.query_one(CopActivitySummary)
            cop_summary.apply_snapshot(self._situation_tracker.snapshot())
        except Exception:
            pass

        self.notify("Refreshed")

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

        try:
            self.app._check_for_updates()  # type: ignore[union-attr]
        except Exception:
            pass

    def on_device_cache_devices_updated(self, message: Any) -> None:
        """Refresh Home when background device-cache priming completes."""
        if self._ipc_bridge is not None:
            self.run_worker(
                self._fetch_daemon_status(),
                group="dashboard-status",
                exclusive=True,
            )

    async def _prime_device_cache_in_background(self) -> None:
        """Kick the shared device cache without blocking first paint."""
        try:
            cache = getattr(self.app, "device_cache", None)
        except Exception:
            return

        if cache is None:
            return

        refresh = getattr(cache, "refresh", None)
        if refresh is None:
            return

        await refresh()

    async def _fetch_daemon_status(self) -> None:
        """Fetch Home status using cheap summary IPC for first paint."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        def _get(obj: Any, key: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        try:
            try:
                # The shared IPC bridge/client is not a good fit for bursty
                # same-connection fan-out at startup. Keep Home on a short,
                # sequential summary path so first paint stays truthful.
                status = await bridge.get_status()
                hub_data = await bridge.get_hub_status()
            except Exception:
                try:
                    bar = self.query_one(HomeStatusBar)
                    bar.daemon_connected = False
                    bar.ipc_backpressured = False
                except Exception:
                    pass
                return

            all_devices = self._get_cached_devices()
            if not all_devices and not getattr(self, "_device_cache_prime_requested", False):
                self._device_cache_prime_requested = True
                self.run_worker(
                    self._prime_device_cache_in_background(),
                    group="dashboard-device-prime",
                    exclusive=True,
                )

            unread_map: dict[str, int] = {}
            ipc_backpressured = False
            try:
                unread_counts = await bridge.get_unread_counts()
                if isinstance(unread_counts, dict):
                    counts = unread_counts.get("counts", unread_counts)
                    if isinstance(counts, dict):
                        unread_map = {
                            str(identity_hash): int(count or 0)
                            for identity_hash, count in counts.items()
                            if identity_hash and int(count or 0) > 0
                        }
            except Exception:
                ipc_backpressured = True

            device_list: list[Any] = all_devices if isinstance(all_devices, list) else []

            try:
                from styrened.models.mesh_device import DeviceType, MeshDevice

                styrene_enum_types = {DeviceType.STYRENE_NODE}
                styrene_str_types = {t.value for t in styrene_enum_types} | {
                    "styrene_node", "styrene_hub",
                }
                styrene_count = sum(
                    1
                    for d in device_list
                    if (
                        isinstance(d, MeshDevice) and d.device_type in styrene_enum_types
                    )
                    or (
                        not isinstance(d, MeshDevice)
                        and _get(d, "device_type") in styrene_str_types
                    )
                )

                # Home should remain truthful before the shared cache is primed.
                # If cache-backed detail is not ready yet, fall back to the cheap
                # daemon status counts instead of showing a misleading zero-fleet view.
                if not device_list:
                    styrene_count = int(_get(status, "styrene_node_count", 0))
                    total_count = int(_get(status, "device_count", 0))
                else:
                    total_count = len(device_list)

                bar = self.query_one(HomeStatusBar)
                bar.daemon_connected = True
                bar.ipc_backpressured = ipc_backpressured
                bar.rns_online = bool(_get(status, "rns_initialized", True))
                ifaces = _get(status, "interfaces", [])
                bar.interface_count = len(ifaces) if isinstance(ifaces, list) else 0
                bar.daemon_uptime = float(_get(status, "uptime", 0))
                bar.transport_enabled = bool(_get(status, "transport_enabled", False))
                bar.propagation_enabled = bool(_get(status, "propagation_enabled", False))
                bar.active_links = int(_get(status, "active_links", 0))
                bar.styrene_mesh_count = styrene_count
                bar.total_device_count = total_count
                bar.unread_count = sum(unread_map.values())

                if isinstance(hub_data, dict):
                    hub_str = hub_data.get("status", "unknown")
                    try:
                        bar.hub_status = HubStatus(hub_str)
                    except (ValueError, KeyError):
                        bar.hub_status = HubStatus.UNKNOWN
            except Exception:
                pass

            try:
                from styrened.models.mesh_device import DeviceType, MeshDevice

                table = self.query_one(HomeNodeSummaryTable)
                nodes = []
                for d in device_list:
                    try:
                        if isinstance(d, MeshDevice):
                            nodes.append(d)
                        else:
                            dt_str = _get(d, "device_type", "unknown")
                            try:
                                dt = DeviceType(dt_str)
                            except (ValueError, KeyError):
                                dt = DeviceType.UNKNOWN
                            nodes.append(MeshDevice(
                                destination_hash=_get(d, "destination_hash", ""),
                                identity_hash=_get(d, "identity_hash", ""),
                                name=_get(d, "name", ""),
                                device_type=dt,
                                last_announce=int(_get(d, "last_announce", 0)),
                                discovered_via=_get(d, "discovered_via", None),
                                hops=_get(d, "hops", None),
                                lxmf_destination_hash=_get(d, "lxmf_destination_hash", None),
                            ))
                    except Exception:
                        pass

                table.update_nodes(nodes, unread_map)

                try:
                    cop_summary = self.query_one(CopActivitySummary)
                    name_map: dict[str, str] = {}
                    for node in nodes:
                        ih = getattr(node, "identity_hash", "")
                        name = getattr(node, "name", "") or ""
                        if ih and name:
                            name_map[ih] = name

                    hub_str = ""
                    try:
                        bar = self.query_one(HomeStatusBar)
                        hub_str = bar.hub_status.value if bar.hub_status else ""
                    except Exception:
                        pass

                    self._situation_tracker.update_from_state(
                        nodes=nodes,
                        unread_map=unread_map,
                        hub_status=hub_str,
                        node_name_map=name_map,
                    )
                    cop_summary.apply_snapshot(self._situation_tracker.snapshot())
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    async def _fetch_adapter_state(self) -> None:
        """Pull current adapter states from daemon on connect.

        Avoids the up-to-30-second wait for the first probe cycle event by
        querying the daemon directly.  Synthesises DaemonEvents so the normal
        on_daemon_event → AdapterStatusTracker → AdapterStatusBar path handles
        the result without any special-casing.
        """
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            adapters = await bridge.get_adapter_state()
            for entry in adapters:
                self.post_message(DaemonEvent(
                    event_type="adapter_changed",
                    action=entry.get("state", "probing"),
                    data={
                        "adapter_name": entry.get("adapter_name", ""),
                        "state": entry.get("state", "probing"),
                        "prev": "probing",
                    },
                ))
        except Exception:
            pass  # Daemon may not support this yet; probe events will catch up

    async def _subscribe_activity(self) -> None:
        """Subscribe to activity events via IPC — ephemeral events only.

        Store-backed situations (nodes, unread, hub) are handled by the
        polling cycle in ``_fetch_daemon_status()``.  This subscription
        only feeds ephemeral events (file transfers, PQC) that aren't
        in the stores.
        """
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            await bridge.subscribe_activity()
            async for event_type, event in bridge.iter_events(IPCMessageType.EVENT_ACTIVITY):
                if event_type != IPCMessageType.EVENT_ACTIVITY:
                    continue
                # Post DaemonEvent — on_daemon_event handles tracker + COP update
                evt_type = event.get("type", "unknown")
                self.post_message(DaemonEvent(
                    event_type=_ipc_type_to_bus_type(evt_type),
                    action=evt_type,
                    data=event,
                ))
        except Exception:
            pass
