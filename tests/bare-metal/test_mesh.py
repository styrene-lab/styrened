"""Mesh network integration tests across bare-metal devices.

These tests require daemons running on both devices.
Run with: pytest tests/bare-metal/test_mesh.py -v
"""

from __future__ import annotations

import pytest
from harness import BareMetalHarness


@pytest.fixture(scope="class")
def running_daemons(harness: BareMetalHarness) -> None:
    """Ensure daemons are running on all devices."""
    for device in harness.registry:
        if not harness.is_daemon_running(device):
            started = harness.start_daemon(device)
            if not started:
                pytest.skip(f"Could not start daemon on {device}")
            # Wait for daemon to be responsive
            if not harness.wait_for_daemon(device, timeout=30):
                pytest.skip(f"Daemon on {device} not responsive")


@pytest.mark.mesh
@pytest.mark.usefixtures("running_daemons")
class TestMeshDiscovery:
    """Test mesh device discovery."""

    def test_styrene_node_discovers_t100ta(self, harness: BareMetalHarness) -> None:
        """styrene-node should discover t100ta."""
        devices = harness.discover_devices("styrene-node", wait=20)
        t100ta_hash = harness.registry["t100ta"].identity_hash

        found = any(
            d.get("identity_hash", "").startswith(t100ta_hash[:16])
            or d.get("destination", "").startswith(t100ta_hash[:16])
            for d in devices
        )
        assert found, f"styrene-node did not discover t100ta. Found: {devices}"

    def test_t100ta_discovers_styrene_node(self, harness: BareMetalHarness) -> None:
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

    def test_status_query_node_to_t100ta(self, harness: BareMetalHarness) -> None:
        """Query status from styrene-node to t100ta."""
        t100ta_hash = harness.registry["t100ta"].identity_hash
        status = harness.query_status("styrene-node", t100ta_hash, timeout=60)

        assert status is not None, "Status query failed"
        assert "hostname" in status
        assert status["hostname"] == "t100ta"

    def test_status_query_t100ta_to_node(self, harness: BareMetalHarness) -> None:
        """Query status from t100ta to styrene-node."""
        node_hash = harness.registry["styrene-node"].identity_hash
        status = harness.query_status("t100ta", node_hash, timeout=60)

        assert status is not None, "Status query failed"
        assert "hostname" in status
        assert status["hostname"] == "styrene-node"

    def test_exec_hostname_node_to_t100ta(self, harness: BareMetalHarness) -> None:
        """Execute hostname command from styrene-node to t100ta."""
        t100ta_hash = harness.registry["t100ta"].identity_hash
        result = harness.exec_command("styrene-node", t100ta_hash, "hostname")

        assert result is not None, "Exec command failed"
        assert result.get("exit_code") == 0
        assert result.get("stdout", "").strip() == "t100ta"

    def test_exec_hostname_t100ta_to_node(self, harness: BareMetalHarness) -> None:
        """Execute hostname command from t100ta to styrene-node."""
        node_hash = harness.registry["styrene-node"].identity_hash
        result = harness.exec_command("t100ta", node_hash, "hostname")

        assert result is not None, "Exec command failed"
        assert result.get("exit_code") == 0
        assert result.get("stdout", "").strip() == "styrene-node"

    def test_exec_uptime(self, harness: BareMetalHarness) -> None:
        """Execute uptime command remotely."""
        t100ta_hash = harness.registry["t100ta"].identity_hash
        result = harness.exec_command("styrene-node", t100ta_hash, "uptime")

        assert result is not None, "Exec command failed"
        assert result.get("exit_code") == 0
        assert "up" in result.get("stdout", "").lower()


@pytest.mark.mesh
@pytest.mark.usefixtures("running_daemons")
class TestChatMessaging:
    """Test LXMF chat messaging between devices."""

    def test_send_chat_node_to_t100ta(self, harness: BareMetalHarness) -> None:
        """Send chat message from styrene-node to t100ta."""
        t100ta_hash = harness.registry["t100ta"].identity_hash

        # Send a test message
        result = harness.run_styrened(
            "styrene-node",
            f'send {t100ta_hash} "Test message from styrene-node"',
            timeout=60,
            check=False,
        )

        # Message should be queued/sent successfully
        assert result.returncode == 0 or "queued" in result.stdout.lower()
