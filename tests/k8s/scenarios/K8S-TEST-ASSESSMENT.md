# K8s Test Suite Assessment

Comprehensive analysis of styrened's Kubernetes integration tests, their execution times, markers, and design goals.

## Executive Summary

**Total Tests**: 68 tests across 6 test files
**Test Distribution**:
- Smoke: 15 tests (~2 min each = **30 min total**)
- Integration: 33 tests (~5-10 min each = **165-330 min total**)
- Comprehensive: 11 tests (~15-30 min each = **165-330 min total**)
- Slow: 13 tests (10+ min each = **130+ min total**)

**Combined Estimates** (with parallelization):
- **Smoke tier**: 30-45 minutes (with `-n 4-8` parallel workers)
- **Integration tier**: 2-4 hours (with `-n 4-8` parallel workers)
- **Comprehensive tier**: 4-8 hours (with parallelization)
- **Full suite with slow**: 8-12 hours (with parallelization)

---

## Test File Analysis

### 1. `test_e2e_integration.py` - E2E Integration Tests

**Purpose**: End-to-end validation of LXMF messaging, RPC operations, and device discovery in realistic K8s environments.

**Test Count**: 9 tests
- Smoke: 3 tests
- Integration: 4 tests
- Comprehensive: 2 tests

**Design Goals**:
1. **Message Delivery**: Validate peer-to-peer, hub-based, and multi-hop LXMF message routing
2. **RPC Operations**: Test status requests, command execution, and cross-pod RPC calls using StyreneProtocol wire format
3. **Mesh Discovery**: Verify RNS announce handling, device discovery, and mesh convergence
4. **Resilience**: Test pod restart recovery and mesh re-establishment

**Time Estimates**:
| Test | Marker | Est. Time | Rationale |
|------|--------|-----------|-----------|
| `test_peer_to_peer_message_delivery` | smoke | ~2 min | 2 pods, 15s init + 30s send + margin |
| `test_hub_based_message_routing` | integration | ~5 min | Hub deploy + 2 peers + routing wait |
| `test_multi_hop_message_propagation` | comprehensive | ~8 min | 4 pods, 60s discovery + multi-hop routing |
| `test_rpc_status_request` | smoke | ~1 min | Wire protocol encoding validation |
| `test_rpc_exec_command` | integration | ~3 min | 2 pods + exec envelope creation |
| `test_rpc_cross_pod_status_check` | integration | ~4 min | 3 pods + multiple status queries |
| `test_basic_announce_and_discover` | smoke | ~2 min | 3 pods + announce cycle wait |
| `test_mesh_convergence_time` | integration | ~6 min | 5 pods + 90s convergence wait |
| `test_mesh_resilience_pod_restart` | comprehensive | ~8 min | 4 pods + pod delete + recreation + re-convergence |

**Total**: Smoke: 5 min, Integration: 18 min, Comprehensive: 16 min

---

### 2. `test_edge_cases.py` - Edge Case and Failure Mode Tests

**Purpose**: Validate styrened behavior under failure conditions, network partitions, identity corruption, and configuration edge cases.

**Test Count**: 10 tests
- Smoke: 4 tests
- Integration: 5 tests
- Comprehensive: 1 test

**Design Goals**:
1. **Network Resilience**: Test network partitions via NetworkPolicy, graceful degradation when isolated
2. **Identity Management**: Verify handling of corrupted/missing identity files
3. **Hub Failover**: Test client pods survive and reconnect after hub crash/restart
4. **Resource Limits**: Validate message queue saturation doesn't crash daemon
5. **Configuration Edge Cases**: Test empty configs, high announce intervals, port conflicts

**Time Estimates**:
| Test | Marker | Est. Time | Rationale |
|------|--------|-----------|-----------|
| `test_pods_isolated_via_network_policy` | comprehensive | ~4 min | NetworkPolicy apply/remove + connectivity tests |
| `test_graceful_degradation_on_partition` | integration | ~3 min | iptables isolation (may skip if no NET_ADMIN) |
| `test_corrupted_identity_file` | smoke | ~2 min | Corrupt file + restart + log check |
| `test_missing_identity_regenerates` | smoke | ~2 min | Identity file check |
| `test_hub_crash_and_restart` | integration | ~6 min | Hub + 2 clients + hub delete + recreation |
| `test_message_queue_saturation` | integration | ~3 min | 2 pods + rapid message stress test |
| `test_invalid_rns_interface_config` | smoke | ~2 min | Default config deployment + validation |
| `test_port_already_in_use` | integration | ~2 min | Port bind attempt + validation |
| `test_empty_config_handled` | smoke | ~2 min | Minimal config deployment |
| `test_high_announce_interval` | integration | ~3 min | 2 pods + verify no excessive announces |

**Total**: Smoke: 8 min, Integration: 17 min, Comprehensive: 4 min

---

### 3. `test_load.py` - Load and Throughput Tests

**Purpose**: Validate styrened performance under high message throughput, discovery scaling, and concurrent RPC operations.

**Test Count**: 8 tests
- Smoke: 1 test
- Integration: 5 tests
- Comprehensive: 2 tests (both also `slow`)

**Design Goals**:
1. **Message Throughput**: Test 100 msgs/min across 10 pods, burst handling
2. **Discovery Scaling**: Validate 20-node mesh discovery, announce flooding prevention
3. **RPC Concurrency**: Test concurrent exec commands, queue handling under load
4. **Resource Usage**: Monitor CPU/memory under load, prevent OOM kills

**Time Estimates**:
| Test | Marker | Est. Time | Rationale |
|------|--------|-----------|-----------|
| `test_100_messages_per_minute` | slow + comprehensive | ~12 min | 10 pods + 100 msgs over ~2 min + overhead |
| `test_burst_message_handling` | integration | ~6 min | 5 pods + 20 rapid messages |
| `test_20_node_discovery` | slow + comprehensive | ~15 min | 20 pods + 150s announce rounds |
| `test_rapid_announce_no_flooding` | integration | ~5 min | 10 pods + 90s monitoring |
| `test_5_concurrent_exec_commands` | smoke | ~2 min | 1 pod + local concurrent execution |
| `test_rpc_queue_under_load` | integration | ~3 min | 1 pod + 50 rapid requests |
| `test_cpu_usage_stays_within_limits` | integration | ~4 min | 5 pods + 60s load + metrics check |
| `test_no_oom_kills_under_load` | integration | ~4 min | 5 pods + memory pressure + event check |

**Total**: Smoke: 2 min, Integration: 22 min, Comprehensive (slow): 27 min

---

### 4. `test_scaling.py` - Horizontal Scaling Tests

**Purpose**: Test styrened's ability to scale horizontally, handle resource constraints, and maintain mesh stability during scaling operations.

**Test Count**: 8 tests
- Smoke: 2 tests
- Integration: 4 tests
- Comprehensive: 2 tests (both also `slow`)

**Design Goals**:
1. **Horizontal Scaling**: Test scale from 1→5→10 pods with mesh discovery
2. **Scale Down**: Verify graceful shutdown when scaling down
3. **Resource Constraints**: Test CPU throttling, memory pressure handling
4. **Network Bandwidth**: Test under bandwidth saturation and high latency
5. **Node Distribution**: Verify pod anti-affinity and cross-node connectivity

**Time Estimates**:
| Test | Marker | Est. Time | Rationale |
|------|--------|-----------|-----------|
| `test_scale_from_1_to_10_pods` | slow + comprehensive | ~12 min | Multiple helm upgrades + convergence waits |
| `test_scale_down_graceful_shutdown` | integration | ~5 min | 5→2 pods + shutdown validation |
| `test_cpu_throttling_handling` | smoke | ~2 min | 1 pod + CPU stress |
| `test_memory_pressure_handling` | smoke | ~2 min | 1 pod + memory stress |
| `test_resource_requests_vs_limits` | integration | ~4 min | 10 pods + resource spec validation |
| `test_bandwidth_saturation` | slow + comprehensive | ~8 min | 5 pods + network load |
| `test_network_latency_impact` | integration | ~4 min | 3 pods + tc qdisc latency injection |
| `test_pods_spread_across_nodes` | integration | ~4 min | 5 pods + node assignment check |

**Total**: Smoke: 4 min, Integration: 17 min, Comprehensive (slow): 20 min

---

### 5. `test_mesh_propagation.py` - Long-Running Mesh Propagation Tests

**Purpose**: Extended validation of production-like multi-hop topologies, LXMF propagation, and sustained mesh operation.

**Test Count**: 9 tests
- All marked `slow` (some also `propagation`, `resilience`, `convergence`)

**Design Goals**:
1. **Hub Topology**: Test hub-based routing with 1 hub + 3 peers
2. **Chain Topology**: Test multi-hop (4-hop) message delivery in linear chain
3. **Hub Failover**: Test peer recovery after hub restart
4. **Sustained Operation**: Test 10-minute continuous messaging for memory leak detection
5. **Large Mesh**: Test 8-node mesh convergence
6. **Identity Persistence**: Verify identities survive pod restarts

**Time Estimates**:
| Test | Marker | Est. Time | Rationale |
|------|--------|-----------|-----------|
| `test_hub_routes_peer_to_peer_messages` | slow + propagation | ~10 min | Hub + 3 peers + 90s announce + routing |
| `test_all_peers_discover_via_hub` | slow + propagation | ~10 min | Hub + 3 peers + convergence wait |
| `test_rpc_status_across_hub` | slow + propagation | ~12 min | Hub + 3 peers + 90s wait + RPC round-trip verification |
| `test_message_traverses_chain` | slow + propagation | ~12 min | 5-node chain + 120s discovery + multi-hop send |
| `test_bidirectional_chain_routing` | slow + propagation | ~14 min | 5-node chain + bidirectional messages |
| `test_peers_survive_hub_restart` | slow + resilience | ~15 min | Hub + 3 peers + hub delete + recreation + re-convergence |
| `test_sustained_messaging_10min` | slow + propagation | ~15 min | 3-node mesh + 20 messages @ 30s intervals |
| `test_8_node_mesh_convergence` | slow + convergence | ~12 min | 8 pods + 300s convergence timeout |
| `test_identity_survives_restart` | slow + resilience | ~10 min | 3 pods + pod delete + identity verification |

**Total**: 110 minutes (~2 hours)

**Notes**: These tests use custom fixtures (`hub_stack`, `chain_stack`, `mesh_stack`) defined in the test file that orchestrate multi-topology deployments.

---

### 6. `test_terminal_sessions.py` - Terminal Session Framework Tests

**Purpose**: Validate terminal session establishment, data plane operations, signal propagation, lifecycle management, and security boundaries.

**Test Count**: 24 tests
- Smoke: 5 tests
- Integration: 15 tests
- Comprehensive: 4 tests

**Design Goals**:
1. **Session Establishment**: Test TERMINAL_REQUEST/ACCEPT/REJECT flows
2. **Data Plane**: Validate StreamData, WindowSize, CommandExited message serialization
3. **Signal Handling**: Test signal propagation (SIGINT, SIGTERM, SIGHUP, etc.)
4. **Lifecycle Management**: Test session close sequences, exit code propagation
5. **Failure Modes**: Test invalid messages, pod restarts, network partitions
6. **Concurrent Sessions**: Test multiple simultaneous sessions, resource limits
7. **Security**: Test authorization config, identity binding, malicious payload rejection
8. **Wire Protocol**: Verify message type prefixes, control plane reserved ranges

**Time Estimates**:
| Test | Marker | Est. Time | Rationale |
|------|--------|-----------|-----------|
| Session establishment tests (3) | smoke/integration | ~2-3 min each | Wire protocol encoding validation |
| Data plane tests (2) | smoke/integration | ~2 min each | Serialization roundtrips |
| Signal tests (1) | integration | ~2 min | Signal message creation |
| Lifecycle tests (2) | integration | ~2 min each | Close/exit sequences |
| Failure mode tests (3) | integration/comprehensive | ~4-8 min each | Pod restarts, network partitions |
| Concurrent sessions (2) | integration/comprehensive | ~3-6 min each | Multiple requests, resource stress |
| Security tests (3) | integration/comprehensive | ~2-4 min each | Auth config, identity binding, payload validation |
| Wire protocol tests (4) | smoke/integration | ~2 min each | Message type verification |

**Total**: Smoke: 10 min, Integration: 45 min, Comprehensive: 24 min

---

## Test Tier Summary

### Smoke Tier (15 tests, ~30-45 min total with parallelization)

**Purpose**: Fast validation of core functionality for rapid feedback in CI.

**Distribution**:
- E2E Integration: 3 tests (message delivery, RPC, discovery)
- Edge Cases: 4 tests (identity, config validation)
- Load: 1 test (RPC concurrency)
- Scaling: 2 tests (CPU/memory constraints)
- Terminal Sessions: 5 tests (session protocol, serialization)

**Characteristics**:
- Single or few pods (1-3)
- Short wait times (10-30s)
- Protocol validation (wire format, serialization)
- Basic functionality checks

**CI Usage**: Run on every PR for fast feedback (~10 min with `-n 4`)

---

### Integration Tier (33 tests, ~2-4 hours total with parallelization)

**Purpose**: Moderate complexity tests validating multi-component interactions.

**Distribution**:
- E2E Integration: 4 tests (hub routing, convergence, RPC)
- Edge Cases: 5 tests (network partition, hub failover, queue saturation)
- Load: 5 tests (burst handling, discovery scaling, resource monitoring)
- Scaling: 4 tests (scale operations, network latency, node distribution)
- Terminal Sessions: 15 tests (session lifecycle, data plane, security)

**Characteristics**:
- Multiple pods (2-10)
- Medium wait times (30-90s)
- Real mesh operations (routing, discovery, RPC)
- Moderate resource requirements

**CI Usage**: Run nightly or on main branch pushes

---

### Comprehensive Tier (11 tests, ~4-8 hours total with parallelization)

**Purpose**: Deep validation with edge cases and extended scenarios.

**Distribution**:
- E2E Integration: 2 tests (multi-hop propagation, resilience)
- Edge Cases: 1 test (network policy isolation)
- Load: 2 tests (100 msg/min throughput, 20-node discovery) ← **also slow**
- Scaling: 2 tests (1→10 scale, bandwidth saturation) ← **also slow**
- Terminal Sessions: 4 tests (pod restart recovery, network partition, resource limits, malicious payloads)

**Characteristics**:
- Many pods (4-20)
- Long wait times (60-180s)
- Complex topologies (hub+peers, chains, large meshes)
- Resource stress testing

**CI Usage**: Run before releases or weekly comprehensive validation

---

### Slow Tier (13 tests, ~2+ hours)

**Purpose**: Load testing, scaling validation, and sustained operation tests.

**Distribution**:
- Load: 2 tests (throughput, large-scale discovery)
- Scaling: 2 tests (horizontal scaling, bandwidth)
- Mesh Propagation: 9 tests (hub topology, chain routing, sustained messaging)

**Characteristics**:
- Very long execution (10-15 min per test)
- Large deployments (8-20 pods)
- Sustained operations (10+ minutes)
- Complex multi-hop topologies

**CI Usage**: Run only when explicitly requested (`pytest --run-slow`) or before major releases

**Note**: The slow marker is used to **exclude** tests by default. Tests with `@pytest.mark.slow` are skipped unless `--run-slow` flag is provided.

---

## Design Philosophy Alignment

### Tier-Based Testing Strategy

The test suite follows a clear tier-based philosophy as documented in the `styrened-testing` skill:

✅ **Smoke** - Fast validation (<2 min per test)
- **Goal**: Rapid feedback on core functionality
- **Reality**: 15 tests averaging ~2 min each
- **Alignment**: Perfect - enables PR validation in ~10 min with parallelization

✅ **Integration** - Moderate complexity (<10 min per test)
- **Goal**: Multi-component validation
- **Reality**: 33 tests averaging ~4-6 min each
- **Alignment**: Good - most tests under 10 min, suitable for nightly runs

✅ **Comprehensive** - Deep validation (<30 min per test)
- **Goal**: Extended scenarios and edge cases
- **Reality**: 11 tests averaging ~10-20 min each (some overlap with slow)
- **Alignment**: Good - suitable for pre-release validation

⚠️ **Slow** - Load/scaling (30+ min per test)
- **Goal**: Performance validation, stress testing
- **Reality**: 13 tests averaging ~10-15 min each, total ~2 hours
- **Alignment**: Excellent - properly gated behind `--run-slow` flag

### Test Independence

✅ **Isolation**: Each test uses ephemeral namespaces (`test_namespace` fixture)
✅ **Parallelization**: Tests can run in parallel (except RNS singleton tests, which are in `tests/integration/`)
✅ **Cleanup**: Automatic namespace deletion via fixture finalizers

### K8s Test Harness Pattern

✅ **Deployment Automation**: `K8sTestHarness` class handles Helm operations
✅ **Pod Management**: `styrened_stack` fixture provides deployment callable
✅ **Validation Helpers**: Port-forward, log retrieval, pod exec helpers
✅ **Multi-Topology Support**: Custom fixtures for hub, chain, mesh topologies (`test_mesh_propagation.py`)

---

## Gaps and Recommendations

### Current State

**Strengths**:
1. ✅ Comprehensive coverage of LXMF messaging, RPC, discovery, and mesh topologies
2. ✅ Well-defined tier system with appropriate time budgets
3. ✅ Good test independence and parallelization support
4. ✅ Terminal session framework thoroughly tested (24 tests)
5. ✅ Edge cases and failure modes well-covered

**Observations**:
1. ⚠️ Some `comprehensive` tests overlap with `slow` (4 tests have both markers)
2. ⚠️ `test_mesh_propagation.py` tests all marked `slow` but not all are `comprehensive`
3. ⚠️ Integration tier has wide time variance (2-10 min per test)

### Recommendations

#### 1. Marker Consistency

Consider marking `test_mesh_propagation.py` tests with appropriate tier markers:
- Hub routing tests → `comprehensive + slow`
- Sustained messaging → `comprehensive + slow`
- Large mesh convergence → `comprehensive + slow`

**Rationale**: Aligns with tier philosophy and makes test selection clearer.

#### 2. Time Budget Refinement

**Current tier estimates** (per test):
- Smoke: <2 min ✅ (actual: 1-2 min)
- Integration: <10 min ⚠️ (actual: 2-10 min, some near limit)
- Comprehensive: <30 min ✅ (actual: 8-20 min)
- Slow: >10 min ✅ (actual: 10-15 min)

**Suggestion**: Add sub-tier for tests in 6-10 min range:
- Fast integration: 2-5 min
- Extended integration: 6-10 min

This helps with CI time budgeting (e.g., fast integration for PR checks, extended for nightly).

#### 3. Parallel Execution Optimization

**Current setup**: Tests are parallelizable via pytest-xdist (`-n auto`)

**Enhancement**: Consider grouping slow tests to run sequentially within workers to prevent resource contention:
```python
# In conftest.py
def pytest_collection_modifyitems(config, items):
    # Group slow tests to run sequentially
    slow_tests = [item for item in items if "slow" in item.keywords]
    for test in slow_tests:
        test.add_marker(pytest.mark.run(order=100))  # Run after others
```

#### 4. Resource Requirements Documentation

**Add to test docstrings**:
- Expected pod count
- Approximate memory/CPU usage
- Cluster requirements (single-node vs multi-node)

**Example**:
```python
async def test_scale_from_1_to_10_pods(...):
    """Test scaling from 1 to 10 pods with mesh discovery.

    Resource Requirements:
    - Pods: 1→10 (scaling)
    - Memory: ~2GB total
    - CPU: ~2 cores
    - Cluster: Works on single-node
    - Est. Time: 12 min
    """
```

#### 5. Smoke Test Targeting

**Goal**: Reduce smoke tier to 15-20 minutes for ultra-fast PR feedback

**Current**: 15 tests × ~2 min = ~30 min serial, ~10 min with `-n 4`

**Refinement**: Consider moving some current smoke tests to integration:
- `test_basic_announce_and_discover` → integration (involves 3 pods + 45s wait)
- `test_cpu_throttling_handling` → integration (stress testing)

**Keep in smoke**:
- Wire protocol validation (no pod deployment)
- Single-pod initialization tests
- Message serialization roundtrips

---

## CI/CD Integration Strategy

### PR Validation (~10 min)
```bash
pytest tests/k8s/ -m smoke -v -n 4
```
- 15 tests, parallelized across 4 workers
- Fast feedback on core functionality

### Nightly Integration (~2 hours)
```bash
pytest tests/k8s/ -m "smoke or integration" -v -n 8
```
- 48 tests (smoke + integration), parallelized across 8 workers
- Catches regressions in multi-component scenarios

### Pre-Release Comprehensive (~4-6 hours)
```bash
pytest tests/k8s/ -v -n 8
```
- 59 tests (smoke + integration + comprehensive, excludes slow unless `--run-slow`)
- Deep validation before tagging release

### Weekly Full Suite (~8-12 hours)
```bash
pytest tests/k8s/ -v --run-slow -n 8
```
- All 68 tests including slow load/scaling tests
- Comprehensive performance and stress validation

---

## Test Execution Examples

### By Tier
```bash
# Smoke only (fast PR validation)
pytest tests/k8s/ -m smoke -v -n auto

# Integration only (nightly)
pytest tests/k8s/ -m integration -v -n auto

# Comprehensive only (pre-release)
pytest tests/k8s/ -m comprehensive -v -n auto

# Everything except slow (default)
pytest tests/k8s/ -m "not slow" -v -n auto
```

### By Category
```bash
# Mesh propagation tests (all slow)
pytest tests/k8s/scenarios/test_mesh_propagation.py -v --run-slow

# Terminal session tests only
pytest tests/k8s/scenarios/test_terminal_sessions.py -v -n auto

# Load and scaling tests
pytest tests/k8s/scenarios/test_load.py tests/k8s/scenarios/test_scaling.py -v --run-slow
```

### By File
```bash
# E2E integration suite
pytest tests/k8s/scenarios/test_e2e_integration.py -v -n 4

# Edge cases and failure modes
pytest tests/k8s/scenarios/test_edge_cases.py -v -n 4
```

---

## Conclusion

The styrened K8s test suite demonstrates **excellent design alignment** with tier-based testing philosophy:

1. **Clear tier separation** with appropriate time budgets
2. **Comprehensive coverage** of messaging, RPC, discovery, scaling, and terminal sessions
3. **Good parallelization support** via pytest-xdist and isolated namespaces
4. **Appropriate gating** of slow tests behind `--run-slow` flag
5. **Well-structured harness** for deployment automation and validation

**Minor improvements** would enhance clarity (consistent marker usage across propagation tests) and CI efficiency (refined smoke tier, resource requirements documentation), but the current design is **production-ready** and suitable for CI/CD integration.

**Estimated Real-World CI Times** (with `-n 4-8` parallelization):
- PR Validation (smoke): 10 minutes ✅
- Nightly (smoke + integration): 90-120 minutes ✅
- Pre-Release (all except slow): 4-6 hours ✅
- Weekly Full Suite (including slow): 8-12 hours ✅
