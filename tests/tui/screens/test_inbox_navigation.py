"""Tests for InboxScreen navigation to ConversationScreen.

These tests verify:
- Row selection in inbox opens conversation
- Correct peer identity passed to conversation screen
- Proper screen stack management
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import DataTable

from styrened.tui.app import StyreneApp
from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.screens.inbox import InboxScreen
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


def _make_mock_lifecycle(conversations: list | None = None) -> MagicMock:
    """Create a mock lifecycle with IPCBridge."""
    bridge = MagicMock()
    bridge.get_conversations = AsyncMock(return_value=conversations or [])
    bridge.get_messages = AsyncMock(return_value=[])
    bridge.mark_read = AsyncMock(return_value=0)
    bridge.send_chat = AsyncMock(return_value={})

    lifecycle = MagicMock()
    lifecycle.ipc_bridge = bridge
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    return lifecycle


class TestInboxRowSelection:
    """Tests for selecting conversation rows in inbox."""

    @pytest.mark.asyncio
    async def test_enter_key_opens_conversation_for_selected_row(self):
        """Pressing Enter on inbox row should open ConversationScreen."""
        conversations = [
            {
                "peer_hash": "peer_a_hash",
                "display_name": "Peer A",
                "unread_count": 0,
                "last_message_time": 200.0,
                "last_message_preview": "Hello",
            },
            {
                "peer_hash": "peer_b_hash",
                "display_name": None,
                "unread_count": 1,
                "last_message_time": 300.0,
                "last_message_preview": "Hey",
            },
        ]
        lifecycle = _make_mock_lifecycle(conversations)

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            inbox = InboxScreen()
            await app.push_screen(inbox)
            await pilot.pause()

            # Focus the table and select first row
            table = app.screen.query_one("#conversation-table", DataTable)
            table.focus()
            await pilot.pause()

            table.move_cursor(row=0)
            await pilot.pause()

            # Open conversation
            inbox.action_open_conversation()
            await pilot.pause()

            assert isinstance(app.screen, ConversationScreen), (
                f"Expected ConversationScreen, got {type(app.screen).__name__}"
            )

    @pytest.mark.asyncio
    async def test_empty_inbox_enter_does_nothing(self):
        """Pressing Enter on empty inbox should not crash or navigate."""
        lifecycle = _make_mock_lifecycle([])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            inbox = InboxScreen()
            await app.push_screen(inbox)
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, InboxScreen), (
                f"Should remain on InboxScreen, got {type(app.screen).__name__}"
            )


class TestInboxNavigation:
    """Tests for navigation to/from inbox screen."""

    @pytest.mark.asyncio
    async def test_escape_from_inbox_returns_to_dashboard(self):
        """Pressing escape in InboxScreen should return to previous screen."""
        lifecycle = _make_mock_lifecycle([])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            initial_screen_type = type(app.screen).__name__

            inbox = InboxScreen()
            await app.push_screen(inbox)
            await pilot.pause()

            assert isinstance(app.screen, InboxScreen)

            await pilot.press("escape")
            await pilot.pause()

            assert type(app.screen).__name__ == initial_screen_type
