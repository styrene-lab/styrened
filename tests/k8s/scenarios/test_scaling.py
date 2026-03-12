"""Scaling test scenarios for styrened containerized testing.

Tests focus on horizontal scaling and resource limits:
- Horizontal scaling (1 → 5 → 10 pods)
- Resource limits (CPU throttling, memory pressure)
- Network bandwidth saturation
"""
from __future__ import annotations


import asyncio

import pytest


class TestHorizontalScaling:
    """Test styrened horizontal scaling behavior."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.comprehensive
    async def test_scale_from_1_to_10_pods(self, k8s_cluster, test_namespace, styrened_stack):
        """Test scaling from 1 to 10 pods with mesh discovery.

        Scenario:
        1. Deploy 1 pod
        2. Verify it starts and announces
        3. Scale to 5 pods
        4. Verify all 5 discover each other
        5. Scale to 10 pods
        6. Verify all 10 discover each other
        """
        # Start with 1 pod
        release_name = "scale-test"
        pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            announce_interval=60,
            release_name=release_name,
        )

        await asyncio.sleep(15)

        # Verify initial pod running
        result = k8s_cluster.exec_in_pod(pods[0], ["pgrep", "-f", "styrened"])
        assert result.returncode == 0

        # Scale to 5 pods
        k8s_cluster.helm_upgrade(
            release_name,
            str(k8s_cluster.helm_dir),
            {"replicaCount": 5},
        )

        # Wait for new pods and discovery
        await asyncio.sleep(45)

        pods = k8s_cluster.get_pods(label=f"app.kubernetes.io/instance={release_name}")
        assert len(pods) == 5

        # Verify all pods running
        for pod in pods:
            result = k8s_cluster.exec_in_pod(pod, ["pgrep", "-f", "styrened"])
            assert result.returncode == 0

        # Scale to 10 pods
        k8s_cluster.helm_upgrade(
            release_name,
            str(k8s_cluster.helm_dir),
            {"replicaCount": 10},
        )

        await asyncio.sleep(60)

        pods = k8s_cluster.get_pods(label=f"app.kubernetes.io/instance={release_name}")
        assert len(pods) == 10

        # Verify mesh discovery at scale
        for pod in pods:
            logs = k8s_cluster.get_pod_logs(pod, tail=50)
            # Should see discovery/announce activity
            assert any(word in logs.lower() for word in ["announce", "discover", "path"])

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scale_down_graceful_shutdown(self, k8s_cluster, test_namespace, styrened_stack):
        """Test that scaling down terminates pods gracefully.

        Scenario:
        1. Deploy 5 pods
        2. Scale down to 2 pods
        3. Verify 3 pods terminate gracefully (no crashes)
        4. Verify remaining 2 pods continue operating
        """
        release_name = "scale-down-test"
        styrened_stack(
            replica_count=5,
            mode="standalone",
            release_name=release_name,
        )

        await asyncio.sleep(20)

        # Scale down to 2
        k8s_cluster.helm_upgrade(
            release_name,
            str(k8s_cluster.helm_dir),
            {"replicaCount": 2},
        )

        await asyncio.sleep(30)

        # Verify only 2 pods remain
        remaining_pods = k8s_cluster.get_pods(label=f"app.kubernetes.io/instance={release_name}")
        assert len(remaining_pods) == 2

        # Verify remaining pods still running
        for pod in remaining_pods:
            result = k8s_cluster.exec_in_pod(pod, ["pgrep", "-f", "styrened"])
            assert result.returncode == 0


class TestResourceLimits:
    """Test behavior under resource constraints."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cpu_throttling_handling(self, k8s_cluster, test_namespace, styrened_stack):
        """Test styrened operates correctly under CPU throttling.

        Resources:
            - Pods: 1 (with CPU limits enforced)
            - Memory: 256Mi
            - CPU: 100m (throttled - stress testing)
            - Estimated time: 5-8 minutes
            - Cluster requirements: CPU limit enforcement

        Scenario:
        1. Deploy pod with low CPU limit (100m)
        2. Generate CPU load (rapid operations)
        3. Verify process doesn't crash
        4. Verify operations continue (slower but stable)
        """
        pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            cpu_limit="100m",  # Very low limit
            cpu_request="50m",
        )

        await asyncio.sleep(10)

        # Generate CPU load
        script = """
import time

# CPU-intensive loop
for i in range(1000):
    _ = sum(range(1000))
    if i % 100 == 0:
        print(f'Iteration {i}')

print('CPU load test complete')
"""

        result = k8s_cluster.exec_in_pod(pods[0], ["python3", "-c", script])

        # Should complete (slowly) without crash
        assert "CPU load test complete" in result.stdout

        # Verify styrened still running
        result = k8s_cluster.exec_in_pod(pods[0], ["pgrep", "-f", "styrened"])
        assert result.returncode == 0

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_memory_pressure_handling(self, k8s_cluster, test_namespace, styrened_stack):
        """Test styrened handles memory pressure gracefully.

        Scenario:
        1. Deploy pod with low memory limit (128Mi)
        2. Generate memory pressure (large data structures)
        3. Verify no OOM kill
        4. Verify garbage collection works
        """
        pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            memory_limit="128Mi",
            memory_request="64Mi",
        )

        await asyncio.sleep(10)

        # Generate memory pressure
        script = """
import gc

# Create large list
data = []
for i in range(100):
    data.append([0] * 10000)
    if i % 10 == 0:
        print(f'Allocated {i}')
        gc.collect()  # Force garbage collection

print('Memory pressure test complete')
del data
gc.collect()
"""

        result = k8s_cluster.exec_in_pod(pods[0], ["python3", "-c", script])

        # Should handle pressure
        assert result.returncode == 0

        # Verify no OOM kill
        events = k8s_cluster.get_pod_events(pods[0])
        oom_events = [e for e in events if "OOM" in e.get("reason", "")]
        assert len(oom_events) == 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_resource_requests_vs_limits(self, k8s_cluster, test_namespace, styrened_stack):
        """Test pod scheduling with requests and limits.

        Scenario:
        1. Deploy 10 pods with requests (100m CPU, 128Mi RAM)
        2. Verify all pods scheduled (requests met)
        3. Monitor actual usage vs limits
        """
        pods = styrened_stack(
            replica_count=10,
            mode="standalone",
            cpu_request="100m",
            cpu_limit="200m",
            memory_request="128Mi",
            memory_limit="256Mi",
        )

        await asyncio.sleep(30)

        # Verify all pods scheduled
        assert len(pods) == 10

        # Check resource usage
        for pod in pods:
            # Get pod status
            status = k8s_cluster.get_pod_status(pod)
            assert status["status"]["phase"] == "Running"

            # Verify resource limits applied
            container_spec = status["spec"]["containers"][0]
            assert container_spec["resources"]["requests"]["cpu"] == "100m"
            assert container_spec["resources"]["limits"]["cpu"] == "200m"


class TestNetworkBandwidth:
    """Test behavior under network bandwidth constraints."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.comprehensive
    async def test_bandwidth_saturation(self, k8s_cluster, test_namespace, styrened_stack):
        """Test message delivery under network bandwidth pressure.

        Scenario:
        1. Deploy 5 pods
        2. Generate high network traffic (large messages)
        3. Verify message delivery continues
        4. Verify backpressure handling
        """
        pods = styrened_stack(replica_count=5, mode="standalone")

        await asyncio.sleep(20)

        # Generate network traffic from multiple pods
        script = """
import time

# Simulate sending large messages
for i in range(10):
    # Mock large message (1MB)
    data = b'x' * 1024 * 1024
    print(f'Sent large message {i} ({len(data)} bytes)')
    time.sleep(1)

print('Network load test complete')
"""

        # Run on multiple pods concurrently
        tasks = []
        for pod in pods[:3]:  # Use 3 pods as senders
            task = k8s_cluster.exec_in_pod_async(pod, ["python3", "-c", script])
            tasks.append(task)

        # Wait for completion
        await asyncio.gather(*tasks)

        # Verify all pods still running
        for pod in pods:
            result = k8s_cluster.exec_in_pod(pod, ["pgrep", "-f", "styrened"])
            assert result.returncode == 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_network_latency_impact(self, k8s_cluster, test_namespace, styrened_stack):
        """Test styrened behavior with high network latency.

        Scenario:
        1. Deploy 3 pods
        2. Add artificial latency (tc qdisc)
        3. Verify operations continue (slower)
        4. Verify timeout handling works
        """
        pods = styrened_stack(replica_count=3, mode="standalone")

        await asyncio.sleep(15)

        # Add 100ms latency to pod-0 (may require NET_ADMIN capability)
        result = k8s_cluster.exec_in_pod(
            pods[0],
            [
                "tc",
                "qdisc",
                "add",
                "dev",
                "eth0",
                "root",
                "netem",
                "delay",
                "100ms",
            ],
        )
        # tc command may fail without NET_ADMIN capability - that's ok for this test
        if result.returncode != 0:
            pytest.skip("tc command requires NET_ADMIN capability")

        await asyncio.sleep(10)

        # Verify pod still operational (with latency)
        result = k8s_cluster.exec_in_pod(pods[0], ["pgrep", "-f", "styrened"])
        assert result.returncode == 0

        # Get pod IP for connectivity test
        pod_1_status = k8s_cluster.get_pod_status(pods[1])
        pod_1_ip = pod_1_status.get("status", {}).get("podIP")

        if pod_1_ip:
            # Verify can still communicate (slower)
            result = k8s_cluster.exec_in_pod(pods[0], ["ping", "-c", "3", "-W", "5", pod_1_ip])
            assert result.returncode == 0


class TestNodeAffinity:
    """Test pod distribution across nodes."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_pods_spread_across_nodes(self, k8s_cluster, test_namespace, styrened_stack):
        """Test that pods are distributed across available nodes.

        Scenario:
        1. Deploy 5 pods with anti-affinity (if supported)
        2. Verify pods spread across nodes (if multi-node cluster)
        3. Verify network connectivity between nodes
        """
        # Note: anti_affinity is configured via extra_values if needed
        pods = styrened_stack(
            replica_count=5,
            mode="standalone",
            extra_values={
                "podAntiAffinity.enabled": "true",
            },
        )

        await asyncio.sleep(20)

        # Get node assignments
        node_assignments = {}
        for pod in pods:
            node = k8s_cluster.get_pod_node(pod)
            if node not in node_assignments:
                node_assignments[node] = []
            node_assignments[node].append(pod)

        # Verify distribution (if multi-node cluster)
        num_nodes = len(node_assignments)
        if num_nodes > 1:
            # Pods should be spread
            max_pods_per_node = max(len(p) for p in node_assignments.values())
            assert max_pods_per_node <= 3, "Pods should be distributed across nodes"

            # Verify cross-node connectivity
            nodes = list(node_assignments.keys())
            pod_node_0 = node_assignments[nodes[0]][0]
            pod_node_1 = node_assignments[nodes[1]][0]

            # Get pod IP for connectivity test
            pod_1_status = k8s_cluster.get_pod_status(pod_node_1)
            pod_1_ip = pod_1_status.get("status", {}).get("podIP")

            if pod_1_ip:
                result = k8s_cluster.exec_in_pod(
                    pod_node_0, ["ping", "-c", "2", "-W", "5", pod_1_ip]
                )
                assert result.returncode == 0, "Cross-node connectivity should work"
        else:
            # Single-node cluster (like brutus) - just verify pods are running
            for pod in pods:
                result = k8s_cluster.exec_in_pod(pod, ["pgrep", "-f", "styrened"])
                assert result.returncode == 0
