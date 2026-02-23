"""IPC wire protocol for control socket communication.

Defines the message types and wire format for CLI/TUI communication
with the styrened daemon over Unix sockets.

Wire Format:
    [LENGTH:4][TYPE:1][REQUEST_ID:16][PAYLOAD:N]

    LENGTH:     uint32 big-endian, total bytes following (TYPE + REQUEST_ID + PAYLOAD)
    TYPE:       uint8, IPCMessageType enum value
    REQUEST_ID: 16 bytes, correlation token for request/response matching
    PAYLOAD:    msgpack-encoded dict (message-type specific)

Usage:
    from styrened.ipc.protocol import (
        IPCMessageType,
        encode_frame,
        decode_frame,
        generate_request_id,
    )

    # Encode a request
    request_id = generate_request_id()
    frame = encode_frame(IPCMessageType.QUERY_DEVICES, request_id, {})

    # Decode a response
    msg_type, req_id, payload = decode_frame(data)
"""

import os
import struct
from enum import IntEnum

import msgpack

# Frame header sizes
LENGTH_SIZE = 4  # uint32 big-endian
TYPE_SIZE = 1  # uint8
REQUEST_ID_SIZE = 16  # 16 random bytes
HEADER_SIZE = TYPE_SIZE + REQUEST_ID_SIZE  # 17 bytes (length not included)

# Maximum payload size (4MB — nodes on public networks accumulate large device stores)
MAX_PAYLOAD_SIZE = 4 * 1024 * 1024


class IPCMessageType(IntEnum):
    """IPC message types for control socket protocol."""

    # Keepalive
    PING = 0x01
    PONG = 0x80

    # Query requests (0x10-0x1F)
    QUERY_DEVICES = 0x10
    QUERY_IDENTITY = 0x11
    QUERY_STATUS = 0x12
    QUERY_CONFIG = 0x13
    QUERY_CONVERSATIONS = 0x14
    QUERY_MESSAGES = 0x15
    QUERY_SEARCH_MESSAGES = 0x16
    QUERY_CONTACTS = 0x17
    QUERY_RESOLVE_NAME = 0x18
    QUERY_AUTO_REPLY = 0x19
    QUERY_PATH_INFO = 0x1A
    QUERY_PAGE = 0x1B

    # Command requests (0x20-0x2F)
    CMD_SEND = 0x20
    CMD_EXEC = 0x21
    CMD_ANNOUNCE = 0x22
    CMD_DEVICE_STATUS = 0x23
    CMD_SEND_CHAT = 0x24
    CMD_MARK_READ = 0x25
    CMD_DELETE_CONVERSATION = 0x26
    CMD_DELETE_MESSAGE = 0x27
    CMD_RETRY_MESSAGE = 0x28
    CMD_SET_CONTACT = 0x29
    CMD_REMOVE_CONTACT = 0x2A
    CMD_SET_AUTO_REPLY = 0x2B
    CMD_SYNC_MESSAGES = 0x2C
    CMD_PAGE_DISCONNECT = 0x2D
    CMD_REBOOT_DEVICE = 0x2E

    # Subscription requests (0x30-0x3F) - for TUI
    SUB_DEVICES = 0x30
    SUB_MESSAGES = 0x31
    UNSUB = 0x3F

    # Responses (0x80-0x8F)
    RESULT = 0x81
    ERROR = 0x82

    # Events (0xC0-0xFF) - pushed to subscribers
    EVENT_DEVICE = 0xC0
    EVENT_MESSAGE = 0xC1


class IPCError(Exception):
    """Base exception for IPC protocol errors."""

    pass


class FrameDecodeError(IPCError):
    """Error decoding an IPC frame."""

    pass


class FrameReadTimeoutError(IPCError):
    """Timeout reading an IPC frame."""

    pass


class PayloadTooLargeError(IPCError):
    """Payload exceeds maximum allowed size."""

    pass


# Default read timeout in seconds (None = no timeout for backwards compatibility)
DEFAULT_READ_TIMEOUT: float | None = None


def generate_request_id() -> bytes:
    """Generate a random 16-byte request ID for correlation.

    Returns:
        16 random bytes suitable for request/response matching.
    """
    return os.urandom(REQUEST_ID_SIZE)


def encode_frame(
    msg_type: IPCMessageType,
    request_id: bytes,
    payload: dict,
) -> bytes:
    """Encode an IPC message into wire format.

    Args:
        msg_type: Message type enum value.
        request_id: 16-byte correlation ID.
        payload: Dict to msgpack-encode as payload.

    Returns:
        Complete frame bytes ready for transmission.

    Raises:
        ValueError: If request_id is not 16 bytes.
        PayloadTooLargeError: If encoded payload exceeds MAX_PAYLOAD_SIZE.
    """
    if len(request_id) != REQUEST_ID_SIZE:
        raise ValueError(f"request_id must be {REQUEST_ID_SIZE} bytes, got {len(request_id)}")

    # Encode payload
    payload_bytes = msgpack.packb(payload, use_bin_type=True)

    if len(payload_bytes) > MAX_PAYLOAD_SIZE:
        raise PayloadTooLargeError(
            f"Payload size {len(payload_bytes)} exceeds maximum {MAX_PAYLOAD_SIZE}"
        )

    # Calculate total length (type + request_id + payload)
    total_length = TYPE_SIZE + REQUEST_ID_SIZE + len(payload_bytes)

    # Build frame
    frame = bytearray()
    frame.extend(struct.pack(">I", total_length))  # 4 bytes, big-endian
    frame.append(msg_type)  # 1 byte
    frame.extend(request_id)  # 16 bytes
    frame.extend(payload_bytes)  # N bytes

    return bytes(frame)


def decode_frame(data: bytes) -> tuple[IPCMessageType, bytes, dict]:
    """Decode an IPC frame from wire format.

    Expects complete frame data including length prefix.

    Args:
        data: Complete frame bytes.

    Returns:
        Tuple of (message_type, request_id, payload_dict).

    Raises:
        FrameDecodeError: If frame is malformed.
    """
    if len(data) < LENGTH_SIZE:
        raise FrameDecodeError(f"Frame too short for length: {len(data)} bytes")

    # Parse length
    total_length = struct.unpack(">I", data[:LENGTH_SIZE])[0]

    if len(data) < LENGTH_SIZE + total_length:
        raise FrameDecodeError(
            f"Frame incomplete: expected {LENGTH_SIZE + total_length}, got {len(data)}"
        )

    # Parse header
    offset = LENGTH_SIZE
    msg_type_byte = data[offset]
    offset += TYPE_SIZE

    try:
        msg_type = IPCMessageType(msg_type_byte)
    except ValueError as e:
        raise FrameDecodeError(f"Unknown message type: 0x{msg_type_byte:02x}") from e

    request_id = data[offset : offset + REQUEST_ID_SIZE]
    offset += REQUEST_ID_SIZE

    # Parse payload
    payload_bytes = data[offset : LENGTH_SIZE + total_length]

    try:
        payload = msgpack.unpackb(payload_bytes, raw=False)
    except Exception as e:
        raise FrameDecodeError(f"Failed to decode payload: {e}") from e

    if not isinstance(payload, dict):
        raise FrameDecodeError(f"Payload must be dict, got {type(payload).__name__}")

    return msg_type, request_id, payload


async def read_frame(
    reader,
    timeout: float | None = DEFAULT_READ_TIMEOUT,
) -> tuple[IPCMessageType, bytes, dict]:
    """Read a complete IPC frame from an asyncio StreamReader.

    Args:
        reader: asyncio.StreamReader to read from.
        timeout: Read timeout in seconds. None means no timeout.
                 Default is DEFAULT_READ_TIMEOUT.

    Returns:
        Tuple of (message_type, request_id, payload_dict).

    Raises:
        FrameDecodeError: If frame is malformed.
        FrameReadTimeoutError: If read times out.
        asyncio.IncompleteReadError: If connection is closed.
    """
    import asyncio

    async def _read_with_timeout(coro):
        """Wrap a coroutine with optional timeout."""
        if timeout is None:
            return await coro
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError as e:
            raise FrameReadTimeoutError(f"Read timed out after {timeout}s") from e

    # Read length prefix
    length_bytes = await _read_with_timeout(reader.readexactly(LENGTH_SIZE))
    total_length = struct.unpack(">I", length_bytes)[0]

    if total_length > MAX_PAYLOAD_SIZE + HEADER_SIZE:
        raise FrameDecodeError(f"Frame too large: {total_length} bytes")

    # Read rest of frame
    frame_data = await _read_with_timeout(reader.readexactly(total_length))

    # Parse header
    msg_type_byte = frame_data[0]
    try:
        msg_type = IPCMessageType(msg_type_byte)
    except ValueError as e:
        raise FrameDecodeError(f"Unknown message type: 0x{msg_type_byte:02x}") from e

    request_id = frame_data[TYPE_SIZE : TYPE_SIZE + REQUEST_ID_SIZE]

    # Parse payload
    payload_bytes = frame_data[TYPE_SIZE + REQUEST_ID_SIZE :]

    try:
        payload = msgpack.unpackb(payload_bytes, raw=False)
    except Exception as e:
        raise FrameDecodeError(f"Failed to decode payload: {e}") from e

    if not isinstance(payload, dict):
        raise FrameDecodeError(f"Payload must be dict, got {type(payload).__name__}")

    return msg_type, request_id, payload


async def write_frame(
    writer,
    msg_type: IPCMessageType,
    request_id: bytes,
    payload: dict,
) -> None:
    """Write an IPC frame to an asyncio StreamWriter.

    Args:
        writer: asyncio.StreamWriter to write to.
        msg_type: Message type enum value.
        request_id: 16-byte correlation ID.
        payload: Dict to msgpack-encode as payload.
    """
    frame = encode_frame(msg_type, request_id, payload)
    writer.write(frame)
    await writer.drain()


def is_request_type(msg_type: IPCMessageType) -> bool:
    """Check if message type is a request (needs response).

    Args:
        msg_type: Message type to check.

    Returns:
        True if this is a request type.
    """
    return msg_type.value < 0x80


def is_response_type(msg_type: IPCMessageType) -> bool:
    """Check if message type is a response.

    Args:
        msg_type: Message type to check.

    Returns:
        True if this is a response type (PONG, RESULT, ERROR).
    """
    return msg_type in (IPCMessageType.PONG, IPCMessageType.RESULT, IPCMessageType.ERROR)


def is_event_type(msg_type: IPCMessageType) -> bool:
    """Check if message type is an event (pushed to subscribers).

    Args:
        msg_type: Message type to check.

    Returns:
        True if this is an event type.
    """
    return msg_type.value >= 0xC0
