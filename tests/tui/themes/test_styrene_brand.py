"""Tests for Styrene brand theme."""

from styrened.tui.themes.styrene_brand import (
    STYRENE_DARK,
    STYRENE_THEME_KEY,
    create_styrene_cascade,
    create_styrene_theme,
)


class TestStyreneCascade:
    """Tests for the brand cascade factory."""

    def test_cascade_has_explicit_brand_colors(self) -> None:
        """Brand cascade uses exact spec values, not algorithmically derived."""
        cascade = create_styrene_cascade()

        assert cascade.phosphex == "#00f0d3"
        assert cascade.preset_name == "Styrene Dark"
        assert cascade.bright == STYRENE_DARK["primary"]
        assert cascade.medium == STYRENE_DARK["foreground"]
        assert cascade.dim == STYRENE_DARK["border"]
        assert cascade.dark == STYRENE_DARK["secondary"]
        assert cascade.bg_screen == STYRENE_DARK["background"]
        assert cascade.bg_panel == STYRENE_DARK["card"]
        assert cascade.border_medium == STYRENE_DARK["border"]
        assert cascade.corner_highlight == STYRENE_DARK["ring"]
        assert cascade.color_warning == STYRENE_DARK["destructive"]

    def test_cascade_from_preset(self) -> None:
        """ColorCascade.from_preset('styrene') returns the brand cascade."""
        from styrened.tui.themes.color_cascade import ColorCascade

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

    def test_theme_is_dark_with_correct_name(self) -> None:
        """Theme has dark=True and name='styrene'."""
        theme = create_styrene_theme()

        assert theme.name == STYRENE_THEME_KEY
        assert theme.dark is True

    def test_theme_uses_brand_colors(self) -> None:
        """Theme maps brand tokens directly, not through cascade mapper."""
        theme = create_styrene_theme()

        assert str(theme.primary).lower() == STYRENE_DARK["primary"]
        assert str(theme.background).lower() == STYRENE_DARK["background"]
        assert str(theme.foreground).lower() == STYRENE_DARK["foreground"]
        assert str(theme.surface).lower() == STYRENE_DARK["card"]
        assert str(theme.warning).lower() == STYRENE_DARK["destructive"]


class TestConfigDefault:
    """Tests for theme default configuration."""

    def test_theme_mode_default_is_styrene(self) -> None:
        """TUIConfig() defaults to the styrene theme."""
        from styrened.tui.models.config import ThemeMode, TUIConfig

        config = TUIConfig()
        assert config.theme == ThemeMode.STYRENE
        assert config.theme.value == STYRENE_THEME_KEY

    def test_theme_mode_only_has_styrene(self) -> None:
        """ThemeMode enum has only the styrene entry."""
        from styrened.tui.models.config import ThemeMode

        assert list(ThemeMode) == [ThemeMode.STYRENE]
