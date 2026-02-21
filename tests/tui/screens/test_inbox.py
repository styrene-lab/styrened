"""Tests for InboxScreen - conversation list."""


import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from styrened.models.messages import Base, Message
from styrened.tui.screens.inbox import InboxScreen


@pytest.fixture
def test_db(tmp_path):
    """Create test database with sample conversations."""
    db_path = tmp_path / "test_inbox.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Add sample messages for conversations
    with Session(engine) as session:
        # Conversation with Alice
        session.add(Message(
            source_hash="alice_hash",
            destination_hash="me_hash",
            timestamp=100.0,
            content="Hello from Alice",
            protocol_id="chat",
            status="sent",
        ))
        session.add(Message(
            source_hash="me_hash",
            destination_hash="alice_hash",
            timestamp=200.0,
            content="Hi Alice!",
            protocol_id="chat",
            status="sent",
        ))

        # Conversation with Bob
        session.add(Message(
            source_hash="bob_hash",
            destination_hash="me_hash",
            timestamp=300.0,
            content="Hey there",
            protocol_id="chat",
            status="sent",
        ))

        session.commit()

    return engine


def test_inbox_screen_initialization():
    """InboxScreen should initialize without errors."""
    screen = InboxScreen(db_engine=None, local_identity_hash="me_hash")
    assert screen is not None


def test_inbox_screen_get_conversations(test_db):
    """InboxScreen should retrieve unique conversations."""
    screen = InboxScreen(db_engine=test_db, local_identity_hash="me_hash")

    conversations = screen.get_conversations()

    # Should have 2 conversations (Alice and Bob)
    assert len(conversations) == 2

    # Extract destination hashes
    dest_hashes = {conv["destination_hash"] for conv in conversations}
    assert "alice_hash" in dest_hashes
    assert "bob_hash" in dest_hashes


def test_inbox_screen_conversation_has_last_message(test_db):
    """Each conversation should include last message preview."""
    screen = InboxScreen(db_engine=test_db, local_identity_hash="me_hash")

    conversations = screen.get_conversations()

    # Find Bob's conversation
    bob_conv = next(c for c in conversations if c["destination_hash"] == "bob_hash")

    assert bob_conv["last_message"] == "Hey there"
    assert bob_conv["last_timestamp"] == 300.0


def test_inbox_screen_conversation_ordering(test_db):
    """Conversations should be ordered by most recent message."""
    screen = InboxScreen(db_engine=test_db, local_identity_hash="me_hash")

    conversations = screen.get_conversations()

    # Bob's message is most recent (timestamp 300)
    assert conversations[0]["destination_hash"] == "bob_hash"
    # Alice's message is older (timestamp 200)
    assert conversations[1]["destination_hash"] == "alice_hash"


def test_inbox_screen_unread_count(test_db):
    """Conversations should track unread message count."""
    # Add an unread message from Alice
    with Session(test_db) as session:
        session.add(Message(
            source_hash="alice_hash",
            destination_hash="me_hash",
            timestamp=400.0,
            content="Unread message",
            protocol_id="chat",
            status="pending",  # Pending = unread
        ))
        session.commit()

    screen = InboxScreen(db_engine=test_db, local_identity_hash="me_hash")
    conversations = screen.get_conversations()

    # Find Alice's conversation
    alice_conv = next(c for c in conversations if c["destination_hash"] == "alice_hash")

    # Should have 1 unread message
    assert alice_conv["unread_count"] == 1


def test_inbox_screen_no_conversations(tmp_path):
    """InboxScreen should handle empty conversation list."""
    db_path = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    screen = InboxScreen(db_engine=engine, local_identity_hash="me_hash")
    conversations = screen.get_conversations()

    assert conversations == []
