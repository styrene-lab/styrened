"""Thin Textual-facing projection helpers for Exploration/Nodes."""

from __future__ import annotations

from dataclasses import dataclass

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.ui_state.nodes import NodeCatalogState, NodeRecord


@dataclass(frozen=True)
class StyreneFleetRowProjection:
    """Projected row for the Styrene fleet table."""

    identity_hash: str
    device: MeshDevice
    node: NodeRecord


def build_styrene_fleet_projection(
    *,
    catalog: NodeCatalogState,
    devices: list[MeshDevice],
) -> tuple[StyreneFleetRowProjection, ...]:
    """Project canonical node catalog into Styrene fleet rows."""
    styrene_devices = [d for d in devices if d.device_type == DeviceType.STYRENE_NODE]
    devices_by_identity: dict[str, MeshDevice] = {}
    for device in styrene_devices:
        if not device.identity_hash:
            continue
        existing = devices_by_identity.get(device.identity_hash)
        if existing is None or float(device.last_announce or 0) > float(existing.last_announce or 0):
            devices_by_identity[device.identity_hash] = device

    rows: list[StyreneFleetRowProjection] = []
    for node in catalog.nodes:
        device = devices_by_identity.get(node.identity_hash)
        if device is None:
            continue
        rows.append(
            StyreneFleetRowProjection(
                identity_hash=node.identity_hash,
                device=device,
                node=node,
            )
        )
    return tuple(rows)
