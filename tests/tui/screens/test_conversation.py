"""Tests for ConversationScreen - message thread display."""

from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from styrened.models.messages import Base, Message
from styrened.protocols.chat import ChatProtocol
from styrened.tui.screens.conversation import ConversationScreen


@pytest.fixture
def test_db(tmp_path):
    """Create test database with sample messages."""
    db_path = tmp_path / "test_conversation.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Add sample conversation with Alice
    with Session(engine) as session:
        session.add(Message(
            source_hash="alice_hash",
            destination_hash="me_hash",
            timestamp=100.0,
            content="Hello!",
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
        session.add(Message(
            source_hash="alice_hash",
            destination_hash="me_hash",
            timestamp=300.0,
            content="How are you?",
            protocol_id="chat",
            status="sent",
        ))
        session.commit()

    return engine


@pytest.fixture
def mock_chat_protocol():
    """Create mock ChatProtocol."""
    protocol = Mock(spec=ChatProtocol)
    protocol.send_message = AsyncMock()
    protocol.get_conversation_history = Mock(return_value=[])
    return protocol


def test_conversation_screen_initialization(mock_chat_protocol):
    """ConversationScreen should initialize without errors."""
    screen = ConversationScreen(
        destination_hash="alice_hash",
        local_identity_hash="me_hash",
        chat_protocol=mock_chat_protocol,
    )
    assert screen is not None
    assert screen.destination_hash == "alice_hash"


def test_conversation_screen_get_messages(test_db, mock_chat_protocol):
    """ConversationScreen should retrieve message history."""
    # Mock chat protocol to return messages from database
    with Session(test_db) as session:
        messages = (
            session.query(Message)
            .filter(
                Message.protocol_id == "chat",
            )
            .order_by(Message.timestamp.asc())
            .all()
        )
        mock_chat_protocol.get_conversation_history.return_value = messages

    screen = ConversationScreen(
        destination_hash="alice_hash",
        local_identity_hash="me_hash",
        chat_protocol=mock_chat_protocol,
    )

    history = screen.get_messages()

    assert len(history) == 3
    assert history[0].content == "Hello!"
    assert history[1].content == "Hi Alice!"
    assert history[2].content == "How are you?"


@pytest.mark.asyncio
async def test_conversation_screen_send_message(mock_chat_protocol):
    """ConversationScreen should send messages via ChatProtocol."""
    screen = ConversationScreen(
        destination_hash="alice_hash",
        local_identity_hash="me_hash",
        chat_protocol=mock_chat_protocol,
    )

    await screen.send_message("Test message")

    # Verify ChatProtocol.send_message was called
    mock_chat_protocol.send_message.assert_called_once_with(
        "alice_hash", "Test message"
    )


def test_conversation_screen_message_formatting(test_db, mock_chat_protocol):
    """ConversationScreen should format messages for display."""
    with Session(test_db) as session:
        messages = (
            session.query(Message)
            .filter(Message.protocol_id == "chat")
            .order_by(Message.timestamp.asc())
            .all()
        )
        mock_chat_protocol.get_conversation_history.return_value = messages

    screen = ConversationScreen(
        destination_hash="alice_hash",
        local_identity_hash="me_hash",
        chat_protocol=mock_chat_protocol,
    )

    formatted = screen.format_messages()

    # Should have 3 formatted messages
    assert len(formatted) == 3

    # First message from Alice
    assert "alice_hash" in formatted[0]["source"]
    assert formatted[0]["content"] == "Hello!"

    # Second message from me
    assert "me_hash" in formatted[1]["source"]
    assert formatted[1]["content"] == "Hi Alice!"
