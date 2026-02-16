# Container Build Pipeline

This document describes the OCI container build and release pipeline for styrened.

## Architecture

The build pipeline uses **nix2container** to produce OCI images directly from the Nix flake. No Dockerfile, no buildx, no multi-stage builds. Nix handles dependency resolution, source filtering, and layer splitting.

```
flake.nix
├── nix/deps.nix       →  RNS + LXMF packages
├── nix/package.nix    →  styrened application
└── nix/oci.nix        →  OCI images (nix2container)
                              ↓
                   nix build .#oci        →  production image
                   nix build .#oci-test   →  test image (+ pytest, ping, ps)
```

### Layer Structure

Images use smart layer splitting for efficient caching:

| Layer | Contents | Changes When |
|-------|----------|-------------|
| 1 | Python 3.11 runtime | Rarely (nixpkgs update) |
| 2 | RNS, LXMF, pyyaml, platformdirs, sqlalchemy, msgpack | Dependency bumps |
| 3 | styrened + entrypoint + coreutils | Code changes |
| 4 (test only) | pytest, pytest-asyncio, iputils, procps | Test tool updates |

## Image Variants

### Production Images
**Registry**: `ghcr.io/styrene-lab/styrened`

Production images contain only the application runtime (no test dependencies).

**Tags**:
- `latest` - Latest stable release (only for non-prerelease versions)
- `edge` - Latest build from main branch
- `X.Y.Z` - Specific release version
- `<commit-sha>` - Build from specific commit

### Test Images
**Registry**: `ghcr.io/styrene-lab/styrened-test`

Test images extend production with pytest and diagnostic tools.

**Tags**:
- `latest` - Latest nightly build
- `<version>` - Version-tagged builds
- `<commit-sha>` - Build from specific commit

## Local Development

### Build Commands

```bash
# Build production OCI image
just build

# Build test OCI image
just build-test

# Load into local podman
just load        # production
just load-test   # test

# Validate built images
just test-image       # production
just test-image-test  # test

# Build Python wheel (for PyPI / pip distribution)
just build-wheel
```

### Version Information

```bash
# Show current version and build metadata
just version
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
just container-login
```

### Push Commands

```bash
# Push production image (version + commit-sha tags)
just push-prod

# Push production image with 'latest' tag (releases only)
just push-prod-latest

# Push edge build (main branch)
just push-edge

# Push test image (nightly builds)
just push-test-nightly
```

Push flow: `nix build .#oci` → `nix run .#oci.copyToPodman` → `podman push`

## CI/CD Workflows

CI/CD runs on **Argo Workflows** (brutus K3s cluster), triggered by **Argo Events** GitHub webhooks. Templates live in `.argo/workflows/`. See [docs/RELEASE-PROCESS.md](docs/RELEASE-PROCESS.md) for full details.

### PR Validation (`.argo/workflows/pr-validation.yaml`)
**Trigger**: Pull requests (opened/synchronize/reopened)

**Steps**: Checkout → Nix build test image → Install kubectl/helm + run smoke tests → Report GitHub status

**Duration**: ~5-7 minutes

### Edge Build (`.argo/workflows/edge-build.yaml`)
**Trigger**: Push to main branch

**Steps**: Checkout → Nix build OCI → Push to GHCR with `edge` + commit SHA tags

### Nightly Tests (`.argo/workflows/nightly-tests.yaml`)
**Trigger**: CronWorkflow at 2 AM UTC (`cron-nightly.yaml`)

**Steps**: Checkout → Smoke tests → Integration tests → Comprehensive tests (gated progression)

### Release Build (`.argo/workflows/release-build.yaml`)
**Trigger**: Tag push matching `refs/tags/v*`

**Steps**: Checkout → Parse version → Build wheel + Build OCI (parallel) → Push to GHCR → Create GitHub Release with artifacts

## Multi-Architecture Strategy

**Current (v0.4.0)**: amd64 only. All K8s targets (kind, k3s on brutus) are amd64. ARM64 edge SBCs use the Nix package directly (not OCI).

**Future**: ARM64 OCI via QEMU binfmt on CI runner or Nix remote builder on ARM64 machine.

## Build Configuration

### Nix Flake (`flake.nix`)

Defines three build outputs:
- `packages.default` - Nix package (for NixOS deployment, systemd service)
- `packages.oci` - Production OCI image
- `packages.oci-test` - Test OCI image

### nix2container (`nix/oci.nix`)

Image definitions with layered structure, OCI labels, and environment configuration.

### Entrypoint (`container/entrypoint.sh`)

Container startup script that handles config injection, RNS config, and identity generation. Wrapped as a `writeShellApplication` Nix derivation with explicit runtime dependencies.

## Troubleshooting

### Authentication Failed

```bash
# Ensure GITHUB_TOKEN has packages:write permission
echo $GITHUB_TOKEN | podman login ghcr.io -u $GITHUB_ACTOR --password-stdin
```

### Image Not Found in Kind

```bash
# Verify image was loaded
docker exec <cluster>-control-plane crictl images | grep styrened
```

### Nix Build Fails

```bash
# Check flake inputs are up to date
nix flake update

# Build with verbose output
nix build .#oci -L

# Check that all source files are git-tracked (Nix flakes require this)
git add -A && nix build .#oci
```

## Security

- Images built from Nix store (reproducible, auditable)
- No compiler toolchain in production image
- Minimal closure (only runtime dependencies)
- OCI-compliant labels for provenance

## Image Labels

All images include OCI-compliant labels:
- `org.opencontainers.image.version` - Semantic version
- `org.opencontainers.image.revision` - Git commit SHA
- `org.opencontainers.image.title` - Image name
- `org.opencontainers.image.source` - Repository URL
- `org.opencontainers.image.licenses` - License (MIT)

Query labels:
```bash
podman inspect ghcr.io/styrene-lab/styrened:latest | jq '.[].Config.Labels'
```
