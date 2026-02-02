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
    delivery_method: str | None = None  # "direct", "propagated", or None
    delivery_attempts: int = 0
    lxmf_hash: str | None = None  # hex-encoded LXMF message hash
    # Attachment fields for ecosystem compatibility
    has_attachment: bool = False
    attachment_type: str | None = None  # "image", "audio", "file"
    attachment_name: str | None = None
    attachment_size: int | None = None
    attachment_mime: str | None = None
    # Threading fields (LXMF FIELD_THREAD)
    thread_id: str | None = None
    reply_to_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for IPC."""
        result = {
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
            "delivery_method": self.delivery_method,
            "delivery_attempts": self.delivery_attempts,
            "lxmf_hash": self.lxmf_hash,
            "has_attachment": self.has_attachment,
            "thread_id": self.thread_id,
            "reply_to_hash": self.reply_to_hash,
        }
        # Only include attachment fields if there's an attachment
        if self.has_attachment:
            result["attachment_type"] = self.attachment_type
            result["attachment_name"] = self.attachment_name
            result["attachment_size"] = self.attachment_size
            result["attachment_mime"] = self.attachment_mime
        return result

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
            delivery_method=data.get("delivery_method"),
            delivery_attempts=data.get("delivery_attempts", 0),
            lxmf_hash=data.get("lxmf_hash"),
            has_attachment=data.get("has_attachment", False),
            attachment_type=data.get("attachment_type"),
            attachment_name=data.get("attachment_name"),
            attachment_size=data.get("attachment_size"),
            attachment_mime=data.get("attachment_mime"),
            thread_id=data.get("thread_id"),
            reply_to_hash=data.get("reply_to_hash"),
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

        # Read from Message columns first, fall back to fields dict for backward compatibility
        signature_valid = msg.signature_valid
        if signature_valid is None:
            signature_valid = fields.get("signature_valid")

        transport_encrypted = msg.transport_encrypted
        if transport_encrypted is None:
            transport_encrypted = fields.get("transport_encrypted")

        # Read title from column first, fall back to fields dict for backward compatibility
        title = msg.title if msg.title else fields.get("title")

        return cls(
            id=msg.id,
            source_hash=msg.source_hash,
            destination_hash=msg.destination_hash,
            timestamp=msg.timestamp,
            content=msg.content,
            title=title,
            protocol=msg.protocol_id,
            status=msg.status,
            is_outgoing=(msg.source_hash == local_identity_hash),
            signature_valid=signature_valid,
            transport_encrypted=transport_encrypted,
            delivery_method=msg.delivery_method,
            delivery_attempts=msg.delivery_attempts or 0,
            lxmf_hash=msg.lxmf_hash,
            has_attachment=msg.has_attachment or False,
            attachment_type=msg.attachment_type,
            attachment_name=msg.attachment_name,
            attachment_size=msg.attachment_size,
            attachment_mime=msg.attachment_mime,
            thread_id=msg.thread_id,
            reply_to_hash=msg.reply_to_hash,
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
        service = ConversationService(db_engine, local_lxmf_hash)
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
            local_identity_hash: Our local LXMF destination hash (hexhash).
                NOTE: Despite the name, this is the LXMF delivery destination hash,
                NOT the RNS identity hash. LXMF messages use destination hashes
                for source/dest identification in message.source_hash/destination_hash.
            node_store: Optional NodeStore for display name lookups
        """
        self._db_engine = db_engine
        self._local_identity_hash = local_identity_hash  # Actually LXMF dest hash
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

    def cleanup_stale_deliveries(self, max_age: float = 3600.0) -> int:
        """Remove delivery trackers older than max_age seconds.

        This prevents memory leaks when LXMF callbacks never fire (e.g., network
        partitions, process crashes, or library bugs). Messages in pending_deliveries
        that exceed max_age are assumed to have failed silently.

        Args:
            max_age: Maximum age in seconds before a tracker is considered stale.
                     Default is 1 hour (3600 seconds).

        Returns:
            Number of stale trackers removed.
        """
        cutoff = time.time() - max_age
        removed = 0

        with self._lock:
            stale_hashes = [
                h for h, tracker in self._pending_deliveries.items() if tracker.created_at < cutoff
            ]
            for h in stale_hashes:
                tracker = self._pending_deliveries.pop(h)
                removed += 1
                logger.warning(
                    f"Removed stale delivery tracker for message {tracker.message_id} "
                    f"(age > {max_age}s)"
                )

        # Mark stale messages as failed in database
        if removed > 0:
            logger.info(f"Cleaned up {removed} stale delivery tracker(s)")

        return removed

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

    def search_messages(
        self,
        query: str,
        peer_hash: str | None = None,
        limit: int = 50,
    ) -> list[MessageInfo]:
        """Search messages using full-text search.

        Uses SQLite FTS5 for efficient content and title searching.
        Supports FTS5 query syntax including AND, OR, NOT, and phrases.

        Args:
            query: FTS5 search query (e.g., "hello", "hello world", "hello OR goodbye")
            peer_hash: Optional filter to specific conversation
            limit: Maximum results to return

        Returns:
            List of matching messages, most recent first
        """
        from sqlalchemy import text

        with Session(self._db_engine) as session:
            # Build FTS query joining with messages table
            sql = """
                SELECT m.id FROM messages m
                JOIN messages_fts fts ON m.id = fts.rowid
                WHERE messages_fts MATCH :query
                AND m.protocol_id = 'chat'
            """
            params: dict[str, Any] = {"query": query, "limit": limit}

            if peer_hash:
                sql += " AND (m.source_hash = :peer OR m.destination_hash = :peer)"
                params["peer"] = peer_hash

            sql += " ORDER BY m.timestamp DESC LIMIT :limit"

            result = session.execute(text(sql), params)
            message_ids = [row[0] for row in result]

            # Fetch full Message objects
            messages = []
            for msg_id in message_ids:
                msg = session.get(Message, msg_id)
                if msg:
                    messages.append(MessageInfo.from_message(msg, self._local_identity_hash))

            return messages

    def save_incoming_message(
        self,
        source_hash: str,
        content: str,
        timestamp: float | None = None,
        title: str | None = None,
        fields: dict[str, Any] | None = None,
        lxmf_hash: bytes | None = None,
        delivery_method: str | None = None,
        signature_valid: bool | None = None,
        transport_encrypted: bool | None = None,
        thread_id: str | None = None,
        reply_to_hash: str | None = None,
        has_attachment: bool = False,
        attachment_type: str | None = None,
        attachment_name: str | None = None,
        attachment_size: int | None = None,
        attachment_mime: str | None = None,
    ) -> int:
        """Save an incoming chat message.

        Updates unread count for the sender's conversation.

        Args:
            source_hash: LXMF destination hash of the sender
            content: Message content
            timestamp: Message timestamp (defaults to now)
            title: Optional message title (from LXMF native title field)
            fields: Optional LXMF fields dict
            lxmf_hash: Optional LXMF message hash (bytes)
            delivery_method: How the message was delivered ("direct", "propagated")
            signature_valid: Whether the LXMF signature was validated
            transport_encrypted: Whether transport encryption was used
            thread_id: Optional thread ID for message threading (LXMF FIELD_THREAD)
            reply_to_hash: Optional LXMF hash of message being replied to
            has_attachment: Whether the message has an attachment
            attachment_type: Type of attachment ("image", "audio", "file")
            attachment_name: Filename for file attachments
            attachment_size: Size of attachment in bytes
            attachment_mime: MIME type of attachment

        Returns:
            Database ID of saved message
        """
        if timestamp is None:
            timestamp = time.time()

        # Convert lxmf_hash bytes to hex string for storage
        lxmf_hash_hex: str | None = None
        if lxmf_hash is not None:
            lxmf_hash_hex = lxmf_hash.hex()

        with Session(self._db_engine) as session:
            msg = Message(
                source_hash=source_hash,
                destination_hash=self._local_identity_hash,
                timestamp=timestamp,
                content=content,
                title=title,
                protocol_id="chat",
                status=MessageStatus.RECEIVED,
                lxmf_hash=lxmf_hash_hex,
                delivery_method=delivery_method,
                signature_valid=signature_valid,
                transport_encrypted=transport_encrypted,
                thread_id=thread_id,
                reply_to_hash=reply_to_hash,
                has_attachment=has_attachment,
                attachment_type=attachment_type,
                attachment_name=attachment_name,
                attachment_size=attachment_size,
                attachment_mime=attachment_mime,
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
        title: str | None = None,
        fields: dict[str, Any] | None = None,
        lxmf_hash: bytes | None = None,
        delivery_method: str | None = None,
        delivery_attempts: int = 0,
        thread_id: str | None = None,
        reply_to_hash: str | None = None,
    ) -> int:
        """Save an outgoing chat message.

        Args:
            destination_hash: LXMF destination hash of recipient
            content: Message content
            timestamp: Message timestamp (defaults to now)
            title: Optional message title (for LXMF native title field)
            fields: Optional LXMF fields dict
            lxmf_hash: Optional LXMF message hash for delivery tracking (bytes)
            delivery_method: How the message will be delivered ("direct", "propagated")
            delivery_attempts: Number of delivery attempts made
            thread_id: Optional thread ID for message threading (LXMF FIELD_THREAD)
            reply_to_hash: Optional LXMF hash of message being replied to

        Returns:
            Database ID of saved message
        """
        if timestamp is None:
            timestamp = time.time()

        # Convert lxmf_hash bytes to hex string for storage
        lxmf_hash_hex: str | None = None
        if lxmf_hash is not None:
            lxmf_hash_hex = lxmf_hash.hex()

        with Session(self._db_engine) as session:
            msg = Message(
                source_hash=self._local_identity_hash,
                destination_hash=destination_hash,
                timestamp=timestamp,
                content=content,
                title=title,
                protocol_id="chat",
                status=MessageStatus.PENDING,
                delivery_method=delivery_method,
                delivery_attempts=delivery_attempts,
                lxmf_hash=lxmf_hash_hex,
                thread_id=thread_id,
                reply_to_hash=reply_to_hash,
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

    def update_destination_hash(self, message_id: int, destination_hash: str) -> bool:
        """Update the destination_hash of a message.

        Used to normalize truncated destination hashes to full 32-char hashes
        after LXMF resolves the identity and creates the actual destination.

        Args:
            message_id: Database ID of the message
            destination_hash: Full 32-char hex LXMF destination hash

        Returns:
            True if message was found and updated
        """
        with Session(self._db_engine) as session:
            msg = session.query(Message).filter(Message.id == message_id).first()
            if msg is None:
                return False

            msg.destination_hash = destination_hash
            session.commit()

        logger.debug(f"Updated message {message_id} destination_hash to {destination_hash[:16]}...")
        return True

    def register_delivery_tracking(self, message_id: int, lxmf_hash: bytes) -> None:
        """Register a message for delivery tracking after it's been sent.

        This allows separating message creation from send, avoiding race conditions
        where a delivery callback arrives before the message is saved.

        Args:
            message_id: Database ID of the message
            lxmf_hash: LXMF message hash for correlating callbacks
        """
        with self._lock:
            self._pending_deliveries[lxmf_hash] = DeliveryTracker(
                message_id=message_id,
                lxmf_hash=lxmf_hash,
            )
        logger.debug(f"Registered delivery tracking for message {message_id}")

    def get_failed_messages(self, peer_hash: str | None = None) -> list[MessageInfo]:
        """Get all failed messages, optionally filtered by peer.

        Args:
            peer_hash: Optional peer hash to filter by

        Returns:
            List of failed messages
        """
        with Session(self._db_engine) as session:
            query = session.query(Message).filter(
                Message.protocol_id == "chat",
                Message.status == MessageStatus.FAILED,
                Message.source_hash == self._local_identity_hash,  # Only outgoing
            )
            if peer_hash:
                query = query.filter(Message.destination_hash == peer_hash)

            query = query.order_by(desc(Message.timestamp))
            messages = query.all()

            # Use from_message for consistent field handling
            return [MessageInfo.from_message(msg, self._local_identity_hash) for msg in messages]

    def prepare_retry(self, message_id: int) -> tuple[str, str, dict[str, Any]] | None:
        """Prepare a failed message for retry.

        Retrieves message details and resets status to PENDING.
        Uses SELECT FOR UPDATE to prevent race conditions when multiple
        concurrent retry requests target the same message.

        Args:
            message_id: Database ID of the message to retry

        Returns:
            Tuple of (destination_hash, content, fields) if found, None otherwise
        """
        with Session(self._db_engine) as session:
            # Use with_for_update() to lock the row and prevent concurrent retries
            # from both succeeding through the FAILED status check
            msg = (
                session.query(Message)
                .filter(
                    Message.id == message_id,
                    Message.status == MessageStatus.FAILED,
                )
                .with_for_update()
                .first()
            )

            if msg is None:
                logger.warning(f"Message {message_id} not found or not in FAILED state")
                return None

            # Capture values before modifying
            dest_hash = msg.destination_hash
            content = msg.content or ""  # Ensure content is never None
            fields = msg.get_fields_dict()

            # Reset to pending for retry
            msg.status = MessageStatus.PENDING
            session.commit()

        logger.info(f"Prepared message {message_id} for retry to {dest_hash[:16]}...")
        return (dest_hash, content, fields)

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

    # -------------------------------------------------------------------------
    # Read Receipt Methods (Phase 4)
    # -------------------------------------------------------------------------

    def mark_read_by_recipient(self, lxmf_hash: str, read_at: float) -> bool:
        """Mark an outgoing message as read by the recipient.

        Called when we receive a read receipt from the peer indicating
        they have read our message.

        Args:
            lxmf_hash: Hex-encoded LXMF message hash
            read_at: Timestamp when the recipient read the message

        Returns:
            True if a message was found and updated
        """
        with Session(self._db_engine) as session:
            msg = (
                session.query(Message)
                .filter(
                    Message.lxmf_hash == lxmf_hash,
                    Message.source_hash == self._local_identity_hash,  # Outgoing only
                )
                .first()
            )

            if msg and not msg.read_by_recipient:
                msg.read_by_recipient = True
                msg.read_by_recipient_at = read_at
                session.commit()
                logger.debug(f"Marked message {msg.id} as read by recipient")
                return True

            return False

    def get_unread_hashes_for_receipt(self, peer_hash: str) -> list[str]:
        """Get LXMF hashes of incoming messages we haven't sent receipts for.

        Called when we want to send a read receipt for messages we've read.
        Returns hashes of messages that:
        - Are from this peer (incoming)
        - Have been marked as read locally
        - Haven't had a read receipt sent yet

        Args:
            peer_hash: LXMF destination hash of the peer

        Returns:
            List of hex-encoded LXMF message hashes
        """
        with Session(self._db_engine) as session:
            messages = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    Message.source_hash == peer_hash,
                    Message.destination_hash == self._local_identity_hash,
                    Message.status == "read",  # We've read them locally
                    Message.read_receipt_sent == False,  # noqa: E712
                    Message.lxmf_hash.isnot(None),
                )
                .all()
            )

            return [m.lxmf_hash for m in messages if m.lxmf_hash]

    def mark_receipts_sent(self, lxmf_hashes: list[str]) -> int:
        """Mark messages as having had read receipts sent.

        Called after successfully sending a read receipt to update
        the read_receipt_sent flag on the messages.

        Args:
            lxmf_hashes: List of hex-encoded LXMF message hashes

        Returns:
            Number of messages updated
        """
        if not lxmf_hashes:
            return 0

        with Session(self._db_engine) as session:
            count = (
                session.query(Message)
                .filter(Message.lxmf_hash.in_(lxmf_hashes))
                .update({Message.read_receipt_sent: True}, synchronize_session=False)
            )
            session.commit()

        logger.debug(f"Marked {count} messages as having receipts sent")
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
