"""Styrene wire format for RPC messages over RNS/LXMF.

This module defines the binary wire format for Styrene-specific messages
that travel over the Reticulum network via LXMF. Messages are stored in
LXMF's FIELD_CUSTOM_DATA field, with FIELD_CUSTOM_TYPE set to "styrene.io".

Wire Format v1 (stored in FIELD_CUSTOM_DATA):
    [PREFIX][VERSION:1][TYPE:1][PAYLOAD:N]

Wire Format v2 (stored in FIELD_CUSTOM_DATA):
    [PREFIX][VERSION:1][TYPE:1][REQUEST_ID:16][PAYLOAD:N]

    PREFIX: b"styrene.io:" (11 bytes) - redundant identifier for validation
    VERSION: uint8 - protocol version (1 or 2)
    TYPE: uint8 - StyreneMessageType enum value
    REQUEST_ID: 16 bytes - correlation token (v2 only)
        - Random bytes for request/response correlation
        - 16 zero bytes for fire-and-forget messages
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
    - REQUEST_ID uses random bytes (not UUID) to avoid fingerprinting
"""

import os
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

import msgpack

# Wire format constants
STYRENE_PREFIX: bytes = b"styrene.io:"
STYRENE_VERSION_1: int = 1  # Legacy: no request_id
STYRENE_VERSION_2: int = 2  # Current: with request_id
STYRENE_VERSION: int = STYRENE_VERSION_2  # Default for new messages

# Request ID constants
REQUEST_ID_LENGTH: int = 16
NO_CORRELATION: bytes = b"\x00" * REQUEST_ID_LENGTH  # Fire-and-forget marker

# Minimum valid message lengths
MIN_MESSAGE_LENGTH_V1: int = len(STYRENE_PREFIX) + 2  # prefix + version + type
MIN_MESSAGE_LENGTH_V2: int = len(STYRENE_PREFIX) + 2 + REQUEST_ID_LENGTH  # + request_id
MIN_MESSAGE_LENGTH: int = MIN_MESSAGE_LENGTH_V1  # For backward compat checks

# Security limits - based on RNS/LXMF constraints
# LXMF propagated messages max 256KB, opportunistic ~295 bytes
MAX_PAYLOAD_SIZE: int = 262144  # 256KB
MAX_MSGPACK_MAP_LEN: int = 1000
MAX_MSGPACK_ARRAY_LEN: int = 10000
MAX_MSGPACK_STR_LEN: int = 65536


class StyreneMessageType(IntEnum):
    """Message types for Styrene protocol.

    Allocation:
    - 0x00:       Reserved (invalid)
    - 0x01-0x0F:  Control/keepalive (15 types)
    - 0x10-0x1F:  Status/query (16 types)
    - 0x20-0x2F:  Content/chat (16 types)
    - 0x30-0x3F:  Network/discovery (16 types)
    - 0x40-0x5F:  RPC commands (32 types)
    - 0x60-0x7F:  RPC responses (32 types)
    - 0x80-0x9F:  Hub services (32 types)
    - 0xA0-0xBF:  Pub/Sub (32 types)
    - 0xC0-0xCF:  Terminal sessions (16 types)
    - 0xD0-0xD7:  PQC session (8 types)
    - 0xD8-0xDF:  Reserved/future (8 types)
    - 0xE0-0xFE:  Application-specific (31 types)
    - 0xFF:       Error
    """

    # Control messages (0x01-0x0F)
    PING = 0x01
    PONG = 0x02
    HEARTBEAT = 0x03

    # Status messages (0x10-0x1F)
    STATUS_REQUEST = 0x10
    STATUS_RESPONSE = 0x11
    CAPABILITIES_REQUEST = 0x12
    CAPABILITIES_RESPONSE = 0x13

    # Content messages (0x20-0x2F)
    CHAT = 0x20
    CHAT_ACK = 0x21
    FILE_OFFER = 0x22
    FILE_ACCEPT = 0x23
    FILE_CHUNK = 0x24

    # Network messages (0x30-0x3F)
    ANNOUNCE = 0x30
    ANNOUNCE_ACK = 0x31
    PEER_REQUEST = 0x32
    PEER_RESPONSE = 0x33

    # RPC Commands (0x40-0x5F)
    EXEC = 0x40
    REBOOT = 0x41
    CONFIG_UPDATE = 0x42
    SERVICE_CONTROL = 0x43
    INBOX_QUERY = 0x44
    MESSAGES_QUERY = 0x45
    SELF_UPDATE = 0x46

    # RPC Responses (0x60-0x7F)
    EXEC_RESULT = 0x60
    REBOOT_RESULT = 0x61
    CONFIG_RESULT = 0x62
    SERVICE_RESULT = 0x63
    INBOX_RESPONSE = 0x64
    MESSAGES_RESPONSE = 0x65
    SELF_UPDATE_RESULT = 0x66

    # Hub Services (0x80-0x9F)
    REGISTRY_QUERY = 0x80
    REGISTRY_RESPONSE = 0x81
    FLEET_STATUS_REQUEST = 0x82
    FLEET_STATUS_RESPONSE = 0x83

    # Pub/Sub (0xA0-0xBF)
    SUBSCRIBE = 0xA0
    UNSUBSCRIBE = 0xA1
    PUBLISH = 0xA2
    SUBSCRIPTION_ACK = 0xA3

    # Terminal Sessions (0xC0-0xCF) - Control plane via LXMF
    # Data plane uses RNS Link directly (not these message types)
    TERMINAL_REQUEST = 0xC0  # Request terminal session
    TERMINAL_ACCEPT = 0xC1  # Session accepted, provides Link destination
    TERMINAL_REJECT = 0xC2  # Session rejected (auth, resource, etc.)
    TERMINAL_RESIZE = 0xC3  # Window size change (can go over LXMF or Link)
    TERMINAL_SIGNAL = 0xC4  # Send signal to PTY (SIGINT, etc.)
    TERMINAL_CLOSE = 0xC5  # Graceful close request
    TERMINAL_CLOSED = 0xC6  # Session terminated (with exit code)

    # PQC Session (0xD0-0xD7) - Post-quantum hybrid key exchange
    PQC_INITIATE = 0xD0  # X25519 ephemeral + ML-KEM ciphertext + session_id
    PQC_RESPOND = 0xD1  # X25519 ephemeral + ML-KEM ciphertext + HMAC
    PQC_CONFIRM = 0xD2  # Confirmation HMAC, session established
    PQC_REKEY = 0xD3  # Initiate session rekeying
    PQC_DATA = 0xD4  # Encrypted payload wrapper
    PQC_CLOSE = 0xD5  # Close PQC session

    # Error (0xFF)
    ERROR = 0xFF


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


def generate_request_id() -> bytes:
    """Generate a random request ID for correlation.

    Returns:
        16 random bytes suitable for request/response correlation.
    """
    return os.urandom(REQUEST_ID_LENGTH)


@dataclass
class StyreneEnvelope:
    """Envelope for Styrene RPC messages.

    The envelope wraps a typed payload with version information and optional
    request correlation, providing a consistent wire format for all Styrene messages.

    Attributes:
        version: Protocol version (1 or 2, must be 0-255)
        message_type: Type of message (determines payload interpretation)
        payload: Raw bytes payload (msgpack-encoded data, decoded by handlers)
        request_id: 16-byte correlation token (v2 only, None for v1)
            - Random bytes: expects correlated response
            - NO_CORRELATION (16 zero bytes): fire-and-forget

    Example:
        >>> # Create a ping message (v2 with correlation)
        >>> envelope = StyreneEnvelope(
        ...     version=STYRENE_VERSION,
        ...     message_type=StyreneMessageType.PING,
        ...     payload=b"",
        ...     request_id=generate_request_id()
        ... )
        >>> wire_data = envelope.encode()
        >>> decoded = StyreneEnvelope.decode(wire_data)
        >>> assert decoded.message_type == StyreneMessageType.PING
        >>> assert decoded.request_id is not None
    """

    version: int
    message_type: StyreneMessageType
    payload: bytes
    request_id: bytes | None = field(default=None)

    def __post_init__(self) -> None:
        """Validate envelope fields after initialization."""
        if not 0 <= self.version <= 255:
            raise ValueError(f"version must be 0-255, got {self.version}")
        if len(self.payload) > MAX_PAYLOAD_SIZE:
            raise ValueError(f"payload too large: {len(self.payload)} > {MAX_PAYLOAD_SIZE}")
        if self.request_id is not None and len(self.request_id) != REQUEST_ID_LENGTH:
            raise ValueError(
                f"request_id must be {REQUEST_ID_LENGTH} bytes, got {len(self.request_id)}"
            )
        # v2 messages should have request_id, v1 should not
        if self.version == STYRENE_VERSION_2 and self.request_id is None:
            # Auto-generate for v2 if not provided
            self.request_id = generate_request_id()
        elif self.version == STYRENE_VERSION_1 and self.request_id is not None:
            raise ValueError("v1 messages cannot have request_id")

    @property
    def expects_response(self) -> bool:
        """Check if this message expects a correlated response.

        Returns:
            True if request_id is set and not NO_CORRELATION.
        """
        return self.request_id is not None and self.request_id != NO_CORRELATION

    def encode(self) -> bytes:
        """Encode envelope to wire format.

        Returns:
            bytes: Wire-format encoded message with styrene.io prefix

        Example:
            >>> env = StyreneEnvelope(2, StyreneMessageType.PING, b"")
            >>> data = env.encode()
            >>> data.startswith(b"styrene.io:")
            True
        """
        header = STYRENE_PREFIX + bytes([self.version]) + bytes([self.message_type])
        if self.version == STYRENE_VERSION_2:
            # v2: include request_id
            req_id = self.request_id if self.request_id else NO_CORRELATION
            return header + req_id + self.payload
        else:
            # v1: no request_id
            return header + self.payload

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
        # Validate minimum length for v1
        if len(data) < MIN_MESSAGE_LENGTH_V1:
            raise InvalidPrefixError(
                f"Message too short: {len(data)} bytes, minimum {MIN_MESSAGE_LENGTH_V1}"
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

        # Validate version
        if version not in (STYRENE_VERSION_1, STYRENE_VERSION_2):
            raise UnsupportedVersionError(
                f"Unsupported version: {version}, expected {STYRENE_VERSION_1} or {STYRENE_VERSION_2}"
            )

        # Validate message type
        try:
            message_type = StyreneMessageType(message_type_value)
        except ValueError as e:
            raise InvalidMessageTypeError(
                f"Unknown message type: 0x{message_type_value:02x}"
            ) from e

        # Parse based on version
        if version == STYRENE_VERSION_2:
            # v2: has request_id
            if len(data) < MIN_MESSAGE_LENGTH_V2:
                raise InvalidPrefixError(
                    f"v2 message too short: {len(data)} bytes, minimum {MIN_MESSAGE_LENGTH_V2}"
                )
            request_id = data[offset + 2 : offset + 2 + REQUEST_ID_LENGTH]
            payload = data[offset + 2 + REQUEST_ID_LENGTH :]
            return cls(
                version=version,
                message_type=message_type,
                payload=payload,
                request_id=request_id,
            )
        else:
            # v1: no request_id
            payload = data[offset + 2 :]
            return cls(version=version, message_type=message_type, payload=payload, request_id=None)

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


def create_ping(request_id: bytes | None = None) -> StyreneEnvelope:
    """Create a PING message envelope.

    Args:
        request_id: Optional correlation ID (auto-generated if None)

    Returns:
        StyreneEnvelope configured as PING message
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.PING,
        payload=b"",
        request_id=request_id,
    )


def create_pong(request_id: bytes | None = None) -> StyreneEnvelope:
    """Create a PONG message envelope.

    Args:
        request_id: Correlation ID from the PING being responded to

    Returns:
        StyreneEnvelope configured as PONG message
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.PONG,
        payload=b"",
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_status_request(request_id: bytes | None = None) -> StyreneEnvelope:
    """Create a STATUS_REQUEST message envelope.

    Args:
        request_id: Optional correlation ID (auto-generated if None)

    Returns:
        StyreneEnvelope configured as STATUS_REQUEST message
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.STATUS_REQUEST,
        payload=b"",
        request_id=request_id,
    )


def create_status_response(
    status_data: dict[str, Any], request_id: bytes | None = None
) -> StyreneEnvelope:
    """Create a STATUS_RESPONSE message envelope.

    Args:
        status_data: Dictionary containing status information
        request_id: Correlation ID from the request being responded to

    Returns:
        StyreneEnvelope configured as STATUS_RESPONSE with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.STATUS_RESPONSE,
        payload=encode_payload(status_data),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_chat(message: str, request_id: bytes | None = None) -> StyreneEnvelope:
    """Create a CHAT message envelope.

    Args:
        message: Chat message text
        request_id: Optional correlation ID (use NO_CORRELATION for fire-and-forget)

    Returns:
        StyreneEnvelope configured as CHAT with encoded message
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.CHAT,
        payload=encode_payload({"text": message}),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_announce(identity_data: dict[str, Any]) -> StyreneEnvelope:
    """Create an ANNOUNCE message envelope.

    Announces are fire-and-forget, so request_id is always NO_CORRELATION.

    Args:
        identity_data: Dictionary containing identity/capability information

    Returns:
        StyreneEnvelope configured as ANNOUNCE with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.ANNOUNCE,
        payload=encode_payload(identity_data),
        request_id=NO_CORRELATION,
    )


def create_error(error_code: int, message: str, request_id: bytes | None = None) -> StyreneEnvelope:
    """Create an ERROR message envelope.

    Args:
        error_code: Numeric error code
        message: Human-readable error message
        request_id: Correlation ID from the request that caused the error

    Returns:
        StyreneEnvelope configured as ERROR with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.ERROR,
        payload=encode_payload({"code": error_code, "message": message}),
        request_id=request_id if request_id else NO_CORRELATION,
    )


# RPC command/response convenience functions


def create_exec(command: str, args: list[str], request_id: bytes | None = None) -> StyreneEnvelope:
    """Create an EXEC command envelope.

    Args:
        command: Command to execute
        args: Command arguments
        request_id: Optional correlation ID (auto-generated if None)

    Returns:
        StyreneEnvelope configured as EXEC with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.EXEC,
        payload=encode_payload({"command": command, "args": args}),
        request_id=request_id,
    )


def create_exec_result(
    exit_code: int, stdout: str, stderr: str, request_id: bytes | None = None
) -> StyreneEnvelope:
    """Create an EXEC_RESULT response envelope.

    Args:
        exit_code: Command exit code
        stdout: Standard output
        stderr: Standard error
        request_id: Correlation ID from the EXEC request

    Returns:
        StyreneEnvelope configured as EXEC_RESULT with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.EXEC_RESULT,
        payload=encode_payload({"exit_code": exit_code, "stdout": stdout, "stderr": stderr}),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_reboot(delay: int = 0, request_id: bytes | None = None) -> StyreneEnvelope:
    """Create a REBOOT command envelope.

    Args:
        delay: Seconds to delay reboot (0 = immediate)
        request_id: Optional correlation ID (auto-generated if None)

    Returns:
        StyreneEnvelope configured as REBOOT with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.REBOOT,
        payload=encode_payload({"delay": delay}),
        request_id=request_id,
    )


def create_reboot_result(
    success: bool,
    message: str,
    scheduled_time: float | None = None,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a REBOOT_RESULT response envelope.

    Args:
        success: Whether reboot was scheduled successfully
        message: Human-readable result message
        scheduled_time: Unix timestamp of scheduled reboot (None if immediate)
        request_id: Correlation ID from the REBOOT request

    Returns:
        StyreneEnvelope configured as REBOOT_RESULT with encoded payload
    """
    payload_data: dict[str, Any] = {"success": success, "message": message}
    if scheduled_time is not None:
        payload_data["scheduled_time"] = scheduled_time
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.REBOOT_RESULT,
        payload=encode_payload(payload_data),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_config_update(
    updates: dict[str, Any], request_id: bytes | None = None
) -> StyreneEnvelope:
    """Create a CONFIG_UPDATE command envelope.

    Args:
        updates: Dictionary of config keys to update
        request_id: Optional correlation ID (auto-generated if None)

    Returns:
        StyreneEnvelope configured as CONFIG_UPDATE with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.CONFIG_UPDATE,
        payload=encode_payload({"updates": updates}),
        request_id=request_id,
    )


def create_config_result(
    success: bool, message: str, updated_keys: list[str], request_id: bytes | None = None
) -> StyreneEnvelope:
    """Create a CONFIG_RESULT response envelope.

    Args:
        success: Whether config update succeeded
        message: Human-readable result message
        updated_keys: List of keys that were updated
        request_id: Correlation ID from the CONFIG_UPDATE request

    Returns:
        StyreneEnvelope configured as CONFIG_RESULT with encoded payload
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.CONFIG_RESULT,
        payload=encode_payload(
            {"success": success, "message": message, "updated_keys": updated_keys}
        ),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_self_update(
    version: str | None = None, request_id: bytes | None = None
) -> StyreneEnvelope:
    """Create a SELF_UPDATE command envelope.

    Args:
        version: Target version to install (None = latest from PyPI).
        request_id: Optional correlation ID (auto-generated if None).

    Returns:
        StyreneEnvelope configured as SELF_UPDATE with encoded payload.
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.SELF_UPDATE,
        payload=encode_payload({"version": version}),
        request_id=request_id,
    )


def create_self_update_result(
    success: bool,
    message: str,
    old_version: str,
    new_version: str | None = None,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a SELF_UPDATE_RESULT response envelope.

    Args:
        success: Whether update was applied successfully.
        message: Human-readable result message.
        old_version: Version before update.
        new_version: Version after update (None if update failed).
        request_id: Correlation ID from the SELF_UPDATE request.

    Returns:
        StyreneEnvelope configured as SELF_UPDATE_RESULT with encoded payload.
    """
    payload_data: dict[str, Any] = {
        "success": success,
        "message": message,
        "old_version": old_version,
    }
    if new_version is not None:
        payload_data["new_version"] = new_version
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.SELF_UPDATE_RESULT,
        payload=encode_payload(payload_data),
        request_id=request_id if request_id else NO_CORRELATION,
    )


# Remote inbox query convenience functions


def create_inbox_query(limit: int = 50, request_id: bytes | None = None) -> StyreneEnvelope:
    """Create an INBOX_QUERY message envelope.

    Args:
        limit: Maximum number of conversations to return.
        request_id: Optional correlation ID (auto-generated if None).

    Returns:
        StyreneEnvelope configured as INBOX_QUERY with encoded payload.
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.INBOX_QUERY,
        payload=encode_payload({"limit": limit}),
        request_id=request_id,
    )


def create_inbox_response(
    conversations: list[dict[str, Any]], request_id: bytes | None = None
) -> StyreneEnvelope:
    """Create an INBOX_RESPONSE message envelope.

    Args:
        conversations: List of conversation dicts (from ConversationInfo.to_dict()).
        request_id: Correlation ID from the INBOX_QUERY request.

    Returns:
        StyreneEnvelope configured as INBOX_RESPONSE with encoded payload.
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.INBOX_RESPONSE,
        payload=encode_payload({"conversations": conversations}),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_messages_query(
    peer_hash: str, limit: int = 50, request_id: bytes | None = None
) -> StyreneEnvelope:
    """Create a MESSAGES_QUERY message envelope.

    Args:
        peer_hash: LXMF destination hash of the peer to query messages for.
        limit: Maximum number of messages to return.
        request_id: Optional correlation ID (auto-generated if None).

    Returns:
        StyreneEnvelope configured as MESSAGES_QUERY with encoded payload.
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.MESSAGES_QUERY,
        payload=encode_payload({"peer_hash": peer_hash, "limit": limit}),
        request_id=request_id,
    )


def create_messages_response(
    messages: list[dict[str, Any]], request_id: bytes | None = None
) -> StyreneEnvelope:
    """Create a MESSAGES_RESPONSE message envelope.

    Args:
        messages: List of message dicts (from MessageInfo.to_dict()).
        request_id: Correlation ID from the MESSAGES_QUERY request.

    Returns:
        StyreneEnvelope configured as MESSAGES_RESPONSE with encoded payload.
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.MESSAGES_RESPONSE,
        payload=encode_payload({"messages": messages}),
        request_id=request_id if request_id else NO_CORRELATION,
    )


# -----------------------------------------------------------------------------
# Terminal Session Messages (Control Plane - via LXMF)
# Data plane messages travel over RNS Link directly, not via LXMF
# -----------------------------------------------------------------------------


def create_terminal_request(
    term_type: str = "xterm-256color",
    rows: int = 24,
    cols: int = 80,
    shell: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a TERMINAL_REQUEST envelope.

    Requests an interactive terminal session. Server will respond with
    TERMINAL_ACCEPT (including RNS Link destination for data plane) or
    TERMINAL_REJECT.

    Args:
        term_type: Terminal type (TERM env var)
        rows: Initial terminal rows
        cols: Initial terminal columns
        shell: Shell to execute (None = server default)
        command: Command to execute instead of shell (None = interactive)
        args: Arguments for command
        request_id: Optional correlation ID (auto-generated if None)

    Returns:
        StyreneEnvelope configured as TERMINAL_REQUEST
    """
    payload: dict[str, Any] = {
        "term_type": term_type,
        "rows": rows,
        "cols": cols,
    }
    if shell is not None:
        payload["shell"] = shell
    if command is not None:
        payload["command"] = command
    if args is not None:
        payload["args"] = args

    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.TERMINAL_REQUEST,
        payload=encode_payload(payload),
        request_id=request_id,
    )


def create_terminal_accept(
    link_destination: str,
    session_id: bytes | None = None,
    request_id: bytes | None = None,
    identity_hash: str | None = None,
) -> StyreneEnvelope:
    """Create a TERMINAL_ACCEPT response envelope.

    Sent when terminal session is approved. Contains the RNS destination
    hash for establishing the data plane Link.

    Args:
        link_destination: RNS destination hash (hex) for data Link
        session_id: Session identifier (defaults to request_id if not provided)
        request_id: Correlation ID from the TERMINAL_REQUEST
        identity_hash: RNS identity hash (hex) that owns the destination

    Returns:
        StyreneEnvelope configured as TERMINAL_ACCEPT
    """
    # Session ID defaults to request_id for simplicity
    effective_session_id = session_id if session_id is not None else request_id
    payload: dict[str, Any] = {
        "link_destination": link_destination,
    }
    if effective_session_id is not None:
        payload["session_id"] = effective_session_id.hex()
    if identity_hash is not None:
        payload["identity_hash"] = identity_hash

    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.TERMINAL_ACCEPT,
        payload=encode_payload(payload),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_terminal_reject(
    reason: str,
    code: int = 1,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a TERMINAL_REJECT response envelope.

    Sent when terminal session is denied.

    Args:
        reason: Human-readable rejection reason
        code: Error code (1=auth, 2=resource, 3=disabled, etc.)
        request_id: Correlation ID from the TERMINAL_REQUEST

    Returns:
        StyreneEnvelope configured as TERMINAL_REJECT
    """
    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.TERMINAL_REJECT,
        payload=encode_payload({"reason": reason, "code": code}),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_terminal_resize(
    rows: int,
    cols: int,
    session_id: bytes | None = None,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a TERMINAL_RESIZE envelope.

    Notifies server of terminal window size change. Can be sent over
    LXMF (control plane) or directly over Link (data plane).

    Args:
        rows: New terminal rows
        cols: New terminal columns
        session_id: Session to resize (uses request_id if not provided)
        request_id: Correlation ID

    Returns:
        StyreneEnvelope configured as TERMINAL_RESIZE
    """
    payload: dict[str, Any] = {"rows": rows, "cols": cols}
    if session_id is not None:
        payload["session_id"] = session_id.hex()

    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.TERMINAL_RESIZE,
        payload=encode_payload(payload),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_terminal_signal(
    signal: int,
    session_id: bytes | None = None,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a TERMINAL_SIGNAL envelope.

    Sends a signal to the terminal process (SIGINT, SIGTSTP, etc.).

    Args:
        signal: Signal number to send (e.g., signal.SIGINT)
        session_id: Session to signal
        request_id: Correlation ID

    Returns:
        StyreneEnvelope configured as TERMINAL_SIGNAL
    """
    payload: dict[str, Any] = {"signal": signal}
    if session_id is not None:
        payload["session_id"] = session_id.hex()

    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.TERMINAL_SIGNAL,
        payload=encode_payload(payload),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_terminal_close(
    session_id: bytes | None = None,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a TERMINAL_CLOSE envelope.

    Requests graceful termination of a terminal session.

    Args:
        session_id: Session to close
        request_id: Correlation ID

    Returns:
        StyreneEnvelope configured as TERMINAL_CLOSE
    """
    payload: dict[str, Any] = {}
    if session_id is not None:
        payload["session_id"] = session_id.hex()

    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.TERMINAL_CLOSE,
        payload=encode_payload(payload),
        request_id=request_id if request_id else NO_CORRELATION,
    )


def create_terminal_closed(
    exit_code: int,
    reason: str = "exited",
    session_id: bytes | None = None,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a TERMINAL_CLOSED envelope.

    Notifies that a terminal session has terminated.

    Args:
        exit_code: Process exit code
        reason: Termination reason ("exited", "signal", "error", etc.)
        session_id: Session that closed
        request_id: Correlation ID

    Returns:
        StyreneEnvelope configured as TERMINAL_CLOSED
    """
    payload: dict[str, Any] = {"exit_code": exit_code, "reason": reason}
    if session_id is not None:
        payload["session_id"] = session_id.hex()

    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.TERMINAL_CLOSED,
        payload=encode_payload(payload),
        request_id=request_id if request_id else NO_CORRELATION,
    )


# ---------------------------------------------------------------------------
# File transfer factories
# ---------------------------------------------------------------------------


def create_file_offer(
    filename: str,
    size: int,
    mime_type: str | None = None,
    checksum_sha256: str | None = None,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a FILE_OFFER envelope.

    Sent to propose a file transfer to a Styrene peer. The receiver
    responds with FILE_ACCEPT (with size limit) or ignores.

    Args:
        filename: Name of the file being offered.
        size: Total size in bytes.
        mime_type: Optional MIME type.
        checksum_sha256: Optional SHA-256 hex digest for integrity verification.
        request_id: Correlation ID for response matching.

    Returns:
        StyreneEnvelope configured as FILE_OFFER.
    """
    payload: dict[str, Any] = {
        "filename": filename,
        "size": size,
    }
    if mime_type is not None:
        payload["mime_type"] = mime_type
    if checksum_sha256 is not None:
        payload["checksum"] = checksum_sha256

    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.FILE_OFFER,
        payload=encode_payload(payload),
        request_id=request_id,
    )


def create_file_accept(
    max_size: int,
    request_id: bytes | None = None,
) -> StyreneEnvelope:
    """Create a FILE_ACCEPT envelope.

    Sent in response to a FILE_OFFER to authorize the transfer.
    The sender should proceed only if the file fits within max_size.

    Args:
        max_size: Maximum file size the receiver will accept.
        request_id: Correlation ID matching the original FILE_OFFER.

    Returns:
        StyreneEnvelope configured as FILE_ACCEPT.
    """
    payload: dict[str, Any] = {"max_size": max_size}

    return StyreneEnvelope(
        version=STYRENE_VERSION,
        message_type=StyreneMessageType.FILE_ACCEPT,
        payload=encode_payload(payload),
        request_id=request_id if request_id else NO_CORRELATION,
    )
