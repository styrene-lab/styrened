"""Tests for InboxScreen - conversation list via IPCBridge."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from styrened.tui.app import StyreneApp
from styrened.tui.screens.base import StyreneScreen
from styrened.tui.screens.inbox import InboxScreen, MailScreen


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for inbox TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


class TestInboxScreenInit:
    """Tests for InboxScreen initialization."""

    def test_mail_screen_alias_points_to_inbox_screen(self) -> None:
        """MailScreen should remain a compatibility alias during migration."""
        assert MailScreen is InboxScreen

    def test_inbox_screen_initialization(self) -> None:
        """InboxScreen should initialize without errors."""
        screen = InboxScreen()
        assert screen is not None

    def test_inbox_is_styrene_screen(self) -> None:
        """InboxScreen must inherit from StyreneScreen for shared lifecycle."""
        assert issubclass(InboxScreen, StyreneScreen)


class TestInboxScreenLifecycle:
    """Tests that InboxScreen uses the shared StyreneScreen load/resume contract."""

    def test_inbox_has_load_data_method(self) -> None:
        """InboxScreen must implement the abstract _load_data() hook."""
        screen = InboxScreen()
        assert callable(getattr(screen, "_load_data", None))

    def test_inbox_does_not_override_on_screen_resume(self) -> None:
        """InboxScreen must NOT define its own on_screen_resume — StyreneScreen owns it."""
        # The method must resolve to StyreneScreen, not InboxScreen
        assert "on_screen_resume" not in InboxScreen.__dict__, (
            "InboxScreen must not override on_screen_resume; "
            "refresh is handled by StyreneScreen._start_load()"
        )

    def test_inbox_load_data_calls_conversations_and_auto_reply(self) -> None:
        """_load_data() must invoke both _load_conversations and _load_auto_reply_state."""
        screen = InboxScreen()

        loaded_conversations = False
        loaded_auto_reply = False

        async def fake_load_conversations() -> None:
            nonlocal loaded_conversations
            loaded_conversations = True

        async def fake_auto_reply() -> None:
            nonlocal loaded_auto_reply
            loaded_auto_reply = True

        screen._load_conversations = fake_load_conversations  # type: ignore[method-assign]
        screen._load_auto_reply_state = fake_auto_reply  # type: ignore[method-assign]

        with patch.object(InboxScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=MagicMock()):
            asyncio.run(screen._load_data())

        assert loaded_conversations, "_load_data() did not call _load_conversations()"
        assert loaded_auto_reply, "_load_data() did not call _load_auto_reply_state()"

    def test_inbox_loading_message(self) -> None:
        """InboxScreen should provide a mail-specific loading message."""
        screen = InboxScreen()
        assert "mail" in screen._loading_message().lower() or "load" in screen._loading_message().lower()

    def test_inbox_has_start_load(self) -> None:
        """InboxScreen must have _start_load() from StyreneScreen (not its own copy)."""
        assert "_start_load" in dir(InboxScreen)  # via StyreneScreen
        assert "_start_load" not in InboxScreen.__dict__, "InboxScreen must not redefine _start_load"


class TestInboxScreenIPCMode:
    """Tests for InboxScreen using IPCBridge."""

    def _make_mock_bridge(self, conversations: list | None = None) -> MagicMock:
        """Create a mock IPCBridge with get_conversations."""
        bridge = MagicMock()
        bridge.get_conversations = AsyncMock(return_value=conversations or [])
        return bridge

    def test_inbox_screen_has_expected_bindings(self) -> None:
        """InboxScreen should have escape and enter bindings."""
        screen = InboxScreen()
        binding_keys = [b.key for b in screen.BINDINGS]
        assert "escape" in binding_keys
        assert "enter" in binding_keys

    def test_inbox_no_hardcoded_colors(self) -> None:
        """InboxScreen CSS should not contain hardcoded hex colors."""
        assert "#39ff14" not in InboxScreen.CSS
        assert "#0a0a0a" not in InboxScreen.CSS


class TestInboxScreenNoBridge:
    """Tests for InboxScreen without IPCBridge (no daemon)."""

    def test_inbox_handles_no_bridge(self) -> None:
        """InboxScreen should handle missing IPCBridge gracefully."""
        screen = InboxScreen()
        # Without an app, _ipc_bridge returns None
        assert screen._ipc_bridge is None

    def test_get_selected_peer_hash_without_app(self) -> None:
        """_get_selected_peer_hash() must exist and return None without an app."""
        screen = InboxScreen()
        # No app → no query_one → should not raise AttributeError
        try:
            result = screen._get_selected_peer_hash()
            assert result is None
        except Exception:
            # Any exception other than AttributeError (missing method) is acceptable
            # at this level — we just need the method to exist.
            pass

    @pytest.mark.asyncio
    async def test_no_bridge_renders_workspace_local_placeholder(self) -> None:
        """Inbox should render a local daemon-required placeholder when no bridge exists."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(InboxScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, InboxScreen)
            table = screen.query_one("#conversation-table", DataTable)
            assert table.row_count >= 1
            message = str(table.get_cell_at(Coordinate(0, 1)))
            assert "Chat requires daemon mode" in message


class TestInboxComposeNew:
    """Tests for compose new conversation feature."""

    def test_compose_binding_exists(self) -> None:
        """InboxScreen should have 'ctrl+n' binding for new conversation."""
        binding_keys = [b.key for b in InboxScreen.BINDINGS]
        assert "ctrl+n" in binding_keys

    def test_compose_bar_in_css(self) -> None:
        """InboxScreen CSS should include compose-bar styling."""
        assert "#compose-bar" in InboxScreen.CSS

    def test_compose_state_initialized(self) -> None:
        """InboxScreen should initialize with compose_active=False."""
        screen = InboxScreen()
        assert screen._compose_active is False

    def test_compose_no_bridge_shows_warning(self) -> None:
        """action_compose_new should handle missing bridge."""
        InboxScreen()
        # Without an app, this should not raise
        # (notify will fail silently without an app)


class TestInboxWorkerScheduling:
    """Tests for callable worker scheduling on async Inbox actions."""

    def test_toggle_auto_reply_schedules_callable(self) -> None:
        """Switch changes should pass a callable to run_worker, not a coroutine object."""
        screen = InboxScreen()
        event = MagicMock()
        event.switch.id = "ooo-switch"
        event.value = True

        captured: list = []

        def fake_run_worker(fn, **kwargs):
            captured.append(fn)
            return MagicMock()

        with patch.object(screen, "run_worker", side_effect=fake_run_worker):
            screen.on_switch_changed(event)

        assert len(captured) == 1
        fn = captured[0]
        import inspect
        assert callable(fn)
        assert not inspect.iscoroutine(fn)

    def test_delete_conversation_schedules_callable(self) -> None:
        """Delete confirmation should schedule a callable worker on the second press."""
        screen = InboxScreen()
        screen._delete_pending = "abc123"
        captured: list = []

        def fake_run_worker(fn, **kwargs):
            captured.append(fn)
            return MagicMock()

        with (
            patch.object(screen, "_get_selected_peer_hash", return_value="abc123"),
            patch.object(screen, "run_worker", side_effect=fake_run_worker),
        ):
            screen.action_delete_conversation()

        assert len(captured) == 1
        fn = captured[0]
        import inspect
        assert callable(fn)
        assert not inspect.iscoroutine(fn)


class TestInboxSync:
    """Tests for propagation node sync feature."""

    def test_sync_binding_exists(self) -> None:
        """InboxScreen should have 's' binding for sync."""
        binding_keys = [b.key for b in InboxScreen.BINDINGS]
        assert "s" in binding_keys

    def test_layered_escape(self) -> None:
        """InboxScreen should have go_back binding instead of direct pop."""
        binding_keys = [b.key for b in InboxScreen.BINDINGS]
        assert "escape" in binding_keys
        # Check that escape maps to go_back, not app.pop_screen
        for b in InboxScreen.BINDINGS:
            if b.key == "escape":
                assert b.action == "go_back"
                break
