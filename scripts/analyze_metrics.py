#!/usr/bin/env python3
"""Analyze test metrics for leak detection and trending.

Reads metrics JSON files from test runs and generates analysis reports.
Detects memory leaks, identifies performance regressions, and creates
markdown reports for review.

Usage:
    # Analyze single test run
    python scripts/analyze_metrics.py /tmp/styrene-test-metrics/test_8_hour_stability_1738454321/

    # Compare two test runs
    python scripts/analyze_metrics.py --compare \\
        /tmp/styrene-test-metrics/run1/ \\
        /tmp/styrene-test-metrics/run2/

    # Generate markdown report
    python scripts/analyze_metrics.py /tmp/styrene-test-metrics/test_8_hour/ --output report.md

    # Analyze all runs in directory
    python scripts/analyze_metrics.py /tmp/styrene-test-metrics/ --all
"""

import argparse
import json
import sys
from pathlib import Path


def load_summary(run_dir: Path) -> dict | None:
    """Load summary.json from test run directory.

    Args:
        run_dir: Path to test run directory

    Returns:
        Summary dict or None if not found
    """
    summary_file = run_dir / "summary.json"
    if not summary_file.exists():
        return None

    with open(summary_file) as f:
        return json.load(f)


def load_snapshots(run_dir: Path) -> list[dict]:
    """Load all snapshot files from test run.

    Args:
        run_dir: Path to test run directory

    Returns:
        List of snapshot dicts in chronological order
    """
    snapshots_dir = run_dir / "snapshots"
    if not snapshots_dir.exists():
        return []

    snapshots = []
    for snapshot_file in sorted(snapshots_dir.glob("snapshot_*.json")):
        with open(snapshot_file) as f:
            snapshots.append(json.load(f))

    return snapshots


def detect_memory_leak(snapshots: list[dict], threshold: float = 10.0) -> tuple[bool, float]:
    """Detect linear memory growth using regression.

    Args:
        snapshots: List of snapshot dicts
        threshold: MB/hour threshold for leak detection (default: 10)

    Returns:
        Tuple of (is_leak, growth_rate_mb_per_hour)
    """
    if len(snapshots) < 2:
        return (False, 0.0)

    # Extract time (hours) and memory (MB)
    times = [s["elapsed_seconds"] / 3600 for s in snapshots]
    memory = [s["total_memory_mb"] for s in snapshots]

    # Simple linear regression: slope = covariance(x,y) / variance(x)
    n = len(times)
    mean_time = sum(times) / n
    mean_memory = sum(memory) / n

    covariance = sum((t - mean_time) * (m - mean_memory) for t, m in zip(times, memory, strict=True))
    variance = sum((t - mean_time) ** 2 for t in times)

    if variance == 0:
        return (False, 0.0)

    slope = covariance / variance  # MB/hour
    is_leak = slope > threshold

    return (is_leak, round(slope, 2))


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "8h 15m")
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)

    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def analyze_single_run(run_dir: Path, output_file: Path | None = None) -> None:
    """Analyze single test run and generate report.

    Args:
        run_dir: Path to test run directory
        output_file: Optional path to write markdown report
    """
    summary = load_summary(run_dir)
    if not summary:
        print(f"Error: No summary.json found in {run_dir}")
        sys.exit(1)

    snapshots = load_snapshots(run_dir)
    if not snapshots:
        print(f"Error: No snapshots found in {run_dir}")
        sys.exit(1)

    # Extract metadata
    metadata = summary["metadata"]
    test_name = metadata["test_name"]
    duration = summary["total_duration_seconds"]
    snapshot_count = len(snapshots)

    # Memory leak detection
    is_leak, growth_rate = detect_memory_leak(snapshots)

    # Generate report
    lines = []
    lines.append(f"# Test Metrics Analysis: {test_name}")
    lines.append("")
    lines.append(f"**Duration**: {format_duration(duration)}")
    lines.append(f"**Snapshots**: {snapshot_count}")
    lines.append(f"**Pods**: {metadata['pod_count']}")
    lines.append("")

    lines.append("## Memory Analysis")
    lines.append("")
    lines.append(f"- **Peak**: {summary['peak_memory_mb']} MB")
    lines.append(f"- **Average**: {summary['avg_memory_mb']} MB")
    lines.append(f"- **Minimum**: {summary['min_memory_mb']} MB")
    lines.append(f"- **Growth rate**: {growth_rate} MB/hour")
    lines.append("")

    if is_leak:
        lines.append("⚠️ **MEMORY LEAK DETECTED**")
        lines.append(f"Growth rate ({growth_rate} MB/hour) exceeds threshold (10 MB/hour)")
    else:
        lines.append("✓ **No memory leak detected**")
        lines.append(f"Growth rate ({growth_rate} MB/hour) within acceptable limits")
    lines.append("")

    lines.append("## CPU Analysis")
    lines.append("")
    lines.append(f"- **Peak**: {summary['peak_cpu_millicores']}m total")
    lines.append(f"- **Average**: {summary['avg_cpu_millicores']}m total")
    lines.append(f"- **Per pod (avg)**: {summary['avg_cpu_millicores'] // metadata['pod_count']}m")
    lines.append("")

    lines.append("## Stability")
    lines.append("")
    lines.append(f"- **Test result**: {'✓ PASSED' if summary['success'] else '✗ FAILED'}")
    lines.append("")

    # Memory over time chart (text-based)
    lines.append("## Memory Trend")
    lines.append("")
    lines.append("```")
    lines.append("Time (h) | Memory (MB)")
    lines.append("---------|------------")

    for i, snapshot in enumerate(snapshots):
        if i % 6 == 0:  # Show every 30 min (6 snapshots at 5-min intervals)
            time_hours = snapshot["elapsed_seconds"] / 3600
            memory_mb = snapshot["total_memory_mb"]
            lines.append(f"{time_hours:8.1f} | {memory_mb:4d}")

    lines.append("```")
    lines.append("")

    # Output report
    report = "\n".join(lines)

    if output_file:
        with open(output_file, "w") as f:
            f.write(report)
        print(f"Report written to {output_file}")
    else:
        print(report)


def compare_runs(run1_dir: Path, run2_dir: Path, output_file: Path | None = None) -> None:
    """Compare two test runs and generate comparison report.

    Args:
        run1_dir: Path to first test run directory
        run2_dir: Path to second test run directory
        output_file: Optional path to write markdown report
    """
    summary1 = load_summary(run1_dir)
    summary2 = load_summary(run2_dir)

    if not summary1 or not summary2:
        print("Error: Could not load summaries from both runs")
        sys.exit(1)

    # Extract metrics
    mem1_avg = summary1["avg_memory_mb"]
    mem2_avg = summary2["avg_memory_mb"]
    mem_delta = mem2_avg - mem1_avg
    mem_pct = (mem_delta / mem1_avg) * 100 if mem1_avg > 0 else 0

    cpu1_avg = summary1["avg_cpu_millicores"]
    cpu2_avg = summary2["avg_cpu_millicores"]
    cpu_delta = cpu2_avg - cpu1_avg
    cpu_pct = (cpu_delta / cpu1_avg) * 100 if cpu1_avg > 0 else 0

    growth1 = summary1["memory_growth_rate"]
    growth2 = summary2["memory_growth_rate"]
    growth_delta = growth2 - growth1

    # Generate report
    lines = []
    lines.append("# Test Run Comparison")
    lines.append("")
    lines.append(f"**Run 1**: {run1_dir.name}")
    lines.append(f"**Run 2**: {run2_dir.name}")
    lines.append("")

    lines.append("## Memory Comparison")
    lines.append("")
    lines.append(f"- **Average memory change**: {mem_delta:+d} MB ({mem_pct:+.1f}%)")
    lines.append(f"  - Run 1: {mem1_avg} MB")
    lines.append(f"  - Run 2: {mem2_avg} MB")
    lines.append("")
    lines.append(f"- **Growth rate change**: {growth_delta:+.2f} MB/hour")
    lines.append(f"  - Run 1: {growth1:.2f} MB/hour")
    lines.append(f"  - Run 2: {growth2:.2f} MB/hour")
    lines.append("")

    lines.append("## CPU Comparison")
    lines.append("")
    lines.append(f"- **Average CPU change**: {cpu_delta:+d}m ({cpu_pct:+.1f}%)")
    lines.append(f"  - Run 1: {cpu1_avg}m")
    lines.append(f"  - Run 2: {cpu2_avg}m")
    lines.append("")

    # Verdict
    lines.append("## Verdict")
    lines.append("")

    issues = []
    if abs(mem_pct) > 10:
        issues.append(f"Memory changed by {mem_pct:+.1f}% (significant)")
    if abs(cpu_pct) > 10:
        issues.append(f"CPU changed by {cpu_pct:+.1f}% (significant)")
    if growth_delta > 5:
        issues.append(f"Memory leak worsened by {growth_delta:+.2f} MB/hour")

    if issues:
        lines.append("⚠️ **Issues detected**:")
        for issue in issues:
            lines.append(f"- {issue}")
    else:
        lines.append("✓ **No significant regressions detected**")

    lines.append("")

    # Output report
    report = "\n".join(lines)

    if output_file:
        with open(output_file, "w") as f:
            f.write(report)
        print(f"Comparison report written to {output_file}")
    else:
        print(report)


def analyze_all_runs(base_dir: Path) -> None:
    """Analyze all test runs in directory.

    Args:
        base_dir: Path to directory containing test run subdirectories
    """
    # Find all run directories (contain metadata.json)
    run_dirs = []
    for item in base_dir.iterdir():
        if item.is_dir() and (item / "metadata.json").exists():
            run_dirs.append(item)

    if not run_dirs:
        print(f"No test runs found in {base_dir}")
        sys.exit(1)

    run_dirs.sort()

    print(f"# All Test Runs ({len(run_dirs)} total)")
    print("")
    print("Test Name | Duration | Avg Memory | Growth Rate | Status")
    print("----------|----------|------------|-------------|-------")

    for run_dir in run_dirs:
        summary = load_summary(run_dir)
        if not summary:
            continue

        metadata = summary["metadata"]
        test_name = metadata["test_name"][:40]  # Truncate long names
        duration = format_duration(summary["total_duration_seconds"])
        avg_mem = summary["avg_memory_mb"]
        growth = summary["memory_growth_rate"]
        success = "✓" if summary["success"] else "✗"

        leak_indicator = "⚠️" if growth > 10 else ""

        print(f"{test_name:40s} | {duration:8s} | {avg_mem:4d} MB | {growth:6.2f} MB/h {leak_indicator} | {success}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze styrened test metrics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "run_dir",
        type=Path,
        help="Path to test run directory or base directory (with --all)",
    )

    parser.add_argument(
        "--compare",
        type=Path,
        metavar="RUN2_DIR",
        help="Compare with another test run",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Write report to file instead of stdout",
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Analyze all test runs in directory",
    )

    args = parser.parse_args()

    if not args.run_dir.exists():
        print(f"Error: Directory not found: {args.run_dir}")
        sys.exit(1)

    # Dispatch to appropriate handler
    if args.all:
        analyze_all_runs(args.run_dir)
    elif args.compare:
        compare_runs(args.run_dir, args.compare, args.output)
    else:
        analyze_single_run(args.run_dir, args.output)


if __name__ == "__main__":
    main()
