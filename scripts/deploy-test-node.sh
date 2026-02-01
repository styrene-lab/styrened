#!/bin/bash
# Deploy styrened to a remote Linux test node
# Usage: ./deploy-test-node.sh <hostname> [version]
#
# Examples:
#   ./deploy-test-node.sh styrene-node
#   ./deploy-test-node.sh styrene-node 0.3.4
#   ./deploy-test-node.sh user@192.168.0.57

set -e

HOST="${1:?Usage: $0 <hostname> [version]}"
VERSION="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STYRENED_DIR="${SCRIPT_DIR}/.."

# Get version from pyproject.toml if not specified
if [[ -z "$VERSION" ]]; then
    VERSION=$(grep '^version = ' "${STYRENED_DIR}/pyproject.toml" | cut -d'"' -f2)
fi

WHEEL="styrened-${VERSION}-py3-none-any.whl"

echo "=== Deploying styrened ${VERSION} to ${HOST} ==="

# Build wheel if not present or outdated
if [[ ! -f "${STYRENED_DIR}/dist/${WHEEL}" ]]; then
    echo "Building wheel..."
    cd "${STYRENED_DIR}"
    pip install build 2>/dev/null || true
    python3 -m build --wheel
fi

# Transfer wheel
echo "Transferring wheel to ${HOST}..."
scp "${STYRENED_DIR}/dist/${WHEEL}" "${HOST}:/tmp/"

# Install on remote
echo "Installing on ${HOST}..."
ssh "${HOST}" bash -s "${VERSION}" << 'REMOTE_SCRIPT'
set -e
VERSION="$1"

# Detect Python
PYTHON=""
for cmd in python3.12 python3.11 python3; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    # Try nix-shell for NixOS
    if command -v nix-shell &>/dev/null; then
        echo "Using nix-shell for Python..."
        nix-shell -p python311 python311Packages.pip python311Packages.virtualenv --run "
            if [[ ! -d ~/.local/styrene-venv ]]; then
                python3 -m venv ~/.local/styrene-venv
            fi
        "
        PYTHON="python3"
    else
        echo "ERROR: Python 3.11+ not found. Please install python3 first."
        exit 1
    fi
fi

echo "Using Python: $PYTHON ($($PYTHON --version))"

# Create venv if needed
if [[ ! -d ~/.local/styrene-venv ]]; then
    echo "Creating virtual environment..."
    $PYTHON -m venv ~/.local/styrene-venv
fi

# Activate and install
source ~/.local/styrene-venv/bin/activate
echo "Installing styrened ${VERSION}..."
pip install --upgrade --quiet pip
pip install --upgrade --force-reinstall /tmp/styrened-*.whl

# Verify installation
echo ""
echo "=== Installation Complete ==="
styrened version

# Show identity (creates if needed)
echo ""
styrened identity

# Check if daemon is already running
if pgrep -f "styrened daemon" > /dev/null; then
    echo ""
    echo "NOTE: Daemon is already running. Restart to use new version:"
    echo "  systemctl --user restart styrened"
    echo "  # or: pkill -f 'styrened daemon' && nohup styrened daemon > /tmp/styrened.log 2>&1 &"
fi
REMOTE_SCRIPT

echo ""
echo "=== Deployment to ${HOST} complete ==="
echo ""
echo "Next steps:"
echo "  1. SSH to ${HOST}"
echo "  2. Create config: mkdir -p ~/.config/styrene && vi ~/.config/styrene/core-config.yaml"
echo "  3. Start daemon: source ~/.local/styrene-venv/bin/activate && styrened daemon"
echo ""
echo "Or run validation: ./scripts/validate-test-node.sh ${HOST}"
