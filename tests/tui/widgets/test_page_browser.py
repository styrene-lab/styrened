"""Tests for PageBrowserWidget - embedded page viewer for NomadNet nodes.

Covers widget initialization, page loading, navigation, and error handling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.tui.services.app_lifecycle import LifecycleMode
from styrened.tui.widgets.page_browser import PageBrowserWidget


@pytest.fixture(autouse=True)
def mock_reticulum_for_tests(tmp_path):
    """Mock Reticulum initialization for all tests."""
    fake_config = tmp_path / "reticulum_config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


def _make_mock_lifecycle(page_result=None):
    """Create a mock lifecycle with IPCBridge that returns page results."""
    bridge = MagicMock()
    bridge.fetch_page = AsyncMock(return_value=page_result or {
        "status": "ok",
        "content": ">Welcome\nHello world",
        "transfer_time": 0.5,
        "content_length": 25,
    })
    bridge.page_disconnect = AsyncMock(return_value=True)

    lifecycle = MagicMock()
    lifecycle.ipc_bridge = bridge
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    return lifecycle


class TestPageBrowserWidgetInit:
    """Tests for widget initialization."""

    def test_widget_creation(self):
        """Widget should initialize with destination hash."""
        widget = PageBrowserWidget(
            destination_hash="abcdef1234567890",
            id="test-browser",
        )
        assert widget.destination_hash == "abcdef1234567890"
        assert widget._initial_path == "/page/index.mu"

    def test_widget_custom_path(self):
        """Widget should accept custom initial path."""
        widget = PageBrowserWidget(
            destination_hash="abcdef1234567890",
            initial_path="/page/about.mu",
        )
        assert widget._initial_path == "/page/about.mu"

    def test_widget_empty_history(self):
        """Widget should start with empty history."""
        widget = PageBrowserWidget(destination_hash="abc")
        assert widget._history == []


class TestPageBrowserNavigation:
    """Tests for navigation methods."""

    def test_navigate_pushes_history(self):
        """Navigate should push current path to history."""
        widget = PageBrowserWidget(destination_hash="abc")
        widget.current_path = "/page/index.mu"

        with patch.object(widget, "run_worker"):
            widget.navigate("/page/about.mu")

        assert "/page/index.mu" in widget._history

    def test_back_pops_history(self):
        """Going back should pop from history."""
        widget = PageBrowserWidget(destination_hash="abc")
        widget._history = ["/page/index.mu", "/page/about.mu"]

        with patch.object(widget, "run_worker"):
            widget.action_go_back()

        assert len(widget._history) == 1
        assert widget._history[0] == "/page/index.mu"

    def test_back_empty_history_does_nothing(self):
        """Going back with empty history should do nothing."""
        widget = PageBrowserWidget(destination_hash="abc")
        widget._history = []

        # Should not raise
        widget.action_go_back()
        assert widget._history == []

    def test_reload_does_not_push_history(self):
        """Reload should not modify history."""
        widget = PageBrowserWidget(destination_hash="abc")
        widget._history = ["/page/old.mu"]

        with patch.object(widget, "run_worker"):
            widget.action_reload()

        assert len(widget._history) == 1


class TestPageBrowserLoadPage:
    """Tests for _load_page internals."""

    @pytest.mark.asyncio
    async def test_load_page_no_bridge_sets_error(self):
        """Loading without bridge should set error message."""
        widget = PageBrowserWidget(destination_hash="abc")

        # Mock the app with no bridge
        mock_app = MagicMock()
        mock_app._lifecycle.ipc_bridge = None
        widget._dom_element = mock_app  # Prevent real DOM access

        # Override the property to return None
        with patch.object(type(widget), "_ipc_bridge", property(lambda s: None)):
            # Need to also mock query_one to prevent NoMatches
            widget.query_one = MagicMock(side_effect=Exception("No DOM"))
            await widget._load_page("/page/index.mu")

        assert widget.loading is False

    @pytest.mark.asyncio
    async def test_load_page_handles_bridge_error(self):
        """Loading should handle exceptions from bridge gracefully."""
        widget = PageBrowserWidget(destination_hash="abc")

        mock_bridge = MagicMock()
        mock_bridge.fetch_page = AsyncMock(side_effect=Exception("connection lost"))

        with patch.object(type(widget), "_ipc_bridge", property(lambda s: mock_bridge)):
            widget.query_one = MagicMock(side_effect=Exception("No DOM"))
            await widget._load_page("/page/index.mu")

        assert widget.loading is False
