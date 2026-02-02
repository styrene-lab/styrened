"""Tests for ConversationService.

Tests conversation management, message history, unread tracking,
and delivery status functionality.
"""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from styrened.models.messages import Base
from styrened.services.conversation_service import (
    ConversationInfo,
    ConversationService,
    MessageInfo,
    MessageStatus,
)


@pytest.fixture
def db_engine():
    """Create a temporary in-memory database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
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
