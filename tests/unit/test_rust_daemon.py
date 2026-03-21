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


class TestExecRustDaemon:
    """Tests for exec_rust_daemon()."""

    def test_returns_negative_one_when_not_found(self):
        """No binary → returns -1."""
        from styrened.rust_daemon import exec_rust_daemon

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("styrened.rust_daemon.find_rust_daemon", return_value=None),
        ):
            assert exec_rust_daemon() == -1

    def test_passes_kwargs_to_build_args(self, tmp_path):
        """Keyword args forwarded to build_rust_daemon_args."""
        from styrened.rust_daemon import exec_rust_daemon

        binary = tmp_path / "reticulumd"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)

        captured = {}

        def mock_execvp(cmd, args):
            captured["cmd"] = cmd
            captured["args"] = args
            raise OSError("mock")

        with (
            patch("styrened.rust_daemon.find_rust_daemon", return_value=str(binary)),
            patch("os.execvp", side_effect=mock_execvp),
        ):
            exec_rust_daemon(db="/tmp/test.db", socket="/tmp/test.sock")

        assert "--db" in captured["args"]
        assert "/tmp/test.db" in captured["args"]
        assert "--socket" in captured["args"]
        assert "/tmp/test.sock" in captured["args"]


class TestSpawnRustDaemon:
    """Tests for spawn_rust_daemon()."""

    def test_returns_none_when_not_found(self):
        """No binary → returns None."""
        from styrened.rust_daemon import spawn_rust_daemon

        with patch("styrened.rust_daemon.find_rust_daemon", return_value=None):
            assert spawn_rust_daemon() is None


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
