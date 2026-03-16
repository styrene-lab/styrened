"""Global COP Screen — monitor-first mesh operations dashboard.

Four zones:
  1. Aggregate health bar (top)             — HomeStatusBar with live node counts
  2. Fleet table (middle-left, largest)     — Health-sorted, Styrene-primary
  3. Alert list (middle-right)              — Ephemeral, auto-resolving alerts
  4. Activity feed (bottom)                 — Live subscription + ring-buffer backfill

Keybinding: g (app-level).
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.widgets import Footer, Header

from styrened.ipc.protocol import IPCMessageType
from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.models.events import DaemonEvent
from styrened.tui.screens.base import BridgeUnavailableError, StyreneScreen
from styrened.tui.widgets.activity_feed import ActivityFeedWidget
from styrened.tui.widgets.alert_list import AlertListWidget
from styrened.tui.widgets.global_cop_fleet_table import GlobalCopFleetTable
from styrened.tui.widgets.highlighted_panel import HighlightedPanel
from styrened.tui.widgets.home_status_bar import HomeStatusBar

log = logging.getLogger(__name__)

_STYRENE_TYPES = {DeviceType.STYRENE_NODE}

# Debounce device-change events to avoid bursty re-fetches
_EVENT_DEBOUNCE: float = 5.0


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute/key access that works on both dicts and dataclass-like objects."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class GlobalCopScreen(StyreneScreen[None]):
    """Monitor-first mesh COP workspace.

    Subscribes to activity at mount (not lazily) so the feed is live before
    the operator first looks at the screen.  The daemon ring buffer is
    backfilled on first load so the feed is never empty after attach.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "refresh_cop", "Refresh", show=True),
        Binding("tab", "toggle_scope", "Toggle scope", show=True),
        Binding("f", "toggle_scope", "Toggle scope", show=False),
    ]

    DEFAULT_CSS = """
    GlobalCopScreen {
        layout: vertical;
    }

    #cop-body {
        layout: horizontal;
        height: 1fr;
    }

    #cop-fleet-pane {
        width: 2fr;
        height: 1fr;
    }

    #cop-right-pane {
        width: 1fr;
        height: 1fr;
        layout: vertical;
    }

    #cop-alert-panel {
        height: 1fr;
    }

    #cop-activity-panel {
        height: 1fr;
    }
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._activity_worker = None
        self._last_event_refresh: float = 0.0

    # ------------------------------------------------------------------
    # StyreneScreen hooks
    # ------------------------------------------------------------------

    def _loading_message(self) -> str:
        return "Loading COP data…"

    async def _acquire_lanes(self) -> None:
        """Start activity subscription at mount/resume (not lazily)."""
        if self._activity_worker is not None:
            # Already running — don't double-subscribe
            return
        self._activity_worker = self.run_worker(
            self._subscribe_activity(),
            group="cop-activity",
            exclusive=False,
        )

    def _cleanup(self) -> None:
        """Cancel activity subscription on suspend/unmount."""
        if self._activity_worker is not None:
            self._activity_worker.cancel()
            self._activity_worker = None
        super()._cleanup()

    async def _load_data(self) -> None:
        """Fetch fleet state and populate all four zones."""
        bridge = self.bridge  # raises BridgeUnavailableError if not connected

        # --- Zone 1: aggregate health bar ---
        try:
            from styrened.services.hub_connection import HubStatus

            status = await bridge.get_status()
            hub_data = await bridge.get_hub_status()

            bar = self.query_one("#cop-status-bar", HomeStatusBar)
            bar.daemon_connected = True
            ifaces = _get(status, "interfaces", [])
            bar.interface_count = len(ifaces) if isinstance(ifaces, list) else 0
            bar.rns_online = bool(_get(status, "rns_initialized", True))
            bar.daemon_uptime = float(_get(status, "uptime", 0))
            bar.transport_enabled = bool(_get(status, "transport_enabled", False))
            bar.propagation_enabled = bool(_get(status, "propagation_enabled", False))
            bar.active_links = int(_get(status, "active_links", 0))

            if isinstance(hub_data, dict):
                hub_str = hub_data.get("status", "unknown")
                try:
                    bar.hub_status = HubStatus(hub_str)
                except (ValueError, KeyError):
                    bar.hub_status = HubStatus.UNKNOWN
        except BridgeUnavailableError:
            raise
        except Exception as e:
            log.debug("GlobalCOP: status fetch failed: %s", e)

        # --- Zone 2 + 3: fleet table and alert list ---
        devices = self._get_devices()
        try:
            table = self.query_one("#cop-fleet-table", GlobalCopFleetTable)
            table.load_devices(devices)
        except Exception as e:
            log.debug("GlobalCOP: fleet table update failed: %s", e)

        try:
            alerts = self.query_one("#cop-alert-list", AlertListWidget)
            alerts.derive_from_devices(devices)
        except Exception as e:
            log.debug("GlobalCOP: alert list update failed: %s", e)

        # Update node counts in health bar
        try:
            bar = self.query_one("#cop-status-bar", HomeStatusBar)
            styrene_count = sum(1 for d in devices if d.device_type in _STYRENE_TYPES)
            bar.styrene_mesh_count = styrene_count
            bar.total_device_count = len(devices)
        except Exception:
            pass

        # --- Zone 4: backfill activity feed on first load ---
        if not self._first_load_done:
            try:
                history = await bridge.get_activity_history(limit=200)
                feed = self.query_one("#cop-activity-feed", ActivityFeedWidget)
                feed.backfill_history(history)
            except Exception as e:
                log.debug("GlobalCOP: activity history backfill failed: %s", e)

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield HighlightedPanel(
            HomeStatusBar(id="cop-status-bar"),
            title="STATUS",
            id="cop-status-panel",
        )
        with Horizontal(id="cop-body"):
            with Container(id="cop-fleet-pane"):
                yield HighlightedPanel(
                    GlobalCopFleetTable(id="cop-fleet-table"),
                    title="FLEET  [Tab: toggle scope]",
                    id="cop-fleet-panel",
                )
            with Container(id="cop-right-pane"):
                yield HighlightedPanel(
                    AlertListWidget(id="cop-alert-list"),
                    title="ALERTS",
                    id="cop-alert-panel",
                )
                yield HighlightedPanel(
                    ActivityFeedWidget(id="cop-activity-feed"),
                    title="ACTIVITY",
                    id="cop-activity-panel",
                )
        yield Footer()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_daemon_event(self, event: DaemonEvent) -> None:
        """Debounce fleet state refresh on node-change events."""
        if event.event_type not in (
            "device_discovered", "device_updated", "device_lost",
            "node_changed",
        ):
            return

        import time as _time

        now = _time.monotonic()
        if (now - self._last_event_refresh) < _EVENT_DEBOUNCE:
            return
        self._last_event_refresh = now

        try:
            self.bridge  # guard: do nothing if bridge is gone
        except BridgeUnavailableError:
            return

        self.run_worker(self._load_data(), group="cop-refresh", exclusive=True)

    def on_device_cache_devices_updated(self, _message: Any) -> None:
        """Refresh fleet table when the shared device cache primes or updates."""
        devices = self._get_devices()
        try:
            table = self.query_one("#cop-fleet-table", GlobalCopFleetTable)
            table.load_devices(devices)
        except Exception:
            pass
        try:
            alerts = self.query_one("#cop-alert-list", AlertListWidget)
            alerts.derive_from_devices(devices)
        except Exception:
            pass
        try:
            bar = self.query_one("#cop-status-bar", HomeStatusBar)
            styrene_count = sum(1 for d in devices if d.device_type in _STYRENE_TYPES)
            bar.styrene_mesh_count = styrene_count
            bar.total_device_count = len(devices)
        except Exception:
            pass

    def on_global_cop_fleet_table_node_selected(
        self, event: GlobalCopFleetTable.NodeSelected
    ) -> None:
        """Push node detail screen without switching workspace."""
        from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

        self.app.push_screen(MeshDeviceDetailScreen(device_identity=event.identity_hash))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_refresh_cop(self) -> None:
        """Manual full refresh."""
        self._start_load()

    def action_toggle_scope(self) -> None:
        """Toggle fleet table between Styrene-only and full neighbourhood."""
        try:
            table = self.query_one("#cop-fleet-table", GlobalCopFleetTable)
            styrene_only = table.toggle_scope()
            scope_label = "Styrene" if styrene_only else "ALL"
            try:
                panel = self.query_one("#cop-fleet-panel", HighlightedPanel)
                panel.border_title = f"FLEET  [{scope_label} · Tab: toggle]"
            except Exception:
                pass
            scope_str = "Styrene nodes" if styrene_only else "all peers"
            self.notify(f"Fleet: {scope_str}", timeout=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_devices(self) -> list[MeshDevice]:
        """Return device list from the shared app device cache."""
        try:
            cache = getattr(self.app, "device_cache", None)
        except Exception:
            cache = None

        if cache is not None:
            try:
                cached = cache.get()
                if cached:
                    return list(cached)
            except Exception:
                pass

        # Fallback: live discovery
        try:
            from styrened.tui.services.reticulum import discover_devices
            return list(discover_devices())
        except Exception:
            return []

    async def _subscribe_activity(self) -> None:
        """Subscribe to daemon activity events and feed the activity widget.

        Called at mount/resume via _acquire_lanes so the feed is live before
        the operator first views the screen.
        """
        try:
            bridge = self.bridge
        except BridgeUnavailableError:
            return
        try:
            await bridge.subscribe_activity()
            async for event_type, event in bridge.iter_events(IPCMessageType.EVENT_ACTIVITY):
                if event_type != IPCMessageType.EVENT_ACTIVITY:
                    continue
                evt_type = event.get("type", "unknown")
                try:
                    feed = self.query_one("#cop-activity-feed", ActivityFeedWidget)
                    feed.add_event(evt_type, event)
                except Exception:
                    pass
                # Post DaemonEvent so on_daemon_event can debounce fleet refreshes
                self.post_message(DaemonEvent(
                    event_type=evt_type,
                    action=evt_type,
                    data=event,
                ))
        except Exception as e:
            log.debug("GlobalCOP: activity subscription ended: %s", e)
        finally:
            self._activity_worker = None
