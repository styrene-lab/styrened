# Release Process

This document describes the release and testing workflows for styrened.

## Overview

The release pipeline is split into two separate workflows:

1. **Release Build** (`release.yml`) - Builds and publishes artifacts
2. **Integration Tests** (`integration-tests.yml`) - K8s testing, run separately

This separation ensures releases aren't blocked by test infrastructure issues and allows testing against different clusters on-demand.

## Release Workflow

### Triggering a Release

Releases are triggered by pushing a version tag:

```bash
# 1. Update version in both files
sed -i '' 's/version = "X.Y.Z"/version = "X.Y.W"/' pyproject.toml
sed -i '' 's/__version__ = "X.Y.Z"/__version__ = "X.Y.W"/' src/styrened/__init__.py

# 2. Commit version bump
git add pyproject.toml src/styrened/__init__.py
git commit -m "chore: Bump version to X.Y.W"

# 3. Push and tag
git push
git tag -a vX.Y.W -m "Release vX.Y.W"
git push origin vX.Y.W
```

Or use the justfile helper:

```bash
just bump-version X.Y.W
just release X.Y.W
```

### What the Release Workflow Does

1. **Validate Release Tag** - Extracts version, detects prereleases (rc/alpha/beta)
2. **Build Python Wheel** - Creates wheel and sdist, verifies version matches tag
3. **Build Multi-Arch Images** - Builds linux/amd64 and linux/arm64 containers
4. **Generate Changelog** - Creates changelog from commits since last tag
5. **Create GitHub Release** - Publishes release with all artifacts

### Release Artifacts

| Artifact | Location |
|----------|----------|
| Python wheel | GitHub Release: `styrened-X.Y.Z-py3-none-any.whl` |
| Source tarball | GitHub Release: `styrened-X.Y.Z.tar.gz` |
| Container (amd64) | `ghcr.io/styrene-lab/styrened:X.Y.Z` |
| Container (arm64) | `ghcr.io/styrene-lab/styrened:X.Y.Z` |
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
# From GitHub Release (wheel)
pip install https://github.com/styrene-lab/styrened/releases/download/vX.Y.Z/styrened-X.Y.Z-py3-none-any.whl

# From git tag
pip install git+https://github.com/styrene-lab/styrened.git@vX.Y.Z

# Container
docker pull ghcr.io/styrene-lab/styrened:X.Y.Z
```

## Integration Testing

Integration tests are run separately from releases to avoid coupling release availability to test infrastructure.

### Test Tiers

| Tier | Duration | Scope | When to Use |
|------|----------|-------|-------------|
| `smoke` | ~10 min | Basic functionality, 1-2 pods | PR validation, quick checks |
| `integration` | ~30 min | Multi-pod scenarios, 3-5 pods | Pre-release validation |
| `comprehensive` | ~60 min | Large topologies, 6+ pods | Major releases |
| `all` | ~90+ min | Everything including slow tests | Full validation |

### Running Integration Tests

#### Via GitHub Actions (kind cluster)

1. Go to Actions → Integration Tests → Run workflow
2. Select:
   - **image_tag**: Version to test (e.g., `0.3.4`, `latest`, `edge`)
   - **test_tier**: Test scope (`smoke`, `integration`, `comprehensive`, `all`)
   - **cluster**: `kind` (ephemeral CI cluster)

#### Locally Against brutus

```bash
# Set up kubeconfig
export KUBECONFIG=~/.kube/config-brutus

# Run smoke tests
pytest tests/k8s/ -m smoke -v -n 4

# Run integration tests
pytest tests/k8s/ -m "smoke or integration" -v -n 4

# Run comprehensive tests
pytest tests/k8s/ -m "smoke or integration or comprehensive" -v -n 4

# Run all tests including slow
pytest tests/k8s/ -v --run-slow -n 4
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
| `STYRENED_TEST_IMAGE` | Container image to test | `styrened-test:latest` |
| `STYRENED_TEST_CLUSTER` | Target cluster name | `kind` |
| `METRICS_ENABLED` | Collect periodic metrics | `true` |
| `METRICS_INTERVAL` | Metrics snapshot interval (seconds) | `300` |

## Edge Builds

The `edge` tag is automatically updated on every push to `main`:

```bash
docker pull ghcr.io/styrene-lab/styrened:edge
```

Use edge builds for:
- Testing unreleased features
- CI/CD pipelines that track main
- Development environments

## Nightly Builds

Nightly builds run comprehensive tests and publish test images:

- **Schedule**: 2 AM UTC daily
- **Image**: `ghcr.io/styrene-lab/styrened-test:latest`
- **Tests**: Smoke + Integration + Comprehensive tiers

## Troubleshooting

### Release Workflow Fails

1. **Version mismatch**: Ensure `pyproject.toml` and `src/styrened/__init__.py` match the tag
2. **GHCR push denied**: Check package permissions at https://github.com/orgs/styrene-lab/packages/container/package/styrened/settings
3. **Build fails**: Check Docker build logs in the workflow run

### Integration Tests Fail

1. **Image pull errors**: Verify the image tag exists in GHCR
2. **Namespace stuck**: Run cleanup script `tests/k8s/cleanup-test-resources.sh`
3. **Timeout**: Increase test timeout or reduce parallelism (`-n 2`)

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `denied: installation not allowed to Write` | Missing package permission | Add repo to package settings with Write access |
| `manifest unknown` | Image tag doesn't exist | Check GHCR for available tags |
| `VERSION file` override | Stale VERSION file | Remove VERSION file, use pyproject.toml |

## Workflow Files

| File | Purpose |
|------|---------|
| `.github/workflows/release.yml` | Release build and publish |
| `.github/workflows/integration-tests.yml` | K8s integration testing |
| `.github/workflows/edge-build.yml` | Edge builds from main |
| `.github/workflows/nightly-build.yml` | Nightly comprehensive tests |
| `.github/workflows/pr-validation.yml` | PR smoke tests |

## Security Notes

- The styrened repo is **private** within the styrene-lab org
- Container images are published to GHCR with **internal** visibility
- Integration tests against brutus are run **locally only** (no CI access to production clusters)
- GitHub Actions use `GITHUB_TOKEN` with minimal permissions (`contents:write`, `packages:write`)
