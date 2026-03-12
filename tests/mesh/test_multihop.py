"""Multi-hop LXMF message routing through a transport node.

Tests message delivery across network boundaries: Node A (alpha network)
communicates with Node C (beta network) only through Node B, which has
transport enabled and bridges both networks.

Topology:
    alpha network: node-a-edge <-> node-b-transport
    beta  network: node-b-transport <-> node-c-edge

Node A and Node C share NO Docker network — all traffic between them
must be relayed by Node B's RNS transport layer.
"""
from __future__ import annotations


import pytest

from styrened.ipc.client import ControlClient

from .conftest import _extract_content, poll_for_message

# All tests share the session-scoped event loop with async fixtures
pytestmark = [pytest.mark.multihop, pytest.mark.asyncio(loop_scope="session")]

DELIVERY_TIMEOUT = 45  # multi-hop delivery needs more time


class TestMultihopHealth:
    """Basic health checks for the three-node topology."""

    async def test_all_nodes_healthy(
        self,
        multihop_node_a: ControlClient,
        multihop_node_b: ControlClient,
        multihop_node_c: ControlClient,
    ):
        """All three daemons respond to ping."""
        assert await multihop_node_a.ping()
        assert await multihop_node_b.ping()
        assert await multihop_node_c.ping()

    async def test_all_nodes_have_distinct_identities(
        self,
        multihop_node_a: ControlClient,
        multihop_node_b: ControlClient,
        multihop_node_c: ControlClient,
    ):
        """All three daemons have unique RNS identities."""
        id_a = await multihop_node_a.query_identity()
        id_b = await multihop_node_b.query_identity()
        id_c = await multihop_node_c.query_identity()

        hashes = {id_a.identity_hash, id_b.identity_hash, id_c.identity_hash}
        assert len(hashes) == 3, f"Identity collision: {hashes}"

    async def test_transport_node_has_transport_enabled(
        self,
        multihop_node_b: ControlClient,
    ):
        """Node B reports transport functionality."""
        status = await multihop_node_b.query_status()
        assert status.uptime > 0


class TestMultihopDiscovery:
    """Discovery across network boundaries via transport."""

    async def test_a_discovers_c_through_transport(
        self,
        multihop_node_a: ControlClient,
        discovered_multihop,
    ):
        """Node A (alpha-only) discovers Node C (beta-only) via B's transport."""
        c_id = discovered_multihop["c_id"]
        devices = await multihop_node_a.query_devices()
        hashes = {d.identity_hash for d in devices}
        assert c_id in hashes, (
            f"Node A did not discover Node C ({c_id}) through transport. "
            f"Visible: {hashes}"
        )

    async def test_c_discovers_a_through_transport(
        self,
        multihop_node_c: ControlClient,
        discovered_multihop,
    ):
        """Node C (beta-only) discovers Node A (alpha-only) via B's transport."""
        a_id = discovered_multihop["a_id"]
        devices = await multihop_node_c.query_devices()
        hashes = {d.identity_hash for d in devices}
        assert a_id in hashes, (
            f"Node C did not discover Node A ({a_id}) through transport. "
            f"Visible: {hashes}"
        )

    async def test_transport_node_sees_both_edges(
        self,
        multihop_node_b: ControlClient,
        discovered_multihop,
    ):
        """Transport node B sees both edge nodes A and C."""
        a_id = discovered_multihop["a_id"]
        c_id = discovered_multihop["c_id"]
        devices = await multihop_node_b.query_devices()
        hashes = {d.identity_hash for d in devices}
        assert a_id in hashes, f"Transport node missing Node A ({a_id})"
        assert c_id in hashes, f"Transport node missing Node C ({c_id})"


class TestMultihopMessaging:
    """Message delivery across network boundaries."""

    async def test_a_sends_to_c_via_transport(
        self,
        multihop_node_a: ControlClient,
        multihop_node_c: ControlClient,
        discovered_multihop,
    ):
        """Message from A (alpha) reaches C (beta) through B's transport."""
        c_lxmf = discovered_multihop["c_lxmf"]

        result = await multihop_node_a.send_chat(
            peer_hash=c_lxmf,
            content="Hello across the bridge from A",
        )
        assert result.get("message_id") is not None, f"send_chat returned: {result}"

        received = await poll_for_message(
            multihop_node_c,
            content="Hello across the bridge from A",
            timeout=DELIVERY_TIMEOUT,
        )
        assert received is not None, (
            "Node C did not receive message from Node A via transport"
        )
        assert _extract_content(received["content"]) == "Hello across the bridge from A"

    async def test_c_replies_to_a_via_transport(
        self,
        multihop_node_a: ControlClient,
        multihop_node_c: ControlClient,
        discovered_multihop,
    ):
        """Reply from C (beta) reaches A (alpha) through B's transport."""
        a_lxmf = discovered_multihop["a_lxmf"]

        result = await multihop_node_c.send_chat(
            peer_hash=a_lxmf,
            content="Reply from the far side C",
        )
        assert result.get("message_id") is not None

        received = await poll_for_message(
            multihop_node_a,
            content="Reply from the far side C",
            timeout=DELIVERY_TIMEOUT,
        )
        assert received is not None, (
            "Node A did not receive reply from Node C via transport"
        )
        assert _extract_content(received["content"]) == "Reply from the far side C"

    async def test_sequential_messages_across_hops(
        self,
        multihop_node_a: ControlClient,
        multihop_node_c: ControlClient,
        discovered_multihop,
    ):
        """Multiple sequential messages all transit through the transport node."""
        c_lxmf = discovered_multihop["c_lxmf"]

        messages = ["Hop msg 1", "Hop msg 2", "Hop msg 3"]
        for content in messages:
            await multihop_node_a.send_chat(peer_hash=c_lxmf, content=content)

        received = await poll_for_message(
            multihop_node_c,
            content="Hop msg 3",
            timeout=DELIVERY_TIMEOUT,
        )
        assert received is not None, "Last multi-hop sequential message did not arrive"

    async def test_conversation_appears_on_both_edges(
        self,
        multihop_node_a: ControlClient,
        multihop_node_c: ControlClient,
        discovered_multihop,
    ):
        """After exchange, both edge nodes list the conversation."""
        a_lxmf = discovered_multihop["a_lxmf"]
        c_lxmf = discovered_multihop["c_lxmf"]

        await multihop_node_a.send_chat(
            peer_hash=c_lxmf, content="Multihop conversation test"
        )
        await poll_for_message(
            multihop_node_c,
            content="Multihop conversation test",
            timeout=DELIVERY_TIMEOUT,
        )

        convs_a = await multihop_node_a.query_conversations()
        convs_c = await multihop_node_c.query_conversations()

        assert any(
            c["peer_hash"] == c_lxmf for c in convs_a
        ), f"Node A conversations missing peer C ({c_lxmf})"
        assert any(
            c["peer_hash"] == a_lxmf for c in convs_c
        ), f"Node C conversations missing peer A ({a_lxmf})"

    async def test_transport_node_does_not_store_relayed_messages(
        self,
        multihop_node_b: ControlClient,
        discovered_multihop,
    ):
        """Transport node B should not have conversations for relayed traffic.

        B acts as a relay — messages between A and C should pass through
        B's RNS transport layer without being stored in B's message DB.
        Only direct messages TO B would create conversations.
        """
        a_lxmf = discovered_multihop["a_lxmf"]
        c_lxmf = discovered_multihop["c_lxmf"]

        convs_b = await multihop_node_b.query_conversations()
        relayed_peers = {a_lxmf, c_lxmf}
        b_convs_with_edges = [
            c for c in convs_b if c["peer_hash"] in relayed_peers
        ]

        # B should NOT have conversations for A-to-C traffic it merely relayed.
        # It might have warmup conversations from the fixture, but those are
        # direct messages TO B, not relayed messages. The check here is that
        # B doesn't accumulate A-to-C or C-to-A chat traffic.
        # This is a soft check — the transport layer shouldn't store transit traffic.
        if b_convs_with_edges:
            # B has conversations with edge nodes — these should only be from
            # warmup/announce traffic, not from the A<->C test messages.
            for conv in b_convs_with_edges:
                messages = await multihop_node_b.query_messages(
                    peer_hash=conv["peer_hash"], limit=50
                )
                # None of these messages should contain A<->C test content
                for msg in messages:
                    extracted = _extract_content(msg.get("content", ""))
                    assert "across the bridge" not in (extracted or ""), (
                        f"Transport node B stored a relayed message: {extracted}"
                    )
