#!/bin/sh
# Entrypoint for styrened containers

set -e

# Resolve HOME — K8s runAsUser doesn't set it from /etc/passwd
HOME="${HOME:-/app}"
export HOME

# Configuration directory (STYRENE_CONFIG_DIR or XDG_CONFIG_HOME fallback)
CONFIG_DIR="${STYRENE_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}}"
mkdir -p "$CONFIG_DIR"

# RNS config directory (follows Path.home() / ".reticulum")
RNS_DIR="${HOME}/.reticulum"
mkdir -p "$RNS_DIR"

# If CONFIG_YAML env var is set, write it to config file
if [ -n "$CONFIG_YAML" ]; then
    echo "$CONFIG_YAML" > "$CONFIG_DIR/config.yaml"
    echo "[entrypoint] Wrote config from CONFIG_YAML env var"
fi

# If RNS_CONFIG env var is set, write it to reticulum config
if [ -n "$RNS_CONFIG" ]; then
    echo "$RNS_CONFIG" > "$RNS_DIR/config"
    echo "[entrypoint] Wrote RNS config from RNS_CONFIG env var"
fi

# Generate identity if it doesn't exist (unless SKIP_IDENTITY_GEN=1)
if [ "$SKIP_IDENTITY_GEN" != "1" ] && [ ! -f "$CONFIG_DIR/operator.key" ]; then
    echo "[entrypoint] Generating operator identity..."
    python3 -c "
import RNS
from pathlib import Path
identity = RNS.Identity()
identity.to_file(Path('$CONFIG_DIR/operator.key'))
print('[entrypoint] Generated identity:', identity.hexhash)
"
fi

# Log startup info
echo "[entrypoint] Starting styrened..."
echo "[entrypoint] HOME=$HOME"
echo "[entrypoint] Config dir: $CONFIG_DIR"
echo "[entrypoint] RNS dir: $RNS_DIR"
echo "[entrypoint] RNS log level: ${RNS_LOGLEVEL:-4}"
echo "[entrypoint] Command: $*"

# Execute command
exec "$@"
