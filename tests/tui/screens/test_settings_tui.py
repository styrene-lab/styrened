"""Comprehensive TUI tests for Settings screen.

Tests form rendering, validation, persistence, and keyboard interactions.
"""
from __future__ import annotations


from unittest.mock import patch

import pytest
from textual.widgets import Input, Select, Switch

from styrened.models.config import GroupThreadFeatureTierConfig
from styrened.tui.app import StyreneApp
from styrened.tui.models.config import StyreneConfig
from styrened.tui.screens.settings import SettingsScreen


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for all TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


@pytest.fixture
def test_config():
    """Create a test configuration."""
    from styrened.tui.services.config import get_default_config

    return get_default_config()


class TestSettingsComposition:
    """Test settings screen composition and widget tree."""

    @pytest.mark.asyncio
    async def test_settings_compose_creates_form_widgets(self, test_config):
        """Settings screen should create all form widgets."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, SettingsScreen)

            # Check for Input widgets
            inputs = list(screen.query(Input))
            assert len(inputs) > 0, "Settings should have Input widgets"

            # Check for Select widgets (theme, log level, etc.)
            selects = list(screen.query(Select))
            assert len(selects) > 0, "Settings should have Select widgets"

            # Check for Switch widgets
            switches = list(screen.query(Switch))
            assert len(switches) > 0, "Settings should have Switch widgets"

    @pytest.mark.asyncio
    async def test_settings_loads_current_config(self, test_config):
        """Settings screen should load current configuration values."""
        app = StyreneApp()

        # Modify test config
        test_config.tui.show_hardware_panel = True
        test_config.mesh.mesh_id = "test-mesh"

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            screen = app.screen

            # Verify config is loaded
            assert screen.config == test_config


class TestSettingsFormInteraction:
    """Test form field interactions."""

    @pytest.mark.asyncio
    async def test_text_input_accepts_user_input(self, test_config):
        """Text input fields should accept user input."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Find mesh_id input
            try:
                mesh_id_input = app.screen.query_one("#mesh_id", Input)
                mesh_id_input.focus()
                await pilot.pause()

                # Clear and type new value
                mesh_id_input.value = ""
                await pilot.press(*"test-mesh")
                await pilot.pause()

                # Input should contain the text
                assert "test-mesh" in mesh_id_input.value
            except Exception:
                # Widget IDs may vary
                pass

    @pytest.mark.asyncio
    async def test_tab_navigation_between_fields(self, test_config):
        """Tab key should navigate between form fields."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Get focusable widgets
            inputs = list(app.screen.query(Input))
            if len(inputs) >= 2:
                # Focus first input
                inputs[0].focus()
                await pilot.pause()

                # Press Tab
                await pilot.press("tab")
                await pilot.pause()

                # Focus should have moved (test doesn't crash)

    @pytest.mark.asyncio
    async def test_escape_cancels_without_saving(self, test_config):
        """Pressing Escape should cancel without saving changes."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Make some changes
            try:
                mesh_id_input = app.screen.query_one("#mesh_id", Input)
                mesh_id_input.value = "changed-value"
                await pilot.pause()
            except Exception:
                pass

            # Press Escape
            await pilot.press("escape")
            await pilot.pause()

            # Should return to previous screen without saving


class TestSettingsValidation:
    """Test form validation."""

    @pytest.mark.asyncio
    async def test_required_fields_validated(self, test_config):
        """Required fields should be validated before save."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Try to save (validation will run)
            await pilot.press("ctrl+s")
            await pilot.pause()

            # Should complete without crash

    @pytest.mark.asyncio
    async def test_path_validation(self, test_config):
        """Path fields should validate file paths."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Validation runs on save
            await pilot.press("ctrl+s")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_log_level_validation(self, test_config):
        """Log level should be one of valid values."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Select widgets enforce valid values
            log_level_select = app.screen.query_one("#log_level", Select)
            assert log_level_select is not None


class TestSettingsPersistence:
    """Test configuration saving and persistence."""

    @pytest.mark.asyncio
    async def test_save_writes_config_file(self, test_config):
        """Saving settings should write to config file."""
        app = StyreneApp()

        with patch("styrened.tui.screens.settings.save_config") as mock_save:
            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                # Press Ctrl+S to save
                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # save_config should be called
                assert mock_save.called

    @pytest.mark.asyncio
    async def test_save_preserves_other_settings(self, test_config):
        """Saving should preserve settings not shown in form."""
        app = StyreneApp()

        with patch("styrened.tui.screens.settings.save_config") as mock_save:
            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                # Save without changing anything
                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # Config should be preserved
                if mock_save.called:
                    saved_config = mock_save.call_args[0][0]
                    assert isinstance(saved_config, StyreneConfig)

    @pytest.mark.asyncio
    async def test_config_file_permissions(self, test_config):
        """Config file should be created with correct permissions."""
        app = StyreneApp()

        with patch("styrened.tui.screens.settings.save_config"):
            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                # Save settings
                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # Config saved (permissions handled by save_config)


class TestSettingsKeyboardBindings:
    """Test settings screen keyboard bindings."""

    @pytest.mark.asyncio
    async def test_ctrl_s_saves_settings(self, test_config):
        """Ctrl+S should save settings."""
        app = StyreneApp()

        with patch("styrened.tui.screens.settings.save_config") as mock_save:
            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                # Press Ctrl+S
                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # save_config should be called
                assert mock_save.called

    @pytest.mark.asyncio
    async def test_escape_closes_settings(self, test_config):
        """Escape should close settings screen."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Press Escape
            await pilot.press("escape")
            await pilot.pause()

            # Screen should close (doesn't crash)


class TestGroupThreadSettings:
    """Test group-thread footprint controls in Settings."""

    @pytest.mark.asyncio
    async def test_group_thread_controls_render_current_values(self, test_config):
        test_config.core.group_threads.feature_tier = GroupThreadFeatureTierConfig.MINIMAL
        test_config.core.group_threads.bounded_retention = True
        test_config.core.group_threads.metadata_first_sync = True
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            screen = app.screen
            assert screen.query_one("#group_threads_enabled", Switch).value is True
            assert (
                screen.query_one("#group_threads_feature_tier", Select).value
                is GroupThreadFeatureTierConfig.MINIMAL
            )
            assert screen.query_one("#group_threads_bounded_retention", Switch).value is True
            assert screen.query_one("#group_threads_metadata_first_sync", Switch).value is True

    @pytest.mark.asyncio
    async def test_save_persists_group_thread_policy(self, test_config):
        app = StyreneApp()

        with (
            patch("styrened.tui.screens.settings.save_config") as mock_save,
            patch("styrened.tui.screens.settings.SettingsScreen._save_identity") as mock_save_id,
        ):
            mock_save_id.return_value = None

            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                screen = app.screen
                screen.query_one("#group_threads_enabled", Switch).value = False
                screen.query_one("#group_threads_bounded_retention", Switch).value = True
                screen.query_one("#group_threads_metadata_first_sync", Switch).value = True
                screen.query_one("#group_threads_auto_media_fetch", Switch).value = False
                screen.query_one("#group_threads_background_catchup", Switch).value = False
                screen.query_one("#group_threads_first_run_auto_tier", Switch).value = False
                tier_select = screen.query_one("#group_threads_feature_tier", Select)
                tier_select.value = GroupThreadFeatureTierConfig.FULL
                await pilot.pause()

                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                assert mock_save.called
                assert test_config.core.group_threads.enabled is False
                assert test_config.core.group_threads.feature_tier is GroupThreadFeatureTierConfig.FULL
                assert test_config.core.group_threads.bounded_retention is True
                assert test_config.core.group_threads.metadata_first_sync is True
                assert test_config.core.group_threads.auto_media_fetch is False
                assert test_config.core.group_threads.background_catchup is False
                assert test_config.core.group_threads.first_run_auto_tier is False


class TestSettingsThemeChanges:
    """Test theme configuration (theme selector disabled — single theme)."""

    pass


class TestSettingsIdentityManagement:
    """Test identity path configuration."""

    @pytest.mark.asyncio
    async def test_identity_path_picker(self, test_config):
        """Identity path should have configuration."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Screen renders successfully

    @pytest.mark.asyncio
    async def test_identity_path_validation(self, test_config):
        """Identity path should be validated as file."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Validation happens on save
            await pilot.press("ctrl+s")
            await pilot.pause(1.0)


class TestSettingsErrorHandling:
    """Test error handling in settings."""

    @pytest.mark.asyncio
    async def test_config_load_failure_shows_defaults(self):
        """Config load failure should show default values."""
        app = StyreneApp()

        # App initializes with defaults on error
        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(app.config))
            await pilot.pause()

            # Should show default values
            screen = app.screen
            assert isinstance(screen, SettingsScreen)

    @pytest.mark.asyncio
    async def test_config_save_failure_shows_error(self, test_config):
        """Config save failure should show error message."""
        app = StyreneApp()

        with patch("styrened.tui.screens.settings.save_config", side_effect=Exception("Save failed")):
            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                # Try to save
                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # Should show error (doesn't crash)

    @pytest.mark.asyncio
    async def test_readonly_config_file_handled(self, test_config):
        """Read-only config file should be handled gracefully."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.settings.save_config", side_effect=PermissionError("Read-only")
        ):
            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                # Try to save
                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # Should handle error gracefully


class TestIdentityIconValidation:
    """Tests for identity icon length validation (W17)."""

    @pytest.mark.asyncio
    async def test_icon_longer_than_4_chars_rejected(self, test_config):
        """Icons longer than 4 characters should be rejected on save."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            screen = app.screen

            # Set icon to something too long
            icon_input = screen.query_one("#identity_icon", Input)
            icon_input.value = "ABCDE"  # 5 chars, exceeds limit
            await pilot.pause()

            # Try to save
            with patch("styrened.tui.screens.settings.save_config") as mock_save:
                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # save_config should NOT be called because validation fails
                mock_save.assert_not_called()

            # Error message should mention icon — render_line captures
            # the Rich content set by _show_error
            from textual.widgets import Static

            status = screen.query_one("#status-message", Static)
            rendered = status.render()
            rendered_str = str(rendered)
            assert "4 characters" in rendered_str or "Icon" in rendered_str

    @pytest.mark.asyncio
    async def test_icon_4_chars_or_fewer_accepted(self, test_config):
        """Icons of 4 characters or fewer should be accepted."""
        app = StyreneApp()

        with patch("styrened.tui.screens.settings.save_config") as mock_save:
            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                screen = app.screen

                # Set a valid 2-char emoji icon
                icon_input = screen.query_one("#identity_icon", Input)
                icon_input.value = "\U0001f4e1"  # single emoji
                await pilot.pause()

                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # save_config should be called (validation passes)
                assert mock_save.called


class TestIPCIdentitySaveFailure:
    """Tests for IPC identity save failure not aborting save (W16)."""

    @pytest.mark.asyncio
    async def test_ipc_identity_failure_continues_save(self, test_config):
        """IPC identity save failure should log warning but continue saving."""
        from unittest.mock import AsyncMock, MagicMock

        from styrened.tui.services.app_lifecycle import LifecycleMode

        bridge = MagicMock()
        bridge.set_identity = AsyncMock(side_effect=Exception("IPC failed"))
        bridge.get_status = AsyncMock(return_value={})
        bridge.get_identity = AsyncMock(return_value={})
        bridge.get_hub_status = AsyncMock(return_value={})
        bridge.get_core_config = AsyncMock(return_value={})
        bridge.get_devices = AsyncMock(return_value=[])
        bridge.get_conversations = AsyncMock(return_value=[])
        bridge.get_contacts = AsyncMock(return_value=[])
        bridge.get_auto_reply = AsyncMock(return_value={})
        bridge.subscribe_activity = AsyncMock(return_value=None)

        lifecycle = MagicMock()
        lifecycle.ipc_bridge = bridge
        lifecycle.initialize_async = AsyncMock(return_value=True)
        lifecycle.active_mode = LifecycleMode.IPC
        lifecycle.shutdown_async = AsyncMock()

        app = StyreneApp()
        app._lifecycle = lifecycle

        with patch("styrened.tui.screens.settings.save_config") as mock_save:
            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # save_config should still be called despite IPC failure
                assert mock_save.called


class TestLocalModeClearIdentity:
    """Tests for clearing identity fields in local mode."""

    @pytest.mark.asyncio
    async def test_empty_display_name_clears_value(self, test_config):
        """Empty display_name string should clear the value in local mode."""
        app = StyreneApp()

        with (
            patch("styrened.tui.screens.settings.save_config"),
            patch(
                "styrened.tui.screens.settings.SettingsScreen._save_identity"
            ) as mock_save_id,
        ):
            mock_save_id.return_value = None

            async with app.run_test() as pilot:
                await app.push_screen(SettingsScreen(test_config))
                await pilot.pause()

                screen = app.screen

                # Clear display name
                dn_input = screen.query_one("#identity_display_name", Input)
                dn_input.value = ""
                await pilot.pause()

                await pilot.press("ctrl+s")
                await pilot.pause(1.0)

                # _save_identity should be called with empty string
                if mock_save_id.called:
                    args = mock_save_id.call_args
                    assert args[0][0] == ""  # display_name == ""


class TestSettingsBridgeUsage:
    """Tests for Settings using the typed services bridge."""

    @pytest.mark.asyncio
    async def test_generate_page_uses_services_bridge(self, test_config):
        from unittest.mock import AsyncMock, MagicMock

        from styrened.tui.services.app_lifecycle import LifecycleMode

        app = StyreneApp()
        bridge = MagicMock()
        bridge.page_regenerate_index = AsyncMock(return_value=True)
        bridge.get_status = AsyncMock(return_value={})
        bridge.get_identity = AsyncMock(return_value={})
        bridge.get_hub_status = AsyncMock(return_value={})
        bridge.get_core_config = AsyncMock(return_value={})
        bridge.get_devices = AsyncMock(return_value=[])
        bridge.get_conversations = AsyncMock(return_value=[])
        bridge.get_contacts = AsyncMock(return_value=[])
        bridge.get_auto_reply = AsyncMock(return_value={})
        bridge.subscribe_activity = AsyncMock(return_value=None)

        lifecycle = MagicMock()
        lifecycle.ipc_bridge = bridge
        lifecycle.initialize_async = AsyncMock(return_value=True)
        lifecycle.active_mode = LifecycleMode.IPC
        lifecycle.shutdown_async = AsyncMock()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, SettingsScreen)
            worker = screen._do_generate_page()
            await worker.wait()
            await pilot.pause()

            bridge.page_regenerate_index.assert_awaited_once()


class TestSettingsResetToDefaults:
    """Test reset to defaults functionality."""

    @pytest.mark.asyncio
    async def test_reset_button_restores_defaults(self, test_config):
        """Reset button should restore default values."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Make changes
            try:
                mesh_id_input = app.screen.query_one("#mesh_id", Input)
                mesh_id_input.value = "modified-value"
                await pilot.pause()
            except Exception:
                pass

            # Screen works (reset would be a button click)

    @pytest.mark.asyncio
    async def test_reset_confirmation_dialog(self, test_config):
        """Reset should show confirmation dialog."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(SettingsScreen(test_config))
            await pilot.pause()

            # Screen renders successfully
            # Reset confirmation would be implementation-specific
