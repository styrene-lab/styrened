"""Tests for the deterministic path resolution module."""

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
        monkeypatch.delenv("STYRENE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("STYRENE_DATA_DIR", raising=False)
        monkeypatch.delenv("STYRENE_CACHE_DIR", raising=False)
        monkeypatch.delenv("STYRENE_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("STYRENED_SOCKET", raising=False)
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        # Ensure /etc/styrene/config.yaml doesn't affect mode detection
        monkeypatch.setattr(paths, "mode", lambda: Mode.USER)

    def test_config_dir(self):
        assert paths.config_dir() == Path.home() / ".config" / "styrene"

    def test_data_dir(self):
        assert paths.data_dir() == Path.home() / ".local" / "share" / "styrene"

    def test_cache_dir(self):
        assert paths.cache_dir() == Path.home() / ".cache" / "styrene"

    def test_log_dir(self):
        assert paths.log_dir() == Path.home() / ".local" / "share" / "styrene" / "logs"

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
        assert paths.identity_file() == Path.home() / ".config" / "styrene" / "operator.key"

    def test_nodes_db(self):
        assert paths.nodes_db() == Path.home() / ".local" / "share" / "styrene" / "nodes.db"

    def test_messages_db(self):
        assert paths.messages_db() == Path.home() / ".local" / "share" / "styrene" / "messages.db"

    def test_lxmf_storage(self):
        assert paths.lxmf_storage() == Path.home() / ".local" / "share" / "styrene" / "lxmf"

    def test_fleet_inventory(self):
        assert paths.fleet_inventory() == Path.home() / ".config" / "styrene" / "fleet-inventory.yaml"

    def test_control_socket(self):
        assert paths.control_socket() == Path.home() / ".local" / "run" / "styrened" / "control.sock"


class TestSystemModePaths:
    """SYSTEM mode path resolution."""

    @pytest.fixture(autouse=True)
    def _system_mode(self, monkeypatch):
        monkeypatch.delenv("STYRENE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("STYRENE_DATA_DIR", raising=False)
        monkeypatch.delenv("STYRENE_CACHE_DIR", raising=False)
        monkeypatch.delenv("STYRENE_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("STYRENED_SOCKET", raising=False)
        monkeypatch.setattr(paths, "mode", lambda: Mode.SYSTEM)

    def test_config_dir(self):
        assert paths.config_dir() == Path("/etc/styrene")

    def test_data_dir(self):
        assert paths.data_dir() == Path("/var/lib/styrene")

    def test_cache_dir(self):
        assert paths.cache_dir() == Path("/var/cache/styrene")

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

    def test_config_dir_override(self, monkeypatch):
        monkeypatch.setenv("STYRENE_CONFIG_DIR", "/custom/config")
        assert paths.config_dir() == Path("/custom/config")

    def test_data_dir_override(self, monkeypatch):
        monkeypatch.setenv("STYRENE_DATA_DIR", "/custom/data")
        assert paths.data_dir() == Path("/custom/data")

    def test_cache_dir_override(self, monkeypatch):
        monkeypatch.setenv("STYRENE_CACHE_DIR", "/custom/cache")
        assert paths.cache_dir() == Path("/custom/cache")

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


class TestEnsureDirectories:
    """Directory creation."""

    def test_creates_all_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("STYRENE_CONFIG_DIR", str(tmp_path / "config"))
        monkeypatch.setenv("STYRENE_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("STYRENE_CACHE_DIR", str(tmp_path / "cache"))

        paths.ensure_directories()

        assert (tmp_path / "config").is_dir()
        assert (tmp_path / "data").is_dir()
        assert (tmp_path / "cache").is_dir()
        assert (tmp_path / "data" / "logs").is_dir()


class TestMigrateLegacyPaths:
    """Legacy path migration."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.home.mkdir()
        monkeypatch.setattr(Path, "home", staticmethod(lambda: self.home))
        monkeypatch.setattr(paths, "mode", lambda: Mode.USER)
        monkeypatch.delenv("STYRENE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("STYRENE_DATA_DIR", raising=False)
        monkeypatch.delenv("STYRENE_CACHE_DIR", raising=False)

    def test_copies_legacy_tui_config(self):
        """~/.styrene/config.yaml -> ~/.config/styrene/tui.yaml."""
        legacy = self.home / ".styrene" / "config.yaml"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("tui: {theme: dark}")

        actions = paths.migrate_legacy_paths()

        assert (self.home / ".config" / "styrene" / "tui.yaml").exists()
        assert any("tui.yaml" in a for a in actions)

    def test_copies_legacy_operator_key(self):
        """~/.styrene/operator.key -> ~/.config/styrene/operator.key."""
        legacy = self.home / ".styrene" / "operator.key"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"key-data")

        paths.migrate_legacy_paths()

        canonical = self.home / ".config" / "styrene" / "operator.key"
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

        # Create canonical
        canonical = self.home / ".config" / "styrene" / "operator.key"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"new-key")

        actions = paths.migrate_legacy_paths()

        # Canonical should be unchanged
        assert canonical.read_bytes() == b"new-key"
        assert not any("operator.key" in a for a in actions)

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
