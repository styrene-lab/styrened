# Test Metrics Collection

Comprehensive metrics storage pipeline for overnight/long-running K8s tests (4-8+ hours) with time-series data collection, persistent storage, and analysis tooling.

## Overview

**Problem**: Current tests only validate pass/fail. No trending data, no memory leak detection, no performance degradation tracking.

**Solution**: Collect periodic snapshots (every 5 min) of pod metrics (CPU, memory, latency) during long-running tests, store as JSON artifacts in GitHub, provide analysis tools for leak detection and trend analysis.

## Architecture

```
Test → MetricsCollector → JSON Files → /tmp/metrics/ → GitHub Artifact → Analysis Scripts
 ↓         ↓                   ↓              ↓              ↓               ↓
pods   dataclass          time-series     local        (90-day        trend reports
       snapshots          every 5min      storage      retention)     leak detection
```

### Storage Strategy

**During test run**:
- Local filesystem: `/tmp/styrene-test-metrics/{run_id}/`
- Format: JSON (matches existing codebase patterns)
- Structure: One file per snapshot + metadata + summary

**After test run**:
- Primary: GitHub Actions artifacts (already in use)
- Retention: 90 days for nightly/release, 7 days for PRs
- Size: ~200 KB compressed per 8-hour test

## File Structure

```
/tmp/styrene-test-metrics/
└── test_8_hour_stability_1738454321/
    ├── metadata.json              # TestRunMetadata
    ├── summary.json               # TestSummary (written at end)
    └── snapshots/
        ├── snapshot_000.json      # T+0
        ├── snapshot_001.json      # T+5min
        ├── snapshot_002.json      # T+10min
        └── ...                    # T+7h 55min (96 total for 8hr)
```

## Usage

### Running Tests with Metrics

```bash
# 8-hour test with default 5-min snapshots
pytest tests/k8s/scenarios/test_overnight_stability.py::test_8_hour_stability \
    --run-slow -v

# 4-hour test with custom 2-min snapshots
METRICS_INTERVAL=120 pytest tests/k8s/scenarios/test_overnight_stability.py::test_4_hour_sustained_load \
    --run-slow -v

# Disable metrics collection (faster for debugging)
METRICS_ENABLED=false pytest tests/k8s/scenarios/test_overnight_stability.py::test_short_stability_check -v

# 5-minute smoke test (validates metrics collection works)
pytest tests/k8s/scenarios/test_overnight_stability.py::test_short_stability_check -v
```

### Downloading Metrics from CI

```bash
# Download from latest nightly build
./scripts/download_metrics.sh nightly-build latest

# Download from specific run ID
./scripts/download_metrics.sh nightly-build 1234567890

# Downloads to ./metrics-analysis/{workflow}-{run-id}/
```

### Analyzing Metrics

```bash
# Analyze single test run
python scripts/analyze_metrics.py /tmp/styrene-test-metrics/test_8_hour_stability_*/

# Output:
# # Test Metrics Analysis: test_8_hour_stability
#
# **Duration**: 8h 0m
# **Snapshots**: 96
# **Pods**: 5
#
# ## Memory Analysis
# - **Peak**: 1024 MB
# - **Average**: 910 MB
# - **Minimum**: 890 MB
# - **Growth rate**: 2.3 MB/hour
#
# ✓ No memory leak detected
# Growth rate (2.3 MB/hour) within acceptable limits
```

```bash
# Analyze all runs in directory
python scripts/analyze_metrics.py /tmp/styrene-test-metrics/ --all

# Output:
# # All Test Runs (3 total)
#
# Test Name                           | Duration | Avg Memory | Growth Rate | Status
# ------------------------------------|----------|------------|-------------|-------
# test_8_hour_stability               | 8h 0m    | 910 MB     |   2.30 MB/h | ✓
# test_4_hour_sustained_load          | 4h 0m    | 950 MB     |   5.20 MB/h | ✓
# test_2_hour_stability               | 2h 0m    | 920 MB     |   1.50 MB/h | ✓
```

```bash
# Compare two runs
python scripts/analyze_metrics.py --compare \
    metrics-analysis/nightly-2026-02-01/ \
    metrics-analysis/nightly-2026-02-02/

# Output:
# # Test Run Comparison
#
# **Run 1**: nightly-2026-02-01
# **Run 2**: nightly-2026-02-02
#
# ## Memory Comparison
# - **Average memory change**: +15 MB (+1.6%)
#   - Run 1: 910 MB
#   - Run 2: 925 MB
# - **Growth rate change**: +0.50 MB/hour
#   - Run 1: 2.30 MB/hour
#   - Run 2: 2.80 MB/hour
#
# ## Verdict
# ✓ No significant regressions detected
```

```bash
# Generate markdown report
python scripts/analyze_metrics.py /tmp/styrene-test-metrics/test_8_hour/ -o report.md
```

## Memory Leak Detection

The analysis script uses linear regression to detect memory leaks:

1. Extract memory values over time
2. Calculate slope (MB/hour) using linear regression
3. Compare against threshold (10 MB/hour)
4. Report in summary

**Threshold**: >10 MB/hour is considered a potential leak

**Example**:
```
Growth rate: 15.2 MB/hour

⚠️ MEMORY LEAK DETECTED
Growth rate (15.2 MB/hour) exceeds threshold (10 MB/hour)
```

## Environment Variables

```bash
# Adjust snapshot interval (default: 300 seconds = 5 min)
METRICS_INTERVAL=120

# Disable metrics collection
METRICS_ENABLED=false
```

## Pytest Integration

Tests automatically collect metrics via the `metrics_collector` fixture:

```python
@pytest.mark.slow_extended
@pytest.mark.comprehensive
async def test_8_hour_stability(
    k8s_cluster,
    styrened_stack,
    metrics_collector,  # Fixture automatically handles collection
):
    # Deploy pods
    pods = styrened_stack(replica_count=5)

    # Start metrics collection
    await metrics_collector.start(pods)

    # Run test
    await asyncio.sleep(28800)  # 8 hours

    # Fixture automatically stops collection and writes summary
```

## CI Integration

Nightly builds automatically:
1. Run comprehensive tests (including overnight tests if scheduled)
2. Collect metrics in `/tmp/styrene-test-metrics/`
3. Upload to GitHub Actions artifacts with 90-day retention
4. Metrics available for download via `gh` CLI

See `.github/workflows/nightly-build.yml` for implementation.

## Test Verification

Generate synthetic metrics to verify the analysis pipeline:

```bash
# Generate normal metrics (no leak)
python scripts/create_test_metrics.py --output /tmp/test-metrics/normal

# Generate metrics with 20 MB/hour leak
python scripts/create_test_metrics.py --output /tmp/test-metrics/leak --leak-rate 20

# Analyze
python scripts/analyze_metrics.py /tmp/test-metrics/leak/

# Should detect leak
```

## Performance Overhead

**Storage** (8-hour test, 5 pods, 5-min snapshots):
- Snapshots: 96
- Size per snapshot: ~2 KB JSON
- Total: 192 KB uncompressed
- Compressed (gzip -9): ~40 KB

**Memory**: <1 MB (in-memory buffer + metadata)

**CPU**: ~0.03% (100ms collection every 5 minutes)

**Conclusion**: Negligible overhead on test runner.

## Data Format

### snapshot_001.json

```json
{
  "snapshot_id": "snapshot_001",
  "timestamp": 1738454621.5,
  "elapsed_seconds": 300,
  "pod_metrics": [
    {
      "pod_name": "test-abc123-styrened-0",
      "timestamp": 1738454621.5,
      "cpu_millicores": 145,
      "memory_mb": 182,
      "ready": true,
      "restart_count": 0,
      "discovered_peers": 4
    }
  ],
  "total_cpu_millicores": 725,
  "total_memory_mb": 910
}
```

### summary.json

```json
{
  "metadata": {
    "run_id": "test_8_hour_stability_1738454321",
    "test_name": "test_8_hour_stability_no_leaks",
    "start_time": 1738454321.5,
    "end_time": 1738483121.5,
    "total_snapshots": 96
  },
  "total_duration_seconds": 28800,
  "peak_memory_mb": 1024,
  "avg_memory_mb": 910,
  "memory_growth_rate": 2.3,
  "success": true,
  "snapshot_files": ["snapshot_000.json", ...]
}
```

## Troubleshooting

**No snapshots collected**:
- Check `METRICS_ENABLED` is not set to "false"
- Verify `/tmp/styrene-test-metrics/` is writable
- Check test fixture is using `metrics_collector`

**Metrics not uploaded to CI**:
- Check test completed (not interrupted)
- Verify artifact upload step in workflow
- Check artifact retention hasn't expired (90 days)

**Analysis script fails**:
- Verify summary.json exists
- Check snapshots directory has files
- Run with `python -v` for detailed errors

## Future Enhancements

If 90-day retention proves insufficient:

1. **InfluxDB**: For >90 day retention and real-time dashboards
2. **S3**: For indefinite retention
3. **Grafana**: For visualization
4. **Real-time alerting**: On leak detection during test run

All require external infrastructure setup - GitHub artifacts are sufficient for current needs.
