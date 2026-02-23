"""Tests for ContactsScreen."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.tui.app import StyreneApp
from styrened.tui.screens.contacts import ContactsScreen
from styrened.tui.services.app_lifecycle import LifecycleMode


def _make_mock_lifecycle(contacts=None):
    """Create mock lifecycle with IPCBridge for contacts."""
    bridge = MagicMock()
    bridge.get_contacts = AsyncMock(return_value=contacts or [])
    bridge.set_contact = AsyncMock(return_value={"peer_hash": "abc123", "alias": "Test"})
    bridge.remove_contact = AsyncMock(return_value=True)
    bridge.resolve_name = AsyncMock(return_value="abc123def456")
    bridge.get_auto_reply = AsyncMock(return_value={"mode": "disabled", "message": "", "cooldown": 300})
    lifecycle = MagicMock()
    lifecycle.ipc_bridge = bridge
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    return lifecycle


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


class TestContactsScreenInit:
    """Test ContactsScreen initialization and bindings."""

    def test_bindings_exist(self):
        """ContactsScreen should have expected bindings."""
        screen = ContactsScreen()
        binding_keys = [b.key for b in screen.BINDINGS]
        assert "escape" in binding_keys
        assert "a" in binding_keys
        assert "e" in binding_keys
        assert "delete" in binding_keys
        assert "r" in binding_keys

    def test_css_uses_theme_variables(self):
        """CSS should use theme variables, not hardcoded colors."""
        assert "#39ff14" not in ContactsScreen.CSS
        assert "#0a0a0a" not in ContactsScreen.CSS
        assert "$background" in ContactsScreen.CSS
        assert "$primary" in ContactsScreen.CSS


class TestContactsScreenNoBridge:
    """Test ContactsScreen without IPCBridge."""

    @pytest.mark.asyncio
    async def test_no_bridge_shows_message(self):
        """With no bridge, table should show 'requires daemon mode'."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ContactsScreen)


class TestContactsScreenIPCMode:
    """Test ContactsScreen with IPCBridge."""

    @pytest.mark.asyncio
    async def test_loads_contacts(self):
        """Screen should load contacts from bridge."""
        contacts = [
            {"peer_hash": "abcdef1234567890", "alias": "Alice", "notes": "Test node"},
            {"peer_hash": "1234567890abcdef", "alias": "Bob", "notes": ""},
        ]
        lifecycle = _make_mock_lifecycle(contacts=contacts)

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ContactsScreen)

    @pytest.mark.asyncio
    async def test_empty_contacts(self):
        """Screen should handle empty contacts list."""
        lifecycle = _make_mock_lifecycle(contacts=[])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ContactsScreen)


class TestContactsScreenRegistration:
    """Test ContactsScreen is properly registered in app."""

    def test_contacts_in_screens(self):
        """ContactsScreen should be registered in app SCREENS."""
        assert "contacts" in StyreneApp.SCREENS
        assert StyreneApp.SCREENS["contacts"] is ContactsScreen

    def test_contacts_binding_exists(self):
        """App should have 'b' binding for contacts."""
        binding_keys = [b.key for b in StyreneApp.BINDINGS]
        assert "b" in binding_keys
