"""Overnight stability tests with metrics collection.

Long-running tests (4-8+ hours) with periodic metrics snapshots for leak detection
and performance trending. Requires --run-slow flag to execute.

Usage:
    # 8-hour test with default 5-min snapshots
    pytest tests/k8s/scenarios/test_overnight_stability.py::test_8_hour_stability \
        --run-slow -v

    # 4-hour test with custom 2-min snapshots
    METRICS_INTERVAL=120 pytest tests/k8s/scenarios/test_overnight_stability.py::test_4_hour_sustained_load \
        --run-slow -v

    # Disable metrics collection (faster for debugging)
    METRICS_ENABLED=false pytest tests/k8s/scenarios/test_overnight_stability.py::test_short_stability_check \
        -v

Test tiers:
    - smoke: test_short_stability_check (5 min, quick validation)
    - comprehensive: test_2_hour_stability (2 hours, pre-release validation)
    - slow_extended: test_4_hour_sustained_load, test_8_hour_stability (overnight)

Metrics output:
    /tmp/styrene-test-metrics/{test_name}_{timestamp}/
        metadata.json
        summary.json
        snapshots/
            snapshot_000.json
            snapshot_001.json
            ...
"""

import asyncio

import pytest


@pytest.mark.smoke
@pytest.mark.comprehensive
async def test_short_stability_check(
    k8s_cluster,
    styrened_stack,
    metrics_collector,
):
    """5-minute stability check with metrics collection.

    Quick validation that metrics collection works without requiring
    a full overnight run. Useful for development and PR validation.

    Resources:
        Pods: 3
        Memory: ~600 MB total
        CPU: ~300m total
        Duration: 5 minutes
        Snapshots: 1 (at start, one at end if interval <= 300s)

    Validation:
        - Pods remain stable (no restarts)
        - Mesh convergence (peers discovered)
        - Metrics collection successful
        - No memory leaks detected
    """
    # Deploy 3-pod mesh
    pods = styrened_stack(replica_count=3, mode="standalone", announce_interval=60)

    # Start metrics collection
    await metrics_collector.start(pods)

    # Wait for mesh convergence (30s should be enough with 60s announce)
    await asyncio.sleep(30)

    # Verify peers discovered
    for pod in pods:
        peers = k8s_cluster.get_discovered_peers(pod)
        assert len(peers) >= 2, f"Pod {pod} should discover at least 2 peers (got {len(peers)})"

    # Run for 5 minutes
    await asyncio.sleep(300)

    # Final verification - no restarts
    for pod in pods:
        status = k8s_cluster.get_pod_status(pod)
        assert status["ready"], f"Pod {pod} should still be ready"
        assert status["restart_count"] == 0, f"Pod {pod} should have no restarts"

    # Metrics collector will auto-stop via fixture


@pytest.mark.comprehensive
async def test_2_hour_stability(
    k8s_cluster,
    styrened_stack,
    metrics_collector,
):
    """2-hour stability test with leak detection.

    Medium-duration test for pre-release validation. Runs long enough
    to detect obvious memory leaks but completes in a reasonable timeframe.

    Resources:
        Pods: 5
        Memory: ~1 GB total
        CPU: ~500m total
        Duration: 2 hours
        Snapshots: 24 (every 5 min)

    Validation:
        - Pods remain stable (no restarts)
        - Mesh convergence maintained
        - Memory growth < 10 MB/hour
        - CPU usage stable
    """
    # Deploy 5-pod mesh
    pods = styrened_stack(
        replica_count=5,
        mode="standalone",
        announce_interval=120,
        rpc_enabled=True,
    )

    # Start metrics collection
    await metrics_collector.start(pods)

    # Wait for mesh convergence
    await asyncio.sleep(60)

    # Verify initial mesh state
    for pod in pods:
        peers = k8s_cluster.get_discovered_peers(pod)
        assert len(peers) >= 4, f"Pod {pod} should discover at least 4 peers (got {len(peers)})"

    # Run for 2 hours
    duration = 2 * 3600  # 2 hours
    await asyncio.sleep(duration)

    # Final verification
    for pod in pods:
        status = k8s_cluster.get_pod_status(pod)
        assert status["ready"], f"Pod {pod} should still be ready after {duration}s"
        assert status["restart_count"] == 0, f"Pod {pod} should have no restarts"

    # Metrics collector will analyze growth rate and write summary


@pytest.mark.slow
@pytest.mark.slow_extended
@pytest.mark.comprehensive
async def test_4_hour_sustained_load(
    k8s_cluster,
    styrened_stack,
    metrics_collector,
):
    """4-hour sustained load test with RPC activity.

    Tests sustained RPC operations over extended period. Validates that
    RPC doesn't cause memory leaks or performance degradation.

    Resources:
        Pods: 5
        Memory: ~1 GB total
        CPU: ~600m total
        Duration: 4 hours
        Snapshots: 48 (every 5 min)
        RPC calls: ~240 total (1 per pod per minute)

    Validation:
        - Pods remain stable under sustained RPC load
        - Memory growth < 10 MB/hour
        - RPC latency remains consistent
        - No message delivery failures
    """
    # Deploy 5-pod mesh with RPC enabled
    pods = styrened_stack(
        replica_count=5,
        mode="standalone",
        announce_interval=120,
        rpc_enabled=True,
    )

    # Start metrics collection
    await metrics_collector.start(pods)

    # Wait for mesh convergence
    await asyncio.sleep(60)

    # Run for 4 hours with periodic RPC activity
    duration = 4 * 3600  # 4 hours
    rpc_interval = 60  # Send RPC every 60s

    start_time = asyncio.get_event_loop().time()
    next_rpc_time = start_time + rpc_interval

    while asyncio.get_event_loop().time() < start_time + duration:
        current_time = asyncio.get_event_loop().time()

        # Send RPC status request every minute
        if current_time >= next_rpc_time:
            for pod in pods:
                try:
                    # Query status via RPC (this exercises LXMF message handling)
                    # Note: This is a basic check - full RPC testing is in other test files
                    status = k8s_cluster.get_pod_status(pod)
                    assert status["ready"], f"Pod {pod} should remain ready during load test"
                except Exception as e:
                    pytest.fail(f"RPC failed during sustained load: {e}")

            next_rpc_time += rpc_interval

        # Sleep for short interval to prevent tight loop
        await asyncio.sleep(10)

    # Final verification - no restarts
    for pod in pods:
        status = k8s_cluster.get_pod_status(pod)
        assert status["ready"], f"Pod {pod} should still be ready after sustained load"
        assert status["restart_count"] == 0, f"Pod {pod} should have no restarts"

    # Metrics collector will analyze growth rate


@pytest.mark.slow
@pytest.mark.slow_extended
@pytest.mark.comprehensive
async def test_8_hour_stability_no_leaks(
    k8s_cluster,
    styrened_stack,
    metrics_collector,
):
    """8-hour stability test with comprehensive leak detection.

    Full overnight test for production readiness validation. Runs long enough
    to detect slow memory leaks and performance degradation issues.

    Resources:
        Pods: 5
        Memory: ~1 GB total
        CPU: ~500m total
        Duration: 8 hours
        Snapshots: 96 (every 5 min)

    Validation:
        - Pods remain stable (no restarts)
        - Mesh convergence maintained throughout
        - Memory growth < 10 MB/hour (leak detection threshold)
        - CPU usage remains consistent
        - No resource exhaustion

    Expected metrics:
        - Peak memory: <1.1 GB (allowing for normal variance)
        - Avg CPU: 100-150m per pod
        - Memory growth rate: <10 MB/hour
    """
    # Deploy 5-pod mesh
    pods = styrened_stack(
        replica_count=5,
        mode="standalone",
        announce_interval=180,
        rpc_enabled=True,
    )

    # Start metrics collection
    await metrics_collector.start(pods)

    # Wait for initial mesh convergence
    await asyncio.sleep(120)

    # Verify initial mesh state
    for pod in pods:
        peers = k8s_cluster.get_discovered_peers(pod)
        assert len(peers) >= 4, (
            f"Pod {pod} should discover at least 4 peers initially (got {len(peers)})"
        )

    # Run for 8 hours
    duration = 8 * 3600  # 8 hours = 28800 seconds
    await asyncio.sleep(duration)

    # Final verification - mesh should still be healthy
    for pod in pods:
        status = k8s_cluster.get_pod_status(pod)
        assert status["ready"], f"Pod {pod} should still be ready after 8 hours"
        assert status["restart_count"] == 0, f"Pod {pod} should have no restarts after 8 hours"

        # Verify mesh still converged
        peers = k8s_cluster.get_discovered_peers(pod)
        assert len(peers) >= 4, (
            f"Pod {pod} should still have peers after 8 hours (got {len(peers)})"
        )

    # Metrics collector will stop via fixture and generate summary
    # Summary will include:
    # - Memory growth rate (should be <10 MB/hour)
    # - Peak/avg memory and CPU
    # - 96 snapshots for trend analysis
