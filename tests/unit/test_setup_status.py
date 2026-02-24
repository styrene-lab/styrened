"""Tests for get_setup_status().

Validates first-run setup status detection.
"""

from __future__ import annotations

from unittest.mock import patch

from styrened.services.setup import SetupStatus, get_setup_status


class TestSetupStatus:
    """Tests for the SetupStatus dataclass."""

    def test_all_true_is_complete(self) -> None:
        """All True → is_complete is True."""
        status = SetupStatus(
            identity_configured=True,
            config_file_exists=True,
            display_name_set=True,
            rns_initialized=True,
        )
        assert status.is_complete is True

    def test_all_false_is_not_complete(self) -> None:
        """All False → is_complete is False."""
        status = SetupStatus(
            identity_configured=False,
            config_file_exists=False,
            display_name_set=False,
            rns_initialized=False,
        )
        assert status.is_complete is False

    def test_partial_state_is_not_complete(self) -> None:
        """Mixed True/False → is_complete is False."""
        status = SetupStatus(
            identity_configured=True,
            config_file_exists=True,
            display_name_set=False,
            rns_initialized=True,
        )
        assert status.is_complete is False


class TestGetSetupStatus:
    """Tests for get_setup_status() with mocked dependencies."""

    @patch("styrened.services.setup.get_operator_identity", return_value=None)
    @patch("styrened.services.setup.is_reticulum_configured", return_value=False)
    @patch("styrened.services.setup.paths")
    @patch("styrened.services.config.load_core_config")
    def test_fresh_state_all_false(
        self, mock_load_config, mock_paths, mock_rns, mock_identity, tmp_path
    ) -> None:
        """Fresh state with no identity, no config file → all False."""
        from styrened.models.config import CoreConfig

        mock_identity.return_value = None
        mock_rns.return_value = False
        mock_paths.config_file.return_value = tmp_path / "config.yaml"  # Does not exist
        mock_load_config.return_value = CoreConfig()  # Default display_name

        status = get_setup_status()

        assert status.identity_configured is False
        assert status.config_file_exists is False
        assert status.display_name_set is False
        assert status.rns_initialized is False
        assert status.is_complete is False

    @patch("styrened.services.setup.get_operator_identity", return_value="a" * 32)
    @patch("styrened.services.setup.is_reticulum_configured", return_value=True)
    @patch("styrened.services.setup.paths")
    @patch("styrened.services.config.load_core_config")
    def test_configured_state_all_true(
        self, mock_load_config, mock_paths, mock_rns, mock_identity, tmp_path
    ) -> None:
        """Fully configured state → all True."""
        from styrened.models.config import CoreConfig

        # Create config file
        config_file = tmp_path / "config.yaml"
        config_file.write_text("reticulum:\n  mode: standalone\n")
        mock_paths.config_file.return_value = config_file

        # Custom display name
        config = CoreConfig()
        config.identity.display_name = "My Custom Node"
        mock_load_config.return_value = config

        status = get_setup_status()

        assert status.identity_configured is True
        assert status.config_file_exists is True
        assert status.display_name_set is True
        assert status.rns_initialized is True
        assert status.is_complete is True

    @patch("styrened.services.setup.get_operator_identity", return_value="b" * 32)
    @patch("styrened.services.setup.is_reticulum_configured", return_value=True)
    @patch("styrened.services.setup.paths")
    @patch("styrened.services.config.load_core_config")
    def test_partial_state_identity_exists_default_name(
        self, mock_load_config, mock_paths, mock_rns, mock_identity, tmp_path
    ) -> None:
        """Identity exists but display_name still default → partial."""
        from styrened.models.config import CoreConfig

        config_file = tmp_path / "config.yaml"
        config_file.write_text("identity:\n  display_name: Anonymous Styrene\n")
        mock_paths.config_file.return_value = config_file

        mock_load_config.return_value = CoreConfig()  # Default display_name

        status = get_setup_status()

        assert status.identity_configured is True
        assert status.config_file_exists is True
        assert status.display_name_set is False  # Still default
        assert status.rns_initialized is True
        assert status.is_complete is False
