"""TUI utility functions.

Pure helper functions shared across TUI screens and widgets.
Factored out of daemon services to allow TUI code to operate
without importing daemon internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from styrened.models.mesh_device import MeshDevice


def _deduplicate_by_identity(devices: list[MeshDevice]) -> list[MeshDevice]:
    """Deduplicate devices by identity_hash.

    The same node announces on multiple destinations (operator + LXMF).
    Keep the entry with the richest metadata (prefer STYRENE_NODE type,
    then most recent announce, then most announce counts).

    Also filters out devices that have been LOST for more than 30 minutes
    to prevent stale ghosts from cluttering the device table.

    This is a pure function — no daemon service imports required.

    Args:
        devices: List of MeshDevice instances (may contain duplicates).

    Returns:
        Deduplicated list of MeshDevice instances.
    """
    from datetime import datetime as _dt

    cutoff = _dt.now().timestamp() - 1800  # 30 minutes

    by_identity: dict[str, MeshDevice] = {}
    for device in devices:
        # Skip stale ghosts — LOST for more than 30 minutes
        if device.last_announce < cutoff:
            continue
        key = device.identity_hash or device.destination_hash
        existing = by_identity.get(key)
        if existing is None:
            by_identity[key] = device
        else:
            # Prefer STYRENE_NODE over other types
            if device.is_styrene_node and not existing.is_styrene_node:
                by_identity[key] = device
            elif device.is_styrene_node == existing.is_styrene_node:
                # Same type — prefer most recent announce
                if device.last_announce > existing.last_announce:
                    by_identity[key] = device
            # Merge LXMF destination if the winner doesn't have one
            winner = by_identity[key]
            if not winner.lxmf_destination_hash and device.lxmf_destination_hash:
                winner.lxmf_destination_hash = device.lxmf_destination_hash
    return list(by_identity.values())
