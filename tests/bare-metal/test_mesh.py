"""Mesh network integration tests across bare-metal devices.

These tests require daemons running on both devices.
Run with: pytest tests/bare-metal/test_mesh.py -v
"""

from __future__ import annotations

import json

import pytest
from tests.harness.ssh import SSHHarness


@pytest.fixture(scope="class")
def running_daemons(harness: SSHHarness) -> None:
    """Ensure daemons are running on all devices."""
    for name in harness.registry:
        if not harness.is_daemon_running(name):
            result = harness.start_daemon(name)
            if not result.success:
                pytest.skip(f"Could not start daemon on {name}")
            if not harness.wait_for_daemon(name, timeout=30):
                pytest.skip(f"Daemon on {name} not responsive")


@pytest.mark.mesh
@pytest.mark.usefixtures("running_daemons")
class TestMeshDiscovery:
    """Test mesh device discovery."""

    def test_styrene_node_discovers_t100ta(self, harness: SSHHarness) -> None:
        """styrene-node should discover t100ta."""
        devices = harness.discover_devices("styrene-node", wait=20)
        t100ta_hash = harness.registry["t100ta"].identity_hash

        found = any(
            d.get("identity_hash", "").startswith(t100ta_hash[:16])
            or d.get("destination", "").startswith(t100ta_hash[:16])
            for d in devices
        )
        assert found, f"styrene-node did not discover t100ta. Found: {devices}"

    def test_t100ta_discovers_styrene_node(self, harness: SSHHarness) -> None:
        """t100ta should discover styrene-node."""
        devices = harness.discover_devices("t100ta", wait=20)
        node_hash = harness.registry["styrene-node"].identity_hash

        found = any(
            d.get("identity_hash", "").startswith(node_hash[:16])
            or d.get("destination", "").startswith(node_hash[:16])
            for d in devices
        )
        assert found, f"t100ta did not discover styrene-node. Found: {devices}"


@pytest.mark.mesh
@pytest.mark.rpc
@pytest.mark.usefixtures("running_daemons")
class TestRPCCommunication:
    """Test RPC communication between devices."""

    def test_status_query_node_to_t100ta(self, harness: SSHHarness) -> None:
        """Query status from styrene-node to t100ta."""
        t100ta_hash = harness.registry["t100ta"].identity_hash
        result = harness.query_status("styrene-node", t100ta_hash, timeout=60)
        assert result.success, f"Status query failed: {result.stderr}"

    def test_status_query_t100ta_to_node(self, harness: SSHHarness) -> None:
        """Query status from t100ta to styrene-node."""
        node_hash = harness.registry["styrene-node"].identity_hash
        result = harness.query_status("t100ta", node_hash, timeout=60)
        assert result.success, f"Status query failed: {result.stderr}"

    def test_exec_hostname_node_to_t100ta(self, harness: SSHHarness) -> None:
        """Execute hostname command from styrene-node to t100ta."""
        t100ta_hash = harness.registry["t100ta"].identity_hash
        result = harness.exec_remote("styrene-node", t100ta_hash, "hostname")
        assert result.success, f"Exec command failed: {result.stderr}"
        assert "t100ta" in result.stdout.strip()

    def test_exec_hostname_t100ta_to_node(self, harness: SSHHarness) -> None:
        """Execute hostname command from t100ta to styrene-node."""
        node_hash = harness.registry["styrene-node"].identity_hash
        result = harness.exec_remote("t100ta", node_hash, "hostname")
        assert result.success, f"Exec command failed: {result.stderr}"
        assert "styrene-node" in result.stdout.strip()

    def test_exec_uptime(self, harness: SSHHarness) -> None:
        """Execute uptime command remotely."""
        t100ta_hash = harness.registry["t100ta"].identity_hash
        result = harness.exec_remote("styrene-node", t100ta_hash, "uptime")
        assert result.success, f"Exec command failed: {result.stderr}"
        assert "up" in result.stdout.lower()


@pytest.mark.mesh
@pytest.mark.usefixtures("running_daemons")
class TestChatMessaging:
    """Test LXMF chat messaging between devices."""

    def test_send_chat_node_to_t100ta(self, harness: SSHHarness) -> None:
        """Send chat message from styrene-node to t100ta."""
        t100ta_hash = harness.registry["t100ta"].identity_hash

        result = harness.run_styrened(
            "styrene-node",
            f'send {t100ta_hash} "Test message from styrene-node"',
            timeout=60,
        )

        # Message should be queued/sent successfully
        assert result.return_code == 0 or "queued" in result.stdout.lower(), (
            f"Send failed: rc={result.return_code} stdout={result.stdout} stderr={result.stderr}"
        )
