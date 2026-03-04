# Release Process

This document describes the release and testing workflows for styrened.

## Overview

CI/CD runs on **Argo Workflows** on the brutus K3s cluster, triggered by **Argo Events** GitHub webhooks. The pipeline is split into separate workflow templates:

1. **Release Build** (`release-build.yaml`) - Builds and publishes artifacts on tag push
2. **Edge Build** (`edge-build.yaml`) - Builds and pushes edge images on push to main
3. **PR Validation** (`pr-validation.yaml`) - Smoke tests on pull requests
4. **Nightly Tests** (`nightly-tests.yaml`) - Tiered test suite run via cron

Argo Events maps GitHub webhook events (push, tag, pull_request) to workflow submissions via a sensor in the infrastructure repo (`apps/argo-events/sensor-styrened.yaml`).

## Release Workflow

### Triggering a Release

Releases are triggered by pushing a version tag. Version is canonical in `src/styrened/__init__.py` (hatchling reads it dynamically). The `VERSION` file mirrors it for the Nix flake.

```bash
# Preferred: use justfile (validates, bumps, commits, tags)
just release X.Y.W
git push origin main --tags
```

Or manually:

```bash
# 1. Update version in both canonical files
sed -i '' 's/__version__ = "X.Y.Z"/__version__ = "X.Y.W"/' src/styrened/__init__.py
echo "X.Y.W" > VERSION

# 2. Commit version bump
git add src/styrened/__init__.py VERSION
git commit -m "chore: bump version to X.Y.W"

# 3. Push and tag
git push
git tag -a vX.Y.W -m "Release vX.Y.W"
git push origin vX.Y.W
```

### What the Release Workflow Does

1. **Checkout** - Authenticated clone of private repo using GHCR token
2. **Parse Version** - Extracts version from tag, detects prereleases (rc/alpha/beta/dev)
3. **Build Python Wheel** - Creates wheel and sdist
4. **Build OCI Image** - Builds linux/amd64 container via Nix (nix2container)
5. **Push to GHCR** - Pushes with version + commit SHA tags (`latest` only for stable releases)
6. **Publish to PyPI** - Uploads wheel and sdist via twine (idempotent with `--skip-existing`)
7. **Create GitHub Release** - Generates changelog, publishes release with wheel and source tarball

### Release Artifacts

| Artifact | Location |
|----------|----------|
| PyPI package | `pip install styrened==X.Y.Z` |
| Python wheel | GitHub Release: `styrened-X.Y.Z-py3-none-any.whl` |
| Source tarball | GitHub Release: `styrened-X.Y.Z.tar.gz` |
| Container (amd64) | `ghcr.io/styrene-lab/styrened:X.Y.Z` |
| Latest tag | `ghcr.io/styrene-lab/styrened:latest` (stable releases only) |

### Version Tagging Strategy

| Tag Pattern | Example | `latest` tag | Notes |
|-------------|---------|--------------|-------|
| Stable | `v0.3.4` | Yes | Production releases |
| Prerelease | `v0.4.0-rc1` | No | Release candidates |
| Alpha | `v0.4.0-alpha1` | No | Early testing |
| Beta | `v0.4.0-beta1` | No | Feature complete, testing |

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

## Integration Testing

Integration tests run on the brutus K3s cluster, either via nightly cron or manually.

### Test Tiers

| Tier | Duration | Scope | When to Use |
|------|----------|-------|-------------|
| `smoke` | ~10 min | Basic functionality, 1-2 pods | PR validation, quick checks |
| `integration` | ~30 min | Multi-pod scenarios, 3-5 pods | Pre-release validation |
| `comprehensive` | ~60 min | Large topologies, 6+ pods | Major releases |
| `all` | ~90+ min | Everything including slow tests | Full validation |

### Running Integration Tests

#### Via Argo Workflows (brutus cluster)

```bash
# Submit manually via kubectl
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

Nightly tests run automatically at 2 AM UTC via `cron-nightly.yaml`.

#### Locally Against brutus

```bash
# Set up kubeconfig
export KUBECONFIG=~/.kube/config-brutus

# Run smoke tests
pytest tests/k8s/scenarios/ -m smoke -v -n 4

# Run integration tests
pytest tests/k8s/scenarios/ -m "smoke or integration" -v -n 4

# Run comprehensive tests
pytest tests/k8s/scenarios/ -m "smoke or integration or comprehensive" -v -n 4

# Run all tests including slow
pytest tests/k8s/scenarios/ -v --run-slow -n 4
```

### Test Markers

Tests are marked with pytest markers for selective execution:

```python
@pytest.mark.smoke           # Fast, basic validation
@pytest.mark.integration     # Multi-component scenarios
@pytest.mark.comprehensive   # Large-scale tests
@pytest.mark.slow            # Extended duration (requires --run-slow)
@pytest.mark.propagation     # LXMF propagation tests
@pytest.mark.resilience      # Failover and recovery
@pytest.mark.convergence     # Mesh discovery
```

### Test Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `STYRENED_TEST_IMAGE_REPO` | Container image repository | `ghcr.io/styrene-lab/styrened-test` |
| `STYRENED_TEST_IMAGE_TAG` | Container image tag | `dev` (cloud) / `local-amd64` (kind/k3d) |
| `METRICS_ENABLED` | Collect periodic metrics | `true` |
| `METRICS_INTERVAL` | Metrics snapshot interval (seconds) | `300` |

## Edge Builds

The `edge` tag is automatically updated on every push to `main` via the `edge-build.yaml` workflow template:

```bash
docker pull ghcr.io/styrene-lab/styrened:edge
```

Use edge builds for:
- Testing unreleased features
- CI/CD pipelines that track main
- Development environments

## Nightly Builds

Nightly builds run tiered test suites:

- **Schedule**: 2 AM UTC daily (via `cron-nightly.yaml` CronWorkflow)
- **Image**: Uses `ghcr.io/styrene-lab/styrened-test:dev`
- **Tests**: Smoke → Integration → Comprehensive (gated progression)

## Troubleshooting

### Release Workflow Fails

1. **Version mismatch**: Ensure `src/styrened/__init__.py` and `VERSION` match the tag (run `just check-versions`)
2. **GHCR push denied**: Check package permissions at https://github.com/orgs/styrene-lab/packages/container/package/styrened/settings
3. **Build fails**: Check workflow logs in Argo UI at https://argo.example.com

### Integration Tests Fail

1. **Image pull errors**: Verify the image tag exists in GHCR
2. **Namespace stuck**: Run cleanup script `tests/k8s/cleanup-test-resources.sh`
3. **Timeout**: Increase test timeout or reduce parallelism (`-n 2`)

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `denied: installation not allowed to Write` | Missing package permission | Add repo to package settings with Write access |
| `manifest unknown` | Image tag doesn't exist | Check GHCR for available tags |
| `VERSION file` override | Stale VERSION file | Run `just check-versions` to verify `__init__.py` == `VERSION` |

## Workflow Files

| File | Purpose |
|------|---------|
| `.argo/workflows/release-build.yaml` | Release build and publish |
| `.argo/workflows/edge-build.yaml` | Edge builds from main |
| `.argo/workflows/pr-validation.yaml` | PR smoke tests |
| `.argo/workflows/nightly-tests.yaml` | Tiered nightly test suite |
| `.argo/workflows/cron-nightly.yaml` | CronWorkflow scheduling nightly tests |

## Infrastructure

### Cluster Resources (brutus)

| Resource | Namespace | Purpose |
|----------|-----------|---------|
| `ci-workflow-sa` ServiceAccount | `argo` | Workflow pod identity |
| `ci-test-runner` ClusterRole | cluster | Namespace/pod/helm RBAC for test harness |
| `ghcr-secret` Secret | `argo` | GHCR registry auth (Vault-synced) |
| `pypi-secret` Secret | `argo` | PyPI API token (Vault-synced from `secret/bootstrap/pypi/styrene-lab`) |
| `ghcr-secret` Secret | `styrene-infra` | GHCR auth source for test namespace copies |
| `operate-workflow-sa` ServiceAccount | `argo-events` | Sensor → Workflow submission |

### Argo Events (infrastructure repo)

| File | Purpose |
|------|---------|
| `apps/argo-events/eventsource-github.yaml` | GitHub webhook receiver |
| `apps/argo-events/sensor-styrened.yaml` | Event → Workflow mapping |
| `apps/argo-events/eventbus.yaml` | JetStream message bus |
| `apps/argo-events/sensor-rbac.yaml` | Sensor service account RBAC |

## Security Notes

- The styrened repo is **private** within the styrene-lab org
- Container images are published to GHCR with **internal** visibility
- All git operations from cluster pods use token authentication via Vault-managed GHCR credentials
- Workflow pods run as `ci-workflow-sa` with least-privilege RBAC scoped to test operations
