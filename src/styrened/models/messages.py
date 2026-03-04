"""SQLAlchemy models for LXMF message persistence.

This module provides database models for storing LXMF messages locally.
Messages are stored at ~/.local/share/styrene/messages.db by default.

Design decisions:
- SQLite for lightweight local storage
- JSON-encoded fields dictionary (LXMF standard)
- Support for message status tracking (pending/sent/delivered/failed)
- Indexed queries by protocol_id, status, timestamp
"""

import json
import logging
from typing import Any

from sqlalchemy import Float, Index, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

logger = logging.getLogger(__name__)


class MessageStatus:
    """Message delivery status constants."""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    RECEIVED = "received"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


class PageCache(Base):
    """Cached NomadNet page content.

    Write-through cache: every successful page fetch writes here.
    On fetch failure, the TUI can display the last cached version
    with a "cached @ <timestamp>" indicator.
    """

    __tablename__ = "page_cache"
    __table_args__ = (
        UniqueConstraint("destination_hash", "path", name="uq_page_cache_dest_path"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    destination_hash: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text, default="")
    content_length: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[float] = mapped_column(Float, default=0.0)


class SavedSite(Base):
    """A NomadNet node saved for periodic background crawling.

    Saved sites are crawled on a configurable interval to keep
    cached pages fresh.  The crawler follows links from the index
    page up to a configurable depth limit.
    """

    __tablename__ = "saved_sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    destination_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    refresh_interval: Mapped[int] = mapped_column(Integer, default=3600)
    last_crawl_at: Mapped[float] = mapped_column(Float, default=0.0)
    pages_cached: Mapped[int] = mapped_column(Integer, default=0)
    max_depth: Mapped[int] = mapped_column(Integer, default=3)


class Message(Base):
    """LXMF message persistence model.

    Stores LXMF messages with protocol discrimination, delivery status,
    and queryable metadata.

    Attributes:
        id: Auto-incrementing primary key
        source_hash: Source identity hash (hex-encoded)
        destination_hash: Destination identity hash (hex-encoded)
        timestamp: Message timestamp (seconds since epoch)
        content: Optional message content (may be None for protocol-only messages)
        fields: JSON-encoded protocol discrimination dictionary
        protocol_id: Cached protocol identifier (for indexed queries)
        status: Message delivery status ('pending', 'sent', 'delivered', 'failed')
    """

    __tablename__ = "messages"

    # Indexes for common query patterns
    __table_args__ = (
        Index("ix_messages_protocol_id", "protocol_id"),
        Index("ix_messages_status", "status"),
        Index("ix_messages_timestamp", "timestamp"),
        # Conversation queries: find messages between two parties
        Index("ix_messages_source_dest", "source_hash", "destination_hash"),
        # Unread count queries: find received messages by status
        Index("ix_messages_dest_status", "destination_hash", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[float] = mapped_column(nullable=False)
    content: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    title: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default=None
    )  # LXMF native title field for ecosystem compatibility
    fields: Mapped[str] = mapped_column(String, nullable=False, default=lambda: "{}")
    protocol_id: Mapped[str] = mapped_column(String(50), nullable=False, default=lambda: "")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=lambda: "pending")

    # LXMF delivery tracking columns (Phase 2a)
    delivery_method: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None
    )  # "direct", "propagated", or None
    delivery_attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    lxmf_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )  # hex-encoded LXMF message hash
    signature_valid: Mapped[bool | None] = mapped_column(
        nullable=True, default=None
    )  # LXMF signature validation result
    transport_encrypted: Mapped[bool | None] = mapped_column(
        nullable=True, default=None
    )  # transport encryption status

    # Read receipt tracking columns (Phase 4)
    # For outgoing messages: track if recipient has read them
    read_by_recipient: Mapped[bool] = mapped_column(nullable=False, default=False)
    read_by_recipient_at: Mapped[float | None] = mapped_column(nullable=True, default=None)
    # For incoming messages: track if we've sent a read receipt
    read_receipt_sent: Mapped[bool] = mapped_column(nullable=False, default=False)

    # Attachment support for ecosystem compatibility (MeshChat, Sideband)
    # LXMF fields: FIELD_IMAGE (0x06), FIELD_AUDIO (0x07), FIELD_FILE_ATTACHMENTS (0x05)
    has_attachment: Mapped[bool] = mapped_column(nullable=False, default=False)
    attachment_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default=None
    )  # "image", "audio", "file"
    attachment_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, default=None
    )  # Original filename
    attachment_size: Mapped[int | None] = mapped_column(
        nullable=True, default=None
    )  # Size in bytes
    attachment_mime: Mapped[str | None] = mapped_column(
        String(100), nullable=True, default=None
    )  # MIME type (e.g., "image/jpeg")
    # For small attachments (<1MB), store inline as base64
    # Larger attachments should use filesystem storage (path in attachment_path)
    attachment_data: Mapped[str | None] = mapped_column(
        String, nullable=True, default=None
    )  # Base64-encoded data for small attachments
    attachment_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )  # Filesystem path for large attachments

    # Message threading support (LXMF FIELD_THREAD = 0x08)
    # Enables threaded conversations and reply tracking
    thread_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )  # Thread identifier (typically first message's lxmf_hash)
    reply_to_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None
    )  # LXMF hash of message being replied to

    def __init__(
        self,
        source_hash: str,
        destination_hash: str,
        timestamp: float,
        content: str | None = None,
        title: str | None = None,
        fields: str = "{}",
        protocol_id: str = "",
        status: str = "pending",
        delivery_method: str | None = None,
        delivery_attempts: int = 0,
        lxmf_hash: str | None = None,
        signature_valid: bool | None = None,
        transport_encrypted: bool | None = None,
        read_by_recipient: bool = False,
        read_by_recipient_at: float | None = None,
        read_receipt_sent: bool = False,
        has_attachment: bool = False,
        attachment_type: str | None = None,
        attachment_name: str | None = None,
        attachment_size: int | None = None,
        attachment_mime: str | None = None,
        attachment_data: str | None = None,
        attachment_path: str | None = None,
        thread_id: str | None = None,
        reply_to_hash: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Message with defaults.

        Args:
            source_hash: Source identity hash
            destination_hash: Destination identity hash
            timestamp: Message timestamp
            content: Optional message content
            title: Optional message title (LXMF native title field)
            fields: JSON-encoded fields dictionary
            protocol_id: Protocol identifier
            status: Message status
            delivery_method: How message was/will be delivered ("direct", "propagated")
            delivery_attempts: Number of delivery attempts made
            lxmf_hash: Hex-encoded LXMF message hash
            signature_valid: Whether LXMF signature was validated
            transport_encrypted: Whether transport encryption was used
            read_by_recipient: Whether recipient has read (for outgoing)
            read_by_recipient_at: When recipient read the message
            read_receipt_sent: Whether we've sent a receipt (for incoming)
            has_attachment: Whether message has an attachment
            attachment_type: Type of attachment ("image", "audio", "file")
            attachment_name: Original filename of attachment
            attachment_size: Size of attachment in bytes
            attachment_mime: MIME type of attachment
            attachment_data: Base64-encoded attachment data (for small files)
            attachment_path: Filesystem path to attachment (for large files)
            thread_id: Thread identifier for grouping related messages
            reply_to_hash: LXMF hash of message being replied to
            **kwargs: Additional keyword arguments for SQLAlchemy
        """
        super().__init__(
            source_hash=source_hash,
            destination_hash=destination_hash,
            timestamp=timestamp,
            content=content,
            title=title,
            fields=fields,
            protocol_id=protocol_id,
            status=status,
            delivery_method=delivery_method,
            delivery_attempts=delivery_attempts,
            lxmf_hash=lxmf_hash,
            signature_valid=signature_valid,
            transport_encrypted=transport_encrypted,
            read_by_recipient=read_by_recipient,
            read_by_recipient_at=read_by_recipient_at,
            read_receipt_sent=read_receipt_sent,
            has_attachment=has_attachment,
            attachment_type=attachment_type,
            attachment_name=attachment_name,
            attachment_size=attachment_size,
            attachment_mime=attachment_mime,
            attachment_data=attachment_data,
            attachment_path=attachment_path,
            thread_id=thread_id,
            reply_to_hash=reply_to_hash,
            **kwargs,
        )

    def get_fields_dict(self) -> dict[str, Any]:
        """Deserialize fields JSON to dictionary.

        Returns:
            Parsed fields dictionary

        Raises:
            json.JSONDecodeError: If fields contains invalid JSON
        """
        if not self.fields:
            return {}
        result: dict[str, Any] = json.loads(self.fields)
        return result

    def set_fields_dict(self, fields_dict: dict[str, Any]) -> None:
        """Serialize dictionary to fields JSON.

        Args:
            fields_dict: Dictionary to serialize
        """
        self.fields = json.dumps(fields_dict, separators=(",", ":"))

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"<Message(id={self.id}, protocol={self.protocol_id}, "
            f"status={self.status}, timestamp={self.timestamp})>"
        )


def init_db(db_path: str | None = None) -> Engine:
    """Initialize database and create tables.

    Args:
        db_path: Path to SQLite database file. If None, uses default location
                 (~/.local/share/styrene/messages.db)

    Returns:
        SQLAlchemy engine
    """
    if db_path is None:
        from styrened import paths

        db = paths.messages_db()
        db.parent.mkdir(parents=True, exist_ok=True)
        db_path = str(db)

    logger.info(f"Initializing message database: {db_path}")
    engine = create_engine(f"sqlite:///{db_path}")

    # Create tables
    Base.metadata.create_all(engine)

    # Schema migration: Add columns if they don't exist
    # This handles databases created before these features were added
    from sqlalchemy import text

    # Add title column (Phase 1)
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE messages ADD COLUMN title VARCHAR(255)"))
            conn.commit()
            logger.info("Added 'title' column to messages table")
    except Exception:
        pass  # Column already exists

    # Add read receipt columns (Phase 4)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE messages ADD COLUMN read_by_recipient BOOLEAN DEFAULT 0")
            )
            conn.commit()
            logger.info("Added 'read_by_recipient' column to messages table")
    except Exception:
        pass  # Column already exists

    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE messages ADD COLUMN read_by_recipient_at REAL"))
            conn.commit()
            logger.info("Added 'read_by_recipient_at' column to messages table")
    except Exception:
        pass  # Column already exists

    try:
        with engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE messages ADD COLUMN read_receipt_sent BOOLEAN DEFAULT 0")
            )
            conn.commit()
            logger.info("Added 'read_receipt_sent' column to messages table")
    except Exception:
        pass  # Column already exists

    # Add attachment columns for ecosystem compatibility (MeshChat, Sideband)
    attachment_columns = [
        ("has_attachment", "BOOLEAN DEFAULT 0"),
        ("attachment_type", "VARCHAR(20)"),
        ("attachment_name", "VARCHAR(255)"),
        ("attachment_size", "INTEGER"),
        ("attachment_mime", "VARCHAR(100)"),
        ("attachment_data", "TEXT"),
        ("attachment_path", "VARCHAR(500)"),
    ]
    for col_name, col_type in attachment_columns:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                logger.info(f"Added '{col_name}' column to messages table")
        except Exception:
            pass  # Column already exists

    # Add message threading columns (LXMF FIELD_THREAD support)
    threading_columns = [
        ("thread_id", "VARCHAR(64)"),
        ("reply_to_hash", "VARCHAR(64)"),
    ]
    for col_name, col_type in threading_columns:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE messages ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                logger.info(f"Added '{col_name}' column to messages table")
        except Exception:
            pass  # Column already exists

    # Create contacts table if it doesn't exist
    # Import here to ensure the model is registered with Base before create_all
    from styrened.models.contacts import Contact  # noqa: F401

    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS contacts ("
                    "peer_hash VARCHAR(32) PRIMARY KEY, "
                    "alias VARCHAR(100) NOT NULL, "
                    "notes VARCHAR(500), "
                    "created_at REAL NOT NULL, "
                    "updated_at REAL NOT NULL"
                    ")"
                )
            )
            conn.commit()
            logger.debug("Contacts table initialized")
    except Exception:
        pass  # Table already exists or was created by create_all

    # Migrate contacts table: add blocked columns if missing
    for col_name, col_type in [
        ("blocked", "BOOLEAN NOT NULL DEFAULT 0"),
        ("blocked_at", "REAL"),
    ]:
        try:
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE contacts ADD COLUMN {col_name} {col_type}"))
                conn.commit()
                logger.info(f"Added '{col_name}' column to contacts table")
        except Exception:
            pass  # Column already exists

    # Create FTS5 virtual table for full-text search
    # This enables searching message content and titles efficiently
    with engine.connect() as conn:
        # Create the FTS5 virtual table (content-less, references messages table)
        conn.execute(
            text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
                content,
                title,
                content='messages',
                content_rowid='id'
            )
        """)
        )

        # Trigger to keep FTS in sync on INSERT
        conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content, title)
                VALUES (new.id, new.content, new.title);
            END
        """)
        )

        # Trigger to keep FTS in sync on DELETE
        conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content, title)
                VALUES ('delete', old.id, old.content, old.title);
            END
        """)
        )

        # Trigger to keep FTS in sync on UPDATE
        conn.execute(
            text("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content, title)
                VALUES ('delete', old.id, old.content, old.title);
                INSERT INTO messages_fts(rowid, content, title)
                VALUES (new.id, new.content, new.title);
            END
        """)
        )

        conn.commit()
        logger.debug("FTS5 virtual table and triggers initialized")

    return engine


def get_session(db_path: str | None = None) -> Session:
    """Get database session.

    Args:
        db_path: Path to SQLite database file. If None, uses default location

    Returns:
        SQLAlchemy session
    """
    engine = init_db(db_path)
    return Session(engine)
