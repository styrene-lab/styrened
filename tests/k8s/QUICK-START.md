# Styrened K8s Integration Tests - Quick Start

## TL;DR

```bash
# Install dependencies
pip install pytest pytest-asyncio pytest-xdist kubernetes

# Run fast smoke tests (3-5 minutes)
pytest tests/k8s/ -v -n auto -m smoke

# Run smoke + integration tests (10-15 minutes)
pytest tests/k8s/ -v -n auto -m "smoke or integration"

# Run all tests (30-50 minutes)
pytest tests/k8s/ -v -n auto
```

## Test Tiers

### Smoke (9 tests, ~3-5min with 4 workers)
**Purpose:** Fast validation of critical paths
**When:** Every commit, during development

```bash
pytest tests/k8s/ -v -n auto -m smoke
```

**Tests:**
- Peer-to-peer LXMF message delivery
- RPC status request
- Basic device discovery
- Identity corruption handling
- Invalid RNS config handling
- RPC concurrency (5 simultaneous commands)
- CPU throttling behavior
- Memory pressure handling

### Integration (17 tests, ~10-15min with 4 workers)
**Purpose:** Common scenarios and failure modes
**When:** Pre-merge, nightly builds

```bash
pytest tests/k8s/ -v -n auto -m integration
```

**Includes:**
- Hub-routed message delivery
- Cross-pod RPC calls
- Mesh convergence timing
- Graceful degradation on partition
- Hub crash and reconnection
- Message queue saturation
- Various load and scaling scenarios

### Comprehensive (7 tests, ~20-30min with 4 workers)
**Purpose:** Deep validation, stress tests, edge cases
**When:** Pre-release, weekly validation

```bash
pytest tests/k8s/ -v -n auto -m comprehensive
```

**Includes:**
- Multi-hop message propagation
- Mesh resilience after pod restarts
- Network partition with NetworkPolicy
- 100 messages/minute throughput
- 20-node discovery scaling
- Scale 1→10 pods
- Network bandwidth saturation

## Parallel Execution Tips

### Optimal Worker Count

```bash
# Let pytest detect optimal workers (recommended)
pytest tests/k8s/ -v -n auto -m smoke

# Manual worker count (4 is usually good for most clusters)
pytest tests/k8s/ -v -n 4 -m smoke

# Reduce workers if cluster is resource-constrained
pytest tests/k8s/ -v -n 2 -m smoke
```

### Monitor Cluster Resources

```bash
# Watch resource usage during parallel tests
watch kubectl top nodes
watch kubectl top pods -A

# If seeing resource exhaustion, reduce worker count
pytest tests/k8s/ -v -n 2 -m smoke  # fewer workers
```

## Common Workflows

### Development Workflow

```bash
# 1. Fast validation during development
pytest tests/k8s/ -v -n auto -m smoke

# 2. Test specific scenario
pytest tests/k8s/scenarios/test_e2e_integration.py::test_peer_to_peer_message_delivery -v

# 3. Pre-commit validation
pytest tests/k8s/ -v -n auto -m "smoke or integration"
```

### CI/CD Workflow

```bash
# Pull request checks (fast feedback)
pytest tests/k8s/ -v -n auto -m smoke

# Merge to main (broader coverage)
pytest tests/k8s/ -v -n auto -m "smoke or integration"

# Pre-release validation (everything)
pytest tests/k8s/ -v -n auto
```

### Debugging Workflow

```bash
# 1. Run single test with full output
pytest tests/k8s/scenarios/test_e2e_integration.py::test_peer_to_peer_message_delivery -v -s

# 2. Disable parallel execution for clearer output
pytest tests/k8s/ -v -m smoke  # no -n flag

# 3. Increase logging verbosity
pytest tests/k8s/ -v -s --log-cli-level=DEBUG -m smoke
```

## Prerequisites

### 1. Kubernetes Cluster

You need a running k8s cluster. Options:

**Local (kind):**
```bash
kind create cluster --name styrene-test
```

**Local (k3d):**
```bash
k3d cluster create styrene-test
```

**Remote:**
```bash
# Ensure kubectl is configured
kubectl cluster-info
```

### 2. Container Image

**Option A: Build locally (recommended for development)**

```bash
# Build test image
just build-test

# Load into kind
kind load docker-image styrene-lab/styrened-test:test --name styrene-test

# OR load into k3d
k3d image import styrene-lab/styrened-test:test -c styrene-test
```

**Option B: Use pre-built images from GHCR**

```bash
# Pull latest nightly test image
docker pull ghcr.io/styrene-lab/styrened-test:latest

# Load into kind
kind load docker-image ghcr.io/styrene-lab/styrened-test:latest --name styrene-test

# OR load into k3d
k3d image import ghcr.io/styrene-lab/styrened-test:latest -c styrene-test
```

**Option C: Build directly (manual Docker command)**

```bash
# Build for AMD64 (if on ARM Mac)
docker build --platform linux/amd64 -t styrened-test:latest -f tests/k8s/docker/Dockerfile .

# Load into cluster
kind load docker-image styrened-test:latest --name styrene-test
```

**Option D: Use GHCR images on remote cluster (recommended for brutus/cloud)**

```bash
# One command: create secret, deploy from GHCR, run tests
just test-k8s-remote
```

This is ideal for:
- Remote k3s clusters (like brutus)
- Cloud Kubernetes (GKE, EKS, AKS)
- Testing CI-built images without rebuilding
- ARM64 clusters (native multi-arch images)

See [REMOTE-TESTING.md](REMOTE-TESTING.md) for complete guide.

### 3. Python Dependencies

```bash
pip install pytest pytest-asyncio pytest-xdist kubernetes
```

## Troubleshooting

### Tests Timeout or Hang

```bash
# Increase pod startup timeout (default 120s)
# Edit conftest.py: wait_for_ready(pods, timeout=180)

# Check pod status
kubectl get pods -A | grep styrene-test

# Check pod logs
kubectl logs <pod-name> -n <namespace>
```

### Namespace Conflicts

```bash
# Clean up orphaned namespaces
kubectl get namespaces | grep styrene-test
kubectl delete namespace <namespace> --grace-period=0
```

### Worker Failures

```bash
# Run with single worker for debugging
pytest tests/k8s/ -v -n 1 -m smoke

# Enable xdist debug output
pytest tests/k8s/ -v -n auto -m smoke --dist loadscope -vv
```

## What Gets Tested

### End-to-End Scenarios
- **LXMF Message Passing:** Peer-to-peer, hub-routed, multi-hop
- **RPC Command Execution:** Status, exec, cross-pod calls
- **Device Discovery:** Announce, discover, mesh formation

### Edge Cases
- Network partitions (NetworkPolicy isolation)
- Identity corruption and regeneration
- Hub crashes and reconnection
- Message queue saturation
- RNS initialization failures

### Load and Scaling
- Message throughput (100 msgs/min)
- Discovery scaling (20 nodes)
- RPC concurrency (5 simultaneous)
- Horizontal scaling (1→10 pods)
- Resource limits (CPU/memory)
- Network bandwidth saturation

## Expected Execution Times

### Sequential (1 worker)

| Tier | Tests | Time |
|------|-------|------|
| Smoke | 9 | ~10-15min |
| Integration | 17 | ~30-40min |
| Comprehensive | 7 | ~60-90min |
| **All** | **33** | **~100-145min** |

### Parallel (4 workers)

| Tier | Tests | Time |
|------|-------|------|
| Smoke | 9 | ~3-5min |
| Integration | 17 | ~10-15min |
| Comprehensive | 7 | ~20-30min |
| **All** | **33** | **~30-50min** |

**Speedup:** 3-4x with parallel execution

## More Information

- **Comprehensive Guide:** See `TESTING-GUIDE.md` for test tier philosophy, marker usage, and best practices
- **Full Documentation:** See `README.md` for detailed fixture documentation and test organization
- **Implementation Report:** See `E2E-IMPLEMENTATION-REPORT.md` for architecture decisions and verification

## Quick Reference

```bash
# Tier selection
-m smoke              # Fast tests only
-m integration        # Moderate tests only
-m comprehensive      # Deep tests only
-m "smoke or integration"  # Combined

# Parallel execution
-n auto              # Auto-detect workers
-n 4                 # 4 workers
# (omit -n flag)     # Sequential

# Output control
-v                   # Verbose
-s                   # Show output
--tb=short           # Short tracebacks
-x                   # Stop on first failure

# Slow tests
--run-slow           # Include slow tests (load/scaling)
# (omit flag)        # Skip slow tests (default)
```

## Example Commands

```bash
# Fast validation (development)
pytest tests/k8s/ -v -n auto -m smoke

# Pre-merge check
pytest tests/k8s/ -v -n auto -m "smoke or integration"

# Pre-release validation
pytest tests/k8s/ -v -n auto --run-slow

# Debug single test
pytest tests/k8s/scenarios/test_e2e_integration.py::test_peer_to_peer_message_delivery -v -s

# Monitor cluster while testing
watch kubectl top pods -A
```
