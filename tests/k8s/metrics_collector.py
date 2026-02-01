"""Metrics collector for long-running K8s tests.

Provides background collection of pod metrics with periodic snapshots to disk.
Integrates with existing K8sTestHarness for metric retrieval.

Usage:
    collector = MetricsCollector(
        harness=k8s_cluster,
        run_id="test_8_hour_stability_1738454321",
        test_name="test_8_hour_stability",
    )

    await collector.start(["pod-1", "pod-2", "pod-3"])

    # Metrics collected in background every 5 minutes

    collector.stop()  # Writes summary.json
"""

import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path

from .harness import K8sTestHarness
from .metrics import (
    PodMetrics,
    TestRunMetadata,
    TestSnapshot,
    TestSummary,
    calculate_memory_growth_rate,
)

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collect and persist test metrics over time.

    Runs a background async task that periodically collects pod metrics
    and writes snapshots to disk. Generates summary statistics on stop.

    Attributes:
        harness: K8sTestHarness instance for metrics retrieval
        run_id: Unique identifier for this test run
        test_name: Name of pytest test
        snapshot_interval: Seconds between snapshots
        output_dir: Base directory for metrics storage
    """

    def __init__(
        self,
        harness: K8sTestHarness,
        run_id: str,
        test_name: str,
        snapshot_interval: int = 300,
        output_dir: Path | None = None,
    ):
        """Initialize metrics collector.

        Args:
            harness: K8sTestHarness for metrics retrieval
            run_id: Unique identifier for this test run
            test_name: Name of pytest test
            snapshot_interval: Seconds between snapshots (default: 300 = 5 min)
            output_dir: Base directory for metrics storage (default: /tmp/styrene-test-metrics)
        """
        self.harness = harness
        self.run_id = run_id
        self.test_name = test_name
        self.snapshot_interval = snapshot_interval
        self.output_dir = output_dir or Path("/tmp/styrene-test-metrics")

        # Run directory structure
        self.run_dir = self.output_dir / run_id
        self.snapshots_dir = self.run_dir / "snapshots"

        # State
        self.pods: list[str] = []
        self.start_time: float = 0
        self.snapshot_count: int = 0
        self.snapshots: list[TestSnapshot] = []  # In-memory buffer for summary
        self._running: bool = False
        self._task: asyncio.Task | None = None

        # Metadata
        self.metadata = TestRunMetadata(
            run_id=run_id,
            test_name=test_name,
            start_time=0,  # Set when start() is called
            snapshot_interval=snapshot_interval,
        )

    async def start(self, pods: list[str]) -> None:
        """Start background metrics collection.

        Args:
            pods: List of pod names to monitor
        """
        self.pods = pods
        self.start_time = time.time()
        self.metadata.start_time = self.start_time
        self.metadata.pod_count = len(pods)
        self._running = True

        # Create output directories
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        # Write metadata
        self._write_metadata()

        # Start background task
        self._task = asyncio.create_task(self._snapshot_task())

        logger.info(
            f"Started metrics collection for {len(pods)} pods "
            f"(interval: {self.snapshot_interval}s, output: {self.run_dir})"
        )

    def stop(self) -> None:
        """Stop metrics collection and write summary.

        Cancels background task and generates summary.json with statistics.
        """
        if not self._running:
            return

        self._running = False

        # Cancel background task
        if self._task:
            self._task.cancel()
            self._task = None

        # Update metadata
        self.metadata.end_time = time.time()
        self.metadata.total_snapshots = self.snapshot_count
        self._write_metadata()

        # Write summary
        self._write_summary()

        logger.info(
            f"Stopped metrics collection "
            f"({self.snapshot_count} snapshots, "
            f"duration: {self.metadata.end_time - self.metadata.start_time:.0f}s)"
        )

    async def _snapshot_task(self) -> None:
        """Background task for periodic snapshot collection.

        Runs every snapshot_interval seconds until stopped.
        Catches exceptions to prevent task death.
        """
        while self._running:
            try:
                snapshot = self.collect_snapshot()
                self._write_snapshot(snapshot)

                # Keep in-memory buffer for summary (last 100 snapshots)
                self.snapshots.append(snapshot)
                if len(self.snapshots) > 100:
                    self.snapshots.pop(0)

                await asyncio.sleep(self.snapshot_interval)

            except asyncio.CancelledError:
                logger.info("Metrics collection task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in metrics collection: {e}", exc_info=True)
                await asyncio.sleep(self.snapshot_interval)

    def collect_snapshot(self) -> TestSnapshot:
        """Collect single snapshot of all pod metrics.

        Uses K8sTestHarness methods to retrieve metrics from kubectl.

        Returns:
            TestSnapshot with current pod metrics
        """
        timestamp = time.time()
        elapsed = timestamp - self.start_time

        pod_metrics_list = []
        total_cpu = 0
        total_memory = 0

        for pod in self.pods:
            # Get resource metrics from kubectl top
            metrics = self.harness.get_pod_metrics(pod)
            cpu = metrics["cpu_usage_millicores"]
            memory = metrics["memory_usage_mb"]

            # Get pod status
            ready, restart_count = self._get_pod_status(pod)

            # Get Reticulum-specific metrics (if available)
            discovered_peers = self._get_discovered_peers(pod)

            pod_metric = PodMetrics(
                pod_name=pod,
                timestamp=timestamp,
                cpu_millicores=cpu,
                memory_mb=memory,
                ready=ready,
                restart_count=restart_count,
                discovered_peers=discovered_peers,
                messages_sent=0,  # TODO: Extract from styrened logs if needed
            )

            pod_metrics_list.append(pod_metric)
            total_cpu += cpu
            total_memory += memory

        snapshot = TestSnapshot(
            snapshot_id=f"snapshot_{self.snapshot_count:03d}",
            timestamp=timestamp,
            elapsed_seconds=elapsed,
            pod_metrics=pod_metrics_list,
            total_cpu_millicores=total_cpu,
            total_memory_mb=total_memory,
        )

        self.snapshot_count += 1
        return snapshot

    def _get_pod_status(self, pod: str) -> tuple[bool, int]:
        """Get pod ready status and restart count.

        Args:
            pod: Pod name

        Returns:
            Tuple of (ready, restart_count)
        """
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "pod",
                    pod,
                    "-n",
                    self.harness.namespace,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return (False, 0)

            data = json.loads(result.stdout)

            # Extract ready status
            conditions = data.get("status", {}).get("conditions", [])
            ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)

            # Extract restart count
            containers = data.get("status", {}).get("containerStatuses", [])
            restart_count = sum(c.get("restartCount", 0) for c in containers)

            return (ready, restart_count)

        except Exception as e:
            logger.warning(f"Failed to get pod status for {pod}: {e}")
            return (False, 0)

    def _get_discovered_peers(self, pod: str) -> int:
        """Get number of discovered mesh peers from pod.

        Attempts to query 'styrened devices' command in pod.
        Returns 0 if command fails or pod doesn't support it.

        Args:
            pod: Pod name

        Returns:
            Number of discovered peers
        """
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "exec",
                    pod,
                    "-n",
                    self.harness.namespace,
                    "--",
                    "styrened",
                    "devices",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return 0

            devices = json.loads(result.stdout)
            return len(devices)

        except Exception:
            # Silently fail - not all pods may support this command
            return 0

    def _write_snapshot(self, snapshot: TestSnapshot) -> None:
        """Write snapshot to disk as JSON.

        Args:
            snapshot: TestSnapshot to persist
        """
        snapshot_file = self.snapshots_dir / f"{snapshot.snapshot_id}.json"

        try:
            with open(snapshot_file, "w") as f:
                json.dump(snapshot.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write snapshot {snapshot.snapshot_id}: {e}")

    def _write_metadata(self) -> None:
        """Write test run metadata to disk."""
        metadata_file = self.run_dir / "metadata.json"

        try:
            with open(metadata_file, "w") as f:
                json.dump(self.metadata.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write metadata: {e}")

    def _write_summary(self) -> None:
        """Generate and write summary statistics.

        Aggregates all snapshots to compute statistics and detect memory leaks.
        """
        # Load all snapshots from disk
        all_snapshots = self._load_all_snapshots()

        if not all_snapshots:
            logger.warning("No snapshots to summarize")
            return

        # Calculate statistics
        memory_values = [s.total_memory_mb for s in all_snapshots]
        cpu_values = [s.total_cpu_millicores for s in all_snapshots]

        peak_memory = max(memory_values)
        avg_memory = int(sum(memory_values) / len(memory_values))
        min_memory = min(memory_values)

        peak_cpu = max(cpu_values)
        avg_cpu = int(sum(cpu_values) / len(cpu_values))

        # Calculate memory growth rate
        growth_rate = calculate_memory_growth_rate(all_snapshots)

        # Get snapshot filenames
        snapshot_files = sorted([f.name for f in self.snapshots_dir.glob("snapshot_*.json")])

        # Create summary
        summary = TestSummary(
            metadata=self.metadata,
            total_duration_seconds=self.metadata.end_time - self.metadata.start_time,
            peak_memory_mb=peak_memory,
            avg_memory_mb=avg_memory,
            min_memory_mb=min_memory,
            peak_cpu_millicores=peak_cpu,
            avg_cpu_millicores=avg_cpu,
            memory_growth_rate=growth_rate,
            success=True,  # Assume success if we got here
            snapshot_files=snapshot_files,
            notes="",
        )

        # Write summary
        summary_file = self.run_dir / "summary.json"
        try:
            with open(summary_file, "w") as f:
                json.dump(summary.to_dict(), f, indent=2)

            logger.info(
                f"Summary: {len(all_snapshots)} snapshots, "
                f"avg memory: {avg_memory} MB, "
                f"growth rate: {growth_rate:.2f} MB/hour"
            )

        except Exception as e:
            logger.error(f"Failed to write summary: {e}")

    def _load_all_snapshots(self) -> list[TestSnapshot]:
        """Load all snapshots from disk.

        Returns:
            List of TestSnapshot objects in chronological order
        """
        snapshots = []

        for snapshot_file in sorted(self.snapshots_dir.glob("snapshot_*.json")):
            try:
                with open(snapshot_file) as f:
                    data = json.load(f)
                    snapshot = TestSnapshot.from_dict(data)
                    snapshots.append(snapshot)
            except Exception as e:
                logger.warning(f"Failed to load snapshot {snapshot_file}: {e}")

        return snapshots
