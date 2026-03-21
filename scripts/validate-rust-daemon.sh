#!/usr/bin/env bash
# validate-rust-daemon.sh — Phase 2 validation harness
#
# Starts the Rust daemon (reticulumd) in standalone mode, waits for the
# IPC socket, runs Python contract tests against it, then optionally
# launches the TUI for manual validation.
#
# Usage:
#   ./scripts/validate-rust-daemon.sh           # Run contract tests only
#   ./scripts/validate-rust-daemon.sh --tui     # Run tests, then launch TUI
#   ./scripts/validate-rust-daemon.sh --tui-only # Skip tests, just launch TUI
#
# Prerequisites:
#   - Rust daemon built: cd ~/workspace/styrene-lab/styrene-rs && cargo build -p styrened-rs
#   - Python venv active: cd ~/workspace/styrene-lab/styrened && source .venv/bin/activate

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
RUST_REPO="${RUST_REPO:-$HOME/workspace/styrene-lab/styrene-rs}"
# Socket path — aligned with Python paths.control_socket() and Rust default_socket_path()
if [ -n "${STYRENED_SOCKET:-}" ]; then
    SOCKET_PATH="$STYRENED_SOCKET"
elif [ -n "${XDG_RUNTIME_DIR:-}" ]; then
    SOCKET_PATH="${XDG_RUNTIME_DIR}/styrened/control.sock"
else
    SOCKET_PATH="${HOME}/.local/run/styrened/control.sock"
fi
RETICULUMD="${RUST_REPO}/target/debug/styrened-rs"
DAEMON_PID=""
LAUNCH_TUI=false
SKIP_TESTS=false

# Parse args
for arg in "$@"; do
    case "$arg" in
        --tui) LAUNCH_TUI=true ;;
        --tui-only) LAUNCH_TUI=true; SKIP_TESTS=true ;;
        --help|-h)
            echo "Usage: $0 [--tui] [--tui-only]"
            echo "  --tui       Run contract tests, then launch TUI"
            echo "  --tui-only  Skip tests, just launch TUI against Rust daemon"
            exit 0
            ;;
    esac
done

cleanup() {
    if [ -n "$DAEMON_PID" ] && kill -0 "$DAEMON_PID" 2>/dev/null; then
        echo "[harness] Stopping Rust daemon (PID $DAEMON_PID)..."
        kill "$DAEMON_PID" 2>/dev/null || true
        wait "$DAEMON_PID" 2>/dev/null || true
    fi
    # Socket cleanup handled by daemon, but be safe
    rm -f "$SOCKET_PATH"
}
trap cleanup EXIT

# ── Step 1: Check prerequisites ──────────────────────────────────────────────

echo "[harness] Checking prerequisites..."

if [ ! -f "$RETICULUMD" ]; then
    echo "[harness] Rust daemon not found at $RETICULUMD"
    echo "[harness] Build with: cd $RUST_REPO && cargo build -p styrened-rs"
    exit 1
fi

if [ ! -f "$REPO_DIR/.venv/bin/python" ]; then
    echo "[harness] Python venv not found at $REPO_DIR/.venv/"
    echo "[harness] Set up with: cd $REPO_DIR && make install"
    exit 1
fi

PYTHON="$REPO_DIR/.venv/bin/python"

# ── Step 2: Clean up any existing socket/daemon ──────────────────────────────

if [ -S "$SOCKET_PATH" ]; then
    echo "[harness] Removing stale socket at $SOCKET_PATH"
    rm -f "$SOCKET_PATH"
fi

# ── Step 3: Start Rust daemon ────────────────────────────────────────────────

echo "[harness] Starting Rust daemon (standalone mode)..."
mkdir -p "$(dirname "$SOCKET_PATH")"

"$RETICULUMD" --socket "$SOCKET_PATH" 2>&1 | sed 's/^/[styrened-rs] /' &
DAEMON_PID=$!
echo "[harness] Daemon PID: $DAEMON_PID"

# Wait for socket
echo -n "[harness] Waiting for IPC socket"
WAITED=0
while [ ! -S "$SOCKET_PATH" ] && [ $WAITED -lt 15 ]; do
    echo -n "."
    sleep 1
    WAITED=$((WAITED + 1))
    # Check daemon is still running
    if ! kill -0 "$DAEMON_PID" 2>/dev/null; then
        echo ""
        echo "[harness] ERROR: Daemon exited before socket appeared"
        echo "[harness] Check output above for errors"
        exit 1
    fi
done
echo ""

if [ ! -S "$SOCKET_PATH" ]; then
    echo "[harness] ERROR: Socket not created after 15s"
    exit 1
fi
echo "[harness] Socket ready at $SOCKET_PATH"

# ── Step 4: Run contract tests ───────────────────────────────────────────────

if [ "$SKIP_TESTS" = false ]; then
    echo ""
    echo "[harness] ═══════════════════════════════════════════════════════"
    echo "[harness] Running IPC contract tests against Rust daemon..."
    echo "[harness] ═══════════════════════════════════════════════════════"
    echo ""

    # Run the contract tests (not skipped — socket exists)
    "$PYTHON" -m pytest \
        tests/unit/test_ipc_contract_rust_daemon.py \
        -v --tb=short \
        -x \
        2>&1 | sed 's/^/[pytest] /'

    TEST_EXIT=$?

    echo ""
    if [ $TEST_EXIT -eq 0 ]; then
        echo "[harness] ✅ All contract tests passed"
    else
        echo "[harness] ❌ Contract tests failed (exit code $TEST_EXIT)"
        echo "[harness] Review failures above — these indicate IPC incompatibilities"
    fi

    # Also run wire compat tests (should already pass, but confirm)
    echo ""
    echo "[harness] Running wire compatibility tests..."
    "$PYTHON" -m pytest \
        tests/unit/test_ipc_wire_compat.py \
        -q \
        2>&1 | sed 's/^/[pytest] /'
fi

# ── Step 5: Optional TUI launch ─────────────────────────────────────────────

if [ "$LAUNCH_TUI" = true ]; then
    echo ""
    echo "[harness] ═══════════════════════════════════════════════════════"
    echo "[harness] Launching TUI against Rust daemon..."
    echo "[harness] The TUI will connect to the Rust IPC socket."
    echo "[harness] Walk through each screen to validate:"
    echo "[harness]   1. Dashboard (Home) — status, node summary"
    echo "[harness]   2. Exploration — device list, sorting"
    echo "[harness]   3. Chat — conversations, send message"
    echo "[harness]   4. Inbox — message list"
    echo "[harness]   5. Contacts — contact list, add/remove"
    echo "[harness]   6. Settings — config display"
    echo "[harness]   7. Node detail — device status query"
    echo "[harness] Press Ctrl+C to exit TUI, daemon stays running."
    echo "[harness] ═══════════════════════════════════════════════════════"
    echo ""

    # Launch TUI (it will auto-connect to the socket)
    "$PYTHON" -m styrened || true
fi

echo "[harness] Done."
