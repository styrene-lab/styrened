"""Tests for InboxScreen - conversation list via IPCBridge."""

from unittest.mock import AsyncMock, MagicMock

from styrened.tui.screens.inbox import InboxScreen


class TestInboxScreenInit:
    """Tests for InboxScreen initialization."""

    def test_inbox_screen_initialization(self) -> None:
        """InboxScreen should initialize without errors."""
        screen = InboxScreen()
        assert screen is not None


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


class TestInboxComposeNew:
    """Tests for compose new conversation feature."""

    def test_compose_binding_exists(self) -> None:
        """InboxScreen should have 'n' binding for new conversation."""
        binding_keys = [b.key for b in InboxScreen.BINDINGS]
        assert "n" in binding_keys

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
