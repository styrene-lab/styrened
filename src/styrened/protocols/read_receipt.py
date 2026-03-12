"""Read receipt protocol for message read acknowledgment.

This protocol handles sending and receiving read receipts between peers.
Read receipts indicate that a user has read specific messages, enabling
multi-client awareness of message read status.

Note: This is distinct from LXMF delivery receipts (implicit RNS packet acks).
Delivery receipts indicate network delivery; read receipts indicate user viewing.

Design decisions:
- Application-level protocol, not part of core chat
- Uses LXMF message hashes for message identification
- Batches multiple message hashes per receipt for efficiency
- Only sends receipts for messages that have been locally marked as read
"""
from __future__ import annotations


import logging
import time
from typing import TYPE_CHECKING, Any

from styrened.protocols.base import LXMFMessage, Protocol

if TYPE_CHECKING:
    from styrened.services.conversation_service import ConversationService
    from styrened.services.lxmf_service import LXMFService

logger = logging.getLogger(__name__)


class ReadReceiptProtocol(Protocol):
    """Protocol for sending/receiving read receipts.

    This protocol:
    - Handles incoming read receipts by marking outgoing messages as read
    - Sends read receipts when messages are marked as read locally
    - Batches receipts for efficiency (multiple hashes per message)

    Usage:
        protocol = ReadReceiptProtocol(conversation_service, lxmf_service)
        registry.register(protocol)

        # When user marks conversation as read
        hashes = conversation_service.get_unread_hashes_for_receipt(peer_hash)
        if hashes:
            protocol.send_read_receipt(peer_hash, hashes)
    """

    def __init__(
        self,
        conversation_service: "ConversationService",
        lxmf_service: "LXMFService",
    ) -> None:
        """Initialize ReadReceiptProtocol.

        Args:
            conversation_service: Service for message persistence
            lxmf_service: Service for sending LXMF messages
        """
        self._conversation_service = conversation_service
        self._lxmf_service = lxmf_service

    @property
    def protocol_id(self) -> str:
        """Protocol identifier for routing."""
        return "read_receipt"

    def can_handle(self, message: LXMFMessage) -> bool:
        """Check if message is a read receipt.

        Args:
            message: LXMF message to check

        Returns:
            True if message has protocol="read_receipt"
        """
        return message.fields.get("protocol") == "read_receipt"

    async def handle_message(self, message: LXMFMessage) -> None:
        """Handle incoming read receipt.

        Updates outgoing messages as read by recipient based on the
        message hashes included in the receipt.

        Args:
            message: Incoming read receipt message
        """
        message_hashes = message.fields.get("message_hashes", [])
        receipt_time = message.fields.get("timestamp", time.time())

        if not message_hashes:
            logger.debug("Read receipt with no message hashes, ignoring")
            return

        if not isinstance(message_hashes, list):
            logger.warning(f"Invalid message_hashes type: {type(message_hashes)}")
            return

        # Mark our outgoing messages as read by recipient
        marked_count = 0
        for msg_hash in message_hashes:
            if not isinstance(msg_hash, str):
                continue
            if self._conversation_service.mark_read_by_recipient(
                lxmf_hash=msg_hash,
                read_at=receipt_time,
            ):
                marked_count += 1

        logger.info(
            f"Received read receipt from {message.source_hash[:16]}... "
            f"for {len(message_hashes)} messages ({marked_count} updated)"
        )

    async def send_message(self, destination: str, content: Any) -> None:
        """Send a read receipt to a peer.

        Args:
            destination: Peer's LXMF destination hash
            content: Dict with "message_hashes" list

        Note:
            Prefer using send_read_receipt() for clearer API.
        """
        if not isinstance(content, dict):
            logger.warning("send_message content must be dict with message_hashes")
            return

        message_hashes = content.get("message_hashes", [])
        if not message_hashes:
            return

        self.send_read_receipt(destination, message_hashes)

    def send_read_receipt(
        self,
        peer_hash: str,
        message_hashes: list[str],
    ) -> bool:
        """Send read receipt to peer.

        This should be called after marking messages as read locally.
        The message_hashes should be LXMF message hashes (hex-encoded)
        of incoming messages we've read.

        Args:
            peer_hash: LXMF destination hash of the peer
            message_hashes: List of LXMF message hashes we've read

        Returns:
            True if receipt was sent successfully
        """
        if not message_hashes:
            return False

        payload: dict[str, object] = {
            "protocol": "read_receipt",
            "message_hashes": message_hashes,
            "timestamp": time.time(),
        }

        result = self._lxmf_service.send_message(
            destination_hash=peer_hash,
            payload=payload,
        )

        if result is not None:
            logger.debug(
                f"Sent read receipt to {peer_hash[:16]}... for {len(message_hashes)} messages"
            )
            return True
        else:
            logger.warning(f"Failed to send read receipt to {peer_hash[:16]}...")
            return False
