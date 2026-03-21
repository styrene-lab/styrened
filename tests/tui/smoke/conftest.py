"""Conftest for TUI smoke tests against a live Rust daemon.

These tests start the Rust daemon (reticulumd) once per session, wait for
the IPC socket, then run Textual Pilot tests against the real TUI connecting
to the real daemon. No mocks — the full IPC path is exercised.

Requires:
    cargo build -p styrened-rs   (in ~/workspace/styrene-lab/styrene-rs)

Mark: @pytest.mark.tui_smoke
Skip: pytest -m "not tui_smoke"
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ── Daemon binary discovery ──────────────────────────────────────────────────

RUST_REPO = Path(os.environ.get(
    "STYRENE_RS_REPO",
    Path.home() / "workspace" / "styrene-lab" / "styrene-rs",
))
RETICULUMD = RUST_REPO / "target" / "debug" / "styrened"


def _socket_path() -> Path:
    """Canonical socket path — same as Python paths.control_socket()."""
    from styrened.paths import control_socket
    return control_socket()


# ── Session-scoped fixtures ──────────────────────────────────────────────────


@pytest.fixture(scope="session")
def rust_daemon():
    """Start the Rust daemon for the entire test session.

    Yields the socket path. Kills the daemon on teardown.
    """
    if not RETICULUMD.exists():
        pytest.skip(
            f"Rust daemon not built at {RETICULUMD} — "
            f"run: cd {RUST_REPO} && cargo build -p styrened-rs"
        )

    socket = _socket_path()

    # Clean stale socket
    if socket.exists():
        socket.unlink()

    # Ensure parent dir exists
    socket.parent.mkdir(parents=True, exist_ok=True)

    # Start daemon with isolated paths (no RNS transport, temp DB)
    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="styrene-smoke-")
    tmp_db = os.path.join(tmp_dir, "test.db")

    proc = subprocess.Popen(
        [str(RETICULUMD), "--db", tmp_db, "--socket", str(socket)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        # Don't inherit our signal handlers
        preexec_fn=os.setpgrp if sys.platform != "win32" else None,
    )

    # Wait for socket to appear
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not proc.poll() is None:
            stdout = proc.stdout.read().decode() if proc.stdout else ""
            pytest.fail(f"Rust daemon exited early (rc={proc.returncode}):\n{stdout}")
        if socket.exists():
            break
        time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail(f"Rust daemon socket not created after 15s at {socket}")

    yield socket

    # Teardown
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    if socket.exists():
        socket.unlink()


@pytest.fixture
def tui_app(rust_daemon):
    """Create a StyreneApp instance that will connect to the live Rust daemon.

    The app's _check_daemon is NOT mocked — it performs a real IPC PING
    against the Rust daemon to verify connectivity.
    """
    from styrened.tui.app import StyreneApp

    app = StyreneApp()
    # Don't mock _check_daemon — let it do a real PING to the Rust daemon
    return app
