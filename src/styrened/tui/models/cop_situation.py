"""COP situation tracker — canonical state for the Home COP activity panel.

The tracker owns all situation state and is held by DashboardScreen.
It is fed from two sources:
- ``update_from_state()``  — called each poll cycle with store-backed data
- ``ingest(DaemonEvent)``  — called immediately on event-driven updates

``snapshot()`` returns a sorted, capped ``CopSituationSnapshot`` for the
presentation widget to render.  The widget itself has no state.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from styrened.tui.models.events import DaemonEvent

# ---------------------------------------------------------------------------
# Transport label mapping (lives here — shared by tracker and widget)
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

    Examples::

        "TCPClientInterface → 3a4b5c6d" → "TCP"
        "AutoInterface"                 → "Auto"
        None                            → "—"
    """
    if not discovered_via:
        return "—"
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
    """A single renderable situation line."""

    priority: SituationPriority
    message: str
    transport_tag: str = "—"
    dim: bool = False

    @property
    def icon(self) -> str:
        return _SITUATION_ICONS.get(self.priority, "●")


@dataclass
class CopSituationSnapshot:
    """Immutable render snapshot produced by ``CopSituationTracker.snapshot()``."""

    lines: list[SituationLine]
    generated_at: float = field(default_factory=time.monotonic)

    @property
    def is_empty(self) -> bool:
        return len(self.lines) == 0


# ---------------------------------------------------------------------------
# Tracker internals
# ---------------------------------------------------------------------------

MAX_SITUATIONS = 6
_EPHEMERAL_TTL = 30 * 60   # seconds — drop after 30 min
_EPHEMERAL_DIM = 10 * 60   # seconds — dim after 10 min
_MAX_EPHEMERALS = 4         # cap on retained ephemeral events


@dataclass
class _Ephemeral:
    message: str
    priority: SituationPriority
    created_at: float = field(default_factory=time.monotonic)


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Get attribute from an object or dict uniformly."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _node_status_str(node: Any) -> str:
    """Normalize node status to a lowercase string."""
    raw = _get_attr(node, "status", "")
    if hasattr(raw, "value"):
        raw = raw.value
    return str(raw).lower().split(".")[-1]


# ---------------------------------------------------------------------------
# CopSituationTracker
# ---------------------------------------------------------------------------

class CopSituationTracker:
    """Owns all COP activity state.  Lives on DashboardScreen.

    Store-backed situations (node anomalies, unread counts, hub state) are
    re-derived each time ``update_from_state()`` is called — no shadow
    accumulation required because the stores are the source of truth.

    Ephemeral situations (file transfers, PQC events) are not in the stores
    so they are retained in ``_ephemerals`` with a TTL.  ``ingest()`` adds
    them from ``DaemonEvent`` dispatched by ``DashboardScreen.on_daemon_event``.
    """

    def __init__(self) -> None:
        self._ephemerals: list[_Ephemeral] = []
        # Latest store-backed snapshot
        self._nodes: list[Any] = []
        self._unread_map: dict[str, int] = {}
        self._hub_status: str = ""
        self._node_name_map: dict[str, str] = {}

    # ---- Event-driven intake -----------------------------------------------

    def ingest(self, event: "DaemonEvent") -> None:
        """Route a DaemonEvent into ephemeral situations.

        Only file and PQC events produce ephemeral situations.  Node,
        message-read, and hub events are handled via ``update_from_state()``
        on the next poll cycle (or triggered immediately by on_daemon_event
        launching a status refresh).
        """
        et = event.event_type
        action = event.action
        data = event.data

        peer = (
            data.get("peer_name")
            or (data.get("peer_hash") or "")[:8]
            or "unknown"
        )

        if et == "message_changed":
            if action == "file_offer":
                filename = (
                    (data.get("metadata") or {}).get("filename")
                    or data.get("filename", "file")
                )
                self._push_ephemeral(f"file from {peer}: {filename}", SituationPriority.FILE)
            elif action == "file_complete":
                filename = (
                    (data.get("metadata") or {}).get("filename")
                    or data.get("filename", "file")
                )
                self._push_ephemeral(f"transfer complete: {filename}", SituationPriority.FILE)

        elif et == "link_changed":
            if action == "pqc_established":
                self._push_ephemeral(f"PQC session with {peer}", SituationPriority.SECURITY)
            elif action == "pqc_rekey":
                self._push_ephemeral(f"PQC rekey with {peer}", SituationPriority.SECURITY)

    def _push_ephemeral(self, message: str, priority: SituationPriority) -> None:
        self._ephemerals.append(_Ephemeral(message=message, priority=priority))
        # Cap at max; keep the most recent
        if len(self._ephemerals) > _MAX_EPHEMERALS:
            self._ephemerals = self._ephemerals[-_MAX_EPHEMERALS:]

    # ---- Poll-cycle intake -------------------------------------------------

    def update_from_state(
        self,
        nodes: list[Any],
        unread_map: dict[str, int] | None = None,
        hub_status: str | None = None,
        node_name_map: dict[str, str] | None = None,
    ) -> None:
        """Absorb the latest store-backed state snapshot.

        Called by DashboardScreen._fetch_daemon_status().  Replaces the
        previous snapshot; does not merge or accumulate.
        """
        self._nodes = list(nodes)
        self._unread_map = dict(unread_map or {})
        self._hub_status = hub_status or ""
        self._node_name_map = dict(node_name_map or {})

    # ---- Snapshot output ---------------------------------------------------

    def snapshot(self) -> CopSituationSnapshot:
        """Build a sorted, capped snapshot ready for widget rendering.

        Ages out stale ephemerals before building.  Safe to call frequently.
        """
        now = time.monotonic()
        situations: list[SituationLine] = []

        # --- NODE_ANOMALY: stale nodes ---
        stale = [n for n in self._nodes if _node_status_str(n) == "stale"]
        if stale:
            count = len(stale)
            situations.append(SituationLine(
                priority=SituationPriority.ANOMALY,
                message=f"{count} node{'s' if count != 1 else ''} stale",
            ))

        # --- UNREAD: grouped by peer ---
        total_unread = sum(self._unread_map.values())
        if total_unread > 0:
            peers_by_count = [
                (ih, cnt)
                for ih, cnt in sorted(self._unread_map.items(), key=lambda x: -x[1])
                if cnt > 0
            ]
            peer_names = [self._node_name_map.get(ih, ih[:8]) for ih, _ in peers_by_count]
            display = ", ".join(peer_names[:3])
            if len(peer_names) > 3:
                display += f" +{len(peer_names) - 3}"
            situations.append(SituationLine(
                priority=SituationPriority.ACTIONABLE,
                message=f"{total_unread} unread from {display}",
            ))

        # --- HUB_STATUS ---
        if self._hub_status and self._hub_status.lower() not in ("connected", "unknown", ""):
            situations.append(SituationLine(
                priority=SituationPriority.HUB,
                message=f"hub {self._hub_status}",
            ))

        # --- EPHEMERALS: file, security (age out) ---
        self._ephemerals = [e for e in self._ephemerals if now - e.created_at < _EPHEMERAL_TTL]
        for evt in self._ephemerals:
            age = now - evt.created_at
            situations.append(SituationLine(
                priority=evt.priority,
                message=evt.message,
                dim=age > _EPHEMERAL_DIM,
            ))

        # --- NODE_DISCOVERY: active nodes coalesced per transport ---
        transport_counts: dict[str, int] = {}
        for node in self._nodes:
            if _node_status_str(node) != "active":
                continue
            tag = transport_label(_get_attr(node, "discovered_via", None))
            transport_counts[tag] = transport_counts.get(tag, 0) + 1

        for tag in sorted(transport_counts):
            count = transport_counts[tag]
            noun = "node" if count == 1 else "nodes"
            situations.append(SituationLine(
                priority=SituationPriority.INFO,
                message=f"{count} {noun} [{tag}]",
                transport_tag=tag,
            ))

        situations.sort(key=lambda s: s.priority)
        return CopSituationSnapshot(lines=situations[:MAX_SITUATIONS])
