"""Conversation management service for LXMF chat.

Provides conversation listing, message history, unread tracking,
and delivery status management. This is the primary backend for
chat functionality in styrene-tui.

Design decisions:
- Conversations are identified by LXMF destination hash (peer's delivery address)
- Messages are stored in the existing Message model with conversation context
- Unread counts tracked per-conversation in memory, persisted via message status
- Delivery callbacks update message status in real-time
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, desc, func, or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from styrened.models.messages import Message

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class ConversationInfo:
    """Summary information about a conversation."""

    peer_hash: str  # LXMF destination hash of the peer
    display_name: str | None  # User-set name or from announce
    unread_count: int
    last_message_time: float | None
    last_message_preview: str | None
    last_message_outgoing: bool | None
    message_count: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for IPC."""
        return {
            "peer_hash": self.peer_hash,
            "display_name": self.display_name,
            "unread_count": self.unread_count,
            "last_message_time": self.last_message_time,
            "last_message_preview": self.last_message_preview,
            "last_message_outgoing": self.last_message_outgoing,
            "message_count": self.message_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationInfo":
        """Deserialize from dictionary."""
        return cls(
            peer_hash=data.get("peer_hash", ""),
            display_name=data.get("display_name"),
            unread_count=data.get("unread_count", 0),
            last_message_time=data.get("last_message_time"),
            last_message_preview=data.get("last_message_preview"),
            last_message_outgoing=data.get("last_message_outgoing"),
            message_count=data.get("message_count", 0),
        )


@dataclass
class MessageInfo:
    """Message information for IPC responses."""

    id: int
    source_hash: str
    destination_hash: str
    timestamp: float
    content: str | None
    title: str | None
    protocol: str
    status: str  # pending, sent, delivered, failed
    is_outgoing: bool
    signature_valid: bool | None = None
    transport_encrypted: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for IPC."""
        return {
            "id": self.id,
            "source_hash": self.source_hash,
            "destination_hash": self.destination_hash,
            "timestamp": self.timestamp,
            "content": self.content,
            "title": self.title,
            "protocol": self.protocol,
            "status": self.status,
            "is_outgoing": self.is_outgoing,
            "signature_valid": self.signature_valid,
            "transport_encrypted": self.transport_encrypted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MessageInfo":
        """Deserialize from dictionary."""
        return cls(
            id=data.get("id", 0),
            source_hash=data.get("source_hash", ""),
            destination_hash=data.get("destination_hash", ""),
            timestamp=data.get("timestamp", 0.0),
            content=data.get("content"),
            title=data.get("title"),
            protocol=data.get("protocol", ""),
            status=data.get("status", "pending"),
            is_outgoing=data.get("is_outgoing", False),
            signature_valid=data.get("signature_valid"),
            transport_encrypted=data.get("transport_encrypted"),
        )

    @classmethod
    def from_message(cls, msg: Message, local_identity_hash: str) -> "MessageInfo":
        """Create MessageInfo from a Message model instance.

        Args:
            msg: SQLAlchemy Message instance
            local_identity_hash: Our local identity hash to determine outgoing

        Returns:
            MessageInfo with data from the Message
        """
        fields = msg.get_fields_dict()
        return cls(
            id=msg.id,
            source_hash=msg.source_hash,
            destination_hash=msg.destination_hash,
            timestamp=msg.timestamp,
            content=msg.content,
            title=fields.get("title"),
            protocol=msg.protocol_id,
            status=msg.status,
            is_outgoing=(msg.source_hash == local_identity_hash),
            signature_valid=fields.get("signature_valid"),
            transport_encrypted=fields.get("transport_encrypted"),
        )


# Message status constants
class MessageStatus:
    """Message delivery status values."""

    PENDING = "pending"  # Created, not yet sent
    SENT = "sent"  # Sent to network, awaiting delivery confirmation
    DELIVERED = "delivered"  # Confirmed delivered to recipient
    FAILED = "failed"  # Delivery failed
    RECEIVED = "received"  # Received from peer (incoming)


@dataclass
class DeliveryTracker:
    """Tracks in-flight messages for delivery callbacks."""

    message_id: int
    lxmf_hash: bytes
    created_at: float = field(default_factory=time.time)


class ConversationService:
    """Manages conversations, message history, and delivery tracking.

    Thread-safe service for chat operations. Maintains in-memory caches
    for unread counts and pending deliveries, backed by SQLite persistence.

    Usage:
        service = ConversationService(db_engine, local_identity_hash)
        service.initialize()

        # List conversations
        convos = service.list_conversations()

        # Get message history
        messages = service.get_messages("peer_hash", limit=50)

        # Save outgoing message (returns ID for delivery tracking)
        msg_id = service.save_outgoing_message("peer_hash", "Hello!")

        # Mark conversation as read
        service.mark_read("peer_hash")
    """

    def __init__(
        self,
        db_engine: Engine,
        local_identity_hash: str,
        node_store: Any | None = None,
    ) -> None:
        """Initialize ConversationService.

        Args:
            db_engine: SQLAlchemy engine for message persistence
            local_identity_hash: Our local identity hash (for determining outgoing)
            node_store: Optional NodeStore for display name lookups
        """
        self._db_engine = db_engine
        self._local_identity_hash = local_identity_hash
        self._node_store = node_store

        # Thread safety
        self._lock = threading.Lock()

        # In-memory caches
        self._unread_counts: dict[str, int] = {}  # peer_hash -> count
        self._pending_deliveries: dict[bytes, DeliveryTracker] = {}  # lxmf_hash -> tracker

        self._initialized = False

    def initialize(self) -> None:
        """Initialize service and load unread counts from database."""
        if self._initialized:
            return

        logger.info("Initializing ConversationService")
        self._load_unread_counts()
        self._initialized = True
        logger.info(
            f"ConversationService initialized with {len(self._unread_counts)} "
            f"conversations having unread messages"
        )

    def shutdown(self) -> None:
        """Shutdown service and clear caches."""
        with self._lock:
            self._unread_counts.clear()
            self._pending_deliveries.clear()
            self._initialized = False
        logger.info("ConversationService shutdown")

    def _load_unread_counts(self) -> None:
        """Load unread counts from database on startup."""
        with Session(self._db_engine) as session:
            # Count received messages that are not marked as 'read'
            # We track unread by looking for received messages with status='received'
            # Once marked read, we update status to 'read'
            results = (
                session.query(Message.source_hash, func.count(Message.id))
                .filter(
                    Message.protocol_id == "chat",
                    Message.status == MessageStatus.RECEIVED,
                    Message.destination_hash == self._local_identity_hash,
                )
                .group_by(Message.source_hash)
                .all()
            )

            with self._lock:
                self._unread_counts = {str(source): int(count) for source, count in results}

    def list_conversations(self) -> list[ConversationInfo]:
        """List all conversations ordered by most recent message.

        Returns:
            List of ConversationInfo sorted by last_message_time descending
        """
        with Session(self._db_engine) as session:
            # Get distinct peers we've communicated with
            # A peer is either a source (incoming) or destination (outgoing)
            # We need to normalize to get the "peer_hash" for each conversation

            # Subquery to get the peer hash for each message
            # For incoming: peer is source_hash
            # For outgoing: peer is destination_hash

            # Get all chat messages involving us
            messages = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    or_(
                        Message.source_hash == self._local_identity_hash,
                        Message.destination_hash == self._local_identity_hash,
                    ),
                )
                .order_by(desc(Message.timestamp))
                .all()
            )

            # Build conversation map
            conversations: dict[str, ConversationInfo] = {}

            for msg in messages:
                # Determine peer hash
                if msg.source_hash == self._local_identity_hash:
                    peer_hash = msg.destination_hash
                    is_outgoing = True
                else:
                    peer_hash = msg.source_hash
                    is_outgoing = False

                if peer_hash not in conversations:
                    # First message for this peer (most recent due to ordering)
                    preview = msg.content[:100] if msg.content else None
                    conversations[peer_hash] = ConversationInfo(
                        peer_hash=peer_hash,
                        display_name=self._get_display_name(peer_hash),
                        unread_count=self._unread_counts.get(peer_hash, 0),
                        last_message_time=msg.timestamp,
                        last_message_preview=preview,
                        last_message_outgoing=is_outgoing,
                        message_count=1,
                    )
                else:
                    conversations[peer_hash].message_count += 1

            # Sort by last message time (most recent first)
            result = sorted(
                conversations.values(),
                key=lambda c: c.last_message_time or 0,
                reverse=True,
            )

            return result

    def get_conversation(self, peer_hash: str) -> ConversationInfo | None:
        """Get information about a specific conversation.

        Args:
            peer_hash: LXMF destination hash of the peer

        Returns:
            ConversationInfo or None if no messages exist
        """
        with Session(self._db_engine) as session:
            # Get most recent message
            last_msg = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    or_(
                        and_(
                            Message.source_hash == self._local_identity_hash,
                            Message.destination_hash == peer_hash,
                        ),
                        and_(
                            Message.source_hash == peer_hash,
                            Message.destination_hash == self._local_identity_hash,
                        ),
                    ),
                )
                .order_by(desc(Message.timestamp))
                .first()
            )

            if last_msg is None:
                return None

            # Count total messages
            count = (
                session.query(func.count(Message.id))
                .filter(
                    Message.protocol_id == "chat",
                    or_(
                        and_(
                            Message.source_hash == self._local_identity_hash,
                            Message.destination_hash == peer_hash,
                        ),
                        and_(
                            Message.source_hash == peer_hash,
                            Message.destination_hash == self._local_identity_hash,
                        ),
                    ),
                )
                .scalar()
            )

            is_outgoing = last_msg.source_hash == self._local_identity_hash
            preview = last_msg.content[:100] if last_msg.content else None

            return ConversationInfo(
                peer_hash=peer_hash,
                display_name=self._get_display_name(peer_hash),
                unread_count=self._unread_counts.get(peer_hash, 0),
                last_message_time=last_msg.timestamp,
                last_message_preview=preview,
                last_message_outgoing=is_outgoing,
                message_count=count or 0,
            )

    def get_messages(
        self,
        peer_hash: str,
        limit: int = 50,
        before_timestamp: float | None = None,
        status_filter: str | None = None,
    ) -> list[MessageInfo]:
        """Get message history for a conversation.

        Args:
            peer_hash: LXMF destination hash of the peer
            limit: Maximum messages to return
            before_timestamp: Only return messages before this time (for pagination)
            status_filter: Optional filter by status (pending, sent, delivered, failed)

        Returns:
            List of MessageInfo ordered by timestamp ascending (oldest first)
        """
        with Session(self._db_engine) as session:
            query = session.query(Message).filter(
                Message.protocol_id == "chat",
                or_(
                    and_(
                        Message.source_hash == self._local_identity_hash,
                        Message.destination_hash == peer_hash,
                    ),
                    and_(
                        Message.source_hash == peer_hash,
                        Message.destination_hash == self._local_identity_hash,
                    ),
                ),
            )

            if before_timestamp is not None:
                query = query.filter(Message.timestamp < before_timestamp)

            if status_filter is not None:
                query = query.filter(Message.status == status_filter)

            # Get most recent N, then reverse for chronological order
            messages = query.order_by(desc(Message.timestamp)).limit(limit).all()

            # Reverse to get oldest-first (chronological order)
            messages.reverse()

            return [MessageInfo.from_message(msg, self._local_identity_hash) for msg in messages]

    def save_incoming_message(
        self,
        source_hash: str,
        content: str,
        timestamp: float | None = None,
        fields: dict[str, Any] | None = None,
    ) -> int:
        """Save an incoming chat message.

        Updates unread count for the sender's conversation.

        Args:
            source_hash: LXMF destination hash of the sender
            content: Message content
            timestamp: Message timestamp (defaults to now)
            fields: Optional LXMF fields dict

        Returns:
            Database ID of saved message
        """
        if timestamp is None:
            timestamp = time.time()

        with Session(self._db_engine) as session:
            msg = Message(
                source_hash=source_hash,
                destination_hash=self._local_identity_hash,
                timestamp=timestamp,
                content=content,
                protocol_id="chat",
                status=MessageStatus.RECEIVED,
            )
            if fields:
                msg.set_fields_dict(fields)

            session.add(msg)
            session.commit()
            msg_id = msg.id

        # Update unread count
        with self._lock:
            self._unread_counts[source_hash] = self._unread_counts.get(source_hash, 0) + 1

        logger.debug(f"Saved incoming message from {source_hash[:16]}..., id={msg_id}")
        return msg_id

    def save_outgoing_message(
        self,
        destination_hash: str,
        content: str,
        timestamp: float | None = None,
        fields: dict[str, Any] | None = None,
        lxmf_hash: bytes | None = None,
    ) -> int:
        """Save an outgoing chat message.

        Args:
            destination_hash: LXMF destination hash of recipient
            content: Message content
            timestamp: Message timestamp (defaults to now)
            fields: Optional LXMF fields dict
            lxmf_hash: Optional LXMF message hash for delivery tracking

        Returns:
            Database ID of saved message
        """
        if timestamp is None:
            timestamp = time.time()

        with Session(self._db_engine) as session:
            msg = Message(
                source_hash=self._local_identity_hash,
                destination_hash=destination_hash,
                timestamp=timestamp,
                content=content,
                protocol_id="chat",
                status=MessageStatus.PENDING,
            )
            if fields:
                msg.set_fields_dict(fields)

            session.add(msg)
            session.commit()
            msg_id = msg.id

        # Track for delivery callback if lxmf_hash provided
        if lxmf_hash is not None:
            with self._lock:
                self._pending_deliveries[lxmf_hash] = DeliveryTracker(
                    message_id=msg_id,
                    lxmf_hash=lxmf_hash,
                )

        logger.debug(f"Saved outgoing message to {destination_hash[:16]}..., id={msg_id}")
        return msg_id

    def update_message_status(self, message_id: int, status: str) -> bool:
        """Update the delivery status of a message.

        Args:
            message_id: Database ID of the message
            status: New status (use MessageStatus constants)

        Returns:
            True if message was found and updated
        """
        with Session(self._db_engine) as session:
            msg = session.query(Message).filter(Message.id == message_id).first()
            if msg is None:
                return False

            msg.status = status
            session.commit()

        logger.debug(f"Updated message {message_id} status to {status}")
        return True

    def on_delivery_callback(self, lxmf_hash: bytes) -> None:
        """Handle LXMF delivery success callback.

        Args:
            lxmf_hash: Hash of the delivered LXMF message
        """
        with self._lock:
            tracker = self._pending_deliveries.pop(lxmf_hash, None)

        if tracker is not None:
            self.update_message_status(tracker.message_id, MessageStatus.DELIVERED)
            logger.info(f"Message {tracker.message_id} delivered")

    def on_failed_callback(self, lxmf_hash: bytes) -> None:
        """Handle LXMF delivery failure callback.

        Args:
            lxmf_hash: Hash of the failed LXMF message
        """
        with self._lock:
            tracker = self._pending_deliveries.pop(lxmf_hash, None)

        if tracker is not None:
            self.update_message_status(tracker.message_id, MessageStatus.FAILED)
            logger.warning(f"Message {tracker.message_id} delivery failed")

    def mark_sent(self, message_id: int) -> None:
        """Mark a message as sent (handed off to network).

        Args:
            message_id: Database ID of the message
        """
        self.update_message_status(message_id, MessageStatus.SENT)

    def mark_read(self, peer_hash: str) -> int:
        """Mark all messages in a conversation as read.

        Args:
            peer_hash: LXMF destination hash of the peer

        Returns:
            Number of messages marked as read
        """
        with Session(self._db_engine) as session:
            # Update all unread received messages from this peer
            count = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    Message.source_hash == peer_hash,
                    Message.destination_hash == self._local_identity_hash,
                    Message.status == MessageStatus.RECEIVED,
                )
                .update({Message.status: "read"})
            )
            session.commit()

        # Clear unread count
        with self._lock:
            self._unread_counts.pop(peer_hash, None)

        logger.debug(f"Marked {count} messages as read from {peer_hash[:16]}...")
        return count

    def get_unread_count(self, peer_hash: str) -> int:
        """Get unread message count for a conversation.

        Args:
            peer_hash: LXMF destination hash of the peer

        Returns:
            Number of unread messages
        """
        with self._lock:
            return self._unread_counts.get(peer_hash, 0)

    def get_total_unread_count(self) -> int:
        """Get total unread message count across all conversations.

        Returns:
            Total number of unread messages
        """
        with self._lock:
            return sum(self._unread_counts.values())

    def delete_conversation(self, peer_hash: str) -> int:
        """Delete all messages in a conversation.

        Args:
            peer_hash: LXMF destination hash of the peer

        Returns:
            Number of messages deleted
        """
        with Session(self._db_engine) as session:
            count = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    or_(
                        and_(
                            Message.source_hash == self._local_identity_hash,
                            Message.destination_hash == peer_hash,
                        ),
                        and_(
                            Message.source_hash == peer_hash,
                            Message.destination_hash == self._local_identity_hash,
                        ),
                    ),
                )
                .delete()
            )
            session.commit()

        # Clear unread count
        with self._lock:
            self._unread_counts.pop(peer_hash, None)

        logger.info(f"Deleted {count} messages in conversation with {peer_hash[:16]}...")
        return count

    def delete_message(self, message_id: int) -> bool:
        """Delete a specific message.

        Args:
            message_id: Database ID of the message

        Returns:
            True if message was found and deleted
        """
        with Session(self._db_engine) as session:
            msg = session.query(Message).filter(Message.id == message_id).first()
            if msg is None:
                return False

            # Update unread count if this was an unread received message
            if msg.status == MessageStatus.RECEIVED:
                peer_hash = msg.source_hash
                with self._lock:
                    if peer_hash in self._unread_counts:
                        self._unread_counts[peer_hash] = max(0, self._unread_counts[peer_hash] - 1)
                        if self._unread_counts[peer_hash] == 0:
                            del self._unread_counts[peer_hash]

            session.delete(msg)
            session.commit()

        logger.debug(f"Deleted message {message_id}")
        return True

    def purge_failed(self, peer_hash: str | None = None) -> int:
        """Delete all failed messages, optionally filtered by peer.

        Args:
            peer_hash: Optional peer hash to filter by

        Returns:
            Number of messages purged
        """
        with Session(self._db_engine) as session:
            query = session.query(Message).filter(
                Message.protocol_id == "chat",
                Message.status == MessageStatus.FAILED,
            )

            if peer_hash is not None:
                query = query.filter(Message.destination_hash == peer_hash)

            count = query.delete()
            session.commit()

        logger.info(f"Purged {count} failed messages")
        return count

    def _get_display_name(self, peer_hash: str) -> str | None:
        """Get display name for a peer from node store.

        Args:
            peer_hash: LXMF destination hash of the peer

        Returns:
            Display name or None if not found
        """
        if self._node_store is None:
            return None

        # Try to find by LXMF destination hash
        node = self._node_store.get_node_by_lxmf_destination(peer_hash)
        if node is not None and node.name:
            name: str = node.name
            return name

        return None
