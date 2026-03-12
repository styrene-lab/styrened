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
from textual.widgets import Footer, Header
from textual.worker import Worker

from styrened.ipc.protocol import IPCMessageType
from styrened.services.hub_connection import HubStatus
from styrened.tui.models.events import DaemonEvent
from styrened.tui.services.config import load_config

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
}


def _ipc_type_to_bus_type(ipc_type: str) -> str:
    """Convert IPC activity event type to coarse bus event type."""
    return _IPC_TO_BUS_TYPE.get(ipc_type, ipc_type)
from styrened.tui.services.reticulum import start_discovery
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

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge via typed services protocol."""
        try:
            return self.app.services.bridge  # type: ignore[union-attr]
        except Exception:
            return None

    def on_mount(self) -> None:
        """Initialise Home: start discovery, then fetch daemon state."""
        start_discovery()
        self._hub_retry_timer = self.set_interval(30.0, self._retry_hub_connection)
        # Slow reconciliation timer — belt-and-suspenders behind event-driven updates
        self._reconcile_timer = self.set_interval(60.0, self._reconcile)

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")
            self._activity_worker = self.run_worker(
                self._subscribe_activity(),
                group="dashboard-activity",
                exclusive=True,
            )

        # Focus a widget so Footer renders screen bindings
        self.call_later(self._refocus_default)

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
        self.call_later(self._refocus_default)

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")
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
        """Handle daemon events — trigger immediate refresh for relevant types.

        Debounces rapid events so fleet-boot bursts don't spawn redundant
        workers.  First event refreshes immediately; subsequent events
        within _EVENT_COOLDOWN are absorbed.
        """
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
        """Focus the first focusable child so Footer renders bindings."""
        try:
            from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable
            table = self.query_one(HomeNodeSummaryTable)
            table.focus()
        except Exception:
            pass

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

    def action_open_exploration(self) -> None:
        """Open the canonical Nodes workspace."""
        self.app.action_open_nodes()  # type: ignore[union-attr]

    def action_refresh(self) -> None:
        """Refresh Home status panels."""
        try:
            cop_summary = self.query_one(CopActivitySummary)
            cop_summary._ephemeral_events.clear()
            cop_summary.refresh()
        except Exception:
            pass

        self.notify("Refreshed")

        if self._ipc_bridge is not None:
            self.run_worker(self._fetch_daemon_status(), group="dashboard-status")

        try:
            self.app._check_for_updates()  # type: ignore[union-attr]
        except Exception:
            pass

    async def _fetch_daemon_status(self) -> None:
        """Fetch Home status from daemon and push into status bar + node table."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        import asyncio

        tasks = {
            "status": asyncio.create_task(bridge.get_status()),
            "hub": asyncio.create_task(bridge.get_hub_status()),
            "config": asyncio.create_task(bridge.get_core_config()),
            "mesh_devices": asyncio.create_task(bridge.get_devices(styrene_only=False)),
            "conversations": asyncio.create_task(bridge.get_conversations()),
        }

        try:
            try:
                status = await tasks["status"]
                hub_data = await tasks["hub"]
                core_config = await tasks["config"]
                all_devices = await tasks["mesh_devices"]
            except Exception:
                try:
                    bar = self.query_one(HomeStatusBar)
                    bar.daemon_connected = False
                except Exception:
                    pass
                return

            # --- Update HomeStatusBar ---
            try:
                bar = self.query_one(HomeStatusBar)
                bar.daemon_connected = True

                # RNS status — handle both dict and dataclass (DaemonStatus)
                def _get(obj: Any, key: str, default: Any = None) -> Any:
                    if isinstance(obj, dict):
                        return obj.get(key, default)
                    return getattr(obj, key, default)

                if status is not None:
                    bar.rns_online = bool(_get(status, "rns_initialized", True))
                    ifaces = _get(status, "interfaces", [])
                    bar.interface_count = len(ifaces) if isinstance(ifaces, list) else 0
                    bar.daemon_uptime = float(_get(status, "uptime", 0))
                    bar.transport_enabled = bool(_get(status, "transport_enabled", False))
                    bar.propagation_enabled = bool(_get(status, "propagation_enabled", False))
                    bar.active_links = int(_get(status, "active_links", 0))

                # Hub status
                if isinstance(hub_data, dict):
                    hub_str = hub_data.get("status", "unknown")
                    try:
                        bar.hub_status = HubStatus(hub_str)
                    except (ValueError, KeyError):
                        bar.hub_status = HubStatus.UNKNOWN

                # Mesh counts
                styrene_count = 0
                total_count = 0
                device_list: list[Any] = []
                if isinstance(all_devices, list):
                    device_list = all_devices
                    total_count = len(device_list)
                    styrene_count = sum(
                        1 for d in device_list
                        if _get(d, "device_type") in ("styrene_node", "styrene_hub", "styrene")
                    )
                bar.styrene_mesh_count = styrene_count
                bar.total_device_count = total_count
            except Exception:
                pass

            # --- Update HomeNodeSummaryTable ---
            try:
                from styrened.models.mesh_device import MeshDevice

                table = self.query_one(HomeNodeSummaryTable)
                nodes = []
                for d in device_list:
                    try:
                        if isinstance(d, MeshDevice):
                            nodes.append(d)
                        else:
                            # DeviceInfo dataclass or dict from IPC bridge
                            dt_str = _get(d, "device_type", "unknown")
                            try:
                                from styrened.models.mesh_device import DeviceType
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

                # Build unread map from conversations
                unread_map: dict[str, int] = {}
                try:
                    convs = await tasks["conversations"]
                    if isinstance(convs, list):
                        for c in convs:
                            if isinstance(c, dict):
                                ih = c.get("identity_hash", "")
                                unread = c.get("unread_count", 0)
                            else:
                                ih = getattr(c, "identity_hash", "")
                                unread = getattr(c, "unread_count", 0)
                            if ih and unread:
                                    unread_map[ih] = unread
                except Exception:
                    pass

                table.update_nodes(nodes, unread_map)

                # Update COP activity summary from current state
                try:
                    cop_summary = self.query_one(CopActivitySummary)
                    # Build identity_hash → name map for unread attribution
                    name_map: dict[str, str] = {}
                    for node in nodes:
                        ih = getattr(node, "identity_hash", "")
                        name = getattr(node, "name", "") or ""
                        if ih and name:
                            name_map[ih] = name

                    # Hub status string
                    hub_str = ""
                    try:
                        bar = self.query_one(HomeStatusBar)
                        hub_str = bar.hub_status.value if bar.hub_status else ""
                    except Exception:
                        pass

                    cop_summary.update_from_state(
                        nodes=nodes,
                        unread_map=unread_map,
                        hub_status=hub_str,
                        node_name_map=name_map,
                    )
                except Exception:
                    pass

                # Update unread count on status bar
                try:
                    bar = self.query_one(HomeStatusBar)
                    bar.unread_count = sum(unread_map.values())
                except Exception:
                    pass
            except Exception:
                pass

        finally:
            pending = [t for t in tasks.values() if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

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
                # Post DaemonEvent to app so any screen can handle it
                evt_type = event.get("type", "unknown")
                self.app.post_message(DaemonEvent(
                    event_type=_ipc_type_to_bus_type(evt_type),
                    action=evt_type,
                    data=event,
                ))
                try:
                    cop_summary = self.query_one(CopActivitySummary)
                    cop_summary.add_ephemeral(evt_type, event)
                except Exception:
                    pass
        except Exception:
            pass
