"""Tests for TUI config serialization roundtrip.

O3: Verify _parse_config_dict ↔ _config_to_dict preserve all fields.
"""

import pytest

from styrened.tui.models.config import LogLevel, StyreneConfig, TUIConfig
from styrened.tui.services.config import (
    _config_to_dict,
    _parse_config_dict,
    get_default_config,
)


def _roundtrip(config: StyreneConfig) -> StyreneConfig:
    """Serialize config to dict and parse it back."""
    data = _config_to_dict(config)
    return _parse_config_dict(data)


class TestTuiConfigRoundtrip:
    """Verify TUI config fields survive serialize → parse roundtrip."""

    def test_theme_roundtrip(self) -> None:
        """Theme string survives roundtrip."""
        config = get_default_config()
        config.tui.theme = "mars"
        result = _roundtrip(config)
        assert result.tui.theme == "mars"

    def test_custom_theme_url_roundtrip(self) -> None:
        """custom_theme_url survives roundtrip."""
        config = get_default_config()
        config.tui.custom_theme_url = "https://example.com/theme.json"
        result = _roundtrip(config)
        assert result.tui.custom_theme_url == "https://example.com/theme.json"

    def test_empty_custom_theme_url_roundtrip(self) -> None:
        """Empty custom_theme_url survives roundtrip."""
        config = get_default_config()
        config.tui.custom_theme_url = ""
        result = _roundtrip(config)
        assert result.tui.custom_theme_url == ""

    def test_log_level_roundtrip(self) -> None:
        """LogLevel enum roundtrips correctly."""
        config = get_default_config()
        config.tui.log_level = LogLevel.DEBUG
        result = _roundtrip(config)
        assert result.tui.log_level == LogLevel.DEBUG

    def test_bool_fields_roundtrip(self) -> None:
        """Boolean TUI fields roundtrip."""
        config = get_default_config()
        config.tui.show_hardware_panel = False
        config.tui.confirm_destructive = False
        result = _roundtrip(config)
        assert result.tui.show_hardware_panel is False
        assert result.tui.confirm_destructive is False

    def test_custom_theme_url_coexists_with_theme(self) -> None:
        """Theme and custom_theme_url can both be set."""
        config = get_default_config()
        config.tui.theme = "stygies"
        config.tui.custom_theme_url = "https://example.com/my-theme.json"
        result = _roundtrip(config)
        assert result.tui.theme == "stygies"
        assert result.tui.custom_theme_url == "https://example.com/my-theme.json"

    def test_default_config_roundtrips_cleanly(self) -> None:
        """Default config survives roundtrip without mutation."""
        config = get_default_config()
        result = _roundtrip(config)
        assert result.tui.theme == config.tui.theme
        assert result.tui.log_level == config.tui.log_level
        assert result.tui.show_hardware_panel == config.tui.show_hardware_panel

    def test_fleet_config_roundtrip(self) -> None:
        """Fleet config fields survive roundtrip."""
        config = get_default_config()
        config.fleet.inventory_file = "custom/path.yaml"
        config.fleet.auto_sync_inventory = False
        result = _roundtrip(config)
        assert result.fleet.inventory_file == "custom/path.yaml"
        assert result.fleet.auto_sync_inventory is False

    def test_provisioning_defaults_roundtrip(self) -> None:
        """Provisioning defaults roundtrip."""
        config = get_default_config()
        config.provisioning.default_hostname_prefix = "edge"
        config.provisioning.default_device_type = "rpi4"
        result = _roundtrip(config)
        assert result.provisioning.default_hostname_prefix == "edge"
        assert result.provisioning.default_device_type == "rpi4"


class TestParseConfigEdgeCases:
    """Edge cases in _parse_config_dict."""

    def test_empty_dict_returns_defaults(self) -> None:
        """Empty dict produces default config."""
        config = _parse_config_dict({})
        default = get_default_config()
        assert config.tui.theme == default.tui.theme

    def test_unknown_keys_ignored(self) -> None:
        """Unknown top-level keys don't cause errors."""
        config = _parse_config_dict({"unknown_section": {"foo": "bar"}})
        assert config.tui.theme == get_default_config().tui.theme

    def test_tui_section_not_dict_ignored(self) -> None:
        """Non-dict tui section is ignored gracefully."""
        config = _parse_config_dict({"tui": "not_a_dict"})
        assert config.tui.theme == get_default_config().tui.theme

    def test_invalid_log_level_keeps_default(self) -> None:
        """Invalid log_level string keeps default (suppressed ValueError)."""
        config = _parse_config_dict({"tui": {"log_level": "NONEXISTENT"}})
        assert config.tui.log_level == LogLevel.INFO

    def test_theme_value_cast_to_string(self) -> None:
        """Numeric theme value is cast to string."""
        config = _parse_config_dict({"tui": {"theme": 12345}})
        assert config.tui.theme == "12345"

    def test_custom_theme_url_value_cast_to_string(self) -> None:
        """Non-string custom_theme_url is cast to string."""
        config = _parse_config_dict({"tui": {"custom_theme_url": 42}})
        assert config.tui.custom_theme_url == "42"


class TestConfigToDict:
    """Verify _config_to_dict output structure."""

    def test_tui_section_present(self) -> None:
        config = get_default_config()
        d = _config_to_dict(config)
        assert "tui" in d
        assert "theme" in d["tui"]
        assert "custom_theme_url" in d["tui"]

    def test_all_top_level_sections_present(self) -> None:
        config = get_default_config()
        d = _config_to_dict(config)
        for section in ("tui", "fleet", "provisioning", "mesh"):
            assert section in d, f"Missing section: {section}"
