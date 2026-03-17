"""Tests for ConversationScreen lifecycle and message status management.

These tests verify:
- Mark messages as read when entering conversation (via ChatWidget)
- Message sending via ChatWidget's IPCBridge
- Proper screen navigation
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from styrened.tui.app import StyreneApp
from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.services.app_lifecycle import LifecycleMode
from styrened.tui.widgets.chat_widget import ChatWidget
from styrened.ui_state import PeerWorkspaceFocus, WorkspaceId


@pytest.fixture(autouse=True)
def mock_reticulum_for_tests(tmp_path):
    """Mock Reticulum initialization for all tests."""
    fake_config = tmp_path / "reticulum_config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


def _make_mock_lifecycle() -> MagicMock:
    """Create a mock lifecycle with IPCBridge."""
    bridge = MagicMock()
    bridge.get_messages = AsyncMock(return_value=[])
    bridge.mark_read = AsyncMock(return_value=3)
    bridge.send_chat = AsyncMock(return_value={"status": "sent"})
    bridge.get_conversations = AsyncMock(return_value=[])
    bridge.get_path_info = AsyncMock(return_value={"found": False})
    bridge.delete_conversation = AsyncMock(return_value=3)
    bridge.block_peer = AsyncMock(return_value=True)
    bridge.get_status = AsyncMock(return_value={})
    bridge.get_identity = AsyncMock(return_value={})
    bridge.get_hub_status = AsyncMock(return_value={})
    bridge.get_core_config = AsyncMock(return_value={})
    bridge.get_devices = AsyncMock(return_value=[])
    bridge.get_contacts = AsyncMock(return_value=[])
    bridge.get_auto_reply = AsyncMock(return_value={"mode": "disabled", "message": "", "cooldown": 300})

    lifecycle = MagicMock()
    lifecycle.ipc_bridge = bridge
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    return lifecycle


class TestConversationRoutingContext:
    """Tests for mail-thread compatibility routing context."""

    def test_conversation_defaults_to_mail_focus(self):
        conversation = ConversationScreen(
            peer_hash="peer_hash_xyz",
            origin_workspace="mail",
        )

        assert conversation.origin_workspace == WorkspaceId.MAIL
        assert conversation.requested_focus == PeerWorkspaceFocus.MAIL

    def test_conversation_defaults_origin_to_home_when_unspecified(self):
        conversation = ConversationScreen(peer_hash="peer_hash_xyz")

        assert conversation.origin_workspace == WorkspaceId.HOME
        assert conversation.requested_focus == PeerWorkspaceFocus.MAIL


class TestConversationMarkAsRead:
    """Tests for marking messages as read when entering conversation."""

    @pytest.mark.asyncio
    async def test_entering_conversation_calls_mark_read(self):
        """Opening ConversationScreen should call mark_read on IPCBridge via ChatWidget."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            conversation = ConversationScreen(peer_hash="a1b2c3d4e5f60708")
            await app.push_screen(conversation)
            await pilot.pause()

            lifecycle.ipc_bridge.mark_read.assert_called_with("a1b2c3d4e5f60708")


class TestConversationPathInfo:
    """Tests for path info header behavior."""

    @pytest.mark.asyncio
    async def test_load_path_info_renders_route_details(self):
        screen = ConversationScreen(peer_hash="peer_hash_xyz")
        bridge = MagicMock()
        bridge.get_path_info = AsyncMock(
            return_value={
                "found": True,
                "hops": 2,
                "interface_name": "tcp0",
                "bitrate": 125000,
            }
        )
        app = MagicMock()
        app.services.bridge = bridge
        path_widget = MagicMock()

        with (
            patch.object(ConversationScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "query_one", return_value=path_widget),
        ):
            await screen._load_path_info()

        path_widget.update.assert_called_once()
        rendered = path_widget.update.call_args.args[0]
        assert "2 hops" in rendered
        assert "via tcp0" in rendered
        assert "125 kbps" in rendered

    @pytest.mark.asyncio
    async def test_load_path_info_handles_missing_route(self):
        screen = ConversationScreen(peer_hash="peer_hash_xyz")
        bridge = MagicMock()
        bridge.get_path_info = AsyncMock(return_value={"found": False})
        app = MagicMock()
        app.services.bridge = bridge
        path_widget = MagicMock()

        with (
            patch.object(ConversationScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "query_one", return_value=path_widget),
        ):
            await screen._load_path_info()

        path_widget.update.assert_called_once_with("[dim]No path info available[/]")


class TestConversationDeleteAndBlock:
    """Tests for destructive conversation actions."""

    def test_delete_conversation_second_press_uses_worker(self):
        screen = ConversationScreen(peer_hash="peer_hash_xyz")
        screen._delete_conv_pending = True
        screen._cancel_delete_conv_timer = MagicMock()
        screen.run_worker = MagicMock()

        with patch.object(ConversationScreen, "_execute_delete_conversation", new=lambda self: None):
            screen.action_delete_conversation()

        screen._cancel_delete_conv_timer.assert_called_once_with()
        screen.run_worker.assert_called_once()

    def test_block_peer_second_press_uses_worker(self):
        screen = ConversationScreen(peer_hash="peer_hash_xyz")
        screen._block_confirm_time = 9999999999
        screen.run_worker = MagicMock()

        with patch("time.time", return_value=9999999999.5), patch.object(
            ConversationScreen, "_execute_block_peer", new=lambda self: None
        ):
            screen.action_block_peer()

        screen.run_worker.assert_called_once()


class TestConversationNavigation:
    """Tests for conversation screen navigation."""

    @pytest.mark.asyncio
    async def test_escape_returns_to_previous_screen(self):
        """Pressing escape in ConversationScreen should return to previous screen."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            initial_screen_type = type(app.screen).__name__

            conversation = ConversationScreen(peer_hash="a1b2c3d4e5f60708")
            await app.push_screen(conversation)
            await pilot.pause()

            assert isinstance(app.screen, ConversationScreen)

            await pilot.press("escape")
            await pilot.pause()

            assert type(app.screen).__name__ == initial_screen_type

    @pytest.mark.asyncio
    async def test_conversation_displays_peer_identity_in_title(self):
        """ConversationScreen should display peer identity in title."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            conversation = ConversationScreen(peer_hash="peer_node_identity_hash")
            await app.push_screen(conversation)
            await pilot.pause()

            from textual.widgets import Static

            title_widget = app.screen.query_one("#conv-title", Static)
            title_text = str(title_widget.render())
            assert "peer_node_id" in title_text, (
                f"Peer identity should appear in title. Got: {title_text}"
            )


class TestConversationMessageSending:
    """Tests for sending messages from conversation screen."""

    @pytest.mark.asyncio
    async def test_send_message_calls_bridge(self):
        """Sending a message should call send_chat on IPCBridge via ChatWidget."""
        lifecycle = _make_mock_lifecycle()

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            conversation = ConversationScreen(peer_hash="a1b2c3d4e5f60708")
            await app.push_screen(conversation)
            await pilot.pause()

            chat_widget = conversation.query_one(ChatWidget)
            await chat_widget._send_message("Hello!")
            await pilot.pause()

            lifecycle.ipc_bridge.send_chat.assert_called_with("a1b2c3d4e5f60708", "Hello!")
