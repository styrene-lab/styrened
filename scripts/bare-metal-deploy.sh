#!/usr/bin/env bash
# Deploy styrened wheel to bare-metal fleet devices.
#
# Reads device registry from tests/bare-metal/devices.yaml.
# Handles venv bootstrapping, wheel deployment, and identity creation.
#
# Usage:
#   ./scripts/bare-metal-deploy.sh                 # Deploy to all reachable devices
#   ./scripts/bare-metal-deploy.sh styrene-node     # Deploy to specific device
#   ./scripts/bare-metal-deploy.sh --build          # Build wheel first, then deploy
#   ./scripts/bare-metal-deploy.sh --status         # Just show fleet status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEVICES_YAML="$PROJECT_ROOT/tests/bare-metal/devices.yaml"
SSH_TIMEOUT=10

# ─── Helpers ──────────────────────────────────────────────────────────────

log()  { printf "  %-14s %s\n" "$1" "$2"; }
ok()   { log "$1" "✓ $2"; }
fail() { log "$1" "✗ $2"; }
info() { echo ":: $*"; }

# Parse device names and hosts from devices.yaml (works without yq)
get_devices() {
    python3 -c "
import yaml, sys
with open('$DEVICES_YAML') as f:
    data = yaml.safe_load(f)
for name, info in data.get('devices', {}).items():
    print(f\"{name} {info['host']} {info.get('venv_path', '~/.local/styrene-venv')}\")
" 2>/dev/null || {
        # Fallback: parse with grep if python3+yaml unavailable
        grep -E '^\s+host:' "$DEVICES_YAML" | sed 's/.*host:\s*//'
    }
}

get_device_info() {
    local device="$1"
    python3 -c "
import yaml
with open('$DEVICES_YAML') as f:
    data = yaml.safe_load(f)
d = data['devices'].get('$device', {})
print(d.get('host', ''))
print(d.get('venv_path', '~/.local/styrene-venv'))
print(d.get('os', 'unknown'))
" 2>/dev/null
}

is_reachable() {
    ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$1" "echo ok" &>/dev/null
}

find_wheel() {
    ls -t "$PROJECT_ROOT"/dist/styrened-*.whl 2>/dev/null | head -1
}

# ─── Commands ─────────────────────────────────────────────────────────────

cmd_status() {
    info "Fleet status"
    while IFS=' ' read -r name host venv; do
        if is_reachable "$host"; then
            version=$(ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$host" \
                "source $venv/bin/activate 2>/dev/null && styrened --version 2>/dev/null || echo 'not installed'" 2>/dev/null)
            ok "$name:" "$version ($host)"
        else
            fail "$name:" "unreachable ($host)"
        fi
    done < <(get_devices)
}

cmd_deploy() {
    local target_device="${1:-}"
    local wheel
    wheel=$(find_wheel)

    if [ -z "$wheel" ]; then
        echo "Error: No wheel found in dist/. Run with --build or: python -m build --wheel" >&2
        exit 1
    fi

    local wheel_name
    wheel_name=$(basename "$wheel")
    local wheel_version
    wheel_version=$(echo "$wheel_name" | sed 's/styrened-\([^-]*\)-.*/\1/')

    info "Deploying $wheel_name"
    echo ""

    while IFS=' ' read -r name host venv; do
        # Filter to specific device if requested
        if [ -n "$target_device" ] && [ "$name" != "$target_device" ]; then
            continue
        fi

        printf "  %-14s " "$name:"

        # Check reachability
        if ! is_reachable "$host"; then
            echo "⊘ unreachable"
            continue
        fi

        # Read device OS for bootstrap decisions
        local dev_os
        dev_os=$(python3 -c "
import yaml
with open('$DEVICES_YAML') as f:
    data = yaml.safe_load(f)
print(data['devices'].get('$name', {}).get('os', 'unknown'))
" 2>/dev/null)

        # Bootstrap: ensure venv exists
        local has_venv
        has_venv=$(ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$host" \
            "test -f $venv/bin/activate && echo yes || echo no" 2>/dev/null)

        if [ "$has_venv" = "no" ]; then
            printf "creating venv... "
            # Install python3-venv if needed (Debian)
            if [[ "$dev_os" == Debian* ]]; then
                ssh -o BatchMode=yes "$host" \
                    "sudo apt-get install -y python3-venv >/dev/null 2>&1 || true" 2>/dev/null
            fi
            ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$host" \
                "python3 -m venv $venv" 2>/dev/null
        fi

        # Deploy wheel
        scp -q "$wheel" "$host:/tmp/$wheel_name" 2>/dev/null
        local pip_out
        pip_out=$(ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$host" \
            "source $venv/bin/activate && pip install --upgrade /tmp/$wheel_name 2>&1" 2>/dev/null)

        # Verify
        local installed_version
        installed_version=$(ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$host" \
            "source $venv/bin/activate && styrened --version 2>/dev/null" 2>/dev/null | awk '{print $NF}')

        if [ "$installed_version" = "$wheel_version" ]; then
            echo "✓ $installed_version"
        else
            echo "✗ expected $wheel_version, got ${installed_version:-nothing}"
        fi

        # Bootstrap: ensure identity exists
        local has_identity
        has_identity=$(ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$host" \
            "source $venv/bin/activate && styrened identity --json 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get(\"exists\",False))' 2>/dev/null" 2>/dev/null)

        if [ "$has_identity" != "True" ]; then
            log "" "  → creating identity..."
            ssh -o BatchMode=yes "$host" \
                "source $venv/bin/activate && styrened identity --create 2>/dev/null" 2>/dev/null
        fi

        # Bootstrap: ensure config exists
        local config_path
        config_path=$(python3 -c "
import yaml
with open('$DEVICES_YAML') as f:
    data = yaml.safe_load(f)
print(data['devices'].get('$name', {}).get('config_path', '~/.config/styrene'))
" 2>/dev/null)

        local has_config
        has_config=$(ssh -o BatchMode=yes -o ConnectTimeout=$SSH_TIMEOUT "$host" \
            "test -f $config_path/core-config.yaml && echo yes || echo no" 2>/dev/null)

        if [ "$has_config" = "no" ]; then
            log "" "  → creating default config..."
            ssh -o BatchMode=yes "$host" "mkdir -p $config_path && cat > $config_path/core-config.yaml << 'YAML'
reticulum:
  mode: standalone
  interfaces:
    auto:
      enabled: true
YAML" 2>/dev/null
        fi

    done < <(get_devices)

    echo ""
    info "Done"
}

# ─── Main ─────────────────────────────────────────────────────────────────

case "${1:-}" in
    --status|-s)
        cmd_status
        ;;
    --build|-b)
        info "Building wheel..."
        (cd "$PROJECT_ROOT" && python3 -m build --wheel 2>&1 | tail -1)
        echo ""
        shift
        cmd_deploy "${1:-}"
        ;;
    --help|-h)
        echo "Usage: $(basename "$0") [OPTIONS] [DEVICE]"
        echo ""
        echo "Deploy styrened to bare-metal fleet devices."
        echo ""
        echo "Options:"
        echo "  --build, -b     Build wheel before deploying"
        echo "  --status, -s    Show fleet status only"
        echo "  --help, -h      Show this help"
        echo ""
        echo "If DEVICE is specified, only deploy to that device."
        echo "Reads device registry from tests/bare-metal/devices.yaml."
        ;;
    --*)
        echo "Unknown option: $1" >&2
        exit 1
        ;;
    *)
        cmd_deploy "${1:-}"
        ;;
esac
