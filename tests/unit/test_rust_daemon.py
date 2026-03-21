"""Tests for the Rust daemon launcher."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from styrened.rust_daemon import (
    BINARY_NAMES,
    build_rust_daemon_args,
    find_rust_daemon,
)


class TestFindRustDaemon:
    """Tests for find_rust_daemon()."""

    def test_returns_none_when_not_found(self):
        """No binary anywhere → None."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("shutil.which", return_value=None),
        ):
            # Also ensure extra paths don't exist
            with patch("styrened.rust_daemon.EXTRA_SEARCH_PATHS", ()):
                assert find_rust_daemon() is None

    def test_env_override_found(self, tmp_path):
        """STYRENED_RS_BIN points to existing executable."""
        binary = tmp_path / "reticulumd"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)

        with patch.dict(os.environ, {"STYRENED_RS_BIN": str(binary)}):
            result = find_rust_daemon()
            assert result is not None
            assert Path(result).name == "reticulumd"

    def test_env_override_not_found(self, tmp_path):
        """STYRENED_RS_BIN set but file doesn't exist → None."""
        with patch.dict(
            os.environ, {"STYRENED_RS_BIN": str(tmp_path / "nonexistent")}
        ):
            assert find_rust_daemon() is None

    def test_found_via_which(self):
        """Binary found on PATH via shutil.which."""
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("shutil.which", side_effect=lambda name: f"/usr/bin/{name}" if name == "reticulumd" else None),
        ):
            result = find_rust_daemon()
            assert result == "/usr/bin/reticulumd"

    def test_found_in_cargo_bin(self, tmp_path):
        """Binary found in ~/.cargo/bin/ fallback."""
        cargo_bin = tmp_path / ".cargo" / "bin"
        cargo_bin.mkdir(parents=True)
        binary = cargo_bin / "reticulumd"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("shutil.which", return_value=None),
            patch("styrened.rust_daemon.EXTRA_SEARCH_PATHS", (cargo_bin,)),
        ):
            result = find_rust_daemon()
            assert result is not None
            assert "reticulumd" in result


class TestBuildRustDaemonArgs:
    """Tests for build_rust_daemon_args()."""

    def test_minimal(self):
        """No options → just binary name."""
        assert build_rust_daemon_args("/usr/bin/reticulumd") == ["/usr/bin/reticulumd"]

    def test_all_options(self):
        """All options present."""
        cmd = build_rust_daemon_args(
            "/usr/bin/reticulumd",
            db="/var/lib/styrene/store.db",
            config="/etc/styrene/config.toml",
            transport="0.0.0.0:4242",
            identity="/etc/styrene/identity",
            socket="/run/styrene/daemon.sock",
            announce_interval=300,
        )
        assert cmd == [
            "/usr/bin/reticulumd",
            "--db", "/var/lib/styrene/store.db",
            "--config", "/etc/styrene/config.toml",
            "--transport", "0.0.0.0:4242",
            "--identity", "/etc/styrene/identity",
            "--socket", "/run/styrene/daemon.sock",
            "--announce-interval", "300",
        ]

    def test_partial_options(self):
        """Only some options."""
        cmd = build_rust_daemon_args("/bin/reticulumd", db="/tmp/test.db")
        assert cmd == ["/bin/reticulumd", "--db", "/tmp/test.db"]
