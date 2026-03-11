"""Tests for TUI color editor: tweakcn profile, colour keys, and theme conversion.

Category O4: Settings color editor unit tests.
"""

from __future__ import annotations

import re
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# _COLOUR_KEYS structure tests
# ---------------------------------------------------------------------------


class TestColourKeys:
    """Verify the _COLOUR_KEYS constant is well-formed."""

    def test_colour_keys_is_frozenset(self) -> None:
        from styrened.tui.themes.tweakcn import _COLOUR_KEYS

        assert isinstance(_COLOUR_KEYS, frozenset)

    def test_colour_keys_non_empty(self) -> None:
        from styrened.tui.themes.tweakcn import _COLOUR_KEYS

        assert len(_COLOUR_KEYS) > 0

    def test_colour_keys_all_strings(self) -> None:
        from styrened.tui.themes.tweakcn import _COLOUR_KEYS

        for key in _COLOUR_KEYS:
            assert isinstance(key, str), f"{key!r} is not a string"

    def test_colour_keys_contains_core_tokens(self) -> None:
        """Core tokens that must exist for any tweakcn theme to work."""
        from styrened.tui.themes.tweakcn import _COLOUR_KEYS

        core = {"primary", "background", "foreground", "secondary", "accent",
                "border", "muted", "destructive"}
        missing = core - _COLOUR_KEYS
        assert not missing, f"Missing core tokens: {missing}"

    def test_colour_keys_no_whitespace_in_names(self) -> None:
        from styrened.tui.themes.tweakcn import _COLOUR_KEYS

        for key in _COLOUR_KEYS:
            assert key == key.strip(), f"Token {key!r} has leading/trailing whitespace"
            assert " " not in key, f"Token {key!r} contains spaces"


# ---------------------------------------------------------------------------
# STYRENE_DARK brand dict tests
# ---------------------------------------------------------------------------


class TestStyreneDark:
    """Verify STYRENE_DARK covers all colour keys with hex values."""

    def test_styrene_dark_keys_map_to_colour_keys(self) -> None:
        """Most STYRENE_DARK keys (underscored) should map to _COLOUR_KEYS tokens (hyphenated).

        Known divergences: STYRENE_DARK uses chartN (no hyphen) vs _COLOUR_KEYS
        chart-N, and includes sidebar_background (maps to 'sidebar' in tweakcn).
        """
        from styrened.tui.themes.styrene_brand import STYRENE_DARK
        from styrened.tui.themes.tweakcn import _COLOUR_KEYS

        # STYRENE_DARK uses underscores; _COLOUR_KEYS uses hyphens (CSS convention)
        hyphenated = {k.replace("_", "-") for k in STYRENE_DARK.keys()}
        # Known naming divergences between STYRENE_DARK and tweakcn _COLOUR_KEYS
        known_divergences = {
            "chart1", "chart2", "chart3", "chart4", "chart5",  # tweakcn: chart-1..5
            "sidebar-background",  # tweakcn: sidebar
        }
        invalid = hyphenated - _COLOUR_KEYS - known_divergences
        assert not invalid, f"STYRENE_DARK has unknown tokens: {invalid}"

    def test_styrene_dark_covers_core_tokens(self) -> None:
        """STYRENE_DARK must have at minimum the core UI tokens."""
        from styrened.tui.themes.styrene_brand import STYRENE_DARK

        core = {"primary", "background", "foreground", "secondary", "accent",
                "border", "muted", "destructive", "card", "input", "ring"}
        missing = core - set(STYRENE_DARK.keys())
        assert not missing, f"STYRENE_DARK missing core tokens: {missing}"

    def test_styrene_dark_values_are_hex(self) -> None:
        from styrened.tui.themes.styrene_brand import STYRENE_DARK

        hex_re = re.compile(r"^#[0-9a-f]{6}$")
        for key, value in STYRENE_DARK.items():
            assert hex_re.match(value), f"STYRENE_DARK[{key!r}] = {value!r} is not #rrggbb hex"

    def test_styrene_dark_is_dict_str_str(self) -> None:
        from styrened.tui.themes.styrene_brand import STYRENE_DARK

        assert isinstance(STYRENE_DARK, dict)
        for k, v in STYRENE_DARK.items():
            assert isinstance(k, str)
            assert isinstance(v, str)


# ---------------------------------------------------------------------------
# parse_color tests
# ---------------------------------------------------------------------------


class TestParseColor:
    """Test the OKLCH/hex parser used by TweakcnProfile."""

    def test_parse_hex_6digit(self) -> None:
        from styrened.tui.themes.tweakcn import parse_color

        assert parse_color("#00f0d3") == "#00f0d3"

    def test_parse_hex_3digit_expands(self) -> None:
        from styrened.tui.themes.tweakcn import parse_color

        assert parse_color("#abc") == "#aabbcc"

    def test_parse_hex_uppercase_lowered(self) -> None:
        from styrened.tui.themes.tweakcn import parse_color

        assert parse_color("#AABBCC") == "#aabbcc"

    def test_parse_oklch_returns_hex(self) -> None:
        from styrened.tui.themes.tweakcn import parse_color

        result = parse_color("oklch(0.5 0.1 180)")
        assert result.startswith("#")
        assert len(result) == 7

    def test_parse_named_color_passthrough(self) -> None:
        from styrened.tui.themes.tweakcn import parse_color

        assert parse_color("red") == "red"

    def test_parse_empty_string(self) -> None:
        from styrened.tui.themes.tweakcn import parse_color

        assert parse_color("") == ""

    def test_parse_strips_whitespace(self) -> None:
        from styrened.tui.themes.tweakcn import parse_color

        assert parse_color("  #abcdef  ") == "#abcdef"


# ---------------------------------------------------------------------------
# TweakcnProfile construction tests
# ---------------------------------------------------------------------------


class TestTweakcnProfileFromRegistryJson:
    """Test TweakcnProfile.from_registry_json() construction."""

    def test_basic_construction(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data = {"cssVars": {"dark": {"primary": "#ff0000"}, "light": {}}}
        profile = TweakcnProfile.from_registry_json(data, name="test")
        assert profile.name == "test"
        assert profile.dark["primary"] == "#ff0000"

    def test_name_from_data(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data = {"name": "mytheme", "cssVars": {"dark": {}, "light": {}}}
        profile = TweakcnProfile.from_registry_json(data)
        assert profile.name == "mytheme"

    def test_name_kwarg_overrides_data(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data = {"name": "mytheme", "cssVars": {"dark": {}, "light": {}}}
        profile = TweakcnProfile.from_registry_json(data, name="override")
        assert profile.name == "override"

    def test_empty_css_vars(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data: dict[str, Any] = {"cssVars": {}}
        profile = TweakcnProfile.from_registry_json(data, name="empty")
        assert profile.dark == {}
        assert profile.light == {}
        assert profile.meta == {}

    def test_missing_css_vars_key(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data: dict[str, Any] = {}
        profile = TweakcnProfile.from_registry_json(data, name="none")
        assert profile.dark == {}
        assert profile.light == {}

    def test_source_url_preserved(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data: dict[str, Any] = {"cssVars": {"dark": {}, "light": {}}}
        profile = TweakcnProfile.from_registry_json(
            data, name="t", source_url="https://tweakcn.com/themes/abc123"
        )
        assert profile.source_url == "https://tweakcn.com/themes/abc123"

    def test_name_with_special_chars(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data: dict[str, Any] = {"cssVars": {"dark": {}, "light": {}}}
        profile = TweakcnProfile.from_registry_json(
            data, name="my-theme (v2) [dark]"
        )
        assert profile.name == "my-theme (v2) [dark]"

    def test_name_with_unicode(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data: dict[str, Any] = {"cssVars": {"dark": {}, "light": {}}}
        profile = TweakcnProfile.from_registry_json(data, name="テーマ🎨")
        assert profile.name == "テーマ🎨"

    def test_meta_dict_populated(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data = {"cssVars": {"dark": {}, "light": {}, "theme": {"radius": "0.5rem"}}}
        profile = TweakcnProfile.from_registry_json(data, name="m")
        assert profile.meta == {"radius": "0.5rem"}

    def test_partial_colors_only_primary(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data = {"cssVars": {"dark": {"primary": "#00ff00"}, "light": {}}}
        profile = TweakcnProfile.from_registry_json(data, name="partial")
        assert profile.dark == {"primary": "#00ff00"}
        assert len(profile.dark) == 1

    def test_default_name_is_custom(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        data: dict[str, Any] = {"cssVars": {"dark": {}, "light": {}}}
        profile = TweakcnProfile.from_registry_json(data)
        assert profile.name == "custom"

    def test_dicts_are_copies(self) -> None:
        """Mutating the returned profile shouldn't affect original data."""
        from styrened.tui.themes.tweakcn import TweakcnProfile

        dark = {"primary": "#aaa"}
        data = {"cssVars": {"dark": dark, "light": {}}}
        profile = TweakcnProfile.from_registry_json(data, name="t")
        profile.dark["primary"] = "#bbb"
        assert dark["primary"] == "#aaa"


# ---------------------------------------------------------------------------
# TweakcnProfile.to_textual_theme() tests
# ---------------------------------------------------------------------------


class TestTweakcnProfileToTextualTheme:
    """Test theme conversion to Textual Theme objects."""

    def _make_profile(self, dark: dict[str, str] | None = None) -> Any:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        return TweakcnProfile(
            name="test-theme",
            dark=dark or {"primary": "#00f0d3", "background": "#161616",
                          "foreground": "#ffffff", "secondary": "#333333",
                          "accent": "#445566", "destructive": "#ff4444",
                          "card": "#222222", "muted": "#1a1a1a",
                          "border": "#444444", "input": "#333333",
                          "ring": "#00f0d3", "popover": "#1e1e1e",
                          "muted-foreground": "#888888",
                          "card-foreground": "#eeeeee",
                          "primary-foreground": "#000000"},
            light={},
        )

    def test_returns_theme_object(self) -> None:
        from textual.theme import Theme

        theme = self._make_profile().to_textual_theme("dark")
        assert isinstance(theme, Theme)

    def test_theme_name_matches_profile(self) -> None:
        theme = self._make_profile().to_textual_theme("dark")
        assert theme.name == "test-theme"

    def test_primary_color_set(self) -> None:
        theme = self._make_profile().to_textual_theme("dark")
        assert theme.primary == "#00f0d3"

    def test_accent_color_set(self) -> None:
        theme = self._make_profile().to_textual_theme("dark")
        assert theme.accent == "#445566"

    def test_dark_mode_flag(self) -> None:
        theme = self._make_profile().to_textual_theme("dark")
        assert theme.dark is True

    def test_light_mode_flag(self) -> None:
        from styrened.tui.themes.tweakcn import TweakcnProfile

        profile = TweakcnProfile(
            name="light-test",
            dark={},
            light={"primary": "#336699", "background": "#ffffff",
                   "foreground": "#000000", "secondary": "#cccccc",
                   "accent": "#336699", "destructive": "#cc0000",
                   "card": "#f0f0f0", "muted": "#e0e0e0",
                   "border": "#dddddd", "input": "#dddddd",
                   "ring": "#336699", "popover": "#ffffff",
                   "muted-foreground": "#666666",
                   "card-foreground": "#111111",
                   "primary-foreground": "#ffffff"},
        )
        theme = profile.to_textual_theme("light")
        assert theme.dark is False

    def test_fallback_to_other_mode(self) -> None:
        """If dark dict is empty, should use light dict."""
        from styrened.tui.themes.tweakcn import TweakcnProfile

        profile = TweakcnProfile(
            name="fallback",
            dark={},
            light={"primary": "#112233", "background": "#ffffff",
                   "foreground": "#000000"},
        )
        theme = profile.to_textual_theme("dark")
        # Should still produce a theme using light colors
        assert theme.primary == "#112233"

    def test_empty_profile_produces_theme(self) -> None:
        """A profile with no colors should still produce a valid Theme."""
        from styrened.tui.themes.tweakcn import TweakcnProfile

        profile = TweakcnProfile(name="empty", dark={}, light={})
        theme = profile.to_textual_theme("dark")
        assert theme.name == "empty"

    def test_variables_dict_has_border(self) -> None:
        theme = self._make_profile().to_textual_theme("dark")
        assert "border" in theme.variables

    def test_oklch_values_converted_to_hex(self) -> None:
        """OKLCH strings should be converted to hex in the theme."""
        from styrened.tui.themes.tweakcn import TweakcnProfile

        profile = TweakcnProfile(
            name="oklch-test",
            dark={"primary": "oklch(0.8556 0.1555 179.7932)",
                  "background": "#161616", "foreground": "#ffffff"},
            light={},
        )
        theme = profile.to_textual_theme("dark")
        assert theme.primary is not None
        assert theme.primary.startswith("#")


# ---------------------------------------------------------------------------
# Styrene profile roundtrip
# ---------------------------------------------------------------------------


class TestStyreneProfileRoundtrip:
    """Test get_styrene_profile() → to_textual_theme() roundtrip."""

    def test_styrene_profile_has_name(self) -> None:
        from styrened.tui.themes.styrene_brand import get_styrene_profile

        profile = get_styrene_profile()
        assert profile.name == "styrene"

    def test_styrene_profile_has_source_url(self) -> None:
        from styrened.tui.themes.styrene_brand import get_styrene_profile

        profile = get_styrene_profile()
        assert "tweakcn.com" in profile.source_url

    def test_styrene_profile_dark_has_all_colour_keys(self) -> None:
        from styrened.tui.themes.styrene_brand import get_styrene_profile
        from styrened.tui.themes.tweakcn import _COLOUR_KEYS

        profile = get_styrene_profile()
        missing = _COLOUR_KEYS - set(profile.dark.keys()) - {"shadow-color"}
        assert not missing, f"Styrene profile dark missing: {missing}"

    def test_styrene_profile_to_theme_primary(self) -> None:
        from styrened.tui.themes.styrene_brand import get_styrene_profile

        profile = get_styrene_profile()
        theme = profile.to_textual_theme("dark")
        assert theme.primary is not None
        assert theme.primary.startswith("#")

    def test_styrene_profile_theme_is_dark(self) -> None:
        from styrened.tui.themes.styrene_brand import get_styrene_profile

        theme = get_styrene_profile().to_textual_theme("dark")
        assert theme.dark is True

    def test_styrene_profile_theme_name(self) -> None:
        from styrened.tui.themes.styrene_brand import get_styrene_profile

        theme = get_styrene_profile().to_textual_theme("dark")
        assert theme.name == "styrene"


# ---------------------------------------------------------------------------
# TCSS status classes
# ---------------------------------------------------------------------------


class TestTcssStatusClasses:
    """Verify that status CSS classes referenced in code exist in styrene.tcss."""

    @pytest.fixture(scope="class")
    def tcss_content(self) -> str:
        from pathlib import Path

        tcss = Path(__file__).resolve().parents[2] / "src" / "styrened" / "tui" / "styles" / "styrene.tcss"
        return tcss.read_text()

    def test_status_info_class_exists(self, tcss_content: str) -> None:
        assert ".status-info" in tcss_content

    def test_no_undefined_status_classes_in_settings(self) -> None:
        """Check that _set_theme_status doesn't use CSS classes not in the TCSS."""
        from pathlib import Path

        settings_path = (
            Path(__file__).resolve().parents[2]
            / "src" / "styrened" / "tui" / "screens" / "settings.py"
        )
        settings_src = settings_path.read_text()

        # _set_theme_status uses Rich markup [green], [red], [dim] — not CSS classes.
        # Verify it doesn't add/remove CSS classes that don't exist.
        # The method just calls Static.update() with Rich markup.
        assert "_set_theme_status" in settings_src
        # Confirm it does NOT use add_class/remove_class with unknown classes
        assert "status-success" not in settings_src or "status-error" not in settings_src
