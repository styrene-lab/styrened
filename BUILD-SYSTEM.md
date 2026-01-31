# Build System Documentation

Complete guide to the styrened build automation, versioning, and CI/CD workflows.

## Overview

The build system automates the entire lifecycle from local development to production releases:

```
Developer → make build → Local Docker image
         → make test → Run tests locally

PR → GitHub Actions → pr-validation.yml → Smoke tests → Comment results

Nightly → nightly-build.yml → Full test suite → Issue on failure

Tag v* → release.yml → Multi-arch build → GHCR push → GitHub Release
```

## Architecture

### Build Components

| Component | Purpose | Source |
|-----------|---------|--------|
| Makefile | Developer commands, local builds | `/Makefile` |
| docker-bake.hcl | Multi-arch build configuration | `/tests/k8s/docker/docker-bake.hcl` |
| version.sh | Semantic version extraction | `/scripts/version.sh` |
| VERSION file | Single source of truth for version | `/VERSION` |
| GitHub Actions | CI/CD automation | `/.github/workflows/` |

### Build Targets

The `docker-bake.hcl` defines multiple build targets for different scenarios:

| Target | Platforms | Output | Use Case |
|--------|-----------|--------|----------|
| `local` | Auto-detect | Docker daemon | Local development |
| `multi` | amd64, arm64 | Image | Multi-arch testing |
| `release` | amd64, arm64 | Push to registry | Production releases |
| `edge` | amd64, arm64 | Push to registry | Main branch builds |
| `pr` | amd64, arm64 | Image | PR validation |
| `test` | amd64 | Docker daemon | Quick validation |

## Makefile Targets Reference

### Development

```bash
make install         # Install package with dev dependencies
make test           # Run all tests (unit + k8s)
make test-unit      # Run unit tests only
make test-k8s       # Run k8s integration tests
make lint           # Run ruff linter
make format         # Format code with ruff
make typecheck      # Run mypy type checker
make validate       # Run lint + typecheck + test
```

### Docker Build

```bash
make version        # Display version information
make build          # Build local single-arch image
make build-multi    # Build multi-arch image (amd64, arm64)
make build-test     # Build test stage only (quick validation)
make push           # Build and push multi-arch to registry
make test-image     # Quick validation of built image
```

### Cleanup

```bash
make clean          # Remove cache directories
make clean-images   # Remove local Docker images
make clean-all      # Remove all build artifacts and images
```

## Docker Build System

### docker-bake.hcl Usage

Docker Buildx Bake provides declarative multi-platform builds with shared configuration.

#### Basic Usage

```bash
# Build for local architecture
cd tests/k8s/docker
docker buildx bake \
  --set "*.context=../../.." \
  --load \
  local

# Build multi-arch
docker buildx bake \
  --set "*.context=../../.." \
  multi

# Build and push
docker buildx bake \
  --set "*.context=../../.." \
  --set "multi.output=type=image,push=true" \
  multi
```

#### Variables

Override build variables:

```bash
docker buildx bake \
  --set "*.context=../../.." \
  --set "*.args.VERSION=0.3.0" \
  --set "*.args.COMMIT_SHA=abc1234" \
  --set "*.args.BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")" \
  local
```

#### Targets

```bash
# Local development (auto-detect platform)
docker buildx bake local

# Multi-arch (amd64 + arm64)
docker buildx bake multi

# Release (multi-arch with full tags)
docker buildx bake release

# Edge (main branch)
docker buildx bake edge

# PR validation
docker buildx bake pr

# Test stage only
docker buildx bake test
```

### Build Cache

The build system uses GitHub Actions cache for faster builds:

```bash
# Local builds (no remote cache)
docker buildx bake local

# CI builds with cache
docker buildx bake \
  --set "*.cache-from=type=gha" \
  --set "*.cache-to=type=gha,mode=max" \
  multi
```

Cache is scoped by platform (`linux/amd64`, `linux/arm64`) to optimize storage.

## Semantic Versioning Strategy

### Version Format

```
MAJOR.MINOR.PATCH[-SUFFIX]

Examples:
  0.2.0          # Stable release
  0.2.1-rc1      # Release candidate
  1.0.0-alpha1   # Alpha release
  1.0.0-beta2    # Beta release
```

### Version Sources

Priority order (first match wins):

1. `/VERSION` file (single source of truth)
2. `pyproject.toml` (Python package version)
3. Git tag (most recent tag)
4. Default: `0.0.0-dev`

### Version Extraction

```bash
# Get current version
./scripts/version.sh version

# Get commit SHA
./scripts/version.sh sha

# Get major version
./scripts/version.sh major

# Get all Docker tags for current state
./scripts/version.sh tags
```

## Image Tagging Rules

### Release Tags (v0.2.0)

```
ghcr.io/styrene-lab/styrened:0.2.0
ghcr.io/styrene-lab/styrened:0.2
ghcr.io/styrene-lab/styrened:0
ghcr.io/styrene-lab/styrened:latest
```

### Pre-release Tags (v0.2.1-rc1)

```
ghcr.io/styrene-lab/styrened:0.2.1-rc1
ghcr.io/styrene-lab/styrened:prerelease
```

### Development Tags (main branch)

```
ghcr.io/styrene-lab/styrened:edge
ghcr.io/styrene-lab/styrened:main-abc1234
```

### PR Tags

```
ghcr.io/styrene-lab/styrened:pr-abc1234
```

### Nightly Tags

```
ghcr.io/styrene-lab/styrened-test:nightly-latest
ghcr.io/styrene-lab/styrened-test:nightly-20260126
ghcr.io/styrene-lab/styrened-test:nightly-abc1234
```

## Multi-Architecture Builds

### Platforms

- `linux/amd64` - x86_64 (Intel/AMD)
- `linux/arm64` - ARM 64-bit (Raspberry Pi 4+, AWS Graviton, Apple Silicon)

### QEMU Emulation

Multi-arch builds use QEMU for cross-platform compilation:

```bash
# Setup QEMU (CI does this automatically)
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes

# Setup buildx builder
docker buildx create --use --name multiarch --driver docker-container

# Build multi-arch
docker buildx bake multi
```

### Build Time

| Configuration | Time (local) | Time (CI with cache) |
|--------------|--------------|----------------------|
| Single arch (local) | ~3-5 min | ~2-3 min |
| Multi-arch (amd64 + arm64) | ~8-12 min | ~5-8 min |
| Full test suite | ~30-40 min | ~20-30 min |

## CI/CD Workflows

### pr-validation.yml

**Trigger**: Pull requests to `main` or `develop`

**Purpose**: Fast validation with smoke tests

**Duration**: ~10-15 minutes

**Actions**:
1. Build single-arch test image (with cache)
2. Setup kind cluster
3. Load image into kind
4. Run smoke tests (parallel, 4 workers)
5. Comment results on PR
6. Upload logs on failure

**Example**:
```bash
# Manually trigger
gh workflow run pr-validation.yml
```

### nightly-build.yml

**Trigger**: Daily at 2 AM UTC, or manual dispatch

**Purpose**: Comprehensive testing with full suite

**Duration**: ~60-90 minutes

**Actions**:
1. Build multi-arch images (amd64, arm64)
2. Push to registry (nightly tags)
3. Run smoke tests
4. Run integration tests
5. Run comprehensive tests
6. Generate test report
7. Create issue on failure

**Manual Trigger with Options**:
```bash
# Run specific test tier
gh workflow run nightly-build.yml -f test_tier=smoke

# Run with custom worker count
gh workflow run nightly-build.yml -f test_tier=all -f workers=4
```

### release.yml

**Trigger**: Git tag push (v*)

**Purpose**: Production release with full validation

**Duration**: ~90-120 minutes

**Actions**:
1. Validate release tag (extract version)
2. Build multi-arch images (amd64, arm64)
3. Push to registry with semantic tags
4. Run full test suite (smoke + integration + comprehensive)
5. Generate changelog from commits
6. Create GitHub release with artifacts
7. Upload coverage reports

**Example**:
```bash
# Create release
./scripts/release.sh 0.3.0

# Or manually
git tag v0.3.0
git push origin v0.3.0
```

### manual-test.yml

**Trigger**: Manual dispatch only

**Purpose**: On-demand test execution with custom configuration

**Duration**: Variable (depends on tier and workers)

**Options**:
- `test_tier`: smoke, integration, comprehensive, all
- `workers`: 1, 2, 4, 6, 8
- `test_pattern`: Specific test pattern (e.g., `test_edge_cases.py::test_network_partition`)
- `run_slow_tests`: Include slow tests (load/scaling)

**Actions**:
1. Build test image
2. Setup kind cluster
3. Run tests with specified configuration
4. Upload coverage and logs
5. Generate summary

**Example**:
```bash
# Run smoke tests with 4 workers
gh workflow run manual-test.yml \
  -f test_tier=smoke \
  -f workers=4

# Run specific test with slow tests enabled
gh workflow run manual-test.yml \
  -f test_tier=smoke \
  -f test_pattern=scenarios/test_load.py::test_message_throughput \
  -f run_slow_tests=true
```

## Troubleshooting

### Build Cache Issues

**Problem**: Stale cache causing build failures

**Solution**:
```bash
# Clear local buildx cache
docker buildx prune -af

# Clear GitHub Actions cache (requires gh CLI)
gh cache list
gh cache delete <cache-key>

# Force rebuild without cache
docker buildx bake --no-cache local
```

### Multi-Arch Build Failures

**Problem**: ARM64 build fails or hangs

**Symptoms**:
- QEMU timeout
- Segmentation fault during build
- Extremely slow build times

**Solutions**:

1. Update QEMU:
```bash
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
```

2. Increase timeout (CI):
```yaml
timeout-minutes: 60  # Increase from default
```

3. Build platforms separately:
```bash
# Build amd64 only
docker buildx bake --set "multi.platforms=linux/amd64" multi

# Build arm64 only
docker buildx bake --set "multi.platforms=linux/arm64" multi
```

### Test Flakiness in CI

**Problem**: Tests pass locally but fail in CI

**Common Causes**:
- Timing issues (cluster startup)
- Resource constraints
- Parallel execution conflicts

**Solutions**:

1. Increase timeouts:
```python
# In test code
harness.wait_for_ready(pods, timeout=120)  # Increase from 60
```

2. Reduce parallelism:
```bash
# In workflow
pytest tests/k8s/ -n 2  # Reduce from 4 or 8
```

3. Check cluster resources:
```yaml
# In workflow
- name: Check cluster resources
  run: |
    kubectl top nodes
    kubectl describe nodes
```

### Image Push Authentication Failures

**Problem**: `unauthorized: authentication required`

**Causes**:
- Expired GitHub token
- Missing registry permissions
- Incorrect image name

**Solutions**:

1. Verify token:
```bash
echo ${{ secrets.GITHUB_TOKEN }} | docker login ghcr.io -u ${{ github.actor }} --password-stdin
```

2. Check permissions:
```yaml
permissions:
  contents: read
  packages: write  # Required for GHCR push
```

3. Verify image name:
```bash
# Must match repository name
REGISTRY: ghcr.io
IMAGE_NAME: ${{ github.repository }}  # owner/repo
```

### Kind Cluster Startup Issues

**Problem**: Kind cluster fails to start in CI

**Symptoms**:
- Timeout waiting for control plane
- Node not ready
- CoreDNS pods not running

**Solutions**:

1. Check Docker service:
```bash
docker ps
docker version
```

2. Increase startup timeout:
```yaml
- name: Set up kind cluster
  uses: helm/kind-action@v1.8.0
  with:
    wait: 600s  # Increase from default
```

3. Verify cluster:
```bash
kubectl cluster-info
kubectl get nodes
kubectl get pods -n kube-system
```

4. Collect logs on failure:
```bash
kind export logs /tmp/kind-logs --name styrene-test
```

## Common Scenarios

### Local Development Build

```bash
# 1. Build local image
make build

# 2. Run tests
make test

# 3. Validate
make validate
```

### Pre-Release Testing

```bash
# 1. Update version
echo "0.3.0-rc1" > VERSION

# 2. Build multi-arch
make build-multi

# 3. Test locally
make test-k8s

# 4. Create tag
git tag v0.3.0-rc1
git push origin v0.3.0-rc1
```

### Production Release

```bash
# 1. Update version
echo "0.3.0" > VERSION

# 2. Commit version bump
git add VERSION
git commit -m "Bump version to 0.3.0"

# 3. Create tag
git tag v0.3.0

# 4. Push (triggers release workflow)
git push origin main
git push origin v0.3.0

# 5. Monitor release
gh run watch

# 6. Verify release
gh release view v0.3.0
docker pull ghcr.io/styrene-lab/styrened:0.3.0
```

### Hotfix Release

```bash
# 1. Create hotfix branch from tag
git checkout v0.3.0
git checkout -b hotfix/0.3.1

# 2. Fix issue
# ... make changes ...

# 3. Update version
echo "0.3.1" > VERSION

# 4. Commit
git add .
git commit -m "Fix critical issue"

# 5. Create tag
git tag v0.3.1

# 6. Push
git push origin hotfix/0.3.1
git push origin v0.3.1

# 7. Merge back to main
git checkout main
git merge --no-ff hotfix/0.3.1
git push origin main
```

### Running Specific Test Tiers in CI

```bash
# Smoke tests only (fastest)
gh workflow run manual-test.yml -f test_tier=smoke -f workers=4

# Integration tests
gh workflow run manual-test.yml -f test_tier=integration -f workers=4

# Comprehensive tests (slowest)
gh workflow run manual-test.yml -f test_tier=comprehensive -f workers=2

# All tiers
gh workflow run manual-test.yml -f test_tier=all -f workers=8
```

### Debugging CI Failures

```bash
# 1. View workflow runs
gh run list --workflow=pr-validation.yml

# 2. Watch live
gh run watch <run-id>

# 3. View logs
gh run view <run-id> --log

# 4. Download artifacts
gh run download <run-id>

# 5. Re-run failed jobs
gh run rerun <run-id> --failed
```

### Manually Triggering Workflows

```bash
# PR validation
gh workflow run pr-validation.yml

# Nightly build (all tests)
gh workflow run nightly-build.yml

# Nightly build (specific tier)
gh workflow run nightly-build.yml -f test_tier=smoke -f workers=8

# Manual test with pattern
gh workflow run manual-test.yml \
  -f test_tier=smoke \
  -f test_pattern=scenarios/test_edge_cases.py \
  -f workers=4
```

## Best Practices

### Version Bumping

1. Always update `/VERSION` file first
2. Commit version bump separately from code changes
3. Use semantic versioning (MAJOR.MINOR.PATCH)
4. Add suffix for pre-releases (-rc1, -alpha1, -beta2)
5. Tag releases with `v` prefix (v0.3.0)

### Docker Images

1. Use semantic tags for releases (0.3.0, 0.3, 0)
2. Use commit SHA tags for development (main-abc1234)
3. Use `:latest` only for stable releases
4. Use `:edge` for main branch builds
5. Use `:prerelease` for release candidates

### Testing

1. Run smoke tests before committing (`make validate`)
2. Run integration tests before PRs
3. Run full suite before releases
4. Use parallel execution for speed (`-n auto`)
5. Check coverage reports in CI artifacts

### CI/CD

1. Let PR validation run before requesting review
2. Monitor nightly builds for regressions
3. Review test logs on failures
4. Update workflows when adding new test tiers
5. Keep workflow timeout margins reasonable

## Performance Optimization

### Build Speed

```bash
# Use cached builds
make build  # Reuses local layers

# Multi-stage builds
docker buildx bake test  # Test stage only (faster)

# Parallel builds
docker buildx bake --set "*.platform=linux/amd64,linux/arm64" multi
```

### Test Speed

```bash
# Parallel execution
pytest tests/k8s/ -n auto  # Auto-detect CPU count

# Specific tier
pytest tests/k8s/ -m smoke  # Fast tier only

# Skip slow tests
pytest tests/k8s/  # Default: skips slow tests
```

### Cache Strategy

```bash
# GitHub Actions cache
cache-from: type=gha
cache-to: type=gha,mode=max

# Local cache
docker buildx bake --cache-from=type=local,src=/tmp/buildx-cache local
```

## Reference

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| VERSION | Build version | 0.2.0 |
| COMMIT_SHA | Git commit SHA | abc1234 |
| BUILD_DATE | ISO 8601 timestamp | 2026-01-26T12:00:00Z |
| REGISTRY | Container registry | ghcr.io |
| IMAGE_NAME | Image repository | styrene-lab/styrened |

### File Locations

| File | Purpose |
|------|---------|
| `/VERSION` | Version number |
| `/Makefile` | Build commands |
| `/tests/k8s/docker/Dockerfile` | Multi-stage image |
| `/tests/k8s/docker/docker-bake.hcl` | Build configuration |
| `/scripts/version.sh` | Version extraction |
| `/.github/workflows/` | CI/CD workflows |

### External Resources

- [Docker Buildx Documentation](https://docs.docker.com/buildx/working-with-buildx/)
- [Semantic Versioning](https://semver.org/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Kind Documentation](https://kind.sigs.k8s.io/)
