"""Announce-level capability bitmask for Styrene wire protocol.

These bits are encoded in the ``capabilities`` field of Styrene announces
(comma-separated string tokens in the wire format).  The module provides
a canonical string token per feature plus an integer bitmask representation
for compact serialisation in future wire-format revisions.

Usage::

    from styrened.models.capabilities import CAPABILITY_YGGDRASIL, has_capability

    if has_capability(device.capabilities, CAPABILITY_YGGDRASIL):
        # This node advertises Yggdrasil support — fetch /meta for its address
        ...
"""

from __future__ import annotations

__all__ = [
    "CAPABILITY_YGGDRASIL",
    "has_capability",
    "add_capability",
]

# ---------------------------------------------------------------------------
# String token constants (used in wire format and DB)
# ---------------------------------------------------------------------------

CAPABILITY_YGGDRASIL: str = "yggdrasil"
"""Token advertised in Styrene announces when the node has Yggdrasil running.

Receivers that see this capability SHOULD fetch the node's Ygg IPv6 address
via a DirectLink ``/meta`` request rather than reading it from the announce
(which keeps announce size LoRa-friendly).
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def has_capability(capabilities: list[str] | None, capability: str) -> bool:
    """Return True if *capability* is present in *capabilities*.

    Args:
        capabilities: Capability list from :class:`~styrened.models.mesh_device.MeshDevice`.
        capability:   Token to test (e.g. :data:`CAPABILITY_YGGDRASIL`).

    Returns:
        ``True`` when the list is non-empty and contains *capability*.
    """
    return capability in (capabilities or [])


def add_capability(capabilities: list[str] | None, capability: str) -> list[str]:
    """Return a new list with *capability* added (idempotent).

    Args:
        capabilities: Existing capability list (may be ``None``).
        capability:   Token to add.

    Returns:
        New list containing all previous tokens plus *capability* (deduplicated).
    """
    existing = list(capabilities or [])
    if capability not in existing:
        existing.append(capability)
    return existing
