# Justfile for styrened development and build automation
#
# Just is a command runner - install via: brew install just / cargo install just
# Run `just` or `just --list` to see available recipes

# ─── Configuration ──────────────────────────────────────────────────────────

# Project paths
project_root := justfile_directory()
docker_dir := project_root / "tests/k8s/docker"
helm_chart := project_root / "tests/k8s/helm/styrened-test"

# Version info (lazy evaluation)
version := `./scripts/version.sh version`
commit_sha := `./scripts/version.sh sha`
build_date := `date -u +"%Y-%m-%dT%H:%M:%SZ"`

# Registry and image configuration
registry := "ghcr.io"
image_prod := "styrene-lab/styrened"
image_test := "styrene-lab/styrened-test"

# Helm/K8s defaults
helm_release := "styrene-test"
helm_namespace := "styrene-test"
local_image_tag := "styrened-test:local-amd64"

# K3s remote host (override with K3S_HOST env var)
k3s_host := env_var_or_default("K3S_HOST", "brutus")

# ─── Help ───────────────────────────────────────────────────────────────────

# Show available recipes (default)
@default:
    just --list --unsorted

# Show version information
@version:
    echo "Version:    {{ version }}"
    echo "Commit:     {{ commit_sha }}"
    echo "Build Date: {{ build_date }}"
    echo "Test Image: {{ registry }}/{{ image_test }}:{{ version }}"
    echo "Prod Image: {{ registry }}/{{ image_prod }}:{{ version }}"

# ─── Development ────────────────────────────────────────────────────────────

# Install package with dev dependencies
install:
    pip install -e ".[dev]"

# Run all tests (unit + integration, no k8s)
test:
    pytest tests/ --ignore=tests/k8s/

# Run unit tests only
test-unit:
    pytest tests/test_*.py tests/unit/ -v

# Run local integration tests (no k8s)
test-integration:
    pytest tests/integration/ -v

# Run linter (ruff)
lint:
    ruff check src/ tests/

# Format code (ruff)
format:
    ruff format src/ tests/

# Run type checker (mypy)
typecheck:
    mypy src/

# Run all validation checks (lint + typecheck + test)
validate: lint typecheck test

# Check version synchronization across all sources
check-versions:
    #!/usr/bin/env bash
    set -euo pipefail
    PYPROJECT_VER=$(grep '^version = ' pyproject.toml | cut -d'"' -f2)
    INIT_VER=$(grep '^__version__ = ' src/styrened/__init__.py | cut -d'"' -f2)
    FILE_VER=$(cat VERSION)
    echo "pyproject.toml: $PYPROJECT_VER"
    echo "__init__.py:    $INIT_VER"
    echo "VERSION:        $FILE_VER"
    if [[ "$PYPROJECT_VER" == "$INIT_VER" && "$INIT_VER" == "$FILE_VER" ]]; then
        echo "OK: All versions synchronized"
    else
        echo "ERROR: VERSION DRIFT DETECTED"
        exit 1
    fi

# ─── Container Build (Test Images) ──────────────────────────────────────────

# Build local test image (auto-detect architecture)
build:
    cd {{ docker_dir }} && docker buildx bake \
        --allow=fs.read={{ project_root }} \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --set "local.tags={{ registry }}/{{ image_test }}:{{ version }}" \
        --set "local.tags={{ registry }}/{{ image_test }}:{{ commit_sha }}" \
        --load \
        local

# Build test image (quick validation, test stage only)
build-test:
    cd {{ docker_dir }} && docker buildx bake \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --load \
        test

# Build multi-arch test image (amd64, arm64)
build-multi:
    cd {{ docker_dir }} && docker buildx bake \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --set "multi.tags={{ registry }}/{{ image_test }}:{{ version }}" \
        --set "multi.tags={{ registry }}/{{ image_test }}:{{ commit_sha }}" \
        multi

# Build AMD64 image for x86_64 clusters (from any host)
build-amd64:
    docker buildx build \
        --platform linux/amd64 \
        -t {{ local_image_tag }} \
        -f {{ docker_dir }}/Dockerfile \
        --load \
        {{ project_root }}

# Validate test image works
test-image:
    docker run --rm {{ registry }}/{{ image_test }}:{{ version }} styrened --version

# ─── Container Build (Production Images) ────────────────────────────────────

# Build production image (auto-detect architecture)
build-prod:
    cd {{ docker_dir }} && docker buildx bake \
        --allow=fs.read={{ project_root }} \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --set "*.target=app" \
        --set "local.tags={{ registry }}/{{ image_prod }}:{{ version }}" \
        --set "local.tags={{ registry }}/{{ image_prod }}:{{ commit_sha }}" \
        --load \
        local

# Build multi-arch production image (amd64, arm64)
build-prod-multi:
    cd {{ docker_dir }} && docker buildx bake \
        --allow=fs.read={{ project_root }} \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --set "*.target=app" \
        --set "multi.tags={{ registry }}/{{ image_prod }}:{{ version }}" \
        --set "multi.tags={{ registry }}/{{ image_prod }}:{{ commit_sha }}" \
        multi

# Validate production image works
test-image-prod:
    docker run --rm {{ registry }}/{{ image_prod }}:{{ version }} styrened --version

# ─── Registry Push ──────────────────────────────────────────────────────────

# Login to GHCR (uses GITHUB_TOKEN env var or gh CLI)
container-login:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        echo "$GITHUB_TOKEN" | docker login {{ registry }} -u "${GITHUB_ACTOR:-$(gh api user -q .login)}" --password-stdin
    else
        echo "GITHUB_TOKEN not set, attempting gh CLI auth..."
        gh auth token | docker login {{ registry }} -u "$(gh api user -q .login)" --password-stdin
    fi

# Backward compatibility alias
alias docker-login := container-login

# Push test image with version tags
push-test: container-login
    cd {{ docker_dir }} && docker buildx bake \
        --allow=fs.read={{ project_root }} \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --set "multi.tags={{ registry }}/{{ image_test }}:{{ version }}" \
        --set "multi.tags={{ registry }}/{{ image_test }}:{{ commit_sha }}" \
        --set "multi.output=type=image,push=true" \
        multi

# Push test image with 'latest' tag (nightly builds)
push-test-nightly: container-login
    cd {{ docker_dir }} && docker buildx bake \
        --allow=fs.read={{ project_root }} \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --set "multi.tags={{ registry }}/{{ image_test }}:latest" \
        --set "multi.tags={{ registry }}/{{ image_test }}:{{ commit_sha }}" \
        --set "multi.output=type=image,push=true" \
        multi

# Push production image with version tags
push-prod: container-login
    cd {{ docker_dir }} && docker buildx bake \
        --allow=fs.read={{ project_root }} \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --set "*.target=app" \
        --set "multi.tags={{ registry }}/{{ image_prod }}:{{ version }}" \
        --set "multi.tags={{ registry }}/{{ image_prod }}:{{ commit_sha }}" \
        --set "multi.output=type=image,push=true" \
        multi

# Push production image with 'latest' tag (stable releases only)
push-prod-latest: container-login
    cd {{ docker_dir }} && docker buildx bake \
        --allow=fs.read={{ project_root }} \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --set "*.target=app" \
        --set "multi.tags={{ registry }}/{{ image_prod }}:{{ version }}" \
        --set "multi.tags={{ registry }}/{{ image_prod }}:{{ commit_sha }}" \
        --set "multi.tags={{ registry }}/{{ image_prod }}:latest" \
        --set "multi.output=type=image,push=true" \
        multi

# Push edge build (main branch)
push-edge: container-login
    cd {{ docker_dir }} && docker buildx bake \
        --allow=fs.read={{ project_root }} \
        --set "*.context={{ project_root }}" \
        --set "*.args.VERSION={{ version }}" \
        --set "*.args.COMMIT_SHA={{ commit_sha }}" \
        --set "*.args.BUILD_DATE={{ build_date }}" \
        --set "*.target=app" \
        --set "multi.tags={{ registry }}/{{ image_prod }}:edge" \
        --set "multi.tags={{ registry }}/{{ image_prod }}:{{ commit_sha }}" \
        --set "multi.output=type=image,push=true" \
        multi

# Alias: push defaults to push-test
alias push := push-test

# ─── Kubernetes / Helm ──────────────────────────────────────────────────────

# Detect cluster type from kubectl context
[private]
@cluster-type:
    #!/usr/bin/env bash
    ctx=$(kubectl config current-context 2>/dev/null || echo "none")
    if [[ "$ctx" == *"kind-"* ]]; then echo "kind"
    elif [[ "$ctx" == *"k3d-"* ]]; then echo "k3d"
    elif command -v k3s >/dev/null 2>&1; then echo "k3s-local"
    elif ssh {{ k3s_host }} "command -v k3s" >/dev/null 2>&1; then echo "k3s-remote"
    else echo "unknown"
    fi

# Load local image into k8s cluster (auto-detect kind/k3d/k3s)
load-k8s-image: build-amd64
    #!/usr/bin/env bash
    set -euo pipefail
    cluster_type=$(just cluster-type)
    echo "Detected cluster type: $cluster_type"
    case "$cluster_type" in
        kind)
            ctx=$(kubectl config current-context)
            kind load docker-image {{ local_image_tag }} --name "${ctx#kind-}"
            ;;
        k3d)
            ctx=$(kubectl config current-context)
            k3d image import {{ local_image_tag }} -c "${ctx#k3d-}"
            ;;
        k3s-remote)
            docker save {{ local_image_tag }} | gzip > /tmp/styrened-image.tar.gz
            scp /tmp/styrened-image.tar.gz {{ k3s_host }}:/tmp/
            ssh {{ k3s_host }} "sudo k3s ctr images import /tmp/styrened-image.tar.gz"
            rm -f /tmp/styrened-image.tar.gz
            ;;
        k3s-local)
            docker save {{ local_image_tag }} | sudo k3s ctr images import -
            ;;
        *)
            echo "Unknown cluster type - please load image manually"
            exit 1
            ;;
    esac
    echo "Image loaded into cluster"

# Create ImagePullSecret for GHCR in test namespace
create-ghcr-secret:
    #!/usr/bin/env bash
    set -euo pipefail
    TOKEN="${GITHUB_TOKEN:-$(gh auth token 2>/dev/null)}"
    ACTOR="${GITHUB_ACTOR:-$(gh api user -q .login 2>/dev/null || echo unknown)}"
    EMAIL="${GITHUB_EMAIL:-noreply@github.com}"
    if [[ -z "$TOKEN" ]]; then
        echo "Error: GITHUB_TOKEN not set and gh CLI not authenticated"
        exit 1
    fi
    kubectl create namespace {{ helm_namespace }} 2>/dev/null || true
    kubectl delete secret ghcr-secret -n {{ helm_namespace }} 2>/dev/null || true
    kubectl create secret docker-registry ghcr-secret \
        --docker-server=ghcr.io \
        --docker-username="$ACTOR" \
        --docker-password="$TOKEN" \
        --docker-email="$EMAIL" \
        -n {{ helm_namespace }}
    echo "Created ImagePullSecret: ghcr-secret in namespace {{ helm_namespace }}"

# Delete GHCR ImagePullSecret from test namespace
delete-ghcr-secret:
    kubectl delete secret ghcr-secret -n {{ helm_namespace }} 2>/dev/null || true

# Verify GHCR ImagePullSecret exists and is valid
verify-ghcr-secret:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! kubectl get secret ghcr-secret -n {{ helm_namespace }} >/dev/null 2>&1; then
        echo "Secret not found. Run: just create-ghcr-secret"
        exit 1
    fi
    size=$(kubectl get secret ghcr-secret -n {{ helm_namespace }} -o yaml | grep "^\s*\.dockerconfigjson:" | wc -c)
    if [[ $size -gt 50 ]]; then
        echo "OK: Secret exists and looks valid ($size bytes)"
    else
        echo "WARN: Secret exists but may be invalid ($size bytes)"
    fi

# Render Helm templates (dry-run)
helm-template:
    helm template {{ helm_release }} {{ helm_chart }} -n {{ helm_namespace }}

# Deploy test stack with local images
helm-install:
    helm upgrade --install {{ helm_release }} {{ helm_chart }} \
        -n {{ helm_namespace }} --create-namespace \
        --set image.repository=styrened-test \
        --set image.tag=local-amd64 \
        --set image.pullPolicy=Never

# Deploy test stack using GHCR images
helm-install-ghcr: verify-ghcr-secret
    helm upgrade --install {{ helm_release }} {{ helm_chart }} \
        -n {{ helm_namespace }} --create-namespace \
        --set image.repository={{ registry }}/{{ image_test }} \
        --set image.tag={{ version }} \
        --set image.pullPolicy=Always \
        --set imagePullSecrets[0].name=ghcr-secret
    @just helm-wait

# Deploy with custom image tag
helm-install-tag tag:
    helm upgrade --install {{ helm_release }} {{ helm_chart }} \
        -n {{ helm_namespace }} --create-namespace \
        --set image.repository={{ registry }}/{{ image_test }} \
        --set image.tag={{ tag }} \
        --set image.pullPolicy=Always \
        --set imagePullSecrets[0].name=ghcr-secret
    @just helm-wait

# Wait for pods to be ready
[private]
helm-wait:
    kubectl wait --for=condition=ready pod \
        -l app.kubernetes.io/instance={{ helm_release }} \
        -n {{ helm_namespace }} --timeout=120s || true
    kubectl get pods -n {{ helm_namespace }}

# Uninstall test stack from cluster
helm-uninstall:
    helm uninstall {{ helm_release }} -n {{ helm_namespace }} || true
    kubectl delete namespace {{ helm_namespace }} --wait=false || true

# Show deployment status
helm-status:
    @echo "=== Helm Release ==="
    @helm status {{ helm_release }} -n {{ helm_namespace }} 2>/dev/null || echo "Not deployed"
    @echo ""
    @echo "=== Pods ==="
    @kubectl get pods -n {{ helm_namespace }} 2>/dev/null || echo "No pods"

# Show logs from test pods
helm-logs *args:
    kubectl logs -l app.kubernetes.io/instance={{ helm_release }} -n {{ helm_namespace }} {{ args }}

# Follow logs from test pods
helm-logs-follow:
    kubectl logs -l app.kubernetes.io/instance={{ helm_release }} -n {{ helm_namespace }} -f --tail=50

# ─── K8s Test Workflows ─────────────────────────────────────────────────────

# Run k8s tests (requires cluster)
test-k8s:
    pytest tests/k8s/

# Run k8s smoke tests only (fast)
test-k8s-smoke:
    pytest tests/k8s/scenarios/ -m smoke -v

# Run full k8s test suite including slow tests
test-k8s-full:
    pytest tests/k8s/scenarios/ --run-slow -v

# Build, load image, and deploy test stack
test-k8s-deploy: load-k8s-image helm-install
    @echo "Test stack deployed"

# Run k8s tests (assumes image already deployed)
test-k8s-run:
    pytest tests/k8s/scenarios/ -v -m smoke --tb=short

# Complete local k8s test workflow: build, load, test
test-k8s-local: load-k8s-image
    @echo "=== K8s Local Test Workflow ==="
    pytest tests/k8s/scenarios/ -v -m smoke --tb=short
    @echo "=== Complete ==="

# Complete remote k8s test workflow: create secret, deploy from GHCR, test
test-k8s-remote: create-ghcr-secret helm-install-ghcr
    @echo "=== K8s Remote Test Workflow (GHCR) ==="
    pytest tests/k8s/scenarios/ -v -m smoke --tb=short
    @echo "=== Complete ==="

# List k8s test namespaces and resources
test-k8s-list:
    @echo "=== Styrened Test Namespaces ==="
    ./tests/k8s/cleanup-test-resources.sh --list

# Clean up k8s test namespaces (interactive)
test-k8s-cleanup:
    ./tests/k8s/cleanup-test-resources.sh

# Clean up k8s test namespaces (force, no confirmation)
test-k8s-cleanup-force:
    ./tests/k8s/cleanup-test-resources.sh --force

# ─── Cleanup ────────────────────────────────────────────────────────────────

# Remove Python cache directories
clean:
    rm -rf .pytest_cache .ruff_cache .mypy_cache
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete

# Remove local container images
clean-images:
    docker rmi {{ registry }}/{{ image_test }}:{{ version }} 2>/dev/null || true
    docker rmi {{ registry }}/{{ image_test }}:{{ commit_sha }} 2>/dev/null || true
    docker rmi {{ registry }}/{{ image_prod }}:{{ version }} 2>/dev/null || true
    docker rmi {{ registry }}/{{ image_prod }}:{{ commit_sha }} 2>/dev/null || true
    docker rmi {{ local_image_tag }} 2>/dev/null || true
    docker rmi {{ image_test }}:test 2>/dev/null || true

# Remove all build artifacts and images
clean-all: clean clean-images
    rm -rf build/ dist/ *.egg-info

# ─── Release Helpers ────────────────────────────────────────────────────────

# Bump version in all source files (interactive)
bump-version new_version:
    #!/usr/bin/env bash
    set -euo pipefail
    current="{{ version }}"
    echo "Current version: $current"
    echo "New version:     {{ new_version }}"
    read -p "Proceed? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted"
        exit 1
    fi
    # Update pyproject.toml
    sed -i '' 's/^version = ".*"/version = "{{ new_version }}"/' pyproject.toml
    # Update __init__.py
    sed -i '' 's/__version__ = ".*"/__version__ = "{{ new_version }}"/' src/styrened/__init__.py
    # Update VERSION file
    echo "{{ new_version }}" > VERSION
    echo "Updated version to {{ new_version }}"
    just check-versions

# Create release tag (after version bump is committed)
tag-release:
    #!/usr/bin/env bash
    set -euo pipefail
    ver="{{ version }}"
    echo "Creating tag: v$ver"
    git tag -a "v$ver" -m "Release v$ver"
    echo "Tag created. Push with: git push origin v$ver"

# Full release workflow: validate, bump, commit, tag
release new_version: validate
    just bump-version {{ new_version }}
    git add pyproject.toml src/styrened/__init__.py VERSION
    git commit -m "chore: bump version to {{ new_version }}"
    just tag-release
    @echo ""
    @echo "Release prepared. To publish:"
    @echo "  git push origin main --tags"

# ─── Development Helpers ────────────────────────────────────────────────────

# Run the daemon locally
run *args:
    styrened {{ args }}

# Run daemon in foreground with debug logging
run-debug:
    STYRENE_LOG_LEVEL=DEBUG styrened daemon

# List discovered devices
devices *args:
    styrened devices {{ args }}

# Query remote device status
status dest:
    styrened status {{ dest }}

# Send message to remote device
send dest message:
    styrened send {{ dest }} "{{ message }}"

# Execute command on remote device
exec dest *cmd:
    styrened exec {{ dest }} {{ cmd }}

# Show local identity
identity:
    styrened identity

# Setup git hooks
setup-hooks:
    git config core.hooksPath .githooks
    @echo "Git hooks configured to use .githooks/"
