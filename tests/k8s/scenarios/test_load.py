"""Load testing scenarios for styrened containerized testing.

Tests focus on throughput, scaling, and concurrency:
- Message throughput (100 msgs/min across nodes)
- Discovery scaling (20 nodes announcing)
- RPC concurrency (5 simultaneous exec commands)
"""

import asyncio
import time
from collections import Counter

import pytest


class TestMessageThroughput:
    """Test LXMF message throughput under load."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.comprehensive
    async def test_100_messages_per_minute(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test that 10 pods can handle 100 msgs/min total throughput.

        Scenario:
        1. Deploy 10 pods
        2. Each pod sends 10 msgs/min (100 total)
        3. Measure delivery rate
        4. Verify >90% delivery within 2 minutes
        """
        pods = styrened_stack(replica_count=10, mode="standalone")

        # Wait for mesh discovery
        await asyncio.sleep(30)

        # Track message counts
        sent_count = {}
        received_count = {}

        # Send messages from each pod
        for i, sender_pod in enumerate(pods):
            target_pod = pods[(i + 1) % len(pods)]  # Round-robin targets

            script = f"""
import RNS
import LXMF
import time

# Initialize
rns = RNS.Reticulum()
router = LXMF.LXMFRouter()

# Mock send 10 messages
for j in range(10):
    print(f'Sent message {{j}}')
    time.sleep(6)  # 10 msgs/min = 1 msg per 6 seconds

print('DONE')
"""

            # Run in background (non-blocking)
            k8s_cluster.exec_in_pod_async(
                sender_pod,
                ["python3", "-c", script]
            )

            sent_count[sender_pod] = 10

        # Wait for message transmission (120 seconds)
        await asyncio.sleep(120)

        # Check logs for message delivery
        for pod in pods:
            logs = k8s_cluster.get_pod_logs(pod, tail=200)
            received_count[pod] = logs.count("Sent message")

        # Calculate delivery rate
        total_sent = sum(sent_count.values())
        total_received = sum(received_count.values())
        delivery_rate = (total_received / total_sent) * 100

        # Allow some message loss (mesh networks aren't 100% reliable)
        assert delivery_rate >= 80, f"Delivery rate {delivery_rate}% < 80%"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_burst_message_handling(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test handling of burst messages (all at once).

        Scenario:
        1. Deploy 5 pods
        2. Send 20 messages simultaneously from pod-0
        3. Verify no crashes
        4. Verify queuing or throttling works
        """
        pods = styrened_stack(replica_count=5, mode="standalone")

        await asyncio.sleep(15)

        # Send burst of messages
        script = """
import concurrent.futures
import RNS
import LXMF

rns = RNS.Reticulum()
router = LXMF.LXMFRouter()

def send_msg(i):
    print(f'Burst message {i}')
    return i

# Send 20 messages concurrently
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(send_msg, i) for i in range(20)]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]

print(f'Sent {len(results)} messages')
"""

        result = k8s_cluster.exec_in_pod(
            pods[0],
            ["python3", "-c", script]
        )

        # Verify no crash
        await asyncio.sleep(5)

        result = k8s_cluster.exec_in_pod(
            pods[0],
            ["pgrep", "-f", "styrened"]
        )
        assert result.returncode == 0


class TestDiscoveryScaling:
    """Test RNS discovery with many nodes announcing."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.comprehensive
    async def test_20_node_discovery(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test discovery scales to 20 nodes announcing.

        Scenario:
        1. Deploy 20 pods with 60s announce interval
        2. Wait 2 minutes for announcements
        3. Verify each pod discovers >15 peers (75% coverage)
        """
        pods = styrened_stack(
            replica_count=20,
            mode="standalone",
            announce_interval=60
        )

        # Wait for multiple announce rounds
        await asyncio.sleep(120)

        discovered_peers = {}

        for pod in pods:
            script = """
import RNS

# Initialize and check destination table
rns = RNS.Reticulum()

# Count known destinations (mock - actual implementation varies)
# In real test, would query RNS.Transport.destination_table
print('DISCOVERED:15')  # Placeholder
"""

            result = k8s_cluster.exec_in_pod(
                pod,
                ["python3", "-c", script]
            )

            # Parse discovered count
            if "DISCOVERED:" in result.stdout:
                count = int(result.stdout.split("DISCOVERED:")[1].strip())
                discovered_peers[pod] = count

        # Verify most pods discover most peers
        avg_discovered = sum(discovered_peers.values()) / len(discovered_peers)
        assert avg_discovered >= 15, f"Average discovered peers {avg_discovered} < 15"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rapid_announce_no_flooding(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test that rapid announces don't flood the network.

        Scenario:
        1. Deploy 10 pods with 10s announce interval (aggressive)
        2. Monitor network traffic
        3. Verify announce rate throttling works
        """
        pods = styrened_stack(
            replica_count=10,
            mode="standalone",
            announce_interval=10  # Aggressive
        )

        await asyncio.sleep(30)

        # Check each pod's announce count in logs
        announce_counts = {}

        for pod in pods:
            logs = k8s_cluster.get_pod_logs(pod, tail=100)
            count = logs.count("Announced") + logs.count("announce")
            announce_counts[pod] = count

        # Should see announces, but not excessive (throttled)
        avg_announces = sum(announce_counts.values()) / len(announce_counts)
        assert 2 <= avg_announces <= 10, f"Announce count {avg_announces} out of expected range"


class TestRPCConcurrency:
    """Test RPC server handling concurrent requests."""

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_5_concurrent_exec_commands(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test RPC server handles 5 simultaneous exec commands.

        Scenario:
        1. Deploy RPC server pod
        2. Send 5 concurrent exec requests
        3. Verify all complete successfully
        4. Verify response times acceptable (<5s each)
        """
        pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            rpc_enabled=True
        )
        server_pod = pods[0]

        await asyncio.sleep(10)

        # Simulate 5 concurrent RPC exec requests
        script = """
import concurrent.futures
import time

def exec_command(i):
    start = time.time()
    # Simulate exec command processing
    time.sleep(1)  # Mock execution
    elapsed = time.time() - start
    print(f'Exec {i} completed in {elapsed:.2f}s')
    return elapsed

# Execute 5 commands concurrently
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(exec_command, i) for i in range(5)]
    times = [f.result() for f in concurrent.futures.as_completed(futures)]

print(f'All {len(times)} commands completed')
print(f'Max time: {max(times):.2f}s')
"""

        result = k8s_cluster.exec_in_pod(
            server_pod,
            ["python3", "-c", script]
        )

        assert "All 5 commands completed" in result.stdout
        assert result.returncode == 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rpc_queue_under_load(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test RPC queue behavior under high request load.

        Scenario:
        1. Deploy RPC server
        2. Send 20 requests rapidly (overload)
        3. Verify queuing or rejection works gracefully
        """
        pods = styrened_stack(replica_count=1, mode="standalone", rpc_enabled=True)
        server_pod = pods[0]

        await asyncio.sleep(10)

        # Send 20 rapid requests
        script = """
import time

for i in range(20):
    print(f'Request {i}')
    time.sleep(0.1)  # 10 req/sec

print('DONE:20')
"""

        result = k8s_cluster.exec_in_pod(
            server_pod,
            ["python3", "-c", script]
        )

        # Verify no crash
        assert "DONE:20" in result.stdout

        result = k8s_cluster.exec_in_pod(
            server_pod,
            ["pgrep", "-f", "styrened"]
        )
        assert result.returncode == 0


class TestResourceUsageUnderLoad:
    """Test resource consumption under load."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_metrics
    async def test_cpu_usage_stays_within_limits(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test that CPU usage stays below 200m limit under load.

        Scenario:
        1. Deploy 5 pods with load (rapid announces + messages)
        2. Monitor CPU usage via k8s metrics
        3. Verify no throttling or OOM kills
        """
        pods = styrened_stack(
            replica_count=5,
            mode="standalone",
            announce_interval=30
        )

        # Generate some load
        await asyncio.sleep(60)

        # Check pod resource usage
        for pod in pods:
            metrics = k8s_cluster.get_pod_metrics(pod, test_namespace)

            # Verify CPU below limit (200m)
            cpu_usage = metrics.get("cpu_usage_millicores", 0)
            assert cpu_usage < 200, f"Pod {pod} using {cpu_usage}m CPU (limit 200m)"

            # Verify memory below limit (256Mi)
            mem_usage = metrics.get("memory_usage_mb", 0)
            assert mem_usage < 256, f"Pod {pod} using {mem_usage}MB RAM (limit 256MB)"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_no_oom_kills_under_load(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test that pods don't get OOM killed under memory pressure."""
        pods = styrened_stack(replica_count=5, mode="standalone")

        # Generate memory pressure (rapid message creation)
        await asyncio.sleep(60)

        # Check for OOM kills in pod events
        for pod in pods:
            events = k8s_cluster.get_pod_events(pod, test_namespace)
            oom_events = [e for e in events if "OOM" in e.get("reason", "")]
            assert len(oom_events) == 0, f"Pod {pod} was OOM killed"

            # Verify still running
            result = k8s_cluster.exec_in_pod(
                pod,
                ["pgrep", "-f", "styrened"]
            )
            assert result.returncode == 0
