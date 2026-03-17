"""Tests for ConversationScreen - message thread display via ChatWidget."""
from __future__ import annotations

from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.widgets.chat_widget import STATUS_ICONS


class TestConversationScreenInit:
    """Tests for ConversationScreen initialization."""

    def test_conversation_screen_initialization(self) -> None:
        """ConversationScreen should initialize with peer_hash."""
        screen = ConversationScreen(peer_hash="alice_hash")
        assert screen.peer_hash == "alice_hash"
        assert screen.display_name is None

    def test_conversation_screen_with_display_name(self) -> None:
        """ConversationScreen should accept optional display_name."""
        screen = ConversationScreen(peer_hash="alice_hash", display_name="Alice")
        assert screen.peer_hash == "alice_hash"
        assert screen.display_name == "Alice"


class TestConversationScreenCSS:
    """Tests for ConversationScreen CSS theming."""

    def test_no_hardcoded_colors(self) -> None:
        """ConversationScreen CSS should not contain hardcoded hex colors."""
        assert "#39ff14" not in ConversationScreen.CSS
        assert "#0a0a0a" not in ConversationScreen.CSS


class TestStatusIcons:
    """Tests for delivery status indicators."""

    def test_all_statuses_have_icons(self) -> None:
        """All expected statuses should have icons."""
        expected = {"pending", "sent", "delivered", "failed", "read"}
        assert expected == set(STATUS_ICONS.keys())

    def test_pending_icon(self) -> None:
        """Pending should show hourglass."""
        assert STATUS_ICONS["pending"] == "\u23f3"

    def test_sent_icon(self) -> None:
        """Sent should show single check."""
        assert STATUS_ICONS["sent"] == "\u2713"

    def test_delivered_icon(self) -> None:
        """Delivered should show double check."""
        assert STATUS_ICONS["delivered"] == "\u2713\u2713"

    def test_failed_icon(self) -> None:
        """Failed should show cross."""
        assert STATUS_ICONS["failed"] == "\u2717"


class TestConversationPathInfo:
    """Tests for path info display in ConversationScreen."""

    def test_path_info_widget_in_css(self) -> None:
        """ConversationScreen CSS should include path info styling."""
        assert "#conv-path-info" in ConversationScreen.CSS

    def test_delete_binding_exists(self) -> None:
        """ConversationScreen should have ctrl+d binding for delete."""
        binding_keys = [b.key for b in ConversationScreen.BINDINGS]
        assert "ctrl+d" in binding_keys
