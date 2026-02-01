"""StyreneProtocol implementation for Styrene RPC over LXMF.

This module implements the Styrene RPC protocol using LXMF's custom fields
mechanism (FIELD_CUSTOM_TYPE and FIELD_CUSTOM_DATA) for proper protocol
encapsulation.

LXMF Fields Used:
    FIELD_CUSTOM_TYPE (0xFB): "styrene.io" - protocol identifier
    FIELD_CUSTOM_DATA (0xFC): wire format envelope (version + type + payload)

This follows LXMF's documented pattern for "embedding or encapsulating other
data types or protocols that are not native to LXMF, or bridging/tunneling
external protocols or services over LXMF."

Design decisions:
- Uses LXMF FIELD_CUSTOM_TYPE/DATA (proper protocol encapsulation)
- Content field contains human-readable summary for non-Styrene clients
- Display-only handlers for received messages (actual processing deferred)
- Complements existing ChatProtocol (doesn't replace it)

Message Flow:
    Outbound: envelope.encode() -> FIELD_CUSTOM_DATA, content = summary
    Inbound: FIELD_CUSTOM_DATA -> StyreneEnvelope.decode() -> handler
"""

import logging
import time
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

try:
    import LXMF
    import RNS

    # LXMF field constants for custom protocol encapsulation
    FIELD_CUSTOM_TYPE = LXMF.FIELD_CUSTOM_TYPE  # 0xFB
    FIELD_CUSTOM_DATA = LXMF.FIELD_CUSTOM_DATA  # 0xFC
except ImportError:
    LXMF = None
    RNS = None
    FIELD_CUSTOM_TYPE = 0xFB
    FIELD_CUSTOM_DATA = 0xFC

from styrened.models.messages import Message
from styrened.models.styrene_wire import (
    STYRENE_VERSION,
    PayloadDecodeError,
    StyreneEnvelope,
    StyreneMessageType,
    StyreneWireError,
    decode_payload,
    encode_payload,
)
from styrened.protocols.base import LXMFMessage, Protocol

logger = logging.getLogger(__name__)

# Protocol identifier for FIELD_CUSTOM_TYPE
STYRENE_CUSTOM_TYPE = b"styrene.io"


class StyreneProtocol(Protocol):
    """Styrene RPC protocol for typed messaging over LXMF.

    Uses LXMF's FIELD_CUSTOM_TYPE and FIELD_CUSTOM_DATA fields for proper
    protocol encapsulation. Non-Styrene clients see a human-readable
    summary in the content field.

    Example:
        ```python
        styrene = StyreneProtocol(router, identity, db_engine)

        # Send a ping
        await styrene.send_ping("abc123")

        # Send a chat message
        await styrene.send_chat("abc123", "Hello from Styrene!")

        # Protocol handles incoming messages via handle_message()
        ```
    """

    # Type alias for message handlers
    MessageHandler = Any  # Callable[[LXMFMessage, StyreneEnvelope], Awaitable[None]]

    def __init__(
        self,
        router: Any,  # LXMF.LXMRouter
        identity: Any,  # RNS.Identity
        db_engine: Engine,
    ) -> None:
        """Initialize StyreneProtocol.

        Args:
            router: LXMF router instance for sending messages
            identity: RNS identity for this node
            db_engine: SQLAlchemy engine for message persistence
        """
        self._router = router
        self._identity = identity
        self._db_engine = db_engine
        self._external_handlers: dict[StyreneMessageType, list[Any]] = {}

    @property
    def protocol_id(self) -> str:
        """Protocol identifier for registration."""
        return "styrene"

    def register_handler(
        self,
        message_type: StyreneMessageType,
        handler: Any,  # Callable[[LXMFMessage, StyreneEnvelope], Awaitable[None]]
    ) -> None:
        """Register an external handler for a message type.

        External handlers are called after internal handlers. Multiple handlers
        can be registered for the same message type.

        Args:
            message_type: StyreneMessageType to handle
            handler: Async function taking (message, envelope) as arguments
        """
        if message_type not in self._external_handlers:
            self._external_handlers[message_type] = []
        self._external_handlers[message_type].append(handler)
        logger.debug(f"Registered external handler for {message_type.name}")

    def unregister_handler(
        self,
        message_type: StyreneMessageType,
        handler: Any,
    ) -> None:
        """Unregister an external handler.

        Args:
            message_type: StyreneMessageType the handler was registered for
            handler: The handler function to remove
        """
        if message_type in self._external_handlers:
            try:
                self._external_handlers[message_type].remove(handler)
                logger.debug(f"Unregistered external handler for {message_type.name}")
            except ValueError:
                pass  # Handler not found

    def can_handle(self, message: LXMFMessage) -> bool:
        """Determine if this is a Styrene message.

        Checks if FIELD_CUSTOM_TYPE contains "styrene.io".

        Args:
            message: LXMF message to evaluate

        Returns:
            True if message has styrene.io custom type
        """
        custom_type = message.fields.get(FIELD_CUSTOM_TYPE)
        if custom_type is None:
            return False

        # Handle both bytes and string
        if isinstance(custom_type, bytes):
            return custom_type == STYRENE_CUSTOM_TYPE
        elif isinstance(custom_type, str):
            return custom_type == STYRENE_CUSTOM_TYPE.decode("utf-8")

        return False

    async def handle_message(self, message: LXMFMessage) -> None:
        """Handle incoming Styrene message.

        Extracts FIELD_CUSTOM_DATA, decodes the wire format, and
        dispatches to type-specific handlers.

        Args:
            message: Incoming LXMF message with Styrene custom fields
        """
        logger.info(f"Received Styrene message from {message.source_hash}")

        # Extract custom data field
        custom_data = message.fields.get(FIELD_CUSTOM_DATA)
        if custom_data is None:
            logger.error("Styrene message missing FIELD_CUSTOM_DATA")
            return

        # Ensure bytes
        if isinstance(custom_data, str):
            custom_data = custom_data.encode("utf-8")

        try:
            envelope = StyreneEnvelope.decode(custom_data)
        except StyreneWireError as e:
            logger.error(f"Failed to decode Styrene message: {e}")
            return

        # Dispatch to type-specific handler
        await self._dispatch_message(message, envelope)

        # Persist to database
        self._persist_message(message, envelope)

    async def _dispatch_message(self, message: LXMFMessage, envelope: StyreneEnvelope) -> None:
        """Dispatch decoded message to type-specific handler.

        Internal handlers are called first, then any registered external handlers.

        Args:
            message: Original LXMF message (for metadata)
            envelope: Decoded Styrene envelope
        """
        # Internal handlers for basic message types
        internal_handlers = {
            StyreneMessageType.PING: self._handle_ping,
            StyreneMessageType.PONG: self._handle_pong,
            StyreneMessageType.STATUS_REQUEST: self._handle_status_request,
            StyreneMessageType.STATUS_RESPONSE: self._handle_status_response,
            StyreneMessageType.CHAT: self._handle_chat,
            StyreneMessageType.ANNOUNCE: self._handle_announce,
        }

        handled = False

        # Call internal handler if present
        internal_handler = internal_handlers.get(envelope.message_type)
        if internal_handler:
            await internal_handler(message, envelope)
            handled = True

        # Call external handlers (e.g., RPCServer, RPCClient)
        external_handlers = self._external_handlers.get(envelope.message_type, [])
        for ext_handler in external_handlers:
            try:
                await ext_handler(message, envelope)
                handled = True
            except Exception as e:
                logger.error(f"External handler error for {envelope.message_type.name}: {e}")

        if not handled:
            logger.warning(f"No handler for message type: {envelope.message_type.name}")

    async def _handle_ping(self, message: LXMFMessage, envelope: StyreneEnvelope) -> None:
        """Handle PING message - log receipt (response deferred)."""
        logger.info(f"PING from {message.source_hash}")
        # TODO: Auto-respond with PONG when RPC is fully implemented

    async def _handle_pong(self, message: LXMFMessage, envelope: StyreneEnvelope) -> None:
        """Handle PONG message - log receipt."""
        logger.info(f"PONG from {message.source_hash}")

    async def _handle_status_request(self, message: LXMFMessage, envelope: StyreneEnvelope) -> None:
        """Handle STATUS_REQUEST - log receipt (response deferred)."""
        logger.info(f"STATUS_REQUEST from {message.source_hash}")
        # TODO: Respond with STATUS_RESPONSE when RPC is fully implemented

    async def _handle_status_response(
        self, message: LXMFMessage, envelope: StyreneEnvelope
    ) -> None:
        """Handle STATUS_RESPONSE - decode and log status data."""
        logger.info(f"STATUS_RESPONSE from {message.source_hash}")
        try:
            status_data = decode_payload(envelope.payload)
            logger.info(f"Status data: {status_data}")
        except PayloadDecodeError as e:
            logger.error(f"Failed to decode status payload: {e}")

    async def _handle_chat(self, message: LXMFMessage, envelope: StyreneEnvelope) -> None:
        """Handle CHAT message - decode and log chat text."""
        logger.info(f"CHAT from {message.source_hash}")
        try:
            chat_data = decode_payload(envelope.payload)
            text = chat_data.get("text", "<no text>")
            logger.info(f"Chat message: {text}")
        except PayloadDecodeError as e:
            logger.error(f"Failed to decode chat payload: {e}")

    async def _handle_announce(self, message: LXMFMessage, envelope: StyreneEnvelope) -> None:
        """Handle ANNOUNCE message - decode and log identity data."""
        logger.info(f"ANNOUNCE from {message.source_hash}")
        try:
            announce_data = decode_payload(envelope.payload)
            logger.info(f"Announce data: {announce_data}")
        except PayloadDecodeError as e:
            logger.error(f"Failed to decode announce payload: {e}")

    def _persist_message(self, message: LXMFMessage, envelope: StyreneEnvelope) -> None:
        """Persist Styrene message to database.

        Args:
            message: Original LXMF message
            envelope: Decoded Styrene envelope
        """
        with Session(self._db_engine) as session:
            db_message = Message(
                source_hash=message.source_hash,
                destination_hash=message.destination_hash,
                timestamp=message.timestamp,
                content=f"[Styrene:{envelope.message_type.name}]",
                protocol_id="styrene",
                status="received",
            )
            db_message.set_fields_dict(
                {
                    "protocol": "styrene",
                    "styrene_version": envelope.version,
                    "styrene_type": envelope.message_type.name,
                }
            )
            session.add(db_message)
            session.commit()

        logger.debug(f"Persisted Styrene message: {envelope.message_type.name}")

    def _resolve_identity(self, destination_hash: str) -> Any:
        """Resolve a destination hash to an RNS Identity.

        This method implements a multi-strategy lookup to find the identity:
        1. Try direct RNS.Identity.recall() with destination_hash
        2. Try NodeStore lookup by operator destination hash
        3. Try NodeStore lookup by LXMF destination hash
        4. Try direct identity hash recall (from_identity_hash=True)

        Args:
            destination_hash: Hex-encoded hash (could be destination or identity).

        Returns:
            RNS.Identity if found, None otherwise.
        """
        dest_bytes = bytes.fromhex(destination_hash)

        # Strategy 1: Direct recall (RNS may have it from announce processing)
        dest_identity = RNS.Identity.recall(dest_bytes)
        if dest_identity:
            logger.debug(
                f"[HASH] Strategy 1 success: direct recall({destination_hash[:16]}...) -> "
                f"identity_hash={dest_identity.hash.hex()[:16]}..."
            )
            return dest_identity

        logger.debug(f"[HASH] Strategy 1 failed: direct recall({destination_hash[:16]}...) -> None")

        # Strategy 2 & 3: NodeStore lookup
        identity_hash = None
        try:
            from styrened.services.node_store import get_node_store

            store = get_node_store()

            # Strategy 2: Try operator destination hash
            identity_hash = store.get_identity_for_destination(destination_hash)
            if identity_hash:
                logger.debug(
                    f"[HASH] Strategy 2 success: operator_dest lookup -> "
                    f"identity_hash={identity_hash[:16]}..."
                )

            # Strategy 3: Try LXMF destination hash
            if not identity_hash:
                identity_hash = store.get_identity_for_lxmf_destination(destination_hash)
                if identity_hash:
                    logger.debug(
                        f"[HASH] Strategy 3 success: lxmf_dest lookup -> "
                        f"identity_hash={identity_hash[:16]}..."
                    )

        except Exception as e:
            logger.warning(f"[HASH] NodeStore lookup failed: {e}")

        # If we found an identity hash in NodeStore, recall it
        if identity_hash:
            identity_bytes = bytes.fromhex(identity_hash)
            # MUST use from_identity_hash=True since this is an identity hash
            dest_identity = RNS.Identity.recall(identity_bytes, from_identity_hash=True)
            if dest_identity:
                logger.info(
                    f"[HASH] Identity resolved: destination={destination_hash[:16]}... -> "
                    f"identity_hash={identity_hash[:16]}... -> Identity OK"
                )
                return dest_identity
            else:
                logger.warning(
                    f"[HASH] NodeStore had identity_hash={identity_hash[:16]}... "
                    f"but RNS.Identity.recall() failed. Identity may not be in RNS cache."
                )

        # Strategy 4: Maybe destination_hash IS the identity hash
        dest_identity = RNS.Identity.recall(dest_bytes, from_identity_hash=True)
        if dest_identity:
            logger.debug(
                f"[HASH] Strategy 4 success: destination WAS identity hash "
                f"({destination_hash[:16]}...)"
            )
            return dest_identity

        logger.debug(
            f"[HASH] All strategies failed for {destination_hash[:16]}... - identity not found"
        )
        return None

    async def send_message(self, destination: str, content: Any) -> None:
        """Send a Styrene message (convenience wrapper for chat).

        This implements the Protocol interface. For typed messages,
        use send_typed_message() instead.

        Args:
            destination: Destination identity hash
            content: Chat message text (string)
        """
        # Default to CHAT message type for string content
        if isinstance(content, str):
            payload = encode_payload({"text": content})
            await self.send_typed_message(
                destination=destination,
                message_type=StyreneMessageType.CHAT,
                payload=payload,
            )
        else:
            raise ValueError(
                "send_message expects string content. Use send_typed_message for typed messages."
            )

    async def send_typed_message(
        self,
        destination: str,
        message_type: StyreneMessageType,
        payload: bytes,
        request_id: bytes | None = None,
    ) -> None:
        """Send a typed Styrene message.

        Creates a StyreneEnvelope, encodes it to wire format, and sends
        via LXMF using FIELD_CUSTOM_TYPE and FIELD_CUSTOM_DATA.

        Args:
            destination: Destination hash (hex string, 32 chars = 16 bytes).
                        Can be an LXMF destination hash or operator destination hash.
            message_type: Type of message to send
            payload: Pre-encoded payload bytes (use encode_payload())
            request_id: Optional 16-byte correlation ID for request/response.
                        If None, auto-generated for v2 messages.

        Raises:
            ImportError: If LXMF/RNS library not available
            ValueError: If destination identity not known (no announce received)
        """
        if LXMF is None or RNS is None:
            raise ImportError("LXMF/RNS library not available")

        logger.info(f"Sending Styrene {message_type.name} to {destination}")

        # Create envelope and encode to wire format
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=message_type,
            payload=payload,
            request_id=request_id,
        )
        wire_data = envelope.encode()

        # Human-readable content for non-Styrene clients
        human_content = f"[styrene.io:{message_type.name}]"

        # Resolve the identity using multi-strategy lookup
        # The destination could be an LXMF destination hash or operator destination hash
        dest_identity = self._resolve_identity(destination)
        if dest_identity is None:
            raise ValueError(
                f"[HASH] Cannot send to {destination[:16]}...: identity not known. "
                "Destination must announce before receiving messages. "
                "Check that the target node has announced its LXMF destination."
            )

        # Create outbound LXMF delivery destination
        dest_destination = RNS.Destination(
            dest_identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            LXMF.APP_NAME,
            "delivery",
        )

        # Create our source destination for signing
        source_destination = RNS.Destination(
            self._identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            LXMF.APP_NAME,
            "delivery",
        )

        # Create LXMF message with proper destination objects
        lxmf_msg = LXMF.LXMessage(
            destination=dest_destination,
            source=source_destination,
            content=human_content,  # Visible to non-Styrene clients
            fields={
                FIELD_CUSTOM_TYPE: STYRENE_CUSTOM_TYPE,  # Protocol identifier
                FIELD_CUSTOM_DATA: wire_data,  # Actual protocol data
            },
        )

        # Register delivery callbacks for debugging
        def on_delivery(message: "LXMF.LXMessage") -> None:
            logger.info(f"[LXMF] Message delivered to {destination[:16]}...")

        def on_failed(message: "LXMF.LXMessage") -> None:
            logger.warning(f"[LXMF] Message delivery FAILED to {destination[:16]}...")

        lxmf_msg.register_delivery_callback(on_delivery)
        lxmf_msg.register_failed_callback(on_failed)

        # Send via router
        self._router.handle_outbound(lxmf_msg)

        # Persist outbound message
        with Session(self._db_engine) as session:
            db_message = Message(
                source_hash=self._identity.hexhash,
                destination_hash=destination,
                timestamp=time.time(),
                content=f"[Styrene:{message_type.name}]",
                protocol_id="styrene",
                status="pending",
            )
            db_message.set_fields_dict(
                {
                    "protocol": "styrene",
                    "styrene_version": STYRENE_VERSION,
                    "styrene_type": message_type.name,
                }
            )
            session.add(db_message)
            session.commit()

        logger.debug(f"Styrene message sent: {message_type.name}")

    # Convenience methods for common message types

    async def send_ping(self, destination: str) -> None:
        """Send a PING message.

        Args:
            destination: Destination identity hash
        """
        await self.send_typed_message(
            destination=destination,
            message_type=StyreneMessageType.PING,
            payload=b"",
        )

    async def send_pong(self, destination: str) -> None:
        """Send a PONG message (response to PING).

        Args:
            destination: Destination identity hash
        """
        await self.send_typed_message(
            destination=destination,
            message_type=StyreneMessageType.PONG,
            payload=b"",
        )

    async def send_status_request(self, destination: str) -> None:
        """Send a STATUS_REQUEST message.

        Args:
            destination: Destination identity hash
        """
        await self.send_typed_message(
            destination=destination,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
        )

    async def send_status_response(self, destination: str, status_data: dict[str, Any]) -> None:
        """Send a STATUS_RESPONSE message.

        Args:
            destination: Destination identity hash
            status_data: Dictionary containing status information
        """
        await self.send_typed_message(
            destination=destination,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=encode_payload(status_data),
        )

    async def send_chat(self, destination: str, text: str) -> None:
        """Send a CHAT message.

        Args:
            destination: Destination identity hash
            text: Chat message text
        """
        await self.send_typed_message(
            destination=destination,
            message_type=StyreneMessageType.CHAT,
            payload=encode_payload({"text": text}),
        )

    async def send_announce(self, destination: str, identity_data: dict[str, Any]) -> None:
        """Send an ANNOUNCE message.

        Args:
            destination: Destination identity hash
            identity_data: Dictionary containing identity/capability info
        """
        await self.send_typed_message(
            destination=destination,
            message_type=StyreneMessageType.ANNOUNCE,
            payload=encode_payload(identity_data),
        )

    async def send(self, destination: str, envelope: StyreneEnvelope) -> None:
        """Send a pre-built StyreneEnvelope to a destination.

        This is a convenience method for terminal sessions that build
        their own envelopes.

        Args:
            destination: Destination hash (hex string)
            envelope: Pre-built StyreneEnvelope to send
        """
        await self.send_typed_message(
            destination=destination,
            message_type=envelope.message_type,
            payload=envelope.payload,
            request_id=envelope.request_id,
        )

    async def send_to_identity(self, identity_hash: str, envelope: StyreneEnvelope) -> None:
        """Send a pre-built StyreneEnvelope to an identity hash.

        This is an alias for send() since the destination resolution
        handles both identity hashes and destination hashes.

        Args:
            identity_hash: Identity hash (hex string)
            envelope: Pre-built StyreneEnvelope to send
        """
        await self.send(identity_hash, envelope)
