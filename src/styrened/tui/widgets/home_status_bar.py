"""Home Status Bar — compact SCADA-style horizontal status indicator.

Renders a single-line pipe-delimited bar showing daemon/mesh status.
All-nominal state renders dim; anomalies promote to bright/warning colors.
"""

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from styrened.models.rns_error import RNSErrorState
from styrened.services.hub_connection import HubStatus


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
    daemon_connected: reactive[bool] = reactive(True)
    daemon_uptime: reactive[float] = reactive(0.0)
    unread_count: reactive[int] = reactive(0)
    error_state: reactive[RNSErrorState | None] = reactive(None)

    def render(self) -> Text:
        """Render the status bar as a Rich Text object."""
        segments: list[Text] = []

        # RNS status
        if self.rns_online:
            segments.append(Text("RNS ● online", style="dim"))
        else:
            style = "bold red" if self.error_state else "bold yellow"
            label = "RNS ○ offline"
            seg = Text(label, style=style)
            if self.error_state and self.error_state.message:
                seg.append(f" ({self.error_state.message})", style=style)
            segments.append(seg)

        # Interfaces
        segments.append(Text(f"IF {self.interface_count}", style="dim"))

        # Hub status
        if self.hub_status == HubStatus.CONNECTED:
            segments.append(Text("HUB ●", style="dim"))
        elif self.hub_status == HubStatus.DISABLED:
            segments.append(Text("HUB —", style="dim"))
        elif self.hub_status == HubStatus.DISCONNECTED:
            segments.append(Text("HUB ○ lost", style="bold yellow"))
        elif self.hub_status == HubStatus.WAITING:
            segments.append(Text("HUB ◐", style="dim"))

        # Mesh count
        segments.append(Text(f"MESH {self.styrene_mesh_count}", style="dim"))

        # Daemon
        if self.daemon_connected:
            uptime_str = self._format_uptime(self.daemon_uptime)
            segments.append(Text(f"IPC ● {uptime_str}", style="dim"))
        else:
            segments.append(Text("IPC ○", style="bold yellow"))

        # Unread
        if self.unread_count > 0:
            segments.append(Text(f"✉ {self.unread_count}", style="bold cyan"))

        # Join with pipe delimiter
        result = Text()
        for i, seg in enumerate(segments):
            if i > 0:
                result.append(" │ ", style="dim")
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
            # Guard against NoActiveAppError during init or testing
            pass

    watch_rns_online = _rerender
    watch_hub_status = _rerender
    watch_interface_count = _rerender
    watch_styrene_mesh_count = _rerender
    watch_daemon_connected = _rerender
    watch_daemon_uptime = _rerender
    watch_unread_count = _rerender
    watch_error_state = _rerender
