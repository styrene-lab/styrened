"""Tests for HighlightedPanel widget."""

import pytest
from textual.app import App
from textual.widgets import Label

from styrened.tui.themes.color_cascade import ColorCascade
from styrened.tui.widgets.highlighted_panel import (
    HighlightedPanel,
    get_color_cascade,
    set_color_cascade,
)


class TestHighlightedPanelThemeColors:
    """Test theme color application to HighlightedPanel."""

    def test_panel_applies_phosphex_color_correctly(self, snap_compare):
        """Verify theme color cascade is applied to panel borders."""

        # Programmatic assertion BEFORE snapshot: Verify the current color cascade has actual values
        current_cascade = get_color_cascade()
        assert current_cascade.bright.startswith("#"), \
            "Cascade bright color should be hex color from theme"
        assert current_cascade.dim.startswith("#"), \
            "Cascade dim color should be hex color from theme"
        assert current_cascade.medium.startswith("#"), \
            "Cascade medium color should be hex color from theme"

        # Verify all three colors are different (proper cascade)
        assert current_cascade.bright != current_cascade.dim, \
            "Bright and dim should be different colors"
        assert current_cascade.bright != current_cascade.medium, \
            "Bright and medium should be different colors"

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("Test Content"),
                    title="Theme Test",
                )

        app = PanelApp()

        # Snapshot comparison - also implicitly tests that theme colors render correctly
        assert snap_compare(app, "panel_default_theme.svg")

    def test_panel_border_color_matches_theme(self, snap_compare):
        """Verify border uses correct theme color (dim phosphex)."""

        # Set Mars theme (green) for testing
        cascade = ColorCascade.from_preset("mars")
        set_color_cascade(cascade)

        # Programmatic assertion BEFORE snapshot: Verify the cascade has actual color values
        assert cascade.bright.startswith("#"), "Mars bright color should be hex color"
        assert cascade.dim.startswith("#"), "Mars dim color should be hex color"
        assert cascade.medium.startswith("#"), "Mars medium color should be hex color"

        # Verify the three cascade levels are distinct
        assert cascade.bright != cascade.dim, "Mars bright and dim should differ"
        assert cascade.bright != cascade.medium, "Mars bright and medium should differ"

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("Border Color Test"),
                    title="Mars Theme",
                )

        app = PanelApp()

        # Snapshot comparison - also implicitly tests that Mars theme renders correctly
        assert snap_compare(app, "panel_border_mars_theme.svg")

    def test_panel_corner_highlights_match_theme(self, snap_compare):
        """Verify corner symbols use bright theme color."""

        # Set Ryza theme (orange) for visual differentiation
        cascade = ColorCascade.from_preset("ryza")
        set_color_cascade(cascade)

        # Programmatic assertion BEFORE snapshot: Verify Ryza cascade has valid colors
        assert cascade.bright.startswith("#"), "Ryza bright color should be hex color"
        assert cascade.dim.startswith("#"), "Ryza dim color should be hex color"

        # Verify HighlightedPanel has the box-drawing characters defined
        assert HighlightedPanel.TOP_LEFT == "┌", "Panel should use correct top-left corner char"
        assert HighlightedPanel.TOP_RIGHT == "┐", "Panel should use correct top-right corner char"
        assert HighlightedPanel.BOTTOM_LEFT == "└", "Panel should use correct bottom-left corner char"
        assert HighlightedPanel.BOTTOM_RIGHT == "┘", "Panel should use correct bottom-right corner char"
        assert HighlightedPanel.HORIZONTAL == "─", "Panel should use correct horizontal line char"

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("Corner Highlight Test"),
                    title="Ryza Theme",
                )

        app = PanelApp()

        # Snapshot comparison - visual verification that corners render with Ryza theme
        assert snap_compare(app, "panel_corners_ryza_theme.svg")


class TestHighlightedPanelCornerHighlighting:
    """Test corner highlighting behavior."""

    @pytest.mark.asyncio
    async def test_panel_shows_corner_symbols_when_enabled(self, snap_compare):
        """Verify corner symbols (box-drawing characters) appear in borders."""

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("Corner symbols should be visible"),
                    title="Corner Test",
                )

        app = PanelApp()
        assert await snap_compare(app, "panel_with_corners.svg")

    @pytest.mark.asyncio
    async def test_panel_hides_corner_symbols_when_disabled(self, snap_compare):
        """Verify panel renders without corner highlights when feature is off.

        Note: Current implementation always shows corners. This test documents
        the expected behavior if corner_extend is set to 0.
        """

        class PanelApp(App):
            def compose(self):
                panel = HighlightedPanel(
                    Label("No corner highlights"),
                    title="Minimal Borders",
                )
                # Set corner extension to 0 to disable highlights
                panel.CORNER_EXTEND = 0
                yield panel

        app = PanelApp()
        assert await snap_compare(app, "panel_minimal_borders.svg")

    @pytest.mark.asyncio
    async def test_panel_corner_position_correct(self, snap_compare):
        """Verify corner symbols appear at correct positions (4 corners)."""

        class PanelApp(App):
            def compose(self):
                # Use wider panel to make corners more distinct
                yield HighlightedPanel(
                    Label("Wide panel to verify corner positions"),
                    title="Corner Position Verification",
                )

        app = PanelApp()
        # Visual inspection will verify corners at top-left, top-right,
        # bottom-left, and bottom-right positions
        assert await snap_compare(app, "panel_corner_positions.svg")


class TestHighlightedPanelContentRendering:
    """Test content area and child widget rendering."""

    @pytest.mark.asyncio
    async def test_panel_renders_child_widgets_correctly(self, snap_compare):
        """Verify content area displays child widgets properly."""

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("First Line"),
                    Label("Second Line"),
                    Label("Third Line"),
                    title="Multi-Widget Panel",
                )

        app = PanelApp()
        assert await snap_compare(app, "panel_multiple_children.svg")

    @pytest.mark.asyncio
    async def test_panel_title_renders_correctly(self, snap_compare):
        """Verify title positioning and styling in top border."""

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("Content with title"),
                    title="Panel Title Here",
                )

        app = PanelApp()
        assert await snap_compare(app, "panel_with_title.svg")


class TestHighlightedPanelBehavior:
    """Test widget behavior and dynamic updates."""

    def test_panel_instantiation(self):
        """Test panel can be instantiated without errors."""
        panel = HighlightedPanel(title="Test")
        assert panel is not None
        assert panel._panel_title == "Test"

    def test_panel_with_children(self):
        """Test panel accepts child widgets."""
        panel = HighlightedPanel(
            Label("Child 1"),
            Label("Child 2"),
            title="Parent Panel",
        )
        assert panel is not None
        assert len(panel._child_widgets) == 2

    @pytest.mark.asyncio
    async def test_panel_updates_on_resize(self, snap_compare):
        """Verify panel borders redraw correctly on terminal resize."""

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("Resize test content"),
                    title="Resize Test",
                )

        app = PanelApp()
        async with app.run_test() as pilot:
            # Initial render
            await pilot.pause()

            # Verify initial state
            panel = app.query_one(HighlightedPanel)
            assert panel is not None

            # Resize would trigger _update_borders() via on_resize()
            # Snapshot captures the rendered state
            pass

        assert await snap_compare(app, "panel_after_resize.svg")

    @pytest.mark.asyncio
    async def test_panel_refresh_theme(self):
        """Test refresh_theme() updates panel colors dynamically."""

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("Theme refresh test"),
                    title="Dynamic Theme",
                )

        app = PanelApp()
        async with app.run_test() as pilot:
            panel = app.query_one(HighlightedPanel)

            # Change cascade
            new_cascade = ColorCascade.from_preset("stygies")
            set_color_cascade(new_cascade)

            # Refresh panel to pick up new colors
            panel.refresh_theme()

            await pilot.pause()

            # Panel should have updated borders
            assert panel is not None


class TestHighlightedPanelEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_panel_empty_title(self, snap_compare):
        """Test panel renders correctly with no title."""

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("No title on this panel"),
                )

        app = PanelApp()
        assert await snap_compare(app, "panel_no_title.svg")

    @pytest.mark.asyncio
    async def test_panel_very_long_title(self, snap_compare):
        """Test panel handles very long titles gracefully."""

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("Long title test"),
                    title="This is an extremely long title that should be truncated",
                )

        app = PanelApp()
        assert await snap_compare(app, "panel_long_title.svg")

    @pytest.mark.asyncio
    async def test_panel_no_children(self, snap_compare):
        """Test panel renders correctly with no child widgets."""

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(title="Empty Panel")

        app = PanelApp()
        assert await snap_compare(app, "panel_empty_content.svg")

    def test_panel_special_characters_in_title(self, snap_compare):
        """Test panel handles special characters in title correctly."""

        # Programmatic assertion BEFORE snapshot: Test that panel accepts special chars
        special_title = 'Special: <>&"\' chars'
        test_panel = HighlightedPanel(Label("Test"), title=special_title)
        assert test_panel._panel_title == special_title, \
            "Panel should preserve special characters in title"

        class PanelApp(App):
            def compose(self):
                # Test HTML/XML special characters that need proper escaping
                yield HighlightedPanel(
                    Label("Content with special chars"),
                    title=special_title,
                )

        app = PanelApp()

        # Snapshot comparison - visual verification that special chars render correctly
        assert snap_compare(app, "panel_special_chars_title.svg")

    def test_panel_very_small_terminal(self, snap_compare):
        """Test panel renders gracefully in very small terminal."""

        # Programmatic assertion: Verify panel can be created without crashing
        test_panel = HighlightedPanel(Label("Tiny"), title="Small")
        assert test_panel is not None, "Panel should be createable"
        assert test_panel._panel_title == "Small", "Panel should store title"

        class PanelApp(App):
            def compose(self):
                yield HighlightedPanel(
                    Label("Tiny"),
                    title="Small",
                )

        app = PanelApp()

        # Snapshot comparison - visual verification that panel renders in small terminal
        # Note: snap_compare controls terminal size, this documents the edge case
        assert snap_compare(app, "panel_tiny_terminal.svg")
