# Styrened K8s Testing Guide

Comprehensive guide for test tier strategy, marker usage, and best practices for the styrened Kubernetes integration test suite.

## Test Tier Philosophy

Tests are organized into three tiers based on execution time, complexity, and resource requirements. This enables rapid feedback during development while maintaining comprehensive validation for releases.

### Design Principles

1. **Fast feedback first** - Smoke tests catch critical regressions in minutes
2. **Balanced coverage** - Integration tests validate common scenarios without excessive runtime
3. **Deep validation when needed** - Comprehensive tests stress test edge cases and scaling
4. **Composable tiers** - Run any combination of tiers for specific validation needs
5. **Parallel-friendly** - All tests support xdist parallelization for faster execution

## Tier Definitions

### Smoke Tier (`@pytest.mark.smoke`)

**Purpose**: Fast validation of critical functionality. Catches regressions quickly during active development.

**Characteristics:**
- Duration: <2 minutes per test
- Scope: Single-pod or minimal multi-pod scenarios
- Resource usage: <1 CPU core, <512MB RAM per test
- Examples: Identity validation, basic RPC, resource constraint handling

**When to run:**
- Every commit during active development
- Pre-commit hooks (optional)
- PR validation (required)
- Quick sanity checks after cluster changes

**Tests in this tier:**
- `test_corrupted_identity_file` - Validates identity error handling
- `test_missing_identity_regenerates` - Tests identity regeneration logic
- `test_invalid_rns_config` - Validates RNS initialization error handling
- `test_5_concurrent_exec_commands` - Basic RPC concurrency check
- `test_cpu_throttling_handling` - CPU resource limit behavior
- `test_memory_pressure_handling` - Memory resource limit behavior

**Expected runtime:**
- Sequential: ~10 minutes (6 tests × ~90 seconds)
- Parallel (4 workers): ~3 minutes
- Parallel (8 workers): ~2 minutes

### Integration Tier (`@pytest.mark.integration`)

**Purpose**: Moderate-complexity validation of common scenarios and failure modes.

**Characteristics:**
- Duration: <10 minutes per test
- Scope: Multi-pod scenarios, network interactions, recovery patterns
- Resource usage: <2 CPU cores, <2GB RAM per test
- Examples: Hub reconnection, message queuing, graceful degradation

**When to run:**
- Before merging to main (required)
- Daily development validation
- Post-deployment smoke tests in staging
- Regular CI builds

**Tests in this tier:**
- `test_graceful_degradation_on_partition` - Offline mode functionality
- `test_hub_crash_and_restart` - Hub recovery and client reconnection
- `test_message_queue_saturation` - Message overflow handling
- `test_port_conflict` - Port conflict detection
- `test_burst_message_handling` - Burst message queuing
- `test_rapid_announce_no_flooding` - Announce rate throttling
- `test_rpc_queue_under_load` - RPC queue behavior
- `test_cpu_usage_stays_within_limits` - CPU usage monitoring (requires metrics-server)
- `test_no_oom_kills_under_load` - Memory leak detection
- `test_scale_down_graceful_shutdown` - Graceful termination
- `test_resource_requests_vs_limits` - Resource allocation validation
- `test_network_latency_impact` - High-latency behavior
- `test_pods_spread_across_nodes` - Node affinity and distribution

**Expected runtime:**
- Sequential: ~90 minutes (13 tests × ~7 minutes)
- Parallel (4 workers): ~25 minutes
- Parallel (8 workers): ~15 minutes

### Comprehensive Tier (`@pytest.mark.comprehensive`)

**Purpose**: Deep validation of edge cases, stress scenarios, and large-scale behavior.

**Characteristics:**
- Duration: <30 minutes per test
- Scope: Large pod counts, network complexity, sustained load
- Resource usage: <4 CPU cores, <4GB RAM per test
- Examples: 20-node discovery, network partition simulation, bandwidth saturation

**When to run:**
- Pre-release validation (required)
- Nightly builds
- Performance regression testing
- Major infrastructure changes

**Tests in this tier:**
- `test_pods_isolated_via_network_policy` - NetworkPolicy isolation and recovery
- `test_100_messages_per_minute` - High-throughput message delivery (10 pods)
- `test_20_node_discovery` - Large-scale mesh discovery (20 pods)
- `test_scale_from_1_to_10_pods` - Horizontal scaling validation
- `test_bandwidth_saturation` - Network bandwidth stress test

**Expected runtime:**
- Sequential: ~2 hours (4 tests × ~30 minutes)
- Parallel (4 workers): ~40 minutes
- Parallel (8 workers): ~25 minutes

## Marker Usage Patterns

### Single Tier

Most tests belong to a single tier based on their characteristics:

```python
@pytest.mark.asyncio
@pytest.mark.smoke
async def test_basic_functionality(k8s_cluster, test_namespace, styrened_stack):
    """Fast validation test."""
    # Test implementation
```

### Multiple Markers

Some tests may have additional markers for special requirements:

```python
@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.requires_metrics
async def test_cpu_usage_stays_within_limits(k8s_cluster, test_namespace, styrened_stack):
    """Integration test requiring metrics-server."""
    # Test implementation
```

### Legacy `slow` Marker

Tests marked `@pytest.mark.slow` are legacy markers that typically map to `comprehensive` tier:

```python
@pytest.mark.asyncio
@pytest.mark.slow
@pytest.mark.comprehensive
async def test_20_node_discovery(k8s_cluster, test_namespace, styrened_stack):
    """Comprehensive test with legacy slow marker."""
    # Test implementation
```

The `slow` marker is controlled by `--run-slow` flag. The tier markers (`smoke`, `integration`, `comprehensive`) are always available and provide more granular control.

## Test Selection Examples

### Development Workflows

**Quick feedback loop (active development):**
```bash
# Run smoke tests in parallel (fastest feedback)
pytest tests/k8s/ -v -n auto -m smoke

# Expected: ~2-3 minutes with 4-8 workers
```

**Pre-commit validation:**
```bash
# Run smoke + integration (catches most issues)
pytest tests/k8s/ -v -n auto -m "smoke or integration"

# Expected: ~10-15 minutes with 4-8 workers
```

**Pre-merge validation:**
```bash
# Full suite excluding comprehensive (good coverage, manageable time)
pytest tests/k8s/ -v -n auto -m "smoke or integration" --run-slow

# Expected: ~15-20 minutes with 4-8 workers
```

**Pre-release validation:**
```bash
# Full suite including comprehensive (exhaustive validation)
pytest tests/k8s/ -v -n auto -m "smoke or integration or comprehensive" --run-slow

# Expected: ~30-40 minutes with 4-8 workers
```

### CI/CD Workflows

**Pull Request validation:**
```yaml
# .github/workflows/pr-tests.yml
- name: Run smoke tests
  run: pytest tests/k8s/ -v -n auto -m smoke
```

**Merge to main:**
```yaml
# .github/workflows/main-tests.yml
- name: Run smoke + integration tests
  run: pytest tests/k8s/ -v -n auto -m "smoke or integration"
```

**Nightly builds:**
```yaml
# .github/workflows/nightly.yml
- name: Run full test suite
  run: pytest tests/k8s/ -v -n auto --run-slow
```

**Release builds:**
```yaml
# .github/workflows/release.yml
- name: Run comprehensive validation
  run: pytest tests/k8s/ -v -n auto -m "smoke or integration or comprehensive" --run-slow
```

### Targeted Testing

**Test specific functionality:**
```bash
# Only RPC tests
pytest tests/k8s/scenarios/test_load.py::TestRPCConcurrency -v -n auto

# Only resource limit tests
pytest tests/k8s/scenarios/test_scaling.py::TestResourceLimits -v -n auto -m smoke
```

**Test specific tier in a file:**
```bash
# Smoke tests in edge cases only
pytest tests/k8s/scenarios/test_edge_cases.py -v -m smoke

# Integration tests in scaling only
pytest tests/k8s/scenarios/test_scaling.py -v -m integration
```

**Exclude specific tiers:**
```bash
# Everything except comprehensive (faster CI)
pytest tests/k8s/ -v -n auto -m "not comprehensive"

# Everything except smoke (focus on deeper tests)
pytest tests/k8s/ -v -n auto -m "not smoke"
```

## Adding New Tests

### Tier Selection Criteria

When writing a new test, assign it to a tier based on these criteria:

**Assign to Smoke tier if:**
- Test completes in <2 minutes
- Uses 1-2 pods maximum
- Tests critical path functionality
- Catches common regressions
- Minimal resource usage (<1 core, <512MB)

**Assign to Integration tier if:**
- Test completes in 2-10 minutes
- Uses 2-5 pods
- Tests common failure modes or recovery patterns
- Requires moderate resources (<2 cores, <2GB)
- Tests interaction between components

**Assign to Comprehensive tier if:**
- Test takes 10-30 minutes
- Uses 5+ pods or complex topologies
- Tests edge cases or stress scenarios
- Requires significant resources (>2 cores, >2GB)
- Tests scaling or performance limits

### Template for New Tests

```python
import pytest


class TestNewFeature:
    """Test suite for new feature."""

    @pytest.mark.asyncio
    @pytest.mark.smoke  # Choose appropriate tier
    async def test_basic_functionality(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test basic functionality (smoke tier).

        Scenario:
        1. Deploy minimal stack
        2. Validate basic behavior
        3. Verify expected outcome

        Duration: <2 minutes
        Resources: 1-2 pods, <1 core, <512MB
        """
        # Test implementation
        pods = styrened_stack(replica_count=1, mode="standalone")
        # ... assertions ...

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_failure_recovery(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test failure recovery (integration tier).

        Scenario:
        1. Deploy multi-pod stack
        2. Simulate failure condition
        3. Verify recovery behavior

        Duration: 2-10 minutes
        Resources: 2-5 pods, <2 cores, <2GB
        """
        # Test implementation
        pods = styrened_stack(replica_count=3, mode="standalone")
        # ... assertions ...

    @pytest.mark.asyncio
    @pytest.mark.slow
    @pytest.mark.comprehensive
    async def test_scaling_stress(
        self, k8s_cluster, test_namespace, styrened_stack
    ):
        """Test scaling under stress (comprehensive tier).

        Scenario:
        1. Deploy large stack
        2. Apply sustained load
        3. Verify stability and performance

        Duration: 10-30 minutes
        Resources: 10+ pods, >2 cores, >2GB
        """
        # Test implementation
        pods = styrened_stack(replica_count=10, mode="standalone")
        # ... assertions ...
```

### Test Documentation Requirements

Each test should include:
1. Docstring with scenario description
2. Duration estimate
3. Resource requirements
4. Expected behavior
5. Appropriate tier marker(s)

## Parallelization Strategy

### Worker-Safe Test Design

All tests must be worker-safe for xdist parallelization:

1. **Unique namespaces** - Provided by `test_namespace` fixture (includes worker ID)
2. **Unique release names** - Use fixture-generated names or pass `release_name` parameter
3. **No shared state** - Each test is isolated
4. **Session-scoped fixtures** - Shared within worker, not across workers

### Optimal Worker Count

**For smoke tests:**
```bash
# Use auto (fast tests benefit from high parallelism)
pytest tests/k8s/ -v -n auto -m smoke
```

**For integration tests:**
```bash
# Use 4-8 workers (balance speedup vs cluster load)
pytest tests/k8s/ -v -n 4 -m integration
```

**For comprehensive tests:**
```bash
# Use 2-4 workers (resource-intensive tests)
pytest tests/k8s/ -v -n 2 -m comprehensive
```

### Performance Monitoring

Monitor cluster resources during parallel execution:

```bash
# Terminal 1: Run tests
pytest tests/k8s/ -v -n auto -m "smoke or integration"

# Terminal 2: Monitor cluster
watch kubectl top nodes
watch kubectl top pods -A
```

If cluster is overloaded, reduce worker count:
```bash
pytest tests/k8s/ -v -n 2 -m integration  # Fewer workers
```

## Troubleshooting

### Test Timing Out

**Symptoms:**
- Tests hang indefinitely
- Worker processes appear stuck

**Solutions:**
```bash
# Check for orphaned namespaces
kubectl get namespaces | grep styrene-test

# Force delete stuck namespace
kubectl delete namespace <namespace> --grace-period=0 --force

# Check for orphaned Helm releases
helm list --all-namespaces | grep test

# Reduce parallelism
pytest tests/k8s/ -v -n 1  # Sequential execution for debugging
```

### Resource Exhaustion

**Symptoms:**
- Pods stuck in Pending state
- Tests fail with timeout errors
- High node CPU/memory usage

**Solutions:**
```bash
# Monitor resource usage
kubectl top nodes
kubectl describe node <node-name>

# Reduce worker count
pytest tests/k8s/ -v -n 2  # Fewer concurrent tests

# Run smaller tier only
pytest tests/k8s/ -v -n auto -m smoke  # Less resource-intensive
```

### Marker Validation

**Verify marker filtering works:**
```bash
# List tests in each tier without running
pytest tests/k8s/ --collect-only -m smoke
pytest tests/k8s/ --collect-only -m integration
pytest tests/k8s/ --collect-only -m comprehensive

# Verify no unmarked tests
pytest tests/k8s/ --collect-only -m "not (smoke or integration or comprehensive)"
```

### Test Selection Not Working

**If marker filtering doesn't work:**
```bash
# Verify markers are registered in pyproject.toml
grep -A 5 "markers" pyproject.toml

# Use strict marker mode (enabled by default)
pytest tests/k8s/ -v -m smoke --strict-markers
```

## Performance Benchmarks

### Single Worker (Sequential)

| Tier | Test Count | Avg Time/Test | Total Time |
|------|-----------|---------------|------------|
| Smoke | 6 | 90s | ~10min |
| Integration | 13 | 7min | ~90min |
| Comprehensive | 4 | 30min | ~2hrs |
| **Total** | **23** | **~6.5min** | **~2.5hrs** |

### 4 Workers (Parallel)

| Tier | Test Count | Speedup | Total Time |
|------|-----------|---------|------------|
| Smoke | 6 | 3.3x | ~3min |
| Integration | 13 | 3.6x | ~25min |
| Comprehensive | 4 | 3.0x | ~40min |
| **Total** | **23** | **~3.0x** | **~50min** |

### 8 Workers (Parallel)

| Tier | Test Count | Speedup | Total Time |
|------|-----------|---------|------------|
| Smoke | 6 | 5.0x | ~2min |
| Integration | 13 | 6.0x | ~15min |
| Comprehensive | 4 | 4.8x | ~25min |
| **Total** | **23** | **~5.4x** | **~35min** |

**Notes:**
- Times measured on local k3d cluster (4-core, 16GB RAM)
- Cloud clusters may show different results
- Resource-constrained environments will be slower
- Speedup limited by cluster capacity and test dependencies

## Best Practices

### For Test Authors

1. **Start with smoke** - Write fast tests first, add comprehensive tests later
2. **One assertion per test** - Each test validates one behavior clearly
3. **Document scenarios** - Clear docstrings with step-by-step scenarios
4. **Estimate duration** - Include expected runtime in docstring
5. **Use appropriate tier** - Don't over-engineer smoke tests, don't under-test comprehensive
6. **Make tests deterministic** - Avoid flaky timing-dependent assertions
7. **Clean up resources** - Use fixtures for automatic cleanup
8. **Test in parallel** - Verify test works with `-n auto` before merging

### For Test Runners

1. **Use tiers strategically** - Don't always run the full suite
2. **Parallelize when possible** - Use `-n auto` for faster feedback
3. **Monitor cluster resources** - Reduce workers if cluster is overloaded
4. **Start with smoke** - Get fast feedback before running longer tests
5. **Run comprehensive before releases** - Don't skip deep validation
6. **Clean up between runs** - Delete orphaned namespaces and releases
7. **Use CI for consistency** - Don't rely on "works on my machine"

### For CI/CD Pipelines

1. **Tier by pipeline stage** - smoke for PRs, integration for merges, comprehensive for releases
2. **Fail fast** - Run smoke tests before expensive integration tests
3. **Collect logs on failure** - Archive pod logs and cluster state
4. **Retry flaky tests** - Use `--reruns 2` for network-dependent tests
5. **Time budget** - Set realistic timeouts (e.g., 10min for smoke, 30min for integration)
6. **Parallel by default** - Use `-n auto` in CI for faster execution
7. **Cache images** - Build once, load into cluster, run tests multiple times

## Tier Assignment Reference

### Current Tier Distribution

| Test Class | Smoke | Integration | Comprehensive |
|------------|-------|-------------|---------------|
| TestNetworkPartition | 0 | 1 | 1 |
| TestIdentityCorruption | 2 | 0 | 0 |
| TestHubReconnection | 0 | 1 | 0 |
| TestMessageOverflow | 0 | 1 | 0 |
| TestRNSInitializationFailure | 1 | 1 | 0 |
| TestMessageThroughput | 0 | 1 | 1 |
| TestDiscoveryScaling | 0 | 1 | 1 |
| TestRPCConcurrency | 1 | 1 | 0 |
| TestResourceUsageUnderLoad | 0 | 2 | 0 |
| TestHorizontalScaling | 0 | 1 | 1 |
| TestResourceLimits | 2 | 1 | 0 |
| TestNetworkBandwidth | 0 | 1 | 1 |
| TestNodeAffinity | 0 | 1 | 0 |
| **Total** | **6** | **13** | **4** |

### Tier Migration

If test execution times change significantly:

1. **Measure actual runtime** - Use `pytest --durations=0` to see slowest tests
2. **Re-evaluate tier** - Move tests to appropriate tier based on actual duration
3. **Update documentation** - Update test docstring with new duration estimate
4. **Update marker** - Change tier marker to match new classification

Example:
```bash
# Measure test durations
pytest tests/k8s/ -v --durations=0 > durations.txt

# Identify slow smoke tests (>2min)
grep "smoke" durations.txt | awk '$1 > 120 {print $2, $1}'

# Migrate slow tests to integration tier
# Update @pytest.mark.smoke → @pytest.mark.integration
```

## Summary

The three-tier test system provides:
- **Fast feedback** via smoke tests (~2-3min)
- **Balanced coverage** via integration tests (~15-25min)
- **Deep validation** via comprehensive tests (~25-40min)
- **Composable execution** via marker combinations
- **Parallel speedup** via xdist (3-5x faster)

Use tiers strategically to balance speed and coverage for your specific validation needs.
