"""Bare-metal metrics collector for styrened fleet testing.

Periodically samples device metrics via SSH and writes snapshots to disk.
Provides summary analysis for memory leak detection and performance tracking.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.harness.ssh import SSHHarness

import logging

logger = logging.getLogger(__name__)


@dataclass
class DeviceSnapshot:
    """Point-in-time metrics for a single device."""

    device: str
    timestamp: str
    rss_kb: int = 0
    cpu_percent: float = 0.0
    daemon_running: bool = False
    discovered_peers: int = 0
    uptime_seconds: int = 0


@dataclass
class FleetSnapshot:
    """Point-in-time metrics for the entire fleet."""

    timestamp: str
    elapsed_seconds: float
    devices: list[DeviceSnapshot] = field(default_factory=list)
    total_rss_kb: int = 0
    total_discovered_peers: int = 0


@dataclass
class MetricsSummary:
    """Summary analysis of a metrics collection run."""

    duration_seconds: float
    snapshot_count: int
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Per-device: peak_rss_kb, avg_rss_kb, peak_cpu, avg_cpu, rss_growth_rate_kb_per_hour


class BareMetalMetricsCollector:
    """Collects metrics from bare-metal fleet via SSH.

    Usage:
        collector = BareMetalMetricsCollector(harness, output_dir=Path("test-results/bare-metal/metrics"))
        collector.start(interval=60)
        # ... run tests ...
        summary = collector.stop()
    """

    def __init__(
        self,
        harness: SSHHarness,
        output_dir: Path | None = None,
        devices: list[str] | None = None,
        device_count_interval: int = 10,
    ):
        self.harness = harness
        self.devices = devices or list(harness.registry.keys())
        self.output_dir = output_dir or Path("test-results/bare-metal/metrics")
        self.device_count_interval = device_count_interval
        self._snapshots: list[FleetSnapshot] = []
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_time: float = 0
        self._snapshot_index: int = 0

    def start(self, interval: float = 60.0) -> None:
        """Start periodic metric collection in background thread."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._snapshots = []
        self._start_time = time.time()
        self._stop_event.clear()

        # Take initial snapshot
        self._collect_snapshot()

        # Start background collection
        self._thread = threading.Thread(
            target=self._collection_loop,
            args=(interval,),
            daemon=True,
            name="bare-metal-metrics",
        )
        self._thread.start()
        logger.info(f"Metrics collection started: interval={interval}s, devices={self.devices}")

    def stop(self) -> MetricsSummary:
        """Stop collection and return summary analysis."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

        # Take final snapshot
        self._collect_snapshot()

        # Write all snapshots
        self._write_snapshots()

        # Generate and write summary
        summary = self._analyze()
        self._write_summary(summary)

        logger.info(f"Metrics collection stopped: {len(self._snapshots)} snapshots, {summary.duration_seconds:.0f}s")
        return summary

    def _collection_loop(self, interval: float) -> None:
        """Background collection loop."""
        while not self._stop_event.wait(timeout=interval):
            try:
                self._collect_snapshot()
            except Exception as e:
                logger.warning(f"Metrics snapshot failed: {e}")

    def _collect_snapshot(self) -> FleetSnapshot:
        """Collect one fleet-wide snapshot."""
        now = datetime.now(UTC)
        elapsed = time.time() - self._start_time
        collect_devices = (self._snapshot_index % self.device_count_interval) == 0

        fleet = FleetSnapshot(
            timestamp=now.isoformat(),
            elapsed_seconds=elapsed,
        )

        for device_name in self.devices:
            device_snap = self._collect_device(
                device_name, now, collect_device_count=collect_devices,
            )
            fleet.devices.append(device_snap)
            fleet.total_rss_kb += device_snap.rss_kb
            fleet.total_discovered_peers += device_snap.discovered_peers

        self._snapshots.append(fleet)
        self._snapshot_index += 1
        return fleet

    def _collect_device(
        self,
        device: str,
        now: datetime,
        collect_device_count: bool = True,
    ) -> DeviceSnapshot:
        """Collect metrics from a single device.

        Args:
            device: Device name.
            now: Current timestamp.
            collect_device_count: If False, skip ``styrened devices --json``
                (expensive) and leave discovered_peers at 0.
        """
        snap = DeviceSnapshot(device=device, timestamp=now.isoformat())

        # Process metrics (RSS and CPU)
        try:
            result = self.harness.run(device, "ps -C styrened -o rss=,pcpu= 2>/dev/null || echo '0 0.0'", timeout=10)
            if result.success:
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    snap.rss_kb = int(parts[0])
                    snap.cpu_percent = float(parts[1])
                    snap.daemon_running = snap.rss_kb > 0
        except Exception:
            pass

        # Device count (discovered peers) — only on selected snapshots
        if snap.daemon_running and collect_device_count:
            try:
                result = self.harness.run_styrened(device, "devices --json", timeout=15)
                if result.success and result.stdout.strip():
                    json_start = result.stdout.find("[")
                    if json_start != -1:
                        devices = json.loads(result.stdout[json_start:])
                        snap.discovered_peers = len(devices)
            except Exception:
                pass

        return snap

    def _write_snapshots(self) -> None:
        """Write snapshots to JSONL file."""
        snapshots_file = self.output_dir / "snapshots.jsonl"
        with open(snapshots_file, "w") as f:
            for snap in self._snapshots:
                json.dump(asdict(snap), f, default=str)
                f.write("\n")

    def _analyze(self) -> MetricsSummary:
        """Analyze collected snapshots."""
        if not self._snapshots:
            return MetricsSummary(duration_seconds=0, snapshot_count=0)

        duration = self._snapshots[-1].elapsed_seconds
        summary = MetricsSummary(
            duration_seconds=duration,
            snapshot_count=len(self._snapshots),
        )

        # Per-device analysis
        for device_name in self.devices:
            rss_values = []
            cpu_values = []
            timestamps = []

            for snap in self._snapshots:
                for d in snap.devices:
                    if d.device == device_name:
                        rss_values.append(d.rss_kb)
                        cpu_values.append(d.cpu_percent)
                        timestamps.append(snap.elapsed_seconds)
                        break

            if not rss_values:
                continue

            # Basic stats
            device_stats: dict[str, Any] = {
                "peak_rss_kb": max(rss_values),
                "avg_rss_kb": sum(rss_values) / len(rss_values),
                "min_rss_kb": min(rss_values),
                "peak_cpu_percent": max(cpu_values),
                "avg_cpu_percent": sum(cpu_values) / len(cpu_values),
                "samples": len(rss_values),
            }

            # Memory growth rate (simple linear regression)
            if len(rss_values) >= 3 and duration > 0:
                n = len(rss_values)
                sum_t = sum(timestamps)
                sum_r = sum(rss_values)
                sum_tr = sum(t * r for t, r in zip(timestamps, rss_values, strict=True))
                sum_tt = sum(t * t for t in timestamps)

                denom = n * sum_tt - sum_t * sum_t
                if denom != 0:
                    slope = (n * sum_tr - sum_t * sum_r) / denom
                    # Convert KB/sec to KB/hour
                    device_stats["rss_growth_rate_kb_per_hour"] = round(slope * 3600, 2)

            summary.devices[device_name] = device_stats

        return summary

    def _write_summary(self, summary: MetricsSummary) -> None:
        """Write summary to JSON file."""
        summary_file = self.output_dir / "summary.json"
        with open(summary_file, "w") as f:
            json.dump(asdict(summary), f, indent=2, default=str)
