# Linux Test Device Deployment Guide

Standardized deployment path for styrened on Linux test devices (NixOS, Debian, Ubuntu, etc.).

## Prerequisites

- SSH access to target device
- Python 3.11+ available (or installable)
- Network connectivity (LAN for mesh testing)

## Deployment Methods

### Method 1: Wheel Transfer (Recommended for Private Repos)

Build wheel locally and transfer to device:

```bash
# On development machine
cd styrened
python3 -m build --wheel
scp dist/styrened-*.whl <user>@<host>:/tmp/
```

Then on target device:
```bash
# Create venv and install
python3 -m venv ~/.local/styrene-venv
source ~/.local/styrene-venv/bin/activate
pip install /tmp/styrened-*.whl
```

### Method 2: Git Install (Requires GitHub Auth)

```bash
python3 -m venv ~/.local/styrene-venv
source ~/.local/styrene-venv/bin/activate
pip install git+https://github.com/styrene-lab/styrened.git@v0.3.4
```

### Method 3: NixOS (via nix-shell)

```bash
nix-shell -p python311 python311Packages.pip python311Packages.virtualenv --run "
    python3 -m venv ~/.local/styrene-venv
"
source ~/.local/styrene-venv/bin/activate
pip install /tmp/styrened-*.whl
```

## Quick Deploy Script

Save as `deploy-styrened.sh` on your development machine:

```bash
#!/bin/bash
# Deploy styrened to a remote Linux host
# Usage: ./deploy-styrened.sh <hostname> [version]

set -e

HOST="${1:?Usage: $0 <hostname> [version]}"
VERSION="${2:-0.3.4}"
WHEEL="styrened-${VERSION}-py3-none-any.whl"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STYRENED_DIR="${SCRIPT_DIR}/.."

# Build wheel if not present
if [[ ! -f "${STYRENED_DIR}/dist/${WHEEL}" ]]; then
    echo "Building wheel..."
    cd "${STYRENED_DIR}"
    python3 -m build --wheel
fi

echo "Deploying styrened ${VERSION} to ${HOST}..."

# Transfer wheel
scp "${STYRENED_DIR}/dist/${WHEEL}" "${HOST}:/tmp/"

# Install on remote
ssh "${HOST}" bash -s << 'REMOTE_SCRIPT'
set -e

# Detect Python
if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python3.11 &>/dev/null; then
    PYTHON=python3.11
else
    echo "ERROR: Python 3 not found. Install python3 first."
    exit 1
fi

# Create venv if needed
if [[ ! -d ~/.local/styrene-venv ]]; then
    echo "Creating venv..."
    $PYTHON -m venv ~/.local/styrene-venv
fi

# Install/upgrade styrened
source ~/.local/styrene-venv/bin/activate
pip install --upgrade /tmp/styrened-*.whl

# Verify
styrened version
echo "Deployment complete!"
REMOTE_SCRIPT
```

## Standard Test Configuration

Create config on each test device:

```bash
ssh <host> 'mkdir -p ~/.config/styrene && cat > ~/.config/styrene/core-config.yaml' << 'EOF'
# Styrened test node configuration
# Device: <HOSTNAME>

reticulum:
  mode: standalone
  config_path_override: ~/.reticulum
  enable_transport: false
  announce_interval: 300
  interfaces:
    # LAN discovery
    auto:
      enabled: true
      group_id: styrene-test-lab
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

chat:
  enabled: true
  auto_reply_enabled: true
  auto_reply_cooldown: 60
  auto_reply_message: |
    Test node: {hostname}
    Version: {version}
    Uptime: {uptime}

ipc:
  enabled: true
  socket_path: null

logging:
  level: INFO
EOF
```

## Running the Daemon

### Interactive (for testing)

```bash
source ~/.local/styrene-venv/bin/activate
styrened -v daemon
```

### Background (simple)

```bash
source ~/.local/styrene-venv/bin/activate
nohup styrened daemon > /tmp/styrened.log 2>&1 &
echo $! > /tmp/styrened.pid
```

### Systemd User Service (persistent)

```bash
mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/styrened.service << 'EOF'
[Unit]
Description=Styrene Daemon
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/styrene-venv/bin/styrened daemon
Restart=always
RestartSec=10
Environment=STYRENE_CONFIG_DIR=%h/.config/styrene

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now styrened
```

## Test Device Registry

Track deployed test devices:

| Hostname | IP | OS | Hardware | Status | Notes |
|----------|----|----|----------|--------|-------|
| styrene-node | 192.168.0.57 | NixOS 24.11 | ASUS Q502LA | Active | First test node |
| | | | | | |
| | | | | | |

## Validation Checklist

Run on each newly deployed device:

```bash
source ~/.local/styrene-venv/bin/activate

# 1. Version check
styrened version

# 2. Identity check (creates if missing)
styrened identity

# 3. Start daemon briefly
timeout 10 styrened -v daemon || true

# 4. Device discovery (daemon must be running)
styrened devices -w 5

# 5. Check logs
tail -20 /tmp/styrened.log
```

## Multi-Node Testing

### Mesh Discovery Test

From any node, verify all test nodes are visible:

```bash
styrened devices -w 30 | grep -E "styrene-|test-"
```

### RPC Round-Trip Test

Query status from Node A to Node B:

```bash
# Get Node B's LXMF destination
ssh node-b 'source ~/.local/styrene-venv/bin/activate && styrened identity'

# From Node A, query Node B
styrened status <node-b-dest-hash> -w 60
```

### Command Execution Test

```bash
# Execute uptime on remote node
styrened exec <dest-hash> uptime -w 60
```

### Chat/Auto-Reply Test

```bash
# Send message, should trigger auto-reply
styrened send <dest-hash> "ping" -w 60
```

## Collecting Test Data

### Gather Node Info

```bash
#!/bin/bash
# Run on each test node to collect system info
echo "=== Node Report: $(hostname) ==="
echo "Date: $(date -Iseconds)"
echo "OS: $(cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)"
echo "Kernel: $(uname -r)"
echo "Arch: $(uname -m)"
echo "IP: $(hostname -I | awk '{print $1}')"
echo "Memory: $(free -h | awk '/^Mem:/{print $2}')"
echo "Disk: $(df -h / | awk 'NR==2{print $4}') free"
echo "Python: $(python3 --version 2>/dev/null || echo 'not found')"
echo "styrened: $(~/.local/styrene-venv/bin/styrened version 2>/dev/null || echo 'not installed')"
echo "Identity: $(~/.local/styrene-venv/bin/styrened identity 2>/dev/null | grep Hash | awk '{print $2}')"
```

### Daemon Health Check

```bash
# Check if daemon is running and responsive
ssh <host> 'pgrep -f "styrened daemon" && echo "Running" || echo "Not running"'
ssh <host> 'source ~/.local/styrene-venv/bin/activate && styrened devices 2>/dev/null | head -5'
```

## Troubleshooting

### Daemon Won't Start

```bash
# Check for existing process
pgrep -f styrened

# Check socket conflicts
ls -la /run/user/$(id -u)/styrened/

# Run with debug logging
styrened -v daemon 2>&1 | head -50
```

### Nodes Not Discovering Each Other

1. Verify same `group_id` in AutoInterface config
2. Check firewall: `sudo iptables -L -n | grep 4242`
3. Verify network connectivity: `ping <other-node-ip>`
4. Check RNS interfaces: Look for "interfaces establishing" in logs

### RPC Timeouts

- Increase wait time: `styrened status <dest> -w 120`
- Verify target daemon is running
- Check LXMF delivery destination matches

## Cleanup

### Stop Daemon

```bash
# If using systemd
systemctl --user stop styrened

# If running in background
kill $(cat /tmp/styrened.pid)
# or
pkill -f "styrened daemon"
```

### Full Uninstall

```bash
systemctl --user disable --now styrened 2>/dev/null || true
rm -rf ~/.local/styrene-venv
rm -rf ~/.config/styrene
rm -rf ~/.local/share/styrene
rm -rf ~/.styrene
rm -f ~/.config/systemd/user/styrened.service
```
