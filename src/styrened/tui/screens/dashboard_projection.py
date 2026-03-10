"""Thin Textual-facing projection layer for Dashboard.

Consumes shared canonical ui_state objects and produces a presentation-oriented
snapshot for the dashboard tree without embedding Textual or IPC concerns into
`ui_state` itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from styrened.models.mesh_device import MeshDevice
from styrened.ui_state.nodes import NodeCatalogState, NodeRecord


@dataclass(frozen=True)
class DashboardTreeNodeProjection:
    """Single dashboard tree row projection."""

    identity_hash: str
    destination_hash: str | None
    device: MeshDevice
    node: NodeRecord
    unread_count: int = 0
    in_my_mesh: bool = False
    interface_group: str = "_direct"


@dataclass(frozen=True)
class DashboardTreeProjection:
    """Tree projection split into trusted and untrusted peers."""

    my_mesh: tuple[DashboardTreeNodeProjection, ...] = ()
    other_nodes: tuple[DashboardTreeNodeProjection, ...] = ()
    by_destination: dict[str, DashboardTreeNodeProjection] = field(default_factory=dict)


def _is_my_mesh(identity_hash: str, rbac: Any) -> bool:
    if rbac is None or not identity_hash:
        return False
    try:
        from styrened.models.rbac import Role

        return rbac.resolve_role(identity_hash) >= Role.PEER
    except Exception:
        return False


def build_dashboard_tree_projection(
    *,
    catalog: NodeCatalogState,
    devices_by_identity: dict[str, MeshDevice],
    unread_counts: dict[str, int] | None = None,
    rbac: Any = None,
) -> DashboardTreeProjection:
    """Project canonical node catalog into dashboard tree groups."""
    unread_counts = unread_counts or {}
    nodes: list[DashboardTreeNodeProjection] = []

    for node in catalog.nodes:
        identity_hash = node.identity_hash
        device = devices_by_identity.get(identity_hash)
        if device is None:
            continue
        destination_hash = device.destination_hash or node.primary_destination_hash
        nodes.append(
            DashboardTreeNodeProjection(
                identity_hash=identity_hash,
                destination_hash=destination_hash,
                device=device,
                node=node,
                unread_count=unread_counts.get(destination_hash or "", 0),
                in_my_mesh=_is_my_mesh(identity_hash, rbac),
                interface_group=device.discovered_via or "_direct",
            )
        )

    my_mesh = tuple(node for node in nodes if node.in_my_mesh)
    other_nodes = tuple(node for node in nodes if not node.in_my_mesh)
    by_destination = {
        node.destination_hash: node
        for node in nodes
        if node.destination_hash
    }
    return DashboardTreeProjection(
        my_mesh=my_mesh,
        other_nodes=other_nodes,
        by_destination=by_destination,
    )
