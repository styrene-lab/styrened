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
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir
from sqlalchemy import Index, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[float] = mapped_column(nullable=False)
    content: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    fields: Mapped[str] = mapped_column(String, nullable=False, default=lambda: "{}")
    protocol_id: Mapped[str] = mapped_column(String(50), nullable=False, default=lambda: "")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=lambda: "pending")

    def __init__(
        self,
        source_hash: str,
        destination_hash: str,
        timestamp: float,
        content: str | None = None,
        fields: str = "{}",
        protocol_id: str = "",
        status: str = "pending",
        **kwargs: Any,
    ) -> None:
        """Initialize Message with defaults.

        Args:
            source_hash: Source identity hash
            destination_hash: Destination identity hash
            timestamp: Message timestamp
            content: Optional message content
            fields: JSON-encoded fields dictionary
            protocol_id: Protocol identifier
            status: Message status
            **kwargs: Additional keyword arguments for SQLAlchemy
        """
        super().__init__(
            source_hash=source_hash,
            destination_hash=destination_hash,
            timestamp=timestamp,
            content=content,
            fields=fields,
            protocol_id=protocol_id,
            status=status,
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
        data_dir = Path(user_data_dir("styrene", "styrene-lab"))
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(data_dir / "messages.db")

    logger.info(f"Initializing message database: {db_path}")
    engine = create_engine(f"sqlite:///{db_path}")

    # Create tables
    Base.metadata.create_all(engine)

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
