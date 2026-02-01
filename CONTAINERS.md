# Container Build Pipeline

This document describes the OCI container build and release pipeline for styrened.

## Image Variants

### Production Images
**Registry**: `ghcr.io/styrene-lab/styrened`

Production images contain only the application runtime (no test dependencies). Built from the `app` stage in the Containerfile.

**Tags**:
- `latest` - Latest stable release (only for non-prerelease versions)
- `edge` - Latest build from main branch
- `v0.2.1` - Specific release version
- `<commit-sha>` - Build from specific commit

### Test Images
**Registry**: `ghcr.io/styrene-lab/styrened-test`

Test images include pytest and test dependencies. Built from the `test` stage in the Containerfile.

**Tags**:
- `latest` - Latest nightly build
- `<version>` - Version-tagged builds
- `<commit-sha>` - Build from specific commit

## Local Development

### Build Commands

```bash
# Build production image (local architecture)
make build-prod

# Build production image (multi-arch: amd64, arm64)
make build-prod-multi

# Build test image for quick validation
make build-test

# Test built image
make test-image-prod
```

### Version Information

```bash
# Show current version and build metadata
make version
```

Version is determined by `scripts/version.sh`:
1. Checks for `VERSION` file
2. Falls back to `pyproject.toml`
3. Falls back to git tags
4. Defaults to `0.0.0-dev`

## Publishing to GHCR

### Prerequisites

Set environment variables:
```bash
export GITHUB_TOKEN=ghp_xxxxx
export GITHUB_ACTOR=your-username
```

Or authenticate manually:
```bash
make container-login
```

### Push Commands

```bash
# Push production image (version + commit-sha tags)
make push-prod

# Push production image with 'latest' tag (releases only)
make push-prod-latest

# Push edge build (main branch)
make push-edge

# Push test image (nightly builds)
make push-test-nightly
```

## CI/CD Workflows

### PR Validation (`.github/workflows/pr-validation.yml`)
**Trigger**: Pull requests to main/develop

**Actions**:
1. Build test image from PR code
2. Run smoke tests in kind cluster
3. Report results as PR comment

**Duration**: ~5-10 minutes

### Edge Build (`.github/workflows/edge-build.yml`)
**Trigger**: Push to main branch

**Actions**:
1. Build production multi-arch image
2. Push to `ghcr.io/styrene-lab/styrened:edge`

**Duration**: ~10-15 minutes

### Nightly Build (`.github/workflows/nightly-build.yml`)
**Trigger**: Scheduled (2 AM UTC daily) or manual

**Actions**:
1. Build and push test images (`latest` tag)
2. Build and push edge images
3. Run comprehensive test suite
4. Generate test reports

**Duration**: ~30-90 minutes (depending on test tier)

### Release (`.github/workflows/release.yml`)
**Trigger**: Git tags matching `v*` (e.g., `v0.2.1`)

**Actions**:
1. Validate version tag
2. Build multi-arch production images
3. Push with semantic version tags:
   - `v0.2.1`
   - `0.2` (major.minor)
   - `0` (major, if stable)
   - `latest` (if stable, not prerelease)
4. Run full test suite
5. Create GitHub release with changelog

**Duration**: ~45-90 minutes

## Multi-Architecture Builds

Images are built for:
- `linux/amd64` - x86_64 servers, desktops
- `linux/arm64` - ARM64 devices (Raspberry Pi 4+, ARM servers)

Multi-arch builds use Buildx with QEMU emulation in CI.

## Build Configuration

### Containerfile (`tests/k8s/docker/Dockerfile`)

Multi-stage build:
1. **base** - System dependencies
2. **deps** - Python dependencies
3. **app** - Application code (production stage)
4. **test** - Test dependencies (test stage)

### Buildx Bake (`tests/k8s/docker/docker-bake.hcl`)

Defines build targets and configurations:
- `local` - Single-arch local builds
- `multi` - Multi-arch builds for registry
- `test` - Test image builds

## Troubleshooting

### Authentication Failed

```bash
# Ensure GITHUB_TOKEN has packages:write permission
echo $GITHUB_TOKEN | docker login ghcr.io -u $GITHUB_ACTOR --password-stdin
```

### Multi-arch Build Fails

```bash
# Ensure Buildx is set up with QEMU
docker buildx create --use --name multiarch
docker run --privileged --rm tonistiigi/binfmt --install all
```

### Image Not Found in Kind

```bash
# Verify image was loaded
docker exec <cluster>-control-plane crictl images | grep styrened
```

## Security

- Images are scanned for vulnerabilities in CI (planned)
- Base image: `python:3.11-slim` (official Python image)
- All images are signed with cosign (planned)
- SBOM generation with Syft (planned)

## Image Labels

All images include OCI-compliant labels:
- `org.opencontainers.image.version` - Semantic version
- `org.opencontainers.image.revision` - Git commit SHA
- `org.opencontainers.image.created` - Build timestamp
- `org.opencontainers.image.source` - Repository URL
- `org.opencontainers.image.licenses` - License (MIT)

Query labels:
```bash
docker inspect ghcr.io/styrene-lab/styrened:latest | jq '.[].Config.Labels'
```
