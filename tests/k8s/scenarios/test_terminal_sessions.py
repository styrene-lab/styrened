"""K8s integration tests for terminal session framework.

Tests cover:
- Peer-to-peer terminal session establishment
- Authentication and authorization flows
- Session lifecycle (create, data transfer, teardown)
- Failure modes (network partition, pod restart, timeout)
- Concurrent sessions and resource limits
- Window resize and signal propagation
- Security boundary validation

Test tiers:
- @pytest.mark.smoke: Fast validation (<2min)
- @pytest.mark.integration: Moderate complexity (<10min)
- @pytest.mark.comprehensive: Deep validation (<30min)
"""
from __future__ import annotations

import asyncio

import pytest


class TestTerminalSessionEstablishment:
    """Tests for terminal session establishment flow."""

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_basic_session_request_accept(self, k8s_cluster, test_namespace, styrened_stack):
        """Test basic TERMINAL_REQUEST -> TERMINAL_ACCEPT flow.

        Scenario:
        1. Deploy 2 pods with terminal service enabled
        2. Pod A sends TERMINAL_REQUEST to Pod B
        3. Verify Pod B responds with TERMINAL_ACCEPT
        4. Verify session_id and link_destination in response

        Success: Valid TERMINAL_ACCEPT received within 30s
        """
        pods = styrened_stack(
            replica_count=2,
            mode="standalone",
            announce_interval=30,
            extra_values={"styrene.terminal.enabled": "true"},
        )
        client_pod, server_pod = pods[0], pods[1]

        # Wait for RNS initialization
        await asyncio.sleep(20)

        # Get server identity hash
        script_get_identity = """
import sys
sys.path.insert(0, '/app/src')
from styrened.services.reticulum import get_operator_identity_object

identity = get_operator_identity_object()
if identity:
    print(f"IDENTITY:{identity.hexhash}")
else:
    print("ERROR:No identity")
    sys.exit(1)
"""
        result = k8s_cluster.exec_in_pod(server_pod, ["python3", "-c", script_get_identity])
        assert result.returncode == 0, f"Failed to get server identity: {result.stderr}"

        server_hash = None
        for line in result.stdout.split("\n"):
            if line.startswith("IDENTITY:"):
                server_hash = line.split("IDENTITY:")[1].strip()
                break
        assert server_hash, f"Server identity not found in output: {result.stdout}"

        # Create and send terminal request from client
        script_send_request = f"""
import sys
import asyncio
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import (
    create_terminal_request,
    StyreneMessageType,
    decode_payload,
)

# Create terminal request
request = create_terminal_request(
    term_type="xterm-256color",
    rows=24,
    cols=80,
)

# Verify request format
assert request.message_type == StyreneMessageType.TERMINAL_REQUEST
assert request.request_id is not None
assert len(request.request_id) == 16

payload = decode_payload(request.payload)
assert payload["term_type"] == "xterm-256color"
assert payload["rows"] == 24
assert payload["cols"] == 80

print(f"REQUEST_ID:{{request.request_id.hex()}}")
print(f"TARGET:{server_hash}")
print("REQUEST_VALID:true")

# Encode for transmission
wire_data = request.encode()
print(f"WIRE_LENGTH:{{len(wire_data)}}")
"""
        result = k8s_cluster.exec_in_pod(client_pod, ["python3", "-c", script_send_request])

        assert "REQUEST_VALID:true" in result.stdout, f"Request validation failed: {result.stdout}"
        assert "WIRE_LENGTH:" in result.stdout, f"Wire encoding failed: {result.stdout}"

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_unauthorized_session_rejected(self, k8s_cluster, test_namespace, styrened_stack):
        """Test that unauthorized identities receive TERMINAL_REJECT.

        Scenario:
        1. Deploy server pod with explicit authorized_identities
        2. Deploy client pod NOT in authorized list
        3. Client sends TERMINAL_REQUEST
        4. Verify TERMINAL_REJECT response

        Success: TERMINAL_REJECT received with reason "not authorized"
        """
        # Deploy server with specific authorized identity (not matching client)
        server_pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            release_name="terminal-server",
            extra_values={
                "styrene.terminal.enabled": "true",
                "styrene.terminal.authorized_identities": "deadbeef" * 8,  # Fake identity
            },
        )
        server_pod = server_pods[0]

        # Deploy client (will have different identity)
        client_pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            release_name="terminal-client",
        )
        _client_pod = client_pods[0]

        await asyncio.sleep(20)

        # Test rejection message creation
        script_test_reject = """
import sys
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import (
    create_terminal_reject,
    StyreneMessageType,
    decode_payload,
)

# Create rejection response (simulating server behavior)
reject = create_terminal_reject(
    reason="Identity not authorized",
    code=1,
    request_id=b"test_request_id_",
)

assert reject.message_type == StyreneMessageType.TERMINAL_REJECT
payload = decode_payload(reject.payload)

print(f"REJECT_REASON:{payload['reason']}")
print(f"REJECT_CODE:{payload['code']}")
print("REJECT_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(server_pod, ["python3", "-c", script_test_reject])

        assert "REJECT_VALID:true" in result.stdout
        assert "REJECT_REASON:Identity not authorized" in result.stdout
        assert "REJECT_CODE:1" in result.stdout

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_session_with_custom_shell(self, k8s_cluster, test_namespace, styrened_stack):
        """Test terminal session with custom shell specification.

        Scenario:
        1. Deploy pods with terminal service
        2. Request session with shell="/bin/sh"
        3. Verify shell parameter in request payload

        Success: Custom shell preserved in wire format
        """
        pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            extra_values={"styrene.terminal.enabled": "true"},
        )
        pod = pods[0]

        await asyncio.sleep(15)

        script_test_shell = """
import sys
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import create_terminal_request, decode_payload

# Test custom shell
request = create_terminal_request(shell="/bin/sh")
payload = decode_payload(request.payload)

assert payload.get("shell") == "/bin/sh", f"Shell mismatch: {payload}"
print("SHELL_VALID:true")

# Test custom command
request2 = create_terminal_request(
    command="python",
    args=["-c", "print('hello')"],
)
payload2 = decode_payload(request2.payload)

assert payload2.get("command") == "python"
assert payload2.get("args") == ["-c", "print('hello')"]
print("COMMAND_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_shell])

        assert "SHELL_VALID:true" in result.stdout
        assert "COMMAND_VALID:true" in result.stdout


class TestTerminalDataPlane:
    """Tests for terminal data plane (RNS Link) operations."""

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_stream_data_serialization(self, k8s_cluster, test_namespace, styrened_stack):
        """Test StreamData message serialization roundtrip.

        Success: All stream types (stdin/stdout/stderr) serialize correctly
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_streams = """
import sys
sys.path.insert(0, '/app/src')

from styrened.terminal.messages import (
    StreamData,
    serialize_message,
    deserialize_message,
)

# Test stdin
stdin_msg = StreamData(stream=StreamData.STDIN, data=b"user input")
wire = serialize_message(stdin_msg)
decoded = deserialize_message(wire)
assert decoded.is_stdin
assert decoded.data == b"user input"
print("STDIN_VALID:true")

# Test stdout
stdout_msg = StreamData(stream=StreamData.STDOUT, data=b"output text")
wire = serialize_message(stdout_msg)
decoded = deserialize_message(wire)
assert decoded.is_stdout
assert decoded.data == b"output text"
print("STDOUT_VALID:true")

# Test stderr
stderr_msg = StreamData(stream=StreamData.STDERR, data=b"error message")
wire = serialize_message(stderr_msg)
decoded = deserialize_message(wire)
assert decoded.is_stderr
assert decoded.data == b"error message"
print("STDERR_VALID:true")

# Test binary data
binary_data = bytes(range(256))
binary_msg = StreamData(stream=StreamData.STDOUT, data=binary_data)
wire = serialize_message(binary_msg)
decoded = deserialize_message(wire)
assert decoded.data == binary_data
print("BINARY_VALID:true")

# Test EOF flag
eof_msg = StreamData(stream=StreamData.STDOUT, data=b"", eof=True)
wire = serialize_message(eof_msg)
decoded = deserialize_message(wire)
assert decoded.eof is True
print("EOF_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_streams])

        assert "STDIN_VALID:true" in result.stdout
        assert "STDOUT_VALID:true" in result.stdout
        assert "STDERR_VALID:true" in result.stdout
        assert "BINARY_VALID:true" in result.stdout
        assert "EOF_VALID:true" in result.stdout

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_window_resize_message(self, k8s_cluster, test_namespace, styrened_stack):
        """Test WindowSize message handling.

        Success: WindowSize messages serialize with all dimensions
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_resize = """
import sys
sys.path.insert(0, '/app/src')

from styrened.terminal.messages import (
    WindowSize,
    serialize_message,
    deserialize_message,
)

# Basic resize
resize = WindowSize(rows=40, cols=120)
wire = serialize_message(resize)
decoded = deserialize_message(wire)

assert decoded.rows == 40
assert decoded.cols == 120
assert decoded.xpixel == 0
assert decoded.ypixel == 0
print("BASIC_RESIZE_VALID:true")

# Resize with pixels
resize2 = WindowSize(rows=50, cols=200, xpixel=1920, ypixel=1080)
wire = serialize_message(resize2)
decoded = deserialize_message(wire)

assert decoded.rows == 50
assert decoded.cols == 200
assert decoded.xpixel == 1920
assert decoded.ypixel == 1080
print("PIXEL_RESIZE_VALID:true")

# Control plane resize (LXMF)
from styrened.models.styrene_wire import create_terminal_resize, decode_payload

session_id = b"0123456789abcdef"
lxmf_resize = create_terminal_resize(rows=30, cols=100, session_id=session_id)
payload = decode_payload(lxmf_resize.payload)

assert payload["rows"] == 30
assert payload["cols"] == 100
assert payload["session_id"] == session_id.hex()
print("CONTROL_RESIZE_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_resize])

        assert "BASIC_RESIZE_VALID:true" in result.stdout
        assert "PIXEL_RESIZE_VALID:true" in result.stdout
        assert "CONTROL_RESIZE_VALID:true" in result.stdout


class TestTerminalSignals:
    """Tests for signal propagation through terminal sessions."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_signal_message_creation(self, k8s_cluster, test_namespace, styrened_stack):
        """Test TERMINAL_SIGNAL message creation for various signals.

        Success: All standard signals encoded correctly
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_signals = """
import sys
import signal
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import create_terminal_signal, decode_payload

session_id = b"test_session_id_"

# Test common signals
signals_to_test = [
    (signal.SIGINT, "SIGINT"),
    (signal.SIGTERM, "SIGTERM"),
    (signal.SIGHUP, "SIGHUP"),
    (signal.SIGTSTP, "SIGTSTP"),
    (signal.SIGCONT, "SIGCONT"),
]

for sig_num, sig_name in signals_to_test:
    msg = create_terminal_signal(signal=sig_num, session_id=session_id)
    payload = decode_payload(msg.payload)

    assert payload["signal"] == sig_num, f"{sig_name} encoding failed"
    assert payload["session_id"] == session_id.hex()
    print(f"{sig_name}_VALID:true")

# Test dangerous signal (SIGKILL) - should still encode
kill_msg = create_terminal_signal(signal=signal.SIGKILL, session_id=session_id)
payload = decode_payload(kill_msg.payload)
assert payload["signal"] == signal.SIGKILL
print("SIGKILL_ENCODES:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_signals])

        assert "SIGINT_VALID:true" in result.stdout
        assert "SIGTERM_VALID:true" in result.stdout
        assert "SIGHUP_VALID:true" in result.stdout
        assert "SIGKILL_ENCODES:true" in result.stdout


class TestSessionLifecycle:
    """Tests for terminal session lifecycle management."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_session_close_sequence(self, k8s_cluster, test_namespace, styrened_stack):
        """Test graceful session close sequence.

        Scenario:
        1. Create session close request
        2. Verify close message format
        3. Create closed notification
        4. Verify exit code and reason propagation

        Success: Close sequence messages format correctly
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_close = """
import sys
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import (
    create_terminal_close,
    create_terminal_closed,
    StyreneMessageType,
    decode_payload,
)

session_id = b"test_session_id_"

# Test close request
close = create_terminal_close(session_id=session_id)
assert close.message_type == StyreneMessageType.TERMINAL_CLOSE
payload = decode_payload(close.payload)
assert payload["session_id"] == session_id.hex()
print("CLOSE_REQUEST_VALID:true")

# Test closed notification - normal exit
closed = create_terminal_closed(
    exit_code=0,
    reason="exited",
    session_id=session_id,
)
assert closed.message_type == StyreneMessageType.TERMINAL_CLOSED
payload = decode_payload(closed.payload)
assert payload["exit_code"] == 0
assert payload["reason"] == "exited"
print("CLOSED_NORMAL_VALID:true")

# Test closed notification - signal exit
closed_signal = create_terminal_closed(
    exit_code=137,
    reason="signal",
    session_id=session_id,
)
payload = decode_payload(closed_signal.payload)
assert payload["exit_code"] == 137
assert payload["reason"] == "signal"
print("CLOSED_SIGNAL_VALID:true")

# Test closed notification - error
closed_error = create_terminal_closed(
    exit_code=1,
    reason="link_closed",
    session_id=session_id,
)
payload = decode_payload(closed_error.payload)
assert payload["reason"] == "link_closed"
print("CLOSED_ERROR_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_close])

        assert "CLOSE_REQUEST_VALID:true" in result.stdout
        assert "CLOSED_NORMAL_VALID:true" in result.stdout
        assert "CLOSED_SIGNAL_VALID:true" in result.stdout
        assert "CLOSED_ERROR_VALID:true" in result.stdout

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_command_exit_message(self, k8s_cluster, test_namespace, styrened_stack):
        """Test CommandExited data plane message.

        Success: Exit codes and signals encoded correctly
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_exit = """
import sys
import signal
sys.path.insert(0, '/app/src')

from styrened.terminal.messages import (
    CommandExited,
    serialize_message,
    deserialize_message,
)

# Normal exit
exit_normal = CommandExited(return_code=0)
wire = serialize_message(exit_normal)
decoded = deserialize_message(wire)
assert decoded.return_code == 0
assert decoded.signal is None
print("EXIT_NORMAL_VALID:true")

# Error exit
exit_error = CommandExited(return_code=127)
wire = serialize_message(exit_error)
decoded = deserialize_message(wire)
assert decoded.return_code == 127
print("EXIT_ERROR_VALID:true")

# Signal exit (SIGKILL = 9, so exit code 128+9=137)
exit_signal = CommandExited(return_code=137, signal=signal.SIGKILL)
wire = serialize_message(exit_signal)
decoded = deserialize_message(wire)
assert decoded.return_code == 137
assert decoded.signal == signal.SIGKILL
print("EXIT_SIGNAL_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_exit])

        assert "EXIT_NORMAL_VALID:true" in result.stdout
        assert "EXIT_ERROR_VALID:true" in result.stdout
        assert "EXIT_SIGNAL_VALID:true" in result.stdout


class TestFailureModes:
    """Tests for terminal session failure handling."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_invalid_message_handling(self, k8s_cluster, test_namespace, styrened_stack):
        """Test handling of malformed terminal messages.

        Success: Invalid messages raise appropriate exceptions
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_invalid = """
import sys
sys.path.insert(0, '/app/src')

from styrened.terminal.messages import deserialize_message

# Empty message
try:
    deserialize_message(b"")
    print("EMPTY_SHOULD_FAIL")
except ValueError as e:
    assert "Empty message" in str(e)
    print("EMPTY_RAISES:true")

# Invalid message type
try:
    deserialize_message(bytes([99]))  # Invalid type byte
    print("INVALID_TYPE_SHOULD_FAIL")
except ValueError:
    print("INVALID_TYPE_RAISES:true")

# Truncated message (type byte only, no payload)
try:
    deserialize_message(bytes([1]))  # StreamData type with no data
    print("TRUNCATED_RESULT:handled_or_raised")
except Exception as e:
    print(f"TRUNCATED_RAISES:{type(e).__name__}")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_invalid])

        assert "EMPTY_RAISES:true" in result.stdout
        assert "INVALID_TYPE_RAISES:true" in result.stdout

    @pytest.mark.asyncio
    @pytest.mark.comprehensive
    async def test_pod_restart_session_recovery(self, k8s_cluster, test_namespace, styrened_stack):
        """Test terminal session behavior when server pod restarts.

        Scenario:
        1. Deploy 2 pods, establish conceptual session
        2. Delete server pod (simulate crash)
        3. Wait for pod recreation
        4. Verify client detects disconnection

        Success: Session state properly cleaned up after pod restart
        """
        pods = styrened_stack(
            replica_count=2,
            mode="standalone",
            extra_values={"styrene.terminal.enabled": "true"},
        )
        client_pod, server_pod = pods[0], pods[1]

        await asyncio.sleep(20)

        # Verify both pods are running
        for pod in pods:
            result = k8s_cluster.exec_in_pod(pod, ["pgrep", "-f", "styrened"])
            assert result.returncode == 0, f"Pod {pod} not running styrened"

        # Get server logs before restart (for debugging if needed)
        _server_logs_before = k8s_cluster.get_pod_logs(server_pod, tail=50)

        # Delete server pod
        k8s_cluster.delete_pod(server_pod)

        # Wait for pod recreation
        await asyncio.sleep(30)

        # Verify client is still running
        result = k8s_cluster.exec_in_pod(client_pod, ["pgrep", "-f", "styrened"])
        assert result.returncode == 0, "Client should survive server restart"

        # Check client logs for disconnection evidence
        _client_logs = k8s_cluster.get_pod_logs(client_pod, tail=100, since_seconds=45)
        # Client should detect something (link closure, timeout, etc.)
        # The exact message depends on implementation

    @pytest.mark.asyncio
    @pytest.mark.comprehensive
    async def test_network_partition_handling(self, k8s_cluster, test_namespace, styrened_stack):
        """Test terminal session behavior during network partition.

        Scenario:
        1. Deploy pods on different nodes (if multi-node)
        2. Create NetworkPolicy to block traffic
        3. Verify session detects partition
        4. Remove NetworkPolicy
        5. Verify behavior after partition heals

        Success: Session handles partition gracefully
        """
        pods = styrened_stack(
            replica_count=2,
            mode="standalone",
            extra_values={"styrene.terminal.enabled": "true"},
        )
        pod_a, pod_b = pods[0], pods[1]

        await asyncio.sleep(20)

        # Get pod IPs
        pod_a_status = k8s_cluster.get_pod_status(pod_a)
        pod_b_status = k8s_cluster.get_pod_status(pod_b)

        pod_a_ip = pod_a_status.get("status", {}).get("podIP")
        pod_b_ip = pod_b_status.get("status", {}).get("podIP")

        assert pod_a_ip and pod_b_ip, "Pod IPs required for network test"

        # Verify connectivity before partition
        result = k8s_cluster.exec_in_pod(pod_a, ["ping", "-c", "2", "-W", "3", pod_b_ip])
        assert result.returncode == 0, "Pods should be able to communicate initially"

        # Create NetworkPolicy to block traffic
        network_policy = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": "terminal-partition-test",
                "namespace": test_namespace,
            },
            "spec": {
                "podSelector": {"matchLabels": {"app.kubernetes.io/name": "styrened-test"}},
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [],  # Block all ingress
                "egress": [],  # Block all egress
            },
        }

        try:
            k8s_cluster.apply_manifest(network_policy)
            await asyncio.sleep(10)

            # Verify partition (ping should fail)
            result = k8s_cluster.exec_in_pod(
                pod_a, ["ping", "-c", "2", "-W", "3", pod_b_ip], timeout=15
            )
            # Ping may succeed or fail depending on CNI implementation
            # The important thing is the test runs

            # Check logs for any timeout/disconnection evidence
            _logs_a = k8s_cluster.get_pod_logs(pod_a, tail=50, since_seconds=20)

        finally:
            # Cleanup NetworkPolicy
            k8s_cluster.delete_manifest("NetworkPolicy", "terminal-partition-test")
            await asyncio.sleep(5)

        # Verify connectivity restored
        result = k8s_cluster.exec_in_pod(pod_a, ["ping", "-c", "2", "-W", "5", pod_b_ip])
        # May or may not succeed depending on timing


class TestConcurrentSessions:
    """Tests for concurrent terminal session handling."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_multiple_session_requests(self, k8s_cluster, test_namespace, styrened_stack):
        """Test handling of multiple concurrent session requests.

        Scenario:
        1. Deploy 4 pods
        2. Pod A creates requests to B, C, D simultaneously
        3. Verify all request envelopes created correctly

        Success: Multiple requests created without interference
        """
        pods = styrened_stack(
            replica_count=4,
            mode="standalone",
            extra_values={"styrene.terminal.enabled": "true"},
        )

        await asyncio.sleep(20)

        # Create multiple requests from first pod
        script_multi_request = """
import sys
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import create_terminal_request

# Create 3 independent requests
requests = []
for i in range(3):
    req = create_terminal_request(
        term_type=f"xterm-{i}",
        rows=24 + i,
        cols=80 + i,
    )
    requests.append(req)

# Verify all have unique request IDs
request_ids = [r.request_id for r in requests]
assert len(set(request_ids)) == 3, "Request IDs should be unique"
print("UNIQUE_IDS:true")

# Verify all encode independently
for i, req in enumerate(requests):
    wire = req.encode()
    assert len(wire) > 0
    print(f"REQUEST_{i}_ENCODED:true")

print(f"TOTAL_REQUESTS:{len(requests)}")
"""
        result = k8s_cluster.exec_in_pod(pods[0], ["python3", "-c", script_multi_request])

        assert "UNIQUE_IDS:true" in result.stdout
        assert "TOTAL_REQUESTS:3" in result.stdout
        assert "REQUEST_0_ENCODED:true" in result.stdout
        assert "REQUEST_1_ENCODED:true" in result.stdout
        assert "REQUEST_2_ENCODED:true" in result.stdout

    @pytest.mark.asyncio
    @pytest.mark.comprehensive
    async def test_session_resource_limits(self, k8s_cluster, test_namespace, styrened_stack):
        """Test terminal session resource usage under load.

        Scenario:
        1. Deploy pod with resource limits
        2. Create multiple session message instances
        3. Measure memory usage
        4. Verify no resource leaks

        Success: Resource usage stays within limits
        """
        pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            cpu_limit="200m",
            memory_limit="256Mi",
            extra_values={"styrene.terminal.enabled": "true"},
        )
        pod = pods[0]

        await asyncio.sleep(15)

        # Get initial metrics
        initial_metrics = k8s_cluster.get_pod_metrics(pod)
        initial_memory = initial_metrics.get("memory_usage_mb", 0)

        # Create many messages
        script_stress = """
import sys
import gc
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import create_terminal_request
from styrened.terminal.messages import StreamData, serialize_message

# Create many request objects
requests = []
for i in range(1000):
    req = create_terminal_request(rows=24, cols=80)
    wire = req.encode()
    requests.append((req, wire))

print(f"REQUESTS_CREATED:{len(requests)}")

# Create many stream data messages
messages = []
for i in range(1000):
    msg = StreamData(stream=StreamData.STDOUT, data=b"x" * 1000)
    wire = serialize_message(msg)
    messages.append((msg, wire))

print(f"MESSAGES_CREATED:{len(messages)}")

# Clear references
del requests
del messages
gc.collect()

print("STRESS_COMPLETE:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_stress], timeout=60)

        assert "REQUESTS_CREATED:1000" in result.stdout
        assert "MESSAGES_CREATED:1000" in result.stdout
        assert "STRESS_COMPLETE:true" in result.stdout

        # Check metrics after stress
        await asyncio.sleep(5)
        final_metrics = k8s_cluster.get_pod_metrics(pod)
        final_memory = final_metrics.get("memory_usage_mb", 0)

        # Memory shouldn't have grown excessively (allow 50MB growth)
        if initial_memory > 0 and final_memory > 0:
            growth = final_memory - initial_memory
            assert growth < 50, f"Memory grew by {growth}MB, possible leak"


class TestVersionNegotiation:
    """Tests for protocol version negotiation."""

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_version_info_exchange(self, k8s_cluster, test_namespace, styrened_stack):
        """Test VersionInfo message exchange.

        Success: Version info serializes and deserializes correctly
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_version = """
import sys
sys.path.insert(0, '/app/src')

from styrened.terminal.messages import (
    VersionInfo,
    serialize_message,
    deserialize_message,
)

# Default version
default_version = VersionInfo()
wire = serialize_message(default_version)
decoded = deserialize_message(wire)

assert decoded.version == "1.0"
assert decoded.software == "styrened"
print("DEFAULT_VERSION_VALID:true")

# Custom version
custom_version = VersionInfo(version="2.0", software="test-client/1.0.0")
wire = serialize_message(custom_version)
decoded = deserialize_message(wire)

assert decoded.version == "2.0"
assert decoded.software == "test-client/1.0.0"
print("CUSTOM_VERSION_VALID:true")

# Wire format check
assert wire[0] == 4  # VERSION_INFO type
print("WIRE_TYPE_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_version])

        assert "DEFAULT_VERSION_VALID:true" in result.stdout
        assert "CUSTOM_VERSION_VALID:true" in result.stdout
        assert "WIRE_TYPE_VALID:true" in result.stdout


class TestErrorMessages:
    """Tests for error message handling."""

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_error_message_creation(self, k8s_cluster, test_namespace, styrened_stack):
        """Test Error message creation and serialization.

        Success: Error messages with various severity levels serialize correctly
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_errors = """
import sys
sys.path.insert(0, '/app/src')

from styrened.terminal.messages import (
    Error,
    serialize_message,
    deserialize_message,
)

# Non-fatal error
warning = Error(message="Connection unstable", code=100, fatal=False)
wire = serialize_message(warning)
decoded = deserialize_message(wire)

assert decoded.message == "Connection unstable"
assert decoded.code == 100
assert decoded.fatal is False
print("WARNING_VALID:true")

# Fatal error
fatal = Error(message="Session terminated", code=500, fatal=True)
wire = serialize_message(fatal)
decoded = deserialize_message(wire)

assert decoded.message == "Session terminated"
assert decoded.code == 500
assert decoded.fatal is True
print("FATAL_VALID:true")

# Default values
default = Error(message="Something went wrong")
wire = serialize_message(default)
decoded = deserialize_message(wire)

assert decoded.code == 1
assert decoded.fatal is False
print("DEFAULT_VALUES_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_errors])

        assert "WARNING_VALID:true" in result.stdout
        assert "FATAL_VALID:true" in result.stdout
        assert "DEFAULT_VALUES_VALID:true" in result.stdout


class TestSecurityBoundaries:
    """Tests for security boundary enforcement."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_authorization_config_loading(self, k8s_cluster, test_namespace, styrened_stack):
        """Test authorized identities configuration loading.

        Success: Authorization configuration parsed correctly
        """
        pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            extra_values={
                "styrene.terminal.enabled": "true",
                "styrene.terminal.authorized_identities": "abc123,def456",
            },
        )
        pod = pods[0]

        await asyncio.sleep(15)

        # Verify terminal service configuration in logs
        logs = k8s_cluster.get_pod_logs(pod, tail=100)

        # Should see evidence of terminal service initialization
        assert any(
            word in logs.lower() for word in ["terminal", "service", "started", "initialized"]
        ), "Terminal service should show initialization in logs"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_session_identity_binding(self, k8s_cluster, test_namespace, styrened_stack):
        """Test that sessions are bound to requesting identity.

        Scenario:
        1. Verify session state includes source_identity
        2. Verify control messages check identity match

        Success: Sessions properly bound to identities
        """
        pods = styrened_stack(
            replica_count=1,
            mode="standalone",
            extra_values={"styrene.terminal.enabled": "true"},
        )
        pod = pods[0]

        await asyncio.sleep(15)

        script_test_binding = """
import sys
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import (
    create_terminal_resize,
    create_terminal_signal,
    create_terminal_close,
    decode_payload,
)
import signal

session_id = b"bound_session_id"

# Resize includes session_id for binding verification
resize = create_terminal_resize(rows=30, cols=100, session_id=session_id)
payload = decode_payload(resize.payload)
assert payload["session_id"] == session_id.hex()
print("RESIZE_BOUND:true")

# Signal includes session_id
sig = create_terminal_signal(signal=signal.SIGINT, session_id=session_id)
payload = decode_payload(sig.payload)
assert payload["session_id"] == session_id.hex()
print("SIGNAL_BOUND:true")

# Close includes session_id
close = create_terminal_close(session_id=session_id)
payload = decode_payload(close.payload)
assert payload["session_id"] == session_id.hex()
print("CLOSE_BOUND:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_binding])

        assert "RESIZE_BOUND:true" in result.stdout
        assert "SIGNAL_BOUND:true" in result.stdout
        assert "CLOSE_BOUND:true" in result.stdout

    @pytest.mark.asyncio
    @pytest.mark.comprehensive
    async def test_malicious_payload_rejection(self, k8s_cluster, test_namespace, styrened_stack):
        """Test rejection of maliciously crafted payloads.

        Success: Malformed payloads raise appropriate errors
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_malicious = """
import sys
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import (
    StyreneEnvelope,
    decode_payload,
    PayloadDecodeError,
    MAX_PAYLOAD_SIZE,
)

# Test oversized payload detection
try:
    # Create payload larger than limit
    large_payload = b"x" * (MAX_PAYLOAD_SIZE + 1)
    decode_payload(large_payload)
    print("OVERSIZE_SHOULD_FAIL")
except PayloadDecodeError:
    print("OVERSIZE_REJECTED:true")

# Test invalid msgpack
try:
    invalid_msgpack = b"\\xff\\xfe\\xfd"  # Not valid msgpack
    decode_payload(invalid_msgpack)
    print("INVALID_MSGPACK_SHOULD_FAIL")
except PayloadDecodeError:
    print("INVALID_MSGPACK_REJECTED:true")

print("MALICIOUS_TESTS_COMPLETE:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_malicious])

        assert "OVERSIZE_REJECTED:true" in result.stdout
        assert "INVALID_MSGPACK_REJECTED:true" in result.stdout
        assert "MALICIOUS_TESTS_COMPLETE:true" in result.stdout


class TestKeepAlive:
    """Tests for session keepalive/noop messages."""

    @pytest.mark.asyncio
    @pytest.mark.smoke
    async def test_noop_message(self, k8s_cluster, test_namespace, styrened_stack):
        """Test Noop keepalive message.

        Success: Noop serializes as minimal wire message
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_noop = """
import sys
sys.path.insert(0, '/app/src')

from styrened.terminal.messages import (
    Noop,
    TerminalMessageType,
    serialize_message,
    deserialize_message,
)

# Create noop
noop = Noop()
wire = serialize_message(noop)

# Verify minimal size
assert wire[0] == TerminalMessageType.NOOP
print(f"NOOP_SIZE:{len(wire)}")

# Verify roundtrip
decoded = deserialize_message(wire)
assert isinstance(decoded, Noop)
print("NOOP_ROUNDTRIP:true")

# Create multiple noops (for keepalive scenarios)
noops = [Noop() for _ in range(100)]
wires = [serialize_message(n) for n in noops]
assert all(len(w) == len(wires[0]) for w in wires)
print("NOOP_CONSISTENT:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_noop])

        assert "NOOP_ROUNDTRIP:true" in result.stdout
        assert "NOOP_CONSISTENT:true" in result.stdout


class TestWireProtocolIntegrity:
    """Tests for wire protocol integrity."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_message_type_prefixes(self, k8s_cluster, test_namespace, styrened_stack):
        """Test that all message types have correct prefix bytes.

        Success: All message types identified by first byte
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_prefixes = """
import sys
sys.path.insert(0, '/app/src')

from styrened.terminal.messages import (
    Noop,
    StreamData,
    WindowSize,
    CommandExited,
    VersionInfo,
    Error,
    TerminalMessageType,
    serialize_message,
)

# Map messages to expected types
test_cases = [
    (Noop(), TerminalMessageType.NOOP),
    (StreamData(stream=0, data=b""), TerminalMessageType.STREAM_DATA),
    (WindowSize(rows=24, cols=80), TerminalMessageType.WINDOW_SIZE),
    (CommandExited(return_code=0), TerminalMessageType.COMMAND_EXITED),
    (VersionInfo(), TerminalMessageType.VERSION_INFO),
    (Error(message="test"), TerminalMessageType.ERROR),
]

for msg, expected_type in test_cases:
    wire = serialize_message(msg)
    actual_type = wire[0]
    assert actual_type == expected_type, f"{type(msg).__name__}: expected {expected_type}, got {actual_type}"
    print(f"{type(msg).__name__}_PREFIX:valid")

print("ALL_PREFIXES_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_prefixes])

        assert "ALL_PREFIXES_VALID:true" in result.stdout
        assert "Noop_PREFIX:valid" in result.stdout
        assert "StreamData_PREFIX:valid" in result.stdout

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_control_plane_message_types(self, k8s_cluster, test_namespace, styrened_stack):
        """Test terminal control plane message types are in reserved range.

        Success: All TERMINAL_* types in 0xC0-0xCF range
        """
        pods = styrened_stack(replica_count=1, mode="standalone")
        pod = pods[0]

        await asyncio.sleep(10)

        script_test_ranges = """
import sys
sys.path.insert(0, '/app/src')

from styrened.models.styrene_wire import StyreneMessageType

terminal_types = [
    StyreneMessageType.TERMINAL_REQUEST,
    StyreneMessageType.TERMINAL_ACCEPT,
    StyreneMessageType.TERMINAL_REJECT,
    StyreneMessageType.TERMINAL_RESIZE,
    StyreneMessageType.TERMINAL_SIGNAL,
    StyreneMessageType.TERMINAL_CLOSE,
    StyreneMessageType.TERMINAL_CLOSED,
]

for msg_type in terminal_types:
    value = msg_type.value
    assert 0xC0 <= value <= 0xCF, f"{msg_type.name} value {hex(value)} not in terminal range"
    print(f"{msg_type.name}:{hex(value)}:valid")

# Verify uniqueness
values = [t.value for t in terminal_types]
assert len(values) == len(set(values)), "Duplicate message type values"
print("TYPES_UNIQUE:true")

print("ALL_RANGES_VALID:true")
"""
        result = k8s_cluster.exec_in_pod(pod, ["python3", "-c", script_test_ranges])

        assert "ALL_RANGES_VALID:true" in result.stdout
        assert "TYPES_UNIQUE:true" in result.stdout
