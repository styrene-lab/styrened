"""Composed test scenarios using primitives.

These scenarios combine multiple primitives to test end-to-end functionality.
Each scenario documents its prerequisites and what it validates.

Run with: pytest tests/bare-metal/test_scenarios.py -v
"""

from __future__ import annotations

from itertools import permutations

import pytest
from conftest import ALL_DEVICES, DEVICES_WITH_IDENTITY, BareMetalHarness
from primitives import (
    check_bidirectional_discovery,
    check_bidirectional_rpc,
    check_config_exists,
    # Daemon
    check_daemon_running,
    check_identity_exists,
    check_identity_matches_registry,
    check_network_reachability,
    # Connectivity
    check_ssh_connectivity,
    check_styrened_installed,
    # Installation
    check_venv_exists,
    # Discovery
    discover_devices,
    send_chat_message,
    send_rpc_exec,
    # RPC
    send_rpc_status,
    start_daemon,
    stop_daemon,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture(scope="class")
def running_daemons(harness: BareMetalHarness, all_devices: list[str]):
    """Ensure daemons are running on all devices for the test class.

    Starts daemons if not running, stops them after tests complete.
    """
    started = []
    for device in all_devices:
        if not check_daemon_running(harness, device).success:
            result = start_daemon(harness, device)
            if result.success:
                started.append(device)
            else:
                pytest.skip(f"Could not start daemon on {device}: {result.error}")

    yield

    # Cleanup: stop daemons we started
    for device in started:
        stop_daemon(harness, device)


# -----------------------------------------------------------------------------
# Scenario: Basic Connectivity
# -----------------------------------------------------------------------------


class TestConnectivityScenario:
    """Validate basic connectivity to all devices.

    Prerequisites: Devices accessible via SSH
    Validates: SSH, network reachability between devices
    """

    @pytest.mark.smoke
    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_ssh_reachable(self, harness: BareMetalHarness, device: str) -> None:
        """Each device is reachable via SSH."""
        result = check_ssh_connectivity(harness, device)
        assert result.success, result.message

    @pytest.mark.smoke
    @pytest.mark.parametrize(
        "source,target",
        list(permutations(ALL_DEVICES, 2)),
        ids=[f"{a}->{b}" for a, b in permutations(ALL_DEVICES, 2)],
    )
    def test_devices_can_reach_each_other(
        self, harness: BareMetalHarness, source: str, target: str
    ) -> None:
        """Devices can ping each other (all directional pairs)."""
        result = check_network_reachability(harness, source, target)
        assert result.success, result.message


# -----------------------------------------------------------------------------
# Scenario: Installation Validation
# -----------------------------------------------------------------------------


class TestInstallationScenario:
    """Validate styrened installation on all devices.

    Prerequisites: SSH access
    Validates: venv, styrened installation, config, identity
    """

    @pytest.mark.smoke
    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_venv_exists(self, harness: BareMetalHarness, device: str) -> None:
        """Python venv exists on device."""
        result = check_venv_exists(harness, device)
        assert result.success, result.message

    @pytest.mark.smoke
    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_styrened_installed(self, harness: BareMetalHarness, device: str) -> None:
        """styrened is installed and runnable."""
        result = check_styrened_installed(harness, device)
        assert result.success, result.message
        assert "version" in result.data

    @pytest.mark.smoke
    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_config_exists(self, harness: BareMetalHarness, device: str) -> None:
        """Styrene config file exists."""
        result = check_config_exists(harness, device)
        assert result.success, result.message

    @pytest.mark.smoke
    @pytest.mark.parametrize("device", DEVICES_WITH_IDENTITY)
    def test_identity_exists(self, harness: BareMetalHarness, device: str) -> None:
        """Device has valid identity."""
        result = check_identity_exists(harness, device)
        assert result.success, result.message

    @pytest.mark.smoke
    @pytest.mark.parametrize("device", DEVICES_WITH_IDENTITY)
    def test_identity_matches_registry(self, harness: BareMetalHarness, device: str) -> None:
        """Device identity matches what's in registry."""
        result = check_identity_matches_registry(harness, device)
        assert result.success, (
            f"{result.message}: expected={result.data.get('expected')}, actual={result.data.get('actual')}"
        )


# -----------------------------------------------------------------------------
# Scenario: Daemon Lifecycle
# -----------------------------------------------------------------------------


class TestDaemonLifecycleScenario:
    """Validate daemon start/stop/restart operations.

    Prerequisites: styrened installed
    Validates: daemon control via systemd
    """

    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_daemon_start_stop_cycle(self, harness: BareMetalHarness, device: str) -> None:
        """Daemon can be started and stopped."""
        # Ensure stopped first
        stop_daemon(harness, device)
        assert not check_daemon_running(harness, device).success

        # Start
        start_result = start_daemon(harness, device, wait_timeout=30)
        assert start_result.success, start_result.message
        assert check_daemon_running(harness, device).success

        # Stop
        stop_result = stop_daemon(harness, device)
        assert stop_result.success, stop_result.message
        assert not check_daemon_running(harness, device).success


# -----------------------------------------------------------------------------
# Scenario: Mesh Discovery
# NOTE: Currently limited to devices with identity_hash (styrene-node, t100ta).
# Expand to all device pairs when minigmk and mobilepi have identities.
# -----------------------------------------------------------------------------


@pytest.mark.mesh
@pytest.mark.usefixtures("running_daemons")
class TestMeshDiscoveryScenario:
    """Validate mesh device discovery.

    Prerequisites: Daemons running on all devices
    Validates: Devices can discover each other
    """

    def test_styrene_node_discovers_devices(self, harness: BareMetalHarness) -> None:
        """styrene-node can discover devices on the mesh."""
        result = discover_devices(harness, "styrene-node", wait=20)
        assert result.success, result.message
        assert result.data["count"] >= 1, "Should discover at least one device"

    def test_t100ta_discovers_devices(self, harness: BareMetalHarness) -> None:
        """t100ta can discover devices on the mesh."""
        result = discover_devices(harness, "t100ta", wait=20)
        assert result.success, result.message
        assert result.data["count"] >= 1, "Should discover at least one device"

    def test_bidirectional_discovery(self, harness: BareMetalHarness) -> None:
        """Both devices can discover each other."""
        result = check_bidirectional_discovery(harness, "styrene-node", "t100ta", wait=25)
        assert result.success, result.message
        assert result.data["a_sees_b"], "styrene-node should see t100ta"
        assert result.data["b_sees_a"], "t100ta should see styrene-node"


# -----------------------------------------------------------------------------
# Scenario: RPC Communication
# NOTE: Currently limited to styrene-node <-> t100ta (devices with identity_hash).
# Expand to all identity-bearing device pairs when more devices have identities.
# -----------------------------------------------------------------------------


@pytest.mark.mesh
@pytest.mark.rpc
@pytest.mark.usefixtures("running_daemons")
class TestRPCScenario:
    """Validate RPC communication between devices.

    Prerequisites: Daemons running, devices discovered
    Validates: Status queries and command execution
    """

    def test_status_query_node_to_t100ta(self, harness: BareMetalHarness) -> None:
        """Query status from styrene-node to t100ta."""
        result = send_rpc_status(harness, "styrene-node", "t100ta", timeout=60)
        assert result.success, result.message
        assert "status" in result.data
        status = result.data["status"]
        assert "hostname" in status or "uptime" in status

    def test_status_query_t100ta_to_node(self, harness: BareMetalHarness) -> None:
        """Query status from t100ta to styrene-node."""
        result = send_rpc_status(harness, "t100ta", "styrene-node", timeout=60)
        assert result.success, result.message

    def test_bidirectional_rpc(self, harness: BareMetalHarness) -> None:
        """Both devices can exchange RPC queries."""
        result = check_bidirectional_rpc(harness, "styrene-node", "t100ta", timeout=60)
        assert result.success, result.message

    def test_exec_hostname_command(self, harness: BareMetalHarness) -> None:
        """Execute hostname command via RPC."""
        result = send_rpc_exec(harness, "styrene-node", "t100ta", "hostname", timeout=60)
        assert result.success, result.message
        exec_result = result.data.get("result", {})
        assert exec_result.get("exit_code") == 0
        assert "t100ta" in exec_result.get("stdout", "")

    def test_exec_uptime_command(self, harness: BareMetalHarness) -> None:
        """Execute uptime command via RPC."""
        result = send_rpc_exec(harness, "styrene-node", "t100ta", "uptime", timeout=60)
        assert result.success, result.message
        exec_result = result.data.get("result", {})
        assert exec_result.get("exit_code") == 0
        assert "up" in exec_result.get("stdout", "").lower()


# -----------------------------------------------------------------------------
# Scenario: Chat/LXMF Messaging
# NOTE: Currently limited to styrene-node <-> t100ta (devices with identity_hash).
# Expand to all identity-bearing device pairs when more devices have identities.
# -----------------------------------------------------------------------------


@pytest.mark.mesh
@pytest.mark.usefixtures("running_daemons")
class TestChatScenario:
    """Validate LXMF chat messaging between devices.

    Prerequisites: Daemons running, devices discovered
    Validates: Chat message sending
    """

    def test_send_chat_node_to_t100ta(self, harness: BareMetalHarness) -> None:
        """Send chat message from styrene-node to t100ta."""
        result = send_chat_message(
            harness,
            "styrene-node",
            "t100ta",
            "Test message from bare-metal test suite",
            timeout=60,
        )
        assert result.success, result.message

    def test_send_chat_t100ta_to_node(self, harness: BareMetalHarness) -> None:
        """Send chat message from t100ta to styrene-node."""
        result = send_chat_message(
            harness,
            "t100ta",
            "styrene-node",
            "Reply from t100ta",
            timeout=60,
        )
        assert result.success, result.message


# -----------------------------------------------------------------------------
# Scenario: End-to-End Validation
# NOTE: Currently limited to styrene-node <-> t100ta (devices with identity_hash).
# Expand to all identity-bearing device pairs when more devices have identities.
# -----------------------------------------------------------------------------


@pytest.mark.mesh
@pytest.mark.usefixtures("running_daemons")
class TestEndToEndScenario:
    """Full end-to-end validation of mesh functionality.

    Prerequisites: Daemons running
    Validates: Complete mesh communication flow
    """

    def test_full_mesh_communication(self, harness: BareMetalHarness) -> None:
        """Complete mesh communication test.

        1. Verify discovery
        2. Send RPC status queries
        3. Execute remote commands
        4. Send chat messages
        """
        # Step 1: Discovery
        discovery = check_bidirectional_discovery(harness, "styrene-node", "t100ta")
        assert discovery.success, f"Discovery failed: {discovery.message}"

        # Step 2: RPC status
        rpc = check_bidirectional_rpc(harness, "styrene-node", "t100ta")
        assert rpc.success, f"RPC failed: {rpc.message}"

        # Step 3: Remote exec
        exec_result = send_rpc_exec(harness, "styrene-node", "t100ta", "hostname")
        assert exec_result.success, f"Exec failed: {exec_result.message}"

        # Step 4: Chat
        chat = send_chat_message(harness, "styrene-node", "t100ta", "E2E test complete")
        assert chat.success, f"Chat failed: {chat.message}"
