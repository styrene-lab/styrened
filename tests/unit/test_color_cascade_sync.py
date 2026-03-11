"""Tests for ColorCascade construction, preset dispatch, and theme sync logic.

O1: ColorCascade derivation from phosphex color
O2: from_preset() dispatch logic (styrene brand, forge world, unknown)
"""

import pytest

from styrened.tui.themes.color_cascade import (
    FORGE_WORLD_PRESETS,
    ColorCascade,
    scale_color,
)
from styrened.tui.themes.styrene_brand import (
    STYRENE_THEME_KEY,
    create_styrene_cascade,
)


# =========================================================================
# O1: ColorCascade derivation tests
# =========================================================================


class TestColorCascadeDerivation:
    """Verify all palette colors derive algorithmically from phosphex."""

    def test_default_phosphex_is_mars_green(self) -> None:
        """Default cascade uses #39ff14 (Mars Pattern)."""
        c = ColorCascade()
        assert c.phosphex == "#39ff14"
        assert c.preset_name == "Mars Pattern"

    def test_bright_equals_phosphex(self) -> None:
        """Bright shade is the raw phosphex color."""
        c = ColorCascade(phosphex="#ff0000")
        assert c.bright == "#ff0000"

    def test_medium_is_scaled_phosphex(self) -> None:
        """Medium shade is 60% of phosphex brightness."""
        c = ColorCascade(phosphex="#ff0000")
        assert c.medium == scale_color("#ff0000", 0.6)

    def test_dim_is_scaled_phosphex(self) -> None:
        """Dim shade is 35% of phosphex brightness."""
        c = ColorCascade(phosphex="#ff0000")
        assert c.dim == scale_color("#ff0000", 0.35)

    def test_bright_medium_dim_derive_from_phosphex_not_hardcoded(self) -> None:
        """Shades change when phosphex changes — not hardcoded values."""
        c1 = ColorCascade(phosphex="#ff0000")
        c2 = ColorCascade(phosphex="#0000ff")
        assert c1.bright != c2.bright
        assert c1.medium != c2.medium
        assert c1.dim != c2.dim

    def test_preset_name_propagates(self) -> None:
        """Preset name is stored on the cascade."""
        c = ColorCascade(phosphex="#aabbcc", preset_name="Custom Test")
        assert c.preset_name == "Custom Test"

    def test_semantic_colors_default_to_phosphex_shades(self) -> None:
        """Without overrides, semantic colors equal phosphex shade levels."""
        c = ColorCascade(phosphex="#00ff00")
        assert c.color_success == c.bright
        assert c.color_warning == c.medium
        assert c.color_danger == c.dim
        assert c.color_info == c.medium

    def test_status_colors_derive_from_phosphex(self) -> None:
        """Status colors use phosphex brightness levels."""
        c = ColorCascade(phosphex="#ff8800")
        assert c.status_online == c.bright
        assert c.status_offline == c.dark
        assert c.status_pending == c.medium

    def test_backgrounds_are_near_black_tinted(self) -> None:
        """Background colors should be very dark (low brightness)."""
        c = ColorCascade(phosphex="#39ff14")
        for bg_attr in ("bg_screen", "bg_panel", "bg_panel_elevated", "bg_hover"):
            bg = getattr(c, bg_attr)
            # Parse RGB and verify all channels are low
            r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
            assert max(r, g, b) < 50, f"{bg_attr}={bg} is too bright"

    def test_to_dict_contains_all_palette_keys(self) -> None:
        """to_dict() exports the full palette."""
        c = ColorCascade()
        d = c.to_dict()
        assert "phosphex" in d
        assert "bright" in d
        assert "medium" in d
        assert "dim" in d
        assert "color_success" in d
        assert "color_danger" in d
        assert "bg_screen" in d

    def test_to_textual_theme_uses_cascade_colors(self) -> None:
        """to_textual_theme() wires cascade colors into Theme fields."""
        c = ColorCascade(phosphex="#ff0000", preset_name="Red Test")
        theme = c.to_textual_theme(name="test-red")
        assert theme.name == "test-red"
        assert theme.accent == c.bright
        assert theme.primary == c.medium
        assert theme.success == c.color_success


# =========================================================================
# O2: from_preset() dispatch logic
# =========================================================================


class TestFromPresetDispatch:
    """Test ColorCascade.from_preset() routing to correct cascade factory."""

    def test_styrene_key_returns_brand_cascade(self) -> None:
        """STYRENE_THEME_KEY ('styrene') produces hand-tuned brand cascade."""
        cascade = ColorCascade.from_preset(STYRENE_THEME_KEY)
        brand = create_styrene_cascade()
        # Should match the hand-tuned brand values, not algorithmic
        assert cascade.phosphex == brand.phosphex
        assert cascade.preset_name == brand.preset_name
        assert cascade.bright == brand.bright

    def test_forge_world_keys_produce_preset_cascade(self) -> None:
        """Each forge world key returns a cascade with matching phosphex."""
        for key, preset in FORGE_WORLD_PRESETS.items():
            cascade = ColorCascade.from_preset(key)
            assert cascade.phosphex == preset.phosphex, f"Mismatch for {key}"
            assert cascade.preset_name == preset.name

    def test_unknown_preset_raises_value_error(self) -> None:
        """Unknown preset key raises ValueError."""
        with pytest.raises(ValueError, match="Unknown forge world preset"):
            ColorCascade.from_preset("nonexistent_forge_world")

    def test_mars_preset_matches_default(self) -> None:
        """Mars preset produces same colors as default constructor."""
        mars = ColorCascade.from_preset("mars")
        default = ColorCascade()
        assert mars.phosphex == default.phosphex
        assert mars.bright == default.bright
        assert mars.medium == default.medium

    def test_styrene_cascade_differs_from_algorithmic(self) -> None:
        """Styrene brand cascade is hand-tuned, not algorithmically derived."""
        brand = ColorCascade.from_preset("styrene")
        # Brand cascade has different bright/medium than what algorithm would produce
        algo = ColorCascade(phosphex=brand.phosphex)
        # At least medium should differ since brand maps medium→foreground
        assert brand.medium != algo.medium

    def test_preset_exception_propagates(self) -> None:
        """Exceptions from from_preset are not silently swallowed."""
        with pytest.raises(ValueError):
            ColorCascade.from_preset("")

    def test_all_forge_world_order_keys_are_valid(self) -> None:
        """Every key in FORGE_WORLD_ORDER resolves via from_preset."""
        from styrened.tui.themes.color_cascade import FORGE_WORLD_ORDER

        for key in FORGE_WORLD_ORDER:
            cascade = ColorCascade.from_preset(key)
            assert cascade.phosphex  # Non-empty


# =========================================================================
# O2 (extended): Textual builtin theme → cascade bridge
# =========================================================================


class TestGenerateAllThemes:
    """Test generate_all_themes() which builds themes for all presets."""

    def test_includes_styrene_theme(self) -> None:
        from styrened.tui.themes.color_cascade import generate_all_themes

        themes = generate_all_themes()
        assert STYRENE_THEME_KEY in themes

    def test_includes_all_forge_world_presets(self) -> None:
        from styrened.tui.themes.color_cascade import generate_all_themes

        themes = generate_all_themes()
        for key in FORGE_WORLD_PRESETS:
            assert key in themes, f"Missing theme for {key}"

    def test_generated_themes_are_textual_themes(self) -> None:
        from textual.theme import Theme

        from styrened.tui.themes.color_cascade import generate_all_themes

        themes = generate_all_themes()
        for key, theme in themes.items():
            assert isinstance(theme, Theme), f"{key} is not a Theme"


# =========================================================================
# O1 (extended): Cascade → Theme → Cascade roundtrip verification
# =========================================================================


class TestCascadeThemeRoundtrip:
    """Verify cascade colors survive the to_textual_theme() mapping.

    Note: from_textual_theme() does not exist in the codebase — the spec
    referenced a non-existent API. These tests verify the cascade→theme
    direction preserves all semantic relationships, which is the testable
    half of the bidirectional mapping.
    """

    def test_theme_accent_equals_cascade_bright(self) -> None:
        """Theme accent should be the cascade's bright (phosphex) color."""
        c = ColorCascade(phosphex="#ff0000", preset_name="Red")
        theme = c.to_textual_theme(name="red")
        assert theme.accent == c.bright

    def test_theme_primary_equals_cascade_medium(self) -> None:
        """Theme primary should be the cascade's medium shade."""
        c = ColorCascade(phosphex="#00ff00", preset_name="Green")
        theme = c.to_textual_theme(name="green")
        assert theme.primary == c.medium

    def test_theme_success_warning_error_map_semantic_colors(self) -> None:
        """Theme success/warning/error map to cascade semantic colors."""
        c = ColorCascade(phosphex="#0088ff", preset_name="Blue")
        theme = c.to_textual_theme(name="blue")
        assert theme.success == c.color_success
        assert theme.warning == c.color_warning
        assert theme.error == c.color_danger

    def test_theme_background_equals_cascade_bg_screen(self) -> None:
        """Theme background is cascade's bg_screen."""
        c = ColorCascade(phosphex="#ff8800")
        theme = c.to_textual_theme(name="orange")
        assert theme.background == c.bg_screen

    def test_different_phosphex_produces_different_theme_accent(self) -> None:
        """Themes from different phosphex values have different accents."""
        t1 = ColorCascade(phosphex="#ff0000").to_textual_theme(name="r")
        t2 = ColorCascade(phosphex="#0000ff").to_textual_theme(name="b")
        assert t1.accent != t2.accent

    def test_all_forge_presets_produce_valid_themes(self) -> None:
        """Every forge world preset produces a theme with non-empty accent."""
        for key in FORGE_WORLD_PRESETS:
            cascade = ColorCascade.from_preset(key)
            theme = cascade.to_textual_theme(name=key)
            assert theme.accent, f"Empty accent for {key}"
            assert theme.primary, f"Empty primary for {key}"


# =========================================================================
# W1: Defensive exception handling in theme/cascade construction
# =========================================================================


class TestCascadeDefensiveErrors:
    """Verify error paths don't crash silently."""

    def test_invalid_phosphex_color_propagates_error(self) -> None:
        """Invalid hex color in phosphex should raise during palette calc."""
        with pytest.raises((ValueError, KeyError)):
            ColorCascade(phosphex="not-a-color")

    def test_empty_preset_key_raises(self) -> None:
        """Empty string preset key raises ValueError."""
        with pytest.raises(ValueError):
            ColorCascade.from_preset("")

    def test_none_phosphex_raises(self) -> None:
        """None as phosphex should raise TypeError."""
        with pytest.raises((TypeError, AttributeError)):
            ColorCascade(phosphex=None)  # type: ignore[arg-type]
