"""Tests for Protocol base class and LXMFMessage."""

import pytest

from styrened.protocols.base import LXMFMessage, Protocol

# Import shared MockProtocol from conftest
from tests.conftest import MockProtocol


def test_lxmf_message_creation():
    """LXMFMessage should be created with required fields."""
    msg = LXMFMessage(
        source_hash="abc123",
        destination_hash="def456",
        timestamp=1234567890.5,
    )

    assert msg.source_hash == "abc123"
    assert msg.destination_hash == "def456"
    assert msg.timestamp == 1234567890.5
    assert msg.content is None
    assert msg.fields == {}
    assert msg.protocol_id == ""
    assert msg.status == "pending"


def test_lxmf_message_with_content():
    """LXMFMessage should support optional content."""
    msg = LXMFMessage(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
        content="Hello World",
    )

    assert msg.content == "Hello World"


def test_lxmf_message_with_fields():
    """LXMFMessage should support fields dictionary."""
    msg = LXMFMessage(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
        fields={"protocol": "chat", "chat_type": "direct"},
    )

    assert msg.fields["protocol"] == "chat"
    assert msg.fields["chat_type"] == "direct"


def test_lxmf_message_get_protocol():
    """LXMFMessage.get_protocol() should extract protocol from fields."""
    msg = LXMFMessage(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
        fields={"protocol": "rpc"},
    )

    assert msg.get_protocol() == "rpc"


def test_lxmf_message_get_protocol_missing():
    """LXMFMessage.get_protocol() should return empty string if no protocol."""
    msg = LXMFMessage(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
    )

    assert msg.get_protocol() == ""


def test_protocol_is_abstract():
    """Protocol should be abstract and not instantiable."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        Protocol()  # type: ignore


def test_protocol_implementation():
    """Protocol implementation should provide all required methods."""
    protocol = MockProtocol("test")

    assert protocol.protocol_id == "test"

    msg = LXMFMessage(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
        fields={"protocol": "test"},
    )

    assert protocol.can_handle(msg)


def test_protocol_can_handle_false():
    """Protocol.can_handle() should return False for wrong protocol."""
    protocol = MockProtocol("chat")

    msg = LXMFMessage(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
        fields={"protocol": "rpc"},
    )

    assert not protocol.can_handle(msg)


@pytest.mark.asyncio
async def test_protocol_handle_message():
    """Protocol.handle_message() should be callable."""
    protocol = MockProtocol()

    msg = LXMFMessage(
        source_hash="abc",
        destination_hash="def",
        timestamp=123.0,
    )

    # Should not raise
    await protocol.handle_message(msg)


@pytest.mark.asyncio
async def test_protocol_send_message():
    """Protocol.send_message() should be callable."""
    protocol = MockProtocol()

    # Should not raise
    await protocol.send_message("destination", "content")
