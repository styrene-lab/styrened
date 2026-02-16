"""Cross-platform connectivity tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.harness.primitives import check_connectivity, check_version

if TYPE_CHECKING:
    from tests.harness.base import NodeInfo, TestHarness


@pytest.mark.smoke
class TestConnectivityScenarios:
    """Basic connectivity tests that run on any backend."""

    def test_node_reachable(
        self,
        harness: TestHarness,
        single_node: NodeInfo,
    ) -> None:
        """Verify node is reachable."""
        result = check_connectivity(harness, single_node)
        assert result.success, f"{single_node.name}: {result.error}"

    def test_all_nodes_reachable(
        self,
        harness: TestHarness,
        all_nodes: list[NodeInfo],
    ) -> None:
        """Verify all nodes are reachable."""
        for node in all_nodes:
            result = check_connectivity(harness, node)
            assert result.success, f"{node.name}: {result.error}"

    def test_styrened_installed(
        self,
        harness: TestHarness,
        single_node: NodeInfo,
    ) -> None:
        """Verify styrened is installed and returns version."""
        result = check_version(harness, single_node)
        assert result.success, f"{single_node.name}: {result.error}"
        assert result.data.get("version"), "Version should not be empty"

    def test_consistent_version_across_nodes(
        self,
        harness: TestHarness,
        all_nodes: list[NodeInfo],
    ) -> None:
        """Verify all nodes have the same styrened version."""
        versions = {}
        for node in all_nodes:
            result = check_version(harness, node)
            if result.success:
                versions[node.name] = result.data.get("version")

        unique_versions = set(versions.values())
        assert len(unique_versions) == 1, f"Version mismatch across nodes: {versions}"
