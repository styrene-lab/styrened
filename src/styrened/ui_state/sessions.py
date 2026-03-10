"""Canonical ephemeral session and link state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum

from styrened.ui_state.base import LoadState, RefreshMeta


class SessionKind(str, Enum):
    """Known live session kinds."""

    DIRECT_LINK = "direct_link"
    RELAY = "relay"
    TERMINAL = "terminal"
    PAGE = "page"
    VPN_HANDSHAKE = "vpn_handshake"


class SessionStatus(str, Enum):
    """Normalized runtime state for a live session."""

    INACTIVE = "inactive"
    CONNECTING = "connecting"
    ACTIVE = "active"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True)
class SessionRecord:
    """Canonical ephemeral session record."""

    session_id: str
    kind: SessionKind
    peer_identity_hash: str | None = None
    status: SessionStatus = SessionStatus.INACTIVE
    link_type: str | None = None
    started_at: float | None = None
    last_activity_at: float | None = None
    bytes_in: int = 0
    bytes_out: int = 0
    status_text: str | None = None


@dataclass(frozen=True)
class SessionIndexState:
    """Canonical index of live sessions."""

    sessions: tuple[SessionRecord, ...]
    by_id: dict[str, SessionRecord]
    by_peer: dict[str, tuple[SessionRecord, ...]]
    refresh: RefreshMeta = field(default_factory=RefreshMeta)


@dataclass(frozen=True)
class SessionIndexInputs:
    """Explicit authoritative inputs for session index construction."""

    sessions: tuple[object, ...]
    now: float | None = None


def _session_kind(raw: object) -> SessionKind:
    value = str(getattr(raw, "kind", "") or getattr(raw, "session_kind", "") or "")
    try:
        return SessionKind(value)
    except ValueError:
        return SessionKind.DIRECT_LINK


def _session_status(raw: object) -> SessionStatus:
    value = str(getattr(raw, "status", "") or "inactive")
    try:
        return SessionStatus(value)
    except ValueError:
        return SessionStatus.INACTIVE


def build_session_index(inputs: SessionIndexInputs) -> SessionIndexState:
    """Build a canonical index of ephemeral runtime sessions."""
    now = inputs.now if inputs.now is not None else time.time()
    sessions: list[SessionRecord] = []
    by_peer: dict[str, list[SessionRecord]] = {}

    for raw in inputs.sessions:
        session_id = str(getattr(raw, "session_id", "") or getattr(raw, "id", "") or "")
        if not session_id:
            continue
        record = SessionRecord(
            session_id=session_id,
            kind=_session_kind(raw),
            peer_identity_hash=getattr(raw, "peer_identity_hash", None),
            status=_session_status(raw),
            link_type=getattr(raw, "link_type", None),
            started_at=getattr(raw, "started_at", None),
            last_activity_at=getattr(raw, "last_activity_at", None),
            bytes_in=int(getattr(raw, "bytes_in", 0) or 0),
            bytes_out=int(getattr(raw, "bytes_out", 0) or 0),
            status_text=getattr(raw, "status_text", None),
        )
        sessions.append(record)
        if record.peer_identity_hash:
            by_peer.setdefault(record.peer_identity_hash, []).append(record)

    sessions.sort(key=lambda record: record.last_activity_at or 0.0, reverse=True)
    return SessionIndexState(
        sessions=tuple(sessions),
        by_id={record.session_id: record for record in sessions},
        by_peer={peer: tuple(records) for peer, records in by_peer.items()},
        refresh=RefreshMeta(load_state=LoadState.READY, refreshed_at=now),
    )
