"""Protocol registry for LXMF message routing.

This module provides ProtocolRegistry, a thread-safe multiplexer that routes
incoming LXMF messages to the appropriate protocol handler based on the
message.fields["protocol"] value.

Design decisions:
- Thread-safe registration with threading.Lock
- Async message routing (supports async protocol handlers)
- Clear error handling for missing/invalid protocols
"""

import logging
import threading

from styrened.protocols.base import LXMFMessage, Protocol

logger = logging.getLogger(__name__)


class ProtocolNotFoundError(Exception):
    """Raised when message cannot be routed to a protocol."""

    pass


class ProtocolRegistry:
    """Thread-safe registry for protocol handlers.

    Manages registration and routing of LXMF messages to protocol implementations.
    Supports concurrent registration and message routing.

    Example:
        ```python
        registry = ProtocolRegistry()

        # Register protocols
        registry.register_protocol(ChatProtocol())
        registry.register_protocol(RPCProtocol())

        # Route incoming message
        await registry.route_message(lxmf_message)
        ```
    """

    def __init__(self) -> None:
        """Initialize empty protocol registry."""
        self._protocols: dict[str, Protocol] = {}
        self._lock = threading.Lock()

    def register_protocol(self, protocol: Protocol) -> None:
        """Register a protocol handler.

        Args:
            protocol: Protocol implementation to register

        Raises:
            ValueError: If protocol with same protocol_id already registered
        """
        with self._lock:
            protocol_id = protocol.protocol_id

            if protocol_id in self._protocols:
                raise ValueError(f"Protocol '{protocol_id}' already registered")

            self._protocols[protocol_id] = protocol
            logger.info(f"Registered protocol: {protocol_id}")

    def unregister_protocol(self, protocol_id: str) -> None:
        """Unregister a protocol handler.

        Args:
            protocol_id: Protocol identifier to unregister

        Raises:
            KeyError: If protocol not registered
        """
        with self._lock:
            if protocol_id not in self._protocols:
                raise KeyError(f"Protocol '{protocol_id}' not registered")

            del self._protocols[protocol_id]
            logger.info(f"Unregistered protocol: {protocol_id}")

    def get_protocol(self, protocol_id: str) -> Protocol | None:
        """Get registered protocol by ID.

        Args:
            protocol_id: Protocol identifier

        Returns:
            Protocol instance if registered, None otherwise
        """
        with self._lock:
            return self._protocols.get(protocol_id)

    def list_protocols(self) -> list[str]:
        """List all registered protocol IDs.

        Returns:
            List of protocol identifiers
        """
        with self._lock:
            return list(self._protocols.keys())

    async def route_message(self, message: LXMFMessage) -> None:
        """Route message to appropriate protocol handler.

        Extracts protocol identifier from message.fields["protocol"] and
        delegates to the registered protocol's handle_message() method.

        Args:
            message: LXMF message to route

        Raises:
            ProtocolNotFoundError: If no protocol specified, protocol not registered,
                                   or protocol cannot handle message
        """
        protocol_id = message.get_protocol()

        if not protocol_id:
            raise ProtocolNotFoundError("No protocol specified in message fields")

        # Get protocol (thread-safe access)
        with self._lock:
            protocol = self._protocols.get(protocol_id)

        if protocol is None:
            raise ProtocolNotFoundError(f"Protocol '{protocol_id}' not found in registry")

        # Verify protocol can handle this message
        if not protocol.can_handle(message):
            raise ProtocolNotFoundError(
                f"Protocol '{protocol_id}' cannot handle message (can_handle returned False)"
            )

        # Delegate to protocol handler (async)
        logger.debug(f"Routing message to protocol: {protocol_id}")
        await protocol.handle_message(message)
