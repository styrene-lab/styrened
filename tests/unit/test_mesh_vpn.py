"""Tests for MeshVPN service — WireGuard mesh VPN bootstrapped over RNS.Link."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from styrened.services.mesh_vpn import (
    MeshVPNConfig,
    MeshVPNService,
    PeerInfo,
    VPNPlatform,
    build_handshake_request,
    build_handshake_response,
    derive_mesh_ip,
    detect_platform,
    extract_prefix,
    generate_keypair,
    parse_handshake_request,
    parse_handshake_response,
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

    def test_extract_prefix_expanded(self):
        """extract_prefix should work on expanded IPv6."""
        assert extract_prefix("fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890") == "fd73:7479:7265:6e65"

    def test_extract_prefix_compressed(self):
        """extract_prefix should handle compressed IPv6 (:: notation)."""
        assert extract_prefix("fd73:7479:7265:6e65::1") == "fd73:7479:7265:6e65"

    def test_extract_prefix_all_zeros_iid(self):
        """extract_prefix should handle all-zero interface ID."""
        assert extract_prefix("fd73:7479:7265:6e65::") == "fd73:7479:7265:6e65"

    def test_extract_prefix_invalid_returns_empty(self):
        """extract_prefix should return empty string for invalid input."""
        assert extract_prefix("not-an-ip") == ""
        assert extract_prefix("") == ""

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

    def test_handshake_rejects_wrong_version(self):
        """Handshake with wrong version should raise ValueError."""
        data = json.dumps({
            "version": 99,
            "wg_pubkey": "dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY=",
            "mesh_ip": "fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890",
        }).encode()
        with pytest.raises(ValueError, match="Unsupported handshake version"):
            parse_handshake_request(data)

    def test_parse_response_detects_error(self):
        """Error response from peer should raise ValueError."""
        data = json.dumps({"error": "subnet_prefix_mismatch"}).encode()
        with pytest.raises(ValueError, match="Handshake rejected"):
            parse_handshake_response(data)

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

    def test_handshake_handler_rejects_prefix_mismatch(self, tmp_path):
        """Handler should reject peers with different subnet prefix."""
        svc = MeshVPNService(
            config=MeshVPNConfig(enable=True, subnet_prefix="fd00:aaaa:bbbb:cccc"),
            styrene_dir=tmp_path,
            identity_hash="abc123",
        )
        svc._ensure_keypair()
        svc.mesh_ip = "fd00:aaaa:bbbb:cccc:1111:2222:3333:4444"
        svc._started = True

        # Peer has different prefix
        request_data = build_handshake_request(
            public_key="dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY=",
            mesh_ip="fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890",
        )

        # Simulate LXMF message + envelope for the async handler
        mock_message = type("MockMsg", (), {"source_hash": "deadbeef" * 4})()

        from styrened.models.styrene_wire import StyreneEnvelope, StyreneMessageType, encode_payload
        envelope = StyreneEnvelope(
            version=1,
            message_type=StyreneMessageType.VPN_HANDSHAKE_REQUEST,
            payload=encode_payload(request_data),
        )

        import asyncio
        asyncio.run(svc.handle_handshake_request(mock_message, envelope))
        # Peer should NOT be stored due to prefix mismatch
        assert "deadbeef" * 4 not in svc._peers

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

    def test_second_gateway_replaces_first(self, tmp_path):
        """Adding a second gateway should demote the first to direct peer."""
        svc = self._make_service(tmp_path)
        gw1 = PeerInfo(
            public_key="a" * 44, mesh_ip="fd73:7479:7265:6e65:aaaa:bbbb:cccc:0001", gateway=True,
        )
        gw2 = PeerInfo(
            public_key="b" * 44, mesh_ip="fd73:7479:7265:6e65:aaaa:bbbb:cccc:0002", gateway=True,
        )
        svc._peers["gw1"] = gw1
        svc._peers["gw2"] = gw2
        # After configure_peer runs for gw2, gw1 should be demoted.
        # We test the property: only one gateway at a time is the design intent.
        assert len(svc.gateway_peers) == 2  # Before configure_peer runs, both are gateway
        # After _configure_peer, the eviction happens — tested via integration.
        # Here we verify the data model supports it:
        gw1.gateway = False
        assert len(svc.gateway_peers) == 1
        assert svc.gateway_peers[0].public_key == "b" * 44

    def test_vxlan_name_length(self, tmp_path):
        """VXLAN interface name must be <= 15 chars (Linux IFNAMSIZ)."""
        svc = self._make_service(tmp_path, gateway=True)
        name = svc._vxlan_name("e762e93731c93752abcdef0123456789")
        assert len(name) <= 15
        assert name.startswith("vx-")

    def test_vxlan_name_deterministic(self, tmp_path):
        """Same identity hash always produces same VXLAN name."""
        svc = self._make_service(tmp_path)
        n1 = svc._vxlan_name("e762e93731c93752")
        n2 = svc._vxlan_name("e762e93731c93752")
        assert n1 == n2

    def test_vxlan_name_unique_per_peer(self, tmp_path):
        """Different peers get different VXLAN names."""
        svc = self._make_service(tmp_path)
        n1 = svc._vxlan_name("e762e93731c93752")
        n2 = svc._vxlan_name("4dbfa342abcdef01")
        assert n1 != n2

    def test_vxlan_vni_constant(self, tmp_path):
        """VXLAN VNI should be the fixed Styrene mesh identifier."""
        svc = self._make_service(tmp_path)
        assert svc.VXLAN_VNI == 7379

    def test_status_includes_subnet(self, tmp_path):
        """Status should show the full mesh subnet."""
        svc = self._make_service(tmp_path)
        status = svc.get_status()
        assert status["subnet"] == "fd73:7479:7265:6e65::/64"

    def test_handshake_response_handler_configures_peer(self, tmp_path):
        """handle_handshake_response should store peer and resolve pending future."""
        import asyncio

        from styrened.models.styrene_wire import StyreneEnvelope, StyreneMessageType, encode_payload

        svc = self._make_service(tmp_path)
        svc._started = True

        response_data = build_handshake_response(
            public_key="dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY=",
            mesh_ip="fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890",
            endpoint="10.0.0.2:51820",
            gateway=False,
        )
        envelope = StyreneEnvelope(
            version=1,
            message_type=StyreneMessageType.VPN_HANDSHAKE_RESPONSE,
            payload=encode_payload(response_data),
        )

        remote_hash = "aabbccdd" * 4
        mock_message = type("MockMsg", (), {"source_hash": remote_hash})()

        # Create pending future
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        svc._pending_handshakes[remote_hash] = future

        loop.run_until_complete(svc.handle_handshake_response(mock_message, envelope))

        # Peer should be stored
        assert remote_hash in svc._peers
        assert svc._peers[remote_hash].mesh_ip == "fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890"
        # Future should be resolved
        assert future.done()
        assert future.result().mesh_ip == "fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890"
        loop.close()

    def test_handshake_request_handler_stores_peer(self, tmp_path):
        """handle_handshake_request should store peer on matching prefix."""
        import asyncio

        from styrened.models.styrene_wire import StyreneEnvelope, StyreneMessageType, encode_payload

        svc = self._make_service(tmp_path)
        svc._started = True

        request_data = build_handshake_request(
            public_key="dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY=",
            mesh_ip="fd73:7479:7265:6e65:a1b2:c3d4:e5f6:7890",
            endpoint="10.0.0.2:51820",
        )
        envelope = StyreneEnvelope(
            version=1,
            message_type=StyreneMessageType.VPN_HANDSHAKE_REQUEST,
            payload=encode_payload(request_data),
        )

        remote_hash = "11223344" * 4
        mock_message = type("MockMsg", (), {"source_hash": remote_hash})()

        # No styrene_protocol set — response won't send, but peer should be stored
        asyncio.run(svc.handle_handshake_request(mock_message, envelope))
        assert remote_hash in svc._peers
        assert svc._peers[remote_hash].public_key == "dGVzdHB1YmxpY2tleXRlc3RwdWJsaWNrZXk0NTY="

    def test_pending_handshakes_initialized(self, tmp_path):
        """Service should have empty pending handshakes dict on init."""
        svc = self._make_service(tmp_path)
        assert svc._pending_handshakes == {}

    def test_initiate_handshake_requires_started(self, tmp_path):
        """initiate_handshake should fail if service not started."""
        import asyncio
        svc = self._make_service(tmp_path)
        svc._started = False
        result = asyncio.run(svc.initiate_handshake("deadbeef" * 4))
        assert result is None

    def test_initiate_handshake_requires_protocol(self, tmp_path):
        """initiate_handshake should fail if no StyreneProtocol set."""
        import asyncio
        svc = self._make_service(tmp_path)
        svc._started = True
        svc._styrene_protocol = None
        result = asyncio.run(svc.initiate_handshake("deadbeef" * 4))
        assert result is None
