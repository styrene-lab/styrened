"""Alert list widget — ephemeral, in-memory per TUI session.

Alerts derive from live daemon state and auto-resolve when the
underlying condition clears.  No persistence across restarts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import RichLog

from styrened.models.mesh_device import MeshDevice, NodeStatus
from styrened.tui.widgets.highlighted_panel import get_color_cascade


class AlertSeverity(Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class _Alert:
    alert_id: str
    severity: AlertSeverity
    message: str
    created_at: float = field(default_factory=time.monotonic)


_SEVERITY_ORDER = {AlertSeverity.CRITICAL: 0, AlertSeverity.WARNING: 1, AlertSeverity.INFO: 2}


class AlertListWidget(Widget):
    """Ephemeral per-session alert surface.

    Alerts are derived from live device state (LOST nodes, adapter errors, etc.)
    and auto-resolve when the underlying condition clears.

    Public API:
        derive_from_devices(devices): Re-derive alerts from current device list.
        add_alert(alert_id, severity, message): Inject an explicit alert.
        resolve_alert(alert_id): Remove an alert by ID.
    """

    DEFAULT_CSS = """
    AlertListWidget {
        height: 1fr;
    }
    AlertListWidget RichLog {
        height: 1fr;
        background: transparent;
        scrollbar-background: transparent;
        scrollbar-color: $border;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._alerts: dict[str, _Alert] = {}

    def compose(self) -> ComposeResult:
        yield RichLog(
            id="alert-log",
            max_lines=200,
            auto_scroll=False,
            markup=True,
        )

    def derive_from_devices(self, devices: list[MeshDevice]) -> None:
        """Derive and auto-resolve LOST-node alerts from current device state.

        New LOST nodes produce WARNING alerts.  Alerts for nodes that are no
        longer LOST are automatically removed.
        """
        # Build current LOST identity set
        lost_ids: set[str] = set()
        for d in devices:
            if d.status == NodeStatus.LOST:
                key = d.identity_hash or d.destination_hash
                if key:
                    lost_ids.add(key)

        # Add alerts for newly-LOST nodes
        for device in devices:
            if device.status != NodeStatus.LOST:
                continue
            key = device.identity_hash or device.destination_hash
            if not key:
                continue
            alert_id = f"lost:{key}"
            if alert_id not in self._alerts:
                name = device.name or (device.destination_hash[:8] if device.destination_hash else "?")
                self._alerts[alert_id] = _Alert(
                    alert_id=alert_id,
                    severity=AlertSeverity.WARNING,
                    message=f"{name} went LOST",
                )

        # Auto-resolve alerts for nodes that are no longer LOST
        stale_ids = [
            aid for aid in list(self._alerts)
            if aid.startswith("lost:") and aid[len("lost:"):] not in lost_ids
        ]
        for aid in stale_ids:
            del self._alerts[aid]

        self._redraw()

    def add_alert(self, alert_id: str, severity: AlertSeverity, message: str) -> None:
        """Add or update a named alert."""
        self._alerts[alert_id] = _Alert(
            alert_id=alert_id,
            severity=severity,
            message=message,
        )
        self._redraw()

    def resolve_alert(self, alert_id: str) -> None:
        """Remove a named alert (condition cleared)."""
        if alert_id in self._alerts:
            del self._alerts[alert_id]
            self._redraw()

    def _redraw(self) -> None:
        try:
            log = self.query_one("#alert-log", RichLog)
            log.clear()
            cascade = get_color_cascade()

            if not self._alerts:
                log.write(f"[{cascade.dim}]No active alerts[/]")
                return

            alerts = sorted(
                self._alerts.values(),
                key=lambda a: (_SEVERITY_ORDER.get(a.severity, 2), a.created_at),
            )
            for alert in alerts:
                if alert.severity == AlertSeverity.CRITICAL:
                    color = cascade.bright
                    prefix = "✗"
                elif alert.severity == AlertSeverity.WARNING:
                    color = cascade.medium
                    prefix = "△"
                else:
                    color = cascade.dim
                    prefix = "·"
                log.write(f"[{color}]{prefix} {alert.message}[/]")
        except Exception:
            pass
