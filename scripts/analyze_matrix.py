#!/usr/bin/env python3
"""Analyze test matrix JSON results.

Produces summary reports, trend analysis, and identifies patterns in test failures.

Usage:
    python scripts/analyze_matrix.py test-results/
    python scripts/analyze_matrix.py test-results/matrix_20260202_184711.json
    python scripts/analyze_matrix.py test-results/ --format=markdown
    python scripts/analyze_matrix.py test-results/ --compare
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class ScenarioStats:
    """Statistics for a single scenario across multiple runs."""

    name: str
    category: str
    total_runs: int = 0
    passes: int = 0
    fails: int = 0
    duration_sum: float = 0.0
    duration_min: float = float("inf")
    duration_max: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passes / self.total_runs if self.total_runs > 0 else 0.0

    @property
    def avg_duration(self) -> float:
        return self.duration_sum / self.total_runs if self.total_runs > 0 else 0.0

    def add_result(
        self,
        outcome_matched: bool,
        duration: float | None,
        error: str | None,
    ) -> None:
        self.total_runs += 1
        if outcome_matched:
            self.passes += 1
        else:
            self.fails += 1
        if duration is not None:
            self.duration_sum += duration
            self.duration_min = min(self.duration_min, duration)
            self.duration_max = max(self.duration_max, duration)
        if error and not outcome_matched:
            self.errors.append(error)


@dataclass
class RunSummary:
    """Summary of a single test run."""

    name: str
    started_at: datetime
    completed_at: datetime | None
    total: int
    passed: int
    failed: int
    duration: float  # seconds
    file_path: Path

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 0.0


def load_result_file(path: Path) -> dict[str, Any] | None:
    """Load a single test result JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Could not load {path}: {e}", file=sys.stderr)
        return None


def find_result_files(path: Path) -> list[Path]:
    """Find all test result JSON files in a directory or return single file."""
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.glob("matrix_*.json"), key=lambda p: p.stat().st_mtime)
    return []


def analyze_single_run(data: dict[str, Any], file_path: Path) -> RunSummary:
    """Analyze a single test run."""
    started_at = datetime.fromisoformat(data["started_at"])
    completed_at = (
        datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
    )
    duration = (completed_at - started_at).total_seconds() if completed_at else 0.0

    return RunSummary(
        name=data["name"],
        started_at=started_at,
        completed_at=completed_at,
        total=data["summary"]["total"],
        passed=data["summary"]["passed"],
        failed=data["summary"]["failed"],
        duration=duration,
        file_path=file_path,
    )


def aggregate_scenarios(results: list[dict[str, Any]]) -> dict[str, ScenarioStats]:
    """Aggregate scenario results across multiple runs."""
    stats: dict[str, ScenarioStats] = {}

    for run in results:
        for scenario in run.get("scenarios", []):
            name = scenario["name"]
            if name not in stats:
                stats[name] = ScenarioStats(
                    name=name,
                    category=scenario["category"],
                )

            analysis = scenario.get("analysis", {})
            actual = scenario.get("actual", {})

            stats[name].add_result(
                outcome_matched=analysis.get("outcome_matched", False),
                duration=actual.get("duration"),
                error=actual.get("error"),
            )

    return stats


def format_duration(seconds: float) -> str:
    """Format duration in human-readable form."""
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def print_text_report(
    summaries: list[RunSummary],
    stats: dict[str, ScenarioStats],
) -> None:
    """Print text-format analysis report."""
    print("=" * 70)
    print("TEST MATRIX ANALYSIS REPORT")
    print("=" * 70)
    print()

    # Run History
    print("RUN HISTORY")
    print("-" * 70)
    print(f"{'Date':<20} {'Total':>8} {'Pass':>8} {'Fail':>8} {'Rate':>8} {'Duration':>12}")
    print("-" * 70)

    for summary in summaries:
        date_str = summary.started_at.strftime("%Y-%m-%d %H:%M")
        rate_str = f"{summary.pass_rate * 100:.0f}%"
        print(
            f"{date_str:<20} {summary.total:>8} {summary.passed:>8} "
            f"{summary.failed:>8} {rate_str:>8} {format_duration(summary.duration):>12}"
        )

    print()

    # Scenario Summary
    print("SCENARIO SUMMARY")
    print("-" * 70)
    print(f"{'Scenario':<40} {'Runs':>6} {'Pass':>6} {'Rate':>8} {'Avg Time':>10}")
    print("-" * 70)

    # Group by category
    by_category: dict[str, list[ScenarioStats]] = defaultdict(list)
    for stat in stats.values():
        by_category[stat.category].append(stat)

    for category in sorted(by_category.keys()):
        print(f"\n[{category.upper()}]")
        for stat in sorted(by_category[category], key=lambda s: s.name):
            rate_str = f"{stat.pass_rate * 100:.0f}%"
            avg_time = format_duration(stat.avg_duration) if stat.total_runs > 0 else "N/A"
            # Truncate long names
            name = stat.name[:38] + ".." if len(stat.name) > 40 else stat.name
            print(
                f"  {name:<38} {stat.total_runs:>6} {stat.passes:>6} {rate_str:>8} {avg_time:>10}"
            )

    print()

    # Failure Analysis
    failures = [s for s in stats.values() if s.fails > 0]
    if failures:
        print("FAILURE ANALYSIS")
        print("-" * 70)
        for stat in sorted(failures, key=lambda s: s.fails, reverse=True):
            print(f"\n{stat.name} ({stat.fails} failures)")
            unique_errors = set(stat.errors)
            for error in unique_errors:
                # Truncate long errors
                error_preview = error[:100] + "..." if len(error) > 100 else error
                print(f"  - {error_preview}")
        print()

    # Duration Analysis
    print("DURATION ANALYSIS")
    print("-" * 70)
    slow_scenarios = sorted(stats.values(), key=lambda s: s.avg_duration, reverse=True)[:5]
    print("Slowest scenarios (average):")
    for stat in slow_scenarios:
        if stat.total_runs > 0:
            print(f"  {stat.name}: {format_duration(stat.avg_duration)}")

    print()

    # Flaky Tests (pass rate between 20% and 80%)
    flaky = [s for s in stats.values() if 0.2 < s.pass_rate < 0.8 and s.total_runs >= 2]
    if flaky:
        print("POTENTIALLY FLAKY TESTS")
        print("-" * 70)
        for stat in sorted(flaky, key=lambda s: abs(s.pass_rate - 0.5)):
            print(
                f"  {stat.name}: {stat.pass_rate * 100:.0f}% pass rate ({stat.passes}/{stat.total_runs})"
            )
        print()


def print_markdown_report(
    summaries: list[RunSummary],
    stats: dict[str, ScenarioStats],
) -> None:
    """Print Markdown-format analysis report."""
    print("# Test Matrix Analysis Report")
    print()
    print(f"Generated: {datetime.now().isoformat()}")
    print()

    # Run History
    print("## Run History")
    print()
    print("| Date | Total | Pass | Fail | Rate | Duration |")
    print("|------|-------|------|------|------|----------|")

    for summary in summaries:
        date_str = summary.started_at.strftime("%Y-%m-%d %H:%M")
        rate_str = f"{summary.pass_rate * 100:.0f}%"
        print(
            f"| {date_str} | {summary.total} | {summary.passed} | "
            f"{summary.failed} | {rate_str} | {format_duration(summary.duration)} |"
        )

    print()

    # Scenario Summary by Category
    print("## Scenario Summary")
    print()

    by_category: dict[str, list[ScenarioStats]] = defaultdict(list)
    for stat in stats.values():
        by_category[stat.category].append(stat)

    for category in sorted(by_category.keys()):
        print(f"### {category.title()}")
        print()
        print("| Scenario | Runs | Pass | Rate | Avg Time |")
        print("|----------|------|------|------|----------|")

        for stat in sorted(by_category[category], key=lambda s: s.name):
            rate_str = f"{stat.pass_rate * 100:.0f}%"
            avg_time = format_duration(stat.avg_duration) if stat.total_runs > 0 else "N/A"
            status = "✅" if stat.pass_rate == 1.0 else "❌" if stat.pass_rate == 0 else "⚠️"
            print(
                f"| {status} {stat.name} | {stat.total_runs} | {stat.passes} | "
                f"{rate_str} | {avg_time} |"
            )
        print()

    # Failure Analysis
    failures = [s for s in stats.values() if s.fails > 0]
    if failures:
        print("## Failure Analysis")
        print()
        for stat in sorted(failures, key=lambda s: s.fails, reverse=True):
            print(f"### {stat.name}")
            print()
            print(f"- **Failures**: {stat.fails}/{stat.total_runs}")
            print("- **Errors**:")
            unique_errors = set(stat.errors)
            for error in unique_errors:
                error_preview = error[:200] + "..." if len(error) > 200 else error
                print(f"  - `{error_preview}`")
            print()

    # Flaky Tests
    flaky = [s for s in stats.values() if 0.2 < s.pass_rate < 0.8 and s.total_runs >= 2]
    if flaky:
        print("## Potentially Flaky Tests")
        print()
        print("Tests with pass rate between 20% and 80%:")
        print()
        for stat in sorted(flaky, key=lambda s: abs(s.pass_rate - 0.5)):
            print(
                f"- **{stat.name}**: {stat.pass_rate * 100:.0f}% ({stat.passes}/{stat.total_runs})"
            )
        print()


def compare_runs(summaries: list[RunSummary]) -> None:
    """Compare the two most recent runs."""
    if len(summaries) < 2:
        print("Need at least 2 runs for comparison.")
        return

    prev = summaries[-2]
    curr = summaries[-1]

    print("=" * 70)
    print("RUN COMPARISON")
    print("=" * 70)
    print()
    print(f"Previous: {prev.started_at.strftime('%Y-%m-%d %H:%M')} ({prev.file_path.name})")
    print(f"Current:  {curr.started_at.strftime('%Y-%m-%d %H:%M')} ({curr.file_path.name})")
    print()

    # Summary comparison
    print(f"{'Metric':<20} {'Previous':>12} {'Current':>12} {'Change':>12}")
    print("-" * 56)
    print(f"{'Total':.<20} {prev.total:>12} {curr.total:>12} {curr.total - prev.total:>+12}")
    print(f"{'Passed':.<20} {prev.passed:>12} {curr.passed:>12} {curr.passed - prev.passed:>+12}")
    print(f"{'Failed':.<20} {prev.failed:>12} {curr.failed:>12} {curr.failed - prev.failed:>+12}")

    prev_rate = f"{prev.pass_rate * 100:.1f}%"
    curr_rate = f"{curr.pass_rate * 100:.1f}%"
    rate_diff = (curr.pass_rate - prev.pass_rate) * 100
    print(f"{'Pass Rate':.<20} {prev_rate:>12} {curr_rate:>12} {rate_diff:>+11.1f}%")

    prev_dur = format_duration(prev.duration)
    curr_dur = format_duration(curr.duration)
    dur_diff = curr.duration - prev.duration
    dur_pct = (dur_diff / prev.duration * 100) if prev.duration > 0 else 0
    print(f"{'Duration':.<20} {prev_dur:>12} {curr_dur:>12} {dur_pct:>+11.1f}%")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze test matrix JSON results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s test-results/
    %(prog)s test-results/matrix_20260202_184711.json
    %(prog)s test-results/ --format=markdown
    %(prog)s test-results/ --compare
    %(prog)s test-results/ --json
        """,
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to results directory or single JSON file",
    )
    parser.add_argument(
        "--format",
        choices=["text", "markdown", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="Compare two most recent runs",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=0,
        help="Only analyze the N most recent results (0 = all)",
    )

    args = parser.parse_args()

    # Find result files
    files = find_result_files(args.path)
    if not files:
        print(f"No result files found in {args.path}", file=sys.stderr)
        return 1

    print(f"Found {len(files)} result file(s)", file=sys.stderr)

    # Limit to latest N if requested
    if args.latest > 0:
        files = files[-args.latest :]

    # Load all results
    results: list[dict[str, Any]] = []
    summaries: list[RunSummary] = []

    for file_path in files:
        data = load_result_file(file_path)
        if data:
            results.append(data)
            summaries.append(analyze_single_run(data, file_path))

    if not results:
        print("No valid results to analyze", file=sys.stderr)
        return 1

    # Sort by date
    summaries.sort(key=lambda s: s.started_at)

    # Aggregate scenario stats
    stats = aggregate_scenarios(results)

    # Output
    if args.compare:
        compare_runs(summaries)
    elif args.format == "json":
        output = {
            "generated_at": datetime.now().isoformat(),
            "runs": [
                {
                    "name": s.name,
                    "started_at": s.started_at.isoformat(),
                    "total": s.total,
                    "passed": s.passed,
                    "failed": s.failed,
                    "pass_rate": s.pass_rate,
                    "duration": s.duration,
                    "file": str(s.file_path),
                }
                for s in summaries
            ],
            "scenarios": {
                name: {
                    "category": stat.category,
                    "total_runs": stat.total_runs,
                    "passes": stat.passes,
                    "fails": stat.fails,
                    "pass_rate": stat.pass_rate,
                    "avg_duration": stat.avg_duration,
                    "duration_min": stat.duration_min
                    if stat.duration_min != float("inf")
                    else None,
                    "duration_max": stat.duration_max,
                    "errors": list(set(stat.errors)),
                }
                for name, stat in stats.items()
            },
        }
        print(json.dumps(output, indent=2))
    elif args.format == "markdown":
        print_markdown_report(summaries, stats)
    else:
        print_text_report(summaries, stats)

    return 0


if __name__ == "__main__":
    sys.exit(main())
