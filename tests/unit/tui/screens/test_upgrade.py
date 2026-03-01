"""Tests for UpgradeScreen."""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from styrened.tui.screens.upgrade import UpgradeScreen, _DAEMON_PKILL_PATTERN, _kill_daemon


class TestBuildUpgradeCmd:
    """Tests for UpgradeScreen._build_upgrade_cmd()."""

    def test_detects_pipx_via_bin_dir_env(self):
        """PIPX_BIN_DIR env var triggers pipx upgrade with eager strategy."""
        with patch.dict(os.environ, {"PIPX_BIN_DIR": "/home/user/.local/bin"}):
            cmd = UpgradeScreen._build_upgrade_cmd()
        assert cmd == ["pipx", "upgrade", "styrene", "--pip-args=--upgrade-strategy=eager"]

    def test_detects_pipx_via_path_heuristic(self):
        """sys.executable under ~/.local/pipx/venvs/ triggers pipx upgrade."""
        fake_exe = os.path.expanduser("~/.local/pipx/venvs/styrene/bin/python")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PIPX_BIN_DIR", None)
            with patch.object(sys, "executable", fake_exe):
                cmd = UpgradeScreen._build_upgrade_cmd()
        assert cmd == ["pipx", "upgrade", "styrene", "--pip-args=--upgrade-strategy=eager"]

    def test_falls_back_to_pip(self):
        """Non-pipx executable uses pip with eager strategy."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PIPX_BIN_DIR", None)
            with patch.object(sys, "executable", "/usr/bin/python3"):
                cmd = UpgradeScreen._build_upgrade_cmd()
        assert cmd == ["/usr/bin/python3", "-m", "pip", "install", "--upgrade", "--upgrade-strategy=eager", "styrene"]

    def test_respects_custom_pipx_home(self):
        """Custom PIPX_HOME is used in path check."""
        custom_home = "/opt/pipx"
        fake_exe = f"{custom_home}/venvs/styrene/bin/python"
        with patch.dict(os.environ, {"PIPX_HOME": custom_home}, clear=False):
            os.environ.pop("PIPX_BIN_DIR", None)
            with patch.object(sys, "executable", fake_exe):
                cmd = UpgradeScreen._build_upgrade_cmd()
        assert cmd == ["pipx", "upgrade", "styrene", "--pip-args=--upgrade-strategy=eager"]


class TestDaemonPkillPattern:
    """Tests for the daemon kill pattern."""

    def test_pattern_is_anchored(self):
        """Pattern must start with ^ to avoid matching substrings in unrelated processes."""
        assert _DAEMON_PKILL_PATTERN.startswith("^")

    def test_kill_daemon_doesnt_raise(self):
        """_kill_daemon() swallows all exceptions."""
        with patch("subprocess.run", side_effect=OSError("not found")):
            # Should not raise
            _kill_daemon()

    def test_kill_daemon_calls_pkill(self):
        """_kill_daemon() calls pkill with the correct pattern."""
        with patch("subprocess.run") as mock_run:
            _kill_daemon()
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert args[0][0] == ["pkill", "-f", _DAEMON_PKILL_PATTERN]


class TestUpgradeScreenInit:
    """Tests for UpgradeScreen initialization."""

    def test_stores_versions(self):
        screen = UpgradeScreen("0.10.37", "0.10.38")
        assert screen._current == "0.10.37"
        assert screen._latest == "0.10.38"
        assert screen._upgrading is False

    def test_cancel_blocked_during_upgrade(self):
        """action_cancel is a no-op when upgrade is in progress."""
        screen = UpgradeScreen("0.10.37", "0.10.38")
        screen._upgrading = True
        # Mock dismiss to verify it's NOT called
        screen.dismiss = MagicMock()
        screen.action_cancel()
        screen.dismiss.assert_not_called()

    def test_cancel_works_when_idle(self):
        """action_cancel dismisses when not upgrading."""
        screen = UpgradeScreen("0.10.37", "0.10.38")
        screen._upgrading = False
        screen.dismiss = MagicMock()
        screen.action_cancel()
        screen.dismiss.assert_called_once_with(False)
