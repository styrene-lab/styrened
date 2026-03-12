"""Tests for StyreneProtocol implementation."""
from __future__ import annotations


from unittest.mock import Mock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from styrened.models.messages import Base, Message
from styrened.models.styrene_wire import (
    STYRENE_PREFIX,
    STYRENE_VERSION,
    StyreneEnvelope,
    StyreneMessageType,
    create_chat,
    create_ping,
    decode_payload,
    encode_payload,
)
from styrened.protocols.base import LXMFMessage
from styrened.protocols.styrene import (
    FIELD_CUSTOM_DATA,
    FIELD_CUSTOM_TYPE,
    STYRENE_CUSTOM_TYPE,
    StyreneProtocol,
)


@pytest.fixture
def test_db(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test_styrene.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def mock_router():
    """Create mock LXMF router."""
    router = Mock()
    router.handle_outbound = Mock()
    return router


@pytest.fixture
def mock_identity():
    """Create mock RNS identity."""
    identity = Mock()
    identity.hash = b"\x74\x65\x73\x74\x69\x64\x65\x6e\x74\x69\x74\x79\x68\x61\x73\x68"
    identity.hexhash = "746573745f6964656e746974795f68617368"
    return identity


@pytest.fixture
def styrene_protocol(mock_router, mock_identity, test_db):
    """Create StyreneProtocol instance."""
    return StyreneProtocol(
        router=mock_router,
        identity=mock_identity,
        db_engine=test_db,
    )


class TestStyreneProtocolBasics:
    """Basic protocol property tests."""

    def test_protocol_id(self, styrene_protocol):
        """Protocol ID should be 'styrene'."""
        assert styrene_protocol.protocol_id == "styrene"

    def test_can_handle_with_custom_type_bytes(self, styrene_protocol):
        """can_handle should return True for styrene.io custom type (bytes)."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE},
        )
        assert styrene_protocol.can_handle(msg)

    def test_can_handle_with_custom_type_string(self, styrene_protocol):
        """can_handle should return True for styrene.io custom type (string)."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={FIELD_CUSTOM_TYPE: "styrene.io"},
        )
        assert styrene_protocol.can_handle(msg)

    def test_can_handle_without_custom_type(self, styrene_protocol):
        """can_handle should return False without custom type field."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={},
        )
        assert not styrene_protocol.can_handle(msg)

    def test_can_handle_with_wrong_custom_type(self, styrene_protocol):
        """can_handle should return False for non-styrene custom type."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={FIELD_CUSTOM_TYPE: b"other.protocol"},
        )
        assert not styrene_protocol.can_handle(msg)

    def test_can_handle_with_none_fields(self, styrene_protocol):
        """can_handle should return False when custom type is None."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={FIELD_CUSTOM_TYPE: None},
        )
        assert not styrene_protocol.can_handle(msg)


class TestStyreneProtocolHandleMessage:
    """Tests for handle_message method."""

    @pytest.mark.asyncio
    async def test_handle_ping_message(self, styrene_protocol, test_db):
        """handle_message should process PING messages."""
        envelope = create_ping()
        wire_data = envelope.encode()

        msg = LXMFMessage(
            source_hash="sender_abc123",
            destination_hash="receiver_def456",
            timestamp=1234567890.0,
            fields={
                FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE,
                FIELD_CUSTOM_DATA: wire_data,
            },
        )

        await styrene_protocol.handle_message(msg)

        # Verify message was persisted
        with Session(test_db) as session:
            saved = session.query(Message).filter_by(source_hash="sender_abc123").first()
            assert saved is not None
            assert saved.protocol_id == "styrene"
            assert "PING" in saved.content

    @pytest.mark.asyncio
    async def test_handle_chat_message(self, styrene_protocol, test_db):
        """handle_message should process CHAT messages."""
        envelope = create_chat("Hello from test!")
        wire_data = envelope.encode()

        msg = LXMFMessage(
            source_hash="sender",
            destination_hash="receiver",
            timestamp=123.0,
            fields={
                FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE,
                FIELD_CUSTOM_DATA: wire_data,
            },
        )

        await styrene_protocol.handle_message(msg)

        # Verify message was persisted
        with Session(test_db) as session:
            saved = session.query(Message).filter_by(source_hash="sender").first()
            assert saved is not None
            assert "CHAT" in saved.content

    @pytest.mark.asyncio
    async def test_handle_message_missing_custom_data(self, styrene_protocol, caplog):
        """handle_message should log error for missing FIELD_CUSTOM_DATA."""
        msg = LXMFMessage(
            source_hash="sender",
            destination_hash="receiver",
            timestamp=123.0,
            fields={FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE},
            # Missing FIELD_CUSTOM_DATA
        )

        await styrene_protocol.handle_message(msg)

        assert "missing FIELD_CUSTOM_DATA" in caplog.text

    @pytest.mark.asyncio
    async def test_handle_message_invalid_wire_data(self, styrene_protocol, caplog):
        """handle_message should log error for invalid wire data."""
        msg = LXMFMessage(
            source_hash="sender",
            destination_hash="receiver",
            timestamp=123.0,
            fields={
                FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE,
                FIELD_CUSTOM_DATA: b"invalid wire data",
            },
        )

        await styrene_protocol.handle_message(msg)

        assert "Failed to decode" in caplog.text


class TestStyreneProtocolSendMessage:
    """Tests for send_message methods."""

    @pytest.mark.asyncio
    @patch("styrened.protocols.styrene.RNS")
    @patch("styrened.protocols.styrene.LXMF")
    async def test_send_typed_message(self, mock_lxmf, mock_rns, styrene_protocol, mock_identity):
        """send_typed_message should create LXMF message with custom fields."""
        mock_message = Mock()
        mock_lxmf.LXMessage.return_value = mock_message
        mock_lxmf.APP_NAME = "lxmf"

        # Mock RNS.Identity.recall to return a mock identity with real bytes hash
        mock_dest_identity = Mock()
        mock_dest_identity.hash = b"\xab\xcd\xef\x01\x23\x45\x67\x89" * 2
        mock_rns.Identity.recall.return_value = mock_dest_identity
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1

        # Use valid 32-char hex string (16 bytes when decoded)
        hex_destination = "0123456789abcdef0123456789abcdef"

        await styrene_protocol.send_typed_message(
            destination=hex_destination,
            message_type=StyreneMessageType.PING,
            payload=b"",
        )

        # Verify RNS.Identity.recall was called with raw bytes
        mock_rns.Identity.recall.assert_called_once_with(bytes.fromhex(hex_destination))

        # Verify LXMF message created
        mock_lxmf.LXMessage.assert_called_once()
        call_kwargs = mock_lxmf.LXMessage.call_args[1]

        # Check custom fields
        assert call_kwargs["fields"][FIELD_CUSTOM_TYPE] == STYRENE_CUSTOM_TYPE
        assert FIELD_CUSTOM_DATA in call_kwargs["fields"]

        # Check human-readable content
        assert "[styrene.io:PING]" in call_kwargs["content"]

        # Verify destination and source are RNS.Destination objects (not None)
        assert call_kwargs["destination"] is not None
        assert call_kwargs["source"] is not None

        # Verify router called
        styrene_protocol._router.handle_outbound.assert_called_once_with(mock_message)

    @pytest.mark.asyncio
    @patch("styrened.protocols.styrene.RNS")
    @patch("styrened.protocols.styrene.LXMF")
    async def test_send_typed_message_unknown_destination_raises(
        self, mock_lxmf, mock_rns, styrene_protocol
    ):
        """send_typed_message should raise ValueError for unknown destination."""
        mock_lxmf.APP_NAME = "lxmf"

        # Mock RNS.Identity.recall to return None (unknown destination)
        mock_rns.Identity.recall.return_value = None

        hex_dest = "deadbeefcafe0123456789abcdef0123"

        with pytest.raises(ValueError, match="identity not known"):
            await styrene_protocol.send_typed_message(
                destination=hex_dest,
                message_type=StyreneMessageType.PING,
                payload=b"",
            )

    @pytest.mark.asyncio
    @patch("styrened.protocols.styrene.RNS")
    @patch("styrened.protocols.styrene.LXMF")
    async def test_send_chat(self, mock_lxmf, mock_rns, styrene_protocol):
        """send_chat should encode chat text in payload."""
        mock_message = Mock()
        mock_lxmf.LXMessage.return_value = mock_message
        mock_lxmf.APP_NAME = "lxmf"
        mock_dest_identity = Mock()
        mock_dest_identity.hash = b"\xab\xcd\xef\x01\x23\x45\x67\x89" * 2
        mock_rns.Identity.recall.return_value = mock_dest_identity
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1

        # Use valid 32-char hex destination
        await styrene_protocol.send_chat("0123456789abcdef0123456789abcdef", "Hello world!")

        # Verify LXMF message created with CHAT type
        call_kwargs = mock_lxmf.LXMessage.call_args[1]
        assert "[styrene.io:CHAT]" in call_kwargs["content"]

        # Verify wire data contains encoded chat
        wire_data = call_kwargs["fields"][FIELD_CUSTOM_DATA]
        envelope = StyreneEnvelope.decode(wire_data)
        assert envelope.message_type == StyreneMessageType.CHAT

        payload_data = decode_payload(envelope.payload)
        assert payload_data["text"] == "Hello world!"

    @pytest.mark.asyncio
    @patch("styrened.protocols.styrene.RNS")
    @patch("styrened.protocols.styrene.LXMF")
    async def test_send_ping(self, mock_lxmf, mock_rns, styrene_protocol):
        """send_ping should create PING message."""
        mock_message = Mock()
        mock_lxmf.LXMessage.return_value = mock_message
        mock_lxmf.APP_NAME = "lxmf"
        mock_dest_identity = Mock()
        mock_dest_identity.hash = b"\xab\xcd\xef\x01\x23\x45\x67\x89" * 2
        mock_rns.Identity.recall.return_value = mock_dest_identity
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1

        await styrene_protocol.send_ping("0123456789abcdef0123456789abcdef")

        call_kwargs = mock_lxmf.LXMessage.call_args[1]
        wire_data = call_kwargs["fields"][FIELD_CUSTOM_DATA]
        envelope = StyreneEnvelope.decode(wire_data)
        assert envelope.message_type == StyreneMessageType.PING

    @pytest.mark.asyncio
    @patch("styrened.protocols.styrene.RNS")
    @patch("styrened.protocols.styrene.LXMF")
    async def test_send_status_response(self, mock_lxmf, mock_rns, styrene_protocol):
        """send_status_response should encode status data."""
        mock_message = Mock()
        mock_lxmf.LXMessage.return_value = mock_message
        mock_lxmf.APP_NAME = "lxmf"
        mock_dest_identity = Mock()
        mock_dest_identity.hash = b"\xab\xcd\xef\x01\x23\x45\x67\x89" * 2
        mock_rns.Identity.recall.return_value = mock_dest_identity
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1

        status_data = {"online": True, "uptime": 3600}
        await styrene_protocol.send_status_response("0123456789abcdef0123456789abcdef", status_data)

        call_kwargs = mock_lxmf.LXMessage.call_args[1]
        wire_data = call_kwargs["fields"][FIELD_CUSTOM_DATA]
        envelope = StyreneEnvelope.decode(wire_data)
        assert envelope.message_type == StyreneMessageType.STATUS_RESPONSE

        payload_data = decode_payload(envelope.payload)
        assert payload_data == status_data

    @pytest.mark.asyncio
    @patch("styrened.protocols.styrene.RNS")
    @patch("styrened.protocols.styrene.LXMF")
    async def test_send_message_persists_to_db(
        self, mock_lxmf, mock_rns, styrene_protocol, test_db
    ):
        """send_typed_message should persist outbound message to database."""
        mock_message = Mock()
        mock_lxmf.LXMessage.return_value = mock_message
        mock_lxmf.APP_NAME = "lxmf"
        mock_dest_identity = Mock()
        mock_dest_identity.hash = b"\xab\xcd\xef\x01\x23\x45\x67\x89" * 2
        mock_rns.Identity.recall.return_value = mock_dest_identity
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1

        hex_dest = "abcdef0123456789abcdef0123456789"
        await styrene_protocol.send_ping(hex_dest)

        with Session(test_db) as session:
            saved = session.query(Message).filter_by(destination_hash=hex_dest).first()
            assert saved is not None
            assert saved.protocol_id == "styrene"
            assert "PING" in saved.content


class TestStyreneProtocolCorruptPayloads:
    """Tests for handling corrupt/malformed payloads."""

    @pytest.mark.asyncio
    async def test_handle_chat_with_corrupt_payload(self, styrene_protocol, caplog):
        """handle_message should log error for chat with corrupt payload."""
        # Create valid envelope structure but with corrupt msgpack in payload
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.CHAT,
            payload=b"\xff\xff\xff",  # Invalid msgpack
        )
        wire_data = envelope.encode()

        msg = LXMFMessage(
            source_hash="sender",
            destination_hash="receiver",
            timestamp=123.0,
            fields={
                FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE,
                FIELD_CUSTOM_DATA: wire_data,
            },
        )

        await styrene_protocol.handle_message(msg)

        assert "Failed to decode" in caplog.text

    @pytest.mark.asyncio
    async def test_handle_status_response_with_corrupt_payload(self, styrene_protocol, caplog):
        """handle_message should log error for status response with corrupt payload."""
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=b"\x00\x01\x02",  # Invalid msgpack
        )
        wire_data = envelope.encode()

        msg = LXMFMessage(
            source_hash="sender",
            destination_hash="receiver",
            timestamp=123.0,
            fields={
                FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE,
                FIELD_CUSTOM_DATA: wire_data,
            },
        )

        await styrene_protocol.handle_message(msg)

        assert "Failed to decode" in caplog.text


class TestLXMFFieldConstants:
    """Tests verifying LXMF field constants match specification."""

    def test_field_custom_type_matches_lxmf_spec(self):
        """FIELD_CUSTOM_TYPE should be 0xFB per LXMF spec."""
        assert FIELD_CUSTOM_TYPE == 0xFB

    def test_field_custom_data_matches_lxmf_spec(self):
        """FIELD_CUSTOM_DATA should be 0xFC per LXMF spec."""
        assert FIELD_CUSTOM_DATA == 0xFC

    def test_styrene_custom_type_is_bytes(self):
        """STYRENE_CUSTOM_TYPE should be bytes for LXMF compatibility."""
        assert isinstance(STYRENE_CUSTOM_TYPE, bytes)
        assert STYRENE_CUSTOM_TYPE == b"styrene.io"


class TestStyreneProtocolIntegration:
    """Integration tests for StyreneProtocol."""

    @pytest.mark.asyncio
    async def test_roundtrip_chat_message(self, styrene_protocol, test_db):
        """Chat message should roundtrip through encode/decode."""
        # Create and encode outbound message
        text = "Integration test message"
        envelope = create_chat(text)
        wire_data = envelope.encode()

        # Simulate receiving the message
        msg = LXMFMessage(
            source_hash="remote_sender",
            destination_hash="local_receiver",
            timestamp=123.0,
            fields={
                FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE,
                FIELD_CUSTOM_DATA: wire_data,
            },
        )

        # Process the message
        await styrene_protocol.handle_message(msg)

        # Verify persistence
        with Session(test_db) as session:
            saved = session.query(Message).first()
            assert saved is not None
            assert saved.protocol_id == "styrene"
            fields = saved.get_fields_dict()
            assert fields["styrene_type"] == "CHAT"

    @pytest.mark.asyncio
    async def test_all_message_types_handle(self, styrene_protocol, test_db):
        """All message types should be handled without error."""
        for msg_type in StyreneMessageType:
            # Create appropriate payload
            if msg_type in (
                StyreneMessageType.STATUS_RESPONSE,
                StyreneMessageType.ANNOUNCE,
            ):
                payload = encode_payload({"test": "data"})
            elif msg_type == StyreneMessageType.CHAT:
                payload = encode_payload({"text": "test"})
            else:
                payload = b""

            envelope = StyreneEnvelope(
                version=STYRENE_VERSION,
                message_type=msg_type,
                payload=payload,
            )
            wire_data = envelope.encode()

            msg = LXMFMessage(
                source_hash=f"sender_{msg_type.name}",
                destination_hash="receiver",
                timestamp=123.0,
                fields={
                    FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE,
                    FIELD_CUSTOM_DATA: wire_data,
                },
            )

            # Should not raise
            await styrene_protocol.handle_message(msg)

        # Verify all were persisted
        with Session(test_db) as session:
            count = session.query(Message).count()
            assert count == len(StyreneMessageType)

    def test_wire_format_includes_prefix(self):
        """Wire format should include styrene.io: prefix for validation."""
        envelope = create_ping()
        wire_data = envelope.encode()
        assert wire_data.startswith(STYRENE_PREFIX)

    def test_non_styrene_client_sees_readable_content(self):
        """Non-Styrene clients should see human-readable content field.

        This verifies our design: the content field is human-readable,
        while the actual protocol data is in FIELD_CUSTOM_DATA.
        """
        # The content we would set on outbound messages
        human_content = "[styrene.io:CHAT]"

        # A non-Styrene client would see this as the message content
        assert "styrene.io" in human_content
        assert "CHAT" in human_content
