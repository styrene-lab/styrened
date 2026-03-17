"""Shared frontend-agnostic UI state primitives.

This package sits above authoritative daemon/IPC snapshots and below any
specific visual frontend. It provides pure typed state objects and builder
helpers; it does not own persistence, polling, or runtime service access.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LoadState(StrEnum):
    """Lifecycle state for a constructed UI snapshot."""

    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


class CapabilityState(StrEnum):
    """Availability of an optional daemon capability."""

    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    AVAILABLE = "available"


class KnowledgeState(StrEnum):
    """Whether a specific field value is known."""

    KNOWN = "known"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class DataIssue:
    """Structured issue attached to a state snapshot."""

    code: str
    message: str
    severity: str = "warning"
    field: str | None = None


@dataclass(frozen=True)
class FieldAuthority:
    """Provenance for a normalized field value."""

    source: str
    observed_at: float | None = None
    complete: bool = True


@dataclass(frozen=True)
class RefreshMeta:
    """Common refresh and degradation metadata for canonical UI state."""

    load_state: LoadState = LoadState.IDLE
    refreshed_at: float | None = None
    source: str = "ipc"
    stale: bool = False
    partial: bool = False
    error_message: str | None = None
    issues: tuple[DataIssue, ...] = ()
