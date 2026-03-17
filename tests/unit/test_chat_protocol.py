"""Unit tests for ChatProtocol.

Tests the chat protocol message handling, persistence, and conversation history.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from styrened.models.messages import Base, Message
from styrened.protocols.base import LXMFMessage
from styrened.protocols.chat import ChatProtocol


class TestChatProtocolBasics:
    """Tests for ChatProtocol basic functionality."""

    @pytest.fixture
    def db_engine(self):
        """Create an in-memory SQLite database for testing."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return engine

    @pytest.fixture
    def mock_router(self) -> MagicMock:
        """Create a mock LXMF router."""
        return MagicMock()

    @pytest.fixture
    def mock_identity(self) -> MagicMock:
        """Create a mock RNS identity."""
        identity = MagicMock()
        identity.hexhash = "abc123def456789012345678901234ab"
        return identity

    @pytest.fixture
    def protocol(self, mock_router, mock_identity, db_engine) -> ChatProtocol:
        """Create a ChatProtocol instance for testing."""
        return ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=db_engine,
        )

    def test_protocol_id_is_chat(self, protocol: ChatProtocol) -> None:
        """Protocol ID should be 'chat'."""
        assert protocol.protocol_id == "chat"

    def test_can_handle_chat_message(self, protocol: ChatProtocol) -> None:
        """Should handle messages with protocol='chat' in fields."""
        message = LXMFMessage(
            source_hash="source123",
            destination_hash="dest456",
            timestamp=time.time(),
            content="Hello!",
            fields={"protocol": "chat"},
        )
        assert protocol.can_handle(message) is True

    def test_cannot_handle_other_protocol(self, protocol: ChatProtocol) -> None:
        """Should not handle messages with different protocol."""
        message = LXMFMessage(
            source_hash="source123",
            destination_hash="dest456",
            timestamp=time.time(),
            content="RPC data",
            fields={"protocol": "rpc"},
        )
        assert protocol.can_handle(message) is False

    def test_cannot_handle_no_protocol(self, protocol: ChatProtocol) -> None:
        """Should not handle messages without protocol field."""
        message = LXMFMessage(
            source_hash="source123",
            destination_hash="dest456",
            timestamp=time.time(),
            content="Plain message",
            fields={},
        )
        assert protocol.can_handle(message) is False

    def test_cannot_handle_empty_protocol(self, protocol: ChatProtocol) -> None:
        """Should not handle messages with empty protocol."""
        message = LXMFMessage(
            source_hash="source123",
            destination_hash="dest456",
            timestamp=time.time(),
            content="Plain message",
            fields={"protocol": ""},
        )
        assert protocol.can_handle(message) is False


class TestChatProtocolMessageHandling:
    """Tests for handling incoming chat messages."""

    @pytest.fixture
    def db_engine(self):
        """Create an in-memory SQLite database for testing."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return engine

    @pytest.fixture
    def mock_router(self) -> MagicMock:
        """Create a mock LXMF router."""
        return MagicMock()

    @pytest.fixture
    def mock_identity(self) -> MagicMock:
        """Create a mock RNS identity."""
        identity = MagicMock()
        identity.hexhash = "abc123def456789012345678901234ab"
        return identity

    @pytest.fixture
    def protocol(self, mock_router, mock_identity, db_engine) -> ChatProtocol:
        """Create a ChatProtocol instance for testing."""
        return ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=db_engine,
        )

    @pytest.mark.asyncio
    async def test_handle_message_saves_to_database(
        self, protocol: ChatProtocol, db_engine
    ) -> None:
        """Incoming message should be saved to database."""
        timestamp = time.time()
        message = LXMFMessage(
            source_hash="sender_hash_123",
            destination_hash="receiver_hash_456",
            timestamp=timestamp,
            content="Hello, world!",
            fields={"protocol": "chat"},
        )

        await protocol.handle_message(message)

        # Verify message was saved
        with Session(db_engine) as session:
            saved = session.query(Message).first()
            assert saved is not None
            assert saved.source_hash == "sender_hash_123"
            assert saved.destination_hash == "receiver_hash_456"
            assert saved.content == "Hello, world!"
            assert saved.protocol_id == "chat"

    @pytest.mark.asyncio
    async def test_handle_message_preserves_fields(self, protocol: ChatProtocol, db_engine) -> None:
        """Message fields should be preserved in database."""
        message = LXMFMessage(
            source_hash="sender_hash",
            destination_hash="receiver_hash",
            timestamp=time.time(),
            content="Test message",
            fields={"protocol": "chat", "custom_field": "custom_value"},
        )

        await protocol.handle_message(message)

        with Session(db_engine) as session:
            saved = session.query(Message).first()
            assert saved is not None
            fields = saved.get_fields_dict()
            assert fields.get("protocol") == "chat"
            assert fields.get("custom_field") == "custom_value"

    @pytest.mark.asyncio
    async def test_handle_multiple_messages(self, protocol: ChatProtocol, db_engine) -> None:
        """Multiple messages should all be saved."""
        for i in range(3):
            message = LXMFMessage(
                source_hash=f"sender_{i}",
                destination_hash="receiver",
                timestamp=time.time() + i,
                content=f"Message {i}",
                fields={"protocol": "chat"},
            )
            await protocol.handle_message(message)

        with Session(db_engine) as session:
            count = session.query(Message).count()
            assert count == 3


class TestChatProtocolConversationHistory:
    """Tests for conversation history retrieval."""

    @pytest.fixture
    def db_engine(self):
        """Create an in-memory SQLite database for testing."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return engine

    @pytest.fixture
    def protocol(self, db_engine) -> ChatProtocol:
        """Create a ChatProtocol instance for testing."""
        return ChatProtocol(
            router=MagicMock(),
            identity=MagicMock(),
            db_engine=db_engine,
        )

    def _add_message(
        self,
        db_engine,
        source: str,
        dest: str,
        content: str,
        timestamp: float,
        protocol_id: str = "chat",
    ) -> None:
        """Helper to add a message to the database."""
        with Session(db_engine) as session:
            msg = Message(
                source_hash=source,
                destination_hash=dest,
                content=content,
                timestamp=timestamp,
                protocol_id=protocol_id,
                status="delivered",
            )
            session.add(msg)
            session.commit()

    def test_get_conversation_history_empty(self, protocol: ChatProtocol, db_engine) -> None:
        """Empty database should return empty list."""
        history = protocol.get_conversation_history("alice", "bob")
        assert history == []

    def test_get_conversation_history_bidirectional(
        self, protocol: ChatProtocol, db_engine
    ) -> None:
        """Should return messages in both directions."""
        base_time = time.time()

        # Alice -> Bob
        self._add_message(db_engine, "alice", "bob", "Hi Bob!", base_time)
        # Bob -> Alice
        self._add_message(db_engine, "bob", "alice", "Hi Alice!", base_time + 1)
        # Alice -> Bob
        self._add_message(db_engine, "alice", "bob", "How are you?", base_time + 2)

        history = protocol.get_conversation_history("alice", "bob")

        assert len(history) == 3
        assert history[0].content == "Hi Bob!"
        assert history[1].content == "Hi Alice!"
        assert history[2].content == "How are you?"

    def test_get_conversation_history_ordered_by_timestamp(
        self, protocol: ChatProtocol, db_engine
    ) -> None:
        """Messages should be ordered by timestamp ascending."""
        base_time = time.time()

        # Add in non-chronological order
        self._add_message(db_engine, "alice", "bob", "Third", base_time + 2)
        self._add_message(db_engine, "alice", "bob", "First", base_time)
        self._add_message(db_engine, "bob", "alice", "Second", base_time + 1)

        history = protocol.get_conversation_history("alice", "bob")

        assert len(history) == 3
        assert history[0].content == "First"
        assert history[1].content == "Second"
        assert history[2].content == "Third"

    def test_get_conversation_history_excludes_other_conversations(
        self, protocol: ChatProtocol, db_engine
    ) -> None:
        """Should not include messages from other conversations."""
        base_time = time.time()

        # Alice <-> Bob conversation
        self._add_message(db_engine, "alice", "bob", "A to B", base_time)
        self._add_message(db_engine, "bob", "alice", "B to A", base_time + 1)

        # Alice <-> Carol conversation
        self._add_message(db_engine, "alice", "carol", "A to C", base_time + 2)

        # Bob <-> Carol conversation
        self._add_message(db_engine, "bob", "carol", "B to C", base_time + 3)

        history = protocol.get_conversation_history("alice", "bob")

        assert len(history) == 2
        assert all(
            (m.source_hash in ("alice", "bob") and m.destination_hash in ("alice", "bob"))
            for m in history
        )

    def test_get_conversation_history_excludes_other_protocols(
        self, protocol: ChatProtocol, db_engine
    ) -> None:
        """Should only return chat protocol messages."""
        base_time = time.time()

        # Chat messages
        self._add_message(db_engine, "alice", "bob", "Chat msg", base_time)

        # RPC message (different protocol)
        self._add_message(db_engine, "alice", "bob", "RPC data", base_time + 1, protocol_id="rpc")

        history = protocol.get_conversation_history("alice", "bob")

        assert len(history) == 1
        assert history[0].content == "Chat msg"

    def test_get_conversation_history_symmetrical(self, protocol: ChatProtocol, db_engine) -> None:
        """Order of identity args shouldn't matter."""
        base_time = time.time()

        self._add_message(db_engine, "alice", "bob", "Message 1", base_time)
        self._add_message(db_engine, "bob", "alice", "Message 2", base_time + 1)

        history_ab = protocol.get_conversation_history("alice", "bob")
        history_ba = protocol.get_conversation_history("bob", "alice")

        assert len(history_ab) == len(history_ba) == 2
        assert history_ab[0].content == history_ba[0].content


class TestChatProtocolSendMessage:
    """Tests for sending chat messages."""

    @pytest.fixture
    def db_engine(self):
        """Create an in-memory SQLite database for testing."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        return engine

    @pytest.fixture
    def mock_router(self) -> MagicMock:
        """Create a mock LXMF router."""
        return MagicMock()

    @pytest.fixture
    def mock_identity(self) -> MagicMock:
        """Create a mock RNS identity."""
        identity = MagicMock()
        identity.hexhash = "abc123def456789012345678901234ab"
        return identity

    @pytest.fixture
    def mock_node_store(self) -> MagicMock:
        """Create a mock node store."""
        store = MagicMock()
        # Default: return a valid node
        node = MagicMock()
        node.identity_hash = "12345678901234567890123456789012"
        node.lxmf_destination_hash = "abcdef1234567890abcdef1234567890"
        store.get_node_by_destination.return_value = node
        return store

    @pytest.mark.asyncio
    async def test_send_message_requires_node_store(
        self, mock_router, mock_identity, db_engine
    ) -> None:
        """Sending without node_store should raise RuntimeError."""
        protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=db_engine,
            node_store=None,  # No node store
        )

        with pytest.raises(RuntimeError, match="requires a node_store"):
            await protocol.send_message("destination", "Hello")

    @pytest.mark.asyncio
    async def test_send_message_requires_known_node(
        self, mock_router, mock_identity, db_engine, mock_node_store
    ) -> None:
        """Sending to unknown node should raise ValueError."""
        mock_node_store.get_node_by_destination.return_value = None

        protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=db_engine,
            node_store=mock_node_store,
        )

        with pytest.raises(ValueError, match="node not found"):
            await protocol.send_message("unknown_dest", "Hello")

    @pytest.mark.asyncio
    async def test_send_message_requires_lxmf_capability(
        self, mock_router, mock_identity, db_engine, mock_node_store
    ) -> None:
        """Sending to node without LXMF should raise ValueError."""
        node = MagicMock()
        node.identity_hash = "12345678901234567890123456789012"
        node.lxmf_destination_hash = None  # No LXMF
        mock_node_store.get_node_by_destination.return_value = node

        protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=db_engine,
            node_store=mock_node_store,
        )

        with pytest.raises(ValueError, match="does not have LXMF capability"):
            await protocol.send_message("dest_no_lxmf", "Hello")

    @pytest.mark.asyncio
    async def test_send_message_saves_to_database(
        self, mock_router, mock_identity, db_engine, mock_node_store
    ) -> None:
        """Sent message should be saved to database."""
        protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=db_engine,
            node_store=mock_node_store,
        )

        # Mock RNS.Identity.recall to return an identity
        with patch("styrened.protocols.chat.RNS") as mock_rns:
            mock_dest_identity = MagicMock()
            mock_rns.Identity.recall.return_value = mock_dest_identity
            mock_rns.Destination.return_value = MagicMock()
            mock_rns.Destination.OUT = 1
            mock_rns.Destination.SINGLE = 2

            with patch("styrened.protocols.chat.LXMF") as mock_lxmf:
                mock_lxmf.APP_NAME = "lxmf"
                mock_lxmf.LXMessage.return_value = MagicMock()

                await protocol.send_message("test_dest", "Hello, test!")

        # Verify saved to database
        with Session(db_engine) as session:
            saved = session.query(Message).first()
            assert saved is not None
            assert saved.content == "Hello, test!"
            assert saved.destination_hash == "test_dest"
            assert saved.protocol_id == "chat"

    @pytest.mark.asyncio
    async def test_send_message_calls_router(
        self, mock_router, mock_identity, db_engine, mock_node_store
    ) -> None:
        """Message should be sent via router."""
        protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=db_engine,
            node_store=mock_node_store,
        )

        with patch("styrened.protocols.chat.RNS") as mock_rns:
            mock_dest_identity = MagicMock()
            mock_rns.Identity.recall.return_value = mock_dest_identity
            mock_rns.Destination.return_value = MagicMock()
            mock_rns.Destination.OUT = 1
            mock_rns.Destination.SINGLE = 2

            with patch("styrened.protocols.chat.LXMF") as mock_lxmf:
                mock_lxmf.APP_NAME = "lxmf"
                mock_msg = MagicMock()
                mock_lxmf.LXMessage.return_value = mock_msg

                await protocol.send_message("test_dest", "Hello!")

                # Router should have been called
                mock_router.handle_outbound.assert_called_once_with(mock_msg)
