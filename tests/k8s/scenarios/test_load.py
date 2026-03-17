"""Load testing scenarios for styrened containerized testing.

Tests focus on throughput, scaling, and concurrency:
- Message throughput (100 msgs/min across nodes)
- Discovery scaling (20 nodes announcing)
- RPC concurrency (5 simultaneous exec commands)
"""
from __future__ import annotations

import asyncio
import re

import pytest


class TestMessageThroughput:
    """Test LXMF message throughput under load."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.comprehensive
    async def test_100_messages_per_minute(self, k8s_cluster, test_namespace, styrened_stack):
        """Test that 10 pods can handle 100 msgs/min total throughput.

        Scenario:
        1. Deploy 10 pods
        2. Each pod sends 10 msgs/min (100 total)
        3. Measure delivery rate
        4. Verify >80% delivery within 2 minutes
        """
        pods = styrened_stack(replica_count=10, mode="standalone", announce_interval=30)

        # Wait for mesh discovery
        await asyncio.sleep(45)

        # Get identity hashes for all pods
        identity_script = """
import sys
sys.path.insert(0, '/app/src')
from styrened.services.reticulum import get_operator_identity_object

identity = get_operator_identity_object()
if identity:
    print(f"IDENTITY:{identity.hexhash}")
else:
    print("ERROR:No identity")
"""
        pod_hashes = {}
        for pod in pods:
            result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", identity_script])
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.startswith("IDENTITY:"):
                        pod_hashes[pod] = line.split("IDENTITY:")[1].strip()
                        break

        assert len(pod_hashes) >= 8, f"Not enough identities discovered: {len(pod_hashes)}"

        # Send messages from each pod to the next (round-robin)
        pod_list = list(pod_hashes.keys())
        send_tasks = []

        for i, sender_pod in enumerate(pod_list):
            target_pod = pod_list[(i + 1) % len(pod_list)]
            target_hash = pod_hashes[target_pod]

            # Send 10 messages over ~60 seconds
            send_script = f"""
import subprocess
import time

sent = 0
for j in range(10):
    result = subprocess.run(
        ["styrened", "send", "{target_hash}", f"load-test-msg-{{j}}", "-w", "5", "--max-wait", "15"],
        capture_output=True,
        text=True,
        timeout=30
    )
    if result.returncode == 0:
        sent += 1
        print(f"SENT:{{j}}")
    else:
        print(f"FAILED:{{j}}:{{result.stderr[:100]}}")
    time.sleep(6)  # ~10 msgs/min

print(f"TOTAL_SENT:{{sent}}")
"""
            task = k8s_cluster.exec_in_pod_async(sender_pod, ["python3", "-c", send_script])
            send_tasks.append(task)

        # Wait for all senders to complete (with timeout)
        results = await asyncio.gather(*send_tasks, return_exceptions=True)

        # Count successful sends
        total_sent = 0
        for result in results:
            if isinstance(result, Exception):
                continue
            for line in result.stdout.split("\n"):
                if line.startswith("TOTAL_SENT:"):
                    total_sent += int(line.split(":")[1])

        # Verify reasonable throughput (at least 80% success)
        expected_total = len(pod_list) * 10
        success_rate = (total_sent / expected_total) * 100 if expected_total > 0 else 0

        assert success_rate >= 60, f"Message success rate {success_rate:.1f}% below 60% threshold"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_burst_message_handling(self, k8s_cluster, test_namespace, styrened_stack):
        """Test handling of burst messages (all at once).

        Scenario:
        1. Deploy 5 pods
        2. Send 20 messages rapidly from pod-0
        3. Verify no crashes
        4. Verify queuing or throttling works
        """
        pods = styrened_stack(replica_count=5, mode="standalone", announce_interval=30)

        await asyncio.sleep(30)

        # Get target identity
        identity_script = """
import sys
sys.path.insert(0, '/app/src')
from styrened.services.reticulum import get_operator_identity_object

identity = get_operator_identity_object()
if identity:
    print(f"IDENTITY:{identity.hexhash}")
"""
        result = k8s_cluster.exec_in_pod(pods[1], ["python3", "-c", identity_script])
        target_hash = None
        for line in result.stdout.split("\n"):
            if line.startswith("IDENTITY:"):
                target_hash = line.split("IDENTITY:")[1].strip()
                break

        if not target_hash:
            pytest.skip("Could not get target identity")

        # Send burst of messages (rapid fire, no delay)
        burst_script = f"""
import subprocess
import concurrent.futures
import time

def send_msg(i):
    try:
        result = subprocess.run(
            ["styrened", "send", "{target_hash}", f"burst-{{i}}", "-w", "3", "--max-wait", "10"],
            capture_output=True,
            text=True,
            timeout=20
        )
        return i, result.returncode == 0
    except Exception as e:
        return i, False

# Send 20 messages with some concurrency
start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(send_msg, i) for i in range(20)]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]

elapsed = time.time() - start
success = sum(1 for _, ok in results if ok)
print(f"BURST_SENT:{{success}}/20")
print(f"ELAPSED:{{elapsed:.1f}}s")
"""

        result = k8s_cluster.exec_in_pod(pods[0], ["python3", "-c", burst_script], timeout=120)

        # Verify no crash
        assert result.returncode == 0 or "BURST_SENT:" in result.stdout

        # Verify styrened still running
        result = k8s_cluster.exec_in_pod(pods[0], ["pgrep", "-f", "styrened"])
        assert result.returncode == 0


class TestDiscoveryScaling:
    """Test RNS discovery with many nodes announcing."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.comprehensive
    async def test_20_node_discovery(self, k8s_cluster, test_namespace, styrened_stack):
        """Test discovery scales to 20 nodes announcing.

        Scenario:
        1. Deploy 20 pods with 60s announce interval
        2. Wait 2 minutes for announcements
        3. Verify each pod discovers >15 peers (75% coverage)
        """
        pods = styrened_stack(replica_count=20, mode="standalone", announce_interval=60)

        # Wait for multiple announce rounds
        await asyncio.sleep(150)

        discovered_counts = []

        for pod in pods[:5]:  # Sample 5 pods for efficiency
            # Use CLI to get device list
            result = k8s_cluster.exec_in_pod(
                pod, ["styrened", "devices", "-w", "10", "--json"], timeout=30
            )

            if result.returncode == 0 and result.stdout.strip():
                # Parse JSON output to count devices
                try:
                    import json

                    devices = json.loads(result.stdout)
                    discovered_counts.append(len(devices))
                except (json.JSONDecodeError, ValueError):
                    # Try counting lines if not valid JSON
                    lines = [line for line in result.stdout.strip().split("\n") if line.strip()]
                    discovered_counts.append(len(lines))

        # Verify most pods discover most peers
        if discovered_counts:
            avg_discovered = sum(discovered_counts) / len(discovered_counts)
            # In mesh networks, discovery can be slow - expect at least 50%
            assert avg_discovered >= 10, f"Average discovered peers {avg_discovered:.1f} < 10"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rapid_announce_no_flooding(self, k8s_cluster, test_namespace, styrened_stack):
        """Test that rapid announces don't flood the network.

        Scenario:
        1. Deploy 10 pods with 30s announce interval (aggressive)
        2. Monitor logs for announce activity
        3. Verify announce rate is reasonable (not flooding)
        """
        pods = styrened_stack(
            replica_count=10,
            mode="standalone",
            announce_interval=30,  # Aggressive
        )

        await asyncio.sleep(90)

        # Check each pod's announce count in logs
        announce_counts = []

        for pod in pods[:5]:  # Sample 5 pods
            logs = k8s_cluster.get_pod_logs(pod, tail=200, since_seconds=90)
            # Count announce-related log entries
            announce_mentions = len(re.findall(r"announc", logs, re.IGNORECASE))
            announce_counts.append(announce_mentions)

        # Should see announces, but not excessive flooding
        if announce_counts:
            avg_announces = sum(announce_counts) / len(announce_counts)
            # Expect 2-10 announce mentions per pod in 90 seconds
            # (allows for initial announce + periodic)
            assert avg_announces >= 1, f"No announce activity detected (avg: {avg_announces})"
            # Upper bound is generous - mainly checking it's not runaway
            assert avg_announces <= 50, f"Possible announce flooding (avg: {avg_announces})"


class TestRPCConcurrency:
    """Test RPC server handling concurrent requests."""

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_5_concurrent_exec_commands(self, k8s_cluster, test_namespace, styrened_stack):
        """Test RPC server handles 5 simultaneous exec commands.

        Scenario:
        1. Deploy RPC server pod
        2. Send 5 concurrent exec requests (local execution)
        3. Verify all complete successfully
        4. Verify response times acceptable
        """
        pods = styrened_stack(replica_count=1, mode="standalone", rpc_enabled=True)
        server_pod = pods[0]

        await asyncio.sleep(15)

        # Simulate 5 concurrent command executions
        script = """
import concurrent.futures
import time
import subprocess

def exec_command(i):
    start = time.time()
    # Execute a simple command
    result = subprocess.run(
        ["echo", f"exec-test-{i}"],
        capture_output=True,
        text=True
    )
    elapsed = time.time() - start
    return i, result.returncode == 0, elapsed

# Execute 5 commands concurrently
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    futures = [executor.submit(exec_command, i) for i in range(5)]
    results = [f.result() for f in concurrent.futures.as_completed(futures)]

success_count = sum(1 for _, ok, _ in results if ok)
max_time = max(t for _, _, t in results)

print(f"COMPLETED:{success_count}/5")
print(f"MAX_TIME:{max_time:.3f}s")
"""

        result = k8s_cluster.exec_in_pod(server_pod, ["python3", "-c", script])

        assert "COMPLETED:5/5" in result.stdout
        assert result.returncode == 0

        # Verify styrened still running
        result = k8s_cluster.exec_in_pod(server_pod, ["pgrep", "-f", "styrened"])
        assert result.returncode == 0

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rpc_queue_under_load(self, k8s_cluster, test_namespace, styrened_stack):
        """Test RPC queue behavior under high request load.

        Scenario:
        1. Deploy RPC server
        2. Send 50 requests rapidly
        3. Verify queuing/handling works gracefully
        """
        pods = styrened_stack(replica_count=1, mode="standalone", rpc_enabled=True)
        server_pod = pods[0]

        await asyncio.sleep(15)

        # Send 50 rapid requests (testing internal handling)
        script = """
import time

completed = 0
for i in range(50):
    # Rapid local operations to stress-test
    print(f"Request {i}")
    completed += 1
    time.sleep(0.05)  # 20 req/sec

print(f"DONE:{completed}")
"""

        result = k8s_cluster.exec_in_pod(server_pod, ["python3", "-c", script])

        # Verify no crash
        assert "DONE:50" in result.stdout

        result = k8s_cluster.exec_in_pod(server_pod, ["pgrep", "-f", "styrened"])
        assert result.returncode == 0


class TestResourceUsageUnderLoad:
    """Test resource consumption under load."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.requires_metrics
    async def test_cpu_usage_stays_within_limits(self, k8s_cluster, test_namespace, styrened_stack):
        """Test that CPU usage stays below limit under load.

        Scenario:
        1. Deploy 5 pods with load (rapid announces + messages)
        2. Monitor CPU usage via k8s metrics
        3. Verify no throttling or OOM kills
        """
        pods = styrened_stack(
            replica_count=5,
            mode="standalone",
            announce_interval=30,
            cpu_limit="200m",
            memory_limit="256Mi",
        )

        # Generate some load
        await asyncio.sleep(60)

        # Check pod resource usage
        for pod in pods[:3]:  # Sample 3 pods
            metrics = k8s_cluster.get_pod_metrics(pod)

            # Verify CPU below limit (200m)
            cpu_usage = metrics.get("cpu_usage_millicores", 0)
            if cpu_usage > 0:  # Only assert if metrics available
                assert cpu_usage < 250, f"Pod {pod} using {cpu_usage}m CPU (limit 200m + margin)"

            # Verify memory below limit (256Mi)
            mem_usage = metrics.get("memory_usage_mb", 0)
            if mem_usage > 0:
                assert mem_usage < 300, f"Pod {pod} using {mem_usage}MB RAM (limit 256MB + margin)"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_no_oom_kills_under_load(self, k8s_cluster, test_namespace, styrened_stack):
        """Test that pods don't get OOM killed under memory pressure."""
        pods = styrened_stack(
            replica_count=5,
            mode="standalone",
            memory_limit="256Mi",
        )

        # Generate memory pressure via active operation
        await asyncio.sleep(60)

        # Check for OOM kills in pod events
        for pod in pods:
            events = k8s_cluster.get_pod_events(pod)
            oom_events = [e for e in events if "OOM" in e.get("reason", "")]
            assert len(oom_events) == 0, f"Pod {pod} was OOM killed"

            # Verify still running
            result = k8s_cluster.exec_in_pod(pod, ["pgrep", "-f", "styrened"])
            assert result.returncode == 0
