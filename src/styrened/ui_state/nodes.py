"""Canonical node catalog state built from authoritative daemon snapshots."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from styrened.ui_state.base import (
    CapabilityState,
    FieldAuthority,
    KnowledgeState,
    LoadState,
    RefreshMeta,
)

_LOST_CUTOFF_SECONDS = 15 * 60
_STALE_CUTOFF_SECONDS = 5 * 60


class PresenceState(str, Enum):
    """Normalized presence state for a peer identity."""

    LIVE = "live"
    STORED = "stored"
    STALE = "stale"
    LOST = "lost"
    UNKNOWN = "unknown"


class RouteKind(str, Enum):
    """Known route/aspect kinds for a peer."""

    STYRENE = "styrene"
    NOMADNET = "nomadnet"
    LXMF = "lxmf"
    OTHER = "other"


@dataclass(frozen=True)
class RouteAspect:
    """A destination/aspect associated with a peer identity."""

    kind: RouteKind
    destination_hash: str
    device_type: str | None = None
    last_seen: float | None = None
    reachable: bool | None = None
    path_known: bool | None = None
    hops: int | None = None
    interface_name: str | None = None
    authority: FieldAuthority | None = None


@dataclass(frozen=True)
class OverlayAddressState:
    """Capability-gated overlay address/runtime summary for a peer."""

    network: str
    capability_state: CapabilityState = CapabilityState.UNSUPPORTED
    address: str | None = None
    endpoint: str | None = None
    knowledge: KnowledgeState = KnowledgeState.UNSUPPORTED
    authority: FieldAuthority | None = None


@dataclass(frozen=True)
class PeerRelationshipState:
    """Local operator relationship metadata for a peer."""

    alias: str | None = None
    blocked: bool = False
    unread_count: int = 0
    rbac_role: str | None = None
    in_my_mesh: bool = False


@dataclass(frozen=True)
class NodeAuthorityState:
    """Field-level provenance for a canonical node record."""

    name: FieldAuthority | None = None
    capabilities: FieldAuthority | None = None
    ygg_address: FieldAuthority | None = None
    i2p_address: FieldAuthority | None = None
    last_seen: FieldAuthority | None = None


@dataclass(frozen=True)
class NodeRecord:
    """Canonical identity-centric peer record."""

    identity_hash: str
    display_name: str
    operator_label: str | None = None
    presence: PresenceState = PresenceState.UNKNOWN
    last_seen: float | None = None
    primary_destination_hash: str | None = None
    routes: tuple[RouteAspect, ...] = ()
    capabilities: frozenset[str] = frozenset()
    ygg: OverlayAddressState = field(
        default_factory=lambda: OverlayAddressState(network="yggdrasil")
    )
    i2p: OverlayAddressState = field(default_factory=lambda: OverlayAddressState(network="i2p"))
    relationship: PeerRelationshipState = field(default_factory=PeerRelationshipState)
    authority: NodeAuthorityState = field(default_factory=NodeAuthorityState)
    status_summary: str | None = None


@dataclass(frozen=True)
class NodeCatalogState:
    """Canonical normalized node catalog."""

    nodes: tuple[NodeRecord, ...]
    by_identity: dict[str, NodeRecord]
    by_destination: dict[str, str]
    refresh: RefreshMeta = field(default_factory=RefreshMeta)


@dataclass(frozen=True)
class NodeCatalogInputs:
    """Explicit authoritative inputs for node catalog construction."""

    devices: tuple[object, ...]
    unread_counts: dict[str, int] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    blocked_identities: frozenset[str] = frozenset()
    local_identity_hash: str | None = None
    now: float | None = None


def classify_presence(last_seen: float | None, *, now: float | None = None) -> PresenceState:
    """Classify a peer's normalized presence from its last-seen time."""
    if not last_seen:
        return PresenceState.UNKNOWN

    now = now if now is not None else time.time()
    elapsed = now - last_seen
    if elapsed < _STALE_CUTOFF_SECONDS:
        return PresenceState.LIVE
    if elapsed < _LOST_CUTOFF_SECONDS:
        return PresenceState.STALE
    return PresenceState.LOST


def _get_name(device: object) -> str:
    return str(getattr(device, "name", "") or "")


def _get_identity_key(device: object) -> str:
    identity_hash = str(getattr(device, "identity_hash", "") or "")
    if identity_hash:
        return identity_hash
    return str(getattr(device, "destination_hash", "") or "")


def _get_capabilities(device: object) -> frozenset[str]:
    raw = getattr(device, "capabilities", None)
    if not raw:
        return frozenset()
    if isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset(str(item) for item in raw if item)
    return frozenset()


def _route_kind(device: object) -> RouteKind:
    device_type = str(getattr(device, "device_type", "") or "").lower()
    if device_type == "styrene":
        return RouteKind.STYRENE
    if device_type == "nomadnet_node":
        return RouteKind.NOMADNET
    if getattr(device, "lxmf_destination_hash", None):
        return RouteKind.LXMF
    return RouteKind.OTHER


def _build_routes(device_group: tuple[object, ...]) -> tuple[RouteAspect, ...]:
    routes: list[RouteAspect] = []
    seen: set[str] = set()
    for device in device_group:
        destination_hash = str(getattr(device, "destination_hash", "") or "")
        if not destination_hash or destination_hash in seen:
            continue
        seen.add(destination_hash)
        routes.append(
            RouteAspect(
                kind=_route_kind(device),
                destination_hash=destination_hash,
                device_type=str(getattr(device, "device_type", "") or "") or None,
                last_seen=float(getattr(device, "last_announce", 0.0) or 0.0) or None,
                hops=getattr(device, "hops", None),
                interface_name=getattr(device, "discovered_via", None),
                authority=FieldAuthority(source="ipc", observed_at=float(getattr(device, "last_announce", 0.0) or 0.0) or None),
            )
        )
    routes.sort(key=lambda route: route.last_seen or 0.0, reverse=True)
    return tuple(routes)


def _select_primary_destination(device_group: tuple[object, ...]) -> str | None:
    preferred = sorted(
        device_group,
        key=lambda device: (
            0 if str(getattr(device, "device_type", "") or "") == "styrene" else 1,
            -(float(getattr(device, "last_announce", 0.0) or 0.0)),
            -(int(getattr(device, "announce_count", 0) or 0)),
        ),
    )
    if not preferred:
        return None
    destination_hash = str(getattr(preferred[0], "destination_hash", "") or "")
    return destination_hash or None


def _select_display_name(device_group: tuple[object, ...], *, alias: str | None = None) -> str:
    if alias:
        return alias
    names = [name for name in (_get_name(device) for device in device_group) if name]
    if names:
        return max(names, key=len)
    primary_destination = _select_primary_destination(device_group)
    return primary_destination or _get_identity_key(device_group[0]) or "unknown"


def _build_overlay_state(
    *,
    network: str,
    device_group: tuple[object, ...],
    capability_name: str,
    address_attr: str,
) -> OverlayAddressState:
    all_capabilities = frozenset().union(*(_get_capabilities(device) for device in device_group))
    has_capability = capability_name in all_capabilities
    address = next(
        (
            str(value)
            for value in (getattr(device, address_attr, None) for device in device_group)
            if value
        ),
        None,
    )
    if address:
        return OverlayAddressState(
            network=network,
            capability_state=CapabilityState.AVAILABLE,
            address=address,
            knowledge=KnowledgeState.KNOWN,
            authority=FieldAuthority(source="ipc", complete=True),
        )
    if has_capability:
        return OverlayAddressState(
            network=network,
            capability_state=CapabilityState.UNAVAILABLE,
            knowledge=KnowledgeState.UNKNOWN,
            authority=FieldAuthority(source="ipc", complete=False),
        )
    return OverlayAddressState(network=network)


def build_node_record(
    identity_hash: str,
    device_group: tuple[object, ...],
    *,
    unread_count: int = 0,
    alias: str | None = None,
    blocked: bool = False,
    local_identity_hash: str | None = None,
    now: float | None = None,
) -> NodeRecord:
    """Build a canonical peer record from all known aspects for one identity."""
    latest_seen = max(float(getattr(device, "last_announce", 0.0) or 0.0) for device in device_group)
    presence = classify_presence(latest_seen or None, now=now)
    capabilities = frozenset().union(*(_get_capabilities(device) for device in device_group))
    display_name = _select_display_name(device_group, alias=alias)
    primary_destination_hash = _select_primary_destination(device_group)
    routes = _build_routes(device_group)

    relationship = PeerRelationshipState(
        alias=alias,
        blocked=blocked,
        unread_count=unread_count,
        in_my_mesh=bool(local_identity_hash and identity_hash == local_identity_hash),
    )

    authority = NodeAuthorityState(
        name=FieldAuthority(source="ipc", observed_at=latest_seen or None),
        capabilities=FieldAuthority(source="ipc", observed_at=latest_seen or None),
        ygg_address=FieldAuthority(source="ipc", observed_at=latest_seen or None, complete=False)
        if any(getattr(device, "ygg_address", None) or "yggdrasil" in _get_capabilities(device) for device in device_group)
        else None,
        i2p_address=FieldAuthority(source="ipc", observed_at=latest_seen or None, complete=False)
        if any(getattr(device, "b32_address", None) or "i2p" in _get_capabilities(device) for device in device_group)
        else None,
        last_seen=FieldAuthority(source="ipc", observed_at=latest_seen or None),
    )

    return NodeRecord(
        identity_hash=identity_hash,
        display_name=display_name,
        presence=presence,
        last_seen=latest_seen or None,
        primary_destination_hash=primary_destination_hash,
        routes=routes,
        capabilities=capabilities,
        ygg=_build_overlay_state(
            network="yggdrasil",
            device_group=device_group,
            capability_name="yggdrasil",
            address_attr="ygg_address",
        ),
        i2p=_build_overlay_state(
            network="i2p",
            device_group=device_group,
            capability_name="i2p",
            address_attr="b32_address",
        ),
        relationship=relationship,
        authority=authority,
        status_summary=presence.value,
    )


def merge_node_inputs_by_identity(devices: tuple[object, ...]) -> dict[str, list[object]]:
    """Group authoritative device snapshots by canonical peer identity."""
    grouped: dict[str, list[object]] = {}
    for device in devices:
        key = _get_identity_key(device)
        if not key:
            continue
        grouped.setdefault(key, []).append(device)
    return grouped


def build_node_catalog(inputs: NodeCatalogInputs) -> NodeCatalogState:
    """Build the canonical identity-centric node catalog."""
    now = inputs.now if inputs.now is not None else time.time()
    grouped = merge_node_inputs_by_identity(inputs.devices)
    nodes: list[NodeRecord] = []
    by_destination: dict[str, str] = {}

    for identity_hash, group in grouped.items():
        alias = inputs.aliases.get(identity_hash)
        record = build_node_record(
            identity_hash,
            tuple(group),
            unread_count=inputs.unread_counts.get(identity_hash, 0),
            alias=alias,
            blocked=identity_hash in inputs.blocked_identities,
            local_identity_hash=inputs.local_identity_hash,
            now=now,
        )
        nodes.append(record)
        for route in record.routes:
            by_destination[route.destination_hash] = identity_hash

    nodes.sort(key=lambda node: ((node.last_seen or 0.0), node.display_name), reverse=True)
    by_identity = {node.identity_hash: node for node in nodes}

    return NodeCatalogState(
        nodes=tuple(nodes),
        by_identity=by_identity,
        by_destination=by_destination,
        refresh=RefreshMeta(load_state=LoadState.READY, refreshed_at=now),
    )
