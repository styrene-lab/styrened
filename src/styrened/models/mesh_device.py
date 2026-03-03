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

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DeviceType(Enum):
    """Type of device discovered on the mesh."""

    STYRENE_NODE = "styrene"  # Node running Styrene endpoint
    RNODE = "rnode"  # RNode hardware device
    GENERIC = "generic"  # Generic Reticulum announce
    UNKNOWN = "unknown"  # Unable to determine type
    HUB = "hub"  # Hub/transport node
    LXMF_PEER = "lxmf_peer"  # LXMF delivery destination (Sideband/NomadNet/MeshChat)
    PROPAGATION_NODE = "propagation_node"  # LXMF propagation node
    NOMADNET_NODE = "nomadnet_node"  # NomadNet page/node service


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
    system_fingerprint: str | None = None
    discovered_via: str | None = None  # Interface name that received this announce
    hops: int | None = None  # Number of hops from path table

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
    def has_auto_reply(self) -> bool:
        """Check if this node has auto-reply (out-of-office) enabled."""
        return "autoreply" in (self.capabilities or [])

    @property
    def is_styrene_node(self) -> bool:
        """Check if this is a Styrene-managed node."""
        return self.device_type == DeviceType.STYRENE_NODE

    @property
    def is_rnode(self) -> bool:
        """Check if this is an RNode device."""
        return self.device_type == DeviceType.RNODE

    @property
    def is_lxmf_peer(self) -> bool:
        """Check if this is an LXMF delivery peer."""
        return self.device_type == DeviceType.LXMF_PEER

    @property
    def is_propagation_node(self) -> bool:
        """Check if this is an LXMF propagation node."""
        return self.device_type == DeviceType.PROPAGATION_NODE

    @property
    def is_nomadnet_node(self) -> bool:
        """Check if this is a NomadNet node."""
        return self.device_type == DeviceType.NOMADNET_NODE

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


_FINGERPRINT_RE = re.compile(r"^[a-zA-Z0-9._|\-]{1,64}$")


def _sanitize_fingerprint(raw: str | None) -> str | None:
    """Validate and sanitize a system fingerprint from the wire.

    Rejects values that are too long or contain unexpected characters.
    """
    if not raw:
        return None
    if len(raw) > 64 or not _FINGERPRINT_RE.match(raw):
        return None
    return raw


def _try_lxmf_parse(
    app_data: bytes,
    aspect_hint: DeviceType | None = None,
) -> tuple[str, DeviceType, list[str] | None, str | None, str | None, str | None, str | None] | None:
    """Try to parse app_data using LXMF library helpers.

    Handles msgpack-encoded LXMF delivery announces (v0.5.0+) and
    propagation node announces. Returns None if LXMF is not installed
    or the data doesn't match LXMF formats.
    """
    try:
        import LXMF  # type: ignore[import-untyped]
    except ImportError:
        return None

    # Check propagation node format first (more specific)
    try:
        if LXMF.pn_announce_data_is_valid(app_data):
            pn_name = LXMF.pn_name_from_app_data(app_data)
            name = pn_name[:32] if pn_name and len(pn_name) > 32 else (pn_name or "propagation-node")
            dtype = aspect_hint or DeviceType.PROPAGATION_NODE
            return (name, dtype, None, None, None, None, None)
    except Exception:
        pass

    # Try LXMF delivery announce format (display_name from msgpack)
    try:
        display_name = LXMF.display_name_from_app_data(app_data)
        if display_name:
            # Styrene nodes tag their LXMF display_name with a [styrene] prefix
            # so they can be identified even when the operator announce doesn't
            # relay through transport nodes.
            if display_name.startswith("[styrene]"):
                clean_name = display_name[len("[styrene]"):].strip()
                name = clean_name[:32] if len(clean_name) > 32 else clean_name
                return (name, DeviceType.STYRENE_NODE, None, None, None, None, None)
            name = display_name[:32] if len(display_name) > 32 else display_name
            dtype = aspect_hint or DeviceType.LXMF_PEER
            return (name, dtype, None, None, None, None, None)
    except Exception:
        pass

    return None


def parse_announce_data(
    app_data: bytes | None,
    aspect_hint: DeviceType | None = None,
) -> tuple[str, DeviceType, list[str] | None, str | None, str | None, str | None, str | None]:
    """Parse announce app_data to extract device information.

    Styrene nodes announce with format:
        "styrene:<hostname>:<version>:<caps>:<lxmf_dest>:<short_name>:<sys_fingerprint>"
    RNodes announce with: "rnode:<device_name>"
    LXMF clients announce with msgpack or JSON containing display name.
    Generic announces may contain any UTF-8 string.

    Args:
        app_data: Raw app_data bytes from announce.
        aspect_hint: Optional DeviceType detected via aspect matching in the
                     announce handler. When set, overrides the type inferred
                     from app_data content alone.

    Returns:
        Tuple of (name, device_type, capabilities, version,
                  lxmf_destination_hash, short_name, system_fingerprint).
    """
    if not app_data:
        dtype = aspect_hint or DeviceType.UNKNOWN
        return ("unknown", dtype, None, None, None, None, None)

    # Try LXMF library parsers for msgpack-encoded announces.
    # LXMF 0.5.0+ peers and propagation nodes use msgpack (first byte 0x90-0x9f or 0xDC).
    # Only try this for msgpack-looking data to avoid catching plain text/JSON.
    if app_data and len(app_data) > 0 and ((app_data[0] & 0xF0) == 0x90 or app_data[0] == 0xDC):
        parsed = _try_lxmf_parse(app_data, aspect_hint)
        if parsed is not None:
            return parsed

    try:
        decoded = app_data.decode("utf-8").strip()
    except UnicodeDecodeError:
        # Binary app_data that wasn't LXMF msgpack
        dtype = aspect_hint or DeviceType.UNKNOWN
        return ("binary-data", dtype, None, None, None, None, None)

    # Check for Styrene node (wire format: "styrene" or "styrene:host:ver:caps:...")
    if decoded.lower() == "styrene" or decoded.lower().startswith("styrene:"):
        # Handle formats:
        # - "styrene" (minimal)
        # - "styrene:hostname:version:caps" (legacy 4-field)
        # - "styrene:hostname:version:caps:lxmf_dest:short_name" (6-field)
        # - "styrene:hostname:version:caps:lxmf_dest:short_name:fingerprint" (7-field)
        if ":" in decoded:
            parts = decoded.split(":")
            name = parts[1] if len(parts) > 1 else "styrene-node"
            version = parts[2] if len(parts) > 2 else None
            capabilities = parts[3].split(",") if len(parts) > 3 and parts[3] else None
            lxmf_dest = parts[4] if len(parts) > 4 and parts[4] else None
            short_name = parts[5] if len(parts) > 5 and parts[5] else None
            raw_fp = parts[6] if len(parts) > 6 and parts[6] else None
            fingerprint = _sanitize_fingerprint(raw_fp)
        else:
            name = "styrene-node"
            version = None
            capabilities = None
            lxmf_dest = None
            short_name = None
            fingerprint = None
        return (name, DeviceType.STYRENE_NODE, capabilities, version, lxmf_dest, short_name, fingerprint)

    # Check for RNode
    if decoded.lower().startswith("rnode:"):
        parts = decoded.split(":")
        name = parts[1] if len(parts) > 1 else "rnode"
        return (name, DeviceType.RNODE, None, None, None, None, None)

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
                    dtype = aspect_hint or DeviceType.GENERIC
                    return (name, dtype, None, None, None, None, None)
        except (json.JSONDecodeError, TypeError):
            pass
        # JSON but no usable name - treat as unknown
        dtype = aspect_hint or DeviceType.UNKNOWN
        return ("unknown", dtype, None, None, None, None, None)

    # Generic announce with custom name (simple string, not JSON/hex)
    # Sanitize: only allow reasonable name characters, reject serialized data
    if (
        decoded
        and not decoded.startswith("0x")
        and len(decoded) <= 64
        and not any(c in decoded for c in "{}[]()<>")
    ):
        # NomadNet nodes announce plain UTF-8 node name
        dtype = aspect_hint or DeviceType.GENERIC
        return (decoded, dtype, None, None, None, None, None)

    # Unknown or unparseable
    dtype = aspect_hint or DeviceType.UNKNOWN
    return ("unknown", dtype, None, None, None, None, None)


def create_mesh_device(
    destination_hash: str,
    identity_hash: str,
    app_data: bytes | None,
    announce_count: int = 1,
    aspect_hint: DeviceType | None = None,
) -> MeshDevice:
    """Create a MeshDevice from announce data.

    Args:
        destination_hash: Hex-encoded destination hash (for routing).
        identity_hash: Hex-encoded identity hash (for Identity.recall).
        app_data: Raw app_data from announce.
        announce_count: Number of announces received.
        aspect_hint: Optional DeviceType from aspect-based detection.

    Returns:
        MeshDevice instance.
    """
    name, device_type, capabilities, version, lxmf_dest, short_name, fingerprint = (
        parse_announce_data(app_data, aspect_hint=aspect_hint)
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
        system_fingerprint=fingerprint,
    )
