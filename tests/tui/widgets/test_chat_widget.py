"""Tests for ChatWidget - embeddable chat messaging widget."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.tui.app import StyreneApp
from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.services.app_lifecycle import LifecycleMode
from styrened.tui.widgets.chat_widget import ChatWidget, STATUS_ICONS
from textual.widgets import Input, Static


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


def _make_mock_lifecycle(messages=None):
    """Create a mock lifecycle with IPCBridge."""
    bridge = MagicMock()
    bridge.get_messages = AsyncMock(return_value=messages or [])
    bridge.mark_read = AsyncMock(return_value=0)
    bridge.send_chat = AsyncMock(return_value={"status": "sent"})

    lifecycle = MagicMock()
    lifecycle.ipc_bridge = bridge
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    return lifecycle


class TestChatWidgetInit:
    """Tests for ChatWidget initialization."""

    def test_chat_widget_initialization(self):
        """ChatWidget should initialize with peer_hash."""
        widget = ChatWidget(peer_hash="test_hash")
        assert widget.peer_hash == "test_hash"
        assert widget.display_name is None

    def test_chat_widget_with_display_name(self):
        """ChatWidget should accept optional display_name."""
        widget = ChatWidget(peer_hash="test_hash", display_name="Test Node")
        assert widget.peer_hash == "test_hash"
        assert widget.display_name == "Test Node"


class TestChatWidgetNoBridge:
    """Tests for ChatWidget when daemon is not connected."""

    @pytest.mark.asyncio
    async def test_shows_daemon_not_connected_when_bridge_is_none(self):
        """ChatWidget should show 'Daemon not connected' when bridge is None."""
        lifecycle = MagicMock()
        lifecycle.ipc_bridge = None
        lifecycle.initialize_async = AsyncMock(return_value=True)
        lifecycle.active_mode = LifecycleMode.IPC
        lifecycle.shutdown_async = AsyncMock()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            screen = ConversationScreen(peer_hash="test_hash")
            await app.push_screen(screen)
            await pilot.pause()

            # Should find the no-bridge message
            no_bridge = screen.query("#chat-no-bridge")
            assert len(no_bridge) > 0, "Should show daemon not connected message"

    @pytest.mark.asyncio
    async def test_no_input_field_when_bridge_is_none(self):
        """ChatWidget should not show input field when bridge is None."""
        lifecycle = MagicMock()
        lifecycle.ipc_bridge = None
        lifecycle.initialize_async = AsyncMock(return_value=True)
        lifecycle.active_mode = LifecycleMode.IPC
        lifecycle.shutdown_async = AsyncMock()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            screen = ConversationScreen(peer_hash="test_hash")
            await app.push_screen(screen)
            await pilot.pause()

            # Should not have chat input
            inputs = screen.query("#chat-input")
            assert len(inputs) == 0, "Should not show input when bridge is None"


class TestChatWidgetWithBridge:
    """Tests for ChatWidget with active IPCBridge."""

    @pytest.mark.asyncio
    async def test_loads_messages_on_mount(self):
        """ChatWidget should load messages via bridge on mount."""
        lifecycle = _make_mock_lifecycle(messages=[
            {"content": "Hello", "is_outgoing": False, "status": "read"},
        ])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            screen = ConversationScreen(peer_hash="peer_xyz")
            await app.push_screen(screen)
            await pilot.pause()

            lifecycle.ipc_bridge.get_messages.assert_called_with("peer_xyz")

    @pytest.mark.asyncio
    async def test_marks_read_on_mount(self):
        """ChatWidget should call mark_read on mount."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            screen = ConversationScreen(peer_hash="peer_xyz")
            await app.push_screen(screen)
            await pilot.pause()

            lifecycle.ipc_bridge.mark_read.assert_called_with("peer_xyz")

    @pytest.mark.asyncio
    async def test_sends_message_via_bridge(self):
        """ChatWidget should send messages via bridge.send_chat."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            screen = ConversationScreen(peer_hash="peer_xyz")
            await app.push_screen(screen)
            await pilot.pause()

            # Get the chat widget and send message directly
            chat_widget = screen.query_one(ChatWidget)
            await chat_widget._send_message("Hello!")
            await pilot.pause()

            lifecycle.ipc_bridge.send_chat.assert_called_with("peer_xyz", "Hello!")

    @pytest.mark.asyncio
    async def test_empty_input_not_submitted(self):
        """ChatWidget should not send empty/whitespace-only input."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            screen = ConversationScreen(peer_hash="peer_xyz")
            await app.push_screen(screen)
            await pilot.pause()

            # Find the input and set empty value, then simulate submit
            chat_input = screen.query_one("#chat-input", Input)
            chat_input.value = "   "  # whitespace only

            # The on_input_submitted handler strips and checks before calling _send_message
            from textual.widgets import Input as TextualInput

            event = TextualInput.Submitted(chat_input, "   ")
            chat_widget = screen.query_one(ChatWidget)
            chat_widget.on_input_submitted(event)
            await pilot.pause()

            # send_chat should not have been called for whitespace-only input
            lifecycle.ipc_bridge.send_chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_has_input_field_when_bridge_connected(self):
        """ChatWidget should show input field when bridge is connected."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            screen = ConversationScreen(peer_hash="peer_xyz")
            await app.push_screen(screen)
            await pilot.pause()

            inputs = screen.query("#chat-input")
            assert len(inputs) > 0, "Should show chat input when bridge is connected"


class TestStatusIcons:
    """Tests for delivery status indicators."""

    def test_all_statuses_have_icons(self):
        """All expected statuses should have icons."""
        expected = {"pending", "sent", "delivered", "failed", "read"}
        assert expected == set(STATUS_ICONS.keys())

    def test_pending_icon(self):
        """Pending should show hourglass."""
        assert STATUS_ICONS["pending"] == "\u23f3"

    def test_sent_icon(self):
        """Sent should show single check."""
        assert STATUS_ICONS["sent"] == "\u2713"

    def test_failed_icon(self):
        """Failed should show cross."""
        assert STATUS_ICONS["failed"] == "\u2717"
