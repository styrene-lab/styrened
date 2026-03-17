"""Tests for StyrenePanel (aliased as HighlightedPanel).

StyrenePanel uses Textual's native border system (border: round) rather than
custom box-drawing characters.  Title is set via border_title.
"""
from __future__ import annotations

from textual.widgets import Label, Static

from styrened.tui.themes.color_cascade import ColorCascade
from styrened.tui.widgets.highlighted_panel import (
    HighlightedPanel,
    StyrenePanel,
    get_color_cascade,
    set_color_cascade,
)


class TestStyrenePanel:
    """Core StyrenePanel behavior."""

    def test_alias_is_same_class(self):
        assert HighlightedPanel is StyrenePanel

    def test_instantiation_no_args(self):
        panel = StyrenePanel()
        assert panel.border_title is None or panel.border_title == ""

    def test_instantiation_with_title(self):
        panel = StyrenePanel(title="STATUS")
        assert panel.border_title == "STATUS"

    def test_instantiation_with_children(self):
        child1 = Label("Hello")
        child2 = Static("World")
        panel = StyrenePanel(child1, child2, title="TEST")
        assert panel.border_title == "TEST"

    def test_instantiation_with_id(self):
        panel = StyrenePanel(id="my-panel")
        assert panel.id == "my-panel"

    def test_instantiation_with_classes(self):
        panel = StyrenePanel(classes="primary constrained")
        assert "primary" in panel.classes
        assert "constrained" in panel.classes

    def test_refresh_theme_is_noop(self):
        """refresh_theme() kept for compat but does nothing."""
        panel = StyrenePanel(title="T")
        panel.refresh_theme()  # should not raise


class TestColorCascade:
    """Module-level color cascade accessors."""

    def test_get_default_cascade(self):
        cascade = get_color_cascade()
        assert isinstance(cascade, ColorCascade)
        assert cascade.bright is not None
        assert cascade.dim is not None

    def test_set_and_get_cascade(self):
        original = get_color_cascade()
        try:
            custom = ColorCascade.from_preset("styrene")
            custom.bright = "#ff0000"
            set_color_cascade(custom)
            assert get_color_cascade().bright == "#ff0000"
        finally:
            set_color_cascade(original)

    def test_cascade_has_bg_fields(self):
        cascade = get_color_cascade()
        assert hasattr(cascade, "bg_screen")
        assert hasattr(cascade, "bg_panel")


class TestStyrenePanel_CSS:
    """Verify DEFAULT_CSS provides expected defaults."""

    def test_default_css_has_round_border(self):
        css = StyrenePanel.DEFAULT_CSS
        assert "border: round" in css

    def test_default_css_has_auto_height(self):
        css = StyrenePanel.DEFAULT_CSS
        assert "height: auto" in css

    def test_default_css_has_transparent_bg(self):
        css = StyrenePanel.DEFAULT_CSS
        assert "background: transparent" in css

    def test_default_css_has_margin(self):
        css = StyrenePanel.DEFAULT_CSS
        assert "margin-bottom: 1" in css
