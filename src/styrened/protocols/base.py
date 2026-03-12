"""Base protocol abstraction for LXMF messaging.

This module provides the abstract Protocol interface that all LXMF protocols
must implement. Based on research from rnsh protocol analysis and LXMF message
structure documentation.

Design decisions:
- Protocol discrimination via fields["protocol"] (LXMF standard)
- Async-first for all network operations (informed by rnsh patterns)
- Type-safe with complete annotations (mypy strict mode)
- MessagePack serialization (LXMF requirement)
"""
from __future__ import annotations


from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LXMFMessage:
    """Represents an LXMF message for protocol routing.

    This is a simplified dataclass for internal message representation,
    separate from the actual LXMF library's message objects.

    Attributes:
        source_hash: Source identity hash (16 bytes hex-encoded)
        destination_hash: Destination identity hash (16 bytes hex-encoded)
        timestamp: Message timestamp (seconds since epoch)
        content: Message content (optional, may be None for protocol-only messages)
        fields: Protocol discrimination dictionary (contains "protocol" key)
        protocol_id: Cached protocol identifier (extracted from fields)
        status: Message status ('pending', 'sent', 'delivered', 'failed')
    """

    source_hash: str
    destination_hash: str
    timestamp: float
    content: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)
    protocol_id: str = ""
    status: str = "pending"

    def get_protocol(self) -> str:
        """Extract protocol identifier from fields dictionary.

        Returns:
            Protocol identifier string, or empty string if not present.
        """
        result = self.fields.get("protocol", "")
        return str(result) if result is not None else ""


class Protocol(ABC):
    """Abstract base class for LXMF protocol handlers.

    All protocol implementations must inherit from this class and implement
    the required abstract methods. This interface supports:

    - Protocol discrimination (can_handle)
    - Inbound message handling (handle_message)
    - Outbound message sending (send_message)
    - Protocol identification (protocol_id)

    Example:
        ```python
        class ChatProtocol(Protocol):
            @property
            def protocol_id(self) -> str:
                return "chat"

            def can_handle(self, message: LXMFMessage) -> bool:
                return message.fields.get("protocol") == "chat"

            async def handle_message(self, message: LXMFMessage) -> None:
                # Process incoming chat message
                print(f"Chat: {message.content}")

            async def send_message(self, destination: str, content: Any) -> None:
                # Send outbound chat message
                pass
        ```
    """

    @property
    @abstractmethod
    def protocol_id(self) -> str:
        """Protocol identifier used for registration and routing.

        This should match the value in message.fields["protocol"].

        Returns:
            Protocol identifier string (e.g., "chat", "rpc", "bond-rpc")
        """
        ...

    @abstractmethod
    def can_handle(self, message: LXMFMessage) -> bool:
        """Determine if this protocol can handle the given message.

        Typically checks if message.fields["protocol"] matches this protocol's ID,
        but may include additional validation logic.

        Args:
            message: LXMF message to evaluate

        Returns:
            True if this protocol can handle the message, False otherwise
        """
        ...

    @abstractmethod
    async def handle_message(self, message: LXMFMessage) -> None:
        """Handle an incoming LXMF message.

        This is an async method to support network operations, database writes,
        and other I/O-bound tasks without blocking.

        Args:
            message: LXMF message to process

        Raises:
            Protocol-specific exceptions for handling errors
        """
        ...

    @abstractmethod
    async def send_message(self, destination: str, content: Any) -> None:
        """Send an outbound LXMF message.

        This is an async method to support non-blocking network operations.

        Args:
            destination: Destination identity hash (hex-encoded)
            content: Message content (type depends on protocol)

        Raises:
            Protocol-specific exceptions for send errors
        """
        ...
