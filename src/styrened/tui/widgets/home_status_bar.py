from __future__ import annotations
"""Home Status Bar — compact SCADA-style horizontal status indicator.

Renders a single-line pipe-delimited bar showing daemon/mesh status.
All-nominal state renders dim; anomalies promote to bright/warning colors.
"""

import logging

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from styrened.models.rns_error import RNSErrorState
from styrened.services.hub_connection import HubStatus
from styrened.tui.widgets.highlighted_panel import get_color_cascade

log = logging.getLogger(__name__)

# Max chars for error message in the status bar to stay within 76-col budget.
_MAX_ERROR_MSG_LEN = 20


class HomeStatusBar(Static):
    """Compact horizontal status bar for the Home screen.

    Displays RNS, hub, mesh, daemon, and unread status as a single
    pipe-delimited line. Nominal indicators are dim; anomalies are
    promoted to warning/error brightness.
    """

    DEFAULT_CSS = """
    HomeStatusBar {
        height: auto;
        width: 1fr;
    }
    """

    # Reactive properties
    rns_online: reactive[bool] = reactive(True)
    hub_status: reactive[HubStatus] = reactive(HubStatus.CONNECTED)
    interface_count: reactive[int] = reactive(0)
    styrene_mesh_count: reactive[int] = reactive(0)
    total_device_count: reactive[int] = reactive(0)
    daemon_connected: reactive[bool] = reactive(True)
    daemon_uptime: reactive[float] = reactive(0.0)
    unread_count: reactive[int] = reactive(0)
    error_state: reactive[RNSErrorState | None] = reactive(None)
    transport_enabled: reactive[bool] = reactive(False)
    propagation_enabled: reactive[bool] = reactive(False)
    active_links: reactive[int] = reactive(0)

    def render(self) -> Text:
        """Render the status bar as a Rich Text object."""
        c = get_color_cascade()
        segments: list[Text] = []

        # RNS status
        if self.rns_online:
            segments.append(Text("RNS ● online", style=c.dim))
        else:
            style = f"bold {c.color_danger}" if self.error_state else f"bold {c.color_warning}"
            label = "RNS ○ offline"
            seg = Text(label, style=style)
            if self.error_state and self.error_state.message:
                msg = self.error_state.message
                if len(msg) > _MAX_ERROR_MSG_LEN:
                    msg = msg[:_MAX_ERROR_MSG_LEN - 1] + "…"
                seg.append(f" ({msg})", style=style)
            segments.append(seg)

        # Interfaces
        segments.append(Text(f"IF {self.interface_count}", style=c.dim))

        # Hub status
        if self.hub_status == HubStatus.CONNECTED:
            segments.append(Text("HUB ●", style=c.dim))
        elif self.hub_status == HubStatus.DISABLED:
            segments.append(Text("HUB —", style=c.dim))
        elif self.hub_status == HubStatus.DISCONNECTED:
            segments.append(Text("HUB ○ lost", style=f"bold {c.color_warning}"))
        elif self.hub_status == HubStatus.WAITING:
            segments.append(Text("HUB ◐ connecting", style=c.medium))

        # Mesh count — show styrene/total if total differs
        if self.total_device_count > self.styrene_mesh_count:
            segments.append(Text(f"MESH {self.styrene_mesh_count}/{self.total_device_count}", style=c.dim))
        else:
            segments.append(Text(f"MESH {self.styrene_mesh_count}", style=c.dim))

        # Transport/Propagation roles — only show when enabled (operator needs to know)
        roles = []
        if self.transport_enabled:
            roles.append("T")
        if self.propagation_enabled:
            roles.append("P")
        if roles:
            segments.append(Text(f"{''.join(roles)}", style=c.medium))

        # Active links — only show when non-zero
        if self.active_links > 0:
            segments.append(Text(f"LNK {self.active_links}", style=c.medium))

        # Daemon — highlight recently-restarted (< 5 min) as a heads-up
        if self.daemon_connected:
            uptime_str = self._format_uptime(self.daemon_uptime)
            if self.daemon_uptime > 0 and self.daemon_uptime < 300:
                segments.append(Text(f"IPC ● {uptime_str}", style=f"bold {c.color_warning}"))
            else:
                segments.append(Text(f"IPC ● {uptime_str}", style=c.dim))
        else:
            segments.append(Text("IPC ○", style=f"bold {c.color_warning}"))

        # Unread
        if self.unread_count > 0:
            segments.append(Text(f"✉ {self.unread_count}", style=f"bold {c.bright}"))

        # Join with pipe delimiter
        result = Text()
        for i, seg in enumerate(segments):
            if i > 0:
                result.append(" │ ", style=c.dim)
            result.append(seg)

        return result

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """Format uptime duration to compact human string."""
        total = int(seconds)
        if total < 60:
            return f"{total}s"
        if total < 3600:
            return f"{total // 60}m"
        if total < 86400:
            h, m = divmod(total, 3600)
            m = m // 60
            return f"{h}h {m}m" if m else f"{h}h"
        d, rem = divmod(total, 86400)
        h = rem // 3600
        return f"{d}d {h}h" if h else f"{d}d"

    # Watchers — any reactive change triggers re-render
    def _rerender(self) -> None:
        """Re-render the status bar content."""
        try:
            self.update(self.render())
        except Exception:
            log.debug("HomeStatusBar._rerender failed", exc_info=True)

    def watch_rns_online(self) -> None:
        self._rerender()

    def watch_hub_status(self) -> None:
        self._rerender()

    def watch_interface_count(self) -> None:
        self._rerender()

    def watch_styrene_mesh_count(self) -> None:
        self._rerender()

    def watch_daemon_connected(self) -> None:
        self._rerender()

    def watch_daemon_uptime(self) -> None:
        self._rerender()

    def watch_unread_count(self) -> None:
        self._rerender()

    def watch_error_state(self) -> None:
        self._rerender()
