#!/bin/bash
# Configure styrened on a remote test node with standard test settings
# Usage: ./setup-test-node-config.sh <hostname> [group_id]

set -e

HOST="${1:?Usage: $0 <hostname> [group_id]}"
GROUP_ID="${2:-styrene-test-lab}"

echo "=== Configuring styrened on ${HOST} ==="
echo "AutoInterface group_id: ${GROUP_ID}"
echo ""

# Get remote hostname for config
REMOTE_HOSTNAME=$(ssh "${HOST}" hostname)

ssh "${HOST}" bash -s "${GROUP_ID}" "${REMOTE_HOSTNAME}" << 'REMOTE_SCRIPT'
GROUP_ID="$1"
NODE_NAME="$2"

mkdir -p ~/.config/styrene

cat > ~/.config/styrene/core-config.yaml << EOF
# Styrened test node configuration
# Device: ${NODE_NAME}
# Generated: $(date -Iseconds)

reticulum:
  mode: standalone
  config_path_override: ~/.reticulum
  enable_transport: false
  announce_interval: 300
  interfaces:
    # LAN discovery - all nodes with same group_id will discover each other
    auto:
      enabled: true
      group_id: ${GROUP_ID}
    # TCP server for direct connections
    server:
      enabled: true
      listen_ip: 0.0.0.0
      port: 4242

rpc:
  enabled: true
  relay_mode: false
  allow_command_execution: true
  allowed_commands:
    - uptime
    - hostname
    - uname -a
    - df -h
    - free -h
    - cat /etc/os-release
    - ip addr show
    - ss -tlnp
    - ps aux --sort=-rss | head -10

chat:
  enabled: true
  auto_reply_enabled: true
  auto_reply_cooldown: 60
  auto_reply_message: |
    Test node: ${NODE_NAME}
    Version: {version}
    Uptime: {uptime}

ipc:
  enabled: true
  socket_path: null

logging:
  level: INFO
EOF

echo "Config written to ~/.config/styrene/core-config.yaml"
cat ~/.config/styrene/core-config.yaml
REMOTE_SCRIPT

echo ""
echo "=== Configuration complete for ${HOST} ==="
echo ""
echo "Start daemon with:"
echo "  ssh ${HOST} 'source ~/.local/styrene-venv/bin/activate && styrened daemon'"
