"""Cross-platform mesh discovery tests."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from tests.harness.primitives import (
    check_bidirectional_discovery,
    discover_peers,
    ensure_daemon_running,
    restart_daemon,
)

if TYPE_CHECKING:
    from tests.harness.base import NodeInfo, TestHarness


@pytest.mark.smoke
class TestDiscoveryScenarios:
    """Discovery tests that run on any backend."""

    def test_daemon_running(
        self,
        harness: TestHarness,
        single_node: NodeInfo,
    ) -> None:
        """Verify daemon is running on test node."""
        result = ensure_daemon_running(harness, single_node, start_if_stopped=True)
        assert result.success, f"{single_node.name}: {result.error}"

    def test_node_discovers_peers(
        self,
        harness: TestHarness,
        test_nodes: list[NodeInfo],
    ) -> None:
        """Each node can discover at least one peer."""
        # Ensure daemons are running
        for node in test_nodes:
            ensure_daemon_running(harness, node)

        # Give mesh time to announce
        time.sleep(5)

        for node in test_nodes:
            result = discover_peers(
                harness,
                node,
                wait_seconds=15,
                min_expected=1,
            )
            assert result.success, f"{node.name}: {result.error}"

    def test_bidirectional_discovery(
        self,
        harness: TestHarness,
        test_nodes: list[NodeInfo],
    ) -> None:
        """Two nodes can discover each other."""
        # Ensure daemons are running
        for node in test_nodes:
            ensure_daemon_running(harness, node)

        node_a, node_b = test_nodes

        result = check_bidirectional_discovery(
            harness,
            node_a,
            node_b,
            wait_seconds=20,
        )
        assert result.success, result.error


@pytest.mark.integration
class TestDiscoveryIntegration:
    """More complex discovery scenarios."""

    def test_discovery_after_restart(
        self,
        harness: TestHarness,
        test_nodes: list[NodeInfo],
    ) -> None:
        """Nodes rediscover each other after daemon restart.

        Note: In K8s, pod restart creates a new container with new identity
        and cleared logs. The log-based discovery cannot work after restart
        because logs are cleared. This test is skipped for K8s.
        """
        from tests.harness.base import ExecutionBackend

        # K8s pod restart clears logs, making log-based discovery impossible
        # This test validates daemon restart behavior which is fundamentally
        # different between SSH (process restart) and K8s (container recreation)
        if harness.backend == ExecutionBackend.K8S:
            pytest.skip("K8s pod restart clears logs; restart behavior tested separately")

        node_a, node_b = test_nodes

        # Ensure both daemons running
        ensure_daemon_running(harness, node_a)
        ensure_daemon_running(harness, node_b)

        # Initial discovery
        result = check_bidirectional_discovery(harness, node_a, node_b, wait_seconds=20)
        assert result.success, f"Initial discovery failed: {result.error}"

        # Restart node_a daemon
        restart_result = restart_daemon(harness, node_a, wait_timeout=30)
        assert restart_result.success, f"Restart failed: {restart_result.error}"

        # Wait for reconnection
        time.sleep(10)

        # Verify rediscovery
        result = check_bidirectional_discovery(harness, node_a, node_b, wait_seconds=20)
        assert result.success, f"Rediscovery failed: {result.error}"

    def test_all_nodes_visible(
        self,
        harness: TestHarness,
        all_nodes: list[NodeInfo],
    ) -> None:
        """Each node can discover all other nodes."""
        if len(all_nodes) < 2:
            pytest.skip("Need at least 2 nodes")

        # Ensure all daemons running
        for node in all_nodes:
            ensure_daemon_running(harness, node)

        # Wait for mesh to stabilize
        time.sleep(10)

        expected_count = len(all_nodes) - 1

        for node in all_nodes:
            result = discover_peers(
                harness,
                node,
                wait_seconds=30,
                min_expected=expected_count,
            )
            # Log what we found even on failure
            if not result.success:
                print(
                    f"{node.name} found {result.data.get('count', 0)}/{expected_count}: "
                    f"{result.data.get('devices', [])}"
                )
            assert result.success, f"{node.name}: {result.error}"
