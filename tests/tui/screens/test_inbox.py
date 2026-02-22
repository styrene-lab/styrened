"""Tests for InboxScreen - conversation list via IPCBridge."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

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
