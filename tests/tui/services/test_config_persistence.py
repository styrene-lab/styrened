"""Test configuration persistence."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from styrened.services.config import load_core_config, save_core_config
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
    monkeypatch.setattr("styrened.paths.config_dir", lambda: config_dir)

    # Create config
    config = get_default_config()
    config.reticulum.mode = DeploymentMode.HUB
    config.reticulum.interfaces.server.enabled = True
    config.reticulum.interfaces.server.port = 4242
    config.reticulum.interfaces.peers = [
        PeerConfig(host="home.example.com", port=4242, name="Home Hub")
    ]

    # Save TUI config plus core-config-backed runtime settings.
    save_config(config)
    core_config = load_core_config()
    core_config.reticulum.mode = config.reticulum.mode
    core_config.reticulum.interfaces.server.enabled = config.reticulum.interfaces.server.enabled
    core_config.reticulum.interfaces.server.port = config.reticulum.interfaces.server.port
    core_config.reticulum.interfaces.peers = config.reticulum.interfaces.peers
    save_core_config(core_config)

    # Verify file exists
    config_file = config_dir / "tui.yaml"
    assert config_file.exists()

    # Load
    loaded_config = load_config()

    # Verify loaded values match
    assert loaded_config.reticulum.mode == DeploymentMode.HUB
    assert loaded_config.reticulum.interfaces.server.enabled is True
    assert loaded_config.reticulum.interfaces.server.port == 4242
    peer_hosts = {peer.host for peer in loaded_config.reticulum.interfaces.peers}
    assert "home.example.com" in peer_hosts
    home_peer = next(
        peer for peer in loaded_config.reticulum.interfaces.peers if peer.host == "home.example.com"
    )
    assert home_peer.name == "Home Hub"


def test_cli_overrides_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that CLI overrides are persisted to config."""
    # Mock config directory
    config_dir = tmp_path / ".styrene"
    monkeypatch.setattr("styrened.paths.config_dir", lambda: config_dir)

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
    peer_hosts = {peer.host for peer in updated_config.reticulum.interfaces.peers}
    assert "peer.example.com" in peer_hosts
    assert updated_config.api.enabled is True
    assert updated_config.api.port == 8000
    assert updated_config.advanced.headless is True

    # Verify persisted to disk
    config_file = config_dir / "tui.yaml"
    assert config_file.exists()

    core_config = load_core_config()
    core_config.reticulum.mode = updated_config.reticulum.mode
    core_config.reticulum.interfaces.server.enabled = updated_config.reticulum.interfaces.server.enabled
    core_config.api.enabled = updated_config.api.enabled
    save_core_config(core_config)

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
    assert config.reticulum.interfaces.auto is False
    assert config.reticulum.interfaces.server.enabled is False
    assert config.reticulum.interfaces.server.port == 4242
    # Default config includes the well-known hub set, with the Styrene hub enabled.
    peer_hosts = {peer.host for peer in config.reticulum.interfaces.peers}
    assert "rns.styrene.io" in peer_hosts
    primary_hub = next(
        peer for peer in config.reticulum.interfaces.peers if peer.host == "rns.styrene.io"
    )
    assert primary_hub.port == 4242
    assert primary_hub.name == "Styrene Community Hub"
    assert primary_hub.enabled is True
    assert config.reticulum.announce_interval == 3600
    # Hub is pre-configured
    assert config.reticulum.hub_enabled is True
    assert config.reticulum.hub_address == "6fc8bf22aa293588c9bf8d7488102e95"

    assert config.api.enabled is False
    assert config.api.port == 8000

    assert config.advanced.headless is False


def test_identity_loaded_from_core_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Identity saved to core config.yaml must be visible when TUI reloads."""
    config_dir = tmp_path / ".styrene"
    config_dir.mkdir()
    monkeypatch.setattr("styrened.paths.config_dir", lambda: config_dir)

    # Write a core config.yaml with identity fields (as _save_identity does)
    core_config_path = config_dir / "config.yaml"
    core_config_path.write_text(yaml.dump({
        "identity": {
            "display_name": "Alice Mesh",
            "icon": "🛰️",
            "short_name": "alice",
        },
    }))

    # Save a minimal TUI config so load_config() doesn't fall back to defaults
    tui_config_path = config_dir / "tui.yaml"
    tui_config_path.write_text(yaml.dump({
        "tui": {"log_level": "INFO"},
    }))

    # Load TUI config — identity must come from core config.yaml
    config = load_config()
    assert config.identity.display_name == "Alice Mesh"
    assert config.identity.icon == "🛰️"
    assert config.identity.short_name == "alice"


def test_identity_roundtrip_through_core_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Identity set via _save_identity (local mode) survives TUI restart."""
    config_dir = tmp_path / ".styrene"
    config_dir.mkdir()
    monkeypatch.setattr("styrened.paths.config_dir", lambda: config_dir)

    # Simulate what _save_identity does in local mode
    from styrened.services.config import load_core_config, save_core_config

    core_cfg = load_core_config()
    core_cfg.identity.display_name = "Bob Node"
    core_cfg.identity.icon = "📡"
    core_cfg.identity.short_name = "bob"
    save_core_config(core_cfg)

    # Also save a TUI config
    config = get_default_config()
    save_config(config)

    # Reload TUI config — identity must reflect core config values
    loaded = load_config()
    assert loaded.identity.display_name == "Bob Node"
    assert loaded.identity.icon == "📡"
    assert loaded.identity.short_name == "bob"


def test_auto_enable_server_in_hub_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that server interface is auto-enabled in hub mode."""
    # Mock config directory
    config_dir = tmp_path / ".styrene"
    monkeypatch.setattr("styrened.paths.config_dir", lambda: config_dir)

    # Start with standalone
    config = get_default_config()
    assert config.reticulum.mode == DeploymentMode.STANDALONE
    assert config.reticulum.interfaces.server.enabled is False

    # Switch to hub mode
    updated_config = update_styrene_config_from_cli(config, mode=DeploymentMode.HUB)

    # Server should be auto-enabled
    assert updated_config.reticulum.mode == DeploymentMode.HUB
    assert updated_config.reticulum.interfaces.server.enabled is True


def test_tui_default_hub_announce_interval_is_public_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TUI defaults should not recreate the legacy 60-second hub announce cadence."""
    config_dir = tmp_path / ".styrene"
    monkeypatch.setattr("styrened.paths.config_dir", lambda: config_dir)

    config = get_default_config()

    assert config.reticulum.hub_announce_interval == 3600
