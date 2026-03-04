# Styrened Kubernetes Integration Tests

Containerized integration test suite for styrened that deploys isolated test stacks into Kubernetes. Enables rapid testing of edge cases, load scenarios, and scaling behavior without requiring massive hardware.

## Prerequisites

### Local Development (kind or k3d)

**kind:**
```bash
# Install kind
brew install kind  # macOS
# OR: https://kind.sigs.k8s.io/docs/user/quick-start/#installation

# Create cluster
kind create cluster --name styrene-test
```

**k3d:**
```bash
# Install k3d
brew install k3d  # macOS
# OR: https://k3d.io/#installation

# Create cluster
k3d cluster create styrene-test
```

### Cloud Kubernetes / Remote Clusters

Ensure `kubectl` is configured with valid context:
```bash
kubectl cluster-info
```

For testing with GHCR images on remote clusters (brutus k3s, cloud K8s), you'll need an ImagePullSecret:

```bash
# One-command setup: create secret, deploy, test
just test-k8s-remote
```

See [REMOTE-TESTING.md](REMOTE-TESTING.md) for complete guide.

### Required Tools

- Nix (for building OCI images)
- Container runtime (Podman recommended, or Docker) for loading/pushing
- Helm 3.x
- kubectl
- pytest

## Quick Start

### 1. Build Test Image

**Using justfile (recommended):**
```bash
# Build test image locally
just build-test

# Verify the build
just test-image
```

**Using nix directly:**
```bash
nix build .#oci-test
nix run .#oci-test.copyToPodman
```

**Image naming:**
- Local builds: `styrene-lab/styrened-test:test`
- Test images in GHCR: `ghcr.io/styrene-lab/styrened-test:latest`
- Production images: `ghcr.io/styrene-lab/styrened:latest`

### 2. Load Image (Local K8s Only)

**kind:**
```bash
# If built with justfile
kind load docker-image styrene-lab/styrened-test:test --name styrene-test

# If built with Docker directly
kind load docker-image styrened-test:latest --name styrene-test
```

**k3d:**
```bash
# If built with justfile
k3d image import styrene-lab/styrened-test:test -c styrene-test

# If built with Docker directly
k3d image import styrened-test:latest -c styrene-test
```

**Using GHCR images (no build required):**

For local clusters (kind/k3d):
```bash
# Pull test image from registry
podman pull ghcr.io/styrene-lab/styrened-test:latest
kind load docker-image ghcr.io/styrene-lab/styrened-test:latest --name styrene-test
```

For remote clusters (e.g., brutus k3s):
```bash
# Create ImagePullSecret and deploy directly from GHCR
just test-k8s-remote
```

See [REMOTE-TESTING.md](REMOTE-TESTING.md) for complete remote cluster testing guide.

### 3. Run Tests

```bash
# All tests (sequential)
pytest tests/k8s/ -v

# Run tests in parallel (auto-detect CPU count)
pytest tests/k8s/ -v -n auto

# Run tests in parallel (explicit worker count)
pytest tests/k8s/ -v -n 4

# Parallel with slow tests included
pytest tests/k8s/ -v -n auto --run-slow

# Specific scenario (parallel)
pytest tests/k8s/scenarios/test_edge_cases.py -v -n auto

# Single test (sequential)
pytest tests/k8s/scenarios/test_edge_cases.py::test_network_partition -v

# Skip slow tests (default)
pytest tests/k8s/ -v

# Include slow tests (load/scaling)
pytest tests/k8s/ -v --run-slow
```

## Test Tier Selection

Tests are organized into three tiers based on execution time and complexity. Use markers to run specific test tiers:

### Tier Overview

| Tier | Marker | Duration | Purpose | Test Count |
|------|--------|----------|---------|------------|
| Smoke | `smoke` | <2min/test | Fast validation, critical path | 6 tests |
| Integration | `integration` | <10min/test | Moderate complexity, common scenarios | 13 tests |
| Comprehensive | `comprehensive` | <30min/test | Deep validation, edge cases, stress | 4 tests |

### Run Specific Tiers

```bash
# Smoke tests only (fastest, ~5-10min total)
pytest tests/k8s/ -v -m smoke

# Integration tests only (~20-30min total)
pytest tests/k8s/ -v -m integration

# Comprehensive tests only (slowest, ~30-60min total)
pytest tests/k8s/ -v -m comprehensive

# Smoke + Integration (most common for development)
pytest tests/k8s/ -v -m "smoke or integration"

# All tiers (full suite)
pytest tests/k8s/ -v -m "smoke or integration or comprehensive"

# Parallel smoke tests (recommended)
pytest tests/k8s/ -v -n auto -m smoke

# Exclude comprehensive tests
pytest tests/k8s/ -v -m "not comprehensive"
```

### Tier Selection Strategy

**Development workflow:**
```bash
# Quick validation during development
pytest tests/k8s/ -v -n auto -m smoke

# Pre-commit validation
pytest tests/k8s/ -v -n auto -m "smoke or integration"

# Pre-release validation
pytest tests/k8s/ -v -n auto -m "smoke or integration or comprehensive"
```

**CI/CD:**
- PR checks: `smoke` tier only
- Merge to main: `smoke or integration`
- Nightly builds: Full suite with `--run-slow`
- Release builds: Full suite including `comprehensive`

### Expected Execution Times

| Configuration | Time (sequential) | Time (4 workers) | Time (8 workers) |
|--------------|-------------------|------------------|------------------|
| Smoke only | ~10min | ~3min | ~2min |
| Integration only | ~30min | ~10min | ~7min |
| Comprehensive only | ~2hrs | ~40min | ~25min |
| Smoke + Integration | ~40min | ~13min | ~9min |
| Full suite | ~2.5hrs | ~50min | ~35min |

**Note**: Times assume healthy cluster. Resource-constrained environments may take longer.

For detailed tier documentation, see [TESTING-GUIDE.md](./TESTING-GUIDE.md).

## Parallel Execution

Tests support parallel execution via `pytest-xdist` to reduce total runtime. Each worker runs tests in isolation with unique namespaces to prevent resource conflicts.

### How It Works

- **Worker Isolation**: Each xdist worker gets a unique namespace prefix (e.g., `styrene-test-w0-*`, `styrene-test-w1-*`)
- **Session-scoped Fixtures**: Long-running daemons persist across tests within the same worker
- **Resource Safety**: No conflicts between parallel workers (namespaces, releases, pods all scoped)

### Usage Examples

```bash
# Auto-detect CPU count (recommended)
pytest tests/k8s/ -v -n auto

# Explicit worker count (4 workers)
pytest tests/k8s/ -v -n 4

# Parallel + slow tests
pytest tests/k8s/ -v -n auto --run-slow

# Parallel + specific markers
pytest tests/k8s/ -v -n auto -m smoke

# Sequential execution (no parallelism)
pytest tests/k8s/ -v
```

### Performance Comparison

| Mode | Workers | Time (smoke) | Time (full) |
|------|---------|--------------|-------------|
| Sequential | 1 | ~10min | ~30min |
| Parallel | 4 | ~3min | ~10min |
| Parallel | 8 | ~2min | ~7min |

**Note**: Actual speedup depends on cluster resources and test distribution.

### Long-Running Daemon Fixture

For tests that need a persistent daemon across multiple test cases, use the `long_running_daemon` fixture:

```python
@pytest.mark.parametrize("test_case", ["case1", "case2", "case3"])
def test_with_daemon(long_running_daemon, test_case):
    pods, namespace = long_running_daemon
    # All test cases share the same daemon instance
    # Daemon persists for entire worker session
```

Benefits:
- **Faster**: Amortize daemon startup cost across multiple tests
- **Session-scoped**: One daemon per worker, reused across tests
- **Worker-safe**: Each worker has its own daemon in a unique namespace

### Troubleshooting Parallel Execution

**Namespace conflicts:**
```bash
# Check for orphaned namespaces from crashed workers
kubectl get namespaces | grep styrene-test
kubectl delete namespace <namespace> --grace-period=0
```

**Worker failures:**
```bash
# Run with verbose xdist output
pytest tests/k8s/ -v -n auto --dist loadscope -vv

# Run with single worker for debugging
pytest tests/k8s/ -v -n 1
```

**Resource exhaustion:**
```bash
# Monitor cluster during parallel execution
watch kubectl top nodes
watch kubectl top pods -A

# Reduce worker count if cluster is overloaded
pytest tests/k8s/ -v -n 2  # fewer workers
```

## Test Organization

```
tests/k8s/
├── scenarios/
│   ├── test_edge_cases.py    # Network partition, identity corruption, etc.
│   ├── test_load.py           # Throughput, discovery scaling, RPC concurrency
│   └── test_scaling.py        # Horizontal scaling, resource limits
├── fixtures/
│   ├── configs/               # YAML configs per deployment mode
│   │   ├── standalone.yaml
│   │   ├── hub.yaml
│   │   ├── peer.yaml
│   │   └── gateway.yaml
│   └── topologies/            # Network topology definitions
│       ├── star.json          # Hub + clients
│       ├── mesh.json          # Full mesh
│       └── linear.json        # Linear chain
├── (container build via Nix — see nix/oci.nix)
│   └── container/entrypoint.sh # Container startup logic (wrapped by Nix)
├── helm/
│   └── styrened-test/         # Helm chart for test deployments
├── harness.py                 # K8sTestHarness orchestration class
└── conftest.py                # Pytest fixtures

```

## Test Scenarios

### Edge Cases (Priority 1)

**Network Partition** (`test_network_partition`)
- Isolates pod via NetworkPolicy
- Validates graceful degradation
- Restores connectivity and verifies recovery

**Identity Corruption** (`test_identity_corruption`)
- Deploys with invalid operator.key
- Verifies error handling
- Tests identity regeneration

**Hub Reconnection** (`test_hub_reconnection`)
- Simulates hub crash (delete pod)
- Validates client reconnection logic
- Measures recovery time

**Message Overflow** (`test_message_overflow`)
- Saturates message queue (50 rapid messages)
- Validates backpressure handling
- Checks for memory leaks

**RNS Initialization Failure** (`test_rns_init_failure`)
- Invalid RNS config (bad port, missing interface)
- Validates error reporting
- Tests fallback behavior

### Load Tests (Priority 2)

**Message Throughput** (`test_message_throughput`)
- 100 messages/min across 10 nodes
- Validates delivery rate ≥90%
- Measures latency percentiles

**Discovery Scaling** (`test_discovery_scaling`)
- 20 nodes announcing simultaneously
- Validates mesh convergence time
- Checks CPU/memory usage

**RPC Concurrency** (`test_rpc_concurrency`)
- 5 simultaneous exec commands
- Validates RPC isolation
- Measures response time

### Scaling Tests (Priority 3)

**Horizontal Scaling** (`test_horizontal_scaling`)
- Scale 1→5→10 pods
- Validates mesh adaptation
- Tests graceful scale-down

**Resource Limits** (`test_resource_limits`)
- CPU throttling (200m limit)
- Memory pressure (256Mi limit)
- Validates graceful degradation

**Network Bandwidth** (`test_network_bandwidth`)
- Saturates network with large messages
- Measures latency impact
- Validates congestion handling

## Fixtures

### `k8s_cluster` (session scope)
Provides K8sTestHarness instance with auto-detected cluster type (kind/k3d/cloud).
Worker-aware: each xdist worker gets its own harness instance.

```python
def test_example(k8s_cluster):
    cluster_type = k8s_cluster.cluster_type  # "kind", "k3d", or "cloud"
```

### `worker_id` (session scope)
Returns the current xdist worker ID ('master', 'gw0', 'gw1', etc.).
Useful for worker-aware logging and resource naming.

```python
def test_example(worker_id):
    print(f"Running on worker: {worker_id}")
```

### `test_namespace` (function scope)
Creates unique namespace per test, cleans up after completion.
Worker-aware: includes worker ID in namespace to prevent conflicts.

```python
def test_example(test_namespace):
    # test_namespace = "styrene-test-w0-a1b2c3d4" (worker 0)
    # test_namespace = "styrene-test-a1b2c3d4" (sequential)
    # Auto-deleted after test
```

### `long_running_daemon` (session scope)
Provides a persistent styrened daemon that lasts for the entire worker session.
Useful for tests that can share a daemon across multiple test cases.

```python
@pytest.mark.parametrize("rpc_call", ["status", "info", "peers"])
def test_rpc_calls(long_running_daemon, rpc_call):
    pods, namespace = long_running_daemon
    # All rpc_call variants share the same daemon
    # Much faster than deploying a new daemon per test
```

Benefits:
- Session-scoped: one daemon per worker, amortizes startup cost
- Worker-safe: each worker has its own isolated daemon
- Auto-cleanup: daemon and namespace deleted after worker session ends

### `styrened_stack` (function scope)
Returns callable for deploying test stacks.
Auto-cleanup: all deployed stacks are deleted after test completes.

```python
def test_example(styrened_stack):
    # Deploy 3 standalone nodes
    pods = styrened_stack(replica_count=3, mode="standalone")

    # Deploy hub + 5 peers
    hub_pods = styrened_stack(replica_count=1, mode="hub")
    peer_pods = styrened_stack(replica_count=5, mode="peer")
```

## K8sTestHarness API

```python
from harness import K8sTestHarness

harness = K8sTestHarness(namespace="default")

# Deploy stack
pods = harness.deploy_stack(
    release_name="test-001",
    replica_count=3,
    mode="standalone",
    rpc_enabled=True,
)

# Wait for ready
harness.wait_for_ready(pods, timeout=60)

# Execute command in pod
result = harness.exec_in_pod(pods[0], ["styrened", "--version"])
print(result.stdout)

# Collect logs
logs = harness.collect_logs(pods, output_dir=Path("/tmp/logs"))

# Cleanup
harness.cleanup("test-001")
```

## Configuration

Test deployments use Helm values from `helm/styrened-test/values.yaml`:

```yaml
replicaCount: 3

resources:
  limits:
    cpu: 200m
    memory: 256Mi
  requests:
    cpu: 100m
    memory: 128Mi

styrene:
  reticulum:
    mode: standalone  # standalone, hub, peer, gateway
    transport_enabled: false
    announce_interval: 300
  rpc:
    enabled: true
    bind_address: "0.0.0.0"
    bind_port: 5820
```

Override via `extra_values` parameter:

```python
pods = styrened_stack(
    replica_count=5,
    mode="peer",
    extra_values={
        "styrene.reticulum.announce_interval": 60,
        "resources.limits.memory": "512Mi",
    }
)
```

## Troubleshooting

### Pods Not Ready

```bash
# Check pod status
kubectl get pods -n <test_namespace>

# Describe pod
kubectl describe pod <pod_name> -n <test_namespace>

# View logs
kubectl logs <pod_name> -n <test_namespace>

# Check events
kubectl get events -n <test_namespace> --sort-by='.lastTimestamp'
```

### Image Pull Failures (Local K8s)

Ensure image is loaded into cluster:

```bash
# kind
kind load docker-image styrened-test:latest --name styrene-test

# k3d
k3d image import styrened-test:latest -c styrene-test
```

### Helm Deployment Failures

```bash
# List releases
helm list -n <test_namespace>

# Get release status
helm status <release_name> -n <test_namespace>

# Uninstall stuck release
helm uninstall <release_name> -n <test_namespace>
```

### Tests Hang

Check for orphaned resources:

```bash
# List all namespaces
kubectl get namespaces | grep styrene-test

# Force delete namespace
kubectl delete namespace <namespace> --grace-period=0 --force

# List all helm releases
helm list --all-namespaces | grep test
```

### Resource Exhaustion

Monitor cluster resources:

```bash
# Node resource usage
kubectl top nodes

# Pod resource usage
kubectl top pods -n <test_namespace>

# Describe node
kubectl describe node <node_name>
```

## CI/CD Integration

### Overview

Automated testing runs on **Argo Workflows** on the brutus K3s cluster, triggered by **Argo Events** GitHub webhooks. Templates live in `.argo/workflows/`. See [CONTAINERS.md](../../CONTAINERS.md) for the complete build pipeline and [RELEASE-PROCESS.md](../../docs/RELEASE-PROCESS.md) for full workflow documentation.

### Workflows

| Workflow | Trigger | Test Tier | Duration | Purpose |
|----------|---------|-----------|----------|---------|
| **pr-validation.yaml** | Pull requests | Smoke | ~5-7 min | Fast PR validation |
| **edge-build.yaml** | Push to main | N/A | ~10 min | Edge images for main |
| **nightly-tests.yaml** | Daily 2 AM UTC | Gated tiers | ~60-90 min | Nightly test suite |
| **release-build.yaml** | Tag push (v*) | N/A | ~15-30 min | Release + publish |

### Quick Reference

#### Submitting Manual Workflows

```bash
# Submit smoke tests manually
kubectl create -n argo -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: styrened-nightly-manual-
spec:
  workflowTemplateRef:
    name: styrened-nightly-tests
  arguments:
    parameters:
      - name: test-tier
        value: "smoke"
EOF

# Submit with integration tier
kubectl create -n argo -f - <<EOF
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: styrened-nightly-manual-
spec:
  workflowTemplateRef:
    name: styrened-nightly-tests
  arguments:
    parameters:
      - name: test-tier
        value: "smoke or integration"
EOF
```

#### Viewing Workflow Results

```bash
# List recent workflows
kubectl get workflows -n argo --sort-by=.metadata.creationTimestamp | grep styrened

# Watch a running workflow
kubectl get workflow <name> -n argo -w

# View workflow logs
kubectl logs -n argo -l workflows.argoproj.io/workflow=<name> --tail=100

# View via Argo UI
# https://argo.example.com/workflows/argo/<name>
```

#### Accessing Test Results

Test results are written to the workspace PVC during workflow execution:

- `smoke-results.xml` — JUnit XML for smoke tests
- `smoke-output.log` — Full test output
- `integration-results.xml` — JUnit XML for integration tests
- `integration-output.log` — Full test output

### CI Test Execution

#### PR Validation (Smoke Tests Only)

Triggered on pull request events (opened/synchronize/reopened):

1. **Checkout** — Authenticated clone via GHCR token
2. **Build test image** — `nix build .#oci-test` (validates build)
3. **Smoke tests** — `pytest tests/k8s/scenarios/ -m smoke -v --tb=short`
4. **Report status** — Posts GitHub commit status (success/failure)

Fast validation (~5-7 minutes).

#### Edge Build (Main Branch)

Triggered on push to main:

1. **Build OCI** — `nix build .#oci`
2. **Push to GHCR** — Tags with `edge` + commit SHA

Automatically publishes `ghcr.io/styrene-lab/styrened:edge` for bleeding-edge deployments.

#### Nightly Tests (All Tiers)

Triggered by CronWorkflow at 2 AM UTC:

1. **Smoke tier** — `pytest tests/k8s/scenarios/ -m smoke` (10 min timeout)
2. **Integration tier** — `pytest tests/k8s/scenarios/ -m integration` (30 min timeout, gated on smoke success)
3. **Comprehensive tier** — `pytest tests/k8s/scenarios/ -m comprehensive` (60 min timeout, gated on integration success)

Gated progression: each tier only runs if the previous tier succeeds.

#### Release Build (Full Suite)

Triggered on tag push matching `v*`:

1. **Parse version** — Extracts version from tag, detects prereleases
2. **Build wheel** + **Build OCI** (parallel)
3. **Push to GHCR** — Version + commit SHA tags (`latest` only for stable releases)
4. **Create GitHub Release** — Changelog, wheel, and source tarball

### CI Environment

| Component | Details |
|-----------|---------|
| Cluster | brutus K3s (amd64) |
| Workflow engine | Argo Workflows |
| Event trigger | Argo Events (GitHub webhooks) |
| Container runtime | containerd (K3s default) |
| Build tool | Nix (nix2container) |
| Python | 3.11 (python:3.11-slim) |
| GHCR auth | Vault-synced `ghcr-secret` |

### Debugging CI Failures

#### Common Issues

**Build failures:**
```bash
# Check workflow logs in Argo UI
# https://argo.example.com/workflows/argo/<workflow-name>

# Test build locally (same command as CI)
just build-test

# Or with nix directly
nix build .#oci-test -L
```

**Test timeouts:**
```bash
# Check workflow pod logs
kubectl logs -n argo -l workflows.argoproj.io/workflow=<name> --tail=200

# Check test namespace state
kubectl get pods -n styrene-test-<hash>
```

**Image pull failures:**
```bash
# Verify ghcr-secret exists in styrene-infra
kubectl get secret ghcr-secret -n styrene-infra

# Check VaultStaticSecret sync status
kubectl get vaultstaticsecret -n styrene-infra
```

#### Re-running Failed Workflows

```bash
# Resubmit a failed workflow
kubectl get workflow <failed-name> -n argo -o json | \
  jq 'del(.metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .status)' | \
  jq '.metadata.name = .metadata.generateName + "retry"' | \
  kubectl create -f -
```

### Local CI Simulation

Replicate CI environment locally:

```bash
# 1. Create kind cluster
kind create cluster --name styrene-test

# 2. Build test image (same command as CI)
just build-test

# 3. Load into kind
just load-k8s-image

# 4. Run smoke tests (same command as CI)
pytest tests/k8s/ -m smoke -v --tb=short -n 4 --dist loadscope

# 5. Cleanup
kind delete cluster --name styrene-test
```

**Alternative (using GHCR images):**
```bash
# Skip build, use nightly test images
podman pull ghcr.io/styrene-lab/styrened-test:latest
kind load docker-image ghcr.io/styrene-lab/styrened-test:latest --name styrene-test
pytest tests/k8s/ -m smoke -v --tb=short -n 4
```

### Performance Benchmarks

Expected execution times on brutus K3s cluster:

| Test Configuration | Sequential | 4 Workers | 8 Workers |
|-------------------|------------|-----------|-----------|
| Smoke only | ~10 min | ~3 min | ~2 min |
| Integration only | ~30 min | ~10 min | ~7 min |
| Comprehensive only | ~2 hrs | ~40 min | ~25 min |
| Full suite | ~2.5 hrs | ~50 min | ~35 min |

**Note**: Times may vary based on cluster load and test distribution.

### Justfile Recipes Reference

**Image Building:**
```bash
just build-test            # Build OCI test image (nix build .#oci-test)
just load-k8s-image        # Load image into cluster (auto-detect kind/k3d/k3s)
```

**Local Testing Workflow:**
```bash
just test-k8s-local        # Build, load, run smoke tests (local images)
just test-k8s-deploy       # Build, load, deploy to cluster
just test-k8s-run          # Run tests (assumes already deployed)
```

**Remote Testing Workflow (GHCR):**
```bash
just test-k8s-remote       # Full remote workflow (create secret, deploy from GHCR, test)
just create-ghcr-secret    # Create ImagePullSecret for GHCR
just verify-ghcr-secret    # Verify secret exists
just delete-ghcr-secret    # Delete ImagePullSecret
just helm-install-ghcr     # Deploy using GHCR images
```

**Helm Operations:**
```bash
just helm-install          # Deploy with local images
just helm-install-ghcr     # Deploy with GHCR images
just helm-uninstall        # Remove deployment
just helm-status           # Show deployment status
just helm-logs             # Show pod logs
just helm-template         # Render templates (dry-run)
```

### Additional Resources

- **Remote Cluster Testing**: [REMOTE-TESTING.md](./REMOTE-TESTING.md)
- **Container Build Pipeline**: [CONTAINERS.md](../../CONTAINERS.md)
- **Release Process**: [RELEASE-PROCESS.md](../../docs/RELEASE-PROCESS.md)
- **Argo Workflow Templates**: [.argo/workflows/](../../.argo/workflows/)
- **Main Project README**: [README.md](../../README.md)
- **K8s Testing Guide**: [TESTING-GUIDE.md](./TESTING-GUIDE.md)

## Performance Targets

| Test Category | Target Completion Time | Resource Usage |
|---------------|------------------------|----------------|
| Edge Cases | <5min | <1 core, <1GB RAM |
| Load Tests | <10min | <2 cores, <2GB RAM |
| Scaling Tests | <15min | <3 cores, <3GB RAM |

**Total Suite**: <30min, <3 cores, <3GB RAM

## Development Workflow

1. **Write test** in `scenarios/test_*.py`
2. **Add fixture config** if needed (new deployment mode)
3. **Build image**: `just build-test`
4. **Load image**: `kind load docker-image styrene-lab/styrened-test:test --name <cluster>`
5. **Run test**: `pytest tests/k8s/scenarios/test_*.py::test_name -v`
6. **Debug**: Collect logs via `harness.collect_logs(pods, output_dir=...)`
7. **Iterate**: Rebuild image, reload, retest

**Quick iteration loop:**
```bash
# Make code changes, then:
just build-test && \
  kind load docker-image styrene-lab/styrened-test:test --name styrene-test && \
  pytest tests/k8s/ -m smoke -v -n auto
```

## Architecture Notes

- **StatefulSet**: Stable pod DNS names for predictable addressing
- **Headless Service**: Direct pod-to-pod communication (no load balancing)
- **NetworkPolicy**: Controlled pod isolation for partition tests
- **ConfigMaps**: Config/RNS config injection per deployment
- **nix2container**: Reproducible OCI builds with smart layer splitting
- **Namespace Isolation**: Clean slate per test, parallel execution safe
- **Helm Templating**: Parameterized deployments, easy config variations

## References

- Helm chart: `helm/styrened-test/`
- OCI image config: `../../nix/oci.nix`
- Nix package: `../../nix/package.nix`
- Nix dependencies: `../../nix/deps.nix`
- Entrypoint: `../../container/entrypoint.sh`
- Test harness: `harness.py`
- Pytest config: `conftest.py`
- Setup guide: `README-setup.md` (detailed cluster setup)
