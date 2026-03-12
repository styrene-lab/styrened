"""Test mesh discovery between two containerized styrened nodes.

Validates that two independent styrened containers connected via TCP
transport can discover each other through RNS announces.
"""
from __future__ import annotations


import pytest

from styrened.ipc.client import ControlClient

# All tests share the session-scoped event loop with async fixtures
pytestmark = [pytest.mark.mesh, pytest.mark.asyncio(loop_scope="session")]


class TestMeshDiscovery:
    """Basic health and identity checks for the two-node mesh."""

    async def test_both_nodes_healthy(
        self, node_a_client: ControlClient, node_b_client: ControlClient
    ):
        """Both daemons respond to ping."""
        assert await node_a_client.ping()
        assert await node_b_client.ping()

    async def test_both_nodes_have_identity(
        self, node_a_client: ControlClient, node_b_client: ControlClient
    ):
        """Both daemons have valid, distinct RNS identities."""
        id_a = await node_a_client.query_identity()
        id_b = await node_b_client.query_identity()

        assert id_a.identity_hash, "Node A missing identity hash"
        assert id_b.identity_hash, "Node B missing identity hash"
        assert id_a.identity_hash != id_b.identity_hash, "Nodes share the same identity"

    async def test_both_nodes_have_lxmf_destination(
        self, node_a_client: ControlClient, node_b_client: ControlClient
    ):
        """Both daemons have LXMF destination hashes for chat."""
        id_a = await node_a_client.query_identity()
        id_b = await node_b_client.query_identity()

        assert id_a.lxmf_destination_hash, "Node A missing LXMF destination"
        assert id_b.lxmf_destination_hash, "Node B missing LXMF destination"
        assert id_a.lxmf_destination_hash != id_b.lxmf_destination_hash

    async def test_mutual_discovery(self, discovered_mesh):
        """Both nodes discover each other via RNS announces."""
        a_id, b_id, a_lxmf, b_lxmf = discovered_mesh

        assert a_id, "Node A identity hash missing"
        assert b_id, "Node B identity hash missing"
        assert a_lxmf, "Node A LXMF destination missing"
        assert b_lxmf, "Node B LXMF destination missing"

    async def test_node_a_sees_node_b(
        self, node_a_client: ControlClient, discovered_mesh
    ):
        """Node A's device list includes Node B."""
        _, b_id, _, _ = discovered_mesh
        devices = await node_a_client.query_devices()
        hashes = {d.identity_hash for d in devices}
        assert b_id in hashes, f"Node A does not see Node B ({b_id}) in {hashes}"

    async def test_node_b_sees_node_a(
        self, node_b_client: ControlClient, discovered_mesh
    ):
        """Node B's device list includes Node A."""
        a_id, _, _, _ = discovered_mesh
        devices = await node_b_client.query_devices()
        hashes = {d.identity_hash for d in devices}
        assert a_id in hashes, f"Node B does not see Node A ({a_id}) in {hashes}"

    async def test_status_reports_uptime(
        self, node_a_client: ControlClient, node_b_client: ControlClient
    ):
        """Both daemons report non-zero uptime."""
        status_a = await node_a_client.query_status()
        status_b = await node_b_client.query_status()

        assert status_a.uptime > 0, "Node A uptime is zero"
        assert status_b.uptime > 0, "Node B uptime is zero"
