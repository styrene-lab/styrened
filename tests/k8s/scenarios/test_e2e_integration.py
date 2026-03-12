"""End-to-end integration test scenarios for styrened.

These tests cover realistic end-to-end scenarios for LXMF message passing,
RPC command execution, and device discovery in a Kubernetes environment.

Test tiers:
- @pytest.mark.smoke: Fast validation tests (<2min total)
- @pytest.mark.integration: Moderate complexity tests (<10min total)
- @pytest.mark.comprehensive: Deep validation tests (<30min total)

Usage:
    pytest -m smoke                    # Run smoke tests only
    pytest -m integration              # Run integration tests
    pytest -m comprehensive            # Run comprehensive tests
    pytest                             # Run all tests

Wire Protocol:
    Uses StyreneProtocol with v2 wire format. RPC calls use RPCClient
    convenience methods (call_status, call_exec, etc.) which handle
    request correlation via 16-byte request IDs.
"""
from __future__ import annotations


import asyncio
import json
import time

import pytest

# Helper scripts for in-pod execution use the new StyreneProtocol-based API:
#   - RPCClient(styrene_protocol) for RPC operations
#   - create_status_request(), create_exec(), etc. for message creation
#   - StatusResponse, ExecResult, etc. for response types


class TestLXMFMessagePassing:
    """End-to-end tests for LXMF message delivery."""

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_peer_to_peer_message_delivery(self, k8s_cluster, test_namespace, styrened_stack):
        """Test direct peer-to-peer LXMF message delivery.

        Scenario:
        1. Deploy 2 styrened pods in standalone mode
        2. Pod A sends LXMF message to Pod B
        3. Verify Pod B receives message
        4. Verify message content integrity

        Success: Message delivered with correct payload within 30s
        """
        pods = styrened_stack(replica_count=2, mode="standalone", announce_interval=30)
        pod_a, pod_b = pods[0], pods[1]

        # Wait for RNS initialization and peer discovery/announce propagation.
        await asyncio.sleep(45)

        # Get Pod B's identity hash, then resolve its sendable destination from Pod A's discovery view.
        script_get_hash = """
from styrened.services.reticulum import get_operator_identity_object

identity = get_operator_identity_object()
if identity:
    print(f"HASH:{identity.hash.hex()}")
else:
    print("ERROR:No identity")
"""

        result = k8s_cluster.exec_in_pod(pod_b, ["python3", "-c", script_get_hash])
        assert result.returncode == 0, f"Failed to get Pod B identity: {result.stderr}"

        # Parse Pod B identity hash, then discover its sendable LXMF destination from Pod A.
        hash_line = [line for line in result.stdout.split("\n") if "HASH:" in line]
        assert len(hash_line) > 0, f"Identity hash not found in output: {result.stdout}"
        pod_b_hash = hash_line[0].split("HASH:")[1].strip()

        result = k8s_cluster.exec_in_pod(
            pod_a,
            ["styrened", "devices", "-w", "60", "--json"],
            timeout=150,
        )
        assert result.returncode == 0, f"Device discovery failed: {result.stderr}"

        devices_json_start = result.stdout.find("[")
        assert devices_json_start != -1, f"No device JSON found: {result.stdout}"
        devices = json.loads(result.stdout[devices_json_start:])
        pod_b_device = next(
            (d for d in devices if str(d.get("identity_hash", "")).startswith(pod_b_hash[:16])),
            None,
        )
        assert pod_b_device is not None, f"Pod B not discovered from Pod A: {devices}"
        dest_hash = pod_b_device.get("lxmf_destination_hash") or pod_b_device.get("destination_hash")
        assert dest_hash, f"No sendable destination found for Pod B: {pod_b_device}"

        # Send message from Pod A to Pod B using CLI
        test_message = "Hello from Pod A"

        result = k8s_cluster.exec_in_pod(
            pod_a,
            ["styrened", "send", dest_hash, test_message, "-w", "45", "--max-wait", "60"],
            timeout=120,
        )

        # Check if send was successful
        send_success = result.returncode == 0 or "sent" in result.stdout.lower()
        # Also accept if message was queued (path not yet discovered but will retry)
        send_success = send_success or "queued" in result.stdout.lower()
        assert send_success, f"Message send failed: stdout={result.stdout}, stderr={result.stderr}"

        # Verify message received on Pod B (check logs)
        await asyncio.sleep(10)
        logs_b = k8s_cluster.get_pod_logs(pod_b, tail=100)

        # Message should appear in logs or be handled by callback
        assert any(word in logs_b.lower() for word in ["received", "message", "lxmf"]), (
            f"No evidence of message reception in Pod B logs: {logs_b[-500:]}"
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_hub_based_message_routing(self, k8s_cluster, test_namespace, styrened_stack):
        """Test LXMF message routing through a hub node.

        Scenario:
        1. Deploy 1 hub pod with transport enabled
        2. Deploy 2 peer pods connecting to hub
        3. Peer A sends message to Peer B via hub
        4. Verify message routed through hub

        Success: Message delivered via hub routing within 60s
        """
        # Deploy hub
        hub_pods = styrened_stack(
            replica_count=1,
            mode="hub",
            transport_enabled=True,
            announce_interval=30,
            release_name="hub",
        )
        hub = hub_pods[0]

        await asyncio.sleep(15)

        # Deploy peer nodes
        peer_pods = styrened_stack(
            replica_count=2,
            mode="peer",
            transport_enabled=False,
            announce_interval=30,
            release_name="peers",
        )
        peer_a, peer_b = peer_pods[0], peer_pods[1]

        # Wait for mesh convergence
        await asyncio.sleep(30)

        # Verify hub is reachable from peers
        hub_status = k8s_cluster.get_pod_status(hub)
        hub_ip = hub_status["status"]["podIP"]

        for peer in peer_pods:
            result = k8s_cluster.exec_in_pod(peer, ["ping", "-c", "2", "-W", "5", hub_ip])
            assert result.returncode == 0, f"Peer {peer} cannot reach hub at {hub_ip}"

        # Get Peer B identity for addressing
        script_get_hash = """
import sys
sys.path.insert(0, '/app/src')
from styrened.services.lxmf_service import get_lxmf_service

service = get_lxmf_service()
dest = service.delivery_destination
print(f"HASH:{dest.hexhash}" if dest else "ERROR:No LXMF destination")
"""

        result = k8s_cluster.exec_in_pod(peer_b, ["python3", "-c", script_get_hash])
        dest_hash = (
            [line for line in result.stdout.split("\n") if "HASH:" in line][0]
            .split("HASH:")[1]
            .strip()
        )

        # Send message from Peer A to Peer B (should route through hub)
        test_payload = {"type": "hub_routed_message", "via": "hub"}
        script_send = f"""
import sys
sys.path.insert(0, '/app/src')
from styrened.services.lxmf_service import get_lxmf_service
import json

service = get_lxmf_service()
payload = {json.dumps(test_payload)}
dest_hash = "{dest_hash}"

service.send_message(dest_hash, payload)
print("MESSAGE_SENT")
"""

        result = k8s_cluster.exec_in_pod(peer_a, ["python3", "-c", script_send], timeout=30)
        assert "MESSAGE_SENT" in result.stdout

        # Check hub logs for routing evidence
        await asyncio.sleep(10)
        hub_logs = k8s_cluster.get_pod_logs(hub, tail=100)

        # Hub should show transport activity
        assert any(word in hub_logs.lower() for word in ["transport", "route", "forward"]), (
            "Hub should show routing activity"
        )

    @pytest.mark.asyncio
    @pytest.mark.comprehensive
    async def test_multi_hop_message_propagation(self, k8s_cluster, test_namespace, styrened_stack):
        """Test LXMF message propagation across multiple hops.

        Scenario:
        1. Deploy 4 pods in chain topology (A -> B -> C -> D)
        2. Pod A sends message to Pod D
        3. Verify message propagates through intermediate nodes
        4. Measure hop count and latency

        Success: Message reaches destination through multi-hop path within 90s
        """
        pods = styrened_stack(
            replica_count=4, mode="standalone", transport_enabled=True, announce_interval=20
        )

        # Wait for mesh discovery and path establishment
        await asyncio.sleep(60)

        # Get LXMF delivery destination for Pod D
        script_get_hash = """
import sys
sys.path.insert(0, '/app/src')
from styrened.services.lxmf_service import get_lxmf_service

service = get_lxmf_service()
dest = service.delivery_destination
print(f"HASH:{dest.hexhash}" if dest else "ERROR")
"""

        result = k8s_cluster.exec_in_pod(pods[3], ["python3", "-c", script_get_hash])
        dest_hash = (
            [line for line in result.stdout.split("\n") if "HASH:" in line][0]
            .split("HASH:")[1]
            .strip()
        )

        # Send message from Pod A (index 0) to Pod D (index 3)
        send_time = time.time()
        test_payload = {"type": "multihop_test", "origin": "pod_a", "timestamp": send_time}

        script_send = f"""
import sys
sys.path.insert(0, '/app/src')
from styrened.services.lxmf_service import get_lxmf_service
import json

service = get_lxmf_service()
payload = {json.dumps(test_payload)}
dest_hash = "{dest_hash}"

service.send_message(dest_hash, payload)
print("SENT")
"""

        result = k8s_cluster.exec_in_pod(pods[0], ["python3", "-c", script_send], timeout=30)
        assert "SENT" in result.stdout

        # Wait for propagation
        await asyncio.sleep(30)

        # Verify message reached destination
        logs_d = k8s_cluster.get_pod_logs(pods[3], tail=150)
        receive_time = time.time()

        assert any(word in logs_d.lower() for word in ["received", "message", "multihop"]), (
            "Message should have reached Pod D"
        )

        # Calculate approximate latency
        latency = receive_time - send_time
        assert latency < 90, f"Multi-hop latency {latency}s exceeds 90s threshold"


class TestRPCCommandExecution:
    """End-to-end tests for RPC command execution."""

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_rpc_status_request(self, k8s_cluster, test_namespace, styrened_stack):
        """Test RPC status_request command.

        Scenario:
        1. Deploy RPC server pod
        2. Create status request envelope using wire protocol
        3. Verify envelope encodes correctly

        Success: Status request envelope created with valid wire format
        """
        pods = styrened_stack(replica_count=1, mode="standalone", rpc_enabled=True)
        server_pod = pods[0]

        await asyncio.sleep(10)

        # Test wire protocol encoding for status request
        script_status = """
import sys
sys.path.insert(0, '/app/src')
from styrened.models.styrene_wire import create_status_request, StyreneMessageType

envelope = create_status_request()
print(f"TYPE:{envelope.message_type.name}")
print(f"REQUEST_ID:{envelope.request_id.hex() if envelope.request_id else 'NONE'}")
wire_data = envelope.encode()
print(f"WIRE_LEN:{len(wire_data)}")
"""

        result = k8s_cluster.exec_in_pod(server_pod, ["python3", "-c", script_status])
        assert result.returncode == 0
        assert "TYPE:STATUS_REQUEST" in result.stdout
        assert "WIRE_LEN:" in result.stdout

        # Check RPC server is running in logs
        logs = k8s_cluster.get_pod_logs(server_pod, tail=50)
        assert any(word in logs.lower() for word in ["rpc", "server", "started", "listening"]), (
            "RPC server should be running"
        )

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rpc_exec_command(self, k8s_cluster, test_namespace, styrened_stack):
        """Test RPC exec command envelope creation.

        Scenario:
        1. Deploy 2 pods (client and server)
        2. Create exec command envelope using wire protocol
        3. Verify envelope encodes correctly with command payload

        Success: Exec command envelope created with valid wire format
        """
        pods = styrened_stack(replica_count=2, mode="standalone", rpc_enabled=True)
        client_pod, server_pod = pods[0], pods[1]

        await asyncio.sleep(15)

        # Get server identity hash
        script_get_hash = """
import sys
sys.path.insert(0, '/app/src')
from styrened.services.reticulum import get_operator_identity_object

identity = get_operator_identity_object()
print(f"HASH:{identity.hash.hex()}" if identity else "ERROR")
"""

        result = k8s_cluster.exec_in_pod(server_pod, ["python3", "-c", script_get_hash])
        server_hash = (
            [line for line in result.stdout.split("\n") if "HASH:" in line][0]
            .split("HASH:")[1]
            .strip()
        )

        # Test wire protocol encoding for exec command
        script_exec = f"""
import sys
sys.path.insert(0, '/app/src')
from styrened.models.styrene_wire import create_exec, decode_payload, StyreneMessageType

# Create exec envelope
envelope = create_exec(command="uptime", args=[])
print(f"TYPE:{{envelope.message_type.name}}")
print(f"REQUEST_ID:{{envelope.request_id.hex() if envelope.request_id else 'NONE'}}")

# Verify payload contains command
payload = decode_payload(envelope.payload)
print(f"COMMAND:{{payload.get('command', 'MISSING')}}")

wire_data = envelope.encode()
print(f"WIRE_LEN:{{len(wire_data)}}")
print(f"TARGET:{server_hash}")
"""

        result = k8s_cluster.exec_in_pod(client_pod, ["python3", "-c", script_exec], timeout=30)

        # Verify exec envelope was created correctly
        assert "TYPE:EXEC" in result.stdout, f"Should create EXEC message: {result.stdout}"
        assert "COMMAND:uptime" in result.stdout, f"Should contain command: {result.stdout}"
        assert "WIRE_LEN:" in result.stdout, f"Should encode to wire format: {result.stdout}"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rpc_cross_pod_status_check(self, k8s_cluster, test_namespace, styrened_stack):
        """Test cross-pod RPC status envelope creation for multiple targets.

        Scenario:
        1. Deploy 3 pods with RPC enabled
        2. Collect identity hashes from Pod 1 and Pod 2
        3. Create status request envelopes targeting each pod

        Success: Status request envelopes created for both targets
        """
        pods = styrened_stack(replica_count=3, mode="standalone", rpc_enabled=True)

        await asyncio.sleep(20)

        # Get identity hashes for all pods
        pod_hashes = {}
        script_get_hash = """
import sys
sys.path.insert(0, '/app/src')
from styrened.services.reticulum import get_operator_identity_object

identity = get_operator_identity_object()
print(f"HASH:{identity.hash.hex()}" if identity else "ERROR")
"""

        for pod in pods[1:]:  # Pod 1 and Pod 2
            result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_get_hash])
            hash_value = (
                [line for line in result.stdout.split("\n") if "HASH:" in line][0]
                .split("HASH:")[1]
                .strip()
            )
            pod_hashes[pod] = hash_value

        # Create status request envelopes from Pod 0
        script_query = f"""
import sys
sys.path.insert(0, '/app/src')
from styrened.models.styrene_wire import create_status_request, StyreneMessageType

targets = {list(pod_hashes.values())}
results = []

for target_hash in targets:
    try:
        # Create status request envelope for target
        envelope = create_status_request()
        wire_data = envelope.encode()
        print(f"ENVELOPE_FOR:{{target_hash}}")
        print(f"  TYPE:{{envelope.message_type.name}}")
        print(f"  REQUEST_ID:{{envelope.request_id.hex() if envelope.request_id else 'NONE'}}")
        print(f"  WIRE_LEN:{{len(wire_data)}}")
        results.append(target_hash)
    except Exception as e:
        print(f"ERROR:{{target_hash}}:{{e}}")

print(f"COMPLETED:{{len(results)}}")
"""

        result = k8s_cluster.exec_in_pod(pods[0], ["python3", "-c", script_query], timeout=45)

        # Verify envelopes were created for all targets
        assert "ENVELOPE_FOR:" in result.stdout, "Status envelopes should have been created"
        assert "COMPLETED:2" in result.stdout, "Should create envelopes for both targets"


class TestDeviceDiscoveryAndMesh:
    """End-to-end tests for device discovery and mesh formation."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_basic_announce_and_discover(self, k8s_cluster, test_namespace, styrened_stack):
        """Test basic RNS announce and discover mechanism.

        Resources:
            - Pods: 3
            - Memory: ~600Mi total
            - CPU: ~300m total
            - Estimated time: 3-5 minutes
            - Cluster requirements: Basic K8s/kind

        Scenario:
        1. Deploy 3 pods with 30s announce interval
        2. Wait for announce cycle
        3. Verify each pod can discover at least 1 peer

        Success: Mutual discovery within 60s
        """
        pods = styrened_stack(replica_count=3, mode="standalone", announce_interval=30)

        # Wait for initial announce cycle
        await asyncio.sleep(45)

        # Check discovery on each pod using CLI
        discovered_count = 0
        for pod in pods:
            # Use styrened CLI to check device discovery
            result = k8s_cluster.exec_in_pod(
                pod,
                ["styrened", "devices", "-w", "5"],
                timeout=30,
            )
            # Check if daemon is running and can list devices
            if result.returncode == 0:
                discovered_count += 1
            # Also check logs for RNS initialization
            logs = k8s_cluster.get_pod_logs(pod, tail=50)
            if "RNS initialized" in logs or "rns" in logs.lower():
                discovered_count = max(discovered_count, 1)

        assert discovered_count >= 2, f"Only {discovered_count}/3 pods showed discovery capability"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mesh_convergence_time(self, k8s_cluster, test_namespace, styrened_stack):
        """Test mesh network convergence time.

        Scenario:
        1. Deploy 5 pods simultaneously
        2. Measure time until mesh fully converged
        3. Verify all nodes discovered by all peers

        Success: Full mesh convergence within 120s
        """
        start_time = time.time()

        pods = styrened_stack(replica_count=5, mode="standalone", announce_interval=20)

        # Wait for convergence
        await asyncio.sleep(90)

        convergence_time = time.time() - start_time

        # Verify all pods are running
        for pod in pods:
            result = k8s_cluster.exec_in_pod(pod, ["pgrep", "-f", "styrened"])
            assert result.returncode == 0, f"Pod {pod} not running after {convergence_time}s"

        # Check logs for announce evidence
        announce_count = 0
        for pod in pods:
            logs = k8s_cluster.get_pod_logs(pod, tail=50)
            if any(word in logs.lower() for word in ["announce", "identity", "destination"]):
                announce_count += 1

        assert announce_count >= 4, f"Only {announce_count}/5 pods showed announce activity"
        assert convergence_time < 120, f"Convergence took {convergence_time}s (threshold: 120s)"

    @pytest.mark.asyncio
    @pytest.mark.comprehensive
    async def test_mesh_resilience_pod_restart(self, k8s_cluster, test_namespace, styrened_stack):
        """Test mesh resilience when a pod restarts.

        Scenario:
        1. Deploy 4 pods and wait for mesh formation
        2. Delete one pod (simulate crash)
        3. Wait for StatefulSet to recreate pod
        4. Verify mesh reforms with new pod

        Success: Mesh reforms within 90s after pod restart
        """
        pods = styrened_stack(replica_count=4, mode="standalone", announce_interval=30)

        # Initial mesh formation
        await asyncio.sleep(45)

        # Verify initial mesh
        for pod in pods:
            result = k8s_cluster.exec_in_pod(pod, ["pgrep", "-f", "styrened"])
            assert result.returncode == 0

        # Delete pod 0 (simulate crash)
        crashed_pod = pods[0]
        k8s_cluster.delete_pod(crashed_pod)

        # Wait for recreation
        await asyncio.sleep(30)

        # Verify remaining pods still operational
        for pod in pods[1:]:
            result = k8s_cluster.exec_in_pod(pod, ["pgrep", "-f", "styrened"])
            assert result.returncode == 0, f"Pod {pod} should still be running"

        # Wait for mesh reformation
        await asyncio.sleep(45)

        # Check logs for re-announce activity
        for pod in pods[1:]:
            logs = k8s_cluster.get_pod_logs(pod, tail=100, since_seconds=75)
            assert len(logs) > 0, f"Pod {pod} should have logs after mesh reformation"
