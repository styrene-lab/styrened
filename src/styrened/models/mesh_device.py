"""Mesh device models for live Reticulum discovery.

These models represent devices discovered on the Reticulum mesh via announces,
as opposed to static fleet inventory.

IMPORTANT - Hash distinction:
- identity_hash: Hash of the RNS Identity public key. Used for RNS.Identity.recall()
                 to look up the identity before sending messages.
- destination_hash: Hash of identity + app_name + aspects. This is what RNS uses
                    for routing and is what appears in announce packets.

To send an LXMF message:
1. Call RNS.Identity.recall(identity_hash_bytes) to get the Identity object
2. Create RNS.Destination with that Identity + LXMF.APP_NAME + "delivery"
3. Send via LXMF router
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DeviceType(Enum):
    """Type of device discovered on the mesh."""

    STYRENE_NODE = "styrene_node"  # Node running Styrene endpoint
    RNODE = "rnode"  # RNode hardware device
    GENERIC = "generic"  # Generic Reticulum announce
    UNKNOWN = "unknown"  # Unable to determine type
    HUB = "hub"  # Hub/transport node


class NodeStatus(Enum):
    """Status of a mesh node based on announce activity."""

    ACTIVE = "active"  # Recently announced (< 5 min)
    STALE = "stale"  # No recent announces (5-15 min)
    LOST = "lost"  # Not seen in a while (> 15 min)


@dataclass
class MeshDevice:
    """Represents a device discovered on the Reticulum mesh.

    Attributes:
        destination_hash: Hex-encoded destination hash (routing identifier).
                         For Styrene nodes, this is the operator destination.
        identity_hash: Hex-encoded identity hash (public key hash, for Identity.recall).
        name: Device name (from announce app_data or generated).
        device_type: Type of device (Styrene node, RNode, etc.).
        last_announce: Unix timestamp of last announce.
        announce_count: Number of announces received.
        app_data_raw: Raw app_data bytes from last announce.
        capabilities: List of capabilities (parsed from app_data).
        version: Styrene version if applicable.
        lxmf_destination_hash: Hex-encoded LXMF delivery destination hash (for messaging).
                               Only present for nodes that support LXMF messaging.
    """

    destination_hash: str
    identity_hash: str
    name: str
    device_type: DeviceType
    last_announce: int
    announce_count: int = 0
    app_data_raw: bytes | None = None
    capabilities: list[str] | None = None
    version: str | None = None
    lxmf_destination_hash: str | None = None
    short_name: str | None = None

    # Legacy alias for backwards compatibility
    @property
    def identity(self) -> str:
        """Legacy alias for destination_hash."""
        return self.destination_hash

    @property
    def status(self) -> NodeStatus:
        """Get node status based on last announce time."""
        now = datetime.now().timestamp()
        elapsed = now - self.last_announce

        if elapsed < 300:  # 5 minutes
            return NodeStatus.ACTIVE
        elif elapsed < 900:  # 15 minutes
            return NodeStatus.STALE
        else:
            return NodeStatus.LOST

    @property
    def last_seen_display(self) -> str:
        """Human-readable last seen time."""
        now = datetime.now().timestamp()
        elapsed = int(now - self.last_announce)

        if elapsed < 60:
            return f"{elapsed}s ago"
        elif elapsed < 3600:
            return f"{elapsed // 60}m ago"
        elif elapsed < 86400:
            return f"{elapsed // 3600}h ago"
        else:
            return f"{elapsed // 86400}d ago"

    @property
    def is_styrene_node(self) -> bool:
        """Check if this is a Styrene-managed node."""
        return self.device_type == DeviceType.STYRENE_NODE

    @property
    def is_rnode(self) -> bool:
        """Check if this is an RNode device."""
        return self.device_type == DeviceType.RNODE

    @property
    def identity_short(self) -> str:
        """Short form of destination hash (first 8 chars)."""
        return self.destination_hash[:8] if self.destination_hash else "unknown"

    def __repr__(self) -> str:
        return (
            f"MeshDevice(name={self.name!r}, "
            f"type={self.device_type.value}, "
            f"status={self.status.value}, "
            f"dest={self.identity_short}...)"
        )


def parse_announce_data(
    app_data: bytes | None,
) -> tuple[str, DeviceType, list[str] | None, str | None, str | None, str | None]:
    """Parse announce app_data to extract device information.

    Styrene nodes announce with format:
        "styrene:<hostname>:<version>:<capabilities>:<lxmf_dest>:<short_name>"
    RNodes announce with: "rnode:<device_name>"
    LXMF clients announce with JSON containing "display_name".
    Generic announces may contain any UTF-8 string.

    Args:
        app_data: Raw app_data bytes from announce.

    Returns:
        Tuple of (name, device_type, capabilities, version,
                  lxmf_destination_hash, short_name).
    """
    if not app_data:
        return ("unknown", DeviceType.UNKNOWN, None, None, None, None)

    try:
        decoded = app_data.decode("utf-8").strip()
    except UnicodeDecodeError:
        # Binary app_data - can't parse
        return ("binary-data", DeviceType.UNKNOWN, None, None, None, None)

    # Check for Styrene node
    if decoded.lower().startswith("styrene"):
        # Handle formats:
        # - "styrene" (minimal)
        # - "styrene:hostname:version:caps" (legacy)
        # - "styrene:hostname:version:caps:lxmf_dest" (current)
        if ":" in decoded:
            parts = decoded.split(":")
            name = parts[1] if len(parts) > 1 else "styrene-node"
            version = parts[2] if len(parts) > 2 else None
            capabilities = parts[3].split(",") if len(parts) > 3 and parts[3] else None
            lxmf_dest = parts[4] if len(parts) > 4 and parts[4] else None
            short_name = parts[5] if len(parts) > 5 and parts[5] else None
        else:
            name = "styrene-node"
            version = None
            capabilities = None
            lxmf_dest = None
            short_name = None
        return (name, DeviceType.STYRENE_NODE, capabilities, version, lxmf_dest, short_name)

    # Check for RNode
    if decoded.lower().startswith("rnode:"):
        parts = decoded.split(":")
        name = parts[1] if len(parts) > 1 else "rnode"
        return (name, DeviceType.RNODE, None, None, None, None)

    # Check for JSON app_data (common in LXMF clients like Sideband/NomadNet)
    # These typically have {"display_name": "...", ...} format
    if decoded.startswith("{") and decoded.endswith("}"):
        try:
            import json

            data = json.loads(decoded)
            if isinstance(data, dict):
                # Extract display_name if present
                display_name = data.get("display_name") or data.get("name")
                if display_name and isinstance(display_name, str):
                    # Truncate long names
                    name = display_name[:32] if len(display_name) > 32 else display_name
                    return (name, DeviceType.GENERIC, None, None, None, None)
        except (json.JSONDecodeError, TypeError):
            pass
        # JSON but no usable name - treat as unknown
        return ("unknown", DeviceType.UNKNOWN, None, None, None, None)

    # Generic announce with custom name (simple string, not JSON/hex)
    # Sanitize: only allow reasonable name characters, reject serialized data
    if (
        decoded
        and not decoded.startswith("0x")
        and len(decoded) <= 64
        and not any(c in decoded for c in "{}[]()<>")
    ):
        return (decoded, DeviceType.GENERIC, None, None, None, None)

    # Unknown or unparseable
    return ("unknown", DeviceType.UNKNOWN, None, None, None, None)


def create_mesh_device(
    destination_hash: str,
    identity_hash: str,
    app_data: bytes | None,
    announce_count: int = 1,
) -> MeshDevice:
    """Create a MeshDevice from announce data.

    Args:
        destination_hash: Hex-encoded destination hash (for routing).
        identity_hash: Hex-encoded identity hash (for Identity.recall).
        app_data: Raw app_data from announce.
        announce_count: Number of announces received.

    Returns:
        MeshDevice instance.
    """
    name, device_type, capabilities, version, lxmf_dest, short_name = parse_announce_data(
        app_data
    )

    # Generate fallback name if needed
    if name == "unknown":
        name = f"device-{destination_hash[:8]}"

    return MeshDevice(
        destination_hash=destination_hash,
        identity_hash=identity_hash,
        name=name,
        device_type=device_type,
        last_announce=int(datetime.now().timestamp()),
        announce_count=announce_count,
        app_data_raw=app_data,
        capabilities=capabilities,
        version=version,
        lxmf_destination_hash=lxmf_dest,
        short_name=short_name,
    )
