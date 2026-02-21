"""Tests for ChatProtocol implementation."""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from styrened.models.messages import Base, Message
from styrened.protocols.base import LXMFMessage
from styrened.protocols.chat import ChatProtocol


@pytest.fixture
def test_db(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test_chat.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def mock_router():
    """Create mock LXMF router."""
    router = Mock()
    router.announce = AsyncMock()
    return router


@pytest.fixture
def mock_identity():
    """Create mock RNS identity."""
    identity = Mock()
    identity.hash = b"test_identity_hash"
    identity.hexhash = "746573745f6964656e746974795f68617368"
    return identity


@pytest.fixture
def chat_protocol(mock_router, mock_identity, test_db):
    """Create ChatProtocol instance."""
    return ChatProtocol(
        router=mock_router,
        identity=mock_identity,
        db_engine=test_db,
    )


def test_chat_protocol_id(chat_protocol):
    """ChatProtocol should have protocol_id 'chat'."""
    assert chat_protocol.protocol_id == "chat"


def test_chat_protocol_can_handle_chat_message(chat_protocol):
    """ChatProtocol should handle messages with protocol='chat'."""
    msg = LXMFMessage(
        source_hash="source",
        destination_hash="dest",
        timestamp=123.0,
        fields={"protocol": "chat"},
    )

    assert chat_protocol.can_handle(msg)


def test_chat_protocol_cannot_handle_non_chat_message(chat_protocol):
    """ChatProtocol should not handle messages without protocol='chat'."""
    msg = LXMFMessage(
        source_hash="source",
        destination_hash="dest",
        timestamp=123.0,
        fields={"protocol": "rpc"},
    )

    assert not chat_protocol.can_handle(msg)


def test_chat_protocol_cannot_handle_no_protocol(chat_protocol):
    """ChatProtocol should not handle messages without protocol field."""
    msg = LXMFMessage(
        source_hash="source",
        destination_hash="dest",
        timestamp=123.0,
        fields={},
    )

    assert not chat_protocol.can_handle(msg)


@pytest.mark.asyncio
async def test_chat_protocol_handle_message(chat_protocol, test_db):
    """ChatProtocol should save incoming messages to database."""
    msg = LXMFMessage(
        source_hash="abc123",
        destination_hash="def456",
        timestamp=1234567890.5,
        content="Hello, world!",
        fields={"protocol": "chat"},
        protocol_id="chat",
    )

    await chat_protocol.handle_message(msg)

    # Verify message saved to database
    with Session(test_db) as session:
        saved_msg = session.query(Message).filter_by(source_hash="abc123").first()
        assert saved_msg is not None
        assert saved_msg.content == "Hello, world!"
        assert saved_msg.protocol_id == "chat"
        assert saved_msg.status == "pending"


@pytest.mark.asyncio
async def test_chat_protocol_handle_message_with_null_content(chat_protocol, test_db):
    """ChatProtocol should handle messages with null content."""
    msg = LXMFMessage(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
        content=None,
        fields={"protocol": "chat"},
        protocol_id="chat",
    )

    await chat_protocol.handle_message(msg)

    # Verify message saved
    with Session(test_db) as session:
        saved_msg = session.query(Message).filter_by(source_hash="abc").first()
        assert saved_msg is not None
        assert saved_msg.content is None


@pytest.mark.asyncio
@patch("styrened.protocols.chat.RNS")
@patch("styrened.protocols.chat.LXMF")
async def test_chat_protocol_send_message(mock_lxmf, mock_rns, chat_protocol, mock_identity):
    """ChatProtocol should send messages via LXMF."""
    mock_message = Mock()
    mock_lxmf.LXMessage.return_value = mock_message
    mock_lxmf.APP_NAME = "lxmf"

    # Mock RNS.Identity.recall to return a mock identity
    mock_dest_identity = Mock()
    mock_rns.Identity.recall.return_value = mock_dest_identity
    mock_rns.Destination.OUT = 2
    mock_rns.Destination.SINGLE = 1

    # Use valid 32-char hex destination
    hex_dest = "0123456789abcdef0123456789abcdef"

    await chat_protocol.send_message(
        destination=hex_dest,
        content="Test message",
    )

    # Verify RNS.Identity.recall was called with raw bytes
    mock_rns.Identity.recall.assert_called_once_with(bytes.fromhex(hex_dest))

    # Verify LXMF message created with proper destination objects
    mock_lxmf.LXMessage.assert_called_once()
    call_kwargs = mock_lxmf.LXMessage.call_args[1]
    # Now we pass proper destination objects, not None
    assert call_kwargs["destination"] is not None
    assert call_kwargs["source"] is not None
    assert call_kwargs["content"] == b"Test message"
    assert call_kwargs["fields"] == {"protocol": "chat"}


@pytest.mark.asyncio
@patch("styrened.protocols.chat.RNS")
@patch("styrened.protocols.chat.LXMF")
async def test_chat_protocol_send_message_unknown_destination_raises(
    mock_lxmf, mock_rns, chat_protocol
):
    """ChatProtocol should raise ValueError for unknown destination."""
    mock_lxmf.APP_NAME = "lxmf"
    mock_rns.Identity.recall.return_value = None

    hex_dest = "deadbeefcafe0123456789abcdef0123"

    with pytest.raises(ValueError, match="identity not known"):
        await chat_protocol.send_message(
            destination=hex_dest,
            content="Test message",
        )


@pytest.mark.asyncio
@patch("styrened.protocols.chat.RNS")
@patch("styrened.protocols.chat.LXMF")
async def test_chat_protocol_send_message_saves_to_db(mock_lxmf, mock_rns, chat_protocol, test_db):
    """ChatProtocol should save sent messages to database."""
    mock_message = Mock()
    mock_lxmf.LXMessage.return_value = mock_message
    mock_lxmf.APP_NAME = "lxmf"
    mock_rns.Identity.recall.return_value = Mock()
    mock_rns.Destination.OUT = 2
    mock_rns.Destination.SINGLE = 1

    hex_dest = "abcdef0123456789abcdef0123456789"

    await chat_protocol.send_message(
        destination=hex_dest,
        content="Test message",
    )

    # Verify message saved to database
    with Session(test_db) as session:
        saved_msg = session.query(Message).filter_by(destination_hash=hex_dest).first()
        assert saved_msg is not None
        assert saved_msg.content == "Test message"
        assert saved_msg.protocol_id == "chat"
        assert saved_msg.status == "pending"


@pytest.mark.asyncio
async def test_chat_protocol_get_conversation_history(chat_protocol, test_db):
    """ChatProtocol should retrieve conversation history from database."""
    # Add test messages to database
    with Session(test_db) as session:
        session.add(
            Message(
                source_hash="alice",
                destination_hash="bob",
                timestamp=100.0,
                content="Message 1",
                protocol_id="chat",
                status="sent",
            )
        )
        session.add(
            Message(
                source_hash="bob",
                destination_hash="alice",
                timestamp=200.0,
                content="Message 2",
                protocol_id="chat",
                status="sent",
            )
        )
        session.add(
            Message(
                source_hash="alice",
                destination_hash="bob",
                timestamp=300.0,
                content="Message 3",
                protocol_id="chat",
                status="sent",
            )
        )
        # RPC message (should be filtered out)
        session.add(
            Message(
                source_hash="alice",
                destination_hash="bob",
                timestamp=400.0,
                content="RPC call",
                protocol_id="rpc",
                status="sent",
            )
        )
        session.commit()

    # Retrieve conversation
    messages = chat_protocol.get_conversation_history("alice", "bob")

    assert len(messages) == 3
    assert messages[0].content == "Message 1"
    assert messages[1].content == "Message 2"
    assert messages[2].content == "Message 3"
    # Verify RPC message not included
    assert all(msg.protocol_id == "chat" for msg in messages)


@pytest.mark.asyncio
async def test_chat_protocol_get_conversation_history_ordered_by_timestamp(chat_protocol, test_db):
    """Conversation history should be ordered by timestamp ascending."""
    # Add messages out of order
    with Session(test_db) as session:
        session.add(
            Message(
                source_hash="alice",
                destination_hash="bob",
                timestamp=300.0,
                content="Third",
                protocol_id="chat",
            )
        )
        session.add(
            Message(
                source_hash="alice",
                destination_hash="bob",
                timestamp=100.0,
                content="First",
                protocol_id="chat",
            )
        )
        session.add(
            Message(
                source_hash="alice",
                destination_hash="bob",
                timestamp=200.0,
                content="Second",
                protocol_id="chat",
            )
        )
        session.commit()

    messages = chat_protocol.get_conversation_history("alice", "bob")

    assert len(messages) == 3
    assert messages[0].content == "First"
    assert messages[1].content == "Second"
    assert messages[2].content == "Third"
