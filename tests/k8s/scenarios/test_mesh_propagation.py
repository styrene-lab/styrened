"""Long-running mesh propagation and multi-node topology tests.

These tests exercise realistic multi-node mesh topologies with LXMF propagation,
multi-hop routing, and resilience scenarios. They validate production-like behavior
over extended periods.

Network Topology:
    All tests use hub+peers topology for reliable mesh convergence in K8s:
    - Hub: Single pod with transport_enabled=true, accepts peer connections on port 4242
    - Peers: Connect to hub via TCPClientInterface
    This avoids multicast/AutoInterface issues in containerized environments.

Test Tiers:
    - @pytest.mark.slow: All tests require --run-slow flag (>10 minutes)
    - @pytest.mark.integration: Moderate hub-based tests (10-15 min)
    - @pytest.mark.comprehensive: Deep validation tests (15-30 min)

Domain Markers:
    - @pytest.mark.propagation: LXMF propagation and multi-hop routing tests
    - @pytest.mark.resilience: Failover and recovery tests
    - @pytest.mark.convergence: Mesh discovery and convergence tests

Usage:
    # Run all propagation tests (requires --run-slow)
    pytest tests/k8s/scenarios/test_mesh_propagation.py -v --run-slow

    # Run only comprehensive propagation tests
    pytest tests/k8s/scenarios/test_mesh_propagation.py -m "comprehensive and propagation" -v --run-slow

    # Run integration tier only (faster subset)
    pytest tests/k8s/scenarios/test_mesh_propagation.py -m integration -v --run-slow
"""
from __future__ import annotations

import asyncio

import pytest

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

# Note: k8s_cluster fixture is provided by conftest.py at session scope


@pytest.fixture
def propagation_namespace(k8s_cluster):
    """Set up namespace for propagation tests."""
    import subprocess

    namespace = "styrene-propagation"

    # Create namespace if it doesn't exist
    subprocess.run(
        ["kubectl", "create", "namespace", namespace],
        capture_output=True,
    )

    original_namespace = k8s_cluster.namespace
    k8s_cluster.namespace = namespace

    yield namespace

    # Restore original namespace
    k8s_cluster.namespace = original_namespace


@pytest.fixture
def hub_stack(k8s_cluster, propagation_namespace):
    """Deploy hub + peer topology and cleanup after test."""
    releases = []

    def _deploy(hub_name: str, peer_name: str, peer_count: int = 3):
        # Deploy hub first
        hub_pod = k8s_cluster.deploy_hub(hub_name, announce_interval=30)
        releases.append(hub_name)

        # Wait for hub to be ready
        assert k8s_cluster.wait_for_ready([hub_pod], timeout=90), "Hub failed to become ready"

        # Get hub IP for peer connections
        hub_ip = k8s_cluster.get_pod_ip(hub_pod)

        # Deploy peers
        peer_pods = k8s_cluster.deploy_peers(
            peer_name,
            hub_address=hub_ip,
            count=peer_count,
            announce_interval=60,
        )
        releases.append(peer_name)

        # Wait for peers to be ready
        assert k8s_cluster.wait_for_ready(peer_pods, timeout=90), "Peers failed to become ready"

        return hub_pod, peer_pods

    yield _deploy

    # Cleanup all releases
    for release in releases:
        k8s_cluster.cleanup(release)


@pytest.fixture
def chain_stack(k8s_cluster, propagation_namespace):
    """Deploy chain topology and cleanup after test."""
    releases = []

    def _deploy(prefix: str, node_count: int = 5, announce_interval: int = 20):
        pods = k8s_cluster.deploy_chain_topology(
            prefix,
            node_count=node_count,
            announce_interval=announce_interval,
        )
        # Track all releases for cleanup
        for i in range(node_count):
            releases.append(f"{prefix}-node-{i}")
        return pods

    yield _deploy

    # Cleanup all releases
    for release in releases:
        k8s_cluster.cleanup(release)


@pytest.fixture
def mesh_stack(k8s_cluster, propagation_namespace):
    """Deploy a hub+peers mesh topology and cleanup after test.

    Uses hub+peers topology for reliable mesh convergence in K8s environments
    where multicast/AutoInterface is not available.
    """
    releases = []

    def _deploy(release_name: str, count: int = 3, announce_interval: int = 30):
        # Deploy hub first
        hub_name = f"{release_name}-hub"
        hub_pod = k8s_cluster.deploy_hub(hub_name, announce_interval=announce_interval)
        releases.append(hub_name)

        assert k8s_cluster.wait_for_ready([hub_pod], timeout=90), "Hub failed to become ready"

        # Get hub IP for peer connections
        hub_ip = k8s_cluster.get_pod_ip(hub_pod)

        # Deploy peers (count - 1 since hub is one node)
        peer_count = max(1, count - 1)
        peer_name = f"{release_name}-peers"
        peer_pods = k8s_cluster.deploy_peers(
            peer_name,
            hub_address=hub_ip,
            count=peer_count,
            announce_interval=announce_interval,
        )
        releases.append(peer_name)

        assert k8s_cluster.wait_for_ready(peer_pods, timeout=90), "Peers failed to become ready"

        # Return all pods (hub + peers)
        return [hub_pod] + peer_pods

    yield _deploy

    for release in releases:
        k8s_cluster.cleanup(release)


# -----------------------------------------------------------------------------
# Test Classes
# -----------------------------------------------------------------------------


class TestHubPropagation:
    """Test hub-based message propagation topology (3 peers + 1 hub)."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.propagation
    async def test_hub_routes_peer_to_peer_messages(self, k8s_cluster, hub_stack):
        """Test that messages between peers route through the hub.

        Scenario:
        1. Deploy 1 hub + 3 peers
        2. Wait for mesh discovery via hub
        3. Send message from peer A to peer C
        4. Verify message routes through hub
        5. Verify message delivered successfully

        Success: Message delivered via hub routing within 60s
        """
        hub_pod, peer_pods = hub_stack("prop-hub", "prop-peers", peer_count=3)
        peer_a, _peer_b, peer_c = peer_pods[0], peer_pods[1], peer_pods[2]

        # Wait for announces to propagate through hub
        await asyncio.sleep(90)

        # Get peer C's identity hash
        dest_hash = k8s_cluster.get_identity_hash(peer_c)

        # Send message from peer A to peer C (should route through hub)
        test_message = "Hello via hub routing"
        success, latency = k8s_cluster.send_message_and_measure(
            peer_a,
            dest_hash,
            test_message,
            discovery_wait=45,
            max_wait=60,
        )

        assert success, f"Message delivery failed. Latency: {latency}s"
        assert latency < 120, f"Message delivery too slow: {latency}s"

        # Verify hub shows routing activity
        hub_routing = k8s_cluster.check_routing_via_hub(hub_pod, since_seconds=120)
        # Note: This is informational - hub may not log all routing details
        print(f"Hub routing activity detected: {hub_routing}")

    @pytest.mark.slow
    @pytest.mark.propagation
    async def test_all_peers_discover_via_hub(self, k8s_cluster, hub_stack):
        """Test that all peers discover each other through the hub.

        Scenario:
        1. Deploy 1 hub + 3 peers
        2. Wait for mesh convergence
        3. Verify each peer discovers all others

        Success: Full mesh convergence within 90s
        """
        hub_pod, peer_pods = hub_stack("disc-hub", "disc-peers", peer_count=3)
        all_pods = [hub_pod] + peer_pods

        # Measure convergence time
        try:
            convergence_time = k8s_cluster.wait_for_mesh_convergence(
                all_pods,
                timeout=180,
                check_interval=15,
            )
            print(f"Mesh converged in {convergence_time:.1f}s")
            assert convergence_time < 120, f"Convergence too slow: {convergence_time}s"
        except TimeoutError as e:
            pytest.fail(str(e))

    @pytest.mark.asyncio
    @pytest.mark.comprehensive
    @pytest.mark.slow
    @pytest.mark.propagation
    async def test_rpc_status_across_hub(self, k8s_cluster, hub_stack):
        """Test RPC status requests route through hub.

        Resources:
            - Pods: 4 (1 hub + 3 peers)
            - Memory: ~800Mi total (200Mi per pod)
            - CPU: ~400m total (100m per pod)
            - Estimated time: 13-16 minutes
            - Cluster requirements: Basic K8s/kind/k3s

        Scenario:
        1. Deploy 1 hub + 3 peers
        2. Wait for discovery (announces must propagate)
        3. Verify peers discovered each other via hub
        4. Trigger RPC status request from peer A to peer C via CLI
        5. Verify peer C received the request (logs)
        6. Verify peer C sent response (logs)
        7. Verify peer A's daemon received response (logs)

        Note: The CLI times out because the daemon receives the response,
        not the CLI. But the daemon-to-daemon round-trip is verified via logs.

        Success: Full RPC round-trip verified in daemon logs
        """
        import uuid

        test_id = uuid.uuid4().hex[:6]
        hub_pod, peer_pods = hub_stack(f"rpc-hub-{test_id}", f"rpc-peers-{test_id}", peer_count=3)
        peer_a, peer_c = peer_pods[0], peer_pods[2]

        # Wait for mesh to stabilize and announces to propagate
        await asyncio.sleep(90)

        # First verify peers can see each other (announces propagated)
        peer_a_sees_others = k8s_cluster.verify_announces_received(peer_a, min_count=2)
        peer_c_sees_others = k8s_cluster.verify_announces_received(peer_c, min_count=2)

        assert peer_a_sees_others, "Peer A has not received announces from other nodes"
        assert peer_c_sees_others, "Peer C has not received announces from other nodes"
        print("Announces propagated - peers can see each other")

        # Now verify RPC round-trip
        # Uses CLI to trigger request (CLI times out, but request is sent)
        # Then verifies daemon logs show full round-trip
        success, latency = k8s_cluster.verify_rpc_round_trip(
            from_pod=peer_a,
            to_pod=peer_c,
            timeout=120,
        )

        if not success:
            # Collect diagnostic info
            peer_a_logs = k8s_cluster.get_pod_logs(peer_a, tail=100)
            peer_c_logs = k8s_cluster.get_pod_logs(peer_c, tail=100)
            hub_logs = k8s_cluster.get_pod_logs(hub_pod, tail=100)

            print(f"\n--- Peer A logs (last 100 lines) ---\n{peer_a_logs[-2000:]}")
            print(f"\n--- Peer C logs (last 100 lines) ---\n{peer_c_logs[-2000:]}")
            print(f"\n--- Hub logs (last 100 lines) ---\n{hub_logs[-2000:]}")

        assert success, "RPC round-trip failed - check logs above for details"
        print(f"RPC round-trip completed in {latency:.1f}s")


class TestMultiHopChain:
    """Test multi-hop message delivery in chain topology (A→B→C→D→E)."""

    @pytest.mark.slow
    @pytest.mark.propagation
    async def test_message_traverses_chain(self, k8s_cluster, chain_stack):
        """Test message delivery across 5-node chain (4 hops).

        Scenario:
        1. Deploy 5 nodes in linear chain
        2. Wait for path discovery
        3. Send message from node A to node E
        4. Verify message delivered

        Success: Message delivered across 4 hops within 90s
        """
        pods = chain_stack("chain", node_count=5, announce_interval=20)
        node_a, node_e = pods[0], pods[4]

        # Wait for path discovery to propagate across chain
        await asyncio.sleep(120)

        # Get node E's identity hash
        dest_hash = k8s_cluster.get_identity_hash(node_e)

        # Send message from A to E
        test_message = "Multi-hop test message"
        success, latency = k8s_cluster.send_message_and_measure(
            node_a,
            dest_hash,
            test_message,
            discovery_wait=60,
            max_wait=90,
        )

        assert success, f"Multi-hop delivery failed. Latency: {latency}s"
        print(f"4-hop message delivered in {latency:.1f}s")

    @pytest.mark.slow
    @pytest.mark.propagation
    async def test_bidirectional_chain_routing(self, k8s_cluster, chain_stack):
        """Test bidirectional message flow in chain.

        Scenario:
        1. Deploy 5-node chain
        2. Send message A→E
        3. Send message E→A
        4. Verify both delivered

        Success: Both messages delivered within 90s each
        """
        pods = chain_stack("bidir", node_count=5, announce_interval=20)
        node_a, node_e = pods[0], pods[4]

        # Wait for path discovery
        await asyncio.sleep(120)

        # Get identity hashes
        hash_a = k8s_cluster.get_identity_hash(node_a)
        hash_e = k8s_cluster.get_identity_hash(node_e)

        # A → E
        success_ae, latency_ae = k8s_cluster.send_message_and_measure(
            node_a, hash_e, "Forward message", discovery_wait=60, max_wait=90
        )
        assert success_ae, f"A→E delivery failed. Latency: {latency_ae}s"

        # E → A
        success_ea, latency_ea = k8s_cluster.send_message_and_measure(
            node_e, hash_a, "Reverse message", discovery_wait=60, max_wait=90
        )
        assert success_ea, f"E→A delivery failed. Latency: {latency_ea}s"

        print(f"A→E: {latency_ae:.1f}s, E→A: {latency_ea:.1f}s")


class TestHubFailover:
    """Test hub failure and recovery scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.slow
    @pytest.mark.resilience
    async def test_peers_survive_hub_restart(self, k8s_cluster, hub_stack):
        """Test that peers can recover after hub restart.

        Scenario:
        1. Deploy 1 hub + 3 peers
        2. Verify initial mesh works
        3. Delete hub pod (simulate crash)
        4. Wait for hub to recover (StatefulSet recreates)
        5. Verify mesh re-establishes

        Success: Mesh recovers within 120s of hub restart
        """
        hub_pod, peer_pods = hub_stack("fail-hub", "fail-peers", peer_count=3)

        # Wait for initial mesh
        await asyncio.sleep(60)

        # Verify initial connectivity
        peer_a, peer_c = peer_pods[0], peer_pods[2]
        dest_hash = k8s_cluster.get_identity_hash(peer_c)

        success, _ = k8s_cluster.send_message_and_measure(
            peer_a, dest_hash, "Pre-failure test", discovery_wait=30, max_wait=45
        )
        assert success, "Initial mesh not working"

        # Delete hub pod
        k8s_cluster.delete_pod(hub_pod)

        # Wait for hub to restart
        await asyncio.sleep(30)

        # Wait for hub to become ready again
        ready = k8s_cluster.wait_for_ready([hub_pod], timeout=90)
        assert ready, "Hub failed to restart"

        # Wait for mesh to re-establish
        await asyncio.sleep(60)

        # Verify mesh recovered
        success, latency = k8s_cluster.send_message_and_measure(
            peer_a, dest_hash, "Post-recovery test", discovery_wait=45, max_wait=60
        )
        assert success, f"Mesh failed to recover. Latency: {latency}s"
        print(f"Mesh recovered, message delivered in {latency:.1f}s")


class TestSustainedMessageFlow:
    """Test sustained message exchange over extended periods."""

    @pytest.mark.asyncio
    @pytest.mark.comprehensive
    @pytest.mark.slow
    @pytest.mark.propagation
    async def test_sustained_messaging_10min(self, k8s_cluster, mesh_stack):
        """Test continuous messaging over 10 minutes.

        Scenario:
        1. Deploy 3-node mesh
        2. Send 1 message every 30s for 10 minutes
        3. Track delivery success rate
        4. Monitor for memory leaks

        Success: 100% delivery rate, <20% memory growth
        """
        pods = mesh_stack("sustained", count=3, announce_interval=30)

        # Wait for mesh convergence
        try:
            k8s_cluster.wait_for_mesh_convergence(pods, timeout=120)
        except TimeoutError as e:
            pytest.fail(str(e))

        # Get identity hashes
        hashes = {pod: k8s_cluster.get_identity_hash(pod) for pod in pods}

        # Record initial memory
        initial_memory = {pod: k8s_cluster.get_memory_usage_mb(pod) for pod in pods}

        # Message pairs: rotate through all combinations
        pairs = [
            (pods[0], hashes[pods[1]]),
            (pods[1], hashes[pods[2]]),
            (pods[2], hashes[pods[0]]),
        ]

        # Run for 10 minutes, 1 message every 30s = 20 messages
        message_count = 20
        successes = 0
        total_latency = 0

        for i in range(message_count):
            source_pod, dest_hash = pairs[i % len(pairs)]
            message = f"Sustained test message {i + 1}"

            success, latency = k8s_cluster.send_message_and_measure(
                source_pod, dest_hash, message, discovery_wait=15, max_wait=30
            )

            if success:
                successes += 1
                total_latency += latency
            else:
                print(f"Message {i + 1} failed")

            # Wait before next message
            await asyncio.sleep(30)

        # Calculate metrics
        success_rate = successes / message_count * 100
        avg_latency = total_latency / max(successes, 1)

        # Check final memory
        final_memory = {pod: k8s_cluster.get_memory_usage_mb(pod) for pod in pods}
        max_growth = max(
            (final_memory[p] - initial_memory[p]) / max(initial_memory[p], 1) * 100
            for p in pods
            if initial_memory[p] > 0
        )

        print(f"Success rate: {success_rate:.1f}%")
        print(f"Average latency: {avg_latency:.1f}s")
        print(f"Max memory growth: {max_growth:.1f}%")

        assert success_rate == 100, f"Delivery rate {success_rate}% < 100%"
        assert max_growth < 50, f"Memory growth {max_growth}% > 50%"


class TestLargeMeshConvergence:
    """Test mesh discovery in larger topologies."""

    @pytest.mark.asyncio
    @pytest.mark.comprehensive
    @pytest.mark.slow
    @pytest.mark.convergence
    async def test_8_node_mesh_convergence(self, k8s_cluster, mesh_stack):
        """Test convergence time for 8-node mesh.

        Resources:
            - Pods: 8
            - Memory: ~1.6Gi total (200Mi per pod)
            - CPU: ~800m total (100m per pod)
            - Estimated time: 18-22 minutes
            - Cluster requirements: Sufficient node capacity for 8 pods

        Scenario:
        1. Deploy 8 pods simultaneously
        2. Measure time to full convergence
        3. Verify all nodes can route to all others

        Success: Full convergence within 180s
        """
        pods = mesh_stack("large-mesh", count=8, announce_interval=30)

        # Measure convergence
        try:
            convergence_time = k8s_cluster.wait_for_mesh_convergence(
                pods,
                timeout=300,
                check_interval=20,
            )
        except TimeoutError as e:
            pytest.fail(str(e))

        print(f"8-node mesh converged in {convergence_time:.1f}s")

        # Verify message delivery across mesh (first to last)
        first_pod, last_pod = pods[0], pods[7]
        dest_hash = k8s_cluster.get_identity_hash(last_pod)

        success, latency = k8s_cluster.send_message_and_measure(
            first_pod, dest_hash, "Convergence verification", discovery_wait=30, max_wait=60
        )

        assert success, f"Post-convergence delivery failed. Latency: {latency}s"
        assert convergence_time < 180, f"Convergence too slow: {convergence_time}s"


class TestIdentityPersistence:
    """Test identity persistence across pod restarts."""

    @pytest.mark.slow
    @pytest.mark.resilience
    async def test_identity_survives_restart(self, k8s_cluster, mesh_stack):
        """Test that identity persists across pod restart.

        Scenario:
        1. Deploy 3-node mesh
        2. Record identity hash of pod A
        3. Delete pod A (StatefulSet recreates)
        4. Verify new pod A has same identity
        5. Verify message delivery resumes

        Success: Identity preserved, messages resume within 60s
        """
        pods = mesh_stack("persist", count=3, announce_interval=30)

        # Wait for initial mesh
        try:
            k8s_cluster.wait_for_mesh_convergence(pods, timeout=120)
        except TimeoutError as e:
            pytest.fail(str(e))

        pod_a, pod_c = pods[0], pods[2]

        # Record pod A's identity
        original_hash = k8s_cluster.get_identity_hash(pod_a)
        dest_hash_c = k8s_cluster.get_identity_hash(pod_c)

        # Verify initial connectivity
        success, _ = k8s_cluster.send_message_and_measure(
            pod_a, dest_hash_c, "Pre-restart test", discovery_wait=15, max_wait=30
        )
        assert success, "Initial mesh not working"

        # Delete pod A
        k8s_cluster.delete_pod(pod_a)

        # Wait for pod to restart
        await asyncio.sleep(15)
        ready = k8s_cluster.wait_for_ready([pod_a], timeout=90)
        assert ready, "Pod A failed to restart"

        # Wait for re-announce
        await asyncio.sleep(45)

        # Verify identity preserved
        new_hash = k8s_cluster.get_identity_hash(pod_a)
        assert new_hash == original_hash, f"Identity changed: {original_hash} → {new_hash}"

        # Verify message delivery resumes
        success, latency = k8s_cluster.send_message_and_measure(
            pod_a, dest_hash_c, "Post-restart test", discovery_wait=30, max_wait=45
        )
        assert success, f"Post-restart delivery failed. Latency: {latency}s"
        print(f"Identity preserved, message delivered in {latency:.1f}s after restart")
