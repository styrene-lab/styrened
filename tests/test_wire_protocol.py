"""Smoke tests for styrene wire protocol."""
from __future__ import annotations

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


def test_file_offer_none_request_id_uses_no_correlation() -> None:
    """create_file_offer with request_id=None should use NO_CORRELATION.

    Regression test: create_file_offer previously passed request_id=None
    through literally, while create_file_accept used NO_CORRELATION.
    Both should now be consistent.
    """
    from styrened.models.styrene_wire import (
        NO_CORRELATION,
        create_file_offer,
    )

    envelope = create_file_offer(
        filename="test.txt",
        size=1024,
        request_id=None,
    )
    assert envelope.request_id == NO_CORRELATION


def test_file_offer_explicit_request_id_preserved() -> None:
    """create_file_offer with explicit request_id should preserve it."""
    import os

    from styrened.models.styrene_wire import create_file_offer

    rid = os.urandom(16)
    envelope = create_file_offer(
        filename="test.txt",
        size=1024,
        request_id=rid,
    )
    assert envelope.request_id == rid


def test_file_accept_none_request_id_uses_no_correlation() -> None:
    """create_file_accept with request_id=None should use NO_CORRELATION."""
    from styrened.models.styrene_wire import (
        NO_CORRELATION,
        create_file_accept,
    )

    envelope = create_file_accept(
        max_size=65536,
        request_id=None,
    )
    assert envelope.request_id == NO_CORRELATION
