"""Adapter status model and tracker for the TUI.

AdapterStatusTracker ingests ``adapter_changed`` EventBus events (bridged
as ``DaemonEvent``) and maintains the latest per-adapter state.

``snapshot()`` returns an ``AdapterStatusSnapshot`` for widget rendering.
``get_situation_line()`` returns a ``SituationLine`` for the COP feed when
a noteworthy state transition occurred, or ``None`` otherwise.

State machine for situation lines (DISABLED→* always None):
  WARMING → READY      informational
  READY   → DEGRADED   anomaly (persists)
  DEGRADED → READY     informational
  all others           None
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from styrened.tui.models.cop_situation import SituationLine, SituationPriority

if TYPE_CHECKING:
    from styrened.tui.models.events import DaemonEvent


# ---------------------------------------------------------------------------
# Enums / state
# ---------------------------------------------------------------------------

class AdapterDisplayState(str, Enum):
    """Canonical adapter states visible to the TUI."""

    DISABLED = "disabled"
    PROBING = "probing"
    WARMING = "warming"
    READY = "ready"
    DEGRADED = "degraded"

    @classmethod
    def _missing_(cls, value: object) -> "AdapterDisplayState":
        """Map unknown values to PROBING rather than raising."""
        return cls.PROBING


# ---------------------------------------------------------------------------
# Snapshot (immutable render target)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdapterEntry:
    """State for one adapter in the snapshot."""

    name: str
    state: AdapterDisplayState
    detail: str = ""  # Optional short detail (e.g. latency, error message)


@dataclass
class AdapterStatusSnapshot:
    """Immutable render snapshot produced by ``AdapterStatusTracker.snapshot()``."""

    adapters: list[AdapterEntry]
    generated_at: float = field(default_factory=time.monotonic)

    @property
    def is_empty(self) -> bool:
        return len(self.adapters) == 0

    @property
    def has_degraded(self) -> bool:
        return any(a.state == AdapterDisplayState.DEGRADED for a in self.adapters)

    @property
    def all_disabled(self) -> bool:
        return all(a.state == AdapterDisplayState.DISABLED for a in self.adapters)


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

@dataclass
class _AdapterRecord:
    """Internal mutable state for one tracked adapter."""

    name: str
    state: AdapterDisplayState
    detail: str = ""
    updated_at: float = field(default_factory=time.monotonic)
    pending_situation: SituationLine | None = None  # emitted once then cleared


class AdapterStatusTracker:
    """Owns adapter status state.  Lives on DashboardScreen.

    Designed to match the CopSituationTracker API style:

        tracker = AdapterStatusTracker()
        tracker.ingest(daemon_event)          # from on_daemon_event
        snap = tracker.snapshot()             # for AdapterStatusBar
        line = tracker.get_situation_line()   # for COP feed (once per transition)
    """

    def __init__(self) -> None:
        self._adapters: dict[str, _AdapterRecord] = {}

    # ---- Event-driven intake ------------------------------------------------

    def ingest(self, event: "DaemonEvent") -> None:
        """Process a DaemonEvent.  Only ``adapter_changed`` events are handled.

        The event payload is expected to contain:
            ``adapter_name``  – str, adapter identifier
            ``state``         – str, new AdapterDisplayState value
            ``detail``        – str (optional), additional context
        """
        if event.event_type != "adapter_changed":
            return

        name: str = event.data.get("adapter_name") or event.data.get("name", "unknown")
        raw_state: str = event.data.get("state", "probing")
        detail: str = event.data.get("detail", "")

        new_state = AdapterDisplayState(raw_state.lower())

        if name in self._adapters:
            old_state = self._adapters[name].state
            situation = self._derive_situation(name, old_state, new_state)
        else:
            situation = None

        self._adapters[name] = _AdapterRecord(
            name=name,
            state=new_state,
            detail=detail,
            pending_situation=situation,
        )

    def _derive_situation(
        self,
        name: str,
        old: AdapterDisplayState,
        new: AdapterDisplayState,
    ) -> SituationLine | None:
        """Return a SituationLine for meaningful transitions, or None.

        Rules (DISABLED origin → always None):
          WARMING → READY      INFO
          READY   → DEGRADED   ANOMALY (persists)
          DEGRADED → READY     INFO
          all others           None
        """
        if old == AdapterDisplayState.DISABLED:
            return None

        if old == AdapterDisplayState.WARMING and new == AdapterDisplayState.READY:
            return SituationLine(
                priority=SituationPriority.INFO,
                message=f"{name} ready",
            )

        if old == AdapterDisplayState.READY and new == AdapterDisplayState.DEGRADED:
            return SituationLine(
                priority=SituationPriority.ANOMALY,
                message=f"{name} degraded",
            )

        if old == AdapterDisplayState.DEGRADED and new == AdapterDisplayState.READY:
            return SituationLine(
                priority=SituationPriority.INFO,
                message=f"{name} recovered",
            )

        return None

    # ---- Snapshot output ---------------------------------------------------

    def snapshot(self) -> AdapterStatusSnapshot:
        """Return the current state of all tracked adapters.

        Adapters are returned in insertion order (which is registration order
        in practice).  Callers must not mutate the returned snapshot.
        """
        entries = [
            AdapterEntry(name=r.name, state=r.state, detail=r.detail)
            for r in self._adapters.values()
        ]
        return AdapterStatusSnapshot(adapters=entries)

    def get_situation_line(self) -> SituationLine | None:
        """Return and consume the most recent pending situation line, if any.

        Callers should call this after ``ingest()`` and push the result into
        the CopSituationTracker if non-None.

        Only the most recently generated line is buffered.  If multiple
        adapters transition simultaneously, the last-ingested one wins.
        """
        for record in reversed(list(self._adapters.values())):
            if record.pending_situation is not None:
                line = record.pending_situation
                record.pending_situation = None
                return line
        return None
