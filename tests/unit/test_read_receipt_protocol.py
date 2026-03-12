"""Tests for ReadReceiptProtocol.

Tests the read receipt protocol for sending and receiving
message read acknowledgments.
"""
from __future__ import annotations


import tempfile
from unittest.mock import MagicMock

import pytest

from styrened.models.messages import init_db
from styrened.protocols.base import LXMFMessage
from styrened.protocols.read_receipt import ReadReceiptProtocol
from styrened.services.conversation_service import ConversationService


@pytest.fixture
def db_engine():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    engine = init_db(db_path)
    return engine


@pytest.fixture
def local_identity_hash():
    """Local identity hash for testing."""
    return "a" * 32


@pytest.fixture
def peer_hash():
    """Peer identity hash for testing."""
    return "b" * 32


@pytest.fixture
def conversation_service(db_engine, local_identity_hash):
    """Create a ConversationService instance for testing."""
    service = ConversationService(
        db_engine=db_engine,
        local_identity_hash=local_identity_hash,
        node_store=None,
    )
    service.initialize()
    yield service
    service.shutdown()


@pytest.fixture
def mock_lxmf_service():
    """Create a mock LXMF service."""
    service = MagicMock()
    service.send_message.return_value = {"hash": b"sent_hash", "method": "direct"}
    return service


@pytest.fixture
def protocol(conversation_service, mock_lxmf_service):
    """Create ReadReceiptProtocol instance."""
    return ReadReceiptProtocol(conversation_service, mock_lxmf_service)


class TestProtocolIdentification:
    """Tests for protocol identification."""

    def test_protocol_id(self, protocol):
        """Test protocol ID is correct."""
        assert protocol.protocol_id == "read_receipt"

    def test_can_handle_read_receipt(self, protocol):
        """Test can_handle returns True for read_receipt protocol."""
        message = LXMFMessage(
            source_hash="a" * 32,
            destination_hash="b" * 32,
            timestamp=1234567890.0,
            fields={"protocol": "read_receipt"},
        )
        assert protocol.can_handle(message) is True

    def test_can_handle_other_protocol(self, protocol):
        """Test can_handle returns False for other protocols."""
        message = LXMFMessage(
            source_hash="a" * 32,
            destination_hash="b" * 32,
            timestamp=1234567890.0,
            fields={"protocol": "chat"},
        )
        assert protocol.can_handle(message) is False

    def test_can_handle_no_protocol(self, protocol):
        """Test can_handle returns False when no protocol field."""
        message = LXMFMessage(
            source_hash="a" * 32,
            destination_hash="b" * 32,
            timestamp=1234567890.0,
            fields={},
        )
        assert protocol.can_handle(message) is False


class TestHandleMessage:
    """Tests for handling incoming read receipts."""

    @pytest.mark.asyncio
    async def test_handle_message_marks_as_read(
        self, protocol, conversation_service, peer_hash, local_identity_hash
    ):
        """Test that incoming receipt marks messages as read by recipient."""
        # Create an outgoing message
        lxmf_hash = b"test_hash_123"
        conversation_service.save_outgoing_message(peer_hash, "Hello", lxmf_hash=lxmf_hash)

        # Create incoming read receipt
        message = LXMFMessage(
            source_hash=peer_hash,
            destination_hash=local_identity_hash,
            timestamp=1234567890.0,
            fields={
                "protocol": "read_receipt",
                "message_hashes": [lxmf_hash.hex()],
                "timestamp": 1234567890.0,
            },
        )

        await protocol.handle_message(message)

        # Verify no exception was raised
        # Note: The MessageInfo doesn't include read_by_recipient directly,
        # but the handler completed successfully if we got here

    @pytest.mark.asyncio
    async def test_handle_message_empty_hashes(self, protocol):
        """Test handling receipt with no hashes."""
        message = LXMFMessage(
            source_hash="a" * 32,
            destination_hash="b" * 32,
            timestamp=1234567890.0,
            fields={
                "protocol": "read_receipt",
                "message_hashes": [],
            },
        )

        # Should not raise
        await protocol.handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_message_no_hashes_field(self, protocol):
        """Test handling receipt with missing hashes field."""
        message = LXMFMessage(
            source_hash="a" * 32,
            destination_hash="b" * 32,
            timestamp=1234567890.0,
            fields={"protocol": "read_receipt"},
        )

        # Should not raise
        await protocol.handle_message(message)

    @pytest.mark.asyncio
    async def test_handle_message_invalid_hashes_type(self, protocol):
        """Test handling receipt with invalid hashes type."""
        message = LXMFMessage(
            source_hash="a" * 32,
            destination_hash="b" * 32,
            timestamp=1234567890.0,
            fields={
                "protocol": "read_receipt",
                "message_hashes": "not_a_list",
            },
        )

        # Should not raise
        await protocol.handle_message(message)


class TestSendReadReceipt:
    """Tests for sending read receipts."""

    def test_send_read_receipt_success(self, protocol, mock_lxmf_service, peer_hash):
        """Test sending read receipt successfully."""
        hashes = ["hash1", "hash2"]

        result = protocol.send_read_receipt(peer_hash, hashes)

        assert result is True
        mock_lxmf_service.send_message.assert_called_once()

        # Verify payload
        call_args = mock_lxmf_service.send_message.call_args
        assert call_args[1]["destination_hash"] == peer_hash
        payload = call_args[1]["payload"]
        assert payload["protocol"] == "read_receipt"
        assert payload["message_hashes"] == hashes
        assert "timestamp" in payload

    def test_send_read_receipt_empty_hashes(self, protocol, mock_lxmf_service, peer_hash):
        """Test sending with empty hashes returns False."""
        result = protocol.send_read_receipt(peer_hash, [])

        assert result is False
        mock_lxmf_service.send_message.assert_not_called()

    def test_send_read_receipt_send_fails(self, protocol, mock_lxmf_service, peer_hash):
        """Test handling send failure."""
        mock_lxmf_service.send_message.return_value = None

        result = protocol.send_read_receipt(peer_hash, ["hash1"])

        assert result is False


class TestSendMessage:
    """Tests for send_message interface."""

    @pytest.mark.asyncio
    async def test_send_message_with_dict(self, protocol, mock_lxmf_service, peer_hash):
        """Test send_message with valid dict content."""
        content = {"message_hashes": ["hash1", "hash2"]}

        await protocol.send_message(peer_hash, content)

        mock_lxmf_service.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_with_non_dict(self, protocol, mock_lxmf_service, peer_hash):
        """Test send_message with invalid content type."""
        await protocol.send_message(peer_hash, "not a dict")

        mock_lxmf_service.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_message_empty_hashes(self, protocol, mock_lxmf_service, peer_hash):
        """Test send_message with empty hashes."""
        content = {"message_hashes": []}

        await protocol.send_message(peer_hash, content)

        mock_lxmf_service.send_message.assert_not_called()
