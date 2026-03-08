"""Unit tests for 'styrened setup' CLI subcommand.

Tests cover:
- provision() is called for the selected adapter
- config is written with mode=MANAGED when binary found
- appropriate messages are printed
- non-zero exit when binary is missing
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from styrened.models.daemon_mode import DaemonMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(enable: str, config: str | None = None) -> argparse.Namespace:
    ns = argparse.Namespace()
    ns.enable = enable
    ns.config = config
    return ns


# ---------------------------------------------------------------------------
# Yggdrasil
# ---------------------------------------------------------------------------


class TestSetupYggdrasil:
    """Tests for 'styrened setup --enable yggdrasil'."""

    def _run(self, binary_found: bool, capsys: Any, tmp_path: Path) -> int:
        from styrened.cli import cmd_setup
        from styrened.models.config import CoreConfig

        cfg = CoreConfig()
        assert cfg.yggdrasil.mode == DaemonMode.DISABLED

        config_file = tmp_path / "config.yaml"

        with (
            patch("styrened.services.config.load_core_config", return_value=cfg) as mock_load,
            patch("styrened.services.config.save_core_config") as mock_save,
            patch("shutil.which", return_value="/usr/bin/yggdrasil" if binary_found else None),
            patch("styrened.services.yggdrasil.YggdrasilAdapter") as MockAdapter,
        ):
            mock_adapter = MagicMock()
            mock_adapter.provision = AsyncMock()
            MockAdapter.return_value = mock_adapter

            args = _make_args("yggdrasil", config=str(config_file))
            rc = cmd_setup(args)

        return rc, cfg, mock_save, mock_adapter, mock_load

    def test_provision_called(self, capsys: Any, tmp_path: Path) -> None:
        rc, cfg, mock_save, mock_adapter, _ = self._run(True, capsys, tmp_path)
        mock_adapter.provision.assert_called_once()

    def test_config_saved_when_binary_found(self, capsys: Any, tmp_path: Path) -> None:
        rc, cfg, mock_save, _, _ = self._run(True, capsys, tmp_path)
        assert rc == 0
        assert cfg.yggdrasil.mode == DaemonMode.MANAGED
        mock_save.assert_called_once()

    def test_managed_mode_set_in_config(self, capsys: Any, tmp_path: Path) -> None:
        rc, cfg, _, _, _ = self._run(True, capsys, tmp_path)
        assert cfg.yggdrasil.mode == DaemonMode.MANAGED

    def test_success_message_printed(self, capsys: Any, tmp_path: Path) -> None:
        self._run(True, capsys, tmp_path)
        captured = capsys.readouterr()
        assert "MANAGED" in captured.out

    def test_nonzero_exit_when_binary_missing(self, capsys: Any, tmp_path: Path) -> None:
        rc, cfg, mock_save, _, _ = self._run(False, capsys, tmp_path)
        assert rc == 1

    def test_config_not_saved_when_binary_missing(self, capsys: Any, tmp_path: Path) -> None:
        _, _, mock_save, _, _ = self._run(False, capsys, tmp_path)
        mock_save.assert_not_called()

    def test_config_mode_unchanged_when_binary_missing(self, capsys: Any, tmp_path: Path) -> None:
        _, cfg, _, _, _ = self._run(False, capsys, tmp_path)
        assert cfg.yggdrasil.mode == DaemonMode.DISABLED

    def test_config_path_passed_to_load(self, capsys: Any, tmp_path: Path) -> None:
        from styrened.cli import cmd_setup
        from styrened.models.config import CoreConfig

        cfg = CoreConfig()
        config_file = tmp_path / "config.yaml"

        with (
            patch("styrened.services.config.load_core_config", return_value=cfg) as mock_load,
            patch("styrened.services.config.save_core_config"),
            patch("shutil.which", return_value="/usr/bin/yggdrasil"),
            patch("styrened.services.yggdrasil.YggdrasilAdapter") as MockAdapter,
        ):
            mock_adapter = MagicMock()
            mock_adapter.provision = AsyncMock()
            MockAdapter.return_value = mock_adapter

            args = _make_args("yggdrasil", config=str(config_file))
            cmd_setup(args)

        called_path = mock_load.call_args[0][0]
        assert called_path == config_file


# ---------------------------------------------------------------------------
# I2P
# ---------------------------------------------------------------------------


class TestSetupI2P:
    """Tests for 'styrened setup --enable i2p'."""

    def _run(self, binary_found: bool, capsys: Any, tmp_path: Path):
        from styrened.cli import cmd_setup
        from styrened.models.config import CoreConfig

        cfg = CoreConfig()
        assert cfg.i2p.mode == DaemonMode.DISABLED

        config_file = tmp_path / "config.yaml"

        with (
            patch("styrened.services.config.load_core_config", return_value=cfg),
            patch("styrened.services.config.save_core_config") as mock_save,
            patch("shutil.which", return_value="/usr/bin/i2pd" if binary_found else None),
            patch("styrened.services.i2p.I2PAdapter") as MockAdapter,
        ):
            mock_adapter = MagicMock()
            mock_adapter.provision = AsyncMock()
            MockAdapter.return_value = mock_adapter

            args = _make_args("i2p", config=str(config_file))
            rc = cmd_setup(args)

        return rc, cfg, mock_save, mock_adapter

    def test_provision_called(self, capsys: Any, tmp_path: Path) -> None:
        _, _, _, mock_adapter = self._run(True, capsys, tmp_path)
        mock_adapter.provision.assert_called_once()

    def test_config_saved_when_binary_found(self, capsys: Any, tmp_path: Path) -> None:
        rc, cfg, mock_save, _ = self._run(True, capsys, tmp_path)
        assert rc == 0
        mock_save.assert_called_once()

    def test_managed_mode_set_in_config(self, capsys: Any, tmp_path: Path) -> None:
        _, cfg, _, _ = self._run(True, capsys, tmp_path)
        assert cfg.i2p.mode == DaemonMode.MANAGED

    def test_cold_start_warning_always_printed(self, capsys: Any, tmp_path: Path) -> None:
        """Cold-start warning must appear regardless of whether binary is found."""
        # binary found
        self._run(True, capsys, tmp_path)
        out_found = capsys.readouterr().out
        assert "5-10 minutes" in out_found

        # binary missing
        self._run(False, capsys, tmp_path)
        out_missing = capsys.readouterr().out
        assert "5-10 minutes" in out_missing

    def test_nonzero_exit_when_binary_missing(self, capsys: Any, tmp_path: Path) -> None:
        rc, _, _, _ = self._run(False, capsys, tmp_path)
        assert rc == 1

    def test_config_not_saved_when_binary_missing(self, capsys: Any, tmp_path: Path) -> None:
        _, _, mock_save, _ = self._run(False, capsys, tmp_path)
        mock_save.assert_not_called()

    def test_config_mode_unchanged_when_binary_missing(self, capsys: Any, tmp_path: Path) -> None:
        _, cfg, _, _ = self._run(False, capsys, tmp_path)
        assert cfg.i2p.mode == DaemonMode.DISABLED

    def test_success_message_printed(self, capsys: Any, tmp_path: Path) -> None:
        self._run(True, capsys, tmp_path)
        out = capsys.readouterr().out
        assert "MANAGED" in out


# ---------------------------------------------------------------------------
# Parser integration
# ---------------------------------------------------------------------------


class TestSetupParser:
    """Tests verifying the setup subcommand is wired into the CLI parser."""

    def test_setup_subcommand_registered(self) -> None:
        from styrened.cli import create_parser

        parser = create_parser()
        # Verify 'setup' is a recognised subcommand by parsing it
        args = parser.parse_args(["setup", "--enable", "yggdrasil"])
        assert args.command == "setup"
        assert args.enable == "yggdrasil"
        assert args.func.__name__ == "cmd_setup"

    def test_setup_enables_i2p(self) -> None:
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["setup", "--enable", "i2p"])
        assert args.enable == "i2p"

    def test_setup_requires_enable(self) -> None:
        from styrened.cli import create_parser

        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["setup"])

    def test_setup_rejects_unknown_daemon(self) -> None:
        from styrened.cli import create_parser

        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["setup", "--enable", "tor"])
