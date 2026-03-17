"""Canonical aggregate state for the Comms workspace."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from styrened.ui_state.base import CapabilityState, LoadState, RefreshMeta


class CommsMode(StrEnum):
    """Transport/session-aware submodes in the Comms workspace."""

    DIRECT = "direct"
    ACTIVE = "active"
    BRIDGES = "bridges"
    PRESENCE = "presence"


@dataclass(frozen=True)
class CommsCapability:
    """Capability-gated comms feature summary."""

    key: str
    title: str
    capability_state: CapabilityState
    description: str | None = None
    warning: str | None = None


@dataclass(frozen=True)
class CommsWorkspaceState:
    """Canonical aggregate snapshot for the Comms workspace."""

    active_mode: CommsMode
    available_modes: tuple[CommsMode, ...]
    direct_available: bool
    active_session_count: int
    bridge_capabilities: tuple[CommsCapability, ...]
    refresh: RefreshMeta = field(default_factory=RefreshMeta)


@dataclass(frozen=True)
class CommsWorkspaceInputs:
    """Authoritative inputs for comms workspace state."""

    active_mode: CommsMode | str | None = None
    direct_available: bool = False
    active_session_count: int = 0
    bridge_status: dict[str, object] | None = None
    now: float | None = None


_BRIDGE_TITLES = {
    "meshtastic": "Meshtastic",
    "yggdrasil": "Yggdrasil",
    "i2p": "I2P",
}


def _coerce_mode(value: CommsMode | str | None) -> CommsMode:
    if isinstance(value, CommsMode):
        return value
    if value is None:
        return CommsMode.DIRECT
    try:
        return CommsMode(str(value).lower())
    except ValueError:
        return CommsMode.DIRECT


def _bridge_capabilities(status: dict[str, object] | None) -> tuple[CommsCapability, ...]:
    if not status:
        return ()

    capabilities: list[CommsCapability] = []
    for key, raw in status.items():
        data = raw if isinstance(raw, dict) else {}
        available = bool(data.get("available", False))
        enabled = bool(data.get("enabled", False))
        capability_state = (
            CapabilityState.AVAILABLE if available else
            CapabilityState.UNAVAILABLE if enabled else
            CapabilityState.UNSUPPORTED
        )
        capabilities.append(
            CommsCapability(
                key=str(key),
                title=_BRIDGE_TITLES.get(str(key), str(key).replace("_", " ").title()),
                capability_state=capability_state,
                description=data.get("description") if isinstance(data.get("description"), str) else None,
                warning=data.get("warning") if isinstance(data.get("warning"), str) else None,
            )
        )
    return tuple(capabilities)


def build_comms_workspace_state(inputs: CommsWorkspaceInputs) -> CommsWorkspaceState:
    """Build a canonical aggregate Comms workspace snapshot."""
    now = inputs.now if inputs.now is not None else time.time()
    return CommsWorkspaceState(
        active_mode=_coerce_mode(inputs.active_mode),
        available_modes=(
            CommsMode.DIRECT,
            CommsMode.ACTIVE,
            CommsMode.BRIDGES,
            CommsMode.PRESENCE,
        ),
        direct_available=inputs.direct_available,
        active_session_count=max(0, int(inputs.active_session_count)),
        bridge_capabilities=_bridge_capabilities(inputs.bridge_status),
        refresh=RefreshMeta(load_state=LoadState.READY, refreshed_at=now),
    )
