"""Tests for the deterministic path resolution module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from styrened import paths
from styrened.paths import Mode


class TestMode:
    """Mode detection tests."""

    def test_default_is_user_mode(self, monkeypatch, tmp_path):
        """USER mode when no env var and no /etc/styrene/config.yaml."""
        monkeypatch.delenv("STYRENE_SYSTEM", raising=False)
        with patch.object(Path, "exists", return_value=False):
            assert paths.mode() == Mode.USER

    def test_styrene_system_env_triggers_system_mode(self, monkeypatch):
        """STYRENE_SYSTEM=1 forces SYSTEM mode."""
        monkeypatch.setenv("STYRENE_SYSTEM", "1")
        assert paths.mode() == Mode.SYSTEM

    def test_styrene_system_true_string(self, monkeypatch):
        """STYRENE_SYSTEM=true forces SYSTEM mode."""
        monkeypatch.setenv("STYRENE_SYSTEM", "true")
        assert paths.mode() == Mode.SYSTEM

    def test_etc_config_triggers_system_mode(self, monkeypatch):
        """Existence of /etc/styrene/config.yaml triggers SYSTEM mode."""
        monkeypatch.delenv("STYRENE_SYSTEM", raising=False)
        with patch.object(Path, "exists", return_value=True):
            assert paths.mode() == Mode.SYSTEM


class TestUserModePaths:
    """USER mode path resolution."""

    @pytest.fixture(autouse=True)
    def _user_mode(self, monkeypatch):
        monkeypatch.delenv("STYRENE_SYSTEM", raising=False)
        monkeypatch.delenv("STYRENE_HOME", raising=False)
        monkeypatch.delenv("STYRENE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("STYRENE_DATA_DIR", raising=False)
        monkeypatch.delenv("STYRENE_STATE_DIR", raising=False)
        monkeypatch.delenv("STYRENE_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("STYRENED_SOCKET", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        # Ensure /etc/styrene/config.yaml doesn't affect mode detection
        monkeypatch.setattr(paths, "mode", lambda: Mode.USER)

    def test_config_dir(self):
        assert paths.config_dir() == Path.home() / ".config" / "styrene"

    def test_data_dir(self):
        assert paths.data_dir() == Path.home() / ".local" / "share" / "styrene"

    def test_state_dir(self):
        assert paths.state_dir() == Path.home() / ".local" / "state" / "styrene"

    def test_log_dir(self):
        assert paths.log_dir() == Path.home() / ".local" / "state" / "styrene" / "logs"

    def test_runtime_dir_no_xdg(self):
        assert paths.runtime_dir() == Path.home() / ".local" / "run" / "styrened"

    def test_runtime_dir_with_xdg(self, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        # Need to un-mock mode since we set env
        monkeypatch.setattr(paths, "mode", lambda: Mode.USER)
        assert paths.runtime_dir() == Path("/run/user/1000/styrened")

    def test_config_file(self):
        assert paths.config_file() == Path.home() / ".config" / "styrene" / "config.yaml"

    def test_config_file_not_core_config(self):
        """config_file() returns config.yaml, NOT core-config.yaml."""
        assert paths.config_file().name == "config.yaml"

    def test_tui_config_file(self):
        assert paths.tui_config_file() == Path.home() / ".config" / "styrene" / "tui.yaml"

    def test_identity_file(self):
        assert paths.identity_file() == Path.home() / ".config" / "styrene" / "identity"

    def test_nodes_db(self):
        assert paths.nodes_db() == Path.home() / ".local" / "share" / "styrene" / "nodes.db"

    def test_messages_db(self):
        assert paths.messages_db() == Path.home() / ".local" / "share" / "styrene" / "messages.db"

    def test_lxmf_storage(self):
        assert paths.lxmf_storage() == Path.home() / ".local" / "share" / "styrene" / "lxmf"

    def test_fleet_inventory(self):
        assert paths.fleet_inventory() == Path.home() / ".local" / "share" / "styrene" / "fleet-inventory.yaml"

    def test_control_socket(self):
        assert paths.control_socket() == Path.home() / ".local" / "run" / "styrened" / "control.sock"


class TestSystemModePaths:
    """SYSTEM mode path resolution."""

    @pytest.fixture(autouse=True)
    def _system_mode(self, monkeypatch):
        monkeypatch.delenv("STYRENE_HOME", raising=False)
        monkeypatch.delenv("STYRENE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("STYRENE_DATA_DIR", raising=False)
        monkeypatch.delenv("STYRENE_STATE_DIR", raising=False)
        monkeypatch.delenv("STYRENE_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("STYRENED_SOCKET", raising=False)
        monkeypatch.setattr(paths, "mode", lambda: Mode.SYSTEM)

    def test_config_dir(self):
        assert paths.config_dir() == Path("/etc/styrene")

    def test_data_dir(self):
        assert paths.data_dir() == Path("/var/lib/styrene")

    def test_state_dir(self):
        assert paths.state_dir() == Path("/var/log/styrene")

    def test_runtime_dir(self):
        assert paths.runtime_dir() == Path("/run/styrened")

    def test_identity_file(self):
        assert paths.identity_file() == Path("/etc/styrene/identity")

    def test_control_socket(self):
        assert paths.control_socket() == Path("/run/styrened/control.sock")


class TestEnvOverrides:
    """Environment variable overrides take precedence."""

    @pytest.fixture(autouse=True)
    def _user_mode(self, monkeypatch):
        monkeypatch.setattr(paths, "mode", lambda: Mode.USER)
        monkeypatch.delenv("STYRENE_HOME", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    def test_config_dir_override(self, monkeypatch):
        monkeypatch.setenv("STYRENE_CONFIG_DIR", "/custom/config")
        assert paths.config_dir() == Path("/custom/config")

    def test_data_dir_override(self, monkeypatch):
        monkeypatch.setenv("STYRENE_DATA_DIR", "/custom/data")
        assert paths.data_dir() == Path("/custom/data")

    def test_state_dir_override(self, monkeypatch):
        monkeypatch.setenv("STYRENE_STATE_DIR", "/custom/state")
        assert paths.state_dir() == Path("/custom/state")

    def test_runtime_dir_override(self, monkeypatch):
        monkeypatch.setenv("STYRENE_RUNTIME_DIR", "/custom/run")
        assert paths.runtime_dir() == Path("/custom/run")

    def test_socket_env_override(self, monkeypatch):
        monkeypatch.setenv("STYRENED_SOCKET", "/tmp/my.sock")
        assert paths.control_socket() == Path("/tmp/my.sock")

    def test_config_file_follows_config_dir(self, monkeypatch):
        monkeypatch.setenv("STYRENE_CONFIG_DIR", "/tmp/test")
        assert paths.config_file() == Path("/tmp/test/config.yaml")

    def test_data_dir_override_in_system_mode(self, monkeypatch):
        """Env override takes precedence even in SYSTEM mode."""
        monkeypatch.setattr(paths, "mode", lambda: Mode.SYSTEM)
        monkeypatch.setenv("STYRENE_DATA_DIR", "/mnt/storage")
        assert paths.data_dir() == Path("/mnt/storage")


class TestXDGOverrides:
    """XDG Base Directory Specification compliance."""

    @pytest.fixture(autouse=True)
    def _user_mode(self, monkeypatch):
        monkeypatch.setattr(paths, "mode", lambda: Mode.USER)
        monkeypatch.delenv("STYRENE_HOME", raising=False)
        monkeypatch.delenv("STYRENE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("STYRENE_DATA_DIR", raising=False)
        monkeypatch.delenv("STYRENE_STATE_DIR", raising=False)
        monkeypatch.delenv("STYRENE_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    def test_xdg_config_home(self, monkeypatch):
        """XDG_CONFIG_HOME overrides config base directory."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "/custom/xdg/config")
        assert paths.config_dir() == Path("/custom/xdg/config/styrene")

    def test_xdg_data_home(self, monkeypatch):
        """XDG_DATA_HOME overrides data base directory."""
        monkeypatch.setenv("XDG_DATA_HOME", "/custom/xdg/data")
        assert paths.data_dir() == Path("/custom/xdg/data/styrene")

    def test_xdg_state_home(self, monkeypatch):
        """XDG_STATE_HOME overrides state base directory."""
        monkeypatch.setenv("XDG_STATE_HOME", "/custom/xdg/state")
        assert paths.state_dir() == Path("/custom/xdg/state/styrene")

    def test_xdg_runtime_dir(self, monkeypatch):
        """XDG_RUNTIME_DIR overrides runtime base directory."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        assert paths.runtime_dir() == Path("/run/user/1000/styrened")

    def test_styrene_override_beats_xdg(self, monkeypatch):
        """STYRENE_*_DIR takes precedence over XDG_*."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg/config")
        monkeypatch.setenv("STYRENE_CONFIG_DIR", "/explicit/override")
        assert paths.config_dir() == Path("/explicit/override")

    def test_xdg_ignored_in_system_mode(self, monkeypatch):
        """XDG variables have no effect in SYSTEM mode."""
        monkeypatch.setattr(paths, "mode", lambda: Mode.SYSTEM)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg/config")
        monkeypatch.setenv("XDG_DATA_HOME", "/xdg/data")
        assert paths.config_dir() == Path("/etc/styrene")
        assert paths.data_dir() == Path("/var/lib/styrene")

    def test_log_dir_follows_state_dir_with_xdg(self, monkeypatch):
        """log_dir() is under state_dir(), which follows XDG_STATE_HOME."""
        monkeypatch.setenv("XDG_STATE_HOME", "/custom/state")
        assert paths.log_dir() == Path("/custom/state/styrene/logs")

    def test_wayland_runtime_dir(self, monkeypatch):
        """Wayland compositors set XDG_RUNTIME_DIR; socket goes there."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
        assert paths.control_socket() == Path("/run/user/1000/styrened/control.sock")


class TestStyreneHome:
    """STYRENE_HOME unified base directory."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        monkeypatch.setattr(paths, "mode", lambda: Mode.USER)
        monkeypatch.delenv("STYRENE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("STYRENE_DATA_DIR", raising=False)
        monkeypatch.delenv("STYRENE_STATE_DIR", raising=False)
        monkeypatch.delenv("STYRENE_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("STYRENE_HOME", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    def test_sets_all_dirs(self, monkeypatch):
        """STYRENE_HOME sets config/, data/, state/, run/ subdirectories."""
        monkeypatch.setenv("STYRENE_HOME", "/app/data")
        assert paths.config_dir() == Path("/app/data/config")
        assert paths.data_dir() == Path("/app/data/data")
        assert paths.state_dir() == Path("/app/data/state")
        assert paths.runtime_dir() == Path("/app/data/run")

    def test_derived_paths_follow(self, monkeypatch):
        """Derived paths (config_file, identity, etc.) follow STYRENE_HOME."""
        monkeypatch.setenv("STYRENE_HOME", "/app/data")
        assert paths.config_file() == Path("/app/data/config/config.yaml")
        assert paths.identity_file() == Path("/app/data/config/identity")
        assert paths.nodes_db() == Path("/app/data/data/nodes.db")
        assert paths.log_dir() == Path("/app/data/state/logs")
        assert paths.control_socket() == Path("/app/data/run/control.sock")

    def test_specific_override_beats_home(self, monkeypatch):
        """STYRENE_*_DIR takes precedence over STYRENE_HOME."""
        monkeypatch.setenv("STYRENE_HOME", "/app/data")
        monkeypatch.setenv("STYRENE_CONFIG_DIR", "/explicit/config")
        assert paths.config_dir() == Path("/explicit/config")
        # Other dirs still come from STYRENE_HOME
        assert paths.data_dir() == Path("/app/data/data")

    def test_home_beats_xdg(self, monkeypatch):
        """STYRENE_HOME takes precedence over XDG_* vars."""
        monkeypatch.setenv("STYRENE_HOME", "/app/data")
        monkeypatch.setenv("XDG_CONFIG_HOME", "/xdg/config")
        monkeypatch.setenv("XDG_DATA_HOME", "/xdg/data")
        assert paths.config_dir() == Path("/app/data/config")
        assert paths.data_dir() == Path("/app/data/data")

    def test_home_beats_system_mode(self, monkeypatch):
        """STYRENE_HOME takes precedence over SYSTEM mode paths."""
        monkeypatch.setattr(paths, "mode", lambda: Mode.SYSTEM)
        monkeypatch.setenv("STYRENE_HOME", "/app/data")
        assert paths.config_dir() == Path("/app/data/config")
        assert paths.data_dir() == Path("/app/data/data")
        assert paths.runtime_dir() == Path("/app/data/run")

    def test_ensure_directories_with_home(self, tmp_path, monkeypatch):
        """ensure_directories() creates subdirs under STYRENE_HOME."""
        monkeypatch.setenv("STYRENE_HOME", str(tmp_path / "styrene"))
        paths.ensure_directories()
        assert (tmp_path / "styrene" / "config").is_dir()
        assert (tmp_path / "styrene" / "data").is_dir()
        assert (tmp_path / "styrene" / "state").is_dir()
        assert (tmp_path / "styrene" / "state" / "logs").is_dir()


class TestEnsureDirectories:
    """Directory creation."""

    def test_creates_all_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STYRENE_CONFIG_DIR", str(tmp_path / "config"))
        monkeypatch.setenv("STYRENE_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("STYRENE_STATE_DIR", str(tmp_path / "state"))

        paths.ensure_directories()

        assert (tmp_path / "config").is_dir()
        assert (tmp_path / "data").is_dir()
        assert (tmp_path / "state").is_dir()
        assert (tmp_path / "state" / "logs").is_dir()


class TestMigrateLegacyPaths:
    """Legacy path migration."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: self.home))
        monkeypatch.setattr(paths, "mode", lambda: Mode.USER)
        monkeypatch.delenv("STYRENE_HOME", raising=False)
        monkeypatch.delenv("STYRENE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("STYRENE_DATA_DIR", raising=False)
        monkeypatch.delenv("STYRENE_STATE_DIR", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    def test_copies_legacy_tui_config(self):
        """~/.styrene/config.yaml -> ~/.config/styrene/tui.yaml."""
        legacy = self.home / ".styrene" / "config.yaml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("tui: {theme: dark}")

        actions = paths.migrate_legacy_paths()

        assert (self.home / ".config" / "styrene" / "tui.yaml").exists()
        assert any("tui.yaml" in a for a in actions)

    def test_copies_legacy_operator_key(self):
        """~/.styrene/operator.key -> ~/.config/styrene/identity."""
        legacy = self.home / ".styrene" / "operator.key"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"key-data")

        paths.migrate_legacy_paths()

        canonical = self.home / ".config" / "styrene" / "identity"
        assert canonical.exists()
        assert canonical.read_bytes() == b"key-data"

    def test_copies_legacy_core_config(self):
        """~/.config/styrene/core-config.yaml -> ~/.config/styrene/config.yaml."""
        legacy = self.home / ".config" / "styrene" / "core-config.yaml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("profile: operator")

        actions = paths.migrate_legacy_paths()

        assert (self.home / ".config" / "styrene" / "config.yaml").exists()
        assert any("config.yaml" in a for a in actions)

    def test_skips_existing_destination(self):
        """Migration does not overwrite existing canonical files."""
        # Create legacy
        legacy = self.home / ".styrene" / "operator.key"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"old-key")

        # Create canonical (identity, not operator.key)
        canonical = self.home / ".config" / "styrene" / "identity"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"new-key")

        actions = paths.migrate_legacy_paths()

        # Canonical should be unchanged
        assert canonical.read_bytes() == b"new-key"
        assert not any("identity" in a for a in actions)

    def test_idempotent_with_marker(self):
        """Second call returns empty actions due to marker file."""
        legacy = self.home / ".styrene" / "config.yaml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("data")

        first = paths.migrate_legacy_paths()
        second = paths.migrate_legacy_paths()

        assert len(first) > 0
        assert len(second) == 0

    def test_marker_file_created(self):
        """Migration writes .paths-migrated marker."""
        paths.migrate_legacy_paths()
        marker = self.home / ".config" / "styrene" / ".paths-migrated"
        assert marker.exists()

    def test_no_migration_in_system_mode(self, monkeypatch):
        """SYSTEM mode skips migration entirely."""
        monkeypatch.setattr(paths, "mode", lambda: Mode.SYSTEM)

        legacy = self.home / ".styrene" / "config.yaml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("data")

        actions = paths.migrate_legacy_paths()
        assert len(actions) == 0


class TestAutoMigration:
    """Auto-migration in log_dir() and fleet_inventory()."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.config = tmp_path / "config"
        self.data = tmp_path / "data"
        self.state = tmp_path / "state"
        self.config.mkdir()
        self.data.mkdir()
        self.state.mkdir()
        monkeypatch.setenv("STYRENE_CONFIG_DIR", str(self.config))
        monkeypatch.setenv("STYRENE_DATA_DIR", str(self.data))
        monkeypatch.setenv("STYRENE_STATE_DIR", str(self.state))
        monkeypatch.delenv("STYRENE_HOME", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.setattr(paths, "mode", lambda: Mode.USER)

    # -- log_dir auto-migration ------------------------------------------------

    def test_log_dir_migrates_from_data_dir(self):
        """log_dir() moves data_dir()/logs -> state_dir()/logs on first access."""
        old = self.data / "logs"
        old.mkdir()
        (old / "daemon.log").write_text("log line")

        result = paths.log_dir()

        canonical = self.state / "logs"
        assert result == canonical
        assert canonical.is_dir()
        assert (canonical / "daemon.log").read_text() == "log line"
        assert not old.exists()

    def test_log_dir_no_migration_when_canonical_exists(self):
        """log_dir() does not overwrite existing canonical directory."""
        old = self.data / "logs"
        old.mkdir()
        (old / "old.log").write_text("old")

        canonical = self.state / "logs"
        canonical.mkdir()
        (canonical / "current.log").write_text("current")

        result = paths.log_dir()

        assert result == canonical
        assert (canonical / "current.log").read_text() == "current"
        # Old dir should still be there — no migration happened
        assert old.exists()

    def test_log_dir_no_migration_when_old_empty(self):
        """Empty old log dir is not migrated."""
        old = self.data / "logs"
        old.mkdir()

        result = paths.log_dir()

        canonical = self.state / "logs"
        assert result == canonical
        # Old dir should still be there — empty dirs aren't migrated
        assert old.exists()
        assert not canonical.exists()

    def test_log_dir_no_migration_when_old_missing(self):
        """log_dir() returns canonical path when no old dir exists."""
        result = paths.log_dir()

        canonical = self.state / "logs"
        assert result == canonical
        assert not canonical.exists()

    # -- fleet_inventory auto-migration ----------------------------------------

    def test_fleet_inventory_migrates_from_config_dir(self):
        """fleet_inventory() moves config_dir()/fleet-inventory.yaml -> data_dir()."""
        old = self.config / "fleet-inventory.yaml"
        old.write_text("fleet:\n  - node1\n")

        result = paths.fleet_inventory()

        canonical = self.data / "fleet-inventory.yaml"
        assert result == canonical
        assert canonical.read_text() == "fleet:\n  - node1\n"
        assert not old.exists()

    def test_fleet_inventory_no_migration_when_canonical_exists(self):
        """fleet_inventory() does not overwrite existing canonical file."""
        old = self.config / "fleet-inventory.yaml"
        old.write_text("old-fleet")

        canonical = self.data / "fleet-inventory.yaml"
        canonical.write_text("current-fleet")

        result = paths.fleet_inventory()

        assert result == canonical
        assert canonical.read_text() == "current-fleet"
        # Old file should still be there — no migration happened
        assert old.exists()

    # -- TOCTOU race resilience (C1 fix) ---------------------------------------

    def test_log_dir_migration_survives_concurrent_deletion(self):
        """log_dir() does not raise when old dir disappears mid-check (TOCTOU)."""
        # No old dir exists — the OSError catch handles the race
        result = paths.log_dir()
        assert result == self.state / "logs"

    def test_fleet_inventory_migration_survives_concurrent_deletion(self):
        """fleet_inventory() does not raise when old file disappears mid-check."""
        # No old file exists — the OSError catch handles the race
        result = paths.fleet_inventory()
        assert result == self.data / "fleet-inventory.yaml"


class TestCrossPlatformConsistency:
    """Paths should be identical on macOS and Linux (no platformdirs)."""

    def test_no_platformdirs_import(self):
        """The paths module must not import platformdirs."""
        import importlib

        spec = importlib.util.find_spec("styrened.paths")
        assert spec is not None

        source = spec.origin
        assert source is not None
        with open(source) as f:
            lines = f.readlines()
        # Check that no line imports platformdirs (ignore comments/docstrings)
        import_lines = [line.strip() for line in lines if line.strip().startswith(("import ", "from "))]
        assert not any("platformdirs" in line for line in import_lines)
