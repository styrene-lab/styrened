"""Pytest configuration and fixtures for styrened k8s tests."""

import os
import time
import uuid
from collections.abc import Callable
from datetime import UTC
from pathlib import Path

import pytest

from .harness import K8sTestHarness
from .metrics_collector import MetricsCollector


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


@pytest.fixture(scope="session", autouse=True)
def cleanup_orphaned_namespaces(k8s_cluster: K8sTestHarness):
    """Clean up orphaned test namespaces from previous runs before starting tests.

    This prevents cluster pollution from interrupted test runs or cleanup failures.
    Removes all namespaces with label styrened-test=true that are older than 10 minutes.
    """
    import json
    import subprocess
    from datetime import datetime, timedelta

    # List all namespaces with our test label
    result = subprocess.run(
        ["kubectl", "get", "namespaces", "-l", "styrened-test=true", "-o", "json"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 and result.stdout.strip():
        try:
            data = json.loads(result.stdout)
            orphaned = []
            now = datetime.now(UTC)

            for ns in data.get("items", []):
                name = ns["metadata"]["name"]
                created_str = ns["metadata"]["creationTimestamp"]

                # Parse creation time (ISO 8601 format)
                created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                age = now - created

                # Consider namespace orphaned if older than 10 minutes
                if age > timedelta(minutes=10):
                    orphaned.append((name, age))

            if orphaned:
                print(f"\n⚠️  Found {len(orphaned)} orphaned test namespace(s) from previous runs:")
                for name, age in orphaned:
                    age_min = int(age.total_seconds() / 60)
                    print(f"   • {name} (age: {age_min}m)")

                print("\n🧹 Cleaning up orphaned namespaces...")
                for name, _ in orphaned:
                    # Clean up Helm releases first
                    helm_result = subprocess.run(
                        ["helm", "list", "-n", name, "-q"],
                        capture_output=True,
                        text=True,
                    )
                    if helm_result.returncode == 0:
                        for release in helm_result.stdout.strip().split("\n"):
                            if release:
                                print(f"   Uninstalling Helm release: {release}")
                                subprocess.run(
                                    ["helm", "uninstall", release, "-n", name],
                                    capture_output=True,
                                )

                    # Delete namespace
                    print(f"   Deleting namespace: {name}")
                    del_result = subprocess.run(
                        ["kubectl", "delete", "namespace", name, "--wait=false"],
                        capture_output=True,
                        text=True,
                    )
                    if del_result.returncode != 0:
                        print(f"   ⚠️  Warning: Failed to delete {name}: {del_result.stderr}")

                print("✓ Cleanup complete\n")

        except (json.JSONDecodeError, KeyError) as e:
            print(f"⚠️  Warning: Could not parse namespace list: {e}")

    yield


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

    # Create namespace with labels for tracking
    subprocess.run(
        [
            "kubectl",
            "create",
            "namespace",
            namespace,
            "--labels",
            f"styrened-test=true,created-by=pytest,worker={worker_id},scope=session",
        ],
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
    result = subprocess.run(
        ["kubectl", "delete", "namespace", namespace, "--wait=false"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"⚠️  Cleanup warning: Failed to delete namespace {namespace}: {result.stderr}")

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
    # Add labels for tracking (separate command for compatibility)
    subprocess.run(
        [
            "kubectl",
            "label",
            "namespace",
            namespace,
            "styrened-test=true",
            f"created-by=pytest",
            f"worker={worker_id}",
            "scope=function",
        ],
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

    result = subprocess.run(
        ["kubectl", "delete", "namespace", namespace, "--wait=false"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"⚠️  Cleanup warning: Failed to delete namespace {namespace}: {result.stderr}")

    # Restore original namespace
    k8s_cluster.namespace = original_namespace


@pytest.fixture
def styrened_stack(k8s_cluster: K8sTestHarness, test_namespace: str) -> Callable[..., list[str]]:
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
        release_name: str | None = None,
        **kwargs,
    ) -> list[str]:
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
            k8s_cluster.collect_logs(pods, output_dir=Path("/tmp") / "styrene-test-logs")
            pytest.fail(f"Pods not ready after 120s: {pods}")

        deployed_releases.append(release_name)
        return pods

    yield _deploy

    # Cleanup all deployed releases
    for release in deployed_releases:
        print(f"\n[k8s-tests] Cleaning up release: {release}")
        k8s_cluster.cleanup(release)


@pytest.fixture
async def metrics_collector(k8s_cluster: K8sTestHarness, request) -> MetricsCollector:
    """Function-level fixture for automatic metrics collection.

    Collects periodic snapshots (default: 5 min) of pod metrics during test run.
    Automatically stops collection and writes summary on test completion.

    Environment variables:
        METRICS_INTERVAL: Seconds between snapshots (default: 300 = 5 min)
        METRICS_ENABLED: Set to "false" to disable collection (default: enabled)

    Usage:
        async def test_overnight(metrics_collector, styrened_stack):
            pods = styrened_stack(replica_count=5)
            await metrics_collector.start(pods)
            # Metrics collected automatically in background
            await asyncio.sleep(28800)  # 8 hours
            # Fixture automatically stops and writes summary

    Returns:
        MetricsCollector instance (not yet started)
    """
    # Check if metrics collection is disabled
    if os.getenv("METRICS_ENABLED", "true").lower() == "false":
        # Return None-like collector that does nothing
        class NoOpCollector:
            async def start(self, pods):
                pass

            def stop(self):
                pass

        yield NoOpCollector()
        return

    # Generate unique run ID
    test_name = request.node.name
    run_id = f"{test_name}_{int(time.time())}"

    # Get snapshot interval from environment
    snapshot_interval = int(os.getenv("METRICS_INTERVAL", "300"))

    # Create collector
    collector = MetricsCollector(
        harness=k8s_cluster,
        run_id=run_id,
        test_name=test_name,
        snapshot_interval=snapshot_interval,
    )

    yield collector

    # Automatic cleanup on test completion
    if collector and hasattr(collector, "stop"):
        collector.stop()


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
        "slow: marks tests as slow (load/scaling tests, >10min)",
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
    config.addinivalue_line(
        "markers",
        "propagation: LXMF propagation and multi-hop routing tests",
    )
    config.addinivalue_line(
        "markers",
        "resilience: failover and recovery tests",
    )
    config.addinivalue_line(
        "markers",
        "convergence: mesh discovery and convergence tests",
    )
    config.addinivalue_line(
        "markers",
        "slow_extended: marks tests as very slow (overnight tests, 4-8+ hours)",
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
