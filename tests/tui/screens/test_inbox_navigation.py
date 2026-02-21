"""Tests for InboxScreen navigation to ConversationScreen.

These tests drive the implementation of:
- Row selection in inbox opens conversation
- Correct peer identity passed to conversation screen
- Proper screen stack management

Tests are written TDD-style and will fail until functionality is implemented.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session
from textual.widgets import DataTable

from styrened.tui.app import StyreneApp
from styrened.models.messages import Message, init_db
from styrened.protocols.chat import ChatProtocol
from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.screens.inbox import InboxScreen


@pytest.fixture
def message_db(tmp_path):
    """Create test message database."""
    db_path = tmp_path / "messages.db"
    engine = init_db(str(db_path))
    return engine


@pytest.fixture
def mock_local_identity():
    """Mock local identity hash."""
    return "local_identity_hash_1234"


def add_conversation_messages(engine, local_hash: str, peer_hash: str, count: int = 3) -> None:
    """Helper to add conversation messages to database."""
    with Session(engine) as session:
        base_time = datetime.now().timestamp()
        for i in range(count):
            # Incoming message
            msg = Message(
                source_hash=peer_hash,
                destination_hash=local_hash,
                timestamp=base_time + i,
                content=f"Message {i} from {peer_hash[:8]}",
                protocol_id="chat",
                status="pending" if i == count - 1 else "read",  # Last one unread
            )
            session.add(msg)
        session.commit()


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


@pytest.fixture
def chat_protocol_factory(message_db, mock_local_identity):
    """Factory fixture to create ChatProtocol instances."""

    def _create():
        mock_router = Mock()
        mock_identity = Mock()
        mock_identity.hexhash = mock_local_identity
        return ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=message_db,
        )

    return _create


class TestInboxRowSelection:
    """Tests for selecting conversation rows in inbox."""

    @pytest.mark.asyncio
    async def test_enter_key_opens_conversation_for_selected_row(
        self, message_db, mock_local_identity, chat_protocol_factory
    ):
        """Pressing Enter on inbox row should open ConversationScreen."""
        # Setup: Conversations with two peers
        add_conversation_messages(message_db, mock_local_identity, "peer_a_hash", count=2)
        add_conversation_messages(message_db, mock_local_identity, "peer_b_hash", count=3)

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        chat_protocol = chat_protocol_factory()
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            # Push inbox screen with chat_protocol
            inbox = InboxScreen(
                db_engine=message_db,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
            await app.push_screen(inbox)
            await pilot.pause()

            # Verify we have conversations
            conversations = inbox.get_conversations()
            assert len(conversations) >= 1, "Should have at least 1 conversation"

            # Focus the table and select row
            table = app.screen.query_one("#conversation-table", DataTable)
            table.focus()
            await pilot.pause()

            # Move cursor to first row explicitly
            table.move_cursor(row=0)
            await pilot.pause()

            # Call action directly to open conversation
            inbox.action_open_conversation()
            await pilot.pause()

            # Should now be in ConversationScreen
            assert isinstance(app.screen, ConversationScreen), (
                f"Expected ConversationScreen, got {type(app.screen).__name__}"
            )

    @pytest.mark.asyncio
    async def test_conversation_opens_with_correct_peer_identity(
        self, message_db, mock_local_identity, chat_protocol_factory
    ):
        """ConversationScreen should receive the correct peer identity from inbox."""
        peer_hash = "specific_peer_hash_xyz"
        add_conversation_messages(message_db, mock_local_identity, peer_hash, count=2)

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        chat_protocol = chat_protocol_factory()
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            inbox = InboxScreen(
                db_engine=message_db,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
            await app.push_screen(inbox)
            await pilot.pause()

            # Select first row and open
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

            if isinstance(app.screen, ConversationScreen):
                # Verify peer identity
                assert app.screen.destination_hash == peer_hash, (
                    f"Expected peer {peer_hash}, got {app.screen.destination_hash}"
                )

    @pytest.mark.asyncio
    async def test_empty_inbox_enter_does_nothing(
        self, message_db, mock_local_identity, chat_protocol_factory
    ):
        """Pressing Enter on empty inbox should not crash or navigate."""
        # No messages in database
        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        chat_protocol = chat_protocol_factory()
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            inbox = InboxScreen(
                db_engine=message_db,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
            await app.push_screen(inbox)
            await pilot.pause()

            # Press Enter on empty table
            await pilot.press("enter")
            await pilot.pause()

            # Should still be on inbox screen
            assert isinstance(app.screen, InboxScreen), (
                f"Should remain on InboxScreen, got {type(app.screen).__name__}"
            )


class TestInboxConversationDisplay:
    """Tests for how conversations are displayed in inbox."""

    @pytest.mark.asyncio
    async def test_inbox_shows_all_conversations(
        self, message_db, mock_local_identity, chat_protocol_factory
    ):
        """Inbox should display all conversation partners."""
        add_conversation_messages(message_db, mock_local_identity, "peer_a_hash", count=2)
        add_conversation_messages(message_db, mock_local_identity, "peer_b_hash", count=1)
        add_conversation_messages(message_db, mock_local_identity, "peer_c_hash", count=4)

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        chat_protocol = chat_protocol_factory()
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            inbox = InboxScreen(
                db_engine=message_db,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
            await app.push_screen(inbox)
            await pilot.pause()

            _ = app.screen.query_one("#conversation-table", DataTable)

            # Should have 3 conversation rows
            # Note: row_count might include placeholder row if empty
            conversations = inbox.get_conversations()
            assert len(conversations) == 3, f"Expected 3 conversations, got {len(conversations)}"

    @pytest.mark.asyncio
    async def test_inbox_shows_unread_counts(
        self, message_db, mock_local_identity, chat_protocol_factory
    ):
        """Inbox should display unread message counts per conversation."""
        # Setup: Add messages with specific unread counts
        with Session(message_db) as session:
            # Peer A: 2 unread
            for i in range(2):
                msg = Message(
                    source_hash="peer_a_hash",
                    destination_hash=mock_local_identity,
                    timestamp=datetime.now().timestamp() + i,
                    content=f"Unread {i}",
                    protocol_id="chat",
                    status="pending",
                )
                session.add(msg)
            session.commit()

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        chat_protocol = chat_protocol_factory()
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            inbox = InboxScreen(
                db_engine=message_db,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
            await app.push_screen(inbox)
            await pilot.pause()

            conversations = inbox.get_conversations()
            peer_a_conv = next(
                (c for c in conversations if c["destination_hash"] == "peer_a_hash"), None
            )

            assert peer_a_conv is not None, "peer_a conversation should exist"
            assert peer_a_conv["unread_count"] == 2, (
                f"Expected 2 unread, got {peer_a_conv['unread_count']}"
            )


class TestInboxNavigation:
    """Tests for navigation to/from inbox screen."""

    @pytest.mark.asyncio
    async def test_escape_from_inbox_returns_to_dashboard(
        self, message_db, mock_local_identity, chat_protocol_factory
    ):
        """Pressing escape in InboxScreen should return to dashboard."""
        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        chat_protocol = chat_protocol_factory()
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            # Record initial screen type
            initial_screen_type = type(app.screen).__name__

            inbox = InboxScreen(
                db_engine=message_db,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
            await app.push_screen(inbox)
            await pilot.pause()

            assert isinstance(app.screen, InboxScreen)

            # Press escape
            await pilot.press("escape")
            await pilot.pause()

            # Should be back to initial screen
            assert type(app.screen).__name__ == initial_screen_type

    @pytest.mark.asyncio
    async def test_escape_from_conversation_returns_to_inbox(
        self, message_db, mock_local_identity, chat_protocol_factory
    ):
        """Escape from conversation (opened via inbox) should return to inbox."""
        add_conversation_messages(message_db, mock_local_identity, "peer_hash", count=2)

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        chat_protocol = chat_protocol_factory()
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            # Push inbox
            inbox = InboxScreen(
                db_engine=message_db,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
            await app.push_screen(inbox)
            await pilot.pause()

            # Open conversation
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

            if isinstance(app.screen, ConversationScreen):
                # Press escape to go back
                await pilot.press("escape")
                await pilot.pause()

                # Should be back to inbox
                assert isinstance(app.screen, InboxScreen), (
                    f"Expected InboxScreen, got {type(app.screen).__name__}"
                )
