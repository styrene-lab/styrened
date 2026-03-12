"""Unit tests for StyreneProtocol message dispatch and handling.

Tests the message routing, handler registration, and error isolation
in the protocol layer.
"""
from __future__ import annotations


from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.styrene_wire import (
    STYRENE_VERSION,
    StyreneEnvelope,
    StyreneMessageType,
    encode_payload,
)
from styrened.protocols.base import LXMFMessage


class TestMessageDetection:
    """Tests for can_handle() protocol detection."""

    @pytest.fixture
    def mock_router(self) -> MagicMock:
        """Create a mock LXMF router."""
        return MagicMock()

    @pytest.fixture
    def mock_identity(self) -> MagicMock:
        """Create a mock RNS identity."""
        mock = MagicMock()
        mock.hexhash = "a" * 32
        return mock

    @pytest.fixture
    def mock_db_engine(self) -> MagicMock:
        """Create a mock SQLAlchemy engine."""
        return MagicMock()

    @pytest.fixture
    def protocol(self, mock_router, mock_identity, mock_db_engine):
        """Create a StyreneProtocol instance."""
        with patch("styrened.protocols.styrene.RNS", MagicMock()):
            with patch("styrened.protocols.styrene.LXMF", MagicMock()):
                from styrened.protocols.styrene import StyreneProtocol

                return StyreneProtocol(mock_router, mock_identity, mock_db_engine)

    def test_detects_styrene_message_bytes(self, protocol):
        """Should detect Styrene messages with bytes FIELD_CUSTOM_TYPE."""
        message = MagicMock(spec=LXMFMessage)
        message.fields = {0xFB: b"styrene.io"}

        assert protocol.can_handle(message) is True

    def test_detects_styrene_message_string(self, protocol):
        """Should detect Styrene messages with string FIELD_CUSTOM_TYPE."""
        message = MagicMock(spec=LXMFMessage)
        message.fields = {0xFB: "styrene.io"}

        assert protocol.can_handle(message) is True

    def test_rejects_non_styrene_message(self, protocol):
        """Should reject messages with different FIELD_CUSTOM_TYPE."""
        message = MagicMock(spec=LXMFMessage)
        message.fields = {0xFB: b"other.protocol"}

        assert protocol.can_handle(message) is False

    def test_rejects_message_without_custom_type(self, protocol):
        """Should reject messages without FIELD_CUSTOM_TYPE."""
        message = MagicMock(spec=LXMFMessage)
        message.fields = {}

        assert protocol.can_handle(message) is False


class TestHandlerRegistration:
    """Tests for external handler registration."""

    @pytest.fixture
    def protocol(self):
        """Create a StyreneProtocol instance."""
        with patch("styrened.protocols.styrene.RNS", MagicMock()):
            with patch("styrened.protocols.styrene.LXMF", MagicMock()):
                from styrened.protocols.styrene import StyreneProtocol

                return StyreneProtocol(MagicMock(), MagicMock(), MagicMock())

    def test_register_external_handler(self, protocol):
        """Should register external handler for message type."""
        handler = AsyncMock()

        protocol.register_handler(StyreneMessageType.EXEC, handler)

        assert StyreneMessageType.EXEC in protocol._external_handlers
        assert handler in protocol._external_handlers[StyreneMessageType.EXEC]

    def test_register_multiple_handlers_same_type(self, protocol):
        """Should allow multiple handlers for same message type."""
        handler1 = AsyncMock()
        handler2 = AsyncMock()

        protocol.register_handler(StyreneMessageType.EXEC, handler1)
        protocol.register_handler(StyreneMessageType.EXEC, handler2)

        handlers = protocol._external_handlers[StyreneMessageType.EXEC]
        assert len(handlers) == 2
        assert handler1 in handlers
        assert handler2 in handlers

    def test_unregister_handler(self, protocol):
        """Should unregister handler."""
        handler = AsyncMock()

        protocol.register_handler(StyreneMessageType.EXEC, handler)
        protocol.unregister_handler(StyreneMessageType.EXEC, handler)

        handlers = protocol._external_handlers.get(StyreneMessageType.EXEC, [])
        assert handler not in handlers

    def test_unregister_nonexistent_handler_safe(self, protocol):
        """Should not raise when unregistering non-existent handler."""
        handler = AsyncMock()

        # Should not raise
        protocol.unregister_handler(StyreneMessageType.EXEC, handler)


class TestMessageDispatch:
    """Tests for _dispatch_message routing."""

    @pytest.fixture
    def protocol(self):
        """Create a StyreneProtocol instance."""
        with patch("styrened.protocols.styrene.RNS", MagicMock()):
            with patch("styrened.protocols.styrene.LXMF", MagicMock()):
                from styrened.protocols.styrene import StyreneProtocol

                return StyreneProtocol(MagicMock(), MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_internal_handler_called(self, protocol):
        """Internal handlers should be called for known types."""
        message = MagicMock(spec=LXMFMessage)
        message.source_hash = "abc123"

        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PING,
            payload=b"",
            request_id=None,
        )

        with patch.object(protocol, "_handle_ping", new_callable=AsyncMock) as mock_handler:
            await protocol._dispatch_message(message, envelope)

            mock_handler.assert_called_once_with(message, envelope)

    @pytest.mark.asyncio
    async def test_external_handlers_called(self, protocol):
        """External handlers should be called after internal handlers."""
        message = MagicMock(spec=LXMFMessage)
        message.source_hash = "abc123"

        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.EXEC,
            payload=encode_payload({"command": "uptime", "args": []}),
            request_id=None,
        )

        external_handler = AsyncMock()
        protocol.register_handler(StyreneMessageType.EXEC, external_handler)

        await protocol._dispatch_message(message, envelope)

        external_handler.assert_called_once_with(message, envelope)

    @pytest.mark.asyncio
    async def test_external_handler_error_isolated(self, protocol):
        """Errors in external handlers should not crash dispatch."""
        message = MagicMock(spec=LXMFMessage)
        message.source_hash = "abc123"

        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.EXEC,
            payload=encode_payload({"command": "uptime", "args": []}),
            request_id=None,
        )

        failing_handler = AsyncMock(side_effect=Exception("Handler error"))
        working_handler = AsyncMock()

        protocol.register_handler(StyreneMessageType.EXEC, failing_handler)
        protocol.register_handler(StyreneMessageType.EXEC, working_handler)

        # Should not raise
        await protocol._dispatch_message(message, envelope)

        # Both handlers should be attempted
        failing_handler.assert_called_once()
        working_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_type_logs_warning(self, protocol, caplog):
        """Unknown message types should log a warning."""
        import logging

        message = MagicMock(spec=LXMFMessage)
        message.source_hash = "abc123"

        # Create envelope with a type that has no handlers
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.CONFIG_UPDATE,  # No internal handler
            payload=b"",
            request_id=None,
        )

        with caplog.at_level(logging.WARNING):
            await protocol._dispatch_message(message, envelope)

        assert "No handler" in caplog.text


class TestMessageHandling:
    """Tests for handle_message entry point."""

    @pytest.fixture
    def protocol(self):
        """Create a StyreneProtocol instance."""
        with patch("styrened.protocols.styrene.RNS", MagicMock()):
            with patch("styrened.protocols.styrene.LXMF", MagicMock()):
                from styrened.protocols.styrene import StyreneProtocol

                return StyreneProtocol(MagicMock(), MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_missing_custom_data_logs_error(self, protocol, caplog):
        """Message without FIELD_CUSTOM_DATA should log error."""
        import logging

        message = MagicMock(spec=LXMFMessage)
        message.source_hash = "abc123"
        message.fields = {0xFB: b"styrene.io"}  # Has type but no data

        with caplog.at_level(logging.ERROR):
            await protocol.handle_message(message)

        assert "missing FIELD_CUSTOM_DATA" in caplog.text

    @pytest.mark.asyncio
    async def test_invalid_wire_format_logs_error(self, protocol, caplog):
        """Invalid wire format should log error."""
        import logging

        message = MagicMock(spec=LXMFMessage)
        message.source_hash = "abc123"
        message.fields = {
            0xFB: b"styrene.io",
            0xFC: b"\xff\xff\xff",  # Invalid wire format
        }

        with caplog.at_level(logging.ERROR):
            await protocol.handle_message(message)

        assert "Failed to decode" in caplog.text

    @pytest.mark.asyncio
    async def test_valid_message_dispatched(self, protocol):
        """Valid Styrene message should be dispatched."""
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PING,
            payload=b"",
            request_id=None,
        )

        message = MagicMock(spec=LXMFMessage)
        message.source_hash = "abc123"
        message.destination_hash = "def456"
        message.timestamp = 1234567890.0
        message.fields = {
            0xFB: b"styrene.io",
            0xFC: envelope.encode(),
        }

        with patch.object(protocol, "_dispatch_message", new_callable=AsyncMock) as mock_dispatch:
            with patch.object(protocol, "_persist_message"):
                await protocol.handle_message(message)

                mock_dispatch.assert_called_once()


class TestMessagePersistence:
    """Tests for message database persistence."""

    @pytest.fixture
    def protocol(self):
        """Create a StyreneProtocol instance."""
        with patch("styrened.protocols.styrene.RNS", MagicMock()):
            with patch("styrened.protocols.styrene.LXMF", MagicMock()):
                from styrened.protocols.styrene import StyreneProtocol

                return StyreneProtocol(MagicMock(), MagicMock(), MagicMock())

    def test_persist_message_creates_record(self, protocol):
        """_persist_message should create database record."""
        message = MagicMock(spec=LXMFMessage)
        message.source_hash = "abc123"
        message.destination_hash = "def456"
        message.timestamp = 1234567890.0

        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.CHAT,
            payload=encode_payload({"text": "hello"}),
            request_id=None,
        )

        with patch("styrened.protocols.styrene.Session") as mock_session_class:
            mock_session = MagicMock()
            mock_session_class.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_class.return_value.__exit__ = MagicMock(return_value=False)

            protocol._persist_message(message, envelope)

            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

            # Check the message was created correctly
            db_message = mock_session.add.call_args[0][0]
            assert db_message.source_hash == "abc123"
            assert db_message.protocol_id == "styrene"
            assert "[Styrene:CHAT]" in db_message.content


class TestConvenienceSendMethods:
    """Tests for send_ping, send_chat, etc."""

    @pytest.fixture
    def protocol(self):
        """Create a StyreneProtocol instance."""
        mock_rns = MagicMock()
        mock_lxmf = MagicMock()
        mock_lxmf.APP_NAME = "lxmf"

        with patch("styrened.protocols.styrene.RNS", mock_rns):
            with patch("styrened.protocols.styrene.LXMF", mock_lxmf):
                from styrened.protocols.styrene import StyreneProtocol

                protocol = StyreneProtocol(MagicMock(), MagicMock(), MagicMock())
                return protocol

    @pytest.mark.asyncio
    async def test_send_ping_calls_send_typed_message(self, protocol):
        """send_ping should call send_typed_message with PING type."""
        with patch.object(protocol, "send_typed_message", new_callable=AsyncMock) as mock_send:
            await protocol.send_ping("abc123")

            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs["destination"] == "abc123"
            assert call_kwargs["message_type"] == StyreneMessageType.PING

    @pytest.mark.asyncio
    async def test_send_chat_includes_text(self, protocol):
        """send_chat should include text in payload."""
        with patch.object(protocol, "send_typed_message", new_callable=AsyncMock) as mock_send:
            await protocol.send_chat("abc123", "Hello, world!")

            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            assert call_kwargs["message_type"] == StyreneMessageType.CHAT
            # Payload should be msgpack-encoded dict with text
            assert call_kwargs["payload"] is not None

    @pytest.mark.asyncio
    async def test_send_to_identity_alias(self, protocol):
        """send_to_identity should delegate to send."""
        with patch.object(protocol, "send", new_callable=AsyncMock) as mock_send:
            envelope = StyreneEnvelope(
                version=STYRENE_VERSION,
                message_type=StyreneMessageType.PING,
                payload=b"",
                request_id=None,
            )

            await protocol.send_to_identity("abc123", envelope)

            mock_send.assert_called_once_with("abc123", envelope)


class TestIdentityResolution:
    """Tests for _resolve_identity in StyreneProtocol."""

    @pytest.fixture
    def mock_rns(self):
        """Create a mock RNS module."""
        mock = MagicMock()
        mock.Identity = MagicMock()
        mock.Identity.recall = MagicMock(return_value=None)
        return mock

    @pytest.fixture
    def protocol(self, mock_rns):
        """Create a StyreneProtocol instance."""
        with patch("styrened.protocols.styrene.RNS", mock_rns):
            with patch("styrened.protocols.styrene.LXMF", MagicMock()):
                from styrened.protocols.styrene import StyreneProtocol

                return StyreneProtocol(MagicMock(), MagicMock(), MagicMock())

    def test_resolve_identity_tries_multiple_strategies(self, protocol, mock_rns):
        """_resolve_identity should try multiple lookup strategies."""
        dest_hash = "a" * 32

        with patch("styrened.protocols.styrene.RNS", mock_rns):
            mock_store = MagicMock()
            mock_store.get_identity_for_destination.return_value = None
            mock_store.get_identity_for_lxmf_destination.return_value = None

            with patch(
                "styrened.services.node_store.get_node_store",
                return_value=mock_store,
            ):
                protocol._resolve_identity(dest_hash)

        # Should have tried direct recall
        assert mock_rns.Identity.recall.called

        # Should have tried NodeStore lookups
        mock_store.get_identity_for_destination.assert_called_with(dest_hash)
        mock_store.get_identity_for_lxmf_destination.assert_called_with(dest_hash)
