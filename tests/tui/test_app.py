"""Tests for the main Styrene application."""
from __future__ import annotations


import pytest

from styrened import paths
from styrened.tui.app import StyreneApp


def test_app_instantiation():
    """Verify app can be instantiated."""
    app = StyreneApp()
    assert app.title == "STYRENE"
    assert app.sub_title == "Management"


@pytest.mark.asyncio
async def test_app_starts_with_dashboard(app: StyreneApp):
    """Verify app starts and shows dashboard screen."""
    async with app.run_test():
        # App should push dashboard on mount
        assert app.screen.__class__.__name__ in ("DashboardScreen", "DaemonSetupScreen")


@pytest.mark.asyncio
async def test_quit_binding(app: StyreneApp):
    """Verify double ctrl+c quits the app (single press pops to dashboard)."""
    async with app.run_test() as pilot:
        # First ctrl+c pops back to dashboard; second ctrl+c from dashboard exits
        await pilot.press("ctrl+c")
        await pilot.press("ctrl+c")
        # App should exit after double ctrl+c
        assert app._exit


# Integration tests for RNS initialization (Phase 6)


@pytest.mark.asyncio
async def test_app_initializes_reticulum_on_startup():
    """Verify app initializes Reticulum on mount.

    Service initialization (including operator identity creation) is deferred
    to on_mount(), not __init__. If RNS cannot fully initialize (e.g., no
    network interfaces), the identity file may not be created.
    """
    app = StyreneApp()

    async with app.run_test():
        # After mount, operator identity should exist if RNS initialized.
        # Skip assertion if RNS could not initialize (CI / offline environments).
        if not paths.identity_file().exists():
            pytest.skip(
                "Operator identity not created (RNS initialization likely failed; "
                "this is expected in environments without network interfaces)"
            )

        # Identity should be a valid hex string
        identity = paths.identity_file().read_bytes().hex()
        assert len(identity) > 0
        assert all(c in "0123456789abcdef" for c in identity)


def test_app_uses_existing_operator_identity():
    """Verify app reuses existing operator identity if present."""
    # Create a known identity
    test_identity = b"test_identity_123456789012345678"
    paths.identity_file().parent.mkdir(parents=True, exist_ok=True)
    paths.identity_file().write_bytes(test_identity)

    StyreneApp()

    # Identity should be unchanged
    assert paths.identity_file().read_bytes() == test_identity


def test_app_rns_initialization_graceful_failure():
    """Verify app handles RNS initialization failure gracefully."""
    # This test verifies that even if RNS fails to initialize,
    # the app still works (stub always returns False)
    app = StyreneApp()

    # App should still be functional
    assert app.title == "STYRENE"
    assert app.config is not None


@pytest.mark.asyncio
async def test_app_cleans_up_rns_on_shutdown():
    """Verify app cleans up RNS resources on shutdown."""
    from styrened.services.rns_service import get_rns_service

    app = StyreneApp()
    rns_service = get_rns_service()

    # Shutdown should be callable without error
    async with app.run_test():
        pass  # App runs

    # Explicitly call on_shutdown (Textual doesn't call it in tests)
    app.on_shutdown()

    # After shutdown, RNS should be cleaned up
    assert not rns_service.is_initialized
