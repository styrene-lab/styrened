"""TUI utility functions.

Pure helper functions shared across TUI screens and widgets.
Factored out of daemon services to allow TUI code to operate
without importing daemon internals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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


def device_info_to_mesh(info: Any) -> MeshDevice:
    """Convert a DeviceInfo dataclass from IPC to a MeshDevice.

    DeviceInfo is a dataclass with attribute access (not a dict).
    Used by dashboard, exploration, and any screen that fetches
    nodes from the daemon via ``bridge.get_nodes()``.

    Args:
        info: DeviceInfo instance (from IPC bridge).

    Returns:
        MeshDevice instance.
    """
    from styrened.models.mesh_device import DeviceType, MeshDevice

    # DeviceInfo.device_type is a string (enum .value, e.g. "styrene").
    # Convert to DeviceType enum safely.
    dt_str = getattr(info, "device_type", "unknown")
    try:
        device_type = DeviceType(dt_str)
    except ValueError:
        device_type = DeviceType.UNKNOWN

    return MeshDevice(
        destination_hash=getattr(info, "destination_hash", ""),
        identity_hash=getattr(info, "identity_hash", ""),
        name=getattr(info, "name", ""),
        device_type=device_type,
        last_announce=getattr(info, "last_announce", 0.0),
        announce_count=getattr(info, "announce_count", 0),
        discovered_via=getattr(info, "discovered_via", None),
        lxmf_destination_hash=getattr(info, "lxmf_destination_hash", None),
        short_name=getattr(info, "short_name", None),
        system_fingerprint=getattr(info, "system_fingerprint", None),
        hops=getattr(info, "hops", None),
    )
