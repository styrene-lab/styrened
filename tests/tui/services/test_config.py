"""Tests for configuration service."""

import tempfile
from pathlib import Path

import pytest

from styrened.tui.models.config import (
    ConfigLoadError,
    ConfigValidationError,
    GatewayMode,
    LogLevel,
    StyreneConfig,
    ThemeMode,
)
from styrened.tui.services.config import (
    get_default_config,
    load_config,
    save_config,
    validate_config,
)


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for config testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestGetDefaultConfig:
    """Tests for default configuration generation."""

    def test_get_default_config(self):
        """Test generating default configuration."""
        config = get_default_config()
        assert isinstance(config, StyreneConfig)
        assert config.tui.theme == ThemeMode.STYRENE
        assert config.tui.log_level == LogLevel.INFO
        assert config.mesh.mesh_id == "styrene"
        assert config.mesh.channel == 6
        assert config.mesh.gateway_mode == GatewayMode.CLIENT

    def test_default_config_auto_detects_ssh_keys(self):
        """Test that default config finds SSH keys if they exist."""
        config = get_default_config()
        # ssh_key_paths should be a list (may be empty if no keys found)
        assert isinstance(config.provisioning.ssh_key_paths, list)
        # Each entry should be a Path
        for path in config.provisioning.ssh_key_paths:
            assert isinstance(path, Path)


class TestConfigValidation:
    """Tests for configuration validation."""

    def test_validate_valid_config(self):
        """Test validating a valid configuration."""
        config = get_default_config()
        errors = validate_config(config)
        assert len(errors) == 0

    def test_validate_invalid_channel(self):
        """Test validating config with invalid channel."""
        config = get_default_config()
        config.mesh.channel = 99  # Invalid channel
        errors = validate_config(config)
        assert len(errors) > 0
        assert any("channel" in str(e) for e in errors)

    def test_validate_invalid_channel_low(self):
        """Test validating config with channel too low."""
        config = get_default_config()
        config.mesh.channel = 0
        errors = validate_config(config)
        assert len(errors) > 0

    def test_validate_nonexistent_edge_fleet_path(self, temp_config_dir):
        """Test validating config with non-existent edge_fleet_path."""
        config = get_default_config()
        config.fleet.edge_fleet_path = temp_config_dir / "nonexistent"
        errors = validate_config(config)
        assert len(errors) > 0
        assert any("edge_fleet_path" in e.field for e in errors)

    def test_validate_nonexistent_ssh_key(self, temp_config_dir):
        """Test validating config with non-existent SSH key."""
        config = get_default_config()
        config.provisioning.ssh_key_paths = [temp_config_dir / "nonexistent.pub"]
        errors = validate_config(config)
        assert len(errors) > 0
        assert any("ssh_key_paths" in e.field for e in errors)

    def test_validate_invalid_hub_address_length(self):
        """Test validating config with invalid hub address length."""
        config = get_default_config()
        config.reticulum.hub_enabled = True
        config.reticulum.hub_address = "abc123"  # Too short
        errors = validate_config(config)
        assert len(errors) > 0
        assert any("hub_address" in e.field for e in errors)

    def test_validate_invalid_hub_address_chars(self):
        """Test validating config with invalid hub address characters."""
        config = get_default_config()
        config.reticulum.hub_enabled = True
        config.reticulum.hub_address = "g" * 32  # Invalid hex chars
        errors = validate_config(config)
        assert len(errors) > 0
        assert any("hub_address" in e.field for e in errors)

    def test_validate_valid_hub_address(self):
        """Test validating config with valid hub address."""
        config = get_default_config()
        config.reticulum.hub_enabled = True
        config.reticulum.hub_address = "a1b2c3d4" * 4  # 32 hex chars
        errors = validate_config(config)
        # Should have no errors related to hub_address
        assert not any("hub_address" in e.field for e in errors)


class TestConfigLoadSave:
    """Tests for configuration loading and saving."""

    def test_save_and_load_config(self, temp_config_dir, monkeypatch):
        """Test save and load roundtrip."""
        # Create a config file path
        config_file = temp_config_dir / "config.yaml"

        # Monkey-patch get_config_path to use our temp file
        monkeypatch.setattr("styrened.tui.services.config.get_config_path", lambda: config_file)

        # Create a custom config
        config = get_default_config()
        config.tui.log_level = LogLevel.DEBUG
        config.mesh.mesh_id = "test-mesh"
        config.mesh.channel = 11

        # Save it
        save_config(config)

        # Verify file exists
        assert config_file.exists()

        # Load it back
        loaded_config = load_config()

        # Verify values match
        assert loaded_config.tui.log_level == LogLevel.DEBUG
        assert loaded_config.mesh.mesh_id == "test-mesh"
        assert loaded_config.mesh.channel == 11

    def test_load_nonexistent_config(self, temp_config_dir, monkeypatch):
        """Test loading when no config file exists returns defaults."""
        config_file = temp_config_dir / "nonexistent.yaml"
        monkeypatch.setattr("styrened.tui.services.config.get_config_path", lambda: config_file)

        config = load_config()
        assert isinstance(config, StyreneConfig)
        # Should be defaults
        assert config.tui.theme == ThemeMode.STYRENE

    def test_load_invalid_yaml(self, temp_config_dir, monkeypatch):
        """Test loading invalid YAML raises error."""
        config_file = temp_config_dir / "config.yaml"
        config_file.write_text("invalid: yaml: [syntax")

        monkeypatch.setattr("styrened.tui.services.config.get_config_path", lambda: config_file)

        with pytest.raises(ConfigLoadError):
            load_config()

    def test_save_invalid_config_raises(self, temp_config_dir, monkeypatch):
        """Test saving invalid config raises validation error."""
        config_file = temp_config_dir / "config.yaml"
        monkeypatch.setattr("styrened.tui.services.config.get_config_path", lambda: config_file)

        config = get_default_config()
        config.mesh.channel = 99  # Invalid

        with pytest.raises(ConfigValidationError):
            save_config(config)

    def test_load_partial_config(self, temp_config_dir, monkeypatch):
        """Test loading partial config merges with defaults."""
        config_file = temp_config_dir / "config.yaml"

        # Write minimal config
        config_file.write_text(
            """
tui:
  log_level: debug
mesh:
  mesh_id: custom-mesh
"""
        )

        monkeypatch.setattr("styrened.tui.services.config.get_config_path", lambda: config_file)

        config = load_config()

        # Specified values should be present
        assert config.tui.log_level == LogLevel.DEBUG
        assert config.mesh.mesh_id == "custom-mesh"

        # Unspecified values should have defaults
        assert config.tui.theme == ThemeMode.STYRENE
        assert config.mesh.channel == 6

    def test_config_file_has_comment_header(self, temp_config_dir, monkeypatch):
        """Test saved config file has header comments."""
        config_file = temp_config_dir / "config.yaml"
        monkeypatch.setattr("styrened.tui.services.config.get_config_path", lambda: config_file)

        config = get_default_config()
        save_config(config)

        content = config_file.read_text()
        assert "Styrene TUI Configuration" in content
        assert "Settings screen" in content

    def test_ssh_key_paths_expansion(self, temp_config_dir, monkeypatch):
        """Test SSH key paths are expanded with ~ properly."""
        config_file = temp_config_dir / "config.yaml"

        # Create a test SSH key file
        home = Path.home()
        test_key = home / "test_key.pub"
        test_key.write_text("test ssh key")

        try:
            config_file.write_text(
                """
provisioning:
  ssh_key_paths:
    - ~/test_key.pub
"""
            )

            monkeypatch.setattr("styrened.tui.services.config.get_config_path", lambda: config_file)

            config = load_config()

            # Path should be expanded (not contain ~)
            if config.provisioning.ssh_key_paths:
                for path in config.provisioning.ssh_key_paths:
                    assert "~" not in str(path)
                    assert path == home / "test_key.pub"
        finally:
            # Cleanup
            if test_key.exists():
                test_key.unlink()


class TestConfigTypes:
    """Tests for configuration enum types."""

    def test_log_level_enum(self):
        """Test LogLevel enum values."""
        assert LogLevel.DEBUG.value == "debug"
        assert LogLevel.INFO.value == "info"
        assert LogLevel.WARNING.value == "warning"
        assert LogLevel.ERROR.value == "error"

    def test_theme_mode_enum(self):
        """Test ThemeMode enum values."""
        assert ThemeMode.STYRENE.value == "styrene"

    def test_gateway_mode_enum(self):
        """Test GatewayMode enum values."""
        assert GatewayMode.OFF.value == "off"
        assert GatewayMode.CLIENT.value == "client"
        assert GatewayMode.SERVER.value == "server"
