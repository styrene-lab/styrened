"""Test configuration persistence."""

from pathlib import Path

import pytest

from styrened.tui.models.config import DeploymentMode, PeerConfig
from styrened.tui.services.config import (
    get_default_config,
    load_config,
    save_config,
    save_rns_config,
    update_styrene_config_from_cli,
)


def test_save_and_load_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test saving and loading configuration."""
    # Mock config directory
    config_dir = tmp_path / ".styrene"
    monkeypatch.setattr("styrened.tui.services.config.get_config_dir", lambda: config_dir)

    # Create config
    config = get_default_config()
    config.reticulum.mode = DeploymentMode.HUB
    config.reticulum.interfaces.server.enabled = True
    config.reticulum.interfaces.server.port = 4242
    config.reticulum.interfaces.peers = [
        PeerConfig(host="home.example.com", port=4242, name="Home Hub")
    ]

    # Save
    save_config(config)

    # Verify file exists
    config_file = config_dir / "config.yaml"
    assert config_file.exists()

    # Load
    loaded_config = load_config()

    # Verify loaded values match
    assert loaded_config.reticulum.mode == DeploymentMode.HUB
    assert loaded_config.reticulum.interfaces.server.enabled is True
    assert loaded_config.reticulum.interfaces.server.port == 4242
    assert len(loaded_config.reticulum.interfaces.peers) == 1
    assert loaded_config.reticulum.interfaces.peers[0].host == "home.example.com"
    assert loaded_config.reticulum.interfaces.peers[0].name == "Home Hub"


def test_cli_overrides_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that CLI overrides are persisted to config."""
    # Mock config directory
    config_dir = tmp_path / ".styrene"
    monkeypatch.setattr("styrened.tui.services.config.get_config_dir", lambda: config_dir)

    # Start with defaults
    config = get_default_config()
    assert config.reticulum.mode == DeploymentMode.STANDALONE

    # Apply CLI overrides
    updated_config = update_styrene_config_from_cli(
        config,
        mode=DeploymentMode.HUB,
        server_port=4242,
        peers=[PeerConfig(host="peer.example.com", port=4242)],
        api_port=8000,
        headless=True,
    )

    # Verify updated values
    assert updated_config.reticulum.mode == DeploymentMode.HUB
    assert updated_config.reticulum.interfaces.server.port == 4242
    assert updated_config.reticulum.interfaces.server.enabled is True  # Auto-enabled in hub mode
    # Default config includes hub peer, CLI adds another peer
    assert len(updated_config.reticulum.interfaces.peers) == 2
    assert updated_config.reticulum.interfaces.peers[1].host == "peer.example.com"
    assert updated_config.api.enabled is True
    assert updated_config.api.port == 8000
    assert updated_config.advanced.headless is True

    # Verify persisted to disk
    config_file = config_dir / "config.yaml"
    assert config_file.exists()

    # Load from disk and verify
    loaded_config = load_config()
    assert loaded_config.reticulum.mode == DeploymentMode.HUB
    assert loaded_config.reticulum.interfaces.server.enabled is True
    assert loaded_config.api.enabled is True


def test_rns_config_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test Reticulum config generation."""
    # Mock RNS config directory
    rns_dir = tmp_path / ".config" / "reticulum"
    monkeypatch.setattr("styrened.tui.services.config.get_rns_config_dir", lambda: rns_dir)

    # Create Styrene config with hub mode
    config = get_default_config()
    config.reticulum.mode = DeploymentMode.HUB
    config.reticulum.interfaces.server.enabled = True
    config.reticulum.interfaces.server.port = 4242
    config.reticulum.interfaces.peers = [
        PeerConfig(host="peer1.example.com", port=4242, name="Peer 1"),
        PeerConfig(host="peer2.example.com", port=4965, name="Peer 2"),
    ]

    # Generate RNS config
    rns_config_path = save_rns_config(config)

    # Verify file created
    assert rns_config_path.exists()
    assert rns_config_path == rns_dir / "config"

    # Read and verify content
    content = rns_config_path.read_text()

    # Check transport enabled
    assert "enable_transport = true" in content

    # Check AutoInterface
    assert "[[AutoInterface]]" in content
    assert "type = AutoInterface" in content

    # Check TCP Server Interface
    assert "[[TCP Server Interface]]" in content
    assert "type = TCPServerInterface" in content
    assert "listen_port = 4242" in content

    # Check peers
    assert "[[Peer 1]]" in content
    assert "target_host = peer1.example.com" in content
    assert "[[Peer 2]]" in content
    assert "target_host = peer2.example.com" in content
    assert "target_port = 4965" in content


def test_config_defaults() -> None:
    """Test default configuration values."""
    config = get_default_config()

    # Verify defaults
    assert config.reticulum.mode == DeploymentMode.STANDALONE
    assert config.reticulum.interfaces.auto is True
    assert config.reticulum.interfaces.server.enabled is False
    assert config.reticulum.interfaces.server.port == 4242
    # Default config includes pre-configured Styrene Community Hub peer
    assert len(config.reticulum.interfaces.peers) == 1
    assert config.reticulum.interfaces.peers[0].host == "192.168.0.102"
    assert config.reticulum.interfaces.peers[0].port == 4242
    assert config.reticulum.interfaces.peers[0].name == "Styrene Community Hub"
    assert config.reticulum.announce_interval == 300
    # Hub is pre-configured
    assert config.reticulum.hub_enabled is True
    assert config.reticulum.hub_address == "6fc8bf22aa293588c9bf8d7488102e95"

    assert config.api.enabled is False
    assert config.api.port == 8000

    assert config.advanced.headless is False


def test_auto_enable_server_in_hub_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that server interface is auto-enabled in hub mode."""
    # Mock config directory
    config_dir = tmp_path / ".styrene"
    monkeypatch.setattr("styrened.tui.services.config.get_config_dir", lambda: config_dir)

    # Start with standalone
    config = get_default_config()
    assert config.reticulum.mode == DeploymentMode.STANDALONE
    assert config.reticulum.interfaces.server.enabled is False

    # Switch to hub mode
    updated_config = update_styrene_config_from_cli(config, mode=DeploymentMode.HUB)

    # Server should be auto-enabled
    assert updated_config.reticulum.mode == DeploymentMode.HUB
    assert updated_config.reticulum.interfaces.server.enabled is True
