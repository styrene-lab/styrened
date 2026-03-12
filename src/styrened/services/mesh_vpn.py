"""Mesh VPN service — WireGuard tunnels bootstrapped over LXMF.

Three-tier connectivity model:
  1. Internet available → WireGuard to mesh gateway → bat0 IP access
  2. Local WiFi         → BATMAN-ADV (802.11s)     → bat0 IP access
  3. LoRa only          → RNS.Link L2 tunnel       → bat0 IP access (future)

This service handles tier 1: using Styrene protocol messages over LXMF
to exchange WireGuard public keys and endpoints, then establishing a WireGuard
tunnel that a gateway node can bridge into bat0.

Key exchange happens as end-to-end encrypted LXMF messages routed through
any available hub — no direct RNS.Link connection needed per peer. The hub
acts as a signaling server; WireGuard data flows directly peer-to-peer.
"""
from __future__ import annotations


import base64
import hashlib
import ipaddress
import json
import logging
import os
import platform
import stat
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Protocol version for handshake compatibility
HANDSHAKE_VERSION = 1

# Capability bit advertised in RNS announces when Yggdrasil is running locally.
CAPABILITY_YGGDRASIL = "yggdrasil"


class PeerDiscovery(Enum):
    """When to fetch /meta from a peer to learn their Yggdrasil address.

    EAGER: /meta is fetched at announce time (via ygg-announce-integration).
           initiate_handshake() can skip the fetch — ygg_endpoint already set.
    LAZY:  /meta is fetched lazily inside initiate_handshake() only when the
           target carries CAPABILITY_YGGDRASIL.  Slower first-handshake but
           avoids a /meta round-trip for every announce.
    """

    EAGER = "eager"
    LAZY = "lazy"

# Default mesh subnet: ULA fd73:7479:7265:6e65::/64
# "styrene" in hex: 73 74 79 72 65 6e 65 → fd73:7479:7265:6e65
# RFC 4193 ULA (fd00::/8) — guaranteed not to conflict with public IPv6
DEFAULT_SUBNET_PREFIX = "fd73:7479:7265:6e65"
DEFAULT_LISTEN_PORT = 51820


def extract_prefix(mesh_ip: str, prefix_len: int = 64) -> str:
    """Extract the network prefix from an IPv6 address.

    Uses ipaddress module to handle all IPv6 forms (compressed, expanded).

    Args:
        mesh_ip: IPv6 address string.
        prefix_len: Prefix length (default 64).

    Returns:
        Network prefix string (no /prefix suffix), e.g. "fd73:7479:7265:6e65".
        Empty string if parsing fails.
    """
    try:
        net = ipaddress.IPv6Network(f"{mesh_ip}/{prefix_len}", strict=False)
        # Format the network address in expanded form, take first 4 groups
        addr = net.network_address
        parts = addr.exploded.split(":")
        # For /64, first 4 groups are the prefix
        group_count = prefix_len // 16
        return ":".join(parts[:group_count])
    except (ValueError, TypeError):
        return ""


# =============================================================================
# Platform detection
# =============================================================================


class VPNPlatform(Enum):
    """Platform-specific WireGuard implementation."""
    LINUX = "linux"      # Kernel module (fastest)
    MACOS = "macos"      # wireguard-go userspace
    UNSUPPORTED = "unsupported"


def detect_platform() -> VPNPlatform:
    """Detect the current platform's WireGuard capabilities."""
    system = platform.system()
    if system == "Linux":
        return VPNPlatform.LINUX
    elif system == "Darwin":
        return VPNPlatform.MACOS
    return VPNPlatform.UNSUPPORTED


# =============================================================================
# Key management (Curve25519)
# =============================================================================


def generate_keypair() -> tuple[str, str]:
    """Generate a WireGuard Curve25519 keypair.

    Returns:
        (private_key_b64, public_key_b64) — base64-encoded 32-byte keys.
    """
    # WireGuard uses Curve25519 — same curve as X25519 key agreement.
    # Generate 32 random bytes, apply clamping per RFC 7748.
    private_bytes = bytearray(os.urandom(32))
    # Clamp private key (X25519 requirement)
    private_bytes[0] &= 248
    private_bytes[31] &= 127
    private_bytes[31] |= 64

    private_b64 = base64.b64encode(bytes(private_bytes)).decode("ascii")
    public_b64 = public_from_private(private_b64)
    return private_b64, public_b64


def public_from_private(private_key_b64: str) -> str:
    """Derive WireGuard public key from private key.

    Uses X25519 scalar multiplication of the private key with the
    Curve25519 base point.

    Args:
        private_key_b64: Base64-encoded 32-byte private key.

    Returns:
        Base64-encoded 32-byte public key.
    """
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

    private_bytes = base64.b64decode(private_key_b64)
    private_key = X25519PrivateKey.from_private_bytes(private_bytes)
    public_bytes = private_key.public_key().public_bytes_raw()
    return base64.b64encode(public_bytes).decode("ascii")


# =============================================================================
# IP derivation
# =============================================================================


def derive_mesh_ip(identity_hash: str, subnet_prefix: str = DEFAULT_SUBNET_PREFIX) -> str:
    """Derive a deterministic mesh IPv6 address from an RNS identity hash.

    Uses RFC 4193 Unique Local Address (ULA) space: fd00::/8.
    The full format is fd{global_id}:{subnet}:{interface_id}.

    We use a fixed global ID derived from "styrene" and fill the
    interface ID (64 bits) from SHA-256 of the identity hash.
    This gives collision-free addressing for all practical purposes
    (birthday bound: ~4 billion nodes for 50% collision).

    Args:
        identity_hash: Hex-encoded RNS identity hash (at least 4 chars).
        subnet_prefix: ULA prefix like "fd73:7479:7265" (default: derived from "styrene").

    Returns:
        IPv6 address string like "fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890".
    """
    digest = hashlib.sha256(identity_hash.encode("ascii")).digest()
    # Use first 8 bytes of digest as interface ID (64 bits)
    iid = digest[:8]
    # Format as 4 colon-separated 16-bit groups
    iid_str = ":".join(
        f"{(iid[i] << 8) | iid[i + 1]:04x}" for i in range(0, 8, 2)
    )
    return f"{subnet_prefix}:{iid_str}"


# =============================================================================
# Handshake protocol (JSON over LXMF StyreneProtocol)
# =============================================================================


@dataclass
class PeerInfo:
    """Information about a VPN peer."""
    public_key: str          # WireGuard public key (base64)
    mesh_ip: str             # Assigned mesh IP
    endpoint: str | None = None      # IP:port for WireGuard (may be None if behind NAT)
    gateway: bool = False            # Whether this peer serves as a bat0 gateway
    identity_hash: str = ""          # RNS identity hash of the peer
    ygg_endpoint: str | None = None  # [addr]:port Yggdrasil endpoint, or None
    capabilities: list[str] = field(default_factory=list)  # Announced capability flags


def build_handshake_request(
    public_key: str,
    mesh_ip: str,
    endpoint: str | None = None,
    ygg_endpoint: str | None = None,
) -> bytes:
    """Build a VPN handshake request to send over LXMF.

    Args:
        public_key: Our WireGuard public key.
        mesh_ip: Our derived mesh IP.
        endpoint: Our WireGuard endpoint (IP:port), if known.
        ygg_endpoint: Our Yggdrasil endpoint in [addr]:port format, or None.

    Returns:
        JSON-encoded bytes.
    """
    payload: dict[str, Any] = {
        "version": HANDSHAKE_VERSION,
        "wg_pubkey": public_key,
        "mesh_ip": mesh_ip,
        "subnet_prefix": extract_prefix(mesh_ip),
        "endpoint": endpoint or "",
    }
    if ygg_endpoint:
        payload["ygg_endpoint"] = ygg_endpoint
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def build_handshake_response(
    public_key: str,
    mesh_ip: str,
    endpoint: str | None = None,
    gateway: bool = False,
    ygg_endpoint: str | None = None,
) -> bytes:
    """Build a VPN handshake response.

    Args:
        public_key: Our WireGuard public key.
        mesh_ip: Our derived mesh IP.
        endpoint: Our WireGuard endpoint.
        gateway: Whether we serve as a bat0 gateway.
        ygg_endpoint: Our Yggdrasil endpoint in [addr]:port format, or None.

    Returns:
        JSON-encoded bytes.
    """
    payload: dict[str, Any] = {
        "version": HANDSHAKE_VERSION,
        "wg_pubkey": public_key,
        "mesh_ip": mesh_ip,
        "subnet_prefix": extract_prefix(mesh_ip),
        "endpoint": endpoint or "",
        "gateway": gateway,
    }
    if ygg_endpoint:
        payload["ygg_endpoint"] = ygg_endpoint
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def parse_handshake_request(data: bytes) -> PeerInfo:
    """Parse a VPN handshake request.

    Args:
        data: JSON-encoded bytes from LXMF message.

    Returns:
        PeerInfo with the peer's WireGuard details.

    Raises:
        ValueError: If required fields are missing.
        KeyError: If required fields are missing.
    """
    payload = json.loads(data)
    if "wg_pubkey" not in payload or "mesh_ip" not in payload:
        raise ValueError("Handshake missing required fields: wg_pubkey, mesh_ip")
    version = payload.get("version", 0)
    if version != HANDSHAKE_VERSION:
        raise ValueError(
            f"Unsupported handshake version {version} (expected {HANDSHAKE_VERSION})"
        )
    return PeerInfo(
        public_key=payload["wg_pubkey"],
        mesh_ip=payload["mesh_ip"],
        endpoint=payload.get("endpoint") or None,
        ygg_endpoint=payload.get("ygg_endpoint") or None,
    )


def parse_handshake_response(data: bytes) -> PeerInfo:
    """Parse a VPN handshake response.

    Args:
        data: JSON-encoded bytes from LXMF message.

    Returns:
        PeerInfo with the responder's WireGuard details.

    Raises:
        ValueError: If required fields are missing or version mismatches.
    """
    payload = json.loads(data)
    # Check for error responses
    if "error" in payload:
        raise ValueError(f"Handshake rejected: {payload['error']}")
    if "wg_pubkey" not in payload or "mesh_ip" not in payload:
        raise ValueError("Handshake missing required fields: wg_pubkey, mesh_ip")
    version = payload.get("version", 0)
    if version != HANDSHAKE_VERSION:
        raise ValueError(
            f"Unsupported handshake version {version} (expected {HANDSHAKE_VERSION})"
        )
    return PeerInfo(
        public_key=payload["wg_pubkey"],
        mesh_ip=payload["mesh_ip"],
        endpoint=payload.get("endpoint") or None,
        gateway=payload.get("gateway", False),
        ygg_endpoint=payload.get("ygg_endpoint") or None,
    )


# Re-export from models for backward compatibility
from styrened.models.config import MeshVPNConfig  # noqa: E402, F401

# =============================================================================
# Service
# =============================================================================


class MeshVPNService:
    """Manages WireGuard mesh VPN tunnels bootstrapped over LXMF.

    Lifecycle:
        1. On start, generate or load WireGuard keypair
        2. Derive mesh IP from RNS identity hash
        3. Register VPN_HANDSHAKE_REQUEST handler on StyreneProtocol
        4. When a peer sends VPN handshake via LXMF:
           a. Exchange WG public keys + endpoints
           b. Configure WireGuard peer
           c. If gateway: bridge into bat0
        5. On stop, tear down WireGuard interface

    LXMF messages are end-to-end encrypted by RNS identity keys.
    The hub routes them but cannot read the payload. Trust comes from
    RNS identity authentication — same as before, no direct link needed.
    """

    def __init__(
        self,
        config: MeshVPNConfig | None = None,
        styrene_dir: Path | None = None,
        identity_hash: str = "",
    ) -> None:
        self.config = config or MeshVPNConfig()
        self._styrene_dir = styrene_dir or Path.home() / ".styrene"
        self._identity_hash = identity_hash
        self._peers: dict[str, PeerInfo] = {}  # identity_hash → PeerInfo
        self.private_key: str = ""
        self.public_key: str = ""
        self.mesh_ip: str = ""
        self._platform = detect_platform()
        self._interface_name = "wg-styrene"
        self._started = False
        self._styrene_protocol: Any = None  # Set by daemon after start
        self._pending_handshakes: dict[str, Any] = {}  # identity_hash → asyncio.Future
        self._ygg_adapter: Any = None  # YggdrasilAdapter, injected by daemon after start

    @property
    def enabled(self) -> bool:
        return self.config.enable

    @staticmethod
    def _detect_local_endpoint(port: int) -> str:
        """Best-effort detection of a reachable local IP for WireGuard.

        Tries to find a non-loopback IPv4 address by opening a UDP socket
        to a public IP (doesn't actually send data). Falls back to empty
        string if detection fails.

        Returns:
            "IP:port" string or empty string.
        """
        import socket

        try:
            # This doesn't send any data — just lets the OS pick
            # the source interface for routing to an external IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                if local_ip and not local_ip.startswith("127."):
                    return f"{local_ip}:{port}"
        except Exception:
            pass
        return ""

    async def _detect_yggdrasil_endpoint(self, port: int) -> str | None:
        """Detect our local Yggdrasil address and format it as [addr]:port.

        Priority order:
          1. If _ygg_adapter is set and running, use its cached address.
          2. Otherwise probe the same socket paths as YggdrasilAdapter._probe().

        Args:
            port: WireGuard listen port to attach to the endpoint string.

        Returns:
            "[ygg_addr]:port" IPv6 endpoint string, or None if Yggdrasil is
            not running or no address is discoverable.
        """
        import json as _json
        import socket as _socket

        # Fast path: adapter already running and has cached address.
        if self._ygg_adapter is not None:
            addr = self._ygg_adapter.get_local_address()
            if addr:
                return f"[{addr}]:{port}"

        # Slow path: probe admin sockets directly.
        try:
            from styrened.services.yggdrasil import SYSTEM_SOCKET_PATHS
        except ImportError:
            return None

        candidates = list(SYSTEM_SOCKET_PATHS)

        for sock_path in candidates:
            if not sock_path.exists():
                continue
            try:
                request = _json.dumps({"request": "getself", "keepalive": False}).encode()
                with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as sock:
                    sock.settimeout(3.0)
                    sock.connect(str(sock_path))
                    sock.sendall(request)
                    buf = b""
                    while True:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        buf += chunk
                        try:
                            data = _json.loads(buf)
                            addr = (
                                data.get("address")
                                or data.get("self", {}).get("address")
                            )
                            if addr:
                                return f"[{addr}]:{port}"
                            break
                        except _json.JSONDecodeError:
                            continue
            except Exception:
                continue

        return None

    def _select_peer_endpoint(self, peer: "PeerInfo") -> str | None:
        """Choose the best WireGuard endpoint for a peer.

        If our local Yggdrasil is running (adapter present and running) and
        the peer has a ygg_endpoint, prefer the Yggdrasil overlay address —
        it stays routable even when the peer's public IP changes.

        Falls back to peer.endpoint otherwise.

        Args:
            peer: The peer whose endpoint we are selecting.

        Returns:
            Endpoint string ("ip:port" or "[addr]:port"), or None.
        """
        ygg_running = (
            self._ygg_adapter is not None
            and self._ygg_adapter.get_local_address() is not None
        )
        if ygg_running and peer.ygg_endpoint:
            return peer.ygg_endpoint
        return peer.endpoint

    async def _fetch_meta_ygg_address(self, target_hash: str) -> str | None:
        """Fetch /meta from *target_hash* over a DirectLink and return ygg_address.

        Delegates to DirectLinkService.request_meta() which manages link
        establishment and teardown.  Returns None if the link cannot be
        established, the peer is not running Yggdrasil, or the request times out.

        Args:
            target_hash: Hex identity hash of the target peer.

        Returns:
            Yggdrasil IPv6 address string, or None.
        """
        try:
            from styrened.services.direct_link import DirectLinkService

            dl: DirectLinkService | None = getattr(self, "_direct_link_service", None)
            if dl is None:
                return None

            meta = await dl.request_meta(target_hash)
            if meta is None:
                return None
            return meta.get("ygg_address") or None

        except Exception as exc:
            logger.debug("_fetch_meta_ygg_address: %s", exc)
            return None

    def _ensure_keypair(self) -> None:
        """Load or generate WireGuard keypair."""
        key_file = self._styrene_dir / "wireguard_private_key"

        if key_file.exists():
            self.private_key = key_file.read_text().strip()
            self.public_key = public_from_private(self.private_key)
            logger.info(f"Loaded WireGuard key: {self.public_key[:8]}...")
        else:
            self.private_key, self.public_key = generate_keypair()
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_text(self.private_key + "\n")
            # Restrict permissions: owner read/write only
            key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
            logger.info(f"Generated WireGuard key: {self.public_key[:8]}...")

    async def start(self, identity_hash: str = "") -> None:
        """Start the mesh VPN service.

        Args:
            identity_hash: Local node's RNS identity hash (hex).
        """
        if not self.enabled:
            return
        if self._started:
            return

        if identity_hash:
            self._identity_hash = identity_hash

        self._ensure_keypair()
        self.mesh_ip = derive_mesh_ip(
            self._identity_hash,
            self.config.subnet_prefix,
        )

        logger.info(
            f"MeshVPN starting: ip={self.mesh_ip} "
            f"port={self.config.listen_port} "
            f"gateway={self.config.gateway} "
            f"platform={self._platform.value}"
        )

        # Create WireGuard interface — raises on failure
        if not await self._create_interface():
            logger.error("MeshVPN failed to create WireGuard interface — starting in degraded mode")
        self._started = True
        logger.info("MeshVPN started")

    async def stop(self) -> None:
        """Stop the service and tear down the WireGuard interface."""
        if not self._started:
            return
        # Tear down VXLAN overlays before destroying the WG interface
        if self.config.gateway and self._platform == VPNPlatform.LINUX:
            await self._destroy_all_vxlans()
        await self._destroy_interface()
        self._peers.clear()
        self._started = False
        logger.info("MeshVPN stopped")

    # -------------------------------------------------------------------------
    # Handshake handler (called from daemon's datalink destination)
    # -------------------------------------------------------------------------

    @staticmethod
    def _on_peer_config_done(task: Any) -> None:
        """Log exceptions from peer configuration tasks."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error(f"Peer configuration failed: {exc}")

    async def handle_handshake_request(self, message: Any, envelope: Any) -> None:
        """Handle incoming VPN_HANDSHAKE_REQUEST via Styrene protocol over LXMF.

        Decodes the peer's WG info, configures WG peer, and sends back
        a VPN_HANDSHAKE_RESPONSE via LXMF.

        Args:
            message: LXMF message (has .source_hash)
            envelope: StyreneEnvelope (payload is JSON handshake request)
        """
        try:
            from styrened.models.styrene_wire import decode_payload
            payload_data = decode_payload(envelope.payload)
            data = payload_data if isinstance(payload_data, bytes) else json.dumps(payload_data).encode()

            peer_info = parse_handshake_request(data)
            remote_hash = message.source_hash  # hex string from LXMFMessage
            peer_info.identity_hash = remote_hash

            logger.info(
                f"VPN handshake request from {remote_hash[:16]}: "
                f"ip={peer_info.mesh_ip} key={peer_info.public_key[:8]}..."
            )

            # Verify subnet prefix agreement
            peer_prefix = extract_prefix(peer_info.mesh_ip)
            our_prefix = extract_prefix(
                f"{self.config.subnet_prefix}::1"
            ) or self.config.subnet_prefix
            if peer_prefix and our_prefix and peer_prefix != our_prefix:
                logger.warning(
                    f"Subnet prefix mismatch with {remote_hash[:16]}: "
                    f"ours={our_prefix} theirs={peer_prefix}"
                )
                return

            # If peer advertises a Yggdrasil endpoint, add them as an ephemeral
            # Yggdrasil peer so the overlay route exists before WG comes up.
            if peer_info.ygg_endpoint and self._ygg_adapter is not None:
                # ygg_endpoint is "[addr]:port" — extract just the address.
                ygg_addr_raw = peer_info.ygg_endpoint.split("]:")[0].lstrip("[")
                await self._ygg_adapter.add_peer(ygg_addr_raw)

            # Prefer Yggdrasil overlay endpoint for configuration when available.
            effective_endpoint = self._select_peer_endpoint(peer_info)
            if effective_endpoint != peer_info.endpoint:
                peer_info = PeerInfo(
                    public_key=peer_info.public_key,
                    mesh_ip=peer_info.mesh_ip,
                    endpoint=effective_endpoint,
                    gateway=peer_info.gateway,
                    identity_hash=peer_info.identity_hash,
                    ygg_endpoint=peer_info.ygg_endpoint,
                    capabilities=peer_info.capabilities,
                )

            # Store and configure peer
            self._peers[remote_hash] = peer_info
            await self._configure_peer(remote_hash, peer_info)

            # Send response via LXMF — include our Yggdrasil endpoint.
            endpoint = self.config.endpoint or self._detect_local_endpoint(
                self.config.listen_port
            )
            our_ygg_endpoint = await self._detect_yggdrasil_endpoint(self.config.listen_port)
            response_data = build_handshake_response(
                public_key=self.public_key,
                mesh_ip=self.mesh_ip,
                endpoint=endpoint,
                gateway=self.config.gateway,
                ygg_endpoint=our_ygg_endpoint,
            )
            await self._send_vpn_message(
                remote_hash,
                "VPN_HANDSHAKE_RESPONSE",
                response_data,
                request_id=envelope.request_id,
            )

            logger.info(f"VPN handshake response sent to {remote_hash[:16]}")

        except Exception as e:
            logger.error(f"VPN handshake request handling failed: {e}")

    async def handle_handshake_response(self, message: Any, envelope: Any) -> None:
        """Handle incoming VPN_HANDSHAKE_RESPONSE via Styrene protocol.

        The peer has accepted our handshake — configure them as WG peer.

        Args:
            message: LXMF message (has .source_hash)
            envelope: StyreneEnvelope (payload is JSON handshake response)
        """
        try:
            from styrened.models.styrene_wire import decode_payload
            payload_data = decode_payload(envelope.payload)
            data = payload_data if isinstance(payload_data, bytes) else json.dumps(payload_data).encode()

            peer_info = parse_handshake_response(data)
            remote_hash = message.source_hash  # hex string from LXMFMessage
            peer_info.identity_hash = remote_hash

            logger.info(
                f"VPN handshake response from {remote_hash[:16]}: "
                f"ip={peer_info.mesh_ip} gateway={peer_info.gateway}"
            )

            # If peer advertises a Yggdrasil endpoint, add ephemeral Ygg peer.
            if peer_info.ygg_endpoint and self._ygg_adapter is not None:
                ygg_addr_raw = peer_info.ygg_endpoint.split("]:")[0].lstrip("[")
                await self._ygg_adapter.add_peer(ygg_addr_raw)

            # Prefer Yggdrasil overlay endpoint when our Ygg is running.
            effective_endpoint = self._select_peer_endpoint(peer_info)
            if effective_endpoint != peer_info.endpoint:
                peer_info = PeerInfo(
                    public_key=peer_info.public_key,
                    mesh_ip=peer_info.mesh_ip,
                    endpoint=effective_endpoint,
                    gateway=peer_info.gateway,
                    identity_hash=peer_info.identity_hash,
                    ygg_endpoint=peer_info.ygg_endpoint,
                    capabilities=peer_info.capabilities,
                )

            # Store and configure peer
            self._peers[remote_hash] = peer_info
            await self._configure_peer(remote_hash, peer_info)

            # Resolve pending handshake future if any
            future = self._pending_handshakes.pop(remote_hash, None)
            if future and not future.done():
                future.set_result(peer_info)

            logger.info(
                f"VPN handshake complete with {remote_hash[:16]}: "
                f"ip={peer_info.mesh_ip} gateway={peer_info.gateway}"
            )

        except Exception as e:
            logger.error(f"VPN handshake response handling failed: {e}")
            future = self._pending_handshakes.pop(message.source_hash, None)
            if future and not future.done():
                future.set_exception(e)

    # -------------------------------------------------------------------------
    # WireGuard interface management (platform-specific)
    # -------------------------------------------------------------------------

    async def _create_interface(self) -> bool:
        """Create the WireGuard interface. Returns True on success."""
        if self._platform == VPNPlatform.LINUX:
            return await self._create_interface_linux()
        elif self._platform == VPNPlatform.MACOS:
            return await self._create_interface_macos()
        else:
            logger.warning(f"WireGuard not supported on {self._platform.value}")
            return False

    async def _destroy_interface(self) -> None:
        """Tear down the WireGuard interface."""
        if self._platform == VPNPlatform.LINUX:
            await self._destroy_interface_linux()
        elif self._platform == VPNPlatform.MACOS:
            await self._destroy_interface_macos()

    async def _create_interface_linux(self) -> bool:
        """Create WireGuard interface on Linux using ip + wg. Returns True on success."""
        import asyncio
        import shutil
        import tempfile

        # Check required binaries
        for binary in ("ip", "wg"):
            if not shutil.which(binary):
                logger.error(f"Required binary '{binary}' not found in PATH")
                return False
        if self.config.gateway and not shutil.which("batctl"):
            logger.error("Gateway mode requires 'batctl' but it's not in PATH")
            return False

        # Create WireGuard interface
        proc = await asyncio.create_subprocess_exec(
            "ip", "link", "add", "dev", self._interface_name, "type", "wireguard",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            if b"RTNETLINK answers: File exists" not in stderr:
                logger.error(f"Failed to create WG interface: {stderr.decode()}")
                return False

        # Write private key to temp file with restricted permissions
        fd, key_path = tempfile.mkstemp(prefix="wg_", suffix=".key")
        fd_closed = False
        try:
            os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
            os.write(fd, self.private_key.encode())
            os.close(fd)
            fd_closed = True

            proc = await asyncio.create_subprocess_exec(
                "wg", "set", self._interface_name,
                "listen-port", str(self.config.listen_port),
                "private-key", key_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"wg set failed: {stderr.decode()}")
                return False
        finally:
            if not fd_closed:
                os.close(fd)
            os.unlink(key_path)

        # Assign mesh IPv6 and bring up
        proc = await asyncio.create_subprocess_exec(
            "ip", "-6", "addr", "add",
            f"{self.mesh_ip}/64",
            "dev", self._interface_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        proc = await asyncio.create_subprocess_exec(
            "ip", "link", "set", "up", "dev", self._interface_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"Failed to bring up {self._interface_name}: {stderr.decode()}")
            return False

        logger.info(f"WireGuard interface {self._interface_name} up: {self.mesh_ip}/64")
        return True

    async def _destroy_interface_linux(self) -> None:
        """Remove WireGuard interface on Linux."""
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            "ip", "link", "del", "dev", self._interface_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        logger.info(f"WireGuard interface {self._interface_name} removed")

    async def _create_interface_macos(self) -> bool:
        """Create WireGuard tunnel on macOS via wg-quick.

        macOS requires root for utun interface creation and all wg
        commands (the UAPI socket is root-owned). If not running as
        root, writes the config file and returns False with instructions.

        Returns:
            True if tunnel is up, False if config-only (not root).
        """
        import asyncio
        import shutil

        if not shutil.which("wg-quick"):
            logger.error("wg-quick not found — install: brew install wireguard-tools")
            return False

        conf_path = self._styrene_dir / f"{self._interface_name}.conf"
        conf_content = (
            f"[Interface]\n"
            f"PrivateKey = {self.private_key}\n"
            f"ListenPort = {self.config.listen_port}\n"
            f"Address = {self.mesh_ip}/64\n"
        )
        conf_path.write_text(conf_content)
        conf_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

        if os.geteuid() != 0:
            logger.warning(
                f"Not running as root — WireGuard config written to {conf_path} "
                f"but tunnel NOT activated. Restart with: sudo styrened daemon"
            )
            return False

        proc = await asyncio.create_subprocess_exec(
            "wg-quick", "up", str(conf_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"wg-quick up failed: {stderr.decode()}")
            return False

        self._macos_tunnel_active = True
        logger.info(f"WireGuard tunnel up on macOS: {self.mesh_ip}/64")
        return True

    async def _destroy_interface_macos(self) -> None:
        """Tear down WireGuard tunnel on macOS."""
        import asyncio

        conf_path = self._styrene_dir / f"{self._interface_name}.conf"

        if getattr(self, "_macos_tunnel_active", False):
            proc = await asyncio.create_subprocess_exec(
                "wg-quick", "down", str(conf_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            self._macos_tunnel_active = False
            logger.info("WireGuard tunnel down on macOS")

        if conf_path.exists():
            conf_path.unlink()

    def _append_peer_to_macos_conf(self, peer: PeerInfo, allowed_ips: str) -> None:
        """Append a [Peer] section to the macOS wg-quick config."""
        conf_path = self._styrene_dir / f"{self._interface_name}.conf"
        if not conf_path.exists():
            return
        peer_block = (
            f"\n[Peer]\n"
            f"PublicKey = {peer.public_key}\n"
            f"AllowedIPs = {allowed_ips}\n"
            f"PersistentKeepalive = 25\n"
        )
        if peer.endpoint:
            peer_block += f"Endpoint = {peer.endpoint}\n"
        with open(conf_path, "a") as f:
            f.write(peer_block)
        logger.info(
            f"Peer added to {conf_path} — re-import or restart tunnel to apply"
        )

    # -------------------------------------------------------------------------
    # BATMAN-ADV gateway integration via VXLAN (Linux only)
    # -------------------------------------------------------------------------
    #
    # WireGuard is L3 — it carries IP packets, not Ethernet frames.
    # BATMAN-ADV hard interfaces need L2 (Ethernet) to carry OGMs.
    # Solution: layer a VXLAN tunnel over the WG mesh IPs.
    #
    #   bat0 (L2 mesh, BATMAN-ADV)
    #     └── vxlan-<peer_prefix>  (L2-over-UDP, per-peer)
    #           └── wg-styrene     (L3 encrypted tunnel)
    #                 └── physical NIC
    #
    # Each peer gets a point-to-point VXLAN interface using their WG mesh
    # IP as the remote endpoint. The VXLAN interface is added to bat0.
    # BATMAN handles L2 forwarding across all VXLAN tunnels.

    # Fixed VXLAN Network Identifier for Styrene mesh
    VXLAN_VNI = 7379  # "sy" as decimal

    def _vxlan_name(self, identity_hash: str) -> str:
        """Generate VXLAN interface name for a peer (max 15 chars for Linux)."""
        return f"vx-{identity_hash[:10]}"

    async def _create_vxlan_for_peer(self, identity_hash: str, peer: PeerInfo) -> bool:
        """Create a VXLAN tunnel over WG to a peer and add it to bat0.

        Args:
            identity_hash: Peer's RNS identity hash.
            peer: Peer info with mesh_ip.

        Returns:
            True if VXLAN was created and added to bat0.
        """
        import asyncio

        vxlan_name = self._vxlan_name(identity_hash)

        # Create VXLAN interface:
        #   - local = our WG mesh IP
        #   - remote = peer's WG mesh IP
        #   - dstport 4789 (IANA standard VXLAN port)
        #   - dev wg-styrene (route VXLAN UDP through the WG tunnel)
        proc = await asyncio.create_subprocess_exec(
            "ip", "link", "add", vxlan_name,
            "type", "vxlan",
            "id", str(self.VXLAN_VNI),
            "local", self.mesh_ip,
            "remote", peer.mesh_ip,
            "dstport", "4789",
            "dev", self._interface_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            if b"File exists" not in stderr:
                logger.error(f"Failed to create VXLAN {vxlan_name}: {stderr.decode()}")
                return False

        # Bring up VXLAN interface
        proc = await asyncio.create_subprocess_exec(
            "ip", "link", "set", "up", "dev", vxlan_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"Failed to bring up {vxlan_name}: {stderr.decode()}")
            return False

        # Verify bat0 exists before adding
        proc = await asyncio.create_subprocess_exec(
            "ip", "link", "show", "bat0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                f"bat0 interface not found — VXLAN {vxlan_name} is up but "
                f"not bridged to BATMAN. Load batman-adv and create bat0 first."
            )
            return True  # VXLAN is up, just not bridged — not a failure

        # Add VXLAN to bat0 as a BATMAN-ADV hard interface
        proc = await asyncio.create_subprocess_exec(
            "batctl", "meshif", "bat0", "if", "add", vxlan_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            if b"is already" not in stderr:
                logger.error(f"batctl if add {vxlan_name} failed: {stderr.decode()}")
                return False

        # Set throughput override — WG over internet is fast but batman-adv
        # can't auto-detect throughput on a VXLAN interface.
        proc = await asyncio.create_subprocess_exec(
            "batctl", "hardif", vxlan_name, "throughput_override", "100Mbit",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        logger.info(
            f"VXLAN {vxlan_name} up: {self.mesh_ip} → {peer.mesh_ip} → bat0"
        )
        return True

    async def _destroy_vxlan_for_peer(self, identity_hash: str) -> None:
        """Remove a peer's VXLAN interface."""
        import asyncio

        vxlan_name = self._vxlan_name(identity_hash)

        # Remove from bat0 first
        proc = await asyncio.create_subprocess_exec(
            "batctl", "meshif", "bat0", "if", "del", vxlan_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Delete the interface
        proc = await asyncio.create_subprocess_exec(
            "ip", "link", "del", "dev", vxlan_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        logger.info(f"VXLAN {vxlan_name} removed")

    async def _destroy_all_vxlans(self) -> None:
        """Remove all VXLAN interfaces for current peers."""
        for identity_hash in list(self._peers):
            await self._destroy_vxlan_for_peer(identity_hash)

    # -------------------------------------------------------------------------
    # Peer configuration
    # -------------------------------------------------------------------------

    async def _update_peer_allowed_ips(self, peer: PeerInfo, allowed_ips: str) -> None:
        """Update a peer's allowed-ips in WireGuard."""
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            "wg", "set", self._interface_name,
            "peer", peer.public_key,
            "allowed-ips", allowed_ips,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"Failed to update allowed-ips for peer: {stderr.decode()}")

    async def _configure_peer(self, identity_hash: str, peer: PeerInfo) -> None:
        """Configure a WireGuard peer after handshake.

        If the peer has an endpoint, configure it as a standard WG peer.
        If no endpoint (both behind NAT), configure without endpoint —
        WireGuard will learn it from the first received packet if the
        other side has our endpoint. For LAN peers, both sides typically
        have reachable IPs.

        Args:
            identity_hash: RNS identity hash of the peer.
            peer: Peer's WireGuard info from handshake.
        """
        import asyncio

        # Gateway peers route the entire mesh subnet.
        # Direct peers only route their own /128.
        # This means: if a gateway exists, traffic to unknown mesh IPs
        # goes through it. If the gateway dies, direct /128 routes to
        # peers we've handshaked with still work — graceful degradation.
        #
        # Only one gateway can hold the /64 route at a time (WireGuard
        # rejects overlapping allowed-ips). If a new gateway appears,
        # remove the old one's /64 route first.
        if peer.gateway:
            # Evict existing gateway's /64 claim
            for existing_hash, existing_peer in list(self._peers.items()):
                if existing_peer.gateway and existing_hash != identity_hash:
                    logger.info(
                        f"Replacing gateway {existing_hash[:16]} with {identity_hash[:16]}"
                    )
                    # Downgrade old gateway to /128 peer route
                    await self._update_peer_allowed_ips(
                        existing_peer, f"{existing_peer.mesh_ip}/128"
                    )
                    existing_peer.gateway = False
            allowed_ips = f"{self.config.subnet_prefix}::/64"
        else:
            allowed_ips = f"{peer.mesh_ip}/128"

        # On macOS without root, the tunnel isn't active — we can only
        # append to the config file for when the user brings it up.
        macos_config_only = (
            self._platform == VPNPlatform.MACOS
            and not getattr(self, "_macos_tunnel_active", False)
        )

        if macos_config_only:
            self._append_peer_to_macos_conf(peer, allowed_ips)
        else:
            cmd = [
                "wg", "set", self._interface_name,
                "peer", peer.public_key,
                "allowed-ips", allowed_ips,
                "persistent-keepalive", "25",
            ]

            if peer.endpoint:
                cmd.extend(["endpoint", peer.endpoint])
            else:
                logger.info(
                    f"Peer {identity_hash[:16]} has no endpoint — "
                    f"configuring as endpoint-less peer (will learn on first packet)"
                )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"wg set peer failed: {stderr.decode()}")
                return

            # On macOS with root, also update the conf for persistence
            if self._platform == VPNPlatform.MACOS:
                self._append_peer_to_macos_conf(peer, allowed_ips)

        # If we're a gateway, create VXLAN overlay for L2 bridging into bat0.
        # Non-gateway nodes don't need VXLAN — they use WG for IP-level access.
        if self.config.gateway and self._platform == VPNPlatform.LINUX:
            await self._create_vxlan_for_peer(identity_hash, peer)

        logger.info(
            f"Configured VPN peer {identity_hash[:16]}: "
            f"{peer.mesh_ip} via {peer.endpoint or '(roaming)'}"
        )

    # -------------------------------------------------------------------------
    # Client-side: initiate handshake
    # -------------------------------------------------------------------------

    async def _send_vpn_message(
        self,
        target_hash: str,
        message_type_name: str,
        payload_data: bytes,
        request_id: bytes | None = None,
    ) -> None:
        """Send a VPN message via Styrene protocol over LXMF.

        Args:
            target_hash: Destination identity hash.
            message_type_name: "VPN_HANDSHAKE_REQUEST" or "VPN_HANDSHAKE_RESPONSE"
            payload_data: JSON-encoded handshake bytes.
            request_id: Optional correlation ID.
        """
        if not self._styrene_protocol:
            raise RuntimeError("StyreneProtocol not set on MeshVPNService")

        from styrened.models.styrene_wire import StyreneMessageType, encode_payload
        msg_type = StyreneMessageType[message_type_name]
        encoded = encode_payload(payload_data)

        await self._styrene_protocol.send_typed_message(
            target_hash,
            msg_type,
            encoded,
            request_id=request_id,
        )

    async def initiate_handshake(self, target_hash: str, timeout: float = 30.0) -> PeerInfo | None:
        """Initiate VPN handshake with a remote peer via LXMF.

        Sends a VPN_HANDSHAKE_REQUEST and waits for VPN_HANDSHAKE_RESPONSE.
        The response arrives asynchronously via handle_handshake_response().

        Args:
            target_hash: Identity hash of the target peer.
            timeout: Seconds to wait for response (default 30s).

        Returns:
            PeerInfo of the remote peer, or None on failure/timeout.
        """
        import asyncio

        if not self._started:
            logger.error("MeshVPN not started")
            return None

        if not self._styrene_protocol:
            logger.error("StyreneProtocol not set — cannot initiate handshake")
            return None

        # LAZY peer_discovery: if target advertises CAPABILITY_YGGDRASIL, fetch
        # /meta now to learn their Yggdrasil address before sending handshake.
        # EAGER mode already fetched /meta at announce time — skip here.
        peer = self._peers.get(target_hash)
        is_lazy = self.config.peer_discovery == PeerDiscovery.LAZY.value
        has_ygg_cap = CAPABILITY_YGGDRASIL in (peer.capabilities if peer else [])
        if is_lazy and has_ygg_cap and (peer is None or not peer.ygg_endpoint):
            ygg_addr = await self._fetch_meta_ygg_address(target_hash)
            if ygg_addr:
                if peer is None:
                    # Create a stub PeerInfo to hold capabilities/ygg data
                    peer = PeerInfo(public_key="", mesh_ip="", capabilities=[CAPABILITY_YGGDRASIL])
                    self._peers[target_hash] = peer
                peer.ygg_endpoint = await self._detect_yggdrasil_endpoint(
                    self.config.listen_port
                )
                # Add peer to Yggdrasil so the overlay route exists before WG starts.
                if self._ygg_adapter is not None and ygg_addr:
                    await self._ygg_adapter.add_peer(ygg_addr)

        # Build handshake request — include our Yggdrasil endpoint if known.
        endpoint = self.config.endpoint or self._detect_local_endpoint(
            self.config.listen_port
        )
        ygg_endpoint = await self._detect_yggdrasil_endpoint(self.config.listen_port)
        request_data = build_handshake_request(
            public_key=self.public_key,
            mesh_ip=self.mesh_ip,
            endpoint=endpoint,
            ygg_endpoint=ygg_endpoint,
        )

        # Create future to wait for response
        future: asyncio.Future[PeerInfo] = asyncio.get_event_loop().create_future()
        self._pending_handshakes[target_hash] = future

        try:
            await self._send_vpn_message(
                target_hash,
                "VPN_HANDSHAKE_REQUEST",
                request_data,
            )
            logger.info(f"VPN handshake request sent to {target_hash[:16]}")

            # Wait for response (arrives via handle_handshake_response)
            peer_info = await asyncio.wait_for(future, timeout=timeout)
            return peer_info

        except TimeoutError:
            logger.warning(f"VPN handshake with {target_hash[:16]} timed out after {timeout}s")
            self._pending_handshakes.pop(target_hash, None)
            return None
        except Exception as e:
            logger.error(f"VPN handshake with {target_hash[:16]} failed: {e}")
            self._pending_handshakes.pop(target_hash, None)
            return None

    # -------------------------------------------------------------------------
    # Gateway lifecycle — topology changes
    # -------------------------------------------------------------------------

    @property
    def has_gateway(self) -> bool:
        """Whether any connected peer is a gateway."""
        return any(p.gateway for p in self._peers.values())

    @property
    def gateway_peers(self) -> list[PeerInfo]:
        """All connected gateway peers."""
        return [p for p in self._peers.values() if p.gateway]

    @property
    def direct_peers(self) -> list[PeerInfo]:
        """All connected non-gateway peers."""
        return [p for p in self._peers.values() if not p.gateway]

    async def handle_peer_lost(self, identity_hash: str) -> None:
        """Handle a peer going offline.

        If the lost peer was a gateway, direct /128 routes to other
        peers still work — graceful degradation to point-to-point.

        Args:
            identity_hash: RNS identity hash of the lost peer.
        """
        peer = self._peers.pop(identity_hash, None)
        if not peer:
            return

        # Remove VXLAN overlay if gateway mode
        if self.config.gateway and self._platform == VPNPlatform.LINUX:
            await self._destroy_vxlan_for_peer(identity_hash)

        # Remove WireGuard peer
        import asyncio
        proc = await asyncio.create_subprocess_exec(
            "wg", "set", self._interface_name,
            "peer", peer.public_key, "remove",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        if peer.gateway:
            logger.warning(
                f"Gateway {identity_hash[:16]} lost — "
                f"degrading to point-to-point ({len(self._peers)} direct peers remain)"
            )
        else:
            logger.info(f"Peer {identity_hash[:16]} removed from VPN")

    # -------------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Get current mesh VPN status."""
        has_gw = self.has_gateway
        mode = "gateway" if self.config.gateway else ("routed" if has_gw else "point-to-point")
        return {
            "enabled": self.enabled,
            "started": self._started,
            "mode": mode,
            "platform": self._platform.value,
            "mesh_ip": self.mesh_ip,
            "subnet": f"{self.config.subnet_prefix}::/64",
            "public_key": self.public_key[:8] + "..." if self.public_key else "",
            "is_gateway": self.config.gateway,
            "has_gateway": has_gw,
            "listen_port": self.config.listen_port,
            "peers": {
                h[:16]: {
                    "mesh_ip": p.mesh_ip,
                    "endpoint": p.endpoint,
                    "gateway": p.gateway,
                }
                for h, p in self._peers.items()
            },
        }
