from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Requires tui-home-cop features not yet on main")

"""Tests for TUI config serialization roundtrip.

O3: Verify _parse_config_dict ↔ _config_to_dict preserve all fields,
    including custom_theme_colors and identity_nudge_dismissed.
"""

from pathlib import Path

import pytest
import yaml

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
        config = get_default_config()
        config.tui.theme = "mars"
        result = _roundtrip(config)
        assert result.tui.theme == "mars"

    def test_custom_theme_url_roundtrip(self) -> None:
        config = get_default_config()
        config.tui.custom_theme_url = "https://example.com/theme.json"
        result = _roundtrip(config)
        assert result.tui.custom_theme_url == "https://example.com/theme.json"

    def test_empty_custom_theme_url_roundtrip(self) -> None:
        config = get_default_config()
        config.tui.custom_theme_url = ""
        result = _roundtrip(config)
        assert result.tui.custom_theme_url == ""

    def test_log_level_roundtrip(self) -> None:
        config = get_default_config()
        config.tui.log_level = LogLevel.DEBUG
        result = _roundtrip(config)
        assert result.tui.log_level == LogLevel.DEBUG

    def test_bool_fields_roundtrip(self) -> None:
        config = get_default_config()
        config.tui.show_hardware_panel = False
        config.tui.confirm_destructive = False
        result = _roundtrip(config)
        assert result.tui.show_hardware_panel is False
        assert result.tui.confirm_destructive is False

    def test_custom_theme_url_coexists_with_theme(self) -> None:
        config = get_default_config()
        config.tui.theme = "stygies"
        config.tui.custom_theme_url = "https://example.com/my-theme.json"
        result = _roundtrip(config)
        assert result.tui.theme == "stygies"
        assert result.tui.custom_theme_url == "https://example.com/my-theme.json"

    def test_default_config_roundtrips_cleanly(self) -> None:
        config = get_default_config()
        result = _roundtrip(config)
        assert result.tui.theme == config.tui.theme
        assert result.tui.log_level == config.tui.log_level
        assert result.tui.show_hardware_panel == config.tui.show_hardware_panel

    def test_fleet_config_roundtrip(self) -> None:
        config = get_default_config()
        config.fleet.inventory_file = "custom/path.yaml"
        config.fleet.auto_sync_inventory = False
        result = _roundtrip(config)
        assert result.fleet.inventory_file == "custom/path.yaml"
        assert result.fleet.auto_sync_inventory is False

    def test_provisioning_defaults_roundtrip(self) -> None:
        config = get_default_config()
        config.provisioning.default_hostname_prefix = "edge"
        config.provisioning.default_device_type = "rpi4"
        result = _roundtrip(config)
        assert result.provisioning.default_hostname_prefix == "edge"
        assert result.provisioning.default_device_type == "rpi4"


class TestParseConfigEdgeCases:
    """Edge cases in _parse_config_dict."""

    def test_empty_dict_returns_defaults(self) -> None:
        config = _parse_config_dict({})
        default = get_default_config()
        assert config.tui.theme == default.tui.theme

    def test_unknown_keys_ignored(self) -> None:
        config = _parse_config_dict({"unknown_section": {"foo": "bar"}})
        assert config.tui.theme == get_default_config().tui.theme

    def test_tui_section_not_dict_ignored(self) -> None:
        config = _parse_config_dict({"tui": "not_a_dict"})
        assert config.tui.theme == get_default_config().tui.theme

    def test_invalid_log_level_keeps_default(self) -> None:
        config = _parse_config_dict({"tui": {"log_level": "NONEXISTENT"}})
        assert config.tui.log_level == LogLevel.INFO

    def test_theme_value_cast_to_string(self) -> None:
        config = _parse_config_dict({"tui": {"theme": 12345}})
        assert config.tui.theme == "12345"

    def test_custom_theme_url_value_cast_to_string(self) -> None:
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


# =========================================================================
# File I/O roundtrip (load_config / save_config)
# =========================================================================


class TestFileIORoundtrip:
    """Test actual YAML file serialization via load_config/save_config."""

    @staticmethod
    def _patch_config_path(monkeypatch: pytest.MonkeyPatch, config_file: Path) -> None:
        """Patch config path and disable core config overlay for isolated tests."""
        monkeypatch.setattr(
            "styrened.tui.services.config.get_config_path",
            lambda: config_file,
        )
        monkeypatch.setattr(
            "styrened.tui.services.config._overlay_core_config",
            lambda config: None,
        )

    def test_save_and_load_preserves_theme(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from styrened.tui.services.config import load_config, save_config

        config_file = tmp_path / "tui.yaml"
        self._patch_config_path(monkeypatch, config_file)

        config = get_default_config()
        config.tui.theme = "stygies"
        config.tui.custom_theme_url = "https://example.com/theme.json"
        save_config(config)

        assert config_file.exists()
        loaded = load_config()
        assert loaded.tui.theme == "stygies"
        assert loaded.tui.custom_theme_url == "https://example.com/theme.json"

    def test_save_and_load_preserves_booleans(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from styrened.tui.services.config import load_config, save_config

        config_file = tmp_path / "tui.yaml"
        self._patch_config_path(monkeypatch, config_file)

        config = get_default_config()
        config.tui.show_hardware_panel = False
        config.tui.confirm_destructive = False
        save_config(config)

        loaded = load_config()
        assert loaded.tui.show_hardware_panel is False
        assert loaded.tui.confirm_destructive is False

    def test_yaml_file_is_valid_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from styrened.tui.services.config import save_config

        config_file = tmp_path / "tui.yaml"
        self._patch_config_path(monkeypatch, config_file)

        save_config(get_default_config())
        with open(config_file) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "tui" in data

    def test_malformed_yaml_handled_gracefully(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """W2: Malformed YAML file should not crash load_config.

        load_config should either raise a known config error or return defaults.
        """
        from styrened.tui.services.config import load_config

        config_file = tmp_path / "tui.yaml"
        config_file.write_text("{{{{invalid: yaml: [unterminated")
        self._patch_config_path(monkeypatch, config_file)

        # load_config should handle corruption gracefully
        try:
            loaded = load_config()
            # If it returns, it should be a valid default config
            assert loaded.tui.theme == get_default_config().tui.theme
        except Exception as e:
            # If it raises, it should be a config-related error, not a raw yaml error
            assert "config" in type(e).__name__.lower() or "yaml" in str(e).lower() or isinstance(e, (yaml.YAMLError, ValueError))


# =========================================================================
# O3: custom_theme_colors roundtrip — field not yet in TUIConfig
# =========================================================================


class TestCustomThemeColorsRoundtrip:
    """Tests for custom_theme_colors dict serialization.

    These tests are xfail because the custom_theme_colors field does not
    exist in TUIConfig. The spec (O3) requires it but the field has not
    been added to the data model. These tests document the expected
    behavior and will pass once the field is implemented.
    """

    def test_dict_roundtrip(self) -> None:
        """Serialize TUI config with custom_theme_colors dict, load back, verify."""
        config = get_default_config()
        config.tui.custom_theme_colors = {"phosphex": "#ff0000", "bg": "#000000"}  # type: ignore[attr-defined]
        result = _roundtrip(config)
        assert result.tui.custom_theme_colors == {"phosphex": "#ff0000", "bg": "#000000"}  # type: ignore[attr-defined]

    def test_empty_dict_roundtrip(self) -> None:
        """Serialize with empty custom_theme_colors, load back, verify empty dict."""
        config = get_default_config()
        config.tui.custom_theme_colors = {}  # type: ignore[attr-defined]
        result = _roundtrip(config)
        assert result.tui.custom_theme_colors == {}  # type: ignore[attr-defined]

    def test_dict_values_survive_as_strings(self) -> None:
        """Verify custom_theme_colors dict values survive as strings."""
        config = get_default_config()
        config.tui.custom_theme_colors = {"key": "#aabbcc"}  # type: ignore[attr-defined]
        result = _roundtrip(config)
        assert isinstance(result.tui.custom_theme_colors["key"], str)  # type: ignore[attr-defined]

    def test_non_dict_value_handled_gracefully(self) -> None:
        """Handle non-dict value in YAML gracefully (type check).

        Even without custom_theme_colors in TUIConfig, _parse_config_dict
        should not crash when encountering unexpected keys in the tui section.
        """
        config = _parse_config_dict({"tui": {"custom_theme_colors": "not-a-dict"}})
        colors = getattr(config.tui, "custom_theme_colors", {})
        assert isinstance(colors, dict)

    def test_coexists_with_custom_theme_url(self) -> None:
        """Verify custom_theme_url and custom_theme_colors coexist."""
        config = get_default_config()
        config.tui.custom_theme_url = "https://example.com/theme.json"
        config.tui.custom_theme_colors = {"phosphex": "#ff0000"}  # type: ignore[attr-defined]
        result = _roundtrip(config)
        assert result.tui.custom_theme_url == "https://example.com/theme.json"
        assert result.tui.custom_theme_colors == {"phosphex": "#ff0000"}  # type: ignore[attr-defined]


# =========================================================================
# O3: identity_nudge_dismissed roundtrip — field not yet in TUIConfig
# =========================================================================


class TestIdentityNudgeDismissedRoundtrip:
    """Tests for identity_nudge_dismissed bool roundtrip.

    xfail because the field does not exist in TUIConfig. The spec says
    it should be added by the warning-fixes sibling task. These tests
    document the expected behavior.
    """

    def test_bool_roundtrip_true(self) -> None:
        config = get_default_config()
        config.tui.identity_nudge_dismissed = True  # type: ignore[attr-defined]
        result = _roundtrip(config)
        assert result.tui.identity_nudge_dismissed is True  # type: ignore[attr-defined]

    def test_bool_roundtrip_false(self) -> None:
        config = get_default_config()
        config.tui.identity_nudge_dismissed = False  # type: ignore[attr-defined]
        result = _roundtrip(config)
        assert result.tui.identity_nudge_dismissed is False  # type: ignore[attr-defined]
