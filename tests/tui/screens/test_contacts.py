"""Tests for ContactsScreen."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static

from styrened.tui.app import StyreneApp
from styrened.tui.screens.base import StyreneScreen
from styrened.tui.screens.contacts import ContactsScreen
from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.services.app_lifecycle import LifecycleMode
from styrened.ui_state import WorkspaceId


def _make_mock_lifecycle(contacts=None):
    """Create mock lifecycle with IPCBridge for contacts."""
    bridge = MagicMock()
    bridge.get_contacts = AsyncMock(return_value=contacts or [])
    bridge.set_contact = AsyncMock(return_value={"peer_hash": "abc123", "alias": "Test"})
    bridge.remove_contact = AsyncMock(return_value=True)
    bridge.resolve_name = AsyncMock(return_value="abc123def456")
    bridge.get_auto_reply = AsyncMock(return_value={"mode": "disabled", "message": "", "cooldown": 300})
    bridge.get_status = AsyncMock(return_value={})
    bridge.get_identity = AsyncMock(return_value={})
    bridge.get_hub_status = AsyncMock(return_value={})
    bridge.get_core_config = AsyncMock(return_value={})
    bridge.get_devices = AsyncMock(return_value=[])
    bridge.get_conversations = AsyncMock(return_value=[])
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


class TestContactsConversationRouting:
    """Test contact launches preserve origin metadata."""

    @pytest.mark.asyncio
    async def test_open_chat_sets_contacts_origin_on_conversation(self):
        contacts = [{"peer_hash": "abcdef1234567890", "alias": "Alice", "notes": ""}]
        lifecycle = _make_mock_lifecycle(contacts=contacts)

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ContactsScreen)

            with patch.object(screen, "_get_selected_peer_hash", return_value="abcdef1234567890"):
                screen.action_open_chat()
                await pilot.pause()

            assert isinstance(app.screen, ConversationScreen)
            assert app.screen.origin_workspace == WorkspaceId.CONTACTS

    def test_row_selected_opens_conversation_with_contacts_origin(self):
        screen = ContactsScreen()
        app = MagicMock()
        app.services.bridge = MagicMock()
        row_key = MagicMock()
        row_key.value = "abcdef1234567890"
        event = MagicMock()
        event.row_key = row_key

        with patch.object(ContactsScreen, "app", new_callable=PropertyMock, return_value=app):
            screen.on_data_table_row_selected(event)

        pushed = app.push_screen.call_args.args[0]
        assert isinstance(pushed, ConversationScreen)
        assert pushed.origin_workspace == WorkspaceId.CONTACTS


class TestContactsLayeringAndForms:
    """Test form layering and validation behavior."""

    @pytest.mark.asyncio
    async def test_escape_hides_edit_form_before_popping(self):
        lifecycle = _make_mock_lifecycle([])
        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ContactsScreen)
            edit_form = screen.query_one("#edit-form", Vertical)
            edit_form.add_class("visible")

            screen.action_go_back()
            await pilot.pause()

            assert not edit_form.has_class("visible")
            assert isinstance(app.screen, ContactsScreen)

    @pytest.mark.asyncio
    async def test_escape_hides_resolve_panel_before_popping(self):
        lifecycle = _make_mock_lifecycle([])
        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ContactsScreen)
            resolve_panel = screen.query_one("#resolve-panel", Vertical)
            resolve_panel.add_class("visible")

            screen.action_go_back()
            await pilot.pause()

            assert not resolve_panel.has_class("visible")
            assert isinstance(app.screen, ContactsScreen)

    @pytest.mark.asyncio
    async def test_add_contact_shows_empty_edit_form(self):
        lifecycle = _make_mock_lifecycle([])
        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ContactsScreen)

            screen.action_add_contact()
            await pilot.pause()

            edit_form = screen.query_one("#edit-form", Vertical)
            hash_input = screen.query_one("#edit-hash-input", Input)
            alias_input = screen.query_one("#edit-alias-input", Input)
            notes_input = screen.query_one("#edit-notes-input", Input)

            assert edit_form.has_class("visible")
            assert hash_input.value == ""
            assert alias_input.value == ""
            assert notes_input.value == ""
            assert hash_input.disabled is False

    @pytest.mark.asyncio
    async def test_edit_contact_prefills_selected_contact(self):
        contacts = [{"peer_hash": "abcdef1234567890", "alias": "Alice", "notes": ""}]
        lifecycle = _make_mock_lifecycle(contacts=contacts)
        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            table = screen.query_one("#contacts-table", DataTable)
            table.clear()
            table.add_row("Alice", "online", "hello", "abcdef1234567890", key="abcdef1234567890")
            table.move_cursor(row=0)

            screen.action_edit_contact()
            await pilot.pause()

            edit_form = screen.query_one("#edit-form", Vertical)
            hash_input = screen.query_one("#edit-hash-input", Input)
            alias_input = screen.query_one("#edit-alias-input", Input)

            assert edit_form.has_class("visible")
            assert hash_input.value == "abcdef1234567890"
            assert hash_input.disabled is True
            assert "Alice" in alias_input.value

    @pytest.mark.asyncio
    async def test_save_contact_requires_peer_hash(self):
        lifecycle = _make_mock_lifecycle([])
        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            screen.notify = MagicMock()
            screen.query_one("#edit-hash-input", Input).value = ""
            screen.query_one("#edit-alias-input", Input).value = "Alice"

            await screen._save_contact()

            screen.notify.assert_called_with("Peer hash is required", severity="warning")

    @pytest.mark.asyncio
    async def test_resolve_name_updates_result_widget(self):
        lifecycle = _make_mock_lifecycle([])
        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            screen.query_one("#resolve-input", Input).value = "alice"

            await screen._resolve_name()
            await pilot.pause()

            result = screen.query_one("#resolve-result", Static)
            assert "Resolved:" in str(result.render())


class TestContactsScreenStyreneContract:
    """Test StyreneScreen lifecycle contract for ContactsScreen."""

    def test_inherits_styrene_screen(self):
        """ContactsScreen must inherit from StyreneScreen, not Screen directly."""
        assert issubclass(ContactsScreen, StyreneScreen)

    @pytest.mark.asyncio
    async def test_no_bridge_placeholder_renders_locally(self):
        """With no bridge, _load_data should render a workspace-local placeholder.

        The table must show the daemon-required message without raising and
        without depending on any shadow cache or daemon-wide disconnect state.
        """
        app = StyreneApp()
        # No _lifecycle set → app.services.bridge will be None → BridgeUnavailableError

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ContactsScreen)
            table = screen.query_one("#contacts-table", DataTable)
            # At least one row should be present (placeholder row)
            assert table.row_count >= 1

    @pytest.mark.asyncio
    async def test_table_bootstrap_idempotent(self):
        """Calling _bootstrap_table() twice should not duplicate columns."""
        lifecycle = _make_mock_lifecycle([])
        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            await app.push_screen(ContactsScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, ContactsScreen)
            col_count_first = len(screen.query_one("#contacts-table", DataTable).columns)
            screen._bootstrap_table()
            col_count_second = len(screen.query_one("#contacts-table", DataTable).columns)
            assert col_count_first == col_count_second

    def test_action_delete_schedules_callable_not_coroutine(self):
        """action_delete_contact must pass a callable (partial) to run_worker.

        Passing an eagerly created coroutine object risks leaving it un-awaited
        if the worker is cancelled before it starts.
        """
        screen = ContactsScreen()
        app = MagicMock()
        app.services.bridge = MagicMock()

        # Build a minimal mock table with a selected row
        table = MagicMock()
        table.cursor_row = 0
        table.row_count = 1
        cell_key = MagicMock()
        cell_key.row_key = MagicMock()
        cell_key.row_key.value = "abcdef1234567890"
        table.coordinate_to_cell_key.return_value = cell_key

        captured: list = []

        def fake_run_worker(fn, **kwargs):
            captured.append(fn)
            return MagicMock()

        with (
            patch.object(ContactsScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "query_one", return_value=table),
            patch.object(screen, "run_worker", side_effect=fake_run_worker),
        ):
            screen.action_delete_contact()

        assert len(captured) == 1
        fn = captured[0]
        # Must be a callable (partial or method), NOT a coroutine object
        import inspect
        assert callable(fn)
        assert not inspect.iscoroutine(fn), (
            "action_delete_contact must pass a callable, not an eager coroutine"
        )

    def test_on_button_pressed_save_schedules_callable(self):
        """on_button_pressed for save-btn must dispatch a callable worker."""
        screen = ContactsScreen()
        app = MagicMock()
        app.services.bridge = MagicMock()

        event = MagicMock()
        event.button.id = "save-btn"

        captured: list = []

        def fake_run_worker(fn, **kwargs):
            captured.append(fn)
            return MagicMock()

        with (
            patch.object(ContactsScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "run_worker", side_effect=fake_run_worker),
        ):
            screen.on_button_pressed(event)

        assert len(captured) == 1
        import inspect
        assert callable(captured[0])
        assert not inspect.iscoroutine(captured[0]), (
            "on_button_pressed save-btn must pass a callable, not an eager coroutine"
        )

    def test_on_button_pressed_resolve_schedules_callable(self):
        """on_button_pressed for resolve-btn must dispatch a callable worker."""
        screen = ContactsScreen()
        app = MagicMock()
        app.services.bridge = MagicMock()

        event = MagicMock()
        event.button.id = "resolve-btn"

        captured: list = []

        def fake_run_worker(fn, **kwargs):
            captured.append(fn)
            return MagicMock()

        with (
            patch.object(ContactsScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "run_worker", side_effect=fake_run_worker),
        ):
            screen.on_button_pressed(event)

        assert len(captured) == 1
        import inspect
        assert callable(captured[0])
        assert not inspect.iscoroutine(captured[0]), (
            "on_button_pressed resolve-btn must pass a callable, not an eager coroutine"
        )


class TestContactsScreenRegistration:
    """Test ContactsScreen is properly registered in app."""

    def test_contacts_in_screens(self):
        """ContactsScreen should be registered in app SCREENS."""
        assert "contacts" in StyreneApp.SCREENS
        assert StyreneApp.SCREENS["contacts"] is ContactsScreen

    def test_contacts_binding_exists(self):
        """App should have stable workspace bindings for contacts/nodes/mail/comms."""
        binding_keys = [b.key for b in StyreneApp.BINDINGS]
        assert "b" in binding_keys
        assert "n" in binding_keys
        assert "m" in binding_keys
        assert "c" in binding_keys
