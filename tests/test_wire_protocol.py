"""Smoke tests for styrene wire protocol."""


from styrened.models.styrene_wire import (
    StyreneEnvelope,
    StyreneMessageType,
    create_chat,
    create_ping,
    create_pong,
    create_self_update,
    create_self_update_result,
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


def test_self_update_roundtrip() -> None:
    """SELF_UPDATE envelope should encode and decode correctly."""
    original = create_self_update(version="1.2.3")
    wire_data = original.encode()

    decoded = StyreneEnvelope.decode(wire_data)
    assert decoded.message_type == StyreneMessageType.SELF_UPDATE
    assert decoded.version == original.version

    payload_data = decode_payload(decoded.payload)
    assert payload_data["version"] == "1.2.3"


def test_self_update_no_version() -> None:
    """SELF_UPDATE with no version should encode None."""
    original = create_self_update()
    wire_data = original.encode()

    decoded = StyreneEnvelope.decode(wire_data)
    assert decoded.message_type == StyreneMessageType.SELF_UPDATE

    payload_data = decode_payload(decoded.payload)
    assert payload_data["version"] is None


def test_self_update_result_roundtrip() -> None:
    """SELF_UPDATE_RESULT envelope should encode and decode correctly."""
    original = create_self_update_result(
        success=True,
        message="Updated from 0.10.5 to 0.10.6",
        old_version="0.10.5",
        new_version="0.10.6",
    )
    wire_data = original.encode()

    decoded = StyreneEnvelope.decode(wire_data)
    assert decoded.message_type == StyreneMessageType.SELF_UPDATE_RESULT

    payload_data = decode_payload(decoded.payload)
    assert payload_data["success"] is True
    assert payload_data["message"] == "Updated from 0.10.5 to 0.10.6"
    assert payload_data["old_version"] == "0.10.5"
    assert payload_data["new_version"] == "0.10.6"


def test_self_update_result_failure() -> None:
    """SELF_UPDATE_RESULT failure should omit new_version."""
    original = create_self_update_result(
        success=False,
        message="pip install failed",
        old_version="0.10.5",
    )
    wire_data = original.encode()

    decoded = StyreneEnvelope.decode(wire_data)
    payload_data = decode_payload(decoded.payload)
    assert payload_data["success"] is False
    assert "new_version" not in payload_data
