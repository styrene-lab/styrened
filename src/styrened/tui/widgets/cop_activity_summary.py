"""COP Activity Summary — coalesced situation lines for the Home screen.

Unlike the Diagnostics ActivityFeedWidget (raw event firehose), this widget
answers 'what needs my attention?' with grouped, prioritized, aging summaries.

Situation categories (priority order):
  1. NODE_ANOMALY  — node lost/stale, persists until recovered
  2. UNREAD        — new messages grouped by peer
  3. FILE_ACTIVITY — file offers/transfers
  4. SECURITY      — PQC session events
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

# Default TTL for resolved situations (seconds)
_RESOLVED_TTL = 30 * 60  # 30 minutes


@dataclass
class SituationLine:
    """A single coalesced situation line."""

    priority: SituationPriority
    message: str
    created_at: float = field(default_factory=time.monotonic)
    resolved_at: float | None = None

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.created_at

    @property
    def resolved_age(self) -> float:
        if self.resolved_at is None:
            return 0.0
        return time.monotonic() - self.resolved_at


# ---------------------------------------------------------------------------
# Event routing — which events the COP cares about
# ---------------------------------------------------------------------------

_COP_EVENT_TYPES = frozenset({
    "new_message",
    "device_discovered",
    "device_updated",
    "file_offer_received",
    "file_transfer_complete",
    "pqc_established",
    "pqc_rekey",
})


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

MAX_SITUATIONS = 6


def _relative_time(seconds: float) -> str:
    """Format seconds into a short relative string."""
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h ago"
    return f"{int(hours // 24)}d ago"


class CopActivitySummary(Widget):
    """Coalesced situation summary for the COP Home screen.

    Feed raw IPC events via ``ingest_event(event_type, payload)``.
    The widget coalesces them into prioritized situation lines and
    re-renders automatically.
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
        # Keyed situation state
        self._unread: dict[str, int] = {}  # peer_name → count
        self._unread_updated: float = 0.0
        self._discoveries: dict[str, tuple[int, float]] = {}  # transport_tag → (count, last_time)
        self._anomalies: dict[str, SituationLine] = {}  # node_name → situation
        self._hub_situation: SituationLine | None = None
        self._file_situations: list[SituationLine] = []
        self._security_situations: list[SituationLine] = []
        # Track known node transport tags for anomaly labeling
        self._node_transports: dict[str, str] = {}  # peer_hash → transport_tag

    # ----- Event ingestion --------------------------------------------------

    def ingest_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Ingest a raw activity event and coalesce into situation state."""
        if event_type not in _COP_EVENT_TYPES:
            return

        if event_type == "new_message":
            self._coalesce_unread(payload)
        elif event_type == "device_discovered":
            self._coalesce_node_discovery(payload)
        elif event_type == "device_updated":
            self._handle_device_updated(payload)
        elif event_type in ("file_offer_received", "file_transfer_complete"):
            self._handle_file_activity(event_type, payload)
        elif event_type in ("pqc_established", "pqc_rekey"):
            self._handle_security(event_type, payload)

        self._age_situations()
        self.refresh()

    # ----- Coalescing methods -----------------------------------------------

    def _coalesce_unread(self, payload: dict[str, Any]) -> None:
        is_outgoing = payload.get("is_outgoing", False)
        if is_outgoing:
            return
        peer = payload.get("peer_name") or payload.get("peer_hash", "")[:8] or "unknown"
        self._unread[peer] = self._unread.get(peer, 0) + 1
        self._unread_updated = time.monotonic()

    def _coalesce_node_discovery(self, payload: dict[str, Any]) -> None:
        via = payload.get("metadata", {}).get("discovered_via") or payload.get("discovered_via")
        tag = transport_label(via)
        peer_hash = payload.get("peer_hash", "")
        if peer_hash:
            self._node_transports[peer_hash] = tag
        count, _ = self._discoveries.get(tag, (0, 0.0))
        self._discoveries[tag] = (count + 1, time.monotonic())
        # If this node was previously anomalous, resolve it
        name = payload.get("metadata", {}).get("name") or payload.get("name") or peer_hash[:8]
        if name in self._anomalies:
            self._anomalies[name].resolved_at = time.monotonic()

    def _handle_device_updated(self, payload: dict[str, Any]) -> None:
        status = payload.get("metadata", {}).get("status") or payload.get("status", "")
        name = payload.get("metadata", {}).get("name") or payload.get("name") or payload.get("peer_hash", "")[:8]
        peer_hash = payload.get("peer_hash", "")
        tag = self._node_transports.get(peer_hash, "—")

        if status.lower() in ("offline", "lost", "stale"):
            if name not in self._anomalies or self._anomalies[name].is_resolved:
                self._anomalies[name] = SituationLine(
                    priority=SituationPriority.ANOMALY,
                    message=f"{name} lost {_relative_time(0)} [{tag}]",
                )
                # Store tag for re-rendering with updated time
                self._anomalies[name]._transport_tag = tag  # type: ignore[attr-defined]
        elif status.lower() in ("active", "online"):
            if name in self._anomalies:
                self._anomalies[name].resolved_at = time.monotonic()

    def _handle_file_activity(self, event_type: str, payload: dict[str, Any]) -> None:
        peer = payload.get("peer_name") or payload.get("peer_hash", "")[:8] or "unknown"
        filename = payload.get("metadata", {}).get("filename") or payload.get("filename", "file")
        if event_type == "file_offer_received":
            msg = f"file from {peer}: {filename}"
        else:
            msg = f"transfer complete: {filename}"
        self._file_situations.append(SituationLine(
            priority=SituationPriority.FILE,
            message=msg,
        ))
        # Keep only the 2 most recent
        self._file_situations = self._file_situations[-2:]

    def _handle_security(self, event_type: str, payload: dict[str, Any]) -> None:
        peer = payload.get("peer_name") or payload.get("peer_hash", "")[:8] or "unknown"
        if event_type == "pqc_established":
            msg = f"PQC session with {peer}"
        else:
            msg = f"PQC rekey with {peer}"
        self._security_situations.append(SituationLine(
            priority=SituationPriority.SECURITY,
            message=msg,
        ))
        self._security_situations = self._security_situations[-2:]

    # ----- Aging ------------------------------------------------------------

    def _age_situations(self) -> None:
        """Remove resolved situations past TTL."""
        now = time.monotonic()
        # Age anomalies
        expired = [k for k, v in self._anomalies.items() if v.is_resolved and v.resolved_age > _RESOLVED_TTL]
        for k in expired:
            del self._anomalies[k]
        # Age discovery entries older than 30 min
        expired_disc = [k for k, (_, t) in self._discoveries.items() if now - t > _RESOLVED_TTL]
        for k in expired_disc:
            del self._discoveries[k]
        # Age file/security situations
        self._file_situations = [s for s in self._file_situations if s.age_seconds < _RESOLVED_TTL]
        self._security_situations = [s for s in self._security_situations if s.age_seconds < _RESOLVED_TTL]

    # ----- Rendering --------------------------------------------------------

    def render(self) -> str:
        """Render priority-sorted situation lines as Rich markup."""
        cascade = get_color_cascade()
        lines: list[tuple[int, str]] = []  # (priority, markup)

        # Anomalies (priority 0)
        for name, sit in self._anomalies.items():
            tag = getattr(sit, "_transport_tag", "—")
            age_str = _relative_time(sit.age_seconds)
            color = cascade.dim if sit.is_resolved else cascade.bright
            icon = _SITUATION_ICONS[SituationPriority.ANOMALY]
            resolved_suffix = " ✓" if sit.is_resolved else ""
            lines.append((
                SituationPriority.ANOMALY,
                f"[{color}]  {icon} {name} lost {age_str} [{tag}]{resolved_suffix}[/]",
            ))

        # Unread messages (priority 1)
        if self._unread:
            total = sum(self._unread.values())
            names = ", ".join(sorted(self._unread.keys())[:3])
            extra = len(self._unread) - 3
            if extra > 0:
                names += f" +{extra}"
            icon = _SITUATION_ICONS[SituationPriority.ACTIONABLE]
            lines.append((
                SituationPriority.ACTIONABLE,
                f"[{cascade.bright}]  {icon} {total} unread from {names}[/]",
            ))

        # File activity (priority 2)
        for sit in self._file_situations:
            color = cascade.dim if sit.age_seconds > 600 else cascade.bright
            icon = _SITUATION_ICONS[SituationPriority.FILE]
            lines.append((
                SituationPriority.FILE,
                f"[{color}]  {icon} {sit.message}[/]",
            ))

        # Security (priority 3)
        for sit in self._security_situations:
            color = cascade.dim if sit.age_seconds > 300 else cascade.medium
            icon = _SITUATION_ICONS[SituationPriority.SECURITY]
            lines.append((
                SituationPriority.SECURITY,
                f"[{color}]  {icon} {sit.message}[/]",
            ))

        # Hub status (priority 4)
        if self._hub_situation and self._hub_situation.age_seconds < _RESOLVED_TTL:
            sit = self._hub_situation
            color = cascade.dim if sit.age_seconds > 600 else cascade.medium
            icon = _SITUATION_ICONS[SituationPriority.HUB]
            lines.append((
                SituationPriority.HUB,
                f"[{color}]  {icon} {sit.message}[/]",
            ))

        # Node discovery (priority 5) — one line per transport tag
        for tag, (count, last_time) in sorted(self._discoveries.items()):
            age = time.monotonic() - last_time
            color = cascade.dim if age > 600 else cascade.medium
            icon = _SITUATION_ICONS[SituationPriority.INFO]
            noun = "node" if count == 1 else "nodes"
            lines.append((
                SituationPriority.INFO,
                f"[{color}]  {icon} {count} {noun} discovered [{tag}][/]",
            ))

        # Sort by priority, cap at MAX_SITUATIONS
        lines.sort(key=lambda x: x[0])
        lines = lines[:MAX_SITUATIONS]

        if not lines:
            return f"[{cascade.dim}]  no recent activity[/]"

        return "\n".join(markup for _, markup in lines)

    def clear_unread(self, peer_name: str | None = None) -> None:
        """Clear unread counts — called when user reads messages."""
        if peer_name is None:
            self._unread.clear()
        else:
            self._unread.pop(peer_name, None)
        self.refresh()
