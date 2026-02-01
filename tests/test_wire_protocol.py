"""Smoke tests for styrene wire protocol."""


from styrened.models.styrene_wire import (
    StyreneEnvelope,
    StyreneMessageType,
    create_chat,
    create_ping,
    create_pong,
    decode_payload,
    encode_payload,
)


def test_ping_pong_encoding() -> None:
    """Ping/pong messages should encode and decode."""
    ping = create_ping()
    assert ping.message_type == StyreneMessageType.PING
    assert ping.payload == b""

    pong = create_pong()
    assert pong.message_type == StyreneMessageType.PONG
    assert pong.payload == b""


def test_envelope_roundtrip() -> None:
    """Envelope should encode and decode correctly."""
    original = create_chat("Hello, world!")
    wire_data = original.encode()

    decoded = StyreneEnvelope.decode(wire_data)
    assert decoded.message_type == StyreneMessageType.CHAT
    assert decoded.version == original.version

    # Decode payload
    payload_data = decode_payload(decoded.payload)
    assert payload_data["text"] == "Hello, world!"


def test_payload_encoding() -> None:
    """Payload encoding should handle various types."""
    data = {"key": "value", "number": 42, "list": [1, 2, 3]}
    encoded = encode_payload(data)
    decoded = decode_payload(encoded)
    assert decoded == data


def test_envelope_is_styrene_message() -> None:
    """is_styrene_message should detect valid messages."""
    envelope = create_ping()
    wire_data = envelope.encode()
    assert StyreneEnvelope.is_styrene_message(wire_data)
    assert not StyreneEnvelope.is_styrene_message(b"random data")
