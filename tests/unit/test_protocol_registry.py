"""Unit tests for ProtocolRegistry.

Tests the protocol registration, routing, and error handling.
"""
from __future__ import annotations


import pytest

from styrened.protocols.base import LXMFMessage, Protocol
from styrened.protocols.registry import ProtocolNotFoundError, ProtocolRegistry


class MockProtocol(Protocol):
    """Mock protocol implementation for testing."""

    def __init__(self, protocol_id: str = "mock", can_handle_result: bool = True):
        self._protocol_id = protocol_id
        self._can_handle_result = can_handle_result
        self.handled_messages: list[LXMFMessage] = []

    @property
    def protocol_id(self) -> str:
        return self._protocol_id

    def can_handle(self, message: LXMFMessage) -> bool:
        return self._can_handle_result

    async def handle_message(self, message: LXMFMessage) -> None:
        self.handled_messages.append(message)

    async def send_message(self, destination: str, content: str) -> None:
        pass


class TestProtocolRegistration:
    """Tests for protocol registration."""

    def test_register_protocol_adds_to_registry(self) -> None:
        """Registered protocol should be retrievable."""
        registry = ProtocolRegistry()
        protocol = MockProtocol("test_protocol")

        registry.register_protocol(protocol)

        result = registry.get_protocol("test_protocol")
        assert result is protocol

    def test_register_multiple_protocols(self) -> None:
        """Multiple protocols can be registered."""
        registry = ProtocolRegistry()
        protocol_a = MockProtocol("protocol_a")
        protocol_b = MockProtocol("protocol_b")
        protocol_c = MockProtocol("protocol_c")

        registry.register_protocol(protocol_a)
        registry.register_protocol(protocol_b)
        registry.register_protocol(protocol_c)

        assert registry.get_protocol("protocol_a") is protocol_a
        assert registry.get_protocol("protocol_b") is protocol_b
        assert registry.get_protocol("protocol_c") is protocol_c

    def test_register_duplicate_protocol_raises_error(self) -> None:
        """Registering duplicate protocol ID should raise ValueError."""
        registry = ProtocolRegistry()
        protocol_1 = MockProtocol("same_id")
        protocol_2 = MockProtocol("same_id")

        registry.register_protocol(protocol_1)

        with pytest.raises(ValueError, match="already registered"):
            registry.register_protocol(protocol_2)

    def test_get_protocol_returns_none_for_unknown(self) -> None:
        """Getting unregistered protocol should return None."""
        registry = ProtocolRegistry()

        result = registry.get_protocol("nonexistent")
        assert result is None

    def test_list_protocols_returns_all_ids(self) -> None:
        """list_protocols should return all registered protocol IDs."""
        registry = ProtocolRegistry()
        registry.register_protocol(MockProtocol("alpha"))
        registry.register_protocol(MockProtocol("beta"))
        registry.register_protocol(MockProtocol("gamma"))

        protocols = registry.list_protocols()

        assert set(protocols) == {"alpha", "beta", "gamma"}

    def test_list_protocols_empty_registry(self) -> None:
        """list_protocols on empty registry should return empty list."""
        registry = ProtocolRegistry()

        protocols = registry.list_protocols()

        assert protocols == []


class TestProtocolUnregistration:
    """Tests for protocol unregistration."""

    def test_unregister_protocol_removes_from_registry(self) -> None:
        """Unregistered protocol should no longer be retrievable."""
        registry = ProtocolRegistry()
        protocol = MockProtocol("to_remove")
        registry.register_protocol(protocol)

        registry.unregister_protocol("to_remove")

        assert registry.get_protocol("to_remove") is None

    def test_unregister_nonexistent_protocol_raises_error(self) -> None:
        """Unregistering non-existent protocol should raise KeyError."""
        registry = ProtocolRegistry()

        with pytest.raises(KeyError, match="not registered"):
            registry.unregister_protocol("nonexistent")

    def test_unregister_then_register_same_id(self) -> None:
        """After unregistration, same ID can be registered again."""
        registry = ProtocolRegistry()
        protocol_1 = MockProtocol("reusable")
        protocol_2 = MockProtocol("reusable")

        registry.register_protocol(protocol_1)
        registry.unregister_protocol("reusable")
        registry.register_protocol(protocol_2)

        assert registry.get_protocol("reusable") is protocol_2


class TestMessageRouting:
    """Tests for message routing."""

    @pytest.mark.asyncio
    async def test_route_message_calls_handler(self) -> None:
        """Message should be routed to correct protocol handler."""
        registry = ProtocolRegistry()
        protocol = MockProtocol("chat")
        registry.register_protocol(protocol)

        message = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=1234567890.0,
            content="Hello",
            fields={"protocol": "chat"},
        )

        await registry.route_message(message)

        assert len(protocol.handled_messages) == 1
        assert protocol.handled_messages[0] is message

    @pytest.mark.asyncio
    async def test_route_message_no_protocol_field(self) -> None:
        """Message without protocol field should raise ProtocolNotFoundError."""
        registry = ProtocolRegistry()
        registry.register_protocol(MockProtocol("chat"))

        message = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=1234567890.0,
            content="No protocol",
            fields={},  # No protocol field
        )

        with pytest.raises(ProtocolNotFoundError, match="No protocol specified"):
            await registry.route_message(message)

    @pytest.mark.asyncio
    async def test_route_message_unknown_protocol(self) -> None:
        """Message with unknown protocol should raise ProtocolNotFoundError."""
        registry = ProtocolRegistry()
        registry.register_protocol(MockProtocol("chat"))

        message = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=1234567890.0,
            content="Unknown protocol",
            fields={"protocol": "unknown"},
        )

        with pytest.raises(ProtocolNotFoundError, match="not found"):
            await registry.route_message(message)

    @pytest.mark.asyncio
    async def test_route_message_protocol_cannot_handle(self) -> None:
        """Message that protocol can't handle should raise ProtocolNotFoundError."""
        registry = ProtocolRegistry()
        # Protocol says it can't handle messages
        protocol = MockProtocol("chat", can_handle_result=False)
        registry.register_protocol(protocol)

        message = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=1234567890.0,
            content="Rejected",
            fields={"protocol": "chat"},
        )

        with pytest.raises(ProtocolNotFoundError, match="cannot handle"):
            await registry.route_message(message)

    @pytest.mark.asyncio
    async def test_route_multiple_messages_to_same_protocol(self) -> None:
        """Multiple messages should all be routed correctly."""
        registry = ProtocolRegistry()
        protocol = MockProtocol("chat")
        registry.register_protocol(protocol)

        for i in range(5):
            message = LXMFMessage(
                source_hash=f"source_{i}",
                destination_hash="dest",
                timestamp=1234567890.0 + i,
                content=f"Message {i}",
                fields={"protocol": "chat"},
            )
            await registry.route_message(message)

        assert len(protocol.handled_messages) == 5

    @pytest.mark.asyncio
    async def test_route_messages_to_different_protocols(self) -> None:
        """Messages should be routed to their respective protocols."""
        registry = ProtocolRegistry()
        chat_protocol = MockProtocol("chat")
        rpc_protocol = MockProtocol("rpc")
        registry.register_protocol(chat_protocol)
        registry.register_protocol(rpc_protocol)

        chat_message = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=1234567890.0,
            content="Chat message",
            fields={"protocol": "chat"},
        )

        rpc_message = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=1234567891.0,
            content="RPC message",
            fields={"protocol": "rpc"},
        )

        await registry.route_message(chat_message)
        await registry.route_message(rpc_message)

        assert len(chat_protocol.handled_messages) == 1
        assert len(rpc_protocol.handled_messages) == 1
        assert chat_protocol.handled_messages[0].content == "Chat message"
        assert rpc_protocol.handled_messages[0].content == "RPC message"


class TestThreadSafety:
    """Tests for thread safety of registry operations."""

    def test_concurrent_registration_thread_safe(self) -> None:
        """Concurrent registrations should not corrupt registry."""
        import threading

        registry = ProtocolRegistry()
        errors: list[Exception] = []

        def register_protocol(protocol_id: str) -> None:
            try:
                registry.register_protocol(MockProtocol(protocol_id))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=register_protocol, args=(f"protocol_{i}",)) for i in range(10)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have no errors and all protocols registered
        assert len(errors) == 0
        assert len(registry.list_protocols()) == 10

    def test_concurrent_lookup_thread_safe(self) -> None:
        """Concurrent lookups should be safe."""
        import threading

        registry = ProtocolRegistry()
        protocol = MockProtocol("test")
        registry.register_protocol(protocol)

        results: list[Protocol | None] = []
        lock = threading.Lock()

        def lookup_protocol() -> None:
            result = registry.get_protocol("test")
            with lock:
                results.append(result)

        threads = [threading.Thread(target=lookup_protocol) for _ in range(20)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All lookups should return the same protocol
        assert len(results) == 20
        assert all(r is protocol for r in results)


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_handler_exception_propagates(self) -> None:
        """Exception in handler should propagate to caller."""

        class FailingProtocol(Protocol):
            @property
            def protocol_id(self) -> str:
                return "failing"

            def can_handle(self, message: LXMFMessage) -> bool:
                return True

            async def handle_message(self, message: LXMFMessage) -> None:
                raise RuntimeError("Handler failed!")

            async def send_message(self, destination: str, content: str) -> None:
                pass

        registry = ProtocolRegistry()
        registry.register_protocol(FailingProtocol())

        message = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=1234567890.0,
            content="Trigger failure",
            fields={"protocol": "failing"},
        )

        with pytest.raises(RuntimeError, match="Handler failed"):
            await registry.route_message(message)

    def test_protocol_id_is_normalized(self) -> None:
        """Protocol IDs should be case-sensitive (no normalization)."""
        registry = ProtocolRegistry()
        registry.register_protocol(MockProtocol("Chat"))
        registry.register_protocol(MockProtocol("chat"))

        # Both should be registered separately
        assert registry.get_protocol("Chat") is not None
        assert registry.get_protocol("chat") is not None
        assert registry.get_protocol("Chat") is not registry.get_protocol("chat")

    def test_empty_protocol_id_allowed(self) -> None:
        """Empty string protocol ID is technically allowed (though unusual)."""
        registry = ProtocolRegistry()
        protocol = MockProtocol("")
        registry.register_protocol(protocol)

        assert registry.get_protocol("") is protocol
