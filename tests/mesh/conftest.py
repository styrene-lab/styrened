"""Fixtures for dual-container mesh conversation tests.

Manages Docker Compose lifecycle, ControlClient connections via TCP relay,
and mesh discovery. All fixtures are session-scoped — containers start
once per test session.

IPC access strategy: Each container runs a Python TCP relay (tcp_relay.py)
that bridges the styrened Unix socket to a TCP port. The test host connects
via TCP using MeshControlClient, a thin ControlClient subclass that uses
asyncio.open_connection instead of open_unix_connection.
"""

import asyncio
import logging
import subprocess
from pathlib import Path

import pytest
import pytest_asyncio

# Shared IPC client and helpers — importable by both mesh and k8s tests
from tests.harness.ipc_client import (
    MeshControlClient,
    poll_for_message,
)
from tests.harness.ipc_client import (
    wait_for_ping as _wait_for_ping,
)
from tests.harness.ipc_client import (
    warmup_path as _warmup_path,
)


def _extract_content(content: object) -> str:
    """Extract plain-text string from an LXMF message content field.

    Content may arrive as ``str``, ``bytes``, or a ``dict`` with a
    ``"text"`` key depending on the transport layer.
    """
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    if isinstance(content, dict):
        return str(content.get("text", content))
    return str(content)

logger = logging.getLogger(__name__)

COMPOSE_FILE = Path(__file__).parent / "docker-compose.yaml"
MULTIHOP_COMPOSE_FILE = Path(__file__).parent / "docker-compose.multihop.yaml"
STARTUP_TIMEOUT = 60  # seconds for daemons + relay to be ready
DISCOVERY_TIMEOUT = 30  # seconds for mutual discovery
MULTIHOP_DISCOVERY_TIMEOUT = 60  # transport path resolution needs more time

# Default TCP relay ports (match docker-compose.yaml)
NODE_A_HOST = "127.0.0.1"
NODE_A_PORT = 9001
NODE_B_HOST = "127.0.0.1"
NODE_B_PORT = 9002

# Multihop TCP relay ports (match docker-compose.multihop.yaml)
MULTIHOP_A_PORT = 9011
MULTIHOP_B_PORT = 9012
MULTIHOP_C_PORT = 9013


def _compose_cmd(*args: str, compose_file: Path = COMPOSE_FILE) -> list[str]:
    """Build docker compose command."""
    return ["docker", "compose", "-f", str(compose_file), *args]


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mesh_topology():
    """Start two-node Docker mesh, wait for containers, tear down at end.

    Yields:
        Dict with TCP connection details for each node.
    """
    # Start containers
    logger.info("Starting mesh topology from %s", COMPOSE_FILE)
    up_result = subprocess.run(
        _compose_cmd("up", "-d"),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if up_result.returncode != 0:
        pytest.fail(
            f"docker compose up failed:\nstdout: {up_result.stdout}\nstderr: {up_result.stderr}"
        )

    topology = {
        "node_a_host": NODE_A_HOST,
        "node_a_port": NODE_A_PORT,
        "node_b_host": NODE_B_HOST,
        "node_b_port": NODE_B_PORT,
    }

    yield topology

    # Teardown
    logger.info("Tearing down mesh topology")
    subprocess.run(
        _compose_cmd("down", "-v"),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def node_a_client(mesh_topology) -> MeshControlClient:
    """MeshControlClient connected to node-a via TCP relay."""
    client = MeshControlClient(
        host=mesh_topology["node_a_host"],
        port=mesh_topology["node_a_port"],
        timeout=10.0,
    )

    if not await _wait_for_ping(client, timeout=STARTUP_TIMEOUT):
        # Dump logs for debugging
        logs = subprocess.run(
            _compose_cmd("logs", "node-a"),
            capture_output=True,
            text=True,
            check=False,
        )
        pytest.fail(
            f"node-a daemon not responsive via TCP "
            f"{mesh_topology['node_a_host']}:{mesh_topology['node_a_port']}\n"
            f"Container logs:\n{logs.stdout}\n{logs.stderr}"
        )

    yield client

    await client.disconnect()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def node_b_client(mesh_topology) -> MeshControlClient:
    """MeshControlClient connected to node-b via TCP relay."""
    client = MeshControlClient(
        host=mesh_topology["node_b_host"],
        port=mesh_topology["node_b_port"],
        timeout=10.0,
    )

    if not await _wait_for_ping(client, timeout=STARTUP_TIMEOUT):
        logs = subprocess.run(
            _compose_cmd("logs", "node-b"),
            capture_output=True,
            text=True,
            check=False,
        )
        pytest.fail(
            f"node-b daemon not responsive via TCP "
            f"{mesh_topology['node_b_host']}:{mesh_topology['node_b_port']}\n"
            f"Container logs:\n{logs.stdout}\n{logs.stderr}"
        )

    yield client

    await client.disconnect()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def discovered_mesh(node_a_client, node_b_client):
    """Wait until both nodes have discovered each other via RNS announces.

    Yields:
        Tuple of (node_a_identity_hash, node_b_identity_hash,
                  node_a_lxmf_hash, node_b_lxmf_hash).
    """
    # Get identities — lxmf_destination_hash is the peer_hash for send_chat
    id_a = await node_a_client.query_identity()
    id_b = await node_b_client.query_identity()

    a_lxmf = id_a.lxmf_destination_hash
    b_lxmf = id_b.lxmf_destination_hash

    assert a_lxmf, "Node A has no LXMF destination hash"
    assert b_lxmf, "Node B has no LXMF destination hash"

    # Trigger announces on both nodes to seed discovery
    await node_a_client.announce()
    await node_b_client.announce()

    # Wait for mutual discovery
    deadline = asyncio.get_event_loop().time() + DISCOVERY_TIMEOUT
    a_sees_b = False
    b_sees_a = False

    while asyncio.get_event_loop().time() < deadline:
        if not a_sees_b:
            devices_a = await node_a_client.query_devices()
            a_sees_b = any(d.identity_hash == id_b.identity_hash for d in devices_a)

        if not b_sees_a:
            devices_b = await node_b_client.query_devices()
            b_sees_a = any(d.identity_hash == id_a.identity_hash for d in devices_b)

        if a_sees_b and b_sees_a:
            break

        # Re-announce to speed things up
        await node_a_client.announce()
        await node_b_client.announce()
        await asyncio.sleep(2.0)

    if not a_sees_b or not b_sees_a:
        pytest.fail(
            f"Mutual discovery failed within {DISCOVERY_TIMEOUT}s. "
            f"A sees B: {a_sees_b}, B sees A: {b_sees_a}"
        )

    # Pre-warm LXMF paths with a bidirectional message exchange.
    # This establishes links and caches paths so actual tests get fast delivery.
    logger.info("Warming up LXMF paths with bidirectional message exchange...")
    warmup_timeout = 30

    try:
        await node_a_client.send_chat(peer_hash=b_lxmf, content="__warmup_a_to_b__")
        warmup_received = await poll_for_message(
            node_b_client, content="__warmup_a_to_b__", timeout=warmup_timeout
        )
        if warmup_received:
            logger.info("LXMF warmup A->B delivered")
        else:
            logger.warning("LXMF warmup A->B not received within %ds", warmup_timeout)
    except Exception as e:
        logger.warning("Warmup A->B failed: %s", e)

    try:
        await node_b_client.send_chat(peer_hash=a_lxmf, content="__warmup_b_to_a__")
        warmup_received = await poll_for_message(
            node_a_client, content="__warmup_b_to_a__", timeout=warmup_timeout
        )
        if warmup_received:
            logger.info("LXMF warmup B->A delivered")
        else:
            logger.warning("LXMF warmup B->A not received within %ds", warmup_timeout)
    except Exception as e:
        logger.warning("Warmup B->A failed: %s", e)

    return (id_a.identity_hash, id_b.identity_hash, a_lxmf, b_lxmf)


# ---------------------------------------------------------------------------
# Multihop topology fixtures (3-node, dual-network)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def multihop_topology():
    """Start three-node multi-hop Docker mesh, tear down at end.

    Topology:
        alpha network: node-a-edge <-> node-b-transport
        beta  network: node-b-transport <-> node-c-edge

    Node A and C share no network — messages route through B.

    Yields:
        Dict with TCP connection details for each node.
    """
    logger.info("Starting multihop topology from %s", MULTIHOP_COMPOSE_FILE)
    up_result = subprocess.run(
        _compose_cmd("up", "-d", "--build", compose_file=MULTIHOP_COMPOSE_FILE),
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if up_result.returncode != 0:
        pytest.fail(
            f"multihop compose up failed:\nstdout: {up_result.stdout}\n"
            f"stderr: {up_result.stderr}"
        )

    topology = {
        "node_a_host": NODE_A_HOST,
        "node_a_port": MULTIHOP_A_PORT,
        "node_b_host": NODE_A_HOST,
        "node_b_port": MULTIHOP_B_PORT,
        "node_c_host": NODE_A_HOST,
        "node_c_port": MULTIHOP_C_PORT,
    }

    yield topology

    logger.info("Tearing down multihop topology")
    subprocess.run(
        _compose_cmd("down", "-v", compose_file=MULTIHOP_COMPOSE_FILE),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def multihop_node_a(multihop_topology) -> MeshControlClient:
    """MeshControlClient for edge node A (alpha network only)."""
    client = MeshControlClient(
        host=multihop_topology["node_a_host"],
        port=multihop_topology["node_a_port"],
        timeout=10.0,
    )
    if not await _wait_for_ping(client, timeout=STARTUP_TIMEOUT):
        logs = subprocess.run(
            _compose_cmd("logs", "node-a-edge", compose_file=MULTIHOP_COMPOSE_FILE),
            capture_output=True, text=True, check=False,
        )
        pytest.fail(
            f"multihop node-a not responsive on port {multihop_topology['node_a_port']}\n"
            f"Container logs:\n{logs.stdout}\n{logs.stderr}"
        )
    yield client
    await client.disconnect()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def multihop_node_b(multihop_topology) -> MeshControlClient:
    """MeshControlClient for transport node B (alpha + beta networks)."""
    client = MeshControlClient(
        host=multihop_topology["node_b_host"],
        port=multihop_topology["node_b_port"],
        timeout=10.0,
    )
    if not await _wait_for_ping(client, timeout=STARTUP_TIMEOUT):
        logs = subprocess.run(
            _compose_cmd("logs", "node-b-transport", compose_file=MULTIHOP_COMPOSE_FILE),
            capture_output=True, text=True, check=False,
        )
        pytest.fail(
            f"multihop node-b not responsive on port {multihop_topology['node_b_port']}\n"
            f"Container logs:\n{logs.stdout}\n{logs.stderr}"
        )
    yield client
    await client.disconnect()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def multihop_node_c(multihop_topology) -> MeshControlClient:
    """MeshControlClient for edge node C (beta network only)."""
    client = MeshControlClient(
        host=multihop_topology["node_c_host"],
        port=multihop_topology["node_c_port"],
        timeout=10.0,
    )
    if not await _wait_for_ping(client, timeout=STARTUP_TIMEOUT):
        logs = subprocess.run(
            _compose_cmd("logs", "node-c-edge", compose_file=MULTIHOP_COMPOSE_FILE),
            capture_output=True, text=True, check=False,
        )
        pytest.fail(
            f"multihop node-c not responsive on port {multihop_topology['node_c_port']}\n"
            f"Container logs:\n{logs.stdout}\n{logs.stderr}"
        )
    yield client
    await client.disconnect()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def discovered_multihop(multihop_node_a, multihop_node_b, multihop_node_c):
    """Wait for full three-node discovery across the transport bridge.

    Discovery path: A announces on alpha, B (transport) re-announces
    across beta, C learns about A. Same in reverse for C -> A.

    Yields:
        Dict with identity and LXMF hashes for all three nodes.
    """
    id_a = await multihop_node_a.query_identity()
    id_b = await multihop_node_b.query_identity()
    id_c = await multihop_node_c.query_identity()

    a_lxmf = id_a.lxmf_destination_hash
    b_lxmf = id_b.lxmf_destination_hash
    c_lxmf = id_c.lxmf_destination_hash

    assert a_lxmf, "Node A has no LXMF destination hash"
    assert b_lxmf, "Node B has no LXMF destination hash"
    assert c_lxmf, "Node C has no LXMF destination hash"

    # Announce all three nodes
    await multihop_node_a.announce()
    await multihop_node_b.announce()
    await multihop_node_c.announce()

    # Wait for A and C to discover each other through B's transport
    deadline = asyncio.get_event_loop().time() + MULTIHOP_DISCOVERY_TIMEOUT
    a_sees_c = False
    c_sees_a = False

    while asyncio.get_event_loop().time() < deadline:
        if not a_sees_c:
            devices_a = await multihop_node_a.query_devices()
            a_sees_c = any(d.identity_hash == id_c.identity_hash for d in devices_a)

        if not c_sees_a:
            devices_c = await multihop_node_c.query_devices()
            c_sees_a = any(d.identity_hash == id_a.identity_hash for d in devices_c)

        if a_sees_c and c_sees_a:
            break

        await multihop_node_a.announce()
        await multihop_node_b.announce()
        await multihop_node_c.announce()
        await asyncio.sleep(2.0)

    if not a_sees_c or not c_sees_a:
        pytest.fail(
            f"Multi-hop discovery failed within {MULTIHOP_DISCOVERY_TIMEOUT}s. "
            f"A sees C: {a_sees_c}, C sees A: {c_sees_a}"
        )

    # Warmup LXMF paths (multi-hop paths need extra priming)
    logger.info("Warming up multi-hop LXMF paths...")
    await _warmup_path(multihop_node_a, multihop_node_c, c_lxmf, "a_to_c", timeout=45)
    await _warmup_path(multihop_node_c, multihop_node_a, a_lxmf, "c_to_a", timeout=45)

    return {
        "a_id": id_a.identity_hash,
        "b_id": id_b.identity_hash,
        "c_id": id_c.identity_hash,
        "a_lxmf": a_lxmf,
        "b_lxmf": b_lxmf,
        "c_lxmf": c_lxmf,
    }


# ---------------------------------------------------------------------------
# pytest configuration
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """Register test markers."""
    config.addinivalue_line(
        "markers",
        "mesh: requires Docker mesh topology (two styrened containers)",
    )
    config.addinivalue_line(
        "markers",
        "multihop: requires multi-hop Docker topology (three containers, two networks)",
    )
