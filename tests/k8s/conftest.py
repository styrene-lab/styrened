"""Pytest configuration and fixtures for styrened k8s tests."""

import os
import uuid
from pathlib import Path
from typing import Callable, List, Optional

import pytest

from .harness import K8sTestHarness


@pytest.fixture(scope="session")
def worker_id(request) -> str:
    """Get the current xdist worker ID.

    Returns 'master' if not running in parallel, otherwise 'gw0', 'gw1', etc.
    """
    return getattr(request.config, "workerinput", {}).get("workerid", "master")


@pytest.fixture(scope="session")
def k8s_cluster(worker_id) -> K8sTestHarness:
    """Session-level fixture for k8s cluster connection.

    Auto-detects local (kind/k3d) or cloud k8s based on current context.
    Validates connection before proceeding with tests.
    """
    # Check for kubeconfig
    kubeconfig = os.environ.get("KUBECONFIG")
    if not kubeconfig:
        kubeconfig = Path.home() / ".kube" / "config"
        if not kubeconfig.exists():
            pytest.skip("No kubeconfig found - k8s tests require kubernetes cluster")

    # Create harness (will detect cluster type)
    harness = K8sTestHarness(namespace="default", kubeconfig=str(kubeconfig))

    # Validate connection
    try:
        import subprocess

        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            pytest.skip(f"Cannot connect to k8s cluster: {result.stderr}")
    except Exception as e:
        pytest.skip(f"K8s cluster validation failed: {e}")

    print(f"\n[k8s-tests:{worker_id}] Connected to {harness.cluster_type} cluster")

    return harness


@pytest.fixture(scope="session")
def long_running_daemon(k8s_cluster: K8sTestHarness, worker_id: str):
    """Session-scoped fixture for long-running daemon that persists across tests.

    Useful for tests that need a persistent styrened daemon for multiple test cases.
    The daemon is shared across all tests in the same worker session.

    Usage:
        @pytest.mark.parametrize("test_case", ["case1", "case2", "case3"])
        def test_with_daemon(long_running_daemon, test_case):
            pods, namespace = long_running_daemon
            # Run test against persistent daemon
            # All test cases share the same daemon instance

    Returns:
        tuple: (pod_names, namespace)
    """
    import subprocess

    # Create worker-specific namespace for the session daemon
    session_id = uuid.uuid4().hex[:8]
    if worker_id == "master":
        namespace = f"styrene-daemon-{session_id}"
    else:
        worker_num = worker_id.replace("gw", "")
        namespace = f"styrene-daemon-w{worker_num}-{session_id}"

    # Create namespace
    subprocess.run(
        ["kubectl", "create", "namespace", namespace],
        check=True,
        capture_output=True,
    )

    print(f"\n[k8s-tests:{worker_id}] Created session daemon namespace: {namespace}")

    # Update harness namespace
    original_namespace = k8s_cluster.namespace
    k8s_cluster.namespace = namespace

    # Deploy long-running daemon stack
    release_name = f"daemon-{worker_id}-{session_id}"
    pods = k8s_cluster.deploy_stack(
        release_name=release_name,
        replica_count=3,
        mode="standalone",
        transport_enabled=False,
        announce_interval=300,
        rpc_enabled=True,
    )

    # Wait for daemon pods to be ready
    if not k8s_cluster.wait_for_ready(pods, timeout=120):
        # Collect logs for debugging
        k8s_cluster.collect_logs(pods, output_dir=Path("/tmp") / "styrene-daemon-logs")
        pytest.fail(f"Daemon pods not ready after 120s: {pods}")

    print(f"\n[k8s-tests:{worker_id}] Session daemon ready: {pods}")

    yield (pods, namespace)

    # Cleanup - delete namespace and all resources
    print(f"\n[k8s-tests:{worker_id}] Cleaning up session daemon: {namespace}")

    k8s_cluster.cleanup(release_name)
    subprocess.run(
        ["kubectl", "delete", "namespace", namespace, "--wait=false"],
        capture_output=True,
    )

    # Restore original namespace
    k8s_cluster.namespace = original_namespace


@pytest.fixture
def test_namespace(k8s_cluster: K8sTestHarness, request) -> str:
    """Function-level fixture providing isolated test namespace.

    Creates unique namespace per test, cleans up after test completes.
    Worker-aware: includes worker_id in namespace to prevent conflicts.
    """
    import subprocess

    # Get worker ID from pytest-xdist (if running in parallel)
    worker_id = getattr(request.config, "workerinput", {}).get("workerid", "master")

    # Generate unique namespace with worker ID to prevent conflicts
    test_id = uuid.uuid4().hex[:8]
    if worker_id == "master":
        namespace = f"styrene-test-{test_id}"
    else:
        # worker_id format: gw0, gw1, gw2, etc.
        worker_num = worker_id.replace("gw", "")
        namespace = f"styrene-test-w{worker_num}-{test_id}"

    # Create namespace
    subprocess.run(
        ["kubectl", "create", "namespace", namespace],
        check=True,
        capture_output=True,
    )

    print(f"\n[k8s-tests:{worker_id}] Created namespace: {namespace}")

    # Update harness namespace
    original_namespace = k8s_cluster.namespace
    k8s_cluster.namespace = namespace

    yield namespace

    # Cleanup - delete namespace (cascades to all resources)
    print(f"\n[k8s-tests:{worker_id}] Cleaning up namespace: {namespace}")

    subprocess.run(
        ["kubectl", "delete", "namespace", namespace, "--wait=false"],
        capture_output=True,
    )

    # Restore original namespace
    k8s_cluster.namespace = original_namespace


@pytest.fixture
def styrened_stack(
    k8s_cluster: K8sTestHarness, test_namespace: str
) -> Callable[..., List[str]]:
    """Function-level fixture providing styrened stack deployment.

    Returns a callable that deploys a stack and returns pod names.
    Automatically cleans up on test completion.

    Usage:
        def test_example(styrened_stack):
            pods = styrened_stack(replica_count=3, mode="standalone")
            # ... test logic ...
    """
    deployed_releases = []

    def _deploy(
        replica_count: int = 3,
        mode: str = "standalone",
        transport_enabled: bool = False,
        announce_interval: int = 300,
        rpc_enabled: bool = True,
        release_name: Optional[str] = None,
        **kwargs,
    ) -> List[str]:
        """Deploy styrened stack.

        Args:
            replica_count: Number of pods
            mode: Deployment mode
            transport_enabled: Enable RNS transport
            announce_interval: Announce interval
            rpc_enabled: Enable RPC
            release_name: Helm release name (auto-generated if None)
            **kwargs: Additional parameters for deploy_stack()

        Returns:
            List of pod names
        """
        if release_name is None:
            release_name = f"test-{uuid.uuid4().hex[:6]}"

        pods = k8s_cluster.deploy_stack(
            release_name=release_name,
            replica_count=replica_count,
            mode=mode,
            transport_enabled=transport_enabled,
            announce_interval=announce_interval,
            rpc_enabled=rpc_enabled,
            **kwargs,
        )

        # Wait for pods to be ready
        if not k8s_cluster.wait_for_ready(pods, timeout=120):
            # Collect logs for debugging
            k8s_cluster.collect_logs(
                pods, output_dir=Path("/tmp") / "styrene-test-logs"
            )
            pytest.fail(f"Pods not ready after 120s: {pods}")

        deployed_releases.append(release_name)
        return pods

    yield _deploy

    # Cleanup all deployed releases
    for release in deployed_releases:
        print(f"\n[k8s-tests] Cleaning up release: {release}")
        k8s_cluster.cleanup(release)


@pytest.fixture(scope="session", autouse=True)
def check_docker_image(k8s_cluster: K8sTestHarness):
    """Session-level fixture to check if styrened-test image exists.

    For local k8s (kind/k3d), reminds user to load image.
    """
    if k8s_cluster.cluster_type in ["kind", "k3d"]:
        print("\n" + "=" * 70)
        print("LOCAL K8S DETECTED - Ensure styrened-test:latest image is loaded")
        print("=" * 70)
        print("\nFor kind:")
        print("  kind load docker-image styrened-test:latest --name <cluster-name>")
        print("\nFor k3d:")
        print("  k3d image import styrened-test:latest -c <cluster-name>")
        print("\nSkip this if image is already loaded.")
        print("=" * 70 + "\n")


# Pytest configuration
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (load/scaling tests)",
    )
    config.addinivalue_line(
        "markers",
        "requires_metrics: requires metrics-server (for resource usage tests)",
    )
    config.addinivalue_line(
        "markers",
        "smoke: marks tests as smoke tests (fast validation, <2min)",
    )
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests (moderate complexity, <10min)",
    )
    config.addinivalue_line(
        "markers",
        "comprehensive: marks tests as comprehensive tests (deep validation, <30min)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip slow tests unless --run-slow flag provided."""
    if not config.getoption("--run-slow", default=False):
        skip_slow = pytest.mark.skip(reason="Slow test (use --run-slow to run)")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)


def pytest_addoption(parser):
    """Add custom CLI options."""
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests (load and scaling tests)",
    )
