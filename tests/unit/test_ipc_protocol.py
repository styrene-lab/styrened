"""Unit tests for IPC protocol module."""
from __future__ import annotations

import asyncio

import pytest

from styrened.ipc.protocol import (
    DEFAULT_READ_TIMEOUT,
    LENGTH_SIZE,
    MAX_PAYLOAD_SIZE,
    REQUEST_ID_SIZE,
    FrameDecodeError,
    FrameReadTimeoutError,
    IPCMessageType,
    PayloadTooLargeError,
    decode_frame,
    encode_frame,
    generate_request_id,
    is_event_type,
    is_request_type,
    is_response_type,
    read_frame,
)


class TestGenerateRequestId:
    """Tests for generate_request_id()."""

    def test_returns_bytes(self):
        """Request ID should be bytes."""
        req_id = generate_request_id()
        assert isinstance(req_id, bytes)

    def test_correct_length(self):
        """Request ID should be 16 bytes."""
        req_id = generate_request_id()
        assert len(req_id) == REQUEST_ID_SIZE

    def test_unique(self):
        """Each request ID should be unique."""
        ids = {generate_request_id() for _ in range(100)}
        assert len(ids) == 100


class TestEncodeFrame:
    """Tests for encode_frame()."""

    def test_basic_encoding(self):
        """Basic frame encoding should work."""
        req_id = generate_request_id()
        payload = {"key": "value"}

        frame = encode_frame(IPCMessageType.QUERY_DEVICES, req_id, payload)

        assert isinstance(frame, bytes)
        # Should have length prefix + type + request_id + payload
        assert len(frame) > LENGTH_SIZE + 1 + REQUEST_ID_SIZE

    def test_empty_payload(self):
        """Empty payload should encode correctly."""
        req_id = generate_request_id()
        frame = encode_frame(IPCMessageType.PING, req_id, {})
        assert isinstance(frame, bytes)

    def test_invalid_request_id_length(self):
        """Should raise ValueError for wrong request_id length."""
        with pytest.raises(ValueError, match="must be 16 bytes"):
            encode_frame(IPCMessageType.PING, b"short", {})

    def test_payload_too_large(self):
        """Should raise PayloadTooLargeError for huge payload."""
        req_id = generate_request_id()
        huge_payload = {"data": "x" * (MAX_PAYLOAD_SIZE + 1)}

        with pytest.raises(PayloadTooLargeError):
            encode_frame(IPCMessageType.QUERY_DEVICES, req_id, huge_payload)


class TestDecodeFrame:
    """Tests for decode_frame()."""

    def test_round_trip(self):
        """Encode then decode should return original values."""
        req_id = generate_request_id()
        payload = {"foo": "bar", "num": 42}

        frame = encode_frame(IPCMessageType.QUERY_STATUS, req_id, payload)
        msg_type, decoded_id, decoded_payload = decode_frame(frame)

        assert msg_type == IPCMessageType.QUERY_STATUS
        assert decoded_id == req_id
        assert decoded_payload == payload

    def test_all_message_types(self):
        """All message types should round-trip correctly."""
        req_id = generate_request_id()

        for msg_type in IPCMessageType:
            frame = encode_frame(msg_type, req_id, {"type": msg_type.name})
            decoded_type, _, decoded_payload = decode_frame(frame)
            assert decoded_type == msg_type
            assert decoded_payload["type"] == msg_type.name

    def test_frame_too_short(self):
        """Should raise FrameDecodeError for truncated frame."""
        with pytest.raises(FrameDecodeError, match="too short"):
            decode_frame(b"\x00\x00")

    def test_frame_incomplete(self):
        """Should raise FrameDecodeError for incomplete frame."""
        req_id = generate_request_id()
        frame = encode_frame(IPCMessageType.PING, req_id, {})
        # Truncate the frame
        truncated = frame[: len(frame) - 5]

        with pytest.raises(FrameDecodeError, match="incomplete"):
            decode_frame(truncated)

    def test_unknown_message_type(self):
        """Should raise FrameDecodeError for unknown message type."""
        import struct

        # Create a frame with invalid message type (0xFE)
        req_id = generate_request_id()
        payload = b"\x80"  # msgpack empty dict
        total_len = 1 + REQUEST_ID_SIZE + len(payload)

        frame = struct.pack(">I", total_len) + bytes([0xFE]) + req_id + payload

        with pytest.raises(FrameDecodeError, match="Unknown message type"):
            decode_frame(frame)

    def test_invalid_payload(self):
        """Should raise FrameDecodeError for malformed msgpack."""
        import struct

        req_id = generate_request_id()
        # Invalid msgpack data
        bad_payload = b"\xff\xff\xff"
        total_len = 1 + REQUEST_ID_SIZE + len(bad_payload)

        frame = struct.pack(">I", total_len) + bytes([0x01]) + req_id + bad_payload

        with pytest.raises(FrameDecodeError, match="Failed to decode"):
            decode_frame(frame)


class TestMessageTypeChecks:
    """Tests for message type classification functions."""

    def test_request_types(self):
        """Request types should be identified correctly."""
        assert is_request_type(IPCMessageType.PING)
        assert is_request_type(IPCMessageType.QUERY_DEVICES)
        assert is_request_type(IPCMessageType.CMD_SEND)
        assert not is_request_type(IPCMessageType.RESULT)
        assert not is_request_type(IPCMessageType.EVENT_DEVICE)

    def test_response_types(self):
        """Response types should be identified correctly."""
        assert is_response_type(IPCMessageType.PONG)
        assert is_response_type(IPCMessageType.RESULT)
        assert is_response_type(IPCMessageType.ERROR)
        assert not is_response_type(IPCMessageType.PING)
        assert not is_response_type(IPCMessageType.EVENT_DEVICE)

    def test_event_types(self):
        """Event types should be identified correctly."""
        assert is_event_type(IPCMessageType.EVENT_DEVICE)
        assert is_event_type(IPCMessageType.EVENT_MESSAGE)
        assert not is_event_type(IPCMessageType.PING)
        assert not is_event_type(IPCMessageType.RESULT)


class TestReadFrame:
    """Tests for async read_frame() with timeout support."""

    @pytest.mark.asyncio
    async def test_read_frame_success(self):
        """read_frame should successfully read a complete frame."""
        req_id = generate_request_id()
        payload = {"test": "data"}
        frame = encode_frame(IPCMessageType.PING, req_id, payload)

        # Create a mock reader with the frame data
        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()

        msg_type, decoded_id, decoded_payload = await read_frame(reader)

        assert msg_type == IPCMessageType.PING
        assert decoded_id == req_id
        assert decoded_payload == payload

    @pytest.mark.asyncio
    async def test_read_frame_with_explicit_timeout(self):
        """read_frame should accept explicit timeout parameter."""
        req_id = generate_request_id()
        frame = encode_frame(IPCMessageType.PONG, req_id, {})

        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()

        # Should succeed with explicit timeout
        msg_type, _, _ = await read_frame(reader, timeout=5.0)
        assert msg_type == IPCMessageType.PONG

    @pytest.mark.asyncio
    async def test_read_frame_timeout_on_no_data(self):
        """read_frame should raise FrameReadTimeoutError when no data arrives."""
        reader = asyncio.StreamReader()
        # Don't feed any data - simulate a peer that doesn't respond

        with pytest.raises(FrameReadTimeoutError, match="timed out"):
            await read_frame(reader, timeout=0.05)

    @pytest.mark.asyncio
    async def test_read_frame_timeout_on_partial_data(self):
        """read_frame should timeout if only partial data arrives."""
        reader = asyncio.StreamReader()
        # Feed only the length prefix, not the full frame
        reader.feed_data(b"\x00\x00\x00\x10")  # Length says 16 bytes follow

        with pytest.raises(FrameReadTimeoutError, match="timed out"):
            await read_frame(reader, timeout=0.05)

    @pytest.mark.asyncio
    async def test_read_frame_no_timeout(self):
        """read_frame with timeout=None should not timeout."""
        req_id = generate_request_id()
        frame = encode_frame(IPCMessageType.QUERY_STATUS, req_id, {"key": "value"})

        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()

        # timeout=None means no timeout
        msg_type, _, payload = await read_frame(reader, timeout=None)
        assert msg_type == IPCMessageType.QUERY_STATUS
        assert payload["key"] == "value"

    @pytest.mark.asyncio
    async def test_read_frame_incomplete_read_error(self):
        """read_frame should raise IncompleteReadError on connection close."""
        reader = asyncio.StreamReader()
        reader.feed_data(b"\x00\x00\x00\x10")  # Length says 16 bytes follow
        reader.feed_eof()  # But connection closed

        with pytest.raises(asyncio.IncompleteReadError):
            await read_frame(reader, timeout=None)

    @pytest.mark.asyncio
    async def test_read_frame_malformed_message_type(self):
        """read_frame should raise FrameDecodeError for invalid message type."""
        import struct

        req_id = generate_request_id()
        payload_bytes = b"\x80"  # msgpack empty dict
        total_len = 1 + REQUEST_ID_SIZE + len(payload_bytes)

        # Use invalid message type 0xFE
        frame = struct.pack(">I", total_len) + bytes([0xFE]) + req_id + payload_bytes

        reader = asyncio.StreamReader()
        reader.feed_data(frame)
        reader.feed_eof()

        with pytest.raises(FrameDecodeError, match="Unknown message type"):
            await read_frame(reader)

    def test_default_read_timeout_is_none(self):
        """DEFAULT_READ_TIMEOUT should be None for backwards compatibility."""
        assert DEFAULT_READ_TIMEOUT is None
