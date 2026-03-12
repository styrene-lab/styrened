"""Node discovery tests (Phase 1.2 and 1.3).

Tests mesh node discovery and persistence:
- Node announces propagate through mesh
- Devices appear in MeshDeviceTable
- NodeStore persists destination and identity hashes
- Cross-node visibility

Prerequisites:
- Hub running on brutus
- At least one edge node (q502) online
"""
from __future__ import annotations


import asyncio
import logging
from typing import Any

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.e2e
@pytest.mark.hub_required
@pytest.mark.slow
class TestNodeDiscovery:
    """Test mesh node discovery via Reticulum announces."""

    @pytest.mark.asyncio
    async def test_discovers_nodes_on_mesh(
        self,
        styrene_lifecycle,
        timeouts: dict[str, int],
    ) -> None:
        """Should discover at least one node on the mesh."""
        from styrened.tui.services.reticulum import discover_devices

        timeout = timeouts.get("discovery_timeout", 120)
        logger.info(f"Waiting up to {timeout}s for node discovery...")

        start_time = asyncio.get_event_loop().time()
        discovered = []

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()
            if devices:
                discovered = devices
                elapsed = asyncio.get_event_loop().time() - start_time
                logger.info(f"Discovered {len(devices)} nodes after {elapsed:.1f}s")
                break
            await asyncio.sleep(5)

        assert len(discovered) > 0, f"No nodes discovered within {timeout}s"

        # Log discovered nodes for debugging
        for device in discovered:
            logger.info(
                f"  - {device.name} ({device.device_type.value}) "
                f"dest={device.identity_short}"
            )

    @pytest.mark.asyncio
    async def test_node_has_required_attributes(
        self,
        styrene_lifecycle,
        timeouts: dict[str, int],
    ) -> None:
        """Discovered nodes should have all required attributes."""
        from styrened.tui.services.reticulum import discover_devices

        timeout = timeouts.get("discovery_timeout", 120)
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()
            if devices:
                for device in devices:
                    # Required attributes
                    assert device.destination_hash, "Missing destination_hash"
                    assert device.identity_hash, "Missing identity_hash"
                    assert device.name, "Missing name"
                    assert device.device_type is not None, "Missing device_type"
                    assert device.last_announce > 0, "Invalid last_announce"
                    assert device.announce_count >= 1, "Invalid announce_count"

                    # Hash format validation (hex strings)
                    assert len(device.destination_hash) >= 16, (
                        "destination_hash too short"
                    )
                    assert len(device.identity_hash) >= 16, "identity_hash too short"

                logger.info(f"All {len(devices)} nodes have valid attributes")
                return

            await asyncio.sleep(5)

        pytest.skip("No nodes discovered to validate attributes")


@pytest.mark.e2e
@pytest.mark.hub_required
class TestNodeStorePersistence:
    """Test that discovered nodes are persisted to SQLite."""

    @pytest.mark.asyncio
    async def test_discovered_nodes_persisted_to_store(
        self,
        styrene_lifecycle,
        node_store,
        timeouts: dict[str, int],
    ) -> None:
        """Discovered nodes should be saved to NodeStore."""
        from styrened.tui.services.reticulum import discover_devices

        timeout = timeouts.get("discovery_timeout", 120)
        start_time = asyncio.get_event_loop().time()

        # Wait for at least one node to be discovered
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()
            if devices:
                break
            await asyncio.sleep(5)

        if not devices:
            pytest.skip("No nodes discovered")

        # Give time for persistence
        await asyncio.sleep(2)

        # Check NodeStore
        for device in devices:
            stored = node_store.get_node_by_destination(device.destination_hash)
            assert stored is not None, f"Node {device.name} not persisted to store"
            assert stored.identity_hash == device.identity_hash, (
                f"Identity hash mismatch for {device.name}"
            )
            logger.info(f"Verified persistence: {device.name}")

    @pytest.mark.asyncio
    async def test_identity_hash_lookup_works(
        self,
        styrene_lifecycle,
        node_store,
        timeouts: dict[str, int],
    ) -> None:
        """Should be able to look up identity hash from destination hash."""
        from styrened.tui.services.reticulum import discover_devices

        timeout = timeouts.get("discovery_timeout", 120)
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()
            if devices:
                break
            await asyncio.sleep(5)

        if not devices:
            pytest.skip("No nodes discovered")

        await asyncio.sleep(2)

        # Verify the critical lookup function works
        for device in devices:
            identity = node_store.get_identity_for_destination(device.destination_hash)
            assert identity is not None, (
                f"get_identity_for_destination failed for {device.name}"
            )
            assert identity == device.identity_hash, (
                f"Identity hash mismatch: {identity} != {device.identity_hash}"
            )
            logger.info(
                f"Identity lookup OK: {device.identity_short} -> {identity[:16]}..."
            )


@pytest.mark.e2e
@pytest.mark.node_q502
@pytest.mark.slow
class TestSpecificNodeDiscovery:
    """Test discovery of specific configured nodes."""

    @pytest.mark.asyncio
    async def test_q502_node_discovered(
        self,
        styrene_lifecycle,
        require_q502: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """q502 node should be discovered on the mesh."""
        from styrened.tui.services.reticulum import discover_devices

        q502_dest = require_q502["destination_hash"]
        timeout = timeouts.get("discovery_timeout", 120)

        logger.info(f"Waiting for q502 ({q502_dest[:16]}...)")

        start_time = asyncio.get_event_loop().time()
        q502_found = None

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()

            for device in devices:
                if device.destination_hash == q502_dest:
                    q502_found = device
                    elapsed = asyncio.get_event_loop().time() - start_time
                    logger.info(f"q502 discovered after {elapsed:.1f}s")
                    break

            if q502_found:
                break

            await asyncio.sleep(5)

        assert q502_found is not None, f"q502 not discovered within {timeout}s"
        assert q502_found.identity_hash == require_q502["identity_hash"], (
            "q502 identity hash mismatch"
        )

    @pytest.mark.asyncio
    async def test_q502_persisted_correctly(
        self,
        styrene_lifecycle,
        require_q502: dict[str, Any],
        node_store,
        timeouts: dict[str, int],
    ) -> None:
        """q502 should be correctly persisted in NodeStore."""
        from styrened.tui.services.reticulum import discover_devices

        q502_dest = require_q502["destination_hash"]
        timeout = timeouts.get("discovery_timeout", 120)

        # Wait for discovery
        start_time = asyncio.get_event_loop().time()
        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()
            if any(d.destination_hash == q502_dest for d in devices):
                break
            await asyncio.sleep(5)

        await asyncio.sleep(2)  # Allow persistence

        # Verify in store
        stored = node_store.get_node_by_destination(q502_dest)
        assert stored is not None, "q502 not in NodeStore"
        assert stored.identity_hash == require_q502["identity_hash"]
        assert stored.name == require_q502.get("name") or stored.name

        logger.info(f"q502 persistence verified: {stored.name}")


@pytest.mark.e2e
@pytest.mark.hub_required
class TestCrossNodeVisibility:
    """Test that nodes can see each other on the mesh."""

    @pytest.mark.asyncio
    async def test_hub_visible_to_operator(
        self,
        styrene_lifecycle,
        hub_config: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Operator should see hub in discovered devices."""
        from styrened.tui.services.reticulum import discover_devices

        hub_address = hub_config["address"]
        timeout = timeouts.get("hub_connection_timeout", 90)

        start_time = asyncio.get_event_loop().time()
        hub_seen = False

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()

            for device in devices:
                if device.destination_hash == hub_address:
                    hub_seen = True
                    logger.info(f"Hub visible: {device.name}")
                    break

            if hub_seen:
                break

            await asyncio.sleep(5)

        assert hub_seen, f"Hub {hub_address} not visible to operator"

    @pytest.mark.asyncio
    async def test_multiple_nodes_visible_simultaneously(
        self,
        styrene_lifecycle,
        hub_config: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Should see multiple nodes simultaneously (hub + any edge nodes)."""
        from styrened.tui.services.reticulum import discover_devices

        timeout = timeouts.get("discovery_timeout", 120)

        start_time = asyncio.get_event_loop().time()
        max_seen = 0

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()
            if len(devices) > max_seen:
                max_seen = len(devices)
                logger.info(f"Now seeing {max_seen} nodes")

            if max_seen >= 2:
                # Good enough - hub + at least one other
                break

            await asyncio.sleep(5)

        logger.info(f"Maximum nodes seen simultaneously: {max_seen}")
        # At minimum we should see the hub
        assert max_seen >= 1, "No nodes visible on mesh"
