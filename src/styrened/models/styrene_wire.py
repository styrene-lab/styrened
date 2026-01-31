"""Styrene wire format for RPC messages over RNS/LXMF.

This module defines the binary wire format for Styrene-specific messages
that travel over the Reticulum network via LXMF. Messages are stored in
LXMF's FIELD_CUSTOM_DATA field, with FIELD_CUSTOM_TYPE set to "styrene.io".

Wire Format (stored in FIELD_CUSTOM_DATA):
    [PREFIX][VERSION:1][TYPE:1][PAYLOAD:N]

    PREFIX: b"styrene.io:" (11 bytes) - redundant identifier for validation
    VERSION: uint8 - protocol version for future compatibility
    TYPE: uint8 - StyreneMessageType enum value
    PAYLOAD: bytes - msgpack-encoded payload (message-type specific)

LXMF Integration:
    FIELD_CUSTOM_TYPE (0xFB): b"styrene.io" - protocol identifier
    FIELD_CUSTOM_DATA (0xFC): this wire format
    content: human-readable summary like "[styrene.io:CHAT]"

The prefix is retained in the wire format for:
    1. Defense-in-depth validation
    2. Standalone message verification
    3. Debugging and logging clarity

Design Decisions:
    - msgpack chosen over protobuf: RNS/LXMF use msgpack internally,
      no additional dependencies needed, and it's compact binary
    - Uses LXMF FIELD_CUSTOM_TYPE/DATA: proper protocol encapsulation
      per LXMF documentation
    - Single-byte version and type: Keeps overhead minimal for constrained
      networks (LoRa, packet radio)
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import msgpack

# Wire format constants
STYRENE_PREFIX: bytes = b"styrene.io:"
STYRENE_VERSION: int = 1

# Minimum valid message: prefix + version + type + empty payload
MIN_MESSAGE_LENGTH: int = len(STYRENE_PREFIX) + 2

# Security limits - based on RNS/LXMF constraints
# LXMF propagated messages max 256KB, opportunistic ~295 bytes
MAX_PAYLOAD_SIZE: int = 262144  # 256KB
MAX_MSGPACK_MAP_LEN: int = 1000
MAX_MSGPACK_ARRAY_LEN: int = 10000
MAX_MSGPACK_STR_LEN: int = 65536


class StyreneMessageType(IntEnum):
    """Message types for Styrene RPC protocol.

    Values are chosen to leave room for future expansion:
    - 0x00: Reserved
    - 0x01-0x0F: Control messages (ping/pong, heartbeat)
    - 0x10-0x1F: Status/query messages
    - 0x20-0x2F: Content messages (chat, data)
    - 0x30-0x3F: Network messages (announce, discover)
    - 0x40-0xFF: Reserved for future use
    """

    # Control messages
    PING = 0x01
    PONG = 0x02

    # Status messages
    STATUS_REQUEST = 0x10
    STATUS_RESPONSE = 0x11

    # Content messages
    CHAT = 0x20

    # Network messages
    ANNOUNCE = 0x30


class StyreneWireError(Exception):
    """Base exception for wire format errors."""

    pass


class InvalidPrefixError(StyreneWireError):
    """Raised when message doesn't start with styrene.io: prefix."""

    pass


class UnsupportedVersionError(StyreneWireError):
    """Raised when message version is not supported."""

    pass


class InvalidMessageTypeError(StyreneWireError):
    """Raised when message type is not recognized."""

    pass


class PayloadDecodeError(StyreneWireError):
    """Raised when payload cannot be decoded."""

    pass


@dataclass
class StyreneEnvelope:
    """Envelope for Styrene RPC messages.

    The envelope wraps a typed payload with version information,
    providing a consistent wire format for all Styrene messages.

    Attributes:
        version: Protocol version (currently 1, must be 0-255)
        message_type: Type of message (determines payload interpretation)
        payload: Raw bytes payload (msgpack-encoded data, decoded by handlers)

    Example:
        >>> # Create a ping message
        >>> envelope = StyreneEnvelope(
        ...     version=STYRENE_VERSION,
        ...     message_type=StyreneMessageType.PING,
        ...     payload=b""
        ... )
        >>> wire_data = envelope.encode()
        >>> decoded = StyreneEnvelope.decode(wire_data)
        >>> assert decoded.message_type == StyreneMessageType.PING
    """

    version: int
    message_type: StyreneMessageType
    payload: bytes

    def __post_init__(self) -> None:
        """Validate envelope fields after initialization."""
        if not 0 <= self.version <= 255:
            raise ValueError(f"version must be 0-255, got {self.version}")
        if len(self.payload) > MAX_PAYLOAD_SIZE:
            raise ValueError(f"payload too large: {len(self.payload)} > {MAX_PAYLOAD_SIZE}")

    def encode(self) -> bytes:
        """Encode envelope to wire format.

        Returns:
            bytes: Wire-format encoded message with styrene.io prefix

        Example:
            >>> env = StyreneEnvelope(1, StyreneMessageType.PING, b"")
            >>> data = env.encode()
            >>> data.startswith(b"styrene.io:")
            True
        """
        return STYRENE_PREFIX + bytes([self.version]) + bytes([self.message_type]) + self.payload

    @classmethod
    def decode(cls, data: bytes) -> "StyreneEnvelope":
        """Decode wire format to envelope.

        Args:
            data: Wire-format encoded message

        Returns:
            StyreneEnvelope: Decoded envelope

        Raises:
            InvalidPrefixError: If data doesn't start with styrene.io:
            UnsupportedVersionError: If version is not supported
            InvalidMessageTypeError: If message type is not recognized
        """
        # Validate minimum length
        if len(data) < MIN_MESSAGE_LENGTH:
            raise InvalidPrefixError(
                f"Message too short: {len(data)} bytes, minimum {MIN_MESSAGE_LENGTH}"
            )

        # Validate prefix
        if not data.startswith(STYRENE_PREFIX):
            raise InvalidPrefixError(
                f"Invalid prefix: expected {STYRENE_PREFIX!r}, got {data[:11]!r}"
            )

        # Extract header fields
        offset = len(STYRENE_PREFIX)
        version = data[offset]
        message_type_value = data[offset + 1]
        payload = data[offset + 2 :]

        # Validate version
        if version != STYRENE_VERSION:
            raise UnsupportedVersionError(
                f"Unsupported version: {version}, expected {STYRENE_VERSION}"
            )

        # Validate message type
        try:
            message_type = StyreneMessageType(message_type_value)
        except ValueError:
            raise InvalidMessageTypeError(f"Unknown message type: 0x{message_type_value:02x}")

        return cls(version=version, message_type=message_type, payload=payload)

    @classmethod
    def is_styrene_message(cls, data: bytes) -> bool:
        """Check if data is a Styrene message (starts with prefix).

        Args:
            data: Raw message bytes

        Returns:
            bool: True if data starts with styrene.io: prefix
        """
        return data.startswith(STYRENE_PREFIX)


def encode_payload(data: Any) -> bytes:
    """Encode arbitrary data as msgpack payload.

    Args:
        data: Any msgpack-serializable data (dict, list, str, int, etc.)

    Returns:
        bytes: msgpack-encoded bytes

    Example:
        >>> payload = encode_payload({"status": "online", "uptime": 3600})
        >>> isinstance(payload, bytes)
        True
    """
    result: bytes = msgpack.packb(data, use_bin_type=True)
    return result


def decode_payload(data: bytes) -> Any:
    """Decode msgpack payload to Python object.

    Args:
        data: msgpack-encoded bytes

    Returns:
        Decoded Python object

    Raises:
        PayloadDecodeError: If payload cannot be decoded or exceeds size limits

    Example:
        >>> payload = encode_payload({"key": "value"})
        >>> decoded = decode_payload(payload)
        >>> decoded["key"]
        'value'
    """
    # Validate payload size before decoding
    if len(data) > MAX_PAYLOAD_SIZE:
        raise PayloadDecodeError(f"Payload too large: {len(data)} > {MAX_PAYLOAD_SIZE}")

    try:
        # Use strict parameters to prevent deserialization attacks
        return msgpack.unpackb(
            data,
            raw=False,
            strict_map_key=True,  # Reject non-string map keys
            max_map_len=MAX_MSGPACK_MAP_LEN,
            max_array_len=MAX_MSGPACK_ARRAY_LEN,
            max_str_len=MAX_MSGPACK_STR_LEN,
            max_bin_len=MAX_PAYLOAD_SIZE,
            max_ext_len=MAX_PAYLOAD_SIZE,
        )
    except Exception as e:
        raise PayloadDecodeError(f"Failed to decode payload: {e}") from e


# Convenience functions for creating common message types


def create_ping() -> StyreneEnvelope:
    """Create a PING message envelope.

    Returns:
        StyreneEnvelope configured as PING message
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.PING,
        payload=b"",
    )


def create_pong() -> StyreneEnvelope:
    """Create a PONG message envelope.

    Returns:
        StyreneEnvelope configured as PONG message
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.PONG,
        payload=b"",
    )


def create_status_request() -> StyreneEnvelope:
    """Create a STATUS_REQUEST message envelope.

    Returns:
        StyreneEnvelope configured as STATUS_REQUEST message
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.STATUS_REQUEST,
        payload=b"",
    )


def create_status_response(status_data: dict[str, Any]) -> StyreneEnvelope:
    """Create a STATUS_RESPONSE message envelope.

    Args:
        status_data: Dictionary containing status information

    Returns:
        StyreneEnvelope configured as STATUS_RESPONSE with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.STATUS_RESPONSE,
        payload=encode_payload(status_data),
    )


def create_chat(message: str) -> StyreneEnvelope:
    """Create a CHAT message envelope.

    Args:
        message: Chat message text

    Returns:
        StyreneEnvelope configured as CHAT with encoded message
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.CHAT,
        payload=encode_payload({"text": message}),
    )


def create_announce(identity_data: dict[str, Any]) -> StyreneEnvelope:
    """Create an ANNOUNCE message envelope.

    Args:
        identity_data: Dictionary containing identity/capability information

    Returns:
        StyreneEnvelope configured as ANNOUNCE with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.ANNOUNCE,
        payload=encode_payload(identity_data),
    )
