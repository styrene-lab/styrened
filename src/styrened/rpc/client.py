"""RPC client for request/response communication over LXMF.

This module implements the RPC protocol layer that provides request/response
semantics over asynchronous LXMF messaging. It handles request correlation,
timeouts, and error propagation.

Usage:
    from styrened.rpc import RPCClient
    from styrened.services.lxmf_service import get_lxmf_service
    from styrened.rpc.messages import StatusRequest, StatusResponse

    # Initialize
    lxmf_service = get_lxmf_service()
    rpc_client = RPCClient(lxmf_service)

    # Make RPC call
    response = await rpc_client.call(device_hash, StatusRequest())
    print(f"Device uptime: {response.uptime}")

    # Use convenience methods
    status = await rpc_client.call_status(device_hash)
    result = await rpc_client.call_exec(device_hash, "systemctl", ["status", "reticulum"])
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from styrened.protocols.base import LXMFMessage, Protocol
from styrened.rpc.errors import (
    RPCInvalidResponseError,
    RPCTimeoutError,
    RPCTransportError,
)
from styrened.rpc.messages import (
    ExecCommand,
    ExecResult,
    RebootCommand,
    RebootResult,
    StatusRequest,
    StatusResponse,
    UpdateConfigCommand,
    UpdateConfigResult,
    deserialize_message,
)
from styrened.services.lxmf_service import LXMFService

logger = logging.getLogger(__name__)


@dataclass
class PendingRequest:
    """Represents a pending RPC request awaiting response.

    Attributes:
        future: Future that will be resolved with response.
        timestamp: Unix timestamp when request was sent.
        destination: Destination hash where request was sent.
        message_type: Type of message sent.
    """

    future: asyncio.Future[StatusResponse | ExecResult | RebootResult | UpdateConfigResult]
    timestamp: float
    destination: str
    message_type: str


class RPCClient(Protocol):
    """RPC client for request/response communication over LXMF.

    This client provides synchronous-style RPC calls over asynchronous LXMF
    messaging. It handles request correlation via UUIDs, timeout management,
    and response routing.

    Implements the Protocol interface for integration with ProtocolRegistry.

    Attributes:
        lxmf_service: LXMF transport service for sending/receiving messages.
        pending_requests: Dict of pending requests keyed by request_id.
        default_timeout: Default timeout in seconds for RPC calls.
    """

    def __init__(self, lxmf_service: LXMFService) -> None:
        """Initialize RPC client.

        Args:
            lxmf_service: LXMF transport service.
        """
        self.lxmf_service = lxmf_service
        self.pending_requests: dict[str, PendingRequest] = {}
        self.default_timeout = 30.0
        self._message_timeouts: dict[str, float] = {}

        # Register callback for incoming messages
        self.lxmf_service.register_callback(self._handle_incoming_message)

        logger.debug("RPCClient initialized")

    @property
    def protocol_id(self) -> str:
        """Protocol identifier for RPC messages."""
        return "rpc"

    def can_handle(self, message: LXMFMessage) -> bool:
        """Determine if this is an RPC message.

        Args:
            message: LXMF message to evaluate

        Returns:
            True if message.fields["protocol"] == "rpc"
        """
        return message.get_protocol() == "rpc"

    async def handle_message(self, message: LXMFMessage) -> None:
        """Handle incoming RPC message.

        Routes to existing _handle_incoming_message logic.

        Args:
            message: Incoming LXMF message
        """
        # Convert LXMFMessage to payload dict for existing logic
        # Fields dictionary contains all the RPC response data
        payload = dict(message.fields)

        # Add content if present
        if message.content:
            payload["content"] = message.content

        # Call existing handler with source hash and payload
        self._handle_incoming_message(message.source_hash, payload)

    async def send_message(self, destination: str, content: Any) -> None:
        """Send RPC message.

        Note: This is a simplified interface for Protocol compliance.
        For full RPC functionality, use call(), call_status(), call_exec(), etc.

        Args:
            destination: Destination identity hash
            content: Message content (should be an RPC command)

        Raises:
            RPCTransportError: If send fails
        """
        if isinstance(content, (StatusRequest, ExecCommand, RebootCommand, UpdateConfigCommand)):
            # Use existing call() method for proper RPC semantics
            await self.call(destination, content)
        else:
            # Generic send (for protocol interface compliance)
            payload = {"protocol": "rpc", "content": content}
            if not self.lxmf_service.send_message(destination, payload):
                raise RPCTransportError(f"Failed to send message to {destination}", destination)

    def _generate_request_id(self) -> str:
        """Generate unique request ID.

        Returns:
            UUID v4 string.
        """
        return str(uuid4())

    def _add_pending_request(
        self,
        request_id: str,
        future: asyncio.Future[StatusResponse | ExecResult | RebootResult | UpdateConfigResult],
        destination: str,
        message_type: str,
    ) -> None:
        """Add pending request to tracking dict.

        Args:
            request_id: UUID of the request.
            future: Future to resolve with response.
            destination: Destination hash.
            message_type: Type of message.
        """
        self.pending_requests[request_id] = PendingRequest(
            future=future,
            timestamp=time.time(),
            destination=destination,
            message_type=message_type,
        )
        logger.debug(f"Added pending request {request_id} for {destination} (type: {message_type})")

    def _remove_pending_request(self, request_id: str) -> None:
        """Remove pending request from tracking dict.

        Args:
            request_id: UUID of the request to remove.
        """
        if request_id in self.pending_requests:
            del self.pending_requests[request_id]
            logger.debug(f"Removed pending request {request_id}")

    def _handle_incoming_message(self, source: str, payload: dict[str, Any]) -> None:
        """Handle incoming LXMF message.

        This callback is invoked by LXMFService when a message is received.
        It correlates the response with the pending request and resolves the future.

        Args:
            source: Source destination hash.
            payload: Message payload.
        """
        logger.debug(f"Received message from {source}: {payload.get('type')}")

        # Extract request_id
        request_id = payload.get("request_id")
        if not request_id:
            logger.warning(f"Received message without request_id from {source}")
            return

        # Check if this is a response to a pending request
        if request_id not in self.pending_requests:
            logger.debug(f"Received response for unknown request_id: {request_id}")
            return

        pending = self.pending_requests[request_id]

        try:
            # Deserialize response message
            response = deserialize_message(payload)

            # Resolve the future
            if not pending.future.done():
                pending.future.set_result(response)  # type: ignore
                logger.debug(f"Resolved request {request_id} with {response.type}")

            # Clean up pending request
            self._remove_pending_request(request_id)

        except (ValueError, KeyError) as e:
            # Deserialization failed
            logger.error(f"Failed to deserialize response: {e}")

            # Set exception on future
            if not pending.future.done():
                pending.future.set_exception(
                    RPCInvalidResponseError(
                        f"Failed to deserialize response: {e}",
                        request_id=request_id,
                        payload=payload,
                    )
                )

            # Clean up pending request
            self._remove_pending_request(request_id)

    async def call(
        self,
        destination: str,
        message: StatusRequest | ExecCommand | RebootCommand | UpdateConfigCommand,
        timeout: float | None = None,
    ) -> StatusResponse | ExecResult | RebootResult | UpdateConfigResult:
        """Make RPC call and wait for response.

        Args:
            destination: Device destination hash.
            message: RPC message to send.
            timeout: Timeout in seconds (uses default if not specified).

        Returns:
            Response message.

        Raises:
            RPCTimeoutError: If response not received within timeout.
            RPCTransportError: If LXMF send fails.
            RPCInvalidResponseError: If response is malformed.
        """
        # Generate request ID
        request_id = self._generate_request_id()

        # Create future for response
        future: asyncio.Future[StatusResponse | ExecResult | RebootResult | UpdateConfigResult] = (
            asyncio.Future()
        )

        # Track pending request
        self._add_pending_request(request_id, future, destination, message.type)

        # Add request_id and protocol to payload
        payload = message.to_dict()
        payload["request_id"] = request_id
        payload["protocol"] = "rpc"  # Protocol discrimination

        # Send message with retry to handle path discovery
        logger.debug(f"Sending {message.type} to {destination} (request_id: {request_id})")
        if not self.lxmf_service.send_with_retry(
            destination, payload, max_wait=15.0, check_interval=1.0
        ):
            # Cleanup on send failure
            self._remove_pending_request(request_id)
            raise RPCTransportError(f"Failed to send message to {destination}", destination)

        # Determine timeout
        if timeout is None:
            timeout = self.get_timeout(message.type)

        # Wait for response with timeout
        try:
            logger.debug(f"Waiting for response to {request_id} (timeout: {timeout}s)")
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as e:
            # Cleanup on timeout
            self._remove_pending_request(request_id)
            logger.warning(f"Request {request_id} to {destination} timed out after {timeout}s")
            raise RPCTimeoutError(
                f"Request {request_id} to {destination} timed out after {timeout}s",
                request_id=request_id,
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
        response = await self.call(destination, StatusRequest(), timeout=timeout)
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
        response = await self.call(
            destination, ExecCommand(command=command, args=args), timeout=timeout
        )
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
        response = await self.call(destination, RebootCommand(delay=delay), timeout=timeout)
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
        response = await self.call(
            destination, UpdateConfigCommand(config_updates=config_updates), timeout=timeout
        )
        assert isinstance(response, UpdateConfigResult)
        return response

    def set_timeout(self, message_type: str, timeout: float) -> None:
        """Set default timeout for specific message type.

        Args:
            message_type: Message type identifier.
            timeout: Timeout in seconds.
        """
        self._message_timeouts[message_type] = timeout
        logger.debug(f"Set timeout for {message_type}: {timeout}s")

    def get_timeout(self, message_type: str) -> float:
        """Get timeout for message type.

        Args:
            message_type: Message type identifier.

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
