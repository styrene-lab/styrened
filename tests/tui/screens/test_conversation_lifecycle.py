"""Tests for ConversationScreen lifecycle and message status management.

These tests verify:
- Mark messages as read when entering conversation
- Message sending via IPCBridge
- Proper screen navigation
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.tui.app import StyreneApp
from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.services.app_lifecycle import LifecycleMode


@pytest.fixture(autouse=True)
def mock_reticulum_for_tests(tmp_path):
    """Mock Reticulum initialization for all tests."""
    fake_config = tmp_path / "reticulum_config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
    ):
        yield


def _make_mock_lifecycle() -> MagicMock:
    """Create a mock lifecycle with IPCBridge."""
    bridge = MagicMock()
    bridge.get_messages = AsyncMock(return_value=[])
    bridge.mark_read = AsyncMock(return_value=3)
    bridge.send_chat = AsyncMock(return_value={"status": "sent"})
    bridge.get_conversations = AsyncMock(return_value=[])

    lifecycle = MagicMock()
    lifecycle.ipc_bridge = bridge
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    return lifecycle


class TestConversationMarkAsRead:
    """Tests for marking messages as read when entering conversation."""

    @pytest.mark.asyncio
    async def test_entering_conversation_calls_mark_read(self):
        """Opening ConversationScreen should call mark_read on IPCBridge."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            conversation = ConversationScreen(peer_hash="peer_hash_xyz")
            await app.push_screen(conversation)
            await pilot.pause()

            lifecycle.ipc_bridge.mark_read.assert_called_with("peer_hash_xyz")


class TestConversationNavigation:
    """Tests for conversation screen navigation."""

    @pytest.mark.asyncio
    async def test_escape_returns_to_previous_screen(self):
        """Pressing escape in ConversationScreen should return to previous screen."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            initial_screen_type = type(app.screen).__name__

            conversation = ConversationScreen(peer_hash="peer_hash_xyz")
            await app.push_screen(conversation)
            await pilot.pause()

            assert isinstance(app.screen, ConversationScreen)

            await pilot.press("escape")
            await pilot.pause()

            assert type(app.screen).__name__ == initial_screen_type

    @pytest.mark.asyncio
    async def test_conversation_displays_peer_identity_in_title(self):
        """ConversationScreen should display peer identity in title."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            conversation = ConversationScreen(peer_hash="peer_node_identity_hash")
            await app.push_screen(conversation)
            await pilot.pause()

            from textual.widgets import Static

            title_widget = app.screen.query_one("#conv-title", Static)
            title_text = str(title_widget.render())
            assert "peer_node_identi" in title_text, (
                f"Peer identity should appear in title. Got: {title_text}"
            )


class TestConversationMessageSending:
    """Tests for sending messages from conversation screen."""

    @pytest.mark.asyncio
    async def test_send_message_calls_bridge(self):
        """Sending a message should call send_chat on IPCBridge."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            conversation = ConversationScreen(peer_hash="peer_hash_xyz")
            await app.push_screen(conversation)
            await pilot.pause()

            await conversation._send_message("Hello!")
            await pilot.pause()

            lifecycle.ipc_bridge.send_chat.assert_called_with("peer_hash_xyz", "Hello!")
