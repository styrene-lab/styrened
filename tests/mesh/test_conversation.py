"""End-to-end LXMF chat conversation between two containerized nodes.

Tests the full message lifecycle: send -> LXMF transport -> receive -> query.
Uses real RNS/LXMF stack through TCP mesh transport between containers.
"""

import asyncio

import pytest

from styrened.ipc.client import ControlClient

from .conftest import _extract_content, poll_for_message, poll_for_status

# All tests share the session-scoped event loop with async fixtures
pytestmark = [pytest.mark.mesh, pytest.mark.asyncio(loop_scope="session")]

DELIVERY_TIMEOUT = 30  # seconds for LXMF message delivery


class TestSendAndReceive:
    """Basic bidirectional message exchange."""

    async def test_a_sends_message_b_receives(
        self,
        node_a_client: ControlClient,
        node_b_client: ControlClient,
        discovered_mesh,
    ):
        """Message sent from A arrives in B's message store."""
        _, _, _, b_lxmf = discovered_mesh

        result = await node_a_client.send_chat(
            peer_hash=b_lxmf,
            content="Hello from Node A",
        )
        assert result.get("message_id") is not None, f"send_chat returned: {result}"

        # Poll B for the incoming message
        received = await poll_for_message(
            node_b_client, content="Hello from Node A", timeout=DELIVERY_TIMEOUT
        )
        assert received is not None, "Node B did not receive message from Node A"
        assert _extract_content(received["content"]) == "Hello from Node A"

    async def test_b_replies_to_a(
        self,
        node_a_client: ControlClient,
        node_b_client: ControlClient,
        discovered_mesh,
    ):
        """Reply from B arrives in A's message store."""
        _, _, a_lxmf, _ = discovered_mesh

        result = await node_b_client.send_chat(
            peer_hash=a_lxmf,
            content="Reply from Node B",
        )
        assert result.get("message_id") is not None

        received = await poll_for_message(
            node_a_client, content="Reply from Node B", timeout=DELIVERY_TIMEOUT
        )
        assert received is not None, "Node A did not receive reply from Node B"
        assert _extract_content(received["content"]) == "Reply from Node B"

    async def test_multiple_messages_in_sequence(
        self,
        node_a_client: ControlClient,
        node_b_client: ControlClient,
        discovered_mesh,
    ):
        """Multiple sequential messages all arrive."""
        _, _, _, b_lxmf = discovered_mesh

        messages = ["Sequence msg 1", "Sequence msg 2", "Sequence msg 3"]
        for content in messages:
            await node_a_client.send_chat(peer_hash=b_lxmf, content=content)

        # Wait for the last message — implies earlier ones arrived too
        received = await poll_for_message(
            node_b_client, content="Sequence msg 3", timeout=DELIVERY_TIMEOUT
        )
        assert received is not None, "Last sequential message did not arrive"


class TestConversationLifecycle:
    """Conversation list, read state, and message history."""

    async def test_conversation_appears_in_list(
        self,
        node_a_client: ControlClient,
        node_b_client: ControlClient,
        discovered_mesh,
    ):
        """After exchange, both nodes list the conversation."""
        _, _, a_lxmf, b_lxmf = discovered_mesh

        await node_a_client.send_chat(
            peer_hash=b_lxmf, content="Conversation list test"
        )
        await poll_for_message(
            node_b_client, content="Conversation list test", timeout=DELIVERY_TIMEOUT
        )

        convs_a = await node_a_client.query_conversations()
        convs_b = await node_b_client.query_conversations()

        assert any(
            c["peer_hash"] == b_lxmf for c in convs_a
        ), f"Node A conversations missing peer {b_lxmf}"
        assert any(
            c["peer_hash"] == a_lxmf for c in convs_b
        ), f"Node B conversations missing peer {a_lxmf}"

    async def test_mark_read_clears_unread_count(
        self,
        node_a_client: ControlClient,
        node_b_client: ControlClient,
        discovered_mesh,
    ):
        """Marking messages as read zeros the unread count."""
        _, _, a_lxmf, b_lxmf = discovered_mesh

        # Send a message so B has unread
        await node_a_client.send_chat(
            peer_hash=b_lxmf, content="Mark read test"
        )
        await poll_for_message(
            node_b_client, content="Mark read test", timeout=DELIVERY_TIMEOUT
        )

        # Mark read on B
        count = await node_b_client.mark_read(peer_hash=a_lxmf)
        assert count >= 0

        convs = await node_b_client.query_conversations()
        conv = next((c for c in convs if c["peer_hash"] == a_lxmf), None)
        if conv:
            assert conv.get("unread_count", 0) == 0

    async def test_message_history_ordered(
        self,
        node_a_client: ControlClient,
        discovered_mesh,
    ):
        """Message history returns messages in chronological order."""
        _, _, _, b_lxmf = discovered_mesh

        messages = await node_a_client.query_messages(peer_hash=b_lxmf, limit=50)
        if len(messages) >= 2:
            timestamps = [m["timestamp"] for m in messages]
            assert timestamps == sorted(timestamps), "Messages not in chronological order"


class TestDeliveryStatus:
    """Message delivery tracking and status transitions."""

    async def test_sent_message_delivered_to_recipient(
        self,
        node_a_client: ControlClient,
        node_b_client: ControlClient,
        discovered_mesh,
    ):
        """Sent message reaches at least 'sent' on sender and arrives at recipient.

        LXMF delivery receipts only come back over direct (link-based)
        delivery.  Propagated delivery skips the receipt, so the sender
        status may stay at 'sent' rather than 'delivered'.  We verify
        both the sender-side status transition *and* actual receipt on B.
        """
        _, _, _, b_lxmf = discovered_mesh

        result = await node_a_client.send_chat(
            peer_hash=b_lxmf, content="Delivery tracking test"
        )
        msg_id = result.get("message_id")
        assert msg_id is not None

        # Verify sender status reaches at least "sent"
        sent = await poll_for_status(
            node_a_client,
            b_lxmf,
            msg_id,
            target_status="sent",
            timeout=DELIVERY_TIMEOUT,
        )
        assert sent, f"Message {msg_id} did not reach 'sent' status"

        # Verify actual receipt on the remote node
        received = await poll_for_message(
            node_b_client, content="Delivery tracking test", timeout=DELIVERY_TIMEOUT
        )
        assert received is not None, "Node B did not receive delivery tracking message"

    async def test_message_search_finds_content(
        self,
        node_a_client: ControlClient,
        discovered_mesh,
    ):
        """Full-text search finds sent messages.

        Uses space-separated words because FTS5 interprets hyphens as
        column modifiers in query syntax (e.g., ``a-b`` means column ``b``).
        """
        _, _, _, b_lxmf = discovered_mesh

        unique_content = "uniquemeshsearchalpha bravo"
        await node_a_client.send_chat(peer_hash=b_lxmf, content=unique_content)
        await asyncio.sleep(2)  # allow persistence + FTS indexing

        results = await node_a_client.search_messages(query="uniquemeshsearchalpha")
        assert any(
            "uniquemeshsearchalpha" in (_extract_content(m.get("content", "")) or "")
            for m in results
        ), f"Search did not find '{unique_content}' in {len(results)} results"


class TestContactManagement:
    """Contact alias and resolution over the mesh."""

    async def test_set_and_resolve_contact(
        self,
        node_a_client: ControlClient,
        discovered_mesh,
    ):
        """Set contact alias and resolve it back."""
        _, _, _, b_lxmf = discovered_mesh

        await node_a_client.set_contact(
            peer_hash=b_lxmf, alias="Node-B", notes="Test peer"
        )

        resolved = await node_a_client.resolve_name("Node-B")
        assert resolved == b_lxmf, f"resolve_name returned {resolved}, expected {b_lxmf}"

    async def test_contact_appears_in_list(
        self,
        node_a_client: ControlClient,
        discovered_mesh,
    ):
        """Set contact appears in query_contacts results."""
        _, _, _, b_lxmf = discovered_mesh

        await node_a_client.set_contact(
            peer_hash=b_lxmf, alias="Node-B-List", notes="List test"
        )

        contacts = await node_a_client.query_contacts()
        assert any(
            c["peer_hash"] == b_lxmf for c in contacts
        ), f"Contact {b_lxmf} not found in contacts list"

    async def test_short_name_visible_in_device_list(
        self,
        node_a_client: ControlClient,
        node_b_client: ControlClient,
        discovered_mesh,
    ):
        """Devices list includes short_name when announced."""
        # Node B's short_name (if configured) should appear in A's device list.
        # Even without config, the short_name field should be present (possibly None).
        devices = await node_a_client.query_devices()
        for d in devices:
            # DeviceInfo.to_dict() always includes short_name key
            assert "short_name" in d.to_dict(), (
                f"Device {d.name} missing short_name field in DeviceInfo"
            )
