"""Integration tests for chat messaging over LXMF.

Tests end-to-end message flow:
- ChatProtocol message handling and persistence
- ProtocolRegistry routing
- Conversation history across multiple participants
- LXMessage creation with correct source/destination parameters

Note: These tests focus on message handling and persistence logic.
Tests requiring full LXMF network initialization (send_message) are
separate unit tests with appropriate mocking.

Fixtures used from conftest.py:
- mock_router: Mock LXMF router
- mock_identity: Mock RNS identity
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

# Check if LXMF is available for integration tests
try:
    import LXMF  # type: ignore[import-untyped]

    LXMF_AVAILABLE = True
except ImportError:
    LXMF_AVAILABLE = False

from styrened.models.messages import init_db
from styrened.protocols.base import LXMFMessage
from styrened.protocols.chat import ChatProtocol
from styrened.protocols.registry import ProtocolRegistry


@pytest.fixture
def test_db_alice(tmp_path):
    """Create Alice's database."""
    db_path = tmp_path / "alice.db"
    return init_db(str(db_path))


@pytest.fixture
def test_db_bob(tmp_path):
    """Create Bob's database."""
    db_path = tmp_path / "bob.db"
    return init_db(str(db_path))


# mock_router and mock_identity fixtures are inherited from conftest.py


@pytest.fixture
def alice_mock_identity():
    """Create mock identity for Alice."""
    identity = Mock()
    identity.hexhash = "alice_identity_hash_abc123"
    return identity


@pytest.fixture
def bob_mock_identity():
    """Create mock identity for Bob."""
    identity = Mock()
    identity.hexhash = "bob_identity_hash_def456"
    return identity


@pytest.mark.asyncio
async def test_chat_protocol_end_to_end(
    test_db_bob, mock_router, alice_mock_identity, bob_mock_identity
):
    """Test end-to-end chat message flow through handle_message.

    This tests the core protocol logic: message handling, persistence,
    and conversation history retrieval.
    """
    # Create ChatProtocol instance for Bob (receiver)
    bob_chat = ChatProtocol(
        router=mock_router,
        identity=bob_mock_identity,
        db_engine=test_db_bob,
    )

    alice_hash = alice_mock_identity.hexhash
    bob_hash = bob_mock_identity.hexhash

    # Simulate Alice sending message to Bob (message arrives at Bob's node)
    incoming_msg = LXMFMessage(
        source_hash=alice_hash,
        destination_hash=bob_hash,
        timestamp=100.0,
        content="Hello Bob!",
        fields={"protocol": "chat"},
        protocol_id="chat",
    )

    # Bob handles incoming message
    await bob_chat.handle_message(incoming_msg)

    # Verify Bob's database has the message
    bob_history = bob_chat.get_conversation_history(alice_hash, bob_hash)
    assert len(bob_history) == 1
    assert bob_history[0].content == "Hello Bob!"
    assert bob_history[0].source_hash == alice_hash


@pytest.mark.asyncio
async def test_protocol_registry_routing(test_db_alice, mock_router, mock_identity):
    """Test ProtocolRegistry routes messages to correct protocol."""
    # Create ChatProtocol and ProtocolRegistry
    chat = ChatProtocol(
        router=mock_router,
        identity=mock_identity,
        db_engine=test_db_alice,
    )
    chat._identity.hexhash = "alice_hash"

    registry = ProtocolRegistry()
    registry.register_protocol(chat)

    # Create chat message
    msg = LXMFMessage(
        source_hash="bob_hash",
        destination_hash="alice_hash",
        timestamp=200.0,
        content="Test message",
        fields={"protocol": "chat"},
        protocol_id="chat",
    )

    # Route via registry
    await registry.route_message(msg)

    # Verify message was handled by ChatProtocol (saved to database)
    history = chat.get_conversation_history("alice_hash", "bob_hash")
    assert len(history) == 1
    assert history[0].content == "Test message"


@pytest.mark.asyncio
async def test_bidirectional_conversation(
    test_db_alice, test_db_bob, mock_router, alice_mock_identity, bob_mock_identity
):
    """Test bidirectional message exchange through handle_message.

    Simulates a full conversation where messages are exchanged both ways,
    testing that both parties maintain consistent conversation history.
    """
    # Setup Alice and Bob
    alice = ChatProtocol(mock_router, alice_mock_identity, test_db_alice)
    bob = ChatProtocol(mock_router, bob_mock_identity, test_db_bob)

    alice_hash = alice_mock_identity.hexhash
    bob_hash = bob_mock_identity.hexhash

    # Simulate Alice's message arriving at Bob
    msg1 = LXMFMessage(
        source_hash=alice_hash,
        destination_hash=bob_hash,
        timestamp=100.0,
        content="Hi Bob!",
        fields={"protocol": "chat"},
        protocol_id="chat",
    )
    await bob.handle_message(msg1)

    # Simulate Alice also storing her outbound message (for her history)
    await alice.handle_message(msg1)

    # Simulate Bob's reply arriving at Alice
    msg2 = LXMFMessage(
        source_hash=bob_hash,
        destination_hash=alice_hash,
        timestamp=200.0,
        content="Hi Alice!",
        fields={"protocol": "chat"},
        protocol_id="chat",
    )
    await alice.handle_message(msg2)

    # Simulate Bob also storing his outbound message
    await bob.handle_message(msg2)

    # Verify both have full conversation history
    alice_history = alice.get_conversation_history(alice_hash, bob_hash)
    bob_history = bob.get_conversation_history(bob_hash, alice_hash)

    assert len(alice_history) == 2
    assert len(bob_history) == 2

    # Alice's view
    assert alice_history[0].content == "Hi Bob!"
    assert alice_history[1].content == "Hi Alice!"

    # Bob's view
    assert bob_history[0].content == "Hi Bob!"
    assert bob_history[1].content == "Hi Alice!"


@pytest.mark.asyncio
async def test_message_persistence_across_instances(tmp_path, mock_router, mock_identity):
    """Test message persistence survives ChatProtocol recreation."""
    db_path = tmp_path / "persist.db"
    engine = init_db(str(db_path))

    # Create first instance and handle a message
    chat1 = ChatProtocol(mock_router, mock_identity, engine)
    chat1._identity.hexhash = "alice_hash"

    msg = LXMFMessage(
        source_hash="bob_hash",
        destination_hash="alice_hash",
        timestamp=100.0,
        content="Persisted message",
        fields={"protocol": "chat"},
        protocol_id="chat",
    )
    await chat1.handle_message(msg)

    # Create new instance with same database
    chat2 = ChatProtocol(mock_router, mock_identity, engine)
    chat2._identity.hexhash = "alice_hash"

    # Verify message is still there
    history = chat2.get_conversation_history("alice_hash", "bob_hash")
    assert len(history) == 1
    assert history[0].content == "Persisted message"


@pytest.mark.asyncio
async def test_multiple_conversations_isolated(test_db_alice, mock_router, alice_mock_identity):
    """Test that conversations with different peers are properly isolated."""
    alice = ChatProtocol(mock_router, alice_mock_identity, test_db_alice)
    alice_hash = alice_mock_identity.hexhash

    # Message from Bob
    msg_from_bob = LXMFMessage(
        source_hash="bob_hash",
        destination_hash=alice_hash,
        timestamp=100.0,
        content="Hello from Bob",
        fields={"protocol": "chat"},
        protocol_id="chat",
    )
    await alice.handle_message(msg_from_bob)

    # Message from Carol
    msg_from_carol = LXMFMessage(
        source_hash="carol_hash",
        destination_hash=alice_hash,
        timestamp=200.0,
        content="Hello from Carol",
        fields={"protocol": "chat"},
        protocol_id="chat",
    )
    await alice.handle_message(msg_from_carol)

    # Verify conversations are isolated
    bob_history = alice.get_conversation_history(alice_hash, "bob_hash")
    carol_history = alice.get_conversation_history(alice_hash, "carol_hash")

    assert len(bob_history) == 1
    assert bob_history[0].content == "Hello from Bob"

    assert len(carol_history) == 1
    assert carol_history[0].content == "Hello from Carol"


@pytest.mark.skipif(not LXMF_AVAILABLE, reason="LXMF library not installed")
def test_lxmessage_creation_with_source_hash():
    """Test that LXMessage can be created with source=None and source_hash.

    This verifies the fix for ValueError: LXMessage initialised with invalid source.
    The LXMF library requires source to be either RNS.Destination or None.
    When using source=None, source_hash must be provided.
    """
    # Create a fake source hash (16 bytes for Reticulum identity hash)
    source_hash = b"0123456789abcdef"
    destination_hash = b"fedcba9876543210"
    content = b"Test message content"

    # This should NOT raise ValueError
    message = LXMF.LXMessage(
        destination=None,
        source=None,
        content=content,
        destination_hash=destination_hash,
        source_hash=source_hash,
    )

    assert message is not None
    assert message.content == content


@pytest.mark.skipif(not LXMF_AVAILABLE, reason="LXMF library not installed")
def test_lxmessage_creation_with_fields():
    """Test LXMessage creation with fields parameter for protocol identification."""
    source_hash = b"0123456789abcdef"
    destination_hash = b"fedcba9876543210"
    content = b"Chat message"
    fields = {"protocol": "chat"}

    message = LXMF.LXMessage(
        destination=None,
        source=None,
        content=content,
        fields=fields,
        destination_hash=destination_hash,
        source_hash=source_hash,
    )

    assert message is not None
    assert message.fields == fields
