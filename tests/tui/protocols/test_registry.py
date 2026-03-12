"""Tests for ProtocolRegistry."""
from __future__ import annotations


import pytest

from styrened.protocols.base import LXMFMessage, Protocol
from styrened.protocols.registry import ProtocolNotFoundError, ProtocolRegistry

# Import shared MockProtocol from conftest
from tests.tui.conftest import MockProtocol


def test_registry_initialization():
    """ProtocolRegistry should initialize empty."""
    registry = ProtocolRegistry()

    assert registry.list_protocols() == []


def test_register_protocol():
    """Registry should register protocols."""
    registry = ProtocolRegistry()
    protocol = MockProtocol("chat")

    registry.register_protocol(protocol)

    assert "chat" in registry.list_protocols()
    assert registry.get_protocol("chat") == protocol


def test_register_duplicate_protocol():
    """Registry should raise ValueError on duplicate registration."""
    registry = ProtocolRegistry()
    protocol1 = MockProtocol("chat")
    protocol2 = MockProtocol("chat")

    registry.register_protocol(protocol1)

    with pytest.raises(ValueError, match="Protocol 'chat' already registered"):
        registry.register_protocol(protocol2)


def test_get_protocol_not_found():
    """Registry should return None for unregistered protocol."""
    registry = ProtocolRegistry()

    assert registry.get_protocol("nonexistent") is None


@pytest.mark.asyncio
async def test_route_message_success():
    """Registry should route message to correct protocol."""
    registry = ProtocolRegistry()
    protocol = MockProtocol("chat")
    registry.register_protocol(protocol)

    msg = LXMFMessage(
        source_hash="source",
        destination_hash="dest",
        timestamp=123.0,
        fields={"protocol": "chat"},
    )

    # Should not raise
    await registry.route_message(msg)


@pytest.mark.asyncio
async def test_route_message_no_protocol():
    """Registry should raise error if no protocol specified."""
    registry = ProtocolRegistry()

    msg = LXMFMessage(
        source_hash="source",
        destination_hash="dest",
        timestamp=123.0,
    )

    with pytest.raises(ProtocolNotFoundError, match="No protocol specified"):
        await registry.route_message(msg)


@pytest.mark.asyncio
async def test_route_message_protocol_not_registered():
    """Registry should raise error if protocol not registered."""
    registry = ProtocolRegistry()

    msg = LXMFMessage(
        source_hash="source",
        destination_hash="dest",
        timestamp=123.0,
        fields={"protocol": "unknown"},
    )

    with pytest.raises(ProtocolNotFoundError, match="Protocol 'unknown' not found"):
        await registry.route_message(msg)


@pytest.mark.asyncio
async def test_route_message_cannot_handle():
    """Registry should raise error if protocol cannot handle message."""

    class RejectingProtocol(Protocol):
        @property
        def protocol_id(self) -> str:
            return "rejecting"

        def can_handle(self, message: LXMFMessage) -> bool:
            return False

        async def handle_message(self, message: LXMFMessage) -> None:
            pass

        async def send_message(self, destination: str, content: str) -> None:
            pass

    registry = ProtocolRegistry()
    registry.register_protocol(RejectingProtocol())

    msg = LXMFMessage(
        source_hash="source",
        destination_hash="dest",
        timestamp=123.0,
        fields={"protocol": "rejecting"},
    )

    with pytest.raises(ProtocolNotFoundError, match="cannot handle"):
        await registry.route_message(msg)


def test_unregister_protocol():
    """Registry should unregister protocols."""
    registry = ProtocolRegistry()
    protocol = MockProtocol("chat")

    registry.register_protocol(protocol)
    assert registry.get_protocol("chat") == protocol

    registry.unregister_protocol("chat")
    assert registry.get_protocol("chat") is None


def test_unregister_nonexistent_protocol():
    """Unregistering non-existent protocol should raise KeyError."""
    registry = ProtocolRegistry()

    with pytest.raises(KeyError, match="Protocol 'nonexistent' not registered"):
        registry.unregister_protocol("nonexistent")


def test_list_protocols():
    """Registry should list all registered protocol IDs."""
    registry = ProtocolRegistry()
    registry.register_protocol(MockProtocol("chat"))
    registry.register_protocol(MockProtocol("rpc"))
    registry.register_protocol(MockProtocol("bond-rpc"))

    protocol_ids = registry.list_protocols()

    assert set(protocol_ids) == {"chat", "rpc", "bond-rpc"}
