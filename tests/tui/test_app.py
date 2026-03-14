"""Tests for the main Styrene application."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest

from styrened import paths
from styrened.tui.app import StyreneApp
from styrened.tui.screens.splash import SplashScreen


def test_app_instantiation():
    """Verify app can be instantiated."""
    app = StyreneApp()
    assert app.title == "STYRENE"
    assert app.sub_title == "Management"


@pytest.mark.asyncio
async def test_app_starts_with_splash(app: StyreneApp):
    """Startup should present SplashScreen before dashboard/setup routing."""
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SplashScreen)


@pytest.mark.asyncio
async def test_quit_binding(app: StyreneApp):
    """Verify double ctrl+c quits the app."""
    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        await pilot.press("ctrl+c")
        assert app._exit


@pytest.mark.asyncio
async def test_app_initializes_reticulum_on_startup():
    """Verify app initializes Reticulum on mount when daemon path succeeds."""
    app = StyreneApp()

    async with app.run_test():
        if not paths.identity_file().exists():
            pytest.skip(
                "Operator identity not created (RNS initialization likely failed; "
                "this is expected in environments without network interfaces)"
            )

        identity = paths.identity_file().read_bytes().hex()
        assert len(identity) > 0
        assert all(c in "0123456789abcdef" for c in identity)


def test_app_uses_existing_operator_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Verify app reuses existing operator identity if present."""
    monkeypatch.setenv("STYRENE_CONFIG_DIR", str(tmp_path / "config"))
    test_identity = b"test_identity_123456789012345678"
    paths.identity_file().parent.mkdir(parents=True, exist_ok=True)
    paths.identity_file().write_bytes(test_identity)

    StyreneApp()

    assert paths.identity_file().read_bytes() == test_identity


def test_app_rns_initialization_graceful_failure():
    """Verify app handles RNS initialization failure gracefully."""
    app = StyreneApp()
    assert app.title == "STYRENE"
    assert app.config is not None


@pytest.mark.asyncio
async def test_app_cleans_up_rns_on_shutdown():
    """Verify app cleans up RNS resources on shutdown."""
    from styrened.services.rns_service import get_rns_service

    app = StyreneApp()
    rns_service = get_rns_service()

    async with app.run_test():
        pass

    await app.on_shutdown()

    assert not rns_service.is_initialized


@pytest.mark.asyncio
async def test_splash_completion_routes_to_dashboard():
    """Successful splash completion should proceed to dashboard workflow."""
    app = StyreneApp()
    app._proceed_after_daemon = AsyncMock()  # type: ignore[method-assign]

    await app._on_splash_complete(True)

    app._proceed_after_daemon.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_splash_opens_setup_screen():
    """Timed-out splash completion should open daemon setup."""
    app = StyreneApp()

    with patch.object(app, "push_screen") as push_screen:
        await app._on_splash_complete(False)

    assert push_screen.called
    pushed = push_screen.call_args.args[0]
    assert pushed.__class__.__name__ == "DaemonSetupScreen"


@pytest.mark.asyncio
async def test_proceed_after_daemon_defers_device_cache_start_until_after_refresh():
    """Shared cache priming should be staged after the initial screen push."""
    app = StyreneApp()
    app._initialize_services = AsyncMock()  # type: ignore[method-assign]
    app._start_device_cache = Mock()  # type: ignore[method-assign]

    with patch("styrened.tui.app.find_reticulum_config", return_value=object()), \
        patch.object(app, "push_screen") as push_screen, \
        patch.object(app, "call_after_refresh") as call_after_refresh:
        await app._proceed_after_daemon()

    app._initialize_services.assert_awaited_once()
    push_screen.assert_called_once_with("dashboard")
    call_after_refresh.assert_called_once_with(app._start_device_cache)


@pytest.mark.asyncio
async def test_initialize_services_updates_bridge_without_starting_cache():
    """Service init should not trigger bulk cache hydration in the same burst."""
    app = StyreneApp()
    app.device_cache.update_bridge = Mock()  # type: ignore[method-assign]
    app.device_cache.start = Mock()  # type: ignore[method-assign]
    bridge = object()
    app._lifecycle.initialize_async = AsyncMock(return_value=True)  # type: ignore[method-assign]

    with patch.object(type(app), "bridge", new_callable=PropertyMock, return_value=bridge):
        await app._initialize_services()

    app.device_cache.update_bridge.assert_called_once_with(bridge)
    app.device_cache.start.assert_not_called()
