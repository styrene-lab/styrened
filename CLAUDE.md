# CLAUDE.md

Development guidance for this repository.

## Development Philosophy

### Test-Driven Development (TDD)

This project follows strict TDD practices. All new functionality must be developed test-first:

1. **Write the test first** - Define expected behavior before implementation
2. **Run the test, watch it fail** - Confirms the test is actually testing something
3. **Write minimal code to pass** - Only implement what's needed to satisfy the test
4. **Refactor** - Clean up while keeping tests green
5. **Repeat** - Red → Green → Refactor cycle

**Test hierarchy** (write tests at the appropriate level):
- **Unit tests** (`tests/unit/`) - Pure logic, no I/O, fast (<100ms each)
- **Integration tests** (`tests/integration/`) - Component interactions, may use mocks
- **Scenario tests** (`tests/scenarios/`) - Cross-platform (SSH/K8s), real infrastructure
- **K8s tests** (`tests/k8s/scenarios/`) - Kubernetes-specific, uses test harness

**When modifying existing code**:
- If tests don't exist, write them first to capture current behavior
- Then modify tests to reflect new expected behavior
- Then change the implementation

**Test naming convention**:
```python
def test_<unit>_<scenario>_<expected_outcome>():
    """Docstring explains the behavior being tested."""
```

**Coverage expectations**:
- New features: 80%+ coverage required
- Bug fixes: Must include regression test
- Refactors: Existing tests must continue to pass

## Project Overview

Styrened is a headless daemon for running Styrene services on Reticulum mesh networks. It's optimized for resource-constrained edge devices and supports deployment via Nix flakes, containers, or PyPI. The styrene-core library and styrene-tui have been merged into this package.

**Key features**: RPC server for remote management, auto-reply handler, device discovery, optional HTTP API, optional TUI (`pip install styrened[tui]`).

## Commands

```bash
# Development setup
make install              # Install with dev dependencies
pip install -e ".[tui,dev]"  # Install with TUI + dev dependencies

# Testing
make test                 # Run all tests
make test-unit            # Run unit tests only (excludes k8s)
make test-k8s             # Run k8s integration tests
pytest tests/tui/models/ -v  # Run TUI model tests
pytest tests/test_models.py::test_name -v  # Run single test

# Code quality
make lint                 # Run ruff linter
make format               # Format with ruff
make typecheck            # Run mypy
make validate             # Run lint + typecheck + test

# Container Build (Nix OCI — no Dockerfile)
just build-wheel          # Build Python wheel to dist/
just build                # Build OCI production image (nix build .#oci)
just build-test           # Build OCI test image (nix build .#oci-test)
just load                 # Load production image into podman
just load-test            # Load test image into podman
just test-image           # Validate production image works
just test-image-test      # Validate test image works

# Container Push (ghcr.io)
just container-login      # Login to GHCR (requires GITHUB_TOKEN)
just push-prod            # Push production with version tags
just push-prod-latest     # Push production with 'latest' tag (releases)
just push-edge            # Push edge build (main branch)
just push-test-nightly    # Push test image with 'latest' tag

# Container Utilities
just version              # Show version info
just clean-images         # Remove local images

# Documentation
make docs                 # Generate API docs to docs/api/
make docs-serve           # Serve docs locally with live reload
make docs-clean           # Remove generated docs

# Run daemon
styrened                  # Run daemon (default)
styrened daemon           # Run daemon explicitly

# CLI tools for interactive testing
styrened devices              # List discovered mesh devices
styrened devices -w 10        # Wait 10s for announces
styrened status               # Show local daemon health (hub, interfaces, mesh)
styrened status <dest>        # Query remote node status
styrened doctor              # Run installation diagnostics
styrened doctor --offline    # Skip PyPI version check
styrened doctor --fix        # Auto-fix simple issues (create dirs, identity)
styrened doctor --setup      # Interactive setup wizard
styrened send <dest> "msg"    # Send chat message to node
styrened exec <dest> uptime   # Execute command on remote
styrened announce             # Trigger local announce
styrened identity             # Show local operator identity
styrened identity --create    # Create identity if missing
```

## Architecture

```
src/styrened/
├── cli.py              # CLI entry point with subcommands (devices, status, send, exec, etc.)
├── daemon.py           # Main StyreneDaemon class - orchestrates all services
├── models/             # Data models (dataclasses)
│   ├── config.py       # CoreConfig - central configuration model
│   ├── mesh_device.py  # MeshDevice, DeviceType, NodeStatus
│   ├── messages.py     # SQLAlchemy message persistence
│   ├── reticulum.py    # ReticulumIdentity, ReticulumInterface
│   ├── rns_error.py    # RNS error state tracking
│   └── styrene_wire.py # StyreneEnvelope wire protocol
├── services/           # Business logic
│   ├── config.py       # YAML config loading/saving
│   ├── lifecycle.py    # CoreLifecycle - init/shutdown orchestration
│   ├── reticulum.py    # Mesh initialization, announce handling
│   ├── rns_service.py  # RNS destination caching
│   ├── lxmf_service.py # LXMF router and message handling
│   ├── auto_reply.py   # Auto-reply with cooldown tracking
│   ├── doctor.py       # Installation diagnostics and setup wizard
│   ├── hub_connection.py
│   └── node_store.py   # Device storage/queries
├── rpc/                # Remote procedure calls over LXMF
│   ├── server.py       # Handles status_request, exec, reboot, update_config
│   ├── client.py       # Sends RPC commands
│   ├── messages.py     # Request/response message types
│   └── errors.py       # RPCError, RPCTimeoutError
├── protocols/          # LXMF protocol handlers
│   ├── base.py         # Abstract Protocol base class
│   ├── chat.py         # Chat protocol (NomadNet/MeshChat)
│   ├── styrene.py      # Styrene-specific protocol
│   └── registry.py     # Protocol routing via fields["protocol"]
└── tui/                # Terminal UI (optional, pip install styrened[tui])
    ├── app.py          # Main StyreneApp (Textual)
    ├── dashboard_app.py # Compact local dashboard
    ├── cli/            # TUI-specific CLI commands
    ├── models/         # TUI data models (config, fleet, hardware)
    ├── screens/        # TUI screens (dashboard, inbox, settings, etc.)
    ├── services/       # TUI services (lifecycle, IPC bridge, provisioner)
    ├── widgets/        # Custom Textual widgets
    ├── themes/         # Imperial CRT theming system
    ├── forge/          # Edge device provisioning (disk detect, nix build)
    └── styles/         # TCSS stylesheets
```

**Async-first**: All network operations use asyncio. The daemon runs an event loop with periodic tasks for announces and cleanup.

**Configuration hierarchy**: `~/.styrene/config.yaml` → `/etc/styrene/config.yaml` → defaults

**Protocol discrimination**: LXMF messages are routed to handlers based on `fields["protocol"]` dictionary.

## Testing

### Test Tiers

Tests are organized in tiers with pytest markers:

**Smoke** - Fast validation (<2 min per test, <20 min total)
- Single or dual pod tests
- Wire protocol validation (no pod deployment)
- Basic functionality checks
- Use for: PR validation, rapid feedback

**Integration** - Moderate complexity (<10 min per test)
- Multi-pod scenarios (3-5 pods)
- Hub-based routing and multi-component interactions
- Basic resilience tests
- Use for: Nightly runs, main branch validation

**Comprehensive** - Deep validation (<30 min per test)
- Large mesh topologies (8+ pods)
- Extended duration tests (10+ min)
- Multi-hop propagation, sustained operations
- Use for: Pre-release validation, weekly comprehensive runs

**Slow** - Load/scaling tests (requires --run-slow flag)
- All mesh_propagation tests
- Load testing scenarios (100+ messages, 20+ nodes)
- Use for: Performance validation, major releases

**Domain Markers** (orthogonal to tiers):
- `propagation` - LXMF propagation and multi-hop routing
- `resilience` - Failover and recovery scenarios
- `convergence` - Mesh discovery and convergence
- `rns_singleton` - Tests requiring RNS singleton isolation

**Tier Assignment Guidelines**:
- Pod count: 1-2 pods → smoke, 3-5 pods → integration, 6+ pods → comprehensive
- Duration: <2 min → smoke, 2-10 min → integration, 10-30 min → comprehensive
- Complexity: Wire protocol → smoke, multi-component → integration, large topologies → comprehensive
- Resource stress: CPU/memory throttling → integration or comprehensive

**Examples**:
```bash
# Fast PR validation (smoke tier)
pytest tests/k8s/scenarios/ -m smoke -v -n 4

# Nightly validation (smoke + integration)
pytest tests/k8s/scenarios/ -m "smoke or integration" -v -n 8

# Pre-release comprehensive (all except slow)
pytest tests/k8s/scenarios/ -v -n 8

# Weekly full suite (including slow tests)
pytest tests/k8s/scenarios/ -v --run-slow -n 8

# Specific domain tests
pytest tests/k8s/scenarios/ -m propagation -v --run-slow
```

K8s tests use `tests/k8s/harness.py` (K8sTestHarness) for Helm deployment automation.

### Metrics Collection for Long-Running Tests

Overnight tests (4-8+ hours) automatically collect periodic metrics snapshots for leak detection and performance trending.

**Metrics Collection**:
- Snapshots collected every 5 minutes (configurable via `METRICS_INTERVAL`)
- Stored locally at `/tmp/styrene-test-metrics/{test_name}_{timestamp}/`
- Written to workspace PVC during CI runs
- Includes CPU, memory, pod status, and mesh state

**File Structure**:
```
/tmp/styrene-test-metrics/
└── test_8_hour_stability_1738454321/
    ├── metadata.json              # Test run metadata
    ├── summary.json               # Aggregated statistics
    └── snapshots/
        ├── snapshot_000.json      # T+0
        ├── snapshot_001.json      # T+5min
        └── ...                    # One per interval
```

**Environment Variables**:
```bash
# Adjust snapshot interval (default: 300 seconds)
METRICS_INTERVAL=120 pytest tests/k8s/scenarios/test_overnight_stability.py

# Disable metrics collection (faster for debugging)
METRICS_ENABLED=false pytest tests/k8s/scenarios/test_overnight_stability.py
```

**Downloading Metrics from CI**:
```bash
# Download from latest nightly build
./scripts/download_metrics.sh nightly-build latest

# Download from specific run ID
./scripts/download_metrics.sh nightly-build 1234567890
```

**Analyzing Metrics**:
```bash
# Analyze single test run
python scripts/analyze_metrics.py /tmp/styrene-test-metrics/test_8_hour_stability_*/

# Analyze all runs
python scripts/analyze_metrics.py /tmp/styrene-test-metrics/ --all

# Compare two runs
python scripts/analyze_metrics.py --compare \\
  metrics-analysis/nightly-2026-02-01/ \\
  metrics-analysis/nightly-2026-02-02/

# Generate markdown report
python scripts/analyze_metrics.py /tmp/styrene-test-metrics/test_8_hour/ -o report.md
```

**Memory Leak Detection**:
- Linear regression on memory over time
- Threshold: >10 MB/hour growth indicates potential leak
- Analysis script automatically calculates growth rate

**Overnight Test Markers**:
- `slow_extended` - 4-8+ hour tests requiring `--run-slow`
- Use for production readiness validation

K8s tests use `tests/k8s/harness.py` (K8sTestHarness) for Helm deployment automation.

### K8s Test Cleanup

K8s tests create ephemeral namespaces (prefixed with `styrene-test-` or `styrene-daemon-`) that are automatically cleaned up after tests complete. However, interrupted tests (Ctrl+C) or cleanup failures can leave orphaned resources.

**Automatic Cleanup**:
- Session-level fixture automatically cleans up orphaned namespaces (>10 min old) before tests start
- Function-level namespaces are deleted after each test
- All namespaces are labeled with `styrened-test=true` for easy identification

**Manual Cleanup**:

```bash
# List test namespaces and resources
just test-k8s-list

# Clean up with confirmation prompt
just test-k8s-cleanup

# Force cleanup without confirmation
just test-k8s-cleanup-force

# Or use the script directly
./tests/k8s/cleanup-test-resources.sh --list
./tests/k8s/cleanup-test-resources.sh
./tests/k8s/cleanup-test-resources.sh --force
```

**Troubleshooting Leftover Resources**:

If you see namespaces stuck in "Terminating" state:
```bash
# Check namespace status
kubectl get namespaces | grep styrene

# Force delete stuck namespace (last resort)
kubectl delete namespace <namespace> --grace-period=0 --force

# Check for finalizers blocking deletion
kubectl get namespace <namespace> -o json | jq '.spec.finalizers'
```

**Preventing Resource Leakage**:
- The test suite automatically cleans orphaned namespaces older than 10 minutes
- Namespace labels enable bulk cleanup: `kubectl delete namespaces -l styrened-test=true`
- Run `just test-k8s-cleanup` periodically if doing frequent test runs
- Consider using ephemeral clusters (kind/k3d) that can be deleted entirely

## Iterative Testing (Two-Machine)

For hands-on peer testing between two machines on the same LAN:

**Machine A (server/hub)** - e.g., MacBook:
```yaml
# ~/.config/styrene/core-config.yaml
reticulum:
  mode: standalone
  interfaces:
    server:
      enabled: true
      listen_ip: 0.0.0.0
      port: 4242
```
Then: `styrened daemon`

**Machine B (client)** - e.g., Desktop:
```yaml
# ~/.config/styrene/core-config.yaml
reticulum:
  mode: standalone
  interfaces:
    peers:
      - host: <machine-a-ip>
        port: 4242
```
Then:
```bash
styrened devices -w 15          # Discover Machine A
styrened status <dest-hash>     # Query its status
styrened send <dest-hash> "hi"  # Send a message
styrened exec <dest-hash> uptime # Run command remotely
```

Watch daemon logs on both sides to observe announces, message delivery, and RPC handling.

## CI/CD

CI/CD runs on **Argo Workflows** (brutus K3s cluster), triggered by **Argo Events** GitHub webhooks. GitHub Actions workflows have been removed. See [docs/RELEASE-PROCESS.md](docs/RELEASE-PROCESS.md) for detailed documentation.

### Workflows

Templates live in `.argo/workflows/`. Argo Events maps GitHub events to workflow submissions via a sensor in the vanderlyn repo (`apps/argo-events/sensor-styrened.yaml`).

| Template | Trigger | Purpose |
|----------|---------|---------|
| `release-build.yaml` | Git tags `v*` | Build wheel + OCI, push to GHCR, create GitHub Release |
| `edge-build.yaml` | Push to main | Build + push OCI with `edge` tag |
| `pr-validation.yaml` | PRs to main | Build test image, run smoke tests, report GitHub status |
| `nightly-tests.yaml` | Referenced by cron | Tiered test suite (smoke → integration → comprehensive) |
| `cron-nightly.yaml` | Daily 2 AM UTC | CronWorkflow that invokes `nightly-tests` |

All workflows run as `ci-workflow-sa` and use GHCR credentials from Vault-synced `ghcr-secret`. Test namespaces get a copy of `ghcr-secret` from the `styrene-infra` namespace (managed by vault-secrets-operator). The test harness image tag can be overridden via `STYRENED_TEST_IMAGE_TAG` and `STYRENED_TEST_IMAGE_REPO` env vars.

### Release Process

Version is canonical in `src/styrened/__init__.py` (hatchling reads it). The `VERSION` file mirrors it for Nix.

```bash
# Preferred: use justfile
just release X.Y.W    # validate → bump → commit → tag

# Manual:
sed -i '' 's/__version__ = "X.Y.Z"/__version__ = "X.Y.W"/' src/styrened/__init__.py
echo "X.Y.W" > VERSION
git add src/styrened/__init__.py VERSION
git commit -m "chore: bump version to X.Y.W"
git push
git tag -a vX.Y.W -m "Release vX.Y.W"
git push origin vX.Y.W
```

The `release-build` workflow then:
1. Extracts version from tag, detects prerelease (rc/alpha/beta/dev)
2. Builds Python wheel and sdist
3. Builds OCI image via Nix (`nix build .#oci`)
4. Pushes to GHCR with version + commit SHA tags (`latest` only for stable releases)
5. Publishes to PyPI via twine
6. Generates changelog from commits since previous tag
7. Creates GitHub Release with wheel and source tarball

### Integration Testing

Integration tests run on the brutus cluster, either via nightly cron or manually:

```bash
# Locally against brutus
export KUBECONFIG=~/.kube/config-brutus
pytest tests/k8s/ -m smoke -v -n 4

# Nightly (automatic via cron-nightly.yaml)
# Runs smoke + integration tiers at 2 AM UTC

# Submit manually via Argo CLI
argo submit -n argo --from workflowtemplate/styrened-nightly-tests \
  -p test-tier="all"
```

Test tiers:
- `smoke` - Fast validation (~10 min)
- `integration` - Multi-pod scenarios (~30 min)
- `comprehensive` - Large topologies (~60 min)
- `all` - Everything including slow tests (~90+ min)

### Image Strategy

| Image | Tags | Purpose |
|-------|------|---------|
| `ghcr.io/styrene-lab/styrened` | `X.Y.Z`, `latest`, `edge`, `<sha>` | Production deployments |
| `ghcr.io/styrene-lab/styrened-test` | `latest`, `<sha>` | CI testing |

### Installation

```bash
# From PyPI (preferred)
pip install styrened
pip install styrened[web]    # with FastAPI/uvicorn

# From GitHub Release (wheel)
pip install https://github.com/styrene-lab/styrened/releases/download/vX.Y.Z/styrened-X.Y.Z-py3-none-any.whl

# From git tag
pip install git+https://github.com/styrene-lab/styrened.git@vX.Y.Z

# Container
docker pull ghcr.io/styrene-lab/styrened:X.Y.Z
```
