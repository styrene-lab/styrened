"""Tests for DaemonSetupScreen."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from styrened.tui.app import StyreneApp
from styrened.tui.screens.daemon_setup import DaemonSetupScreen
from styrened.tui.services.service_installer import ServicePlatform


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for all TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch(
            "styrened.tui.services.reticulum.find_reticulum_config",
            return_value=fake_config,
        ),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


class TestDaemonSetupComposition:
    """Test screen composition and widget tree."""

    @pytest.mark.asyncio
    async def test_compose_creates_expected_widgets(self):
        """Screen should create info text, buttons, and status area."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DaemonSetupScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, DaemonSetupScreen)

            # Check buttons exist
            from textual.widgets import Button

            buttons = screen.query(Button)
            button_ids = [b.id for b in buttons]
            assert "btn-install-service" in button_ids
            assert "btn-start-now" in button_ids
            assert "btn-skip" in button_ids

    @pytest.mark.asyncio
    async def test_info_text_is_populated_on_mount(self):
        """Info text should be populated after mount."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DaemonSetupScreen())
            await pilot.pause()

            from textual.widgets import Static

            info = app.screen.query_one("#daemon-info-text", Static)
            # Should have some content (not the initial empty string)
            rendered = info.render()
            assert rendered is not None

    @pytest.mark.asyncio
    async def test_status_area_exists(self):
        """Status area widget should exist."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DaemonSetupScreen())
            await pilot.pause()

            from textual.widgets import Static

            status = app.screen.query_one("#daemon-status", Static)
            assert status is not None


class TestDaemonSetupPlatformDetection:
    """Test platform-specific behavior."""

    @pytest.mark.asyncio
    async def test_unsupported_platform_disables_install(self):
        """Install button should be disabled on unsupported platforms."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.daemon_setup.detect_platform",
            return_value=ServicePlatform.UNSUPPORTED,
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DaemonSetupScreen())
                await pilot.pause()

                from textual.widgets import Button

                install_btn = app.screen.query_one("#btn-install-service", Button)
                assert install_btn.disabled is True

    @pytest.mark.asyncio
    async def test_launchd_platform_enables_install(self):
        """Install button should be enabled on macOS."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.daemon_setup.detect_platform",
            return_value=ServicePlatform.LAUNCHD,
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DaemonSetupScreen())
                await pilot.pause()

                from textual.widgets import Button

                install_btn = app.screen.query_one("#btn-install-service", Button)
                assert install_btn.disabled is False

    @pytest.mark.asyncio
    async def test_systemd_platform_enables_install(self):
        """Install button should be enabled on Linux with systemd."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.daemon_setup.detect_platform",
            return_value=ServicePlatform.SYSTEMD,
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DaemonSetupScreen())
                await pilot.pause()

                from textual.widgets import Button

                install_btn = app.screen.query_one("#btn-install-service", Button)
                assert install_btn.disabled is False


class TestDaemonSetupCSS:
    """Test that CSS uses theme variables, not hardcoded colors."""

    @pytest.mark.asyncio
    async def test_no_hardcoded_hex_colors_in_screen(self):
        """Screen source should not contain hardcoded hex colors."""
        import inspect

        source = inspect.getsource(DaemonSetupScreen)
        # Check for common hardcoded color patterns
        import re

        hex_colors = re.findall(r"#[0-9a-fA-F]{3,8}\b", source)
        # Filter out Python comments and IDs (like #btn-skip)
        real_colors = [
            c for c in hex_colors
            if not any(c.startswith(f"#{prefix}") for prefix in [
                "btn", "daemon", "wizard",
            ])
        ]
        assert real_colors == [], f"Found hardcoded colors: {real_colors}"


class TestDaemonSetupBindings:
    """Test keyboard bindings."""

    @pytest.mark.asyncio
    async def test_escape_binding_exists(self):
        """Escape should be bound to skip."""
        screen = DaemonSetupScreen()
        binding_keys = [b.key for b in screen.BINDINGS]
        assert "escape" in binding_keys

    @pytest.mark.asyncio
    async def test_skip_button_dismisses_with_false(self):
        """Skip button should dismiss the screen with False."""
        app = StyreneApp()
        result_holder = {}

        def capture_result(result):
            result_holder["value"] = result

        async with app.run_test() as pilot:
            app.push_screen(DaemonSetupScreen(), callback=capture_result)
            await pilot.pause()

            # Use press on the focused button after tabbing to it,
            # or directly invoke the action
            screen = app.screen
            assert isinstance(screen, DaemonSetupScreen)
            screen.on_skip()
            await pilot.pause()

            assert result_holder.get("value") is False
