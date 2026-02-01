#!/bin/bash
# Validate styrened installation on a remote test node
# Usage: ./validate-test-node.sh <hostname>

set -e

HOST="${1:?Usage: $0 <hostname>}"

echo "=== Validating styrened on ${HOST} ==="
echo ""

ssh -o ConnectTimeout=10 -o ServerAliveInterval=5 "${HOST}" bash << 'REMOTE_SCRIPT'
VENV=~/.local/styrene-venv
PASS=0
FAIL=0

pass() { echo "✓ $1"; ((PASS++)); }
fail() { echo "✗ $1"; ((FAIL++)); }

echo "--- Environment ---"

# Check for Python (may be in venv only on NixOS)
if command -v python3 &>/dev/null; then
    pass "Python installed (system)"
elif [[ -x "$VENV/bin/python3" ]]; then
    pass "Python installed (venv only)"
else
    fail "Python not found"
fi

[[ -d "$VENV" ]] && pass "Venv exists" || fail "Venv missing"
[[ -x "$VENV/bin/styrened" ]] && pass "styrened installed" || fail "styrened not installed"

if [[ -x "$VENV/bin/styrened" ]]; then
    source "$VENV/bin/activate"

    echo ""
    echo "--- Version ---"
    styrened version

    echo ""
    echo "--- Identity ---"
    styrened identity

    echo ""
    echo "--- Config ---"
    if [[ -f ~/.config/styrene/core-config.yaml ]]; then
        pass "Config file exists"
        echo "  Path: ~/.config/styrene/core-config.yaml"
        MODE=$(grep -E '^\s+mode:' ~/.config/styrene/core-config.yaml 2>/dev/null | head -1 | awk '{print $2}')
        echo "  Mode: ${MODE:-unknown}"
    else
        fail "Config file missing"
    fi

    echo ""
    echo "--- Daemon Status ---"
    if pgrep -f "styrened daemon" &>/dev/null; then
        pass "Daemon running"
        PID=$(pgrep -f "styrened daemon" | head -1)
        echo "  PID: $PID"
        UPTIME=$(ps -o etime= -p "$PID" 2>/dev/null | tr -d ' ')
        echo "  Uptime: ${UPTIME:-unknown}"
    else
        fail "Daemon not running"
    fi

    # Check IPC socket
    SOCKET="/run/user/$(id -u)/styrened/control.sock"
    if [[ -S "$SOCKET" ]]; then
        pass "IPC socket available"
    else
        echo "  IPC socket not found (daemon may need restart)"
    fi
fi

echo ""
echo "--- Network ---"
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[[ -z "$IP" ]] && IP=$(ip -4 addr show 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v 127.0.0.1 | head -1)
echo "  IP: ${IP:-unknown}"
echo "  Hostname: $(hostname)"

# Check TCP server
if command -v ss &>/dev/null && ss -tlnp 2>/dev/null | grep -q ':4242'; then
    pass "TCP server on :4242"
fi

echo ""
echo "--- System ---"
OS=$(grep PRETTY_NAME /etc/os-release 2>/dev/null | cut -d'"' -f2)
echo "  OS: ${OS:-$(uname -s)}"
echo "  Kernel: $(uname -r)"
echo "  Arch: $(uname -m)"

echo ""
echo "=== Result: ${PASS} passed, ${FAIL} failed ==="
[[ $FAIL -eq 0 ]]
REMOTE_SCRIPT

echo ""
echo "Validation complete for ${HOST}"
