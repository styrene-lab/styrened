"""Tests for ConversationService.

Tests conversation management, message history, unread tracking,
and delivery status functionality.
"""

import tempfile
from unittest.mock import MagicMock

import pytest

from styrened.models.messages import init_db
from styrened.services.conversation_service import (
    ConversationInfo,
    ConversationService,
    MessageInfo,
    MessageStatus,
)


@pytest.fixture
def db_engine():
    """Create a temporary database for testing with FTS5 support."""
    # Use a temp file instead of :memory: because init_db needs a path
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = init_db(db_path)
    return engine


@pytest.fixture
def local_identity_hash():
    """Local identity hash for testing."""
    return "a" * 32  # 32 hex chars


@pytest.fixture
def peer_hash():
    """Peer identity hash for testing."""
    return "b" * 32  # 32 hex chars


@pytest.fixture
def conversation_service(db_engine, local_identity_hash):
    """Create a ConversationService instance for testing."""
    service = ConversationService(
        db_engine=db_engine,
        local_identity_hash=local_identity_hash,
        node_store=None,
    )
    service.initialize()
    yield service
    service.shutdown()


class TestConversationServiceInitialization:
    """Tests for service initialization and shutdown."""

    def test_initialize_creates_empty_unread_counts(self, db_engine, local_identity_hash):
        """Test that initialization creates empty unread counts."""
        service = ConversationService(db_engine, local_identity_hash)
        service.initialize()

        assert service._unread_counts == {}
        service.shutdown()

    def test_double_initialize_is_safe(self, db_engine, local_identity_hash):
        """Test that calling initialize twice is safe."""
        service = ConversationService(db_engine, local_identity_hash)
        service.initialize()
        service.initialize()  # Should not raise

        assert service._initialized
        service.shutdown()

    def test_shutdown_clears_state(self, db_engine, local_identity_hash):
        """Test that shutdown clears caches."""
        service = ConversationService(db_engine, local_identity_hash)
        service.initialize()
        service._unread_counts["test"] = 5
        service._pending_deliveries[b"test"] = MagicMock()

        service.shutdown()

        assert service._unread_counts == {}
        assert service._pending_deliveries == {}
        assert not service._initialized


class TestMessagePersistence:
    """Tests for saving and retrieving messages."""

    def test_save_incoming_message(self, conversation_service, peer_hash):
        """Test saving an incoming message."""
        msg_id = conversation_service.save_incoming_message(
            source_hash=peer_hash,
            content="Hello!",
        )

        assert msg_id > 0

    def test_save_incoming_message_increments_unread(self, conversation_service, peer_hash):
        """Test that incoming messages increment unread count."""
        conversation_service.save_incoming_message(peer_hash, "Message 1")
        conversation_service.save_incoming_message(peer_hash, "Message 2")

        assert conversation_service.get_unread_count(peer_hash) == 2

    def test_save_outgoing_message(self, conversation_service, peer_hash):
        """Test saving an outgoing message."""
        msg_id = conversation_service.save_outgoing_message(
            destination_hash=peer_hash,
            content="Hi there!",
        )

        assert msg_id > 0

    def test_save_outgoing_message_does_not_increment_unread(self, conversation_service, peer_hash):
        """Test that outgoing messages don't increment unread count."""
        conversation_service.save_outgoing_message(peer_hash, "Message 1")

        assert conversation_service.get_unread_count(peer_hash) == 0

    def test_save_message_with_timestamp(self, conversation_service, peer_hash):
        """Test saving a message with explicit timestamp."""
        timestamp = 1234567890.0
        conversation_service.save_incoming_message(
            source_hash=peer_hash,
            content="Test",
            timestamp=timestamp,
        )

        messages = conversation_service.get_messages(peer_hash, limit=1)
        assert len(messages) == 1
        assert messages[0].timestamp == timestamp

    def test_save_message_with_fields(self, conversation_service, peer_hash):
        """Test saving a message with LXMF fields."""
        fields = {"protocol": "chat", "title": "Test Title"}
        conversation_service.save_incoming_message(
            source_hash=peer_hash,
            content="Test",
            fields=fields,
        )

        messages = conversation_service.get_messages(peer_hash, limit=1)
        assert len(messages) == 1
        assert messages[0].title == "Test Title"

    def test_save_incoming_message_with_native_title(self, conversation_service, peer_hash):
        """Test saving an incoming message with native title column."""
        msg_id = conversation_service.save_incoming_message(
            source_hash=peer_hash,
            content="Hello!",
            title="Important Message",
        )

        messages = conversation_service.get_messages(peer_hash, limit=1)
        assert len(messages) == 1
        assert messages[0].title == "Important Message"
        assert messages[0].id == msg_id

    def test_save_outgoing_message_with_native_title(self, conversation_service, peer_hash):
        """Test saving an outgoing message with native title column."""
        msg_id = conversation_service.save_outgoing_message(
            destination_hash=peer_hash,
            content="Hello!",
            title="Outgoing Title",
        )

        messages = conversation_service.get_messages(peer_hash, limit=1)
        assert len(messages) == 1
        assert messages[0].title == "Outgoing Title"
        assert messages[0].id == msg_id

    def test_native_title_takes_precedence_over_fields_title(self, conversation_service, peer_hash):
        """Test that native title column takes precedence over fields dict title."""
        # When both native title and fields title exist, native should win
        conversation_service.save_incoming_message(
            source_hash=peer_hash,
            content="Test",
            title="Native Title",
            fields={"protocol": "chat", "title": "Fields Title"},
        )

        messages = conversation_service.get_messages(peer_hash, limit=1)
        assert len(messages) == 1
        assert messages[0].title == "Native Title"

    def test_fields_title_fallback_when_no_native_title(self, conversation_service, peer_hash):
        """Test that fields title is used when native title is None."""
        # When only fields title exists, should fall back to it
        conversation_service.save_incoming_message(
            source_hash=peer_hash,
            content="Test",
            title=None,  # No native title
            fields={"protocol": "chat", "title": "Fields Title"},
        )

        messages = conversation_service.get_messages(peer_hash, limit=1)
        assert len(messages) == 1
        assert messages[0].title == "Fields Title"


class TestMessageRetrieval:
    """Tests for retrieving message history."""

    def test_get_messages_empty(self, conversation_service, peer_hash):
        """Test getting messages from empty conversation."""
        messages = conversation_service.get_messages(peer_hash)

        assert messages == []

    def test_get_messages_returns_chronological_order(
        self, conversation_service, local_identity_hash, peer_hash
    ):
        """Test that messages are returned in chronological order."""
        # Save messages with explicit timestamps
        conversation_service.save_incoming_message(peer_hash, "First", timestamp=1000.0)
        conversation_service.save_outgoing_message(peer_hash, "Second", timestamp=2000.0)
        conversation_service.save_incoming_message(peer_hash, "Third", timestamp=3000.0)

        messages = conversation_service.get_messages(peer_hash)

        assert len(messages) == 3
        assert messages[0].content == "First"
        assert messages[1].content == "Second"
        assert messages[2].content == "Third"

    def test_get_messages_respects_limit(self, conversation_service, peer_hash):
        """Test that limit parameter works."""
        for i in range(10):
            conversation_service.save_incoming_message(
                peer_hash, f"Message {i}", timestamp=float(i)
            )

        messages = conversation_service.get_messages(peer_hash, limit=3)

        # Should get the 3 most recent, but in chronological order
        assert len(messages) == 3
        assert messages[0].content == "Message 7"
        assert messages[1].content == "Message 8"
        assert messages[2].content == "Message 9"

    def test_get_messages_with_before_timestamp(self, conversation_service, peer_hash):
        """Test pagination with before_timestamp."""
        for i in range(10):
            conversation_service.save_incoming_message(
                peer_hash, f"Message {i}", timestamp=float(i * 1000)
            )

        # Get messages before timestamp 5000 (i.e., messages 0-4)
        messages = conversation_service.get_messages(peer_hash, limit=10, before_timestamp=5000.0)

        assert len(messages) == 5
        assert messages[-1].content == "Message 4"

    def test_get_messages_with_status_filter(self, conversation_service, peer_hash):
        """Test filtering by status."""
        conversation_service.save_incoming_message(peer_hash, "Received")
        msg_id = conversation_service.save_outgoing_message(peer_hash, "Pending")
        conversation_service.update_message_status(msg_id, MessageStatus.FAILED)

        messages = conversation_service.get_messages(peer_hash, status_filter=MessageStatus.FAILED)

        assert len(messages) == 1
        assert messages[0].content == "Pending"

    def test_get_messages_identifies_outgoing(
        self, conversation_service, local_identity_hash, peer_hash
    ):
        """Test that is_outgoing is correctly set."""
        conversation_service.save_incoming_message(peer_hash, "Incoming")
        conversation_service.save_outgoing_message(peer_hash, "Outgoing")

        messages = conversation_service.get_messages(peer_hash)

        assert len(messages) == 2
        incoming = next(m for m in messages if m.content == "Incoming")
        outgoing = next(m for m in messages if m.content == "Outgoing")

        assert not incoming.is_outgoing
        assert outgoing.is_outgoing


class TestConversationListing:
    """Tests for listing conversations."""

    def test_list_conversations_empty(self, conversation_service):
        """Test listing with no conversations."""
        convos = conversation_service.list_conversations()

        assert convos == []

    def test_list_conversations_returns_all(self, conversation_service):
        """Test that all conversations are returned."""
        peer1 = "1" * 32
        peer2 = "2" * 32
        peer3 = "3" * 32

        conversation_service.save_incoming_message(peer1, "From peer 1")
        conversation_service.save_incoming_message(peer2, "From peer 2")
        conversation_service.save_outgoing_message(peer3, "To peer 3")

        convos = conversation_service.list_conversations()

        assert len(convos) == 3
        peer_hashes = {c.peer_hash for c in convos}
        assert peer_hashes == {peer1, peer2, peer3}

    def test_list_conversations_ordered_by_recency(self, conversation_service):
        """Test that conversations are ordered by most recent message."""
        peer1 = "1" * 32
        peer2 = "2" * 32

        conversation_service.save_incoming_message(peer1, "Old", timestamp=1000.0)
        conversation_service.save_incoming_message(peer2, "New", timestamp=2000.0)

        convos = conversation_service.list_conversations()

        assert len(convos) == 2
        assert convos[0].peer_hash == peer2  # Most recent first
        assert convos[1].peer_hash == peer1

    def test_list_conversations_includes_unread_count(self, conversation_service, peer_hash):
        """Test that unread count is included."""
        conversation_service.save_incoming_message(peer_hash, "Msg 1")
        conversation_service.save_incoming_message(peer_hash, "Msg 2")

        convos = conversation_service.list_conversations()

        assert len(convos) == 1
        assert convos[0].unread_count == 2

    def test_list_conversations_includes_message_count(self, conversation_service, peer_hash):
        """Test that total message count is included."""
        conversation_service.save_incoming_message(peer_hash, "Incoming")
        conversation_service.save_outgoing_message(peer_hash, "Outgoing")

        convos = conversation_service.list_conversations()

        assert len(convos) == 1
        assert convos[0].message_count == 2

    def test_list_conversations_includes_preview(self, conversation_service, peer_hash):
        """Test that last message preview is included."""
        conversation_service.save_incoming_message(peer_hash, "First", timestamp=1000.0)
        conversation_service.save_outgoing_message(peer_hash, "Last message", timestamp=2000.0)

        convos = conversation_service.list_conversations()

        assert len(convos) == 1
        assert convos[0].last_message_preview == "Last message"
        assert convos[0].last_message_outgoing is True

    def test_get_conversation_returns_none_for_unknown(self, conversation_service):
        """Test that getting unknown conversation returns None."""
        result = conversation_service.get_conversation("unknown" * 4)  # 32 chars

        assert result is None


class TestUnreadTracking:
    """Tests for unread message tracking."""

    def test_mark_read_clears_unread_count(self, conversation_service, peer_hash):
        """Test that mark_read clears unread count."""
        conversation_service.save_incoming_message(peer_hash, "Msg 1")
        conversation_service.save_incoming_message(peer_hash, "Msg 2")

        count = conversation_service.mark_read(peer_hash)

        assert count == 2
        assert conversation_service.get_unread_count(peer_hash) == 0

    def test_mark_read_returns_zero_when_no_unread(self, conversation_service, peer_hash):
        """Test mark_read when no unread messages."""
        conversation_service.save_outgoing_message(peer_hash, "Outgoing")

        count = conversation_service.mark_read(peer_hash)

        assert count == 0

    def test_get_total_unread_count(self, conversation_service):
        """Test getting total unread count across conversations."""
        peer1 = "1" * 32
        peer2 = "2" * 32

        conversation_service.save_incoming_message(peer1, "Msg 1")
        conversation_service.save_incoming_message(peer1, "Msg 2")
        conversation_service.save_incoming_message(peer2, "Msg 3")

        total = conversation_service.get_total_unread_count()

        assert total == 3


class TestMessageDeletion:
    """Tests for deleting messages and conversations."""

    def test_delete_message(self, conversation_service, peer_hash):
        """Test deleting a single message."""
        msg_id = conversation_service.save_incoming_message(peer_hash, "To delete")

        deleted = conversation_service.delete_message(msg_id)

        assert deleted is True
        assert conversation_service.get_messages(peer_hash) == []

    def test_delete_message_not_found(self, conversation_service):
        """Test deleting non-existent message."""
        deleted = conversation_service.delete_message(99999)

        assert deleted is False

    def test_delete_message_updates_unread_count(self, conversation_service, peer_hash):
        """Test that deleting unread message updates count."""
        msg_id = conversation_service.save_incoming_message(peer_hash, "Unread")
        assert conversation_service.get_unread_count(peer_hash) == 1

        conversation_service.delete_message(msg_id)

        assert conversation_service.get_unread_count(peer_hash) == 0

    def test_delete_conversation(self, conversation_service, peer_hash):
        """Test deleting all messages in a conversation."""
        conversation_service.save_incoming_message(peer_hash, "Msg 1")
        conversation_service.save_outgoing_message(peer_hash, "Msg 2")

        count = conversation_service.delete_conversation(peer_hash)

        assert count == 2
        assert conversation_service.get_messages(peer_hash) == []

    def test_delete_conversation_clears_unread(self, conversation_service, peer_hash):
        """Test that deleting conversation clears unread count."""
        conversation_service.save_incoming_message(peer_hash, "Unread")

        conversation_service.delete_conversation(peer_hash)

        assert conversation_service.get_unread_count(peer_hash) == 0

    def test_purge_failed_messages(self, conversation_service, peer_hash):
        """Test purging failed messages."""
        msg_id = conversation_service.save_outgoing_message(peer_hash, "Failed")
        conversation_service.update_message_status(msg_id, MessageStatus.FAILED)

        count = conversation_service.purge_failed()

        assert count == 1
        assert conversation_service.get_messages(peer_hash) == []


class TestDeliveryTracking:
    """Tests for delivery status tracking."""

    def test_update_message_status(self, conversation_service, peer_hash):
        """Test updating message status."""
        msg_id = conversation_service.save_outgoing_message(peer_hash, "Test")

        result = conversation_service.update_message_status(msg_id, MessageStatus.DELIVERED)

        assert result is True
        messages = conversation_service.get_messages(peer_hash)
        assert messages[0].status == MessageStatus.DELIVERED

    def test_mark_sent(self, conversation_service, peer_hash):
        """Test marking message as sent."""
        msg_id = conversation_service.save_outgoing_message(peer_hash, "Test")

        conversation_service.mark_sent(msg_id)

        messages = conversation_service.get_messages(peer_hash)
        assert messages[0].status == MessageStatus.SENT

    def test_delivery_callback(self, conversation_service, peer_hash):
        """Test delivery callback updates status."""
        lxmf_hash = b"test_hash_12345"
        conversation_service.save_outgoing_message(peer_hash, "Test", lxmf_hash=lxmf_hash)

        conversation_service.on_delivery_callback(lxmf_hash)

        messages = conversation_service.get_messages(peer_hash)
        assert messages[0].status == MessageStatus.DELIVERED

    def test_failed_callback(self, conversation_service, peer_hash):
        """Test failed callback updates status."""
        lxmf_hash = b"test_hash_12345"
        conversation_service.save_outgoing_message(peer_hash, "Test", lxmf_hash=lxmf_hash)

        conversation_service.on_failed_callback(lxmf_hash)

        messages = conversation_service.get_messages(peer_hash)
        assert messages[0].status == MessageStatus.FAILED

    def test_callback_removes_from_pending(self, conversation_service, peer_hash):
        """Test that callbacks remove message from pending tracking."""
        lxmf_hash = b"test_hash_12345"
        conversation_service.save_outgoing_message(peer_hash, "Test", lxmf_hash=lxmf_hash)

        assert lxmf_hash in conversation_service._pending_deliveries

        conversation_service.on_delivery_callback(lxmf_hash)

        assert lxmf_hash not in conversation_service._pending_deliveries

    def test_update_destination_hash(self, conversation_service, peer_hash):
        """Test updating destination_hash normalizes truncated hashes."""
        # Save with truncated hash (simulates what IPC receives from user)
        truncated_hash = peer_hash[:16]
        msg_id = conversation_service.save_outgoing_message(truncated_hash, "Test")

        # Update to full hash (simulates LXMF resolution)
        full_hash = "c" * 32
        result = conversation_service.update_destination_hash(msg_id, full_hash)

        assert result is True
        # Get messages using the new full hash
        messages = conversation_service.get_messages(full_hash)
        assert len(messages) == 1
        assert messages[0].content == "Test"

    def test_update_destination_hash_not_found(self, conversation_service):
        """Test update_destination_hash returns False for nonexistent message."""
        result = conversation_service.update_destination_hash(99999, "c" * 32)
        assert result is False


class TestDataClasses:
    """Tests for ConversationInfo and MessageInfo dataclasses."""

    def test_conversation_info_to_dict(self):
        """Test ConversationInfo serialization."""
        info = ConversationInfo(
            peer_hash="a" * 32,
            display_name="Test User",
            unread_count=5,
            last_message_time=1234567890.0,
            last_message_preview="Hello",
            last_message_outgoing=True,
            message_count=10,
        )

        d = info.to_dict()

        assert d["peer_hash"] == "a" * 32
        assert d["display_name"] == "Test User"
        assert d["unread_count"] == 5
        assert d["message_count"] == 10

    def test_conversation_info_from_dict(self):
        """Test ConversationInfo deserialization."""
        d = {
            "peer_hash": "b" * 32,
            "display_name": "Other User",
            "unread_count": 3,
            "last_message_time": 1234567890.0,
            "last_message_preview": "Hi",
            "last_message_outgoing": False,
            "message_count": 5,
        }

        info = ConversationInfo.from_dict(d)

        assert info.peer_hash == "b" * 32
        assert info.display_name == "Other User"
        assert info.unread_count == 3

    def test_message_info_to_dict(self):
        """Test MessageInfo serialization."""
        info = MessageInfo(
            id=1,
            source_hash="a" * 32,
            destination_hash="b" * 32,
            timestamp=1234567890.0,
            content="Test message",
            title=None,
            protocol="chat",
            status="delivered",
            is_outgoing=True,
        )

        d = info.to_dict()

        assert d["id"] == 1
        assert d["content"] == "Test message"
        assert d["status"] == "delivered"
        assert d["is_outgoing"] is True

    def test_message_info_from_dict(self):
        """Test MessageInfo deserialization."""
        d = {
            "id": 2,
            "source_hash": "a" * 32,
            "destination_hash": "b" * 32,
            "timestamp": 1234567890.0,
            "content": "Another message",
            "title": "Title",
            "protocol": "chat",
            "status": "sent",
            "is_outgoing": False,
        }

        info = MessageInfo.from_dict(d)

        assert info.id == 2
        assert info.content == "Another message"
        assert info.title == "Title"
        assert info.status == "sent"


class TestMessageSearch:
    """Tests for full-text search functionality."""

    def test_search_messages_basic(self, conversation_service, peer_hash):
        """Test basic full-text search finds matching messages."""
        conversation_service.save_incoming_message(peer_hash, "Hello world")
        conversation_service.save_incoming_message(peer_hash, "Goodbye moon")
        conversation_service.save_incoming_message(peer_hash, "Hello again")

        results = conversation_service.search_messages("hello")

        assert len(results) == 2
        contents = {r.content for r in results}
        assert "Hello world" in contents
        assert "Hello again" in contents

    def test_search_messages_no_results(self, conversation_service, peer_hash):
        """Test search returns empty list when no matches."""
        conversation_service.save_incoming_message(peer_hash, "Hello world")

        results = conversation_service.search_messages("nonexistent")

        assert results == []

    def test_search_messages_by_peer(self, conversation_service):
        """Test search can filter by peer hash."""
        peer1 = "1" * 32
        peer2 = "2" * 32

        conversation_service.save_incoming_message(peer1, "Hello from peer 1")
        conversation_service.save_incoming_message(peer2, "Hello from peer 2")

        results = conversation_service.search_messages("hello", peer_hash=peer1)

        assert len(results) == 1
        assert results[0].content == "Hello from peer 1"

    def test_search_messages_respects_limit(self, conversation_service, peer_hash):
        """Test search respects limit parameter."""
        for i in range(10):
            conversation_service.save_incoming_message(peer_hash, f"Test message {i}")

        results = conversation_service.search_messages("test", limit=3)

        assert len(results) == 3

    def test_search_messages_returns_most_recent_first(self, conversation_service, peer_hash):
        """Test search returns results ordered by most recent first."""
        conversation_service.save_incoming_message(peer_hash, "Test old", timestamp=1000.0)
        conversation_service.save_incoming_message(peer_hash, "Test new", timestamp=2000.0)

        results = conversation_service.search_messages("test")

        assert len(results) == 2
        assert results[0].content == "Test new"  # Most recent first
        assert results[1].content == "Test old"

    def test_search_messages_searches_title(self, conversation_service, peer_hash):
        """Test search includes message titles."""
        conversation_service.save_incoming_message(
            peer_hash, "Some content", title="Important announcement"
        )
        conversation_service.save_incoming_message(
            peer_hash, "Other content", title="Regular message"
        )

        results = conversation_service.search_messages("important")

        assert len(results) == 1
        assert results[0].title == "Important announcement"

    def test_search_messages_fts_syntax_and(self, conversation_service, peer_hash):
        """Test FTS5 AND syntax works."""
        conversation_service.save_incoming_message(peer_hash, "Hello beautiful world")
        conversation_service.save_incoming_message(peer_hash, "Hello universe")
        conversation_service.save_incoming_message(peer_hash, "Goodbye world")

        # Search for messages containing both "hello" AND "world"
        results = conversation_service.search_messages("hello world")

        assert len(results) == 1
        assert results[0].content == "Hello beautiful world"

    def test_search_messages_only_chat_protocol(self, conversation_service, peer_hash):
        """Test search only returns chat protocol messages."""
        # Save a chat message
        conversation_service.save_incoming_message(peer_hash, "Chat message")

        # Save a non-chat message directly (simulating other protocol)
        from sqlalchemy.orm import Session

        from styrened.models.messages import Message

        with Session(conversation_service._db_engine) as session:
            msg = Message(
                source_hash=peer_hash,
                destination_hash=conversation_service._local_identity_hash,
                timestamp=1000.0,
                content="RPC message",
                protocol_id="rpc",  # Not chat
                status="received",
            )
            session.add(msg)
            session.commit()

        # Search should only find chat messages
        results = conversation_service.search_messages("message")

        assert len(results) == 1
        assert results[0].content == "Chat message"


class TestReadReceipts:
    """Tests for read receipt tracking functionality."""

    def test_mark_read_by_recipient(self, conversation_service, peer_hash):
        """Test marking an outgoing message as read by recipient."""
        # Create outgoing message with lxmf_hash (bytes)
        lxmf_hash = b"test_hash_1234"
        conversation_service.save_outgoing_message(peer_hash, "Hello", lxmf_hash=lxmf_hash)

        # The hash is stored as hex, so we need to use the hex version
        result = conversation_service.mark_read_by_recipient(
            lxmf_hash=lxmf_hash.hex(),
            read_at=1234567890.0,
        )

        assert result is True

    def test_mark_read_by_recipient_already_read(self, conversation_service, peer_hash):
        """Test that marking already-read message returns False."""
        lxmf_hash = b"test_hash_1234"
        conversation_service.save_outgoing_message(peer_hash, "Hello", lxmf_hash=lxmf_hash)

        # Mark as read first time
        result1 = conversation_service.mark_read_by_recipient(
            lxmf_hash=lxmf_hash.hex(),
            read_at=1234567890.0,
        )
        assert result1 is True

        # Mark as read second time
        result2 = conversation_service.mark_read_by_recipient(
            lxmf_hash=lxmf_hash.hex(),
            read_at=1234567891.0,
        )
        assert result2 is False  # Already marked

    def test_mark_read_by_recipient_unknown_hash(self, conversation_service):
        """Test marking unknown message returns False."""
        result = conversation_service.mark_read_by_recipient(
            lxmf_hash="nonexistent_hash",
            read_at=1234567890.0,
        )
        assert result is False

    def test_get_unread_hashes_for_receipt(self, conversation_service, peer_hash):
        """Test getting hashes for messages needing receipts."""
        # Create incoming messages with hashes
        hash1 = b"hash_1"
        hash2 = b"hash_2"

        conversation_service.save_incoming_message(peer_hash, "Msg 1", lxmf_hash=hash1)
        conversation_service.save_incoming_message(peer_hash, "Msg 2", lxmf_hash=hash2)

        # Mark conversation as read
        conversation_service.mark_read(peer_hash)

        # Get hashes for receipt
        hashes = conversation_service.get_unread_hashes_for_receipt(peer_hash)

        assert len(hashes) == 2
        assert hash1.hex() in hashes
        assert hash2.hex() in hashes

    def test_get_unread_hashes_excludes_sent_receipts(self, conversation_service, peer_hash):
        """Test that already-receipted messages are excluded."""
        hash1 = b"hash_1"
        hash2 = b"hash_2"

        conversation_service.save_incoming_message(peer_hash, "Msg 1", lxmf_hash=hash1)
        conversation_service.save_incoming_message(peer_hash, "Msg 2", lxmf_hash=hash2)

        # Mark as read
        conversation_service.mark_read(peer_hash)

        # Mark one as having receipt sent
        conversation_service.mark_receipts_sent([hash1.hex()])

        # Get hashes - should only get hash2
        hashes = conversation_service.get_unread_hashes_for_receipt(peer_hash)

        assert len(hashes) == 1
        assert hash2.hex() in hashes
        assert hash1.hex() not in hashes

    def test_get_unread_hashes_excludes_unread(self, conversation_service, peer_hash):
        """Test that unread messages are not included."""
        hash1 = b"hash_1"

        conversation_service.save_incoming_message(peer_hash, "Msg 1", lxmf_hash=hash1)

        # Don't mark as read

        # Should get empty list (messages not read yet)
        hashes = conversation_service.get_unread_hashes_for_receipt(peer_hash)

        assert hashes == []

    def test_mark_receipts_sent(self, conversation_service, peer_hash):
        """Test marking messages as having receipts sent."""
        hash1 = b"hash_1"
        hash2 = b"hash_2"

        conversation_service.save_incoming_message(peer_hash, "Msg 1", lxmf_hash=hash1)
        conversation_service.save_incoming_message(peer_hash, "Msg 2", lxmf_hash=hash2)

        # Mark receipts as sent
        count = conversation_service.mark_receipts_sent([hash1.hex(), hash2.hex()])

        assert count == 2

    def test_mark_receipts_sent_empty_list(self, conversation_service):
        """Test marking empty list returns 0."""
        count = conversation_service.mark_receipts_sent([])
        assert count == 0


class TestStaleDeliveryCleanup:
    """Tests for cleanup_stale_deliveries functionality."""

    def test_cleanup_removes_stale_trackers(self, conversation_service, peer_hash):
        """Test that cleanup removes trackers older than max_age."""
        import time

        from styrened.services.conversation_service import DeliveryTracker

        # Save a message and create a tracker
        msg_id = conversation_service.save_outgoing_message(peer_hash, "Test message")

        # Manually add a stale tracker (bypassing normal flow)
        stale_hash = b"stale_hash_12345"
        with conversation_service._lock:
            conversation_service._pending_deliveries[stale_hash] = DeliveryTracker(
                message_id=msg_id,
                lxmf_hash=stale_hash,
                created_at=time.time() - 7200,  # 2 hours ago
            )

        # Should have one tracker
        assert len(conversation_service._pending_deliveries) == 1

        # Cleanup with 1 hour max age
        removed = conversation_service.cleanup_stale_deliveries(max_age=3600.0)

        assert removed == 1
        assert len(conversation_service._pending_deliveries) == 0

    def test_cleanup_keeps_fresh_trackers(self, conversation_service, peer_hash):
        """Test that cleanup keeps trackers newer than max_age."""
        import time

        from styrened.services.conversation_service import DeliveryTracker

        msg_id = conversation_service.save_outgoing_message(peer_hash, "Test message")

        # Manually add a fresh tracker
        fresh_hash = b"fresh_hash_12345"
        with conversation_service._lock:
            conversation_service._pending_deliveries[fresh_hash] = DeliveryTracker(
                message_id=msg_id,
                lxmf_hash=fresh_hash,
                created_at=time.time() - 60,  # 1 minute ago
            )

        # Cleanup with 1 hour max age
        removed = conversation_service.cleanup_stale_deliveries(max_age=3600.0)

        assert removed == 0
        assert len(conversation_service._pending_deliveries) == 1

    def test_cleanup_handles_empty_deliveries(self, conversation_service):
        """Test cleanup with no pending deliveries."""
        removed = conversation_service.cleanup_stale_deliveries()
        assert removed == 0
