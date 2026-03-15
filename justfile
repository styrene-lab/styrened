# Justfile for styrened development and build automation
#
# Just is a command runner - install via: brew install just / cargo install just
# Run `just` or `just --list` to see available recipes

# ─── Configuration ──────────────────────────────────────────────────────────

# Project paths
project_root := justfile_directory()
container_dir := project_root / "container"
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
    .venv/bin/python -m pytest tests/ --ignore=tests/k8s/

# Run unit tests only (parallel, ~4s)
test-unit:
    .venv/bin/python -m pytest tests/unit/ -n auto -q --tb=short

# Run TUI tests only (parallel, ~2min)
test-tui:
    .venv/bin/python -m pytest tests/tui/ -n auto -q --tb=short

# Fast smoke: unit + TUI widgets/services/models (~36s, 3200+ tests)
# Skips slow Textual run_test() screen tests and navigation workflows
test-fast:
    .venv/bin/python -m pytest tests/unit/ tests/tui/ -n auto -q --tb=short \
        --ignore=tests/tui/screens \
        --ignore=tests/tui/test_navigation_workflows.py \
        --ignore=tests/tui/integration \
        --ignore=tests/tui/test_screens.py \
        --ignore=tests/tui/test_app.py

# Run local integration tests (no k8s)
test-integration:
    .venv/bin/python -m pytest tests/integration/ -v

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

# ── Dev workflow ────────────────────────────────────────────────────────────

# Dev home — isolated from production config/data.
# Override with STYRENE_HOME env var if you want a different location.
_dev_home := env_var_or_default("STYRENE_HOME", env_var("HOME") + "/.styrene-dev")

# Stop the system service and run the venv daemon in the foreground (Ctrl-C to stop).
# Merges dev/profiles/_base.yaml + dev/profiles/<profile>.yaml into the dev home
# before launching. Use profile= to select a profile (default: standard).
# Use ephemeral=true to run with a temp identity discarded on exit.
#
# Profiles:
#   standard (default) — AutoInterface + Styrene hub, no extras
#   hub                — standard + LXMF propagation enabled (tests hub status)
#   overlay            — hub + yggdrasil/i2p in adopt mode (tests COP adapter row)
#   full               — all well-known hubs + hub propagation + API
#   minimal            — RNS + LXMF only, low-noise baseline
#
# Examples:
#   just dev-daemon                    # standard profile, persistent QA identity
#   just dev-daemon profile=hub        # with LXMF propagation → hub status visible
#   just dev-daemon profile=overlay    # hub + ygg + i2p adapt (requires local daemons)
#   just dev-daemon profile=full       # all hubs up, API on
#   just dev-daemon profile=minimal    # RNS + LXMF only
#   just dev-daemon ephemeral=true     # throwaway identity, standard profile
dev-daemon profile="standard" ephemeral="false":
    #!/usr/bin/env bash
    set -euo pipefail

    PROFILE="{{ profile }}"
    EPHEMERAL="{{ ephemeral }}"
    DEV_HOME="{{ _dev_home }}"

    # Ephemeral: use a temp dir, cleaned up on exit
    if [[ "$EPHEMERAL" == "true" ]]; then
        DEV_HOME="$(mktemp -d)"
        trap "rm -rf '$DEV_HOME'" EXIT
        echo "→ Ephemeral mode: dev home at $DEV_HOME (discarded on exit)"
    fi

    CONFIG_OUT="$DEV_HOME/config/config.yaml"

    echo "→ Stopping system service (if any)..."
    if [[ "$(uname)" == "Darwin" ]]; then
        launchctl unload ~/Library/LaunchAgents/com.styrene.styrened.plist 2>/dev/null || true
    else
        systemctl --user stop styrened.service 2>/dev/null || true
    fi

    echo "→ Merging profile '$PROFILE' → $CONFIG_OUT"
    .venv/bin/python dev/merge_profile.py "$PROFILE" "$CONFIG_OUT"

    echo "→ Starting dev daemon ($(STYRENE_HOME="$DEV_HOME" .venv/bin/python -c 'import styrened; print(styrened.__version__)'), profile=$PROFILE)..."
    echo "   STYRENE_HOME=$DEV_HOME"
    STYRENE_HOME="$DEV_HOME" .venv/bin/styrened daemon

# Alias for dev-daemon — use when you just want a clean slate.
dev-reset profile="standard": (dev-daemon profile)

# Launch the TUI — starts the dev daemon in the background automatically,
# waits for it to be ready, runs the TUI, then kills the daemon on exit.
# You own the TUI. The justfile owns the daemon. profile= selects a profile.
dev-tui profile="standard":
    #!/usr/bin/env bash
    set -euo pipefail

    DEV_HOME="{{ _dev_home }}"
    PROFILE="{{ profile }}"
    CONFIG_OUT="$DEV_HOME/config/config.yaml"
    SOCK="$DEV_HOME/run/control.sock"
    LOG="$DEV_HOME/logs/daemon-dev.log"

    # Stop system service so it doesn't collide
    if [[ "$(uname)" == "Darwin" ]]; then
        launchctl unload ~/Library/LaunchAgents/com.styrene.styrened.plist 2>/dev/null || true
    else
        systemctl --user stop styrened.service 2>/dev/null || true
    fi

    # Merge profile config
    mkdir -p "$DEV_HOME/config" "$DEV_HOME/logs"
    .venv/bin/python dev/merge_profile.py "$PROFILE" "$CONFIG_OUT"

    # Kill any leftover daemon from a previous session
    if [[ -S "$SOCK" ]]; then
        OLD_PID=$(lsof -t "$SOCK" 2>/dev/null || true)
        if [[ -n "$OLD_PID" ]]; then
            echo "→ Killing stale dev daemon (pid $OLD_PID)..."
            kill "$OLD_PID" 2>/dev/null || true
            sleep 0.5
        fi
        rm -f "$SOCK"
    fi

    # Start daemon in background, fully detached from terminal.
    # < /dev/null: daemon has no stdin — prevents it from stealing terminal input
    # and interfering with Textual's raw mode.
    echo "→ Starting dev daemon (profile=$PROFILE) → $LOG"
    STYRENE_HOME="$DEV_HOME" .venv/bin/styrened daemon < /dev/null >> "$LOG" 2>&1 &
    DAEMON_PID=$!
    echo "   daemon pid=$DAEMON_PID"

    # Ensure daemon is killed when the TUI exits (normal or signal)
    trap "echo '→ Stopping dev daemon (pid $DAEMON_PID)...'; kill $DAEMON_PID 2>/dev/null || true; wait $DAEMON_PID 2>/dev/null || true" EXIT

    # Wait for socket to appear (up to 15s)
    echo -n "→ Waiting for daemon socket"
    for i in $(seq 1 30); do
        if [[ -S "$SOCK" ]]; then
            echo " ready (${i}×0.5s)"
            break
        fi
        echo -n "."
        sleep 0.5
        if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
            echo ""
            echo "✗ Dev daemon exited unexpectedly. Check $LOG"
            exit 1
        fi
    done

    if [[ ! -S "$SOCK" ]]; then
        echo ""
        echo "✗ Daemon socket never appeared after 15s. Check $LOG"
        kill "$DAEMON_PID" 2>/dev/null || true
        exit 1
    fi

    # Run the TUI — blocks until user exits
    echo "→ Launching TUI..."
    STYRENE_HOME="$DEV_HOME" .venv/bin/styrene

# Launch the compact dashboard — same lifecycle management as dev-tui.
dev-dashboard profile="standard":
    #!/usr/bin/env bash
    set -euo pipefail

    DEV_HOME="{{ _dev_home }}"
    PROFILE="{{ profile }}"
    CONFIG_OUT="$DEV_HOME/config/config.yaml"
    SOCK="$DEV_HOME/run/control.sock"
    LOG="$DEV_HOME/logs/daemon-dev.log"

    if [[ "$(uname)" == "Darwin" ]]; then
        launchctl unload ~/Library/LaunchAgents/com.styrene.styrened.plist 2>/dev/null || true
    else
        systemctl --user stop styrened.service 2>/dev/null || true
    fi

    mkdir -p "$DEV_HOME/config" "$DEV_HOME/logs"
    .venv/bin/python dev/merge_profile.py "$PROFILE" "$CONFIG_OUT"

    if [[ -S "$SOCK" ]]; then
        OLD_PID=$(lsof -t "$SOCK" 2>/dev/null || true)
        if [[ -n "$OLD_PID" ]]; then
            kill "$OLD_PID" 2>/dev/null || true
            sleep 0.5
        fi
        rm -f "$SOCK"
    fi

    echo "→ Starting dev daemon (profile=$PROFILE) → $LOG"
    STYRENE_HOME="$DEV_HOME" .venv/bin/styrened daemon < /dev/null >> "$LOG" 2>&1 &
    DAEMON_PID=$!
    trap "kill $DAEMON_PID 2>/dev/null || true; wait $DAEMON_PID 2>/dev/null || true" EXIT

    echo -n "→ Waiting for daemon socket"
    for i in $(seq 1 30); do
        if [[ -S "$SOCK" ]]; then echo " ready"; break; fi
        echo -n "."; sleep 0.5
        if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
            echo ""; echo "✗ Daemon exited. Check $LOG"; exit 1
        fi
    done

    STYRENE_HOME="$DEV_HOME" .venv/bin/styrene --dashboard

# Restore the system service after dev work.
dev-restore:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ "$(uname)" == "Darwin" ]]; then
        launchctl load ~/Library/LaunchAgents/com.styrene.styrened.plist
        echo "✓ launchd service restored"
    else
        systemctl --user start styrened.service
        echo "✓ systemd service restored"
    fi

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

# Check version synchronization across canonical sources
check-versions:
    #!/usr/bin/env bash
    set -euo pipefail
    INIT_VER=$(grep '^__version__ = ' src/styrened/__init__.py | cut -d'"' -f2)
    FILE_VER=$(cat VERSION)
    echo "__init__.py: $INIT_VER"
    echo "VERSION:     $FILE_VER"
    if [[ "$INIT_VER" == "$FILE_VER" ]]; then
        echo "OK: Versions synchronized"
    else
        echo "ERROR: VERSION DRIFT DETECTED"
        exit 1
    fi

# ─── Container Build ───────────────────────────────────────────────────────

# Build Python wheel (for PyPI / GitHub Release distribution)
build-wheel:
    #!/usr/bin/env bash
    set -euo pipefail
    expected="dist/styrened-{{ version }}-py3-none-any.whl"
    if [ -f "$expected" ]; then
        echo "Wheel exists: $expected"
    else
        echo "Building wheel..."
        python scripts/generate_changelog.py
        rm -f dist/styrened-*.whl
        python -m build --wheel
    fi
    ls -la dist/styrened-*.whl | tail -1

# Build OCI production image (via nix2container)
build:
    nix build .#oci
    @echo "Built: $(readlink result)"

# Build OCI test image (via nix2container)
build-test:
    nix build .#oci-test
    @echo "Built: $(readlink result)"

# Load OCI image into local podman (via nix2container)
load: build
    nix run .#oci.copyToPodman

# Load test image into local podman (via nix2container)
load-test: build-test
    nix run .#oci-test.copyToPodman

# Validate production image
test-image: load
    podman run --rm {{ registry }}/{{ image_prod }}:{{ version }} styrened --version

# Validate test image
test-image-test: load-test
    podman run --rm {{ registry }}/{{ image_test }}:{{ version }} styrened --version

# ─── Registry Push ──────────────────────────────────────────────────────────

# Login to GHCR (uses GITHUB_TOKEN env var or gh CLI)
container-login:
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ -n "${GITHUB_TOKEN:-}" ]]; then
        echo "$GITHUB_TOKEN" | podman login {{ registry }} -u "${GITHUB_ACTOR:-$(gh api user -q .login)}" --password-stdin
    else
        echo "GITHUB_TOKEN not set, attempting gh CLI auth..."
        gh auth token | podman login {{ registry }} -u "$(gh api user -q .login)" --password-stdin
    fi

# Push production image with version and commit tags
push-prod: container-login build
    nix run .#oci.copyToPodman
    podman push {{ registry }}/{{ image_prod }}:{{ version }}
    podman tag {{ registry }}/{{ image_prod }}:{{ version }} {{ registry }}/{{ image_prod }}:{{ commit_sha }}
    podman push {{ registry }}/{{ image_prod }}:{{ commit_sha }}

# Push production image with 'latest' tag (stable releases only)
push-prod-latest: push-prod
    podman tag {{ registry }}/{{ image_prod }}:{{ version }} {{ registry }}/{{ image_prod }}:latest
    podman push {{ registry }}/{{ image_prod }}:latest

# Push nightly build (:nightly + :nightly-{sha})
push-nightly: container-login build
    nix run .#oci.copyToPodman
    podman tag {{ registry }}/{{ image_prod }}:{{ version }} {{ registry }}/{{ image_prod }}:nightly
    podman push {{ registry }}/{{ image_prod }}:nightly
    podman tag {{ registry }}/{{ image_prod }}:{{ version }} {{ registry }}/{{ image_prod }}:nightly-{{ commit_sha }}
    podman push {{ registry }}/{{ image_prod }}:nightly-{{ commit_sha }}

# Push test image with 'latest' tag (nightly builds)
push-test-nightly: container-login build-test
    nix run .#oci-test.copyToPodman
    podman push {{ registry }}/{{ image_test }}:{{ version }}
    podman tag {{ registry }}/{{ image_test }}:{{ version }} {{ registry }}/{{ image_test }}:latest
    podman push {{ registry }}/{{ image_test }}:latest

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

# Load OCI test image into k8s cluster (auto-detect kind/k3d/k3s)
load-k8s-image: build-test
    #!/usr/bin/env bash
    set -euo pipefail
    # Load into local podman first (via nix2container)
    nix run .#oci-test.copyToPodman
    cluster_type=$(just cluster-type)
    echo "Detected cluster type: $cluster_type"
    case "$cluster_type" in
        kind)
            ctx=$(kubectl config current-context)
            podman save {{ registry }}/{{ image_test }}:{{ version }} | \
                kind load image-archive /dev/stdin --name "${ctx#kind-}"
            ;;
        k3d)
            ctx=$(kubectl config current-context)
            podman save {{ registry }}/{{ image_test }}:{{ version }} -o /tmp/styrened-test.tar
            k3d image import /tmp/styrened-test.tar -c "${ctx#k3d-}"
            rm -f /tmp/styrened-test.tar
            ;;
        k3s-remote)
            podman save {{ registry }}/{{ image_test }}:{{ version }} | gzip > /tmp/styrened-image.tar.gz
            scp /tmp/styrened-image.tar.gz {{ k3s_host }}:/tmp/
            ssh {{ k3s_host }} "sudo k3s ctr images import /tmp/styrened-image.tar.gz"
            rm -f /tmp/styrened-image.tar.gz
            ;;
        k3s-local)
            podman save {{ registry }}/{{ image_test }}:{{ version }} | sudo k3s ctr images import -
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
    .venv/bin/python -m pytest tests/k8s/

# Run k8s smoke tests only (fast)
test-k8s-smoke:
    .venv/bin/python -m pytest tests/k8s/scenarios/ -m smoke -v

# Run full k8s test suite including slow tests
test-k8s-full:
    .venv/bin/python -m pytest tests/k8s/scenarios/ --run-slow -v

# Build, load image, and deploy test stack
test-k8s-deploy: load-k8s-image helm-install
    @echo "Test stack deployed"

# Run k8s tests (assumes image already deployed)
test-k8s-run:
    .venv/bin/python -m pytest tests/k8s/scenarios/ -v -m smoke --tb=short

# Complete local k8s test workflow: build, load, test
test-k8s-local: load-k8s-image
    @echo "=== K8s Local Test Workflow ==="
    .venv/bin/python -m pytest tests/k8s/scenarios/ -v -m smoke --tb=short
    @echo "=== Complete ==="

# Complete remote k8s test workflow: create secret, deploy from GHCR, test
test-k8s-remote: create-ghcr-secret helm-install-ghcr
    @echo "=== K8s Remote Test Workflow (GHCR) ==="
    .venv/bin/python -m pytest tests/k8s/scenarios/ -v -m smoke --tb=short
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
    podman rmi {{ registry }}/{{ image_test }}:{{ version }} 2>/dev/null || true
    podman rmi {{ registry }}/{{ image_test }}:{{ commit_sha }} 2>/dev/null || true
    podman rmi {{ registry }}/{{ image_prod }}:{{ version }} 2>/dev/null || true
    podman rmi {{ registry }}/{{ image_prod }}:{{ commit_sha }} 2>/dev/null || true
    podman rmi {{ local_image_tag }} 2>/dev/null || true
    podman rmi {{ image_test }}:test 2>/dev/null || true

# Remove all build artifacts and images
clean-all: clean clean-images
    rm -rf build/ dist/ *.egg-info

# ─── Release Helpers ────────────────────────────────────────────────────────

# Bump version in canonical sources (interactive)
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
    # Update __init__.py (canonical source — hatchling reads this)
    sed -i '' 's/__version__ = ".*"/__version__ = "{{ new_version }}"/' src/styrened/__init__.py
    # Update VERSION file (mirrors for Nix flake)
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

# Full release workflow: validate, QA gate, bump, commit, tag
# Use `just release X.Y.Z --skip-qa` to bypass visual QA (hotfixes only)
release new_version *flags: validate
    #!/usr/bin/env bash
    set -euo pipefail
    if [[ "{{ flags }}" == *"--skip-qa"* ]]; then
        bash scripts/qa_gate.sh --skip
    else
        bash scripts/qa_gate.sh
    fi
    just bump-version {{ new_version }}
    git add src/styrened/__init__.py VERSION
    git commit -m "chore: bump version to {{ new_version }}"
    just tag-release
    @echo ""
    @echo "Release prepared. Publishing..."
    git push origin main --tags
    just publish

# Build wheel+sdist and publish to PyPI immediately
publish:
    #!/usr/bin/env bash
    set -euo pipefail
    VERSION=$(cat VERSION)
    # Bake changelog into package from git tags
    .venv/bin/python scripts/generate_changelog.py
    rm -rf dist/
    .venv/bin/python -m build
    .venv/bin/python -m twine upload --skip-existing dist/*
    echo ""
    echo "✓ Published $VERSION to PyPI"
    # Notify styrene-pypi meta-package to sync version immediately.
    # Bypasses hourly cron + PyPI CDN staleness on GitHub Actions runners.
    echo "Notifying styrene-pypi to sync to $VERSION..."
    gh api repos/styrene-lab/styrene-pypi/dispatches \
      -f event_type=styrened-release \
      -f "client_payload[version]=$VERSION" \
      && echo "✓ styrene-pypi sync triggered" \
      || echo "⚠ styrene-pypi dispatch failed (non-fatal)"

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
    .venv/bin/python -m pytest tests/bare-metal/test_smoke.py -v

# Deploy wheel to bare-metal devices and verify
test-bare-metal-deploy:
    @echo "Building wheel..."
    python -m build --wheel
    @echo "Running bare-metal deployment tests..."
    .venv/bin/python -m pytest tests/bare-metal/test_deployment.py -v

# Mesh integration tests (requires running daemons)
test-bare-metal-mesh:
    @echo "Running bare-metal mesh tests..."
    .venv/bin/python -m pytest tests/bare-metal/test_mesh.py -v

# Run all bare-metal tests (smoke + mesh)
test-bare-metal: test-bare-metal-smoke test-bare-metal-mesh
    @echo "All bare-metal tests complete"

# Run bare-metal tests on specific device
test-bare-metal-device device:
    @echo "Running tests on {{ device }}..."
    .venv/bin/python -m pytest tests/bare-metal/ -v -k "{{ device }}"

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
    .venv/bin/python -m pytest tests/scenarios/ --backend=ssh -v

# Run cross-platform scenarios on K8s backend
test-scenarios-k8s namespace="styrene-test":
    @echo "Running cross-platform scenarios on K8s backend..."
    .venv/bin/python -m pytest tests/scenarios/ --backend=k8s --k8s-namespace={{ namespace }} -v

# Run cross-platform scenarios on both backends
test-scenarios-both namespace="styrene-test":
    @echo "Running cross-platform scenarios on both backends..."
    .venv/bin/python -m pytest tests/scenarios/ --backend=both --k8s-namespace={{ namespace }} -v

# Run smoke-tier cross-platform tests (fast validation)
test-scenarios-smoke backend="ssh":
    @echo "Running smoke scenarios on {{ backend }} backend..."
    .venv/bin/python -m pytest tests/scenarios/ --backend={{ backend }} -m smoke -v

# Run integration-tier cross-platform tests
test-scenarios-integration backend="ssh":
    @echo "Running integration scenarios on {{ backend }} backend..."
    .venv/bin/python -m pytest tests/scenarios/ --backend={{ backend }} -m integration -v

# Run comprehensive cross-platform tests
test-scenarios-comprehensive backend="ssh":
    @echo "Running comprehensive scenarios on {{ backend }} backend..."
    .venv/bin/python -m pytest tests/scenarios/ --backend={{ backend }} -m comprehensive -v

# ─── Installation Testing ───────────────────────────────────────────────────
#
# Installation tests handle deployment/provisioning of styrened.
# These are separate from connectivity/mesh tests which assume working installation.

# Run installation smoke tests (validate existing installation)
test-install-smoke:
    @echo "Running installation smoke tests..."
    .venv/bin/python -m pytest tests/scenarios/test_installation.py --backend=ssh -m smoke -v

# Run full installation tests (install/upgrade cycles)
test-install:
    @echo "Running installation tests..."
    .venv/bin/python -m pytest tests/scenarios/test_installation.py --backend=ssh -m installation -v

# Run provisioning tests (install + systemd setup)
test-provision:
    @echo "Running provisioning tests..."
    .venv/bin/python -m pytest tests/scenarios/test_installation.py --backend=ssh -m provisioning -v

# Install from specific git tag on all devices
test-install-tag tag:
    @echo "Installing tag {{ tag }} on all devices..."
    .venv/bin/python -m pytest tests/scenarios/test_installation.py::TestPipGitInstallation::test_install_from_tag \
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
    .venv/bin/python -m pytest tests/scenarios/test_installation.py::TestWheelInstallation::test_install_from_wheel \
        --backend=ssh --wheel-path="$wheel" -v

# Full provisioning workflow on all devices
test-provision-all:
    @echo "Provisioning all devices..."
    .venv/bin/python -m pytest tests/scenarios/test_installation.py::TestFullProvisioning::test_provision_all_nodes \
        --backend=ssh -v

# ─── Test Matrix ────────────────────────────────────────────────────────────
#
# Structured test scenarios with expected parameters and results for analysis.

# Run full test matrix (smoke + integration)
test-matrix:
    @echo "Running test matrix..."
    .venv/bin/python -m pytest tests/scenarios/test_matrix.py --backend=ssh -v -s 2>&1 | tee test-results/matrix-$(date +%Y%m%d_%H%M%S).log

# Run smoke test matrix only
test-matrix-smoke:
    @echo "Running smoke test matrix..."
    .venv/bin/python -m pytest tests/scenarios/test_matrix.py --backend=ssh -m smoke -v -s

# Run integration test matrix (requires running daemons)
test-matrix-integration:
    @echo "Running integration test matrix..."
    .venv/bin/python -m pytest tests/scenarios/test_matrix.py --backend=ssh -m integration -v -s

# Analyze test matrix results
test-matrix-analyze:
    @echo "Analyzing test matrix results..."
    python scripts/analyze_matrix.py test-results/

# List recent test matrix results
test-matrix-list:
    @echo "Recent test matrix results:"
    @ls -lt test-results/matrix_*.json 2>/dev/null | head -10 || echo "  No results found"
