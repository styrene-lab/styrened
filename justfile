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

# ─── Documentation ──────────────────────────────────────────────────────────

# Generate API documentation (output: docs/api/)
docs:
    @echo "Generating API documentation..."
    @pip show pdoc >/dev/null 2>&1 || { echo "pdoc not installed. Run: pip install -e '.[docs]'"; exit 1; }
    pdoc src/styrened -o docs/api --docformat google
    @echo "Generated: docs/api/"

# Serve API documentation locally (live reload)
docs-serve:
    @echo "Starting documentation server..."
    @pip show pdoc >/dev/null 2>&1 || { echo "pdoc not installed. Run: pip install -e '.[docs]'"; exit 1; }
    pdoc src/styrened --docformat google

# Remove generated documentation
docs-clean:
    rm -rf docs/api/
    @echo "Cleaned: docs/api/"

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

# ─── Bare-Metal Testing ─────────────────────────────────────────────────────
#
# Hardware integration tests for physical devices.
# Requires SSH access to registered devices (see tests/bare-metal/devices.yaml)
# SSH config (~/.ssh/config) handles user/key selection.

# Show status of all bare-metal devices
bare-metal-status:
    ./scripts/bare-metal-deploy.sh --status

# Quick smoke tests on all bare-metal devices
test-bare-metal-smoke:
    @echo "Running bare-metal smoke tests..."
    pytest tests/bare-metal/test_smoke.py -v

# Deploy wheel to bare-metal devices and verify
test-bare-metal-deploy:
    @echo "Building wheel..."
    python -m build --wheel
    @echo "Running bare-metal deployment tests..."
    pytest tests/bare-metal/test_deployment.py -v

# Mesh integration tests (requires running daemons)
test-bare-metal-mesh:
    @echo "Running bare-metal mesh tests..."
    pytest tests/bare-metal/test_mesh.py -v

# Run all bare-metal tests (smoke + mesh)
test-bare-metal: test-bare-metal-smoke test-bare-metal-mesh
    @echo "All bare-metal tests complete"

# Run bare-metal tests on specific device
test-bare-metal-device device:
    @echo "Running tests on {{ device }}..."
    pytest tests/bare-metal/ -v -k "{{ device }}"

# Start daemons on all bare-metal devices (reads from devices.yaml)
bare-metal-start:
    #!/usr/bin/env bash
    set -euo pipefail
    devices=$(python3 -c "
    import yaml
    with open('tests/bare-metal/devices.yaml') as f:
        data = yaml.safe_load(f)
    for name, info in data.get('devices', {}).items():
        print(f\"{name} {info['host']} {info.get('venv_path', '~/.local/styrene-venv')}\")
    ")
    while IFS=' ' read -r name host venv; do
        printf "  %-14s " "$name:"
        if ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" "echo ok" &>/dev/null; then
            ssh -o BatchMode=yes "$host" \
                "systemctl --user start styrened 2>/dev/null || { source $venv/bin/activate && nohup styrened daemon > /tmp/styrened.log 2>&1 & }" 2>/dev/null
            echo "started"
        else
            echo "unreachable"
        fi
    done <<< "$devices"

# Stop daemons on all bare-metal devices (reads from devices.yaml)
bare-metal-stop:
    #!/usr/bin/env bash
    set -euo pipefail
    devices=$(python3 -c "
    import yaml
    with open('tests/bare-metal/devices.yaml') as f:
        data = yaml.safe_load(f)
    for name, info in data.get('devices', {}).items():
        print(f\"{name} {info['host']}\")
    ")
    while IFS=' ' read -r name host; do
        printf "  %-14s " "$name:"
        if ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" "echo ok" &>/dev/null; then
            ssh -o BatchMode=yes "$host" \
                "systemctl --user stop styrened 2>/dev/null || pkill -f 'styrened daemon' 2>/dev/null || true" 2>/dev/null
            echo "stopped"
        else
            echo "unreachable"
        fi
    done <<< "$devices"

# Deploy current wheel to all bare-metal devices (or specify DEVICE)
bare-metal-deploy device="":
    ./scripts/bare-metal-deploy.sh --build {{ device }}

# ─── Cross-Platform Test Scenarios ──────────────────────────────────────────
#
# Unified test scenarios that run on either SSH (bare-metal) or K8s backend.
# Uses the unified test harness (tests/harness/).

# Run cross-platform scenarios on SSH backend (bare-metal devices)
test-scenarios-ssh:
    @echo "Running cross-platform scenarios on SSH backend..."
    pytest tests/scenarios/ --backend=ssh -v

# Run cross-platform scenarios on K8s backend
test-scenarios-k8s namespace="styrene-test":
    @echo "Running cross-platform scenarios on K8s backend..."
    pytest tests/scenarios/ --backend=k8s --k8s-namespace={{ namespace }} -v

# Run cross-platform scenarios on both backends
test-scenarios-both namespace="styrene-test":
    @echo "Running cross-platform scenarios on both backends..."
    pytest tests/scenarios/ --backend=both --k8s-namespace={{ namespace }} -v

# Run smoke-tier cross-platform tests (fast validation)
test-scenarios-smoke backend="ssh":
    @echo "Running smoke scenarios on {{ backend }} backend..."
    pytest tests/scenarios/ --backend={{ backend }} -m smoke -v

# Run integration-tier cross-platform tests
test-scenarios-integration backend="ssh":
    @echo "Running integration scenarios on {{ backend }} backend..."
    pytest tests/scenarios/ --backend={{ backend }} -m integration -v

# Run comprehensive cross-platform tests
test-scenarios-comprehensive backend="ssh":
    @echo "Running comprehensive scenarios on {{ backend }} backend..."
    pytest tests/scenarios/ --backend={{ backend }} -m comprehensive -v

# ─── Installation Testing ───────────────────────────────────────────────────
#
# Installation tests handle deployment/provisioning of styrened.
# These are separate from connectivity/mesh tests which assume working installation.

# Run installation smoke tests (validate existing installation)
test-install-smoke:
    @echo "Running installation smoke tests..."
    pytest tests/scenarios/test_installation.py --backend=ssh -m smoke -v

# Run full installation tests (install/upgrade cycles)
test-install:
    @echo "Running installation tests..."
    pytest tests/scenarios/test_installation.py --backend=ssh -m installation -v

# Run provisioning tests (install + systemd setup)
test-provision:
    @echo "Running provisioning tests..."
    pytest tests/scenarios/test_installation.py --backend=ssh -m provisioning -v

# Install from specific git tag on all devices
test-install-tag tag:
    @echo "Installing tag {{ tag }} on all devices..."
    pytest tests/scenarios/test_installation.py::TestPipGitInstallation::test_install_from_tag \
        --backend=ssh --install-tag={{ tag }} -v

# Install from wheel on all devices
test-install-wheel wheel_path="":
    #!/usr/bin/env bash
    if [[ -z "{{ wheel_path }}" ]]; then
        wheel=$(ls -t dist/styrened-*.whl 2>/dev/null | head -1)
        if [[ -z "$wheel" ]]; then
            echo "No wheel found. Build with: just build-wheel"
            exit 1
        fi
    else
        wheel="{{ wheel_path }}"
    fi
    echo "Installing wheel: $wheel"
    pytest tests/scenarios/test_installation.py::TestWheelInstallation::test_install_from_wheel \
        --backend=ssh --wheel-path="$wheel" -v

# Full provisioning workflow on all devices
test-provision-all:
    @echo "Provisioning all devices..."
    pytest tests/scenarios/test_installation.py::TestFullProvisioning::test_provision_all_nodes \
        --backend=ssh -v

# Build wheel for installation tests
build-wheel:
    @echo "Building wheel..."
    python -m build --wheel
    @ls -la dist/styrened-*.whl | tail -1

# ─── Test Matrix ────────────────────────────────────────────────────────────
#
# Structured test scenarios with expected parameters and results for analysis.

# Run full test matrix (smoke + integration)
test-matrix:
    @echo "Running test matrix..."
    pytest tests/scenarios/test_matrix.py --backend=ssh -v -s 2>&1 | tee test-results/matrix-$(date +%Y%m%d_%H%M%S).log

# Run smoke test matrix only
test-matrix-smoke:
    @echo "Running smoke test matrix..."
    pytest tests/scenarios/test_matrix.py --backend=ssh -m smoke -v -s

# Run integration test matrix (requires running daemons)
test-matrix-integration:
    @echo "Running integration test matrix..."
    pytest tests/scenarios/test_matrix.py --backend=ssh -m integration -v -s

# Analyze test matrix results
test-matrix-analyze:
    @echo "Analyzing test matrix results..."
    python scripts/analyze_matrix.py test-results/

# List recent test matrix results
test-matrix-list:
    @echo "Recent test matrix results:"
    @ls -lt test-results/matrix_*.json 2>/dev/null | head -10 || echo "  No results found"
