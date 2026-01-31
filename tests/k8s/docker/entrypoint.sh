#!/bin/bash
# Entrypoint for styrened k8s test containers

set -e

# Configuration directory
CONFIG_DIR="${STYRENE_CONFIG_DIR:-/root/.styrene}"
mkdir -p "$CONFIG_DIR"

# If CONFIG_YAML env var is set, write it to config file
if [ -n "$CONFIG_YAML" ]; then
    echo "$CONFIG_YAML" > "$CONFIG_DIR/config.yaml"
    echo "[entrypoint] Wrote config from CONFIG_YAML env var"
fi

# If RNS_CONFIG env var is set, write it to reticulum config
if [ -n "$RNS_CONFIG" ]; then
    mkdir -p /root/.reticulum
    echo "$RNS_CONFIG" > /root/.reticulum/config
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
echo "[entrypoint] Config dir: $CONFIG_DIR"
echo "[entrypoint] RNS log level: ${RNS_LOGLEVEL:-4}"
echo "[entrypoint] Command: $@"

# Execute command
exec "$@"
