"""Tests for progress panel widget."""

from styrened.tui.widgets.progress_panel import ProgressPanel


def test_progress_panel_instantiation():
    """Test progress panel can be instantiated."""
    panel = ProgressPanel()
    assert panel is not None
    assert not panel.is_complete
    assert not panel.is_error
