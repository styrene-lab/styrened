"""ChatProtocol implementation for text messaging over LXMF.

This module implements a simple chat protocol using the Protocol interface.
Messages are persisted to the database and can be retrieved for conversation history.

Design decisions:
- Protocol ID: "chat"
- Uses LXMF.LXMessage for transmission
- Stores all messages (sent and received) in database
- Conversation history ordered by timestamp

Note: This protocol depends on node_store service which will be migrated in a later phase.
"""

import logging
import time
from typing import Any

from sqlalchemy import or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

try:
    import LXMF
    import RNS
except ImportError:
    # Allow imports for testing without RNS/LXMF installed
    LXMF = None
    RNS = None

from styrened.models.messages import Message
from styrened.protocols.base import LXMFMessage, Protocol

logger = logging.getLogger(__name__)


class ChatProtocol(Protocol):
    """Chat protocol for text messaging.

    Implements simple text chat functionality over LXMF. Messages are
    persisted to the database and can be retrieved for conversation history.

    Example:
        ```python
        chat = ChatProtocol(router, identity, db_engine, node_store)

        # Send message
        await chat.send_message("destination_hash", "Hello!")

        # Get conversation history
        messages = chat.get_conversation_history("alice", "bob")
        ```
    """

    def __init__(
        self,
        router: Any,  # LXMF.LXMRouter
        identity: Any,  # RNS.Identity
        db_engine: Engine,
        node_store: Any | None = None,  # Optional for testing/headless mode
    ) -> None:
        """Initialize ChatProtocol.

        Args:
            router: LXMF router instance
            identity: RNS identity for this node
            db_engine: SQLAlchemy engine for message persistence
            node_store: Optional node store for destination lookup (required for send_message)
        """
        self._router = router
        self._identity = identity
        self._db_engine = db_engine
        self._node_store = node_store

    @property
    def protocol_id(self) -> str:
        """Protocol identifier for chat messages."""
        return "chat"

    def can_handle(self, message: LXMFMessage) -> bool:
        """Determine if this is a chat message.

        Args:
            message: LXMF message to evaluate

        Returns:
            True if message.fields["protocol"] == "chat"
        """
        return message.get_protocol() == "chat"

    async def handle_message(self, message: LXMFMessage) -> None:
        """Handle incoming chat message.

        Saves message to database for conversation history.

        Args:
            message: Incoming LXMF message
        """
        logger.info(f"Received chat message from {message.source_hash}: {message.content}")

        # Save to database
        with Session(self._db_engine) as session:
            db_message = Message(
                source_hash=message.source_hash,
                destination_hash=message.destination_hash,
                timestamp=message.timestamp,
                content=message.content,
                protocol_id="chat",
                status="pending",  # Will be updated when delivered
            )
            db_message.set_fields_dict(message.fields)
            session.add(db_message)
            session.commit()

        logger.debug(f"Saved chat message to database: {message.source_hash}")

    async def send_message(self, destination: str, content: str) -> None:
        """Send chat message.

        Creates LXMF message with protocol="chat" in fields dictionary,
        sends via LXMF router, and saves to database.

        Args:
            destination: Destination hash (hex string, 32 chars = 16 bytes)
            content: Message content (text)

        Raises:
            ImportError: If LXMF library not available
            ValueError: If destination identity not known (no announce received)
        """
        if LXMF is None or RNS is None:
            raise ImportError("LXMF/RNS library not available")

        logger.info(f"Sending chat message to {destination}")

        # Require node_store for destination lookup
        if self._node_store is None:
            raise RuntimeError(
                "ChatProtocol requires a node_store to send messages. "
                "Pass node_store parameter to __init__."
            )

        # Look up node info for this operator destination
        # We need both the identity_hash (for Identity.recall) and verification that LXMF is available
        node = self._node_store.get_node_by_destination(destination)
        if node is None:
            raise ValueError(
                f"Cannot send to {destination}: node not found in node store. "
                "Destination must announce before receiving messages."
            )

        if not node.lxmf_destination_hash:
            raise ValueError(
                f"Cannot send to {destination}: node does not have LXMF capability. "
                "LXMF destination not announced."
            )

        # Convert identity hash to bytes (32 hex chars -> 16 bytes)
        # Note: We use identity_hash (public key hash), NOT lxmf_destination_hash
        # Both operator and LXMF destinations share the same underlying identity
        identity_bytes = bytes.fromhex(node.identity_hash)

        # Recall the identity for this node
        # This requires that we've seen an announce from this identity
        dest_identity = RNS.Identity.recall(identity_bytes)
        if dest_identity is None:
            raise ValueError(
                f"Cannot send to {destination}: identity {node.identity_hash[:16]}... not known to RNS. "
                "Node must announce before receiving messages."
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
            content=content.encode() if isinstance(content, str) else content,
            fields={"protocol": "chat"},
        )

        # Send via router
        self._router.handle_outbound(lxmf_msg)

        # Save to database
        with Session(self._db_engine) as session:
            db_message = Message(
                source_hash=self._identity.hexhash,
                destination_hash=destination,
                timestamp=time.time(),
                content=content,
                protocol_id="chat",
                status="pending",
            )
            db_message.set_fields_dict({"protocol": "chat"})
            session.add(db_message)
            session.commit()

        logger.debug(f"Chat message sent and saved: {destination}")

    def get_conversation_history(self, identity_a: str, identity_b: str) -> list[Message]:
        """Retrieve conversation history between two identities.

        Returns all chat messages (sent and received) between two parties,
        ordered by timestamp ascending.

        Args:
            identity_a: First identity hash
            identity_b: Second identity hash

        Returns:
            List of Message objects ordered by timestamp
        """
        with Session(self._db_engine) as session:
            messages = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    or_(
                        # A -> B
                        (Message.source_hash == identity_a)
                        & (Message.destination_hash == identity_b),
                        # B -> A
                        (Message.source_hash == identity_b)
                        & (Message.destination_hash == identity_a),
                    ),
                )
                .order_by(Message.timestamp.asc())
                .all()
            )

            return messages
