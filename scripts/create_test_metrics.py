#!/usr/bin/env python3
"""Generate synthetic test metrics for verification.

Creates test metrics with configurable memory leak rate for validating
the analysis pipeline without running full overnight tests.

Usage:
    # Generate normal metrics (no leak)
    python scripts/create_test_metrics.py --output /tmp/test-metrics/normal

    # Generate metrics with memory leak
    python scripts/create_test_metrics.py --output /tmp/test-metrics/leak --leak-rate 20

    # Generate 8-hour simulation with leak
    python scripts/create_test_metrics.py --duration 28800 --leak-rate 15
"""

import argparse
import json

# Add parent directory to path to import metrics modules
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "tests" / "k8s"))

from metrics import (
    PodMetrics,
    TestRunMetadata,
    TestSnapshot,
    TestSummary,
    calculate_memory_growth_rate,
)


def generate_test_metrics(
    output_dir: Path,
    duration: int = 28800,
    interval: int = 300,
    pod_count: int = 5,
    base_memory: int = 200,
    leak_rate: float = 0,
    base_cpu: int = 100,
) -> None:
    """Generate synthetic test metrics.

    Args:
        output_dir: Output directory for metrics
        duration: Test duration in seconds (default: 8 hours)
        interval: Snapshot interval in seconds (default: 5 min)
        pod_count: Number of pods to simulate
        base_memory: Base memory per pod in MB
        leak_rate: Memory leak rate in MB/hour (0 = no leak)
        base_cpu: Base CPU per pod in millicores
    """
    # Create directory structure
    run_dir = output_dir
    snapshots_dir = run_dir / "snapshots"
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Create metadata
    start_time = time.time()
    metadata = TestRunMetadata(
        run_id=run_dir.name,
        test_name="synthetic_test",
        start_time=start_time,
        pod_count=pod_count,
        snapshot_interval=interval,
    )

    # Write metadata
    with open(run_dir / "metadata.json", "w") as f:
        json.dump(metadata.to_dict(), f, indent=2)

    # Generate snapshots
    snapshot_count = duration // interval
    snapshots = []

    print(f"Generating {snapshot_count} snapshots...")
    print(f"  Duration: {duration}s ({duration/3600:.1f}h)")
    print(f"  Interval: {interval}s")
    print(f"  Pods: {pod_count}")
    print(f"  Base memory: {base_memory} MB/pod")
    print(f"  Leak rate: {leak_rate:.2f} MB/hour")
    print()

    for i in range(snapshot_count):
        elapsed = i * interval
        timestamp = start_time + elapsed

        # Calculate memory with leak
        leak_mb = (leak_rate * elapsed) / 3600  # Convert to MB
        memory_variance = 10  # Random variance in MB

        pod_metrics = []
        total_cpu = 0
        total_memory = 0

        for pod_idx in range(pod_count):
            # Add some variance and leak
            import random

            pod_memory = int(base_memory + leak_mb + random.uniform(-memory_variance, memory_variance))
            pod_cpu = int(base_cpu + random.uniform(-10, 10))

            pod_metric = PodMetrics(
                pod_name=f"test-pod-{pod_idx}",
                timestamp=timestamp,
                cpu_millicores=pod_cpu,
                memory_mb=pod_memory,
                ready=True,
                restart_count=0,
                discovered_peers=pod_count - 1,
            )

            pod_metrics.append(pod_metric)
            total_cpu += pod_cpu
            total_memory += pod_memory

        snapshot = TestSnapshot(
            snapshot_id=f"snapshot_{i:03d}",
            timestamp=timestamp,
            elapsed_seconds=elapsed,
            pod_metrics=pod_metrics,
            total_cpu_millicores=total_cpu,
            total_memory_mb=total_memory,
        )

        # Write snapshot
        snapshot_file = snapshots_dir / f"snapshot_{i:03d}.json"
        with open(snapshot_file, "w") as f:
            json.dump(snapshot.to_dict(), f, indent=2)

        snapshots.append(snapshot)

        if (i + 1) % 12 == 0:  # Progress every hour (12 * 5min)
            elapsed_hours = elapsed / 3600
            print(f"  Progress: {i+1}/{snapshot_count} snapshots ({elapsed_hours:.1f}h)")

    # Update metadata
    metadata.end_time = start_time + duration
    metadata.total_snapshots = len(snapshots)
    with open(run_dir / "metadata.json", "w") as f:
        json.dump(metadata.to_dict(), f, indent=2)

    # Generate summary
    memory_values = [s.total_memory_mb for s in snapshots]
    cpu_values = [s.total_cpu_millicores for s in snapshots]

    growth_rate = calculate_memory_growth_rate(snapshots)

    summary = TestSummary(
        metadata=metadata,
        total_duration_seconds=duration,
        peak_memory_mb=max(memory_values),
        avg_memory_mb=int(sum(memory_values) / len(memory_values)),
        min_memory_mb=min(memory_values),
        peak_cpu_millicores=max(cpu_values),
        avg_cpu_millicores=int(sum(cpu_values) / len(cpu_values)),
        memory_growth_rate=growth_rate,
        success=True,
        snapshot_files=[f"snapshot_{i:03d}.json" for i in range(len(snapshots))],
    )

    # Write summary
    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary.to_dict(), f, indent=2)

    print()
    print(f"✓ Generated {len(snapshots)} snapshots")
    print(f"  Output: {run_dir}")
    print(f"  Calculated growth rate: {growth_rate:.2f} MB/hour")
    print(f"  Expected growth rate: {leak_rate:.2f} MB/hour")
    print()

    if abs(growth_rate - leak_rate) < 5:
        print("✓ Growth rate matches expected value")
    else:
        print(f"⚠️  Growth rate differs from expected (delta: {growth_rate - leak_rate:.2f})")


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic test metrics")

    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("/tmp/synthetic-metrics"),
        help="Output directory (default: /tmp/synthetic-metrics)",
    )

    parser.add_argument(
        "--duration",
        "-d",
        type=int,
        default=28800,
        help="Test duration in seconds (default: 28800 = 8 hours)",
    )

    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=300,
        help="Snapshot interval in seconds (default: 300 = 5 min)",
    )

    parser.add_argument(
        "--pods",
        "-p",
        type=int,
        default=5,
        help="Number of pods (default: 5)",
    )

    parser.add_argument(
        "--leak-rate",
        "-l",
        type=float,
        default=0,
        help="Memory leak rate in MB/hour (default: 0 = no leak)",
    )

    args = parser.parse_args()

    generate_test_metrics(
        output_dir=args.output,
        duration=args.duration,
        interval=args.interval,
        pod_count=args.pods,
        leak_rate=args.leak_rate,
    )


if __name__ == "__main__":
    main()
