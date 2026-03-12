"""Tests for first-run wizard screen and config generation."""
from __future__ import annotations


from pathlib import Path
from unittest.mock import patch

import pytest

from styrened.tui.screens.first_run_wizard import FirstRunWizardScreen
from styrened.tui.services.reticulum import (
    _generate_config_content,
    create_default_reticulum_config,
)


class TestConfigGeneration:
    """Tests for Reticulum config generation."""

    def test_generate_config_auto_interface(self):
        """Test config generation with AutoInterface."""
        config = _generate_config_content("auto")

        assert "# Reticulum Configuration" in config
        assert "enable_transport = False" in config
        assert "AutoInterface" in config
        assert "type = AutoInterface" in config
        assert "enabled = Yes" in config

    def test_generate_config_tcp_interface(self):
        """Test config generation with TCP client interface."""
        config = _generate_config_content("tcp")

        assert "TCPClientInterface" in config
        assert "target_host" in config
        assert "target_port" in config

    def test_generate_config_tcp_server_interface(self):
        """Test config generation with TCP server interface."""
        config = _generate_config_content("tcp-server")

        assert "TCPServerInterface" in config
        assert "listen_ip" in config
        assert "listen_port" in config

    def test_generate_config_unknown_fallback(self):
        """Test config generation with unknown interface type falls back to auto."""
        config = _generate_config_content("unknown")

        # Should fallback to AutoInterface
        assert "AutoInterface" in config

    def test_create_default_config(self, tmp_path: Path):
        """Test creating default config file."""
        # create_default_reticulum_config uses Path.home() / ".reticulum" directly,
        # so we mock Path.home to redirect to our tmp_path
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        expected_config_dir = fake_home / ".reticulum"

        with patch.object(Path, "home", return_value=fake_home):
            config_file = create_default_reticulum_config("auto")

            assert config_file.exists()
            assert config_file == expected_config_dir / "config"

            # Verify storage directory created
            storage_dir = expected_config_dir / "storage"
            assert storage_dir.exists()
            assert storage_dir.is_dir()

            # Verify config content
            content = config_file.read_text()
            assert "Reticulum Configuration" in content
            assert "AutoInterface" in content


class TestFirstRunWizardScreen:
    """Tests for FirstRunWizardScreen."""

    @pytest.mark.asyncio
    async def test_wizard_initializes(self):
        """Test wizard screen initializes correctly."""
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test():
            # Push wizard screen
            await app.push_screen(FirstRunWizardScreen())

            # Verify wizard is showing
            assert app.screen.id is None  # Anonymous screen
            assert isinstance(app.screen, FirstRunWizardScreen)

            # Verify step 1 is visible
            assert app.screen.step == 1

    @pytest.mark.asyncio
    async def test_wizard_navigation(self):
        """Test wizard step navigation."""
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test():
            wizard = FirstRunWizardScreen()
            await app.push_screen(wizard)

            # Should start at step 1
            assert wizard.step == 1

            # Navigate to step 2
            wizard._show_step(2)
            assert wizard.step == 2

            # Navigate to step 3
            wizard._show_step(3)
            assert wizard.step == 3

            # Navigate back to step 1
            wizard._show_step(1)
            assert wizard.step == 1

    @pytest.mark.asyncio
    async def test_wizard_skip(self):
        """Test skipping wizard returns False."""
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test():
            wizard = FirstRunWizardScreen()

            # Mock dismiss to capture result
            dismiss_called = False
            original_dismiss = wizard.dismiss

            def mock_dismiss(result: bool) -> None:
                nonlocal dismiss_called
                dismiss_called = True
                assert result is False  # Should skip (False)
                original_dismiss(result)

            wizard.dismiss = mock_dismiss  # type: ignore[method-assign]

            await app.push_screen(wizard)

            # Trigger skip action
            wizard.action_cancel()

            assert dismiss_called

    @pytest.mark.asyncio
    async def test_wizard_interface_selection(self):
        """Test interface selection updates wizard state."""
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test():
            wizard = FirstRunWizardScreen()
            await app.push_screen(wizard)

            # Navigate to interface selection
            wizard._show_step(2)

            # Default should be auto
            assert wizard.interface_choice == "auto"

            # Change to TCP (simulated)
            wizard.interface_choice = "tcp"
            assert wizard.interface_choice == "tcp"

    @pytest.mark.asyncio
    async def test_wizard_create_config(self, tmp_path: Path):
        """Test wizard creates config file."""
        from styrened.tui.app import StyreneApp

        app = StyreneApp()
        async with app.run_test():
            wizard = FirstRunWizardScreen()
            await app.push_screen(wizard)

            # Navigate to finalization
            wizard._show_step(3)

            # Mock config creation
            with patch(
                "styrened.tui.services.reticulum.create_default_reticulum_config",
                return_value=tmp_path / "config",
            ) as mock_create:
                # Trigger config creation (via button would be ideal, but we'll call directly)
                wizard.on_step3_create()

                # Verify config creation was called
                mock_create.assert_called_once_with(interface_type="auto")
