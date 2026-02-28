"""Tests for MessageBubble widget."""

from styrened.tui.widgets.message_bubble import STATUS_ICONS, MessageBubble


class TestMessageBubbleCreation:
    """Tests for MessageBubble initialization."""

    def test_outgoing_has_correct_classes(self):
        """Outgoing bubble should have --outgoing class."""
        bubble = MessageBubble("ME: test", message_id=1, is_outgoing=True, status="sent")
        assert bubble.has_class("message-bubble")
        assert bubble.has_class("--outgoing")
        assert not bubble.has_class("--incoming")

    def test_incoming_has_correct_classes(self):
        """Incoming bubble should have --incoming class."""
        bubble = MessageBubble("Peer: test", message_id=2, is_outgoing=False, status="read")
        assert bubble.has_class("message-bubble")
        assert bubble.has_class("--incoming")
        assert not bubble.has_class("--outgoing")

    def test_failed_has_failed_class(self):
        """Failed status should add --failed class."""
        bubble = MessageBubble("ME: oops", message_id=3, is_outgoing=True, status="failed")
        assert bubble.has_class("--failed")
        assert bubble.is_failed is True

    def test_non_failed_no_failed_class(self):
        """Non-failed status should not have --failed class."""
        bubble = MessageBubble("ME: hi", message_id=4, is_outgoing=True, status="delivered")
        assert not bubble.has_class("--failed")
        assert bubble.is_failed is False

    def test_metadata_fields(self):
        """All metadata fields should be stored correctly."""
        bubble = MessageBubble(
            "test",
            message_id=42,
            is_outgoing=True,
            status="delivered",
            lxmf_hash="abc123def456",
            reply_to_hash="789xyz",
            raw_content="test content",
            timestamp=1700000000.0,
            read_by_recipient=True,
        )
        assert bubble.message_id == 42
        assert bubble.is_outgoing is True
        assert bubble.status == "delivered"
        assert bubble.lxmf_hash == "abc123def456"
        assert bubble.reply_to_hash == "789xyz"
        assert bubble.raw_content == "test content"
        assert bubble.timestamp == 1700000000.0
        assert bubble.read_by_recipient is True

    def test_default_values(self):
        """Default values should be sensible."""
        bubble = MessageBubble("test")
        assert bubble.message_id == 0
        assert bubble.is_outgoing is False
        assert bubble.status == ""
        assert bubble.lxmf_hash is None
        assert bubble.reply_to_hash is None
        assert bubble.raw_content == ""
        assert bubble.timestamp == 0.0
        assert bubble.read_by_recipient is False


class TestMessageBubbleSelection:
    """Tests for selection behavior."""

    def test_initially_not_selected(self):
        """Bubble should start unselected."""
        bubble = MessageBubble("test", message_id=1)
        assert not bubble.is_selected

    def test_select_adds_class(self):
        """select() should add --selected class."""
        bubble = MessageBubble("test", message_id=1)
        bubble.select()
        assert bubble.is_selected
        assert bubble.has_class("--selected")

    def test_deselect_removes_class(self):
        """deselect() should remove --selected class."""
        bubble = MessageBubble("test", message_id=1)
        bubble.select()
        bubble.deselect()
        assert not bubble.is_selected
        assert not bubble.has_class("--selected")

    def test_multiple_select_idempotent(self):
        """Multiple select() calls should be idempotent."""
        bubble = MessageBubble("test", message_id=1)
        bubble.select()
        bubble.select()
        assert bubble.is_selected


class TestMessageBubbleStatusUpdate:
    """Tests for status updates."""

    def test_update_to_failed(self):
        """Updating to failed should add --failed class."""
        bubble = MessageBubble("test", message_id=1, status="pending")
        bubble.update_status("failed")
        assert bubble.status == "failed"
        assert bubble.is_failed
        assert bubble.has_class("--failed")

    def test_update_from_failed(self):
        """Updating from failed should remove --failed class."""
        bubble = MessageBubble("test", message_id=1, status="failed")
        bubble.update_status("delivered")
        assert bubble.status == "delivered"
        assert not bubble.is_failed
        assert not bubble.has_class("--failed")

    def test_update_between_non_failed(self):
        """Updating between non-failed statuses should work."""
        bubble = MessageBubble("test", message_id=1, status="pending")
        bubble.update_status("sent")
        assert bubble.status == "sent"
        assert not bubble.has_class("--failed")

        bubble.update_status("delivered")
        assert bubble.status == "delivered"


class TestIPCBridgeAccessor:
    """Tests for _ipc_bridge property encapsulation."""

    def test_ipc_bridge_returns_none_without_app(self):
        """_ipc_bridge should return None when not mounted in an app."""
        bubble = MessageBubble("test", message_id=1)
        assert bubble._ipc_bridge is None

    def test_ipc_bridge_returns_none_when_lifecycle_missing(self):
        """_ipc_bridge should return None when app has no _lifecycle."""
        from unittest.mock import MagicMock

        bubble = MessageBubble("test", message_id=1)
        # Mock app without _lifecycle attribute
        mock_app = MagicMock(spec=[])
        try:
            bubble._app = mock_app
        except Exception:
            pass
        # Should return None, not raise
        assert bubble._ipc_bridge is None

    def test_ipc_bridge_property_exists(self):
        """MessageBubble should have an _ipc_bridge property."""
        assert hasattr(MessageBubble, "_ipc_bridge")


class TestStatusIcons:
    """Tests for status icon constants."""

    def test_all_expected_statuses(self):
        """All expected status keys should exist."""
        expected = {"pending", "sent", "delivered", "failed", "read"}
        assert expected == set(STATUS_ICONS.keys())

    def test_pending_icon(self):
        assert STATUS_ICONS["pending"] == "\u23f3"

    def test_sent_icon(self):
        assert STATUS_ICONS["sent"] == "\u2713"

    def test_delivered_icon(self):
        assert STATUS_ICONS["delivered"] == "\u2713\u2713"

    def test_failed_icon(self):
        assert STATUS_ICONS["failed"] == "\u2717"

    def test_read_icon(self):
        assert STATUS_ICONS["read"] == "\u2713\u2713"
