"""Daemon resilience and recovery tests.

Tests daemon restart behavior, state persistence, and recovery from failures.
"""

from __future__ import annotations

import time

import pytest
from tests.harness.ssh import SSHHarness


@pytest.mark.mesh
class TestDaemonResilience:
    """Test daemon restart and state recovery."""

    def test_restart_preserves_node_store(self, harness: SSHHarness) -> None:
        """NodeStore persists discovered devices across restarts.

        1. Start daemon, wait for discovery
        2. Record discovered devices
        3. Restart daemon
        4. Verify previously discovered devices are still known
        """
        # Pick a device with identity
        devices = [d for d in harness.registry if harness.registry[d].identity_hash]
        if len(devices) < 2:
            pytest.skip("Need at least 2 devices with identity")

        test_device = devices[0]
        peer_device = devices[1]

        # Ensure both daemons running
        for d in [test_device, peer_device]:
            if not harness.is_daemon_running(d):
                result = harness.start_daemon(d)
                assert result.success, f"Failed to start {d}"
                assert harness.wait_for_daemon(d, timeout=30), f"{d} not responsive"

        # Wait for discovery
        peer_hash = harness.registry[peer_device].identity_hash
        discovered_before = harness.discover_devices(test_device, wait_seconds=20)
        found_before = any(
            d.get("identity_hash", d.get("destination", "")).startswith(peer_hash[:16])
            for d in discovered_before
        )
        assert found_before, f"{test_device} did not discover {peer_device} before restart"

        # Restart the test device daemon
        result = harness.restart_daemon(test_device)
        assert result.success, f"Restart failed: {result.stderr}"
        assert harness.wait_for_daemon(test_device, timeout=30), "Not responsive after restart"

        # Check that devices are still discoverable (from NodeStore)
        # Use shorter wait since NodeStore should have cached entries
        discovered_after = harness.discover_devices(test_device, wait_seconds=5)
        found_after = any(
            d.get("identity_hash", d.get("destination", "")).startswith(peer_hash[:16])
            for d in discovered_after
        )
        assert found_after, (
            f"{test_device} lost {peer_device} after restart. "
            f"Before: {len(discovered_before)} devices, After: {len(discovered_after)} devices"
        )

    def test_rapid_restart_stability(self, harness: SSHHarness) -> None:
        """Daemon handles rapid restart cycles without degradation.

        Restarts daemon 3 times in quick succession, verifying it
        becomes responsive each time.
        """
        devices = [d for d in harness.registry if harness.registry[d].identity_hash]
        if not devices:
            pytest.skip("No devices with identity")

        test_device = devices[0]
        restart_times: list[float] = []

        # Ensure running first
        if not harness.is_daemon_running(test_device):
            harness.start_daemon(test_device)
            harness.wait_for_daemon(test_device, timeout=30)

        for i in range(3):
            start = time.time()
            result = harness.restart_daemon(test_device)
            assert result.success, f"Restart {i+1} failed: {result.stderr}"

            responsive = harness.wait_for_daemon(test_device, timeout=30)
            restart_time = time.time() - start
            restart_times.append(restart_time)

            assert responsive, f"Not responsive after restart {i+1} ({restart_time:.1f}s)"

        # Restart times should not degrade significantly
        # Allow 50% variance from first restart
        baseline = restart_times[0]
        for i, t in enumerate(restart_times[1:], 2):
            assert t < baseline * 2.0, (
                f"Restart {i} took {t:.1f}s vs baseline {baseline:.1f}s "
                f"(>{2.0}x degradation)"
            )

    def test_identity_stable_across_restarts(self, harness: SSHHarness) -> None:
        """Identity hash remains stable through restart cycles."""
        devices = [d for d in harness.registry if harness.registry[d].identity_hash]
        if not devices:
            pytest.skip("No devices with identity")

        test_device = devices[0]
        expected_hash = harness.registry[test_device].identity_hash

        # Ensure running
        if not harness.is_daemon_running(test_device):
            harness.start_daemon(test_device)
            harness.wait_for_daemon(test_device, timeout=30)

        # Check identity, restart, check again
        identity_before = harness.get_identity(test_device)
        assert identity_before is not None
        assert identity_before["identity_hash"] == expected_hash

        harness.restart_daemon(test_device)
        harness.wait_for_daemon(test_device, timeout=30)

        identity_after = harness.get_identity(test_device)
        assert identity_after is not None
        assert identity_after["identity_hash"] == expected_hash, (
            f"Identity changed after restart: {identity_before['identity_hash']} -> {identity_after['identity_hash']}"
        )
