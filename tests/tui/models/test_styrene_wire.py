"""Tests for Styrene wire format."""
from __future__ import annotations


import pytest

from styrened.models.styrene_wire import (
    MAX_MSGPACK_ARRAY_LEN,
    MAX_MSGPACK_MAP_LEN,
    MAX_PAYLOAD_SIZE,
    STYRENE_PREFIX,
    STYRENE_VERSION,
    InvalidMessageTypeError,
    InvalidPrefixError,
    PayloadDecodeError,
    StyreneEnvelope,
    StyreneMessageType,
    UnsupportedVersionError,
    create_announce,
    create_chat,
    create_ping,
    create_pong,
    create_status_request,
    create_status_response,
    decode_payload,
    encode_payload,
)


class TestStyreneMessageType:
    """Tests for StyreneMessageType enum."""

    def test_message_type_values(self):
        """Message types should have expected values."""
        assert StyreneMessageType.PING == 0x01
        assert StyreneMessageType.PONG == 0x02
        assert StyreneMessageType.STATUS_REQUEST == 0x10
        assert StyreneMessageType.STATUS_RESPONSE == 0x11
        assert StyreneMessageType.CHAT == 0x20
        assert StyreneMessageType.ANNOUNCE == 0x30

    def test_message_type_is_int(self):
        """Message types should be usable as integers."""
        assert int(StyreneMessageType.PING) == 1
        assert bytes([StyreneMessageType.CHAT]) == b"\x20"


class TestStyreneEnvelope:
    """Tests for StyreneEnvelope encode/decode."""

    def test_encode_produces_prefix(self):
        """Encoded message should start with styrene.io: prefix."""
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PING,
            payload=b"",
        )
        encoded = envelope.encode()
        assert encoded.startswith(STYRENE_PREFIX)

    def test_encode_includes_version(self):
        """Encoded message should include version byte after prefix."""
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PING,
            payload=b"",
        )
        encoded = envelope.encode()
        version_offset = len(STYRENE_PREFIX)
        assert encoded[version_offset] == STYRENE_VERSION

    def test_encode_includes_message_type(self):
        """Encoded message should include message type byte."""
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.CHAT,
            payload=b"",
        )
        encoded = envelope.encode()
        type_offset = len(STYRENE_PREFIX) + 1
        assert encoded[type_offset] == StyreneMessageType.CHAT

    def test_encode_includes_payload(self):
        """Encoded message should include payload bytes after request_id (v2)."""
        payload = b"test payload data"
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.CHAT,
            payload=payload,
        )
        encoded = envelope.encode()
        # v2: prefix + version(1) + type(1) + request_id(16) + payload
        from styrened.models.styrene_wire import REQUEST_ID_LENGTH
        payload_offset = len(STYRENE_PREFIX) + 2 + REQUEST_ID_LENGTH
        assert encoded[payload_offset:] == payload

    def test_decode_roundtrip(self):
        """Decode should recover original envelope from encoded bytes."""
        original = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=b"some response data",
        )
        encoded = original.encode()
        decoded = StyreneEnvelope.decode(encoded)

        assert decoded.version == original.version
        assert decoded.message_type == original.message_type
        assert decoded.payload == original.payload

    def test_decode_all_message_types(self):
        """All message types should roundtrip correctly."""
        for msg_type in StyreneMessageType:
            envelope = StyreneEnvelope(
                version=STYRENE_VERSION,
                message_type=msg_type,
                payload=b"type-specific-data",
            )
            decoded = StyreneEnvelope.decode(envelope.encode())
            assert decoded.message_type == msg_type

    def test_decode_invalid_prefix_raises(self):
        """Decode should raise InvalidPrefixError for wrong prefix."""
        bad_data = b"not-styrene:" + bytes([1, 0x20]) + b"payload"
        with pytest.raises(InvalidPrefixError):
            StyreneEnvelope.decode(bad_data)

    def test_decode_too_short_raises(self):
        """Decode should raise InvalidPrefixError for too-short message."""
        short_data = b"styrene.io:"  # Missing version and type
        with pytest.raises(InvalidPrefixError) as exc_info:
            StyreneEnvelope.decode(short_data)
        assert "too short" in str(exc_info.value).lower()

    def test_decode_unsupported_version_raises(self):
        """Decode should raise UnsupportedVersionError for unknown version."""
        bad_version = STYRENE_PREFIX + bytes([99, 0x01])  # Version 99
        with pytest.raises(UnsupportedVersionError):
            StyreneEnvelope.decode(bad_version)

    def test_decode_invalid_message_type_raises(self):
        """Decode should raise InvalidMessageTypeError for unknown type."""
        # Use a supported version (1 or 2) with an invalid message type
        bad_type = STYRENE_PREFIX + bytes([1, 0xFE])  # Version 1, type 0xFE not defined
        with pytest.raises(InvalidMessageTypeError):
            StyreneEnvelope.decode(bad_type)

    def test_is_styrene_message_true(self):
        """is_styrene_message should return True for valid prefix."""
        envelope = create_ping()
        assert StyreneEnvelope.is_styrene_message(envelope.encode())

    def test_is_styrene_message_false(self):
        """is_styrene_message should return False for other data."""
        assert not StyreneEnvelope.is_styrene_message(b"Hello, world!")
        assert not StyreneEnvelope.is_styrene_message(b"")
        assert not StyreneEnvelope.is_styrene_message(b"styrene")  # Incomplete

    def test_empty_payload_allowed(self):
        """Empty payload should be valid."""
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.PING,
            payload=b"",
        )
        encoded = envelope.encode()
        decoded = StyreneEnvelope.decode(encoded)
        assert decoded.payload == b""

    def test_invalid_version_raises(self):
        """StyreneEnvelope should reject invalid version values."""
        with pytest.raises(ValueError, match="version must be 0-255"):
            StyreneEnvelope(
                version=256,
                message_type=StyreneMessageType.PING,
                payload=b"",
            )

        with pytest.raises(ValueError, match="version must be 0-255"):
            StyreneEnvelope(
                version=-1,
                message_type=StyreneMessageType.PING,
                payload=b"",
            )

    def test_oversized_payload_raises(self):
        """StyreneEnvelope should reject payloads exceeding MAX_PAYLOAD_SIZE."""
        oversized_payload = b"x" * (MAX_PAYLOAD_SIZE + 1)
        with pytest.raises(ValueError, match="payload too large"):
            StyreneEnvelope(
                version=STYRENE_VERSION,
                message_type=StyreneMessageType.CHAT,
                payload=oversized_payload,
            )


class TestPayloadEncoding:
    """Tests for msgpack payload encoding/decoding."""

    def test_encode_dict(self):
        """encode_payload should handle dictionaries."""
        data = {"key": "value", "count": 42}
        encoded = encode_payload(data)
        assert isinstance(encoded, bytes)
        assert len(encoded) > 0

    def test_decode_dict(self):
        """decode_payload should recover dictionaries."""
        original = {"key": "value", "count": 42}
        encoded = encode_payload(original)
        decoded = decode_payload(encoded)
        assert decoded == original

    def test_encode_nested_structures(self):
        """encode_payload should handle nested structures."""
        data = {
            "device": {
                "name": "sensor-01",
                "readings": [1.5, 2.3, 3.7],
            },
            "timestamp": 1234567890,
        }
        encoded = encode_payload(data)
        decoded = decode_payload(encoded)
        assert decoded == data

    def test_encode_binary_data(self):
        """encode_payload should handle binary data."""
        data = {"raw": b"\x00\x01\x02\xff"}
        encoded = encode_payload(data)
        decoded = decode_payload(encoded)
        assert decoded["raw"] == b"\x00\x01\x02\xff"

    def test_decode_invalid_raises(self):
        """decode_payload should raise PayloadDecodeError for invalid data."""
        with pytest.raises(PayloadDecodeError):
            decode_payload(b"\xff\xff\xff\xff")  # Invalid msgpack

    def test_decode_oversized_payload_raises(self):
        """decode_payload should reject oversized payloads."""
        # Create a payload larger than MAX_PAYLOAD_SIZE
        oversized_data = b"x" * (MAX_PAYLOAD_SIZE + 1)
        with pytest.raises(PayloadDecodeError, match="Payload too large"):
            decode_payload(oversized_data)

    def test_decode_rejects_oversized_array(self):
        """decode_payload should reject arrays exceeding MAX_MSGPACK_ARRAY_LEN."""
        import msgpack

        # Create array larger than limit
        large_array = list(range(MAX_MSGPACK_ARRAY_LEN + 1))
        encoded = msgpack.packb(large_array)
        with pytest.raises(PayloadDecodeError):
            decode_payload(encoded)

    def test_decode_rejects_oversized_map(self):
        """decode_payload should reject maps exceeding MAX_MSGPACK_MAP_LEN."""
        import msgpack

        # Create dict larger than limit
        large_dict = {f"key_{i}": i for i in range(MAX_MSGPACK_MAP_LEN + 1)}
        encoded = msgpack.packb(large_dict)
        with pytest.raises(PayloadDecodeError):
            decode_payload(encoded)


class TestConvenienceFunctions:
    """Tests for message creation convenience functions."""

    def test_create_ping(self):
        """create_ping should create valid PING envelope."""
        envelope = create_ping()
        assert envelope.version == STYRENE_VERSION
        assert envelope.message_type == StyreneMessageType.PING
        assert envelope.payload == b""

    def test_create_pong(self):
        """create_pong should create valid PONG envelope."""
        envelope = create_pong()
        assert envelope.version == STYRENE_VERSION
        assert envelope.message_type == StyreneMessageType.PONG
        assert envelope.payload == b""

    def test_create_status_request(self):
        """create_status_request should create valid STATUS_REQUEST envelope."""
        envelope = create_status_request()
        assert envelope.version == STYRENE_VERSION
        assert envelope.message_type == StyreneMessageType.STATUS_REQUEST
        assert envelope.payload == b""

    def test_create_status_response(self):
        """create_status_response should encode status data."""
        status = {"online": True, "uptime": 3600}
        envelope = create_status_response(status)
        assert envelope.version == STYRENE_VERSION
        assert envelope.message_type == StyreneMessageType.STATUS_RESPONSE
        decoded = decode_payload(envelope.payload)
        assert decoded == status

    def test_create_chat(self):
        """create_chat should encode chat message."""
        envelope = create_chat("Hello, mesh!")
        assert envelope.version == STYRENE_VERSION
        assert envelope.message_type == StyreneMessageType.CHAT
        decoded = decode_payload(envelope.payload)
        assert decoded["text"] == "Hello, mesh!"

    def test_create_announce(self):
        """create_announce should encode identity data."""
        identity = {"name": "node-alpha", "capabilities": ["chat", "rpc"]}
        envelope = create_announce(identity)
        assert envelope.version == STYRENE_VERSION
        assert envelope.message_type == StyreneMessageType.ANNOUNCE
        decoded = decode_payload(envelope.payload)
        assert decoded == identity


class TestWireFormatIntegration:
    """Integration tests for wire format with LXMF-style usage."""

    def test_full_roundtrip_chat_message(self):
        """Full roundtrip: create -> encode -> decode -> extract."""
        # Create chat message
        original_text = "Test message over RNS"
        envelope = create_chat(original_text)

        # Encode to wire format (this is what LXMF would transmit)
        wire_data = envelope.encode()

        # Verify it's identifiable
        assert StyreneEnvelope.is_styrene_message(wire_data)
        assert wire_data.startswith(b"styrene.io:")

        # Decode envelope
        decoded = StyreneEnvelope.decode(wire_data)
        assert decoded.message_type == StyreneMessageType.CHAT

        # Extract payload
        payload = decode_payload(decoded.payload)
        assert payload["text"] == original_text

    def test_wire_format_is_binary_after_prefix(self):
        """Wire format should be binary (non-printable) after prefix."""
        envelope = create_status_response({"data": "value"})
        wire_data = envelope.encode()

        # Prefix is ASCII
        prefix_part = wire_data[: len(STYRENE_PREFIX)]
        assert prefix_part.decode("ascii") == "styrene.io:"

        # After prefix contains non-ASCII (version, type, msgpack)
        binary_part = wire_data[len(STYRENE_PREFIX) :]
        # Should have at least version + type
        assert len(binary_part) >= 2

    def test_minimum_message_length(self):
        """Minimum valid message should be prefix + version + type + request_id (v2)."""
        from styrened.models.styrene_wire import MIN_MESSAGE_LENGTH_V2
        envelope = create_ping()
        encoded = envelope.encode()
        # create_ping() creates a v2 message with request_id (16 bytes)
        assert len(encoded) == MIN_MESSAGE_LENGTH_V2

    def test_non_styrene_client_sees_prefix(self):
        """Non-Styrene client receiving message sees identifiable prefix.

        This simulates what a NomadNet or other LXMF client would see
        when receiving a Styrene message - they can't decode it, but
        they can see it's from Styrene.
        """
        envelope = create_chat("Secret styrene message")
        wire_data = envelope.encode()

        # A non-Styrene client would try to decode as text
        # The prefix is readable, rest is binary garbage
        try:
            as_text = wire_data.decode("utf-8", errors="replace")
            assert as_text.startswith("styrene.io:")
            # Contains replacement characters for binary data
            assert "\ufffd" in as_text or len(as_text) > len("styrene.io:")
        except UnicodeDecodeError:
            # This is also acceptable - binary data
            pass
