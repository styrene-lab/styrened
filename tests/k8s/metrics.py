"""Metrics data models for K8s test monitoring.

Provides dataclass models for collecting and storing time-series metrics during
long-running tests (4-8+ hours) to enable leak detection, trend analysis, and
performance regression tracking.

Storage strategy:
- Periodic snapshots (every 5 min) written to local filesystem during test run
- JSON format for compatibility with existing codebase patterns
- Uploaded to GitHub Actions artifacts (90-day retention) after test completion
- Analysis scripts consume JSON files for leak detection and trending

Example usage:
    snapshot = TestSnapshot(
        snapshot_id="snapshot_001",
        timestamp=time.time(),
        elapsed_seconds=300,
        pod_metrics=[...],
        total_cpu_millicores=500,
        total_memory_mb=1024,
    )

    with open("snapshot_001.json", "w") as f:
        json.dump(snapshot.to_dict(), f, indent=2)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class PodMetrics:
    """Resource metrics for a single pod at a point in time.

    Attributes:
        pod_name: Full pod name (e.g., "styrene-test-abc123-0")
        timestamp: Unix epoch timestamp when metrics were collected
        cpu_millicores: CPU usage in millicores (e.g., 150 = 0.15 cores)
        memory_mb: Memory usage in megabytes
        ready: Whether pod is in Ready state
        restart_count: Number of pod restarts since creation
        discovered_peers: Number of mesh peers discovered (Reticulum-specific)
        messages_sent: Number of LXMF messages sent (Reticulum-specific)
    """

    pod_name: str
    timestamp: float
    cpu_millicores: int
    memory_mb: int
    ready: bool
    restart_count: int
    discovered_peers: int = 0
    messages_sent: int = 0

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization.

        Returns:
            Dictionary representation of pod metrics
        """
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PodMetrics:
        """Create PodMetrics from dict.

        Args:
            data: Dictionary with pod metrics fields

        Returns:
            PodMetrics instance
        """
        return cls(**data)


@dataclass
class TestSnapshot:
    """Complete test state at a point in time.

    Represents a single snapshot of all pod metrics at a specific moment.
    Used for time-series analysis of resource usage over test duration.

    Attributes:
        snapshot_id: Unique snapshot identifier (e.g., "snapshot_001")
        timestamp: Unix epoch timestamp when snapshot was taken
        elapsed_seconds: Seconds elapsed since test start
        pod_metrics: List of per-pod metrics
        total_cpu_millicores: Sum of CPU usage across all pods
        total_memory_mb: Sum of memory usage across all pods
    """

    snapshot_id: str
    timestamp: float
    elapsed_seconds: float
    pod_metrics: list[PodMetrics]
    total_cpu_millicores: int
    total_memory_mb: int

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization.

        Returns:
            Dictionary representation with nested pod_metrics converted
        """
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "elapsed_seconds": self.elapsed_seconds,
            "pod_metrics": [pm.to_dict() for pm in self.pod_metrics],
            "total_cpu_millicores": self.total_cpu_millicores,
            "total_memory_mb": self.total_memory_mb,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TestSnapshot:
        """Create TestSnapshot from dict.

        Args:
            data: Dictionary with snapshot fields

        Returns:
            TestSnapshot instance
        """
        pod_metrics = [PodMetrics.from_dict(pm) for pm in data["pod_metrics"]]
        return cls(
            snapshot_id=data["snapshot_id"],
            timestamp=data["timestamp"],
            elapsed_seconds=data["elapsed_seconds"],
            pod_metrics=pod_metrics,
            total_cpu_millicores=data["total_cpu_millicores"],
            total_memory_mb=data["total_memory_mb"],
        )


@dataclass
class TestRunMetadata:
    """Metadata describing a test run.

    Attributes:
        run_id: Unique identifier for this test run
        test_name: Name of the pytest test (e.g., "test_8_hour_stability")
        start_time: Unix epoch timestamp when test started
        end_time: Unix epoch timestamp when test ended (0 if still running)
        total_snapshots: Number of snapshots collected
        pod_count: Number of pods in the test
        snapshot_interval: Seconds between snapshots
    """

    run_id: str
    test_name: str
    start_time: float
    end_time: float = 0
    total_snapshots: int = 0
    pod_count: int = 0
    snapshot_interval: int = 300  # 5 minutes default

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TestRunMetadata:
        """Create TestRunMetadata from dict."""
        return cls(**data)


@dataclass
class TestSummary:
    """Summary statistics for a completed test run.

    Generated after test completion by aggregating all snapshots.
    Used for quick analysis without loading all snapshot files.

    Attributes:
        metadata: Test run metadata
        total_duration_seconds: Total test duration
        peak_memory_mb: Highest memory usage observed
        avg_memory_mb: Average memory usage across snapshots
        min_memory_mb: Lowest memory usage observed
        peak_cpu_millicores: Highest CPU usage observed
        avg_cpu_millicores: Average CPU usage across snapshots
        memory_growth_rate: Linear memory growth rate (MB/hour)
        success: Whether test completed successfully
        snapshot_files: List of snapshot filenames
        notes: Optional freeform notes about the test run
    """

    metadata: TestRunMetadata
    total_duration_seconds: float
    peak_memory_mb: int
    avg_memory_mb: int
    min_memory_mb: int
    peak_cpu_millicores: int
    avg_cpu_millicores: int
    memory_growth_rate: float
    success: bool
    snapshot_files: list[str]
    notes: str = ""

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "metadata": self.metadata.to_dict(),
            "total_duration_seconds": self.total_duration_seconds,
            "peak_memory_mb": self.peak_memory_mb,
            "avg_memory_mb": self.avg_memory_mb,
            "min_memory_mb": self.min_memory_mb,
            "peak_cpu_millicores": self.peak_cpu_millicores,
            "avg_cpu_millicores": self.avg_cpu_millicores,
            "memory_growth_rate": self.memory_growth_rate,
            "success": self.success,
            "snapshot_files": self.snapshot_files,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TestSummary:
        """Create TestSummary from dict."""
        metadata = TestRunMetadata.from_dict(data["metadata"])
        return cls(
            metadata=metadata,
            total_duration_seconds=data["total_duration_seconds"],
            peak_memory_mb=data["peak_memory_mb"],
            avg_memory_mb=data["avg_memory_mb"],
            min_memory_mb=data["min_memory_mb"],
            peak_cpu_millicores=data["peak_cpu_millicores"],
            avg_cpu_millicores=data["avg_cpu_millicores"],
            memory_growth_rate=data["memory_growth_rate"],
            success=data["success"],
            snapshot_files=data["snapshot_files"],
            notes=data.get("notes", ""),
        )


def calculate_memory_growth_rate(snapshots: list[TestSnapshot]) -> float:
    """Calculate linear memory growth rate from snapshots.

    Uses simple linear regression to estimate MB/hour growth rate.
    Positive values indicate memory leak, negative values indicate cleanup.

    Args:
        snapshots: List of snapshots in chronological order

    Returns:
        Memory growth rate in MB/hour
    """
    if len(snapshots) < 2:
        return 0.0

    # Extract time (hours) and memory (MB)
    times = [s.elapsed_seconds / 3600 for s in snapshots]
    memory = [s.total_memory_mb for s in snapshots]

    # Simple linear regression: slope = covariance(x,y) / variance(x)
    n = len(times)
    mean_time = sum(times) / n
    mean_memory = sum(memory) / n

    covariance = sum(
        (t - mean_time) * (m - mean_memory) for t, m in zip(times, memory, strict=True)
    )
    variance = sum((t - mean_time) ** 2 for t in times)

    if variance == 0:
        return 0.0

    slope = covariance / variance  # MB/hour
    return round(slope, 2)
