"""Unit tests for Network tab in Settings screen — Reticulum interface manager.

Tests the redesigned Network tab that manages:
- TCPClientInterface peers (add/remove/edit)
- AutoInterface toggle
- Transport mode and settings
- Config persistence to core-config.yaml + ~/.reticulum/config regeneration
"""

from styrened.models.config import (
    CoreConfig,
    DeploymentMode,
    PeerConfig,
    ServerInterfaceConfig,
)
from styrened.services.reticulum import generate_rns_config


class TestGenerateRnsConfigFromPeers:
    """Test that generate_rns_config correctly reflects interface config."""

    def test_default_peer_generates_tcp_client(self):
        """Default config with styrene hub peer should generate TCPClientInterface."""
        config = CoreConfig()
        config.reticulum.interfaces.peers = [
            PeerConfig(host="rns.styrene.io", port=4242, name="Styrene Community Hub"),
        ]
        result = generate_rns_config(config)
        assert "TCPClientInterface" in result
        assert "rns.styrene.io" in result
        assert "4242" in result

    def test_multiple_peers_generate_multiple_interfaces(self):
        """Multiple peers should each get their own TCPClientInterface stanza."""
        config = CoreConfig()
        config.reticulum.interfaces.peers = [
            PeerConfig(host="rns.styrene.io", port=4242, name="Styrene Hub"),
            PeerConfig(host="10.0.0.1", port=5555, name="Private Transport"),
            PeerConfig(host="relay.example.com", port=4242, name="Relay"),
        ]
        result = generate_rns_config(config)
        assert result.count("TCPClientInterface") == 3
        assert "rns.styrene.io" in result
        assert "10.0.0.1" in result
        assert "relay.example.com" in result

    def test_empty_peers_no_tcp_client(self):
        """No peers should produce no TCPClientInterface stanzas."""
        config = CoreConfig()
        config.reticulum.interfaces.peers = []
        result = generate_rns_config(config)
        assert "TCPClientInterface" not in result

    def test_auto_interface_enabled(self):
        """AutoInterface enabled should appear as enabled in config."""
        config = CoreConfig()
        config.reticulum.interfaces.auto = True
        config.reticulum.interfaces.peers = []
        result = generate_rns_config(config)
        assert "AutoInterface" in result
        assert "enabled = true" in result

    def test_auto_interface_disabled(self):
        """AutoInterface disabled should appear as disabled in config."""
        config = CoreConfig()
        config.reticulum.interfaces.auto = False
        config.reticulum.interfaces.peers = []
        result = generate_rns_config(config)
        assert "AutoInterface" in result
        assert "enabled = false" in result

    def test_server_interface_enabled(self):
        """Server interface should appear when enabled."""
        config = CoreConfig()
        config.reticulum.interfaces.server = ServerInterfaceConfig(
            enabled=True, listen_ip="0.0.0.0", port=4242
        )
        config.reticulum.interfaces.peers = []
        result = generate_rns_config(config)
        assert "TCPServerInterface" in result
        assert "listen_port = 4242" in result

    def test_server_interface_disabled(self):
        """Server interface should not appear when disabled."""
        config = CoreConfig()
        config.reticulum.interfaces.server = ServerInterfaceConfig(enabled=False)
        config.reticulum.interfaces.peers = []
        result = generate_rns_config(config)
        assert "TCPServerInterface" not in result

    def test_standalone_mode_sets_transport(self):
        """Standalone mode should enable transport and disable share_instance."""
        config = CoreConfig()
        config.reticulum.mode = DeploymentMode.STANDALONE
        config.reticulum.interfaces.peers = []
        result = generate_rns_config(config)
        assert "enable_transport = true" in result
        assert "share_instance = false" in result

    def test_hub_mode_sets_transport(self):
        """Hub mode should enable transport and share_instance."""
        config = CoreConfig()
        config.reticulum.mode = DeploymentMode.HUB
        config.reticulum.interfaces.peers = []
        result = generate_rns_config(config)
        assert "enable_transport = true" in result
        assert "share_instance = true" in result

    def test_peer_name_used_as_interface_name(self):
        """Peer name should be used as the [[interface_name]] in config."""
        config = CoreConfig()
        config.reticulum.interfaces.peers = [
            PeerConfig(host="10.0.0.1", port=4242, name="My Custom Relay"),
        ]
        result = generate_rns_config(config)
        assert "[[My Custom Relay]]" in result

    def test_unnamed_peer_gets_default_name(self):
        """Peer without name should get a default numbered name."""
        config = CoreConfig()
        config.reticulum.interfaces.peers = [
            PeerConfig(host="10.0.0.1", port=4242),
        ]
        result = generate_rns_config(config)
        assert "[[Peer 1]]" in result


class TestCoreConfigPeerRoundTrip:
    """Test that peers survive save/load round-trip."""

    def test_peer_config_serialization(self):
        """PeerConfig should serialize to dict correctly."""
        from styrened.services.config import serialize_config

        config = CoreConfig()
        config.reticulum.interfaces.peers = [
            PeerConfig(host="rns.styrene.io", port=4242, name="Hub"),
            PeerConfig(host="10.0.0.1", port=5555),
        ]
        data = serialize_config(config)
        peers = data["reticulum"]["interfaces"]["peers"]
        assert len(peers) == 2
        assert peers[0]["host"] == "rns.styrene.io"
        assert peers[0]["port"] == 4242
        assert peers[0]["name"] == "Hub"
        assert peers[1]["host"] == "10.0.0.1"
        assert "name" not in peers[1]

    def test_peer_config_round_trip(self, tmp_path):
        """Peers should survive save → load round trip."""
        from styrened.services.config import load_core_config, save_core_config

        config = CoreConfig()
        config.reticulum.interfaces.peers = [
            PeerConfig(host="relay.example.com", port=9999, name="Test Relay"),
        ]
        config.reticulum.interfaces.auto = True
        config.reticulum.interfaces.server = ServerInterfaceConfig(
            enabled=True, listen_ip="127.0.0.1", port=8888
        )

        config_path = tmp_path / "config.yaml"
        save_core_config(config, config_path)
        loaded = load_core_config(config_path)

        # Explicit peer preserved at start, well-known hubs merged as disabled
        assert loaded.reticulum.interfaces.peers[0].host == "relay.example.com"
        assert loaded.reticulum.interfaces.peers[0].port == 9999
        assert loaded.reticulum.interfaces.peers[0].name == "Test Relay"
        from styrened.models.config import WELL_KNOWN_HUBS
        assert len(loaded.reticulum.interfaces.peers) == 1 + len(WELL_KNOWN_HUBS)
        assert loaded.reticulum.interfaces.auto is True
        assert loaded.reticulum.interfaces.server.enabled is True
        assert loaded.reticulum.interfaces.server.listen_ip == "127.0.0.1"
        assert loaded.reticulum.interfaces.server.port == 8888

    def test_deployment_mode_round_trip(self, tmp_path):
        """Deployment mode should survive save → load round trip."""
        from styrened.services.config import load_core_config, save_core_config

        for mode in DeploymentMode:
            config = CoreConfig()
            config.reticulum.mode = mode
            path = tmp_path / f"config_{mode.value}.yaml"
            save_core_config(config, path)
            loaded = load_core_config(path)
            assert loaded.reticulum.mode == mode


class TestNetworkConfigValidation:
    """Test validation of network-related config fields."""

    def test_peer_empty_host_rejected(self):
        """Peer with empty host should fail validation."""
        from styrened.services.config import validate_core_config

        config = CoreConfig()
        config.reticulum.interfaces.peers = [PeerConfig(host="", port=4242)]
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert any("peers" in f and "host" in f for f in field_names)

    def test_peer_invalid_port_rejected(self):
        """Peer with port out of range should fail validation."""
        from styrened.services.config import validate_core_config

        config = CoreConfig()
        config.reticulum.interfaces.peers = [PeerConfig(host="10.0.0.1", port=99999)]
        errors = validate_core_config(config)
        field_names = [e.field for e in errors]
        assert any("port" in f for f in field_names)

    def test_hub_mode_without_interfaces_warns(self):
        """Hub mode with no server or peers should produce validation error."""
        from styrened.services.config import validate_core_config

        config = CoreConfig()
        config.reticulum.mode = DeploymentMode.HUB
        config.reticulum.interfaces.server = ServerInterfaceConfig(enabled=False)
        config.reticulum.interfaces.peers = []
        errors = validate_core_config(config)
        assert len(errors) > 0
        assert any("hub" in str(e).lower() for e in errors)
