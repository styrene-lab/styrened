"""Tests for InboxScreen navigation to ConversationScreen.

These tests verify:
- Row selection in inbox opens conversation
- Correct peer identity passed to conversation screen
- Proper screen stack management
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from textual.widgets import DataTable

from styrened.tui.app import StyreneApp
from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.screens.forum_thread import ForumThreadScreen
from styrened.tui.screens.inbox import InboxScreen, MailScreen
from styrened.tui.screens.mail_group_thread import MailGroupThreadScreen
from styrened.tui.services.app_lifecycle import LifecycleMode
from styrened.ui_state import (
    ConversationScopeKind,
    ForumThreadMeta,
    GroupThreadMeta,
    MailIndexState,
    MailThreadRecord,
)


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


def _make_mock_lifecycle(conversations: list | None = None) -> MagicMock:
    """Create a mock lifecycle with IPCBridge."""
    bridge = MagicMock()
    bridge.get_conversations = AsyncMock(return_value=conversations or [])
    bridge.get_messages = AsyncMock(return_value=[])
    bridge.mark_read = AsyncMock(return_value=0)
    bridge.send_chat = AsyncMock(return_value={})
    bridge.get_status = AsyncMock(return_value={})
    bridge.get_identity = AsyncMock(return_value={})
    bridge.get_hub_status = AsyncMock(return_value={})
    bridge.get_core_config = AsyncMock(return_value={})
    bridge.get_devices = AsyncMock(return_value=[])
    bridge.get_contacts = AsyncMock(return_value=[])
    bridge.get_auto_reply = AsyncMock(return_value={"mode": "disabled", "message": "", "cooldown": 300})

    lifecycle = MagicMock()
    lifecycle.ipc_bridge = bridge
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    return lifecycle


class TestInboxRowSelection:
    """Tests for selecting conversation rows in inbox."""

    @pytest.mark.asyncio
    async def test_inbox_builds_canonical_mail_index_from_legacy_conversations(self):
        """Inbox should normalize legacy IPC conversation payloads into mail threads."""
        conversations = [
            {
                "peer_hash": "peer_a_hash",
                "display_name": "Peer A",
                "unread_count": 2,
                "last_message_time": 200.0,
                "last_message_preview": "Hello",
                "attachment_count": 1,
            },
        ]
        lifecycle = _make_mock_lifecycle(conversations)

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            inbox = InboxScreen()
            await app.push_screen(inbox)
            await pilot.pause()

            assert len(inbox._mail_index.threads) == 1
            thread = inbox._mail_index.threads[0]
            assert thread.thread_id == "peer_a_hash"
            assert thread.participant_identity == "peer_a_hash"
            assert thread.display_name == "Peer A"
            assert thread.unread_count == 2
            assert thread.latest_message is not None
            assert thread.latest_message.preview == "Hello"


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
    async def test_group_thread_open_routes_to_group_placeholder_screen(self):
        """Group threads should route to a room-centric placeholder, not direct chat."""
        lifecycle = _make_mock_lifecycle([])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            inbox = InboxScreen()
            await app.push_screen(inbox)
            await pilot.pause()

            inbox._mail_index = MailIndexState(
                threads=(
                    MailThreadRecord(
                        thread_id="room-alpha",
                        scope_kind=ConversationScopeKind.GROUP,
                        display_name="Alpha Room",
                        group=GroupThreadMeta(room_id="room-alpha", room_name="Alpha Room", epoch_id="epoch-1"),
                    ),
                ),
                by_thread_id={},
            )
            inbox._mail_index = MailIndexState(
                threads=inbox._mail_index.threads,
                by_thread_id={thread.thread_id: thread for thread in inbox._mail_index.threads},
                refresh=inbox._mail_index.refresh,
            )

            table = app.screen.query_one("#conversation-table", DataTable)
            table.clear()
            table.add_row("Alpha Room", "hello", "-", "-", "-", key="room-alpha")
            table.focus()
            table.move_cursor(row=0)
            await pilot.pause()

            inbox.action_open_conversation()
            await pilot.pause()

            assert isinstance(app.screen, MailGroupThreadScreen)

    @pytest.mark.asyncio
    async def test_forum_thread_open_routes_to_forum_placeholder_screen(self):
        """Forum threads should route to a topic-centric placeholder screen."""
        lifecycle = _make_mock_lifecycle([])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            inbox = InboxScreen()
            await app.push_screen(inbox)
            await pilot.pause()

            inbox._mail_index = MailIndexState(
                threads=(
                    MailThreadRecord(
                        thread_id="topic-1",
                        scope_kind=ConversationScopeKind.FORUM,
                        display_name="Mesh Planning",
                        forum=ForumThreadMeta(topic_id="topic-1", topic_title="Mesh Planning", page_ref="nomad://board/topic-1"),
                    ),
                ),
                by_thread_id={},
            )
            inbox._mail_index = MailIndexState(
                threads=inbox._mail_index.threads,
                by_thread_id={thread.thread_id: thread for thread in inbox._mail_index.threads},
                refresh=inbox._mail_index.refresh,
            )

            table = app.screen.query_one("#conversation-table", DataTable)
            table.clear()
            table.add_row("Mesh Planning", "hello", "-", "-", "-", key="topic-1")
            table.focus()
            table.move_cursor(row=0)
            await pilot.pause()

            inbox.action_open_conversation()
            await pilot.pause()

            assert isinstance(app.screen, ForumThreadScreen)

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


class TestInboxLifecycleAndLayering:
    """Tests for mail workspace refresh and layered escape behavior."""

    def test_screen_resume_reloads_conversations_when_bridge_available(self):
        screen = InboxScreen()
        screen.run_worker = MagicMock()
        app = MagicMock()
        app.services.bridge = MagicMock()

        with (
            patch.object(InboxScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(InboxScreen, "_load_conversations", new=lambda self: None),
        ):
            screen.on_screen_resume()

        screen.run_worker.assert_called_once()

    def test_screen_resume_does_nothing_without_bridge(self):
        """StyreneScreen base handles missing bridge gracefully on resume."""
        screen = InboxScreen()
        screen._start_load = MagicMock()

        # StyreneScreen.on_screen_resume calls _start_load
        screen.on_screen_resume()

        screen._start_load.assert_called_once()

    def test_go_back_closes_compose_before_popping(self):
        screen = InboxScreen()
        screen._compose_active = True
        screen._close_compose = MagicMock()
        screen._close_search = MagicMock()
        app = MagicMock()

        with patch.object(InboxScreen, "app", new_callable=PropertyMock, return_value=app):
            screen.action_go_back()

        screen._close_compose.assert_called_once_with()
        screen._close_search.assert_not_called()
        app.pop_screen.assert_not_called()

    def test_go_back_closes_search_before_popping(self):
        screen = InboxScreen()
        screen._search_active = True
        screen._close_compose = MagicMock()
        screen._close_search = MagicMock()
        app = MagicMock()

        with patch.object(InboxScreen, "app", new_callable=PropertyMock, return_value=app):
            screen.action_go_back()

        screen._close_search.assert_called_once_with()
        screen._close_compose.assert_not_called()
        app.pop_screen.assert_not_called()


class TestInboxNavigation:
    """Tests for navigation to/from inbox screen."""

    @pytest.mark.asyncio
    async def test_open_mail_action_switches_to_exchange_workspace(self):
        """Global mail action should switch to Exchange workspace (Mail tab)."""
        from styrened.tui.screens.exchange import ExchangeScreen

        lifecycle = _make_mock_lifecycle([])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            app.action_open_mail()
            await pilot.pause()

            # Mail is now a tab within the Exchange workspace
            assert isinstance(app.screen, ExchangeScreen)

    @pytest.mark.asyncio
    async def test_push_inbox_and_escape_pops_it(self):
        """Pushing InboxScreen and pressing escape should pop it."""
        lifecycle = _make_mock_lifecycle([])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            inbox = InboxScreen()
            await app.push_screen(inbox)
            await pilot.pause()

            assert isinstance(app.screen, InboxScreen)

            await pilot.press("escape")
            await pilot.pause()

            # InboxScreen should be popped — whatever is underneath is fine
            assert not isinstance(app.screen, InboxScreen)
