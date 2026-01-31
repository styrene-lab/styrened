"""RPC error types.

This module defines exception types for RPC communication errors.
"""

from typing import Any


class RPCError(Exception):
    """Base class for RPC errors."""

    pass


class RPCTimeoutError(RPCError):
    """Raised when RPC call times out waiting for response.

    Attributes:
        message: Error description.
        request_id: UUID of the timed-out request.
        destination: Destination hash that didn't respond.
        timeout: Timeout duration in seconds.
    """

    def __init__(self, message: str, request_id: str, destination: str, timeout: float) -> None:
        """Initialize timeout error.

        Args:
            message: Error description.
            request_id: UUID of the timed-out request.
            destination: Destination hash that didn't respond.
            timeout: Timeout duration in seconds.
        """
        super().__init__(message)
        self.request_id = request_id
        self.destination = destination
        self.timeout = timeout


class RPCTransportError(RPCError):
    """Raised when LXMF transport fails to send message.

    Attributes:
        message: Error description.
        destination: Destination hash where send failed.
    """

    def __init__(self, message: str, destination: str) -> None:
        """Initialize transport error.

        Args:
            message: Error description.
            destination: Destination hash where send failed.
        """
        super().__init__(message)
        self.destination = destination


class RPCInvalidResponseError(RPCError):
    """Raised when response is malformed or doesn't match request.

    Attributes:
        message: Error description.
        request_id: UUID of the request (if available).
        payload: Raw response payload.
    """

    def __init__(self, message: str, request_id: str | None, payload: dict[str, Any]) -> None:
        """Initialize invalid response error.

        Args:
            message: Error description.
            request_id: UUID of the request (if available).
            payload: Raw response payload.
        """
        super().__init__(message)
        self.request_id = request_id
        self.payload = payload
