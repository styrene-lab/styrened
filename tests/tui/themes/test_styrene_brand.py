"""Tests for Styrene brand theme."""

from styrened.tui.themes.color_cascade import ColorCascade, generate_all_themes, list_presets
from styrened.tui.themes.styrene_brand import (
    STYRENE_DARK,
    STYRENE_THEME_KEY,
    create_styrene_cascade,
    create_styrene_theme,
)


class TestStyreneCascade:
    """Tests for the brand cascade factory."""

    def test_styrene_cascade_has_explicit_colors(self) -> None:
        """Brand cascade uses exact spec values, not algorithmically derived."""
        cascade = create_styrene_cascade()

        assert cascade.phosphex == "#00f0d3"
        assert cascade.preset_name == "Styrene Dark"
        assert cascade.bright == STYRENE_DARK["primary"]
        assert cascade.medium == STYRENE_DARK["foreground"]
        assert cascade.bg_screen == STYRENE_DARK["background"]
        assert cascade.bg_panel == STYRENE_DARK["card"]
        assert cascade.border_medium == STYRENE_DARK["border"]
        assert cascade.corner_highlight == STYRENE_DARK["ring"]
        assert cascade.color_warning == STYRENE_DARK["destructive"]

    def test_styrene_cascade_from_preset(self) -> None:
        """ColorCascade.from_preset('styrene') returns the brand cascade."""
        cascade = ColorCascade.from_preset("styrene")

        assert cascade.phosphex == "#00f0d3"
        assert cascade.preset_name == "Styrene Dark"
        assert cascade.bg_screen == "#16171d"
        assert cascade.bg_panel == "#202b30"

    def test_cascade_to_dict_includes_all_fields(self) -> None:
        """to_dict() works with the brand cascade and includes all standard keys."""
        cascade = create_styrene_cascade()
        d = cascade.to_dict()

        expected_keys = {
            "phosphex",
            "preset_name",
            "bright",
            "medium",
            "dim",
            "dark",
            "bg_screen",
            "bg_panel",
            "bg_panel_elevated",
            "bg_hover",
            "border_dim",
            "border_medium",
            "border_bright",
            "corner_highlight",
            "status_online",
            "status_offline",
            "status_pending",
            "status_scanning",
            "status_info",
            "color_success",
            "color_warning",
            "color_danger",
            "color_info",
        }
        assert set(d.keys()) == expected_keys


class TestStyreneTheme:
    """Tests for the brand Textual theme."""

    def test_styrene_theme_is_dark(self) -> None:
        """Theme has dark=True and name='styrene'."""
        theme = create_styrene_theme()

        assert theme.name == STYRENE_THEME_KEY
        assert theme.dark is True

    def test_styrene_theme_uses_brand_background(self) -> None:
        """Theme background matches the brand spec."""
        theme = create_styrene_theme()

        assert theme.background is not None
        assert str(theme.background).lower() == "#16171d"


class TestPresetIntegration:
    """Tests for brand theme integration with the preset system."""

    def test_styrene_in_list_presets(self) -> None:
        """Brand theme appears first in preset list."""
        presets = list_presets()

        assert len(presets) > 0
        first_key, first_preset = presets[0]
        assert first_key == STYRENE_THEME_KEY

    def test_styrene_in_generate_all_themes(self) -> None:
        """Brand theme is included in generated themes dict."""
        themes = generate_all_themes()

        assert STYRENE_THEME_KEY in themes
        assert themes[STYRENE_THEME_KEY].name == STYRENE_THEME_KEY

    def test_forge_world_presets_still_work(self) -> None:
        """Existing forge world presets are unaffected."""
        cascade = ColorCascade.from_preset("mars")
        assert cascade.phosphex == "#39ff14"
        assert cascade.preset_name == "Mars Pattern"

        cascade = ColorCascade.from_preset("ryza")
        assert cascade.phosphex == "#ff8c00"


class TestConfigDefault:
    """Tests for theme default configuration."""

    def test_theme_mode_default_is_styrene(self) -> None:
        """TUIConfig() defaults to the styrene theme."""
        from styrened.tui.models.config import ThemeMode, TUIConfig

        config = TUIConfig()
        assert config.theme == ThemeMode.STYRENE
        assert config.theme.value == STYRENE_THEME_KEY
