"""Tests for Message persistence models."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from styrened.models.messages import Base, Message, init_db


@pytest.fixture
def test_db(tmp_path: Path):
    """Create test database."""
    db_path = tmp_path / "test_messages.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


def test_message_creation(test_db):
    """Message model should create records correctly."""
    with Session(test_db) as session:
        message = Message(
            source_hash="abc123",
            destination_hash="def456",
            timestamp=1234567890.5,
            content="Hello World",
            fields='{"protocol": "chat"}',
            protocol_id="chat",
            status="sent",
        )
        session.add(message)
        session.commit()

        # Query back
        stmt = select(Message).where(Message.source_hash == "abc123")
        result = session.execute(stmt).scalar_one()

        assert result.source_hash == "abc123"
        assert result.destination_hash == "def456"
        assert result.timestamp == 1234567890.5
        assert result.content == "Hello World"
        assert result.fields == '{"protocol": "chat"}'
        assert result.protocol_id == "chat"
        assert result.status == "sent"
        assert result.id is not None


def test_message_get_fields_dict():
    """Message.get_fields_dict() should deserialize JSON fields."""
    message = Message(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
        fields='{"protocol": "rpc", "operation": "status"}',
    )

    fields_dict = message.get_fields_dict()

    assert fields_dict == {"protocol": "rpc", "operation": "status"}


def test_message_set_fields_dict():
    """Message.set_fields_dict() should serialize dict to JSON."""
    message = Message(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
    )

    message.set_fields_dict({"protocol": "chat", "chat_type": "direct"})

    assert message.fields == '{"protocol":"chat","chat_type":"direct"}'
    # Verify round-trip
    assert message.get_fields_dict() == {"protocol": "chat", "chat_type": "direct"}


def test_message_default_status():
    """Message should default to 'pending' status."""
    message = Message(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
    )

    assert message.status == "pending"


def test_message_nullable_content():
    """Message content should be nullable."""
    message = Message(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
        content=None,
    )

    assert message.content is None


def test_message_query_by_protocol(test_db):
    """Should be able to query messages by protocol_id."""
    with Session(test_db) as session:
        session.add(
            Message(
                source_hash="s1",
                destination_hash="d1",
                timestamp=100.0,
                protocol_id="chat",
                fields="{}",
                status="sent",
            )
        )
        session.add(
            Message(
                source_hash="s2",
                destination_hash="d2",
                timestamp=200.0,
                protocol_id="rpc",
                fields="{}",
                status="sent",
            )
        )
        session.add(
            Message(
                source_hash="s3",
                destination_hash="d3",
                timestamp=300.0,
                protocol_id="chat",
                fields="{}",
                status="pending",
            )
        )
        session.commit()

        # Query chat messages only
        stmt = select(Message).where(Message.protocol_id == "chat")
        results = session.execute(stmt).scalars().all()

        assert len(results) == 2
        assert all(msg.protocol_id == "chat" for msg in results)


def test_init_db_creates_tables(tmp_path: Path):
    """init_db() should create database tables."""
    db_path = tmp_path / "messages.db"
    engine = init_db(str(db_path))

    assert db_path.exists()

    # Verify table exists
    with Session(engine) as session:
        message = Message(
            source_hash="test",
            destination_hash="test",
            timestamp=123.0,
        )
        session.add(message)
        session.commit()

        stmt = select(Message)
        result = session.execute(stmt).scalar_one()
        assert result.source_hash == "test"


def test_message_repr():
    """Message should have useful __repr__."""
    message = Message(
        source_hash="abc123",
        destination_hash="def456",
        timestamp=1234567890.0,
        protocol_id="chat",
        status="sent",
    )

    repr_str = repr(message)
    assert "Message" in repr_str
    assert "chat" in repr_str
    assert "sent" in repr_str
