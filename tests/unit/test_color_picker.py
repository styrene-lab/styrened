"""Unit tests for the ColorPickerDialog widget."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason="Requires tui-home-cop features not yet on main")


import colorsys

import pytest

from styrened.tui.widgets.color_picker import (
    PRESET_COLORS,
    ColorPickerDialog,
    HueBar,
    SatLightGrid,
)


class TestHueBar:
    """HueBar reactive and action tests."""

    def test_initial_hue_is_zero(self):
        bar = HueBar()
        assert bar.hue == 0.0

    def test_hue_clamps_left(self):
        bar = HueBar()
        bar.hue = 2.0
        bar.action_hue_left()
        assert bar.hue == 0.0  # clamped, not negative

    def test_hue_clamps_right(self):
        bar = HueBar()
        bar.hue = 358.0
        bar.action_hue_right()
        assert bar.hue == 360.0


class TestSatLightGrid:
    """SatLightGrid reactive and action tests."""

    def test_initial_values(self):
        grid = SatLightGrid()
        assert grid.saturation == 1.0
        assert grid.lightness == 0.5

    def test_saturation_clamps_low(self):
        grid = SatLightGrid()
        grid.saturation = 0.02
        grid.action_sat_left()
        assert grid.saturation == 0.0

    def test_lightness_clamps_high(self):
        grid = SatLightGrid()
        grid.lightness = 0.98
        grid.action_light_up()
        assert grid.lightness == 1.0

    def test_saturation_increments(self):
        grid = SatLightGrid()
        grid.saturation = 0.5
        grid.action_sat_right()
        assert abs(grid.saturation - 0.55) < 0.001


class TestColorPickerDialog:
    """ColorPickerDialog initialization tests."""

    def test_init_stores_token_and_color(self):
        dialog = ColorPickerDialog(token_name="primary", initial_color="#4a9a8a")
        assert dialog._token_name == "primary"
        assert dialog._initial_color == "#4a9a8a"

    def test_init_defaults_to_black(self):
        dialog = ColorPickerDialog(token_name="bg")
        assert dialog._initial_color == "#000000"

    def test_hex_from_hsl_round_trip(self):
        """HSL → hex → HSL should be roughly stable."""
        from textual.color import Color

        original = "#4a9a8a"
        c = Color.parse(original)
        hsl = c.hsl
        r, g, b = colorsys.hls_to_rgb(hsl.h, hsl.l, hsl.s)
        reconstructed = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        # Allow 1-unit rounding per channel
        for i in range(1, 7, 2):
            orig_val = int(original[i:i+2], 16)
            recon_val = int(reconstructed[i:i+2], 16)
            assert abs(orig_val - recon_val) <= 1, f"Channel mismatch: {original} vs {reconstructed}"


class TestPresetColors:
    """Validate preset palette."""

    def test_all_presets_are_valid_hex(self):
        for color in PRESET_COLORS:
            assert color.startswith("#")
            assert len(color) == 7
            int(color[1:], 16)  # should not raise

    def test_preset_count(self):
        assert len(PRESET_COLORS) >= 12
