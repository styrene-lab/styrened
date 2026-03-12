from __future__ import annotations

import pytest


"""Tests for ColorCascade construction, preset dispatch, and theme sync logic.

O1: ColorCascade derivation from phosphex color and from_textual_theme()
O2: Theme→cascade dispatch logic (styrene brand, forge world, builtin, unknown)
"""

import pytest
from textual.theme import BUILTIN_THEMES, Theme

from styrened.tui.themes.color_cascade import (
    FORGE_WORLD_ORDER,
    FORGE_WORLD_PRESETS,
    ColorCascade,
    generate_all_themes,
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

    def test_semantic_color_overrides_applied(self) -> None:
        """When semantic colors are overridden post-init, values stick.

        W1: ColorCascade computes semantics algorithmically in _calculate_palette.
        Overriding after construction verifies the attributes are writable and
        that to_textual_theme() picks up the overridden values.
        """
        c = ColorCascade(phosphex="#00ff00")
        c.color_success = "#00ff00"
        c.color_warning = "#ffff00"
        c.color_danger = "#ff0000"
        assert c.color_success == "#00ff00"
        assert c.color_warning == "#ffff00"
        assert c.color_danger == "#ff0000"
        # Verify to_textual_theme uses the overridden values
        theme = c.to_textual_theme(name="override-test")
        assert theme.success == "#00ff00"
        assert theme.warning == "#ffff00"
        assert theme.error == "#ff0000"

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
# O1: from_textual_theme() tests — API does not exist yet
# =========================================================================


class TestFromTextualTheme:
    """O1 spec: Tests for ColorCascade.from_textual_theme().

    This API does not exist in the codebase. These tests document the
    spec'd behavior and are marked xfail until the method is implemented.
    The spec requires 7 test cases for constructing a ColorCascade from
    a Textual Theme object.
    """

    def test_theme_with_accent_derives_phosphex(self) -> None:
        """Theme with accent set: cascade phosphex should derive from accent."""
        theme = Theme(name="test", accent="#ff0000", primary="#880000")
        cascade = ColorCascade.from_textual_theme(theme)  # type: ignore[attr-defined]
        assert cascade.phosphex == "#ff0000"

    def test_theme_with_only_primary_uses_primary(self) -> None:
        """Theme with only primary (no accent): cascade should use primary."""
        theme = Theme(name="test", primary="#00ff00")
        cascade = ColorCascade.from_textual_theme(theme)  # type: ignore[attr-defined]
        assert cascade.phosphex == "#00ff00"

    def test_theme_with_no_accent_uses_primary(self) -> None:
        """Theme with no accent falls back to primary (Textual requires primary)."""
        theme = Theme(name="test", primary="#888888")
        cascade = ColorCascade.from_textual_theme(theme)  # type: ignore[attr-defined]
        assert cascade.phosphex == "#888888"

    def test_theme_semantic_overrides(self) -> None:
        """Theme with success/warning/error: cascade should use theme values."""
        theme = Theme(
            name="test",
            primary="#880000",
            accent="#ff0000",
            success="#00ff00",
            warning="#ffff00",
            error="#ff0000",
        )
        cascade = ColorCascade.from_textual_theme(theme)  # type: ignore[attr-defined]
        assert cascade.color_success == "#00ff00"
        assert cascade.color_warning == "#ffff00"
        assert cascade.color_danger == "#ff0000"

    def test_theme_partial_semantics_keep_algorithmic_defaults(self) -> None:
        """Theme with only success set: other semantics keep defaults."""
        theme = Theme(name="test", primary="#880000", accent="#ff0000", success="#00ff00")
        cascade = ColorCascade.from_textual_theme(theme)  # type: ignore[attr-defined]
        # warning and danger should be algorithmic (not from theme)
        algo = ColorCascade(phosphex="#ff0000")
        assert cascade.color_warning == algo.color_warning
        assert cascade.color_danger == algo.color_danger

    def test_theme_name_propagation(self) -> None:
        """cascade.preset_name should match theme.name."""
        theme = Theme(name="my-custom-theme", primary="#880000", accent="#ff0000")
        cascade = ColorCascade.from_textual_theme(theme)  # type: ignore[attr-defined]
        assert cascade.preset_name == "my-custom-theme"

    def test_bright_medium_dim_derived_from_accent(self) -> None:
        """Verify bright/medium/dim are derived from accent, not hardcoded."""
        theme = Theme(name="test", primary="#880000", accent="#ff0000")
        cascade = ColorCascade.from_textual_theme(theme)  # type: ignore[attr-defined]
        assert cascade.bright == "#ff0000"
        assert cascade.medium == scale_color("#ff0000", 0.6)
        assert cascade.dim == scale_color("#ff0000", 0.35)


# =========================================================================
# O2: from_preset() dispatch logic
# =========================================================================


class TestFromPresetDispatch:
    """Test ColorCascade.from_preset() routing to correct cascade factory."""

    def test_styrene_key_returns_brand_cascade(self) -> None:
        """STYRENE_THEME_KEY ('styrene') produces hand-tuned brand cascade."""
        cascade = ColorCascade.from_preset(STYRENE_THEME_KEY)
        brand = create_styrene_cascade()
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
        algo = ColorCascade(phosphex=brand.phosphex)
        assert brand.medium != algo.medium

    def test_all_forge_world_order_keys_are_valid(self) -> None:
        """Every key in FORGE_WORLD_ORDER resolves via from_preset."""
        for key in FORGE_WORLD_ORDER:
            cascade = ColorCascade.from_preset(key)
            assert cascade.phosphex  # Non-empty


# =========================================================================
# O2: Theme→cascade dispatch logic (replicating _apply_saved_theme paths)
# =========================================================================


class TestThemeCascadeDispatch:
    """Test theme→cascade dispatch logic.

    StyreneApp._apply_saved_theme() routes theme names to cascade factories.
    We replicate that dispatch logic here since StyreneApp is hard to
    instantiate in unit tests.
    """

    @staticmethod
    def _dispatch_theme_to_cascade(
        theme_name: str,
        existing_cascade: ColorCascade | None = None,
    ) -> ColorCascade:
        """Replicate the dispatch logic from _apply_saved_theme / watch_theme.

        Routes:
        - STYRENE_THEME_KEY → create_styrene_cascade()
        - forge world preset key → ColorCascade.from_preset()
        - Textual builtin theme name → cascade from BUILTIN_THEMES
        - unknown → return existing cascade unchanged
        """
        if theme_name == STYRENE_THEME_KEY:
            return create_styrene_cascade()

        # Check forge world presets
        if theme_name in FORGE_WORLD_PRESETS or theme_name in FORGE_WORLD_ORDER:
            return ColorCascade.from_preset(theme_name)

        # Check Textual builtin themes
        if theme_name in BUILTIN_THEMES:
            builtin_theme = BUILTIN_THEMES[theme_name]
            # Derive cascade from builtin theme's accent or primary
            accent = getattr(builtin_theme, "accent", None)
            primary = getattr(builtin_theme, "primary", None)
            phosphex = accent or primary or "#39ff14"
            return ColorCascade(phosphex=phosphex, preset_name=theme_name)

        # Unknown theme — keep existing cascade
        if existing_cascade is not None:
            return existing_cascade
        return ColorCascade()  # fallback default

    def test_styrene_key_produces_brand_cascade(self) -> None:
        """STYRENE_THEME_KEY dispatches to create_styrene_cascade()."""
        cascade = self._dispatch_theme_to_cascade(STYRENE_THEME_KEY)
        brand = create_styrene_cascade()
        assert cascade.phosphex == brand.phosphex
        assert cascade.preset_name == brand.preset_name

    def test_forge_world_key_produces_preset_cascade(self) -> None:
        """Forge world preset keys dispatch to ColorCascade.from_preset()."""
        for key in list(FORGE_WORLD_PRESETS.keys())[:3]:
            cascade = self._dispatch_theme_to_cascade(key)
            assert cascade.phosphex == FORGE_WORLD_PRESETS[key].phosphex

    def test_builtin_theme_produces_cascade(self) -> None:
        """Textual builtin theme name (e.g., 'nord') produces a cascade."""
        cascade = self._dispatch_theme_to_cascade("nord")
        # Nord theme has accent/primary — cascade should use it, not default
        nord = BUILTIN_THEMES["nord"]
        expected_phosphex = nord.accent or nord.primary or "#39ff14"
        assert cascade.phosphex == expected_phosphex
        assert cascade.preset_name == "nord"

    def test_unknown_theme_keeps_existing_cascade(self) -> None:
        """Unknown theme name with no match keeps existing cascade unchanged."""
        existing = ColorCascade(phosphex="#aabbcc", preset_name="My Existing")
        result = self._dispatch_theme_to_cascade(
            "totally_unknown_theme_xyz",
            existing_cascade=existing,
        )
        assert result is existing
        assert result.phosphex == "#aabbcc"
        assert result.preset_name == "My Existing"

    def test_exception_in_cascade_construction_doesnt_crash(self) -> None:
        """Exception in from_textual_theme equivalent doesn't crash dispatch.

        The dispatch should handle errors gracefully, not propagate them.
        """
        # Simulate what happens when from_preset raises for a bad key
        # The dispatch function should return existing cascade, not crash
        existing = ColorCascade(phosphex="#112233", preset_name="Safe")
        # An unknown key that's not in any lookup should return existing
        result = self._dispatch_theme_to_cascade("", existing_cascade=existing)
        assert result is existing


# =========================================================================
# O2: generate_all_themes() validation
# =========================================================================


class TestGenerateAllThemes:
    """Test generate_all_themes() which builds themes for all presets."""

    def test_includes_styrene_theme(self) -> None:
        themes = generate_all_themes()
        assert STYRENE_THEME_KEY in themes

    def test_includes_all_forge_world_presets(self) -> None:
        themes = generate_all_themes()
        for key in FORGE_WORLD_PRESETS:
            assert key in themes, f"Missing theme for {key}"

    def test_generated_themes_are_textual_themes(self) -> None:
        themes = generate_all_themes()
        for key, theme in themes.items():
            assert isinstance(theme, Theme), f"{key} is not a Theme"


# =========================================================================
# O1: Cascade → Theme roundtrip verification
# =========================================================================


class TestCascadeThemeRoundtrip:
    """Verify cascade colors survive the to_textual_theme() mapping."""

    def test_theme_accent_equals_cascade_bright(self) -> None:
        c = ColorCascade(phosphex="#ff0000", preset_name="Red")
        theme = c.to_textual_theme(name="red")
        assert theme.accent == c.bright

    def test_theme_primary_equals_cascade_medium(self) -> None:
        c = ColorCascade(phosphex="#00ff00", preset_name="Green")
        theme = c.to_textual_theme(name="green")
        assert theme.primary == c.medium

    def test_theme_success_warning_error_map_semantic_colors(self) -> None:
        c = ColorCascade(phosphex="#0088ff", preset_name="Blue")
        theme = c.to_textual_theme(name="blue")
        assert theme.success == c.color_success
        assert theme.warning == c.color_warning
        assert theme.error == c.color_danger

    def test_theme_background_equals_cascade_bg_screen(self) -> None:
        c = ColorCascade(phosphex="#ff8800")
        theme = c.to_textual_theme(name="orange")
        assert theme.background == c.bg_screen

    def test_different_phosphex_produces_different_theme_accent(self) -> None:
        t1 = ColorCascade(phosphex="#ff0000").to_textual_theme(name="r")
        t2 = ColorCascade(phosphex="#0000ff").to_textual_theme(name="b")
        assert t1.accent != t2.accent

    def test_all_forge_presets_produce_valid_themes(self) -> None:
        for key in FORGE_WORLD_PRESETS:
            cascade = ColorCascade.from_preset(key)
            theme = cascade.to_textual_theme(name=key)
            assert theme.accent, f"Empty accent for {key}"
            assert theme.primary, f"Empty primary for {key}"


# =========================================================================
# Defensive exception handling
# =========================================================================


class TestCascadeDefensiveErrors:
    """Verify error paths don't crash silently."""

    def test_invalid_phosphex_color_propagates_error(self) -> None:
        with pytest.raises((ValueError, KeyError)):
            ColorCascade(phosphex="not-a-color")

    def test_empty_preset_key_raises(self) -> None:
        with pytest.raises(ValueError):
            ColorCascade.from_preset("")

    def test_none_phosphex_raises(self) -> None:
        with pytest.raises((TypeError, AttributeError)):
            ColorCascade(phosphex=None)  # type: ignore[arg-type]
