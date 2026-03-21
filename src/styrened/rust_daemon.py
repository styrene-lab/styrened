"""Rust daemon launcher — finds and spawns reticulumd binary.

Phase 2 of the Python daemon sunset: `styrened daemon` prefers the Rust
binary when available, falls back to the Python daemon otherwise.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


# Binary names to search for on PATH and in extra search dirs.
# Note: when the Python package also installs a "styrened" script,
# shutil.which("styrened") may find the Python script first. The
# _is_rust_binary() check filters out non-ELF/Mach-O scripts.
BINARY_NAMES = ("styrened", "styrened-rs")

# Additional search paths beyond $PATH.
EXTRA_SEARCH_PATHS = (
    Path.home() / ".cargo" / "bin",
    Path("/usr/local/bin"),
    Path("/opt/styrene/bin"),
)


def _is_compiled_binary(path: str) -> bool:
    """Check if a file is a compiled binary (not a Python/shell script).

    Reads the first 4 bytes to detect ELF (\x7fELF) or Mach-O
    (\xfe\xed\xfa or \xcf\xfa\xed\xfe) magic bytes.
    """
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
        if magic[:4] == b"\x7fELF":
            return True  # ELF (Linux)
        if magic[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                         b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"):
            return True  # Mach-O (macOS)
        return False
    except (OSError, IOError):
        return False


def find_rust_daemon() -> str | None:
    """Locate the Rust daemon binary.

    Search order:
    1. STYRENED_RS_BIN environment variable (explicit override)
    2. $PATH via shutil.which()
    3. ~/.cargo/bin/
    4. /usr/local/bin/, /opt/styrene/bin/

    Returns:
        Absolute path to the binary, or None if not found.
    """
    # Explicit override
    env_bin = os.environ.get("STYRENED_RS_BIN")
    if env_bin:
        p = Path(env_bin)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p.resolve())
        # If explicitly set but not found, don't search further
        print(
            f"[daemon] STYRENED_RS_BIN={env_bin} not found or not executable",
            file=sys.stderr,
        )
        return None

    # Search PATH — but filter out Python scripts (avoid finding ourselves)
    for name in BINARY_NAMES:
        found = shutil.which(name)
        if found and _is_compiled_binary(found):
            return found

    # Search extra paths
    for search_dir in EXTRA_SEARCH_PATHS:
        for name in BINARY_NAMES:
            candidate = search_dir / name
            if candidate.is_file() and os.access(candidate, os.X_OK) and _is_compiled_binary(str(candidate)):
                return str(candidate.resolve())

    return None


def build_rust_daemon_args(
    binary: str,
    *,
    db: str | None = None,
    config: str | None = None,
    transport: str | None = None,
    identity: str | None = None,
    socket: str | None = None,
    announce_interval: int | None = None,
) -> list[str]:
    """Build the command-line arguments for the Rust daemon.

    Maps styrened's configuration to reticulumd CLI flags.
    """
    cmd = [binary]

    if db:
        cmd.extend(["--db", db])
    if config:
        cmd.extend(["--config", config])
    if transport:
        cmd.extend(["--transport", transport])
    if identity:
        cmd.extend(["--identity", identity])
    if socket:
        cmd.extend(["--socket", socket])
    if announce_interval is not None:
        cmd.extend(["--announce-interval", str(announce_interval)])

    return cmd


def exec_rust_daemon(**kwargs) -> int:
    """Find and exec the Rust daemon, replacing this process.

    Returns:
        Exit code (only if exec fails or binary not found).
    """
    binary = find_rust_daemon()
    if not binary:
        return -1  # Signal: not found

    cmd = build_rust_daemon_args(binary, **kwargs)
    print(f"[daemon] starting Rust daemon: {' '.join(cmd)}", file=sys.stderr)

    try:
        # Replace this process with the Rust daemon
        os.execvp(cmd[0], cmd)
    except OSError as e:
        print(f"[daemon] failed to exec {binary}: {e}", file=sys.stderr)
        return 1

    return 0  # unreachable after successful exec


def spawn_rust_daemon(**kwargs) -> subprocess.Popen | None:
    """Spawn the Rust daemon as a subprocess (for managed mode).

    Returns:
        Popen handle, or None if binary not found.
    """
    binary = find_rust_daemon()
    if not binary:
        return None

    cmd = build_rust_daemon_args(binary, **kwargs)
    print(f"[daemon] spawning Rust daemon: {' '.join(cmd)}", file=sys.stderr)

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
