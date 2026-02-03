"""Pytest fixtures for cross-platform test scenarios."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

# Ensure tests package is importable
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

if TYPE_CHECKING:
    from tests.harness.base import NodeInfo, TestHarness


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers and configure logging for scenario tests."""
    config.addinivalue_line("markers", "smoke: Quick validation tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "comprehensive: Comprehensive tests")
    config.addinivalue_line("markers", "installation: Full installation tests")
    config.addinivalue_line("markers", "provisioning: Complete provisioning tests")

    # Configure harness logging based on environment/verbosity
    from tests.harness.logging import configure_harness_logging

    # Determine log level from environment or pytest verbosity
    log_level = os.environ.get("HARNESS_LOG_LEVEL", "INFO")
    if config.option.verbose >= 2:
        log_level = "DEBUG"
    elif config.option.verbose >= 1:
        log_level = "INFO"

    # Configure the harness logger
    configure_harness_logging(
        level=log_level,
        verbose=(config.option.verbose >= 2),
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add command-line options for scenario tests."""
    parser.addoption(
        "--backend",
        action="store",
        default="ssh",
        choices=["ssh", "k8s", "both"],
        help="Test backend: ssh (bare-metal), k8s, or both",
    )
    parser.addoption(
        "--k8s-namespace",
        action="store",
        default="styrene-test",
        help="K8s namespace for tests",
    )
    parser.addoption(
        "--k8s-replica-count",
        action="store",
        default="2",
        type=int,
        help="Number of K8s pods to deploy for tests",
    )
    parser.addoption(
        "--devices-file",
        action="store",
        default=None,
        help="Path to devices.yaml for SSH backend",
    )
    # Installation test options
    parser.addoption(
        "--install-tag",
        action="store",
        default=None,
        help="Git tag to install for installation tests",
    )
    parser.addoption(
        "--wheel-path",
        action="store",
        default=None,
        help="Path to wheel file for installation tests",
    )


@pytest.fixture(scope="session")
def backend(request: pytest.FixtureRequest) -> str:
    """Get the requested backend type."""
    return request.config.getoption("--backend")


@pytest.fixture(scope="session")
def ssh_harness(request: pytest.FixtureRequest) -> TestHarness:
    """Create SSH harness instance."""
    from tests.harness.ssh import SSHHarness

    devices_file = request.config.getoption("--devices-file")
    if devices_file:
        devices_file = Path(devices_file)

    return SSHHarness(devices_file=devices_file)


@pytest.fixture(scope="session")
def k8s_harness_base(request: pytest.FixtureRequest) -> TestHarness:
    """Create base K8s harness instance (without deployment)."""
    from tests.harness.k8s import K8sHarness

    # Check for kubeconfig
    kubeconfig = os.environ.get("KUBECONFIG")
    if not kubeconfig:
        kubeconfig_path = Path.home() / ".kube" / "config"
        if kubeconfig_path.exists():
            kubeconfig = str(kubeconfig_path)

    return K8sHarness(namespace="default", kubeconfig=kubeconfig)


@pytest.fixture(scope="session")
def k8s_test_namespace(
    k8s_harness_base: TestHarness,
    request: pytest.FixtureRequest,
) -> str:
    """Session-scoped K8s namespace for scenario tests.

    Creates a unique namespace at session start, cleans up at session end.
    Returns empty string and skips cleanup if K8s backend not requested.
    """
    backend = request.config.getoption("--backend")
    if backend == "ssh":
        # K8s not requested, yield empty and skip cleanup
        yield ""
        return

    # Generate unique namespace
    session_id = uuid.uuid4().hex[:8]
    namespace = f"styrene-scenarios-{session_id}"

    # Create namespace with labels
    result = subprocess.run(
        [
            "kubectl",
            "create",
            "namespace",
            namespace,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"Failed to create K8s namespace: {result.stderr}")

    # Add labels
    subprocess.run(
        [
            "kubectl",
            "label",
            "namespace",
            namespace,
            "styrened-test=true",
            "created-by=pytest-scenarios",
            "scope=session",
        ],
        capture_output=True,
    )

    print(f"\n[k8s-scenarios] Created namespace: {namespace}")

    yield namespace

    # Cleanup
    print(f"\n[k8s-scenarios] Cleaning up namespace: {namespace}")

    # Uninstall any Helm releases
    helm_result = subprocess.run(
        ["helm", "list", "-n", namespace, "-q"],
        capture_output=True,
        text=True,
    )
    if helm_result.returncode == 0:
        for release in helm_result.stdout.strip().split("\n"):
            if release:
                subprocess.run(
                    ["helm", "uninstall", release, "-n", namespace],
                    capture_output=True,
                )

    # Delete namespace
    subprocess.run(
        ["kubectl", "delete", "namespace", namespace, "--wait=false"],
        capture_output=True,
    )


@pytest.fixture(scope="session")
def k8s_deployed_pods(
    k8s_harness_base: TestHarness,
    k8s_test_namespace: str,
    request: pytest.FixtureRequest,
) -> list[str]:
    """Session-scoped K8s pod deployment.

    Deploys styrened pods at session start for K8s scenario tests.
    Returns empty list for SSH-only runs.
    """
    backend = request.config.getoption("--backend")
    if backend == "ssh":
        # Return empty list - K8s tests will be skipped by harness fixture
        return []

    # Skip if no namespace was created
    if not k8s_test_namespace:
        return []

    from tests.harness.k8s import K8sHarness

    harness = k8s_harness_base
    if not isinstance(harness, K8sHarness):
        # Return empty - K8s tests will be skipped
        return []

    # Validate cluster connection
    result = subprocess.run(
        ["kubectl", "cluster-info"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        print(f"[k8s-scenarios] Cannot connect to K8s cluster: {result.stderr}")
        return []

    # Update harness namespace
    harness.namespace = k8s_test_namespace

    # Deploy stack
    replica_count = request.config.getoption("--k8s-replica-count")
    release_name = f"scenario-{uuid.uuid4().hex[:6]}"

    print(f"\n[k8s-scenarios] Deploying {replica_count} pods in {k8s_test_namespace}...")

    try:
        pods = harness.deploy_hub(
            release_name=f"{release_name}-hub",
            announce_interval=30,
        )
        hub_pod = pods if isinstance(pods, str) else pods[0]

        # Get hub IP for peer connection
        hub_ip = harness.get_pod_ip(hub_pod)
        if not hub_ip:
            # Wait a moment and retry
            time.sleep(5)
            hub_ip = harness.get_pod_ip(hub_pod)

        # Deploy peers connecting to hub
        peer_count = max(1, replica_count - 1)
        peer_pods = harness.deploy_peers(
            release_name=f"{release_name}-peers",
            hub_address=hub_ip,
            count=peer_count,
            announce_interval=30,
        )

        all_pods = [hub_pod] + peer_pods

        # Wait for all pods to be ready
        if not harness.wait_for_ready(all_pods, timeout=120):
            # Collect logs for debugging
            harness.collect_logs(all_pods, output_dir=Path("/tmp") / "styrene-scenario-logs")
            print(f"[k8s-scenarios] Pods not ready after 120s: {all_pods}")
            return []

        print(f"[k8s-scenarios] Deployed pods: {all_pods}")

        # Wait for mesh to stabilize
        time.sleep(10)

        return all_pods

    except Exception as e:
        print(f"[k8s-scenarios] Failed to deploy K8s stack: {e}")
        return []


@pytest.fixture(scope="session")
def k8s_harness(
    k8s_harness_base: TestHarness,
    k8s_test_namespace: str,
    k8s_deployed_pods: list[str],
    request: pytest.FixtureRequest,
) -> TestHarness:
    """K8s harness with deployed pods ready for testing.

    Note: This fixture doesn't skip for SSH-only runs. The skip logic is in
    the parametrized `harness` fixture which selects between backends.
    """
    backend = request.config.getoption("--backend")
    if backend == "ssh":
        # Return the base harness without deployment for SSH-only runs
        # The harness fixture will skip K8s tests appropriately
        return k8s_harness_base

    from tests.harness.k8s import K8sHarness

    harness = k8s_harness_base
    if not isinstance(harness, K8sHarness):
        # Return base harness - will be skipped in harness fixture
        return k8s_harness_base

    # Ensure namespace is set
    harness.namespace = k8s_test_namespace

    # Refresh pod list to ensure we have current state
    harness.refresh_pods()

    return harness


@pytest.fixture(params=["ssh", "k8s"])
def harness(
    request: pytest.FixtureRequest,
    ssh_harness: TestHarness,
    k8s_harness: TestHarness,
    backend: str,
) -> TestHarness:
    """Parametrized fixture that yields each requested backend.

    When --backend=both, tests run twice (once per backend).
    When --backend=ssh or --backend=k8s, only that backend runs.
    """
    harness_type = request.param

    # Skip if not requested
    if backend != "both" and backend != harness_type:
        pytest.skip(f"Backend {harness_type} not requested (--backend={backend})")

    if harness_type == "ssh":
        return ssh_harness
    else:
        return k8s_harness


@pytest.fixture
def test_nodes(harness: TestHarness) -> list[NodeInfo]:
    """Get available test nodes for the current harness.

    Requires at least 2 nodes for pair tests.
    """
    nodes = harness.get_nodes()
    if len(nodes) < 2:
        pytest.skip(f"Need at least 2 nodes, have {len(nodes)}")
    return nodes[:2]  # Return first two for pair tests


@pytest.fixture
def single_node(harness: TestHarness) -> NodeInfo:
    """Get a single test node.

    For tests that only need one node.
    """
    nodes = harness.get_nodes()
    if len(nodes) < 1:
        pytest.skip("Need at least 1 node")
    return nodes[0]


@pytest.fixture
def all_nodes(harness: TestHarness) -> list[NodeInfo]:
    """Get all available test nodes."""
    nodes = harness.get_nodes()
    if len(nodes) < 1:
        pytest.skip("Need at least 1 node")
    return nodes
