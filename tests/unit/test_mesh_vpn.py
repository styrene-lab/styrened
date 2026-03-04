"""Tests for MeshVPN service — WireGuard mesh VPN bootstrapped over RNS.Link."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.services.mesh_vpn import (
    MeshVPNConfig,
    MeshVPNService,
    PeerInfo,
    derive_mesh_ip,
    generate_keypair,
    parse_handshake_request,
    parse_handshake_response,
    build_handshake_request,
    build_handshake_response,
    VPNPlatform,
    detect_platform,
)


# =============================================================================
# Key generation
# =============================================================================


class TestKeyGeneration:
    """WireGuard key generation and persistence."""

    def test_generate_keypair_returns_base64_keys(self):
        """Keys should be 44-char base64 strings (32 bytes encoded)."""
        private, public = generate_keypair()
        assert len(private) == 44
        assert len(public) == 44
        assert private != public

    def test_generate_keypair_deterministic_public_from_private(self):
        """Same private key always yields the same public key."""
        priv1, pub1 = generate_keypair()
        # Re-derive public from private
        from styrened.services.mesh_vpn import public_from_private
        pub2 = public_from_private(priv1)
        assert pub1 == pub2

    def test_keypair_persistence(self, tmp_path):
        """Keys should save/load from disk."""
        service = MeshVPNService(
            config=MeshVPNConfig(enable=True),
            styrene_dir=tmp_path,
        )
        service._ensure_keypair()
        key_file = tmp_path / "wireguard_private_key"
        assert key_file.exists()
        # Permissions should be restricted
        assert oct(key_file.stat().st_mode & 0o777) == "0o600"

        # Reload should get same keys
        service2 = MeshVPNService(
            config=MeshVPNConfig(enable=True),
            styrene_dir=tmp_path,
        )
        service2._ensure_keypair()
        assert service.private_key == service2.private_key
        assert service.public_key == service2.public_key


# =============================================================================
# IP derivation
# =============================================================================


class TestIPDerivation:
    """Mesh IPv6 derived from RNS identity hash."""

    def test_derive_mesh_ip_from_identity_hash(self):
        """IP should be a ULA IPv6 in fd73:7479:7265:6e65::/64."""
        ip = derive_mesh_ip("e762e93731c93752")
        assert ip.startswith("fd73:7479:7265:6e65:")
        # Should have 8 colon-separated groups total
        groups = ip.split(":")
        assert len(groups) == 8

    def test_derive_mesh_ip_deterministic(self):
        """Same hash always yields same IP."""
        ip1 = derive_mesh_ip("e762e93731c93752")
        ip2 = derive_mesh_ip("e762e93731c93752")
        assert ip1 == ip2

    def test_derive_mesh_ip_different_hashes_differ(self):
        """Different identity hashes should produce different IPs."""
        ip1 = derive_mesh_ip("e762e93731c93752")
        ip2 = derive_mesh_ip("4dbfa342abcdef01")
        assert ip1 != ip2

    def test_derive_mesh_ip_64bit_interface_id(self):
        """Interface ID should use 64 bits — collision-free for practical purposes."""
        # Generate many IPs, verify all unique (64-bit space = no collisions in small sets)
        ips = set()
        for i in range(1000):
            ip = derive_mesh_ip(f"{i:032x}")
            ips.add(ip)
        assert len(ips) == 1000

    def test_derive_mesh_ip_custom_prefix(self):
        """Should support custom ULA prefix."""
        ip = derive_mesh_ip("e762e93731c93752", subnet_prefix="fd00:aaaa:bbbb:cccc")
        assert ip.startswith("fd00:aaaa:bbbb:cccc:")

    def test_derive_mesh_ip_valid_ipv6(self):
        """Result should parse as valid IPv6."""
        import ipaddress
        ip = derive_mesh_ip("e762e93731c93752")
        addr = ipaddress.IPv6Address(ip)
        assert addr.is_private  # ULA is private


# =============================================================================
# Handshake protocol
# =============================================================================


class TestHandshakeProtocol:
    """WireGuard key exchange over RNS.Link."""

    def test_build_handshake_request(self):
        """Request should contain public key, mesh IP, and endpoint."""
        req = build_handshake_request(
            public_key="dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY=",
            mesh_ip="fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890",
            endpoint="192.168.1.5:51820",
        )
        assert isinstance(req, bytes)
        parsed = json.loads(req)
        assert parsed["wg_pubkey"] == "dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY="
        assert parsed["mesh_ip"] == "fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890"
        assert parsed["endpoint"] == "192.168.1.5:51820"
        assert "version" in parsed

    def test_parse_handshake_request(self):
        """Should extract peer info from request bytes."""
        req = build_handshake_request(
            public_key="dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY=",
            mesh_ip="fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890",
            endpoint="192.168.1.5:51820",
        )
        info = parse_handshake_request(req)
        assert info.public_key == "dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY="
        assert info.mesh_ip == "fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890"
        assert info.endpoint == "192.168.1.5:51820"

    def test_build_handshake_response(self):
        """Response should mirror request structure with responder's info."""
        resp = build_handshake_response(
            public_key="cmVzcG9uZGVycHVibGlja2V5cmVzcG9uZGVycHVi",
            mesh_ip="fd73:7479:7265:6e65:1111:2222:3333:4444",
            endpoint="10.0.0.1:51820",
            gateway=True,
        )
        parsed = json.loads(resp)
        assert parsed["gateway"] is True

    def test_parse_handshake_response(self):
        """Should extract peer info from response bytes."""
        resp = build_handshake_response(
            public_key="cmVzcG9uZGVycHVibGlja2V5cmVzcG9uZGVycHVi",
            mesh_ip="fd73:7479:7265:6e65:1111:2222:3333:4444",
            endpoint="10.0.0.1:51820",
            gateway=True,
        )
        info = parse_handshake_response(resp)
        assert info.gateway is True
        assert info.mesh_ip == "fd73:7479:7265:6e65:1111:2222:3333:4444"

    def test_handshake_includes_subnet_prefix(self):
        """Handshake should carry the subnet prefix for agreement check."""
        req = build_handshake_request(
            public_key="dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY=",
            mesh_ip="fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890",
        )
        parsed = json.loads(req)
        assert parsed["subnet_prefix"] == "fd73:7479:7265:6e65"

    def test_handshake_rejects_missing_fields(self):
        """Malformed handshake should raise ValueError."""
        with pytest.raises((ValueError, KeyError)):
            parse_handshake_request(b'{"wg_pubkey": "abc"}')


# =============================================================================
# Platform detection
# =============================================================================


class TestPlatformDetection:
    """Detect WireGuard capabilities per platform."""

    def test_detect_platform_returns_enum(self):
        """Should return a VPNPlatform enum value."""
        platform = detect_platform()
        assert isinstance(platform, VPNPlatform)

    @patch("platform.system", return_value="Linux")
    def test_linux_detected(self, _):
        assert detect_platform() == VPNPlatform.LINUX

    @patch("platform.system", return_value="Darwin")
    def test_macos_detected(self, _):
        assert detect_platform() == VPNPlatform.MACOS


# =============================================================================
# Service lifecycle
# =============================================================================


class TestMeshVPNService:
    """Service init, start, stop."""

    def test_service_disabled_by_default(self):
        """Service should not start if config.enable is False."""
        svc = MeshVPNService(config=MeshVPNConfig(enable=False))
        assert not svc.enabled

    def test_service_enabled(self, tmp_path):
        """Service should be active when enabled."""
        svc = MeshVPNService(
            config=MeshVPNConfig(enable=True),
            styrene_dir=tmp_path,
        )
        assert svc.enabled

    def test_config_defaults(self):
        """Config should have sensible defaults."""
        cfg = MeshVPNConfig()
        assert cfg.enable is False
        assert cfg.listen_port == 51820
        assert cfg.subnet_prefix == "fd73:7479:7265:6e65"
        assert cfg.gateway is False

    def test_auto_detect_endpoint(self, tmp_path):
        """Should detect a local IP for WireGuard endpoint."""
        endpoint = MeshVPNService._detect_local_endpoint(51820)
        # May be empty in CI/sandboxed environments, but if set should be IP:port
        if endpoint:
            assert ":" in endpoint
            ip, port = endpoint.rsplit(":", 1)
            assert not ip.startswith("127.")
            assert port == "51820"

    def test_peer_tracking(self, tmp_path):
        """Service should track peers by identity hash."""
        svc = MeshVPNService(
            config=MeshVPNConfig(enable=True),
            styrene_dir=tmp_path,
        )
        svc._ensure_keypair()
        peer = PeerInfo(
            public_key="dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY=",
            mesh_ip="fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890",
            endpoint="192.168.1.5:51820",
        )
        svc._peers["abc123"] = peer
        assert "abc123" in svc._peers
        assert svc._peers["abc123"].mesh_ip == "fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890"


# =============================================================================
# Gateway topology
# =============================================================================


class TestGatewayTopology:
    """Gateway detection, routing, and degradation."""

    def _make_service(self, tmp_path, gateway=False):
        svc = MeshVPNService(
            config=MeshVPNConfig(enable=True, gateway=gateway),
            styrene_dir=tmp_path,
        )
        svc._ensure_keypair()
        return svc

    def test_no_gateway_is_point_to_point(self, tmp_path):
        """Two peers without gateway → point-to-point mode."""
        svc = self._make_service(tmp_path)
        svc._peers["peer1"] = PeerInfo(
            public_key="a" * 44, mesh_ip="fd73:7479:7265:6e65:aaaa:bbbb:cccc:0001", gateway=False,
        )
        assert not svc.has_gateway
        status = svc.get_status()
        assert status["mode"] == "point-to-point"

    def test_gateway_peer_detected(self, tmp_path):
        """Adding a gateway peer switches to routed mode."""
        svc = self._make_service(tmp_path)
        svc._peers["gw1"] = PeerInfo(
            public_key="b" * 44, mesh_ip="fd73:7479:7265:6e65:aaaa:bbbb:cccc:0001", gateway=True,
        )
        assert svc.has_gateway
        status = svc.get_status()
        assert status["mode"] == "routed"
        assert status["has_gateway"] is True

    def test_gateway_node_reports_gateway_mode(self, tmp_path):
        """A node configured as gateway reports gateway mode."""
        svc = self._make_service(tmp_path, gateway=True)
        status = svc.get_status()
        assert status["mode"] == "gateway"
        assert status["is_gateway"] is True

    def test_gateway_lost_degrades_to_p2p(self, tmp_path):
        """Losing the gateway peer → back to point-to-point."""
        svc = self._make_service(tmp_path)
        svc._peers["gw1"] = PeerInfo(
            public_key="b" * 44, mesh_ip="fd73:7479:7265:6e65:aaaa:bbbb:cccc:0001", gateway=True,
        )
        svc._peers["peer1"] = PeerInfo(
            public_key="c" * 44, mesh_ip="fd73:7479:7265:6e65:aaaa:bbbb:cccc:0002", gateway=False,
        )
        assert svc.has_gateway
        # Remove gateway
        svc._peers.pop("gw1")
        assert not svc.has_gateway
        assert svc.get_status()["mode"] == "point-to-point"

    def test_direct_and_gateway_peers_listed(self, tmp_path):
        """Properties should partition peers correctly."""
        svc = self._make_service(tmp_path)
        svc._peers["gw"] = PeerInfo(
            public_key="a" * 44, mesh_ip="fd73:7479:7265:6e65:aaaa:bbbb:cccc:0001", gateway=True,
        )
        svc._peers["p1"] = PeerInfo(
            public_key="b" * 44, mesh_ip="fd73:7479:7265:6e65:aaaa:bbbb:cccc:0002", gateway=False,
        )
        svc._peers["p2"] = PeerInfo(
            public_key="c" * 44, mesh_ip="fd73:7479:7265:6e65:aaaa:bbbb:cccc:0003", gateway=False,
        )
        assert len(svc.gateway_peers) == 1
        assert len(svc.direct_peers) == 2

    def test_status_includes_subnet(self, tmp_path):
        """Status should show the full mesh subnet."""
        svc = self._make_service(tmp_path)
        status = svc.get_status()
        assert status["subnet"] == "fd73:7479:7265:6e65::/64"
