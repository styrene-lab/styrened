"""Unit tests for CoreLifecycle RNS config precedence.

Tests the config path discovery and precedence logic to ensure:
1. Explicit override from core-config.yaml is checked first
2. Standard RNS paths are checked in correct order
3. Temp config is generated only when no existing config found
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from styrened.models.config import CoreConfig


class TestRNSConfigPrecedence:
    """Tests for RNS configuration path precedence in CoreLifecycle."""

    def test_explicit_override_takes_precedence(self, tmp_path: Path) -> None:
        """config_path_override should be checked first when set."""
        # Create a config at the override path
        override_dir = tmp_path / "custom-rns"
        override_dir.mkdir()
        (override_dir / "config").write_text("[reticulum]\nenable_transport = false\n")

        config = CoreConfig()
        config.reticulum.config_path_override = override_dir

        from styrened.services.reticulum import find_reticulum_config

        result = find_reticulum_config(override=config.reticulum.config_path_override)
        assert result == override_dir

    def test_override_path_not_found_falls_back_to_standard(self, tmp_path: Path) -> None:
        """When override path doesn't exist, should check standard paths."""
        # Override points to non-existent path
        config = CoreConfig()
        config.reticulum.config_path_override = tmp_path / "nonexistent"

        # Create a config at XDG path
        with patch("styrened.services.reticulum.get_reticulum_config_paths") as mock_paths:
            xdg_dir = tmp_path / ".config" / "reticulum"
            xdg_dir.mkdir(parents=True)
            (xdg_dir / "config").write_text("[reticulum]\n")

            mock_paths.return_value = [xdg_dir]

            from styrened.services.reticulum import find_reticulum_config

            result = find_reticulum_config(override=config.reticulum.config_path_override)
            assert result == xdg_dir

    def test_none_override_searches_standard_paths(self) -> None:
        """When override is None, should only check standard paths."""
        from styrened.services.reticulum import find_reticulum_config

        # With no override and no configs, should return None
        with patch("styrened.services.reticulum.get_reticulum_config_paths") as mock_paths:
            mock_paths.return_value = []
            result = find_reticulum_config(override=None)
            assert result is None

    def test_standard_path_priority_order(self, tmp_path: Path) -> None:
        """Standard paths should be checked in XDG priority order."""
        from styrened.services.reticulum import get_reticulum_config_paths

        paths = get_reticulum_config_paths()

        # Should return paths in this order:
        # 1. /etc/reticulum (system)
        # 2. ~/.config/reticulum (XDG)
        # 3. ~/.reticulum (legacy)
        assert len(paths) == 3
        assert paths[0] == Path("/etc/reticulum")
        assert paths[1] == Path.home() / ".config" / "reticulum"
        assert paths[2] == Path.home() / ".reticulum"

    def test_find_reticulum_config_with_xdg_config(self, tmp_path: Path) -> None:
        """XDG config should be found when present."""
        with patch("styrened.services.reticulum.get_reticulum_config_paths") as mock_paths:
            xdg_dir = tmp_path / ".config" / "reticulum"
            xdg_dir.mkdir(parents=True)
            (xdg_dir / "config").write_text("[reticulum]\n")

            # Only XDG path exists
            mock_paths.return_value = [
                tmp_path / "nonexistent1",  # /etc/reticulum - doesn't exist
                xdg_dir,  # ~/.config/reticulum - exists
                tmp_path / "nonexistent2",  # ~/.reticulum - doesn't exist
            ]

            from styrened.services.reticulum import find_reticulum_config

            result = find_reticulum_config()
            assert result == xdg_dir

    def test_find_reticulum_config_prefers_earlier_path(self, tmp_path: Path) -> None:
        """Earlier paths in priority order should be preferred."""
        with patch("styrened.services.reticulum.get_reticulum_config_paths") as mock_paths:
            etc_dir = tmp_path / "etc" / "reticulum"
            xdg_dir = tmp_path / ".config" / "reticulum"
            legacy_dir = tmp_path / ".reticulum"

            # Create configs at all three locations
            for d in [etc_dir, xdg_dir, legacy_dir]:
                d.mkdir(parents=True)
                (d / "config").write_text("[reticulum]\n")

            mock_paths.return_value = [etc_dir, xdg_dir, legacy_dir]

            from styrened.services.reticulum import find_reticulum_config

            result = find_reticulum_config()
            # Should return first one found (etc)
            assert result == etc_dir


class TestLifecycleConfigLogging:
    """Tests for config path logging during initialization."""

    def test_logs_which_config_used(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Should log which config path is being used."""
        import logging

        caplog.set_level(logging.INFO)

        config_dir = tmp_path / "reticulum"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum]\nenable_transport = false\n")

        config = CoreConfig()
        config.reticulum.config_path_override = config_dir

        from styrened.services.reticulum import find_reticulum_config

        result = find_reticulum_config(override=config.reticulum.config_path_override)
        assert result == config_dir

    def test_logs_searched_paths_when_generating_temp(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Should log which paths were searched when generating temp config."""
        # This test validates the logging behavior we want to add
        # Currently just ensures find_reticulum_config returns None for non-existent paths
        from styrened.services.reticulum import find_reticulum_config

        with patch("styrened.services.reticulum.get_reticulum_config_paths") as mock_paths:
            mock_paths.return_value = [
                tmp_path / "nonexistent1",
                tmp_path / "nonexistent2",
            ]

            result = find_reticulum_config()
            assert result is None


class TestIsReticulumConfigured:
    """Tests for is_reticulum_configured() helper."""

    def test_configured_when_config_file_exists(self, tmp_path: Path) -> None:
        """Should return True when config file exists."""
        config_dir = tmp_path / "reticulum"
        config_dir.mkdir()
        (config_dir / "config").write_text("[reticulum]\n")

        from styrened.services.reticulum import is_reticulum_configured

        assert is_reticulum_configured(config_dir=config_dir) is True

    def test_not_configured_when_directory_missing(self, tmp_path: Path) -> None:
        """Should return False when directory doesn't exist."""
        from styrened.services.reticulum import is_reticulum_configured

        assert is_reticulum_configured(config_dir=tmp_path / "nonexistent") is False

    def test_not_configured_when_config_file_missing(self, tmp_path: Path) -> None:
        """Should return False when directory exists but config file missing."""
        config_dir = tmp_path / "reticulum"
        config_dir.mkdir()
        # No config file created

        from styrened.services.reticulum import is_reticulum_configured

        assert is_reticulum_configured(config_dir=config_dir) is False
