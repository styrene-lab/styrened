"""COP Activity Summary — coalesced situation lines for the Home screen.

Unlike the Diagnostics ActivityFeedWidget (raw event firehose), this widget
answers 'what needs my attention?' with grouped, prioritized situation lines
derived from the current state of the node store and message database.

This widget is stateless — it re-derives situation lines each time
``update_from_state()`` is called with current data from the daemon.
No shadow state, no event ingestion, no dedup. Just render the truth.

Situation categories (priority order):
  1. NODE_ANOMALY  — node lost/stale, persists until recovered
  2. UNREAD        — new messages grouped by peer
  3. FILE_ACTIVITY — file offers/transfers (event-driven, ephemeral)
  4. SECURITY      — PQC session events (event-driven, ephemeral)
  5. HUB_STATUS    — hub connect/disconnect
  6. NODE_DISCOVERY — nodes discovered, coalesced per transport
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from textual.widget import Widget

from styrened.tui.widgets.highlighted_panel import get_color_cascade


# ---------------------------------------------------------------------------
# Transport label mapping
# ---------------------------------------------------------------------------

_TRANSPORT_LABELS: dict[str, str] = {
    "TCPClientInterface": "TCP",
    "TCPServerInterface": "TCP",
    "AutoInterface": "Auto",
    "RNodeInterface": "RNode",
    "I2PInterface": "I2P",
    "YggdrasilInterface": "Ygg",
    "UDPInterface": "UDP",
    "SerialInterface": "SER",
    "KISSInterface": "KISS",
    "PipeInterface": "Pipe",
    "MeshtasticBridge": "Mesh",
}


def transport_label(discovered_via: str | None) -> str:
    """Derive a short COP tag from a discovered_via string.

    Examples:
        "TCPClientInterface → 3a4b5c6d" → "TCP"
        "AutoInterface" → "Auto"
        None → "—"
    """
    if not discovered_via:
        return "—"
    # Strip next-hop suffix if present
    prefix = discovered_via.split(" → ")[0].split(" ")[0].strip()
    return _TRANSPORT_LABELS.get(prefix, prefix[:4] or "—")


# ---------------------------------------------------------------------------
# Situation model
# ---------------------------------------------------------------------------

class SituationPriority(IntEnum):
    """Lower value = higher priority (renders first)."""

    ANOMALY = 0
    ACTIONABLE = 1
    FILE = 2
    SECURITY = 3
    HUB = 4
    INFO = 5


_SITUATION_ICONS: dict[SituationPriority, str] = {
    SituationPriority.ANOMALY: "▲",
    SituationPriority.ACTIONABLE: "✉",
    SituationPriority.FILE: "◇",
    SituationPriority.SECURITY: "◆",
    SituationPriority.HUB: "●",
    SituationPriority.INFO: "●",
}


@dataclass
class SituationLine:
    """A single situation line for rendering."""

    priority: SituationPriority
    message: str
    transport_tag: str = "—"
    dim: bool = False


# Maximum lines to render
MAX_SITUATIONS = 6

# Ephemeral event TTL (seconds) — file/security events age out
_EPHEMERAL_TTL = 30 * 60  # 30 minutes


@dataclass
class _EphemeralEvent:
    """Short-lived event that doesn't come from the stores."""

    message: str
    priority: SituationPriority
    created_at: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------


class CopActivitySummary(Widget):
    """Coalesced situation summary for the COP Home screen.

    State-driven: call ``update_from_state()`` each poll cycle with current
    data from the daemon.  The widget derives situation lines from the truth
    rather than maintaining shadow state.

    For ephemeral events (file transfers, PQC) that aren't in the stores,
    call ``add_ephemeral()`` from the activity event subscription.
    """

    DEFAULT_CSS = """
    CopActivitySummary {
        height: auto;
        min-height: 3;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._situations: list[SituationLine] = []
        self._ephemeral_events: list[_EphemeralEvent] = []

    # ----- State-driven update ----------------------------------------------

    def update_from_state(
        self,
        nodes: list[Any],
        unread_map: dict[str, int] | None = None,
        hub_status: str | None = None,
        node_name_map: dict[str, str] | None = None,
    ) -> None:
        """Derive situation lines from current daemon state.

        Args:
            nodes: List of MeshDevice objects (or dicts with .discovered_via, .status, .name).
            unread_map: identity_hash → unread count.
            hub_status: Hub connection status string.
            node_name_map: identity_hash → display name for unread attribution.
        """
        situations: list[SituationLine] = []

        # --- NODE_ANOMALY: offline/stale nodes ---
        for node in nodes:
            status = _get_attr(node, "status", "")
            if hasattr(status, "value"):
                status = status.value
            if str(status).lower() in ("offline", "lost", "stale"):
                name = _get_attr(node, "name", "") or _get_attr(node, "destination_hash", "")[:8]
                via = _get_attr(node, "discovered_via", None)
                tag = transport_label(via)
                situations.append(SituationLine(
                    priority=SituationPriority.ANOMALY,
                    message=f"{name} lost [{tag}]",
                    transport_tag=tag,
                ))

        # --- UNREAD: grouped by peer ---
        if unread_map:
            total = sum(unread_map.values())
            if total > 0:
                name_map = node_name_map or {}
                peer_names = []
                for ih, count in sorted(unread_map.items(), key=lambda x: -x[1]):
                    if count > 0:
                        peer_names.append(name_map.get(ih, ih[:8]))
                display_names = ", ".join(peer_names[:3])
                extra = len(peer_names) - 3
                if extra > 0:
                    display_names += f" +{extra}"
                situations.append(SituationLine(
                    priority=SituationPriority.ACTIONABLE,
                    message=f"{total} unread from {display_names}",
                ))

        # --- Ephemeral events (file, security) ---
        now = time.monotonic()
        self._ephemeral_events = [e for e in self._ephemeral_events if now - e.created_at < _EPHEMERAL_TTL]
        for evt in self._ephemeral_events:
            age = now - evt.created_at
            situations.append(SituationLine(
                priority=evt.priority,
                message=evt.message,
                dim=age > 600,  # Dim after 10 minutes
            ))

        # --- HUB_STATUS ---
        if hub_status and hub_status.lower() not in ("connected", "unknown", ""):
            situations.append(SituationLine(
                priority=SituationPriority.HUB,
                message=f"hub {hub_status}",
            ))

        # --- NODE_DISCOVERY: coalesced per transport ---
        transport_counts: dict[str, int] = {}
        for node in nodes:
            status = _get_attr(node, "status", "")
            if hasattr(status, "value"):
                status = status.value
            if str(status).lower() in ("offline", "lost", "stale"):
                continue  # Already shown as anomaly
            via = _get_attr(node, "discovered_via", None)
            tag = transport_label(via)
            transport_counts[tag] = transport_counts.get(tag, 0) + 1

        for tag in sorted(transport_counts):
            count = transport_counts[tag]
            noun = "node" if count == 1 else "nodes"
            situations.append(SituationLine(
                priority=SituationPriority.INFO,
                message=f"{count} {noun} [{tag}]",
                transport_tag=tag,
            ))

        # Sort by priority, cap
        situations.sort(key=lambda s: s.priority)
        self._situations = situations[:MAX_SITUATIONS]
        self.refresh()

    # ----- Ephemeral event ingestion ----------------------------------------

    def add_ephemeral(self, event_type: str, payload: dict[str, Any]) -> None:
        """Ingest ephemeral events not tracked in stores (files, PQC).

        These age out after 30 minutes.  Store-backed situations (nodes,
        unread, hub) are handled by ``update_from_state()``.
        """
        peer = payload.get("peer_name") or payload.get("peer_hash", "")[:8] or "unknown"

        if event_type == "file_offer_received":
            filename = payload.get("metadata", {}).get("filename") or payload.get("filename", "file")
            self._ephemeral_events.append(_EphemeralEvent(
                message=f"file from {peer}: {filename}",
                priority=SituationPriority.FILE,
            ))
        elif event_type == "file_transfer_complete":
            filename = payload.get("metadata", {}).get("filename") or payload.get("filename", "file")
            self._ephemeral_events.append(_EphemeralEvent(
                message=f"transfer complete: {filename}",
                priority=SituationPriority.FILE,
            ))
        elif event_type == "pqc_established":
            self._ephemeral_events.append(_EphemeralEvent(
                message=f"PQC session with {peer}",
                priority=SituationPriority.SECURITY,
            ))
        elif event_type == "pqc_rekey":
            self._ephemeral_events.append(_EphemeralEvent(
                message=f"PQC rekey with {peer}",
                priority=SituationPriority.SECURITY,
            ))
        else:
            return  # Not an ephemeral COP event

        # Keep only last 4 ephemeral events
        self._ephemeral_events = self._ephemeral_events[-4:]
        self.refresh()

    # ----- Rendering --------------------------------------------------------

    def render(self) -> str:
        """Render priority-sorted situation lines as Rich markup."""
        cascade = get_color_cascade()

        if not self._situations:
            return f"[{cascade.dim}]  no recent activity[/]"

        lines: list[str] = []
        for sit in self._situations:
            icon = _SITUATION_ICONS.get(sit.priority, "●")
            if sit.dim:
                color = cascade.dim
            elif sit.priority == SituationPriority.ANOMALY:
                color = cascade.bright
            elif sit.priority == SituationPriority.ACTIONABLE:
                color = cascade.bright
            elif sit.priority == SituationPriority.INFO:
                color = cascade.medium
            else:
                color = cascade.medium
            lines.append(f"[{color}]  {icon} {sit.message}[/]")

        return "\n".join(lines)

    def clear_unread(self, peer_name: str | None = None) -> None:
        """Hint that unread was cleared — will reflect on next update_from_state()."""
        # No-op: unread is derived from store, not maintained here.
        # Kept for API compatibility.
        pass


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Get attribute from object or dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
