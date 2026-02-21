"""Tests for core config service."""

import tempfile
from pathlib import Path

from styrened.models.config import CoreConfig, DeploymentMode, Profile
from styrened.services.config import (
    get_default_core_config,
    load_core_config,
    save_core_config,
)


def test_default_config() -> None:
    """Default config should have sensible operator profile values."""
    config = get_default_core_config()
    assert config.profile == Profile.OPERATOR
    assert config.reticulum.mode == DeploymentMode.STANDALONE
    assert config.rpc.enabled is True
    assert config.rpc.allow_command_execution is False
    assert config.discovery.enabled is True
    assert config.chat.auto_reply_enabled is False


def test_config_roundtrip() -> None:
    """Config should survive save/load cycle."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "test-config.yaml"

        # Create and modify config
        original = get_default_core_config()
        original.reticulum.announce_interval = 600
        original.rpc.enabled = False
        original.chat.auto_reply_enabled = False

        # Save
        save_core_config(original, config_path)
        assert config_path.exists()

        # Load
        loaded = load_core_config(config_path)

        # Verify values survived the roundtrip
        assert loaded is not None
        assert isinstance(loaded, CoreConfig)
        assert loaded.reticulum.announce_interval == 600
        assert loaded.rpc.enabled is False
        assert loaded.chat.auto_reply_enabled is False


def test_load_missing_config() -> None:
    """Loading missing config should return defaults."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "nonexistent.yaml"
        config = load_core_config(config_path)

        assert config is not None
        assert config.reticulum.mode == DeploymentMode.STANDALONE
