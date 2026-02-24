"""RPC client for request/response communication over LXMF.

This module implements the RPC protocol layer that provides request/response
semantics over asynchronous LXMF messaging using the Styrene wire protocol.
It handles request correlation, timeouts, and error propagation.

Wire Format:
    Uses StyreneProtocol with FIELD_CUSTOM_TYPE="styrene.io" and
    FIELD_CUSTOM_DATA containing the v2 wire format with 16-byte request_id
    for correlation.

Usage:
    from styrened.rpc import RPCClient
    from styrened.protocols.styrene import StyreneProtocol

    # Initialize with StyreneProtocol
    styrene_protocol = StyreneProtocol(router, identity, db_engine)
    rpc_client = RPCClient(styrene_protocol)

    # Make RPC call
    status = await rpc_client.call_status(device_hash)
    print(f"Device uptime: {status.uptime}")

    # Execute command
    result = await rpc_client.call_exec(device_hash, "systemctl", ["status", "reticulum"])
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from styrened.models.styrene_wire import (
    NO_CORRELATION,
    StyreneEnvelope,
    StyreneMessageType,
    create_config_update,
    create_exec,
    create_inbox_query,
    create_messages_query,
    create_reboot,
    create_self_update,
    create_status_request,
    decode_payload,
    generate_request_id,
)
from styrened.protocols.base import LXMFMessage, Protocol
from styrened.rpc.errors import (
    RPCInvalidResponseError,
    RPCTimeoutError,
    RPCTransportError,
)

# Import response types for type hints and public API
from styrened.rpc.messages import (
    ExecResult,
    InboxResponse,
    MessagesResponse,
    RebootResult,
    SelfUpdateResult,
    StatusResponse,
    UpdateConfigResult,
)

if TYPE_CHECKING:
    from styrened.protocols.styrene import StyreneProtocol

logger = logging.getLogger(__name__)

# Response type union for type hints
RPCResponseType = StatusResponse | ExecResult | RebootResult | UpdateConfigResult | SelfUpdateResult | InboxResponse | MessagesResponse


@dataclass
class PendingRequest:
    """Represents a pending RPC request awaiting response.

    Attributes:
        future: Future that will be resolved with response.
        timestamp: Unix timestamp when request was sent.
        destination: Destination hash where request was sent.
        message_type: StyreneMessageType of message sent.
    """

    future: asyncio.Future[RPCResponseType]
    timestamp: float
    destination: str
    message_type: StyreneMessageType


class RPCClient(Protocol):
    """RPC client for request/response communication over Styrene protocol.

    This client provides synchronous-style RPC calls over asynchronous LXMF
    messaging using the Styrene wire protocol. It handles request correlation
    via 16-byte random request_ids, timeout management, and response routing.

    Implements the Protocol interface for integration with ProtocolRegistry.

    Attributes:
        styrene_protocol: StyreneProtocol instance for sending/receiving messages.
        pending_requests: Dict of pending requests keyed by request_id (bytes).
        default_timeout: Default timeout in seconds for RPC calls.
    """

    def __init__(self, styrene_protocol: "StyreneProtocol") -> None:
        """Initialize RPC client.

        Args:
            styrene_protocol: StyreneProtocol instance for transport.
        """
        self._protocol = styrene_protocol
        self.pending_requests: dict[bytes, PendingRequest] = {}
        self.default_timeout = 30.0
        self._message_timeouts: dict[StyreneMessageType, float] = {}

        # Register handlers for RPC response types
        self._register_response_handlers()

        logger.debug("RPCClient initialized with StyreneProtocol")

    def _register_response_handlers(self) -> None:
        """Register handlers for RPC response message types.

        Registers this client as a handler for all RPC response types
        so it can correlate responses with pending requests.
        """
        # Register for all response types we expect to receive
        response_types = [
            StyreneMessageType.STATUS_RESPONSE,
            StyreneMessageType.EXEC_RESULT,
            StyreneMessageType.REBOOT_RESULT,
            StyreneMessageType.CONFIG_RESULT,
            StyreneMessageType.SELF_UPDATE_RESULT,
            StyreneMessageType.INBOX_RESPONSE,
            StyreneMessageType.MESSAGES_RESPONSE,
            StyreneMessageType.ERROR,
        ]

        for msg_type in response_types:
            self._protocol.register_handler(msg_type, self._handle_response)

        logger.debug(f"Registered handlers for {len(response_types)} response types")

    async def _handle_response(self, message: "LXMFMessage", envelope: "StyreneEnvelope") -> None:
        """Handle incoming RPC response from StyreneProtocol.

        This is called by StyreneProtocol when a response message is received.
        Correlates with pending requests and resolves futures.

        Args:
            message: Original LXMF message
            envelope: Decoded Styrene envelope with response data
        """
        logger.debug(f"RPCClient received response: {envelope.message_type.name}")

        # Get request_id for correlation
        request_id = envelope.request_id
        if request_id is None or request_id == NO_CORRELATION:
            logger.warning("RPC response missing request_id for correlation")
            return

        # Check if this correlates with a pending request
        if request_id not in self.pending_requests:
            logger.debug(f"Received response for unknown request_id: {request_id.hex()}")
            return

        pending = self.pending_requests[request_id]

        try:
            # Decode payload and create response object
            response = self._decode_response(envelope)

            # Resolve the future
            if not pending.future.done():
                pending.future.set_result(response)
                logger.info(
                    f"Resolved request {request_id.hex()[:16]}... with {envelope.message_type.name}"
                )

            # Clean up pending request
            self._remove_pending_request(request_id)

        except Exception as e:
            logger.error(f"Failed to decode RPC response: {e}")

            # Set exception on future
            if not pending.future.done():
                pending.future.set_exception(
                    RPCInvalidResponseError(
                        f"Failed to decode response: {e}",
                        request_id=request_id.hex(),
                        payload={},
                    )
                )

            # Clean up pending request
            self._remove_pending_request(request_id)

    @property
    def protocol_id(self) -> str:
        """Protocol identifier for RPC messages."""
        return "rpc"

    def can_handle(self, message: LXMFMessage) -> bool:
        """Determine if this is an RPC response message.

        RPC responses use StyreneProtocol with specific message types
        in the RPC response range (0x60-0x7F).

        Args:
            message: LXMF message to evaluate

        Returns:
            True if message is a Styrene RPC response
        """
        # Check if it's a Styrene message first
        if not self._protocol.can_handle(message):
            return False

        # We'll check the message type after decoding
        # For now, delegate to StyreneProtocol's can_handle
        return True

    async def handle_message(self, message: LXMFMessage) -> None:
        """Handle incoming RPC response message.

        Extracts the StyreneEnvelope, correlates with pending request,
        and resolves the appropriate future.

        Args:
            message: Incoming LXMF message with Styrene RPC response
        """
        # Import here to avoid circular import
        try:
            import LXMF

            field_custom_data = LXMF.FIELD_CUSTOM_DATA
        except ImportError:
            field_custom_data = 0xFC

        logger.debug(f"RPCClient handling message from {message.source_hash}")

        # Extract custom data field
        custom_data = message.fields.get(field_custom_data)
        if custom_data is None:
            logger.warning("RPC message missing FIELD_CUSTOM_DATA")
            return

        # Ensure bytes
        if isinstance(custom_data, str):
            custom_data = custom_data.encode("utf-8")

        try:
            envelope = StyreneEnvelope.decode(custom_data)
        except Exception as e:
            logger.error(f"Failed to decode Styrene envelope: {e}")
            return

        # Check if this is an RPC response type
        if not self._is_rpc_response(envelope.message_type):
            logger.debug(f"Not an RPC response type: {envelope.message_type.name}")
            return

        # Get request_id for correlation
        request_id = envelope.request_id
        if request_id is None or request_id == NO_CORRELATION:
            logger.warning("RPC response missing request_id for correlation")
            return

        # Check if this correlates with a pending request
        if request_id not in self.pending_requests:
            logger.debug(f"Received response for unknown request_id: {request_id.hex()}")
            return

        pending = self.pending_requests[request_id]

        try:
            # Decode payload and create response object
            response = self._decode_response(envelope)

            # Resolve the future
            if not pending.future.done():
                pending.future.set_result(response)
                logger.debug(
                    f"Resolved request {request_id.hex()} with {envelope.message_type.name}"
                )

            # Clean up pending request
            self._remove_pending_request(request_id)

        except Exception as e:
            logger.error(f"Failed to decode RPC response: {e}")

            # Set exception on future
            if not pending.future.done():
                pending.future.set_exception(
                    RPCInvalidResponseError(
                        f"Failed to decode response: {e}",
                        request_id=request_id.hex(),
                        payload={"raw": custom_data.hex()},
                    )
                )

            # Clean up pending request
            self._remove_pending_request(request_id)

    def _is_rpc_response(self, message_type: StyreneMessageType) -> bool:
        """Check if message type is an RPC response.

        Args:
            message_type: StyreneMessageType to check

        Returns:
            True if message type is in RPC response range (0x60-0x7F)
        """
        return message_type in (
            StyreneMessageType.STATUS_RESPONSE,
            StyreneMessageType.EXEC_RESULT,
            StyreneMessageType.REBOOT_RESULT,
            StyreneMessageType.CONFIG_RESULT,
            StyreneMessageType.SELF_UPDATE_RESULT,
            StyreneMessageType.INBOX_RESPONSE,
            StyreneMessageType.MESSAGES_RESPONSE,
            StyreneMessageType.ERROR,
        )

    def _decode_response(self, envelope: StyreneEnvelope) -> RPCResponseType:
        """Decode StyreneEnvelope payload into response object.

        Args:
            envelope: Decoded Styrene envelope

        Returns:
            Appropriate response type based on message_type

        Raises:
            ValueError: If response type is unknown or payload is invalid
        """
        payload_data = decode_payload(envelope.payload) if envelope.payload else {}

        if envelope.message_type == StyreneMessageType.STATUS_RESPONSE:
            return StatusResponse(
                uptime=payload_data.get("uptime", 0),
                ip=payload_data.get("ip", ""),
                services=payload_data.get("services", []),
                disk_used=payload_data.get("disk_used", 0),
                disk_total=payload_data.get("disk_total", 0),
                styrened_version=payload_data.get("styrened_version"),
                hostname=payload_data.get("hostname"),
                arch=payload_data.get("arch"),
                os_id=payload_data.get("os_id"),
                os_version=payload_data.get("os_version"),
                nixos_generation=payload_data.get("nixos_generation"),
                available_commands=payload_data.get("available_commands"),
            )
        elif envelope.message_type == StyreneMessageType.EXEC_RESULT:
            return ExecResult(
                exit_code=payload_data.get("exit_code", -1),
                stdout=payload_data.get("stdout", ""),
                stderr=payload_data.get("stderr", ""),
            )
        elif envelope.message_type == StyreneMessageType.REBOOT_RESULT:
            return RebootResult(
                success=payload_data.get("success", False),
                message=payload_data.get("message", ""),
                scheduled_time=payload_data.get("scheduled_time"),
            )
        elif envelope.message_type == StyreneMessageType.CONFIG_RESULT:
            return UpdateConfigResult(
                success=payload_data.get("success", False),
                message=payload_data.get("message", ""),
                updated_keys=payload_data.get("updated_keys", []),
            )
        elif envelope.message_type == StyreneMessageType.SELF_UPDATE_RESULT:
            return SelfUpdateResult(
                success=payload_data.get("success", False),
                message=payload_data.get("message", ""),
                old_version=payload_data.get("old_version", ""),
                new_version=payload_data.get("new_version"),
            )
        elif envelope.message_type == StyreneMessageType.INBOX_RESPONSE:
            return InboxResponse(
                conversations=payload_data.get("conversations", []),
            )
        elif envelope.message_type == StyreneMessageType.MESSAGES_RESPONSE:
            return MessagesResponse(
                messages=payload_data.get("messages", []),
            )
        elif envelope.message_type == StyreneMessageType.ERROR:
            # Convert ERROR to an exception
            error_code = payload_data.get("code", -1)
            error_message = payload_data.get("message", "Unknown error")
            raise ValueError(f"RPC error {error_code}: {error_message}")
        else:
            raise ValueError(f"Unknown response type: {envelope.message_type.name}")

    async def send_message(self, destination: str, content: Any) -> None:
        """Send RPC message (Protocol interface compliance).

        Note: This is a simplified interface for Protocol compliance.
        For full RPC functionality, use call(), call_status(), call_exec(), etc.

        Args:
            destination: Destination identity hash
            content: Message content (should be a StyreneEnvelope)

        Raises:
            RPCTransportError: If send fails
        """
        if isinstance(content, StyreneEnvelope):
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=content.message_type,
                payload=content.payload,
                request_id=content.request_id,
            )
        else:
            raise ValueError("send_message expects StyreneEnvelope. Use call() methods for RPC.")

    def _add_pending_request(
        self,
        request_id: bytes,
        future: asyncio.Future[RPCResponseType],
        destination: str,
        message_type: StyreneMessageType,
    ) -> None:
        """Add pending request to tracking dict.

        Args:
            request_id: 16-byte correlation ID.
            future: Future to resolve with response.
            destination: Destination hash.
            message_type: StyreneMessageType of message.
        """
        self.pending_requests[request_id] = PendingRequest(
            future=future,
            timestamp=time.time(),
            destination=destination,
            message_type=message_type,
        )
        logger.debug(
            f"Added pending request {request_id.hex()} for {destination} "
            f"(type: {message_type.name})"
        )

    def _remove_pending_request(self, request_id: bytes) -> None:
        """Remove pending request from tracking dict.

        Args:
            request_id: 16-byte correlation ID to remove.
        """
        if request_id in self.pending_requests:
            del self.pending_requests[request_id]
            logger.debug(f"Removed pending request {request_id.hex()}")

    async def _send_envelope(self, destination: str, envelope: StyreneEnvelope) -> None:
        """Send a StyreneEnvelope via the protocol.

        Args:
            destination: Destination identity hash
            envelope: Encoded envelope to send

        Raises:
            RPCTransportError: If send fails
        """
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=envelope.message_type,
                payload=envelope.payload,
                request_id=envelope.request_id,
            )
        except Exception as e:
            raise RPCTransportError(
                f"Failed to send message to {destination}: {e}", destination
            ) from e

    async def call(
        self,
        destination: str,
        envelope: StyreneEnvelope,
        timeout: float | None = None,
    ) -> RPCResponseType:
        """Make RPC call and wait for response.

        Args:
            destination: Device destination hash.
            envelope: StyreneEnvelope to send.
            timeout: Timeout in seconds (uses default if not specified).

        Returns:
            Response message.

        Raises:
            RPCTimeoutError: If response not received within timeout.
            RPCTransportError: If LXMF send fails.
            RPCInvalidResponseError: If response is malformed.
        """
        # Ensure we have a request_id for correlation
        request_id = envelope.request_id
        if request_id is None or request_id == NO_CORRELATION:
            # Generate one if not provided
            request_id = generate_request_id()
            # Re-create envelope with request_id
            envelope = StyreneEnvelope(
                version=envelope.version,
                message_type=envelope.message_type,
                payload=envelope.payload,
                request_id=request_id,
            )

        # Create future for response
        future: asyncio.Future[RPCResponseType] = asyncio.Future()

        # Track pending request
        self._add_pending_request(request_id, future, destination, envelope.message_type)

        # Send message
        logger.debug(
            f"Sending {envelope.message_type.name} to {destination} "
            f"(request_id: {request_id.hex()})"
        )
        try:
            await self._send_envelope(destination, envelope)
        except RPCTransportError:
            # Cleanup on send failure
            self._remove_pending_request(request_id)
            raise

        # Determine timeout
        if timeout is None:
            timeout = self.get_timeout(envelope.message_type)

        # Wait for response with timeout
        try:
            logger.debug(f"Waiting for response to {request_id.hex()} (timeout: {timeout}s)")
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as e:
            # Cleanup on timeout
            self._remove_pending_request(request_id)
            logger.warning(
                f"Request {request_id.hex()} to {destination} timed out after {timeout}s"
            )
            raise RPCTimeoutError(
                f"Request {request_id.hex()} to {destination} timed out after {timeout}s",
                request_id=request_id.hex(),
                destination=destination,
                timeout=timeout,
            ) from e

    async def call_status(self, destination: str, timeout: float = 10.0) -> StatusResponse:
        """Request device status.

        Convenience method for status requests.

        Args:
            destination: Device destination hash.
            timeout: Timeout in seconds (default 10.0).

        Returns:
            StatusResponse with device information.

        Raises:
            RPCTimeoutError: If response not received within timeout.
            RPCTransportError: If LXMF send fails.
        """
        envelope = create_status_request()
        response = await self.call(destination, envelope, timeout=timeout)
        assert isinstance(response, StatusResponse)
        return response

    async def call_exec(
        self,
        destination: str,
        command: str,
        args: list[str],
        timeout: float = 60.0,
    ) -> ExecResult:
        """Execute command on device.

        Convenience method for exec commands.

        Args:
            destination: Device destination hash.
            command: Command to execute.
            args: Command arguments.
            timeout: Timeout in seconds (default 60.0).

        Returns:
            ExecResult with command output.

        Raises:
            RPCTimeoutError: If response not received within timeout.
            RPCTransportError: If LXMF send fails.
        """
        envelope = create_exec(command=command, args=args)
        response = await self.call(destination, envelope, timeout=timeout)
        assert isinstance(response, ExecResult)
        return response

    async def call_reboot(
        self,
        destination: str,
        delay: int = 0,
        timeout: float = 10.0,
    ) -> RebootResult:
        """Reboot remote device.

        Convenience method for reboot commands.

        Args:
            destination: Device destination hash.
            delay: Seconds to delay reboot (default: immediate).
            timeout: Timeout in seconds (default 10.0).

        Returns:
            RebootResult with success status and scheduled time.

        Raises:
            RPCTimeoutError: If response not received within timeout.
            RPCTransportError: If LXMF send fails.
        """
        envelope = create_reboot(delay=delay)
        response = await self.call(destination, envelope, timeout=timeout)
        assert isinstance(response, RebootResult)
        return response

    async def call_update_config(
        self,
        destination: str,
        config_updates: dict[str, Any],
        timeout: float = 10.0,
    ) -> UpdateConfigResult:
        """Update device configuration.

        Convenience method for config update commands.

        Args:
            destination: Device destination hash.
            config_updates: Dictionary of config keys to update.
            timeout: Timeout in seconds (default 10.0).

        Returns:
            UpdateConfigResult with updated keys and success status.

        Raises:
            RPCTimeoutError: If response not received within timeout.
            RPCTransportError: If LXMF send fails.
        """
        envelope = create_config_update(updates=config_updates)
        response = await self.call(destination, envelope, timeout=timeout)
        assert isinstance(response, UpdateConfigResult)
        return response

    async def call_inbox(
        self,
        destination: str,
        limit: int = 50,
        timeout: float = 30.0,
    ) -> InboxResponse:
        """Query remote node's inbox (conversation list).

        Args:
            destination: Device destination hash.
            limit: Maximum conversations to return.
            timeout: Timeout in seconds.

        Returns:
            InboxResponse with conversation list.

        Raises:
            RPCTimeoutError: If response not received within timeout.
            RPCTransportError: If LXMF send fails.
        """
        envelope = create_inbox_query(limit=limit)
        response = await self.call(destination, envelope, timeout=timeout)
        assert isinstance(response, InboxResponse)
        return response

    async def call_messages(
        self,
        destination: str,
        peer_hash: str,
        limit: int = 50,
        timeout: float = 30.0,
    ) -> MessagesResponse:
        """Query messages for a specific peer on a remote node.

        Args:
            destination: Device destination hash.
            peer_hash: Peer hash to query messages for.
            limit: Maximum messages to return.
            timeout: Timeout in seconds.

        Returns:
            MessagesResponse with message list.

        Raises:
            RPCTimeoutError: If response not received within timeout.
            RPCTransportError: If LXMF send fails.
        """
        envelope = create_messages_query(peer_hash=peer_hash, limit=limit)
        response = await self.call(destination, envelope, timeout=timeout)
        assert isinstance(response, MessagesResponse)
        return response

    async def call_self_update(
        self,
        destination: str,
        version: str | None = None,
        timeout: float = 120.0,
    ) -> SelfUpdateResult:
        """Trigger self-update on remote device.

        Convenience method for self-update commands. Uses a longer default
        timeout since pip install can take significant time.

        Args:
            destination: Device destination hash.
            version: Target version (None = latest from PyPI).
            timeout: Timeout in seconds (default 120.0).

        Returns:
            SelfUpdateResult with old/new versions and success status.

        Raises:
            RPCTimeoutError: If response not received within timeout.
            RPCTransportError: If LXMF send fails.
        """
        envelope = create_self_update(version=version)
        response = await self.call(destination, envelope, timeout=timeout)
        assert isinstance(response, SelfUpdateResult)
        return response

    def set_timeout(self, message_type: StyreneMessageType, timeout: float) -> None:
        """Set default timeout for specific message type.

        Args:
            message_type: StyreneMessageType identifier.
            timeout: Timeout in seconds.
        """
        self._message_timeouts[message_type] = timeout
        logger.debug(f"Set timeout for {message_type.name}: {timeout}s")

    def get_timeout(self, message_type: StyreneMessageType) -> float:
        """Get timeout for message type.

        Args:
            message_type: StyreneMessageType identifier.

        Returns:
            Timeout in seconds (falls back to default_timeout).
        """
        return self._message_timeouts.get(message_type, self.default_timeout)

    @property
    def pending_count(self) -> int:
        """Get number of pending requests.

        Returns:
            Count of pending requests.
        """
        return len(self.pending_requests)
