"""Tests for ActivityFeedWidget."""
from __future__ import annotations

import time

from styrened.tui.widgets.activity_feed import (
    _EVENT_CATEGORIES,
    _format_event,
    _summarize,
)
from styrened.tui.widgets.highlighted_panel import get_color_cascade


class TestFormatEvent:
    """Tests for _format_event formatting helper."""

    def test_format_event_includes_timestamp(self):
        """Formatted event includes HH:MM:SS timestamp."""
        ts = time.time()
        result = _format_event("new_message", {"timestamp": ts})
        expected_time = time.strftime("%H:%M:%S", time.localtime(ts))
        assert expected_time in result

    def test_format_event_includes_tag(self):
        """Formatted event includes category tag."""
        result = _format_event("new_message", {"timestamp": time.time()})
        assert "MSG" in result

    def test_format_event_uses_current_time_without_timestamp(self):
        """Formatted event uses current time when no timestamp in payload."""
        result = _format_event("announce_sent", {})
        # Should still produce a valid time format
        assert ":" in result  # HH:MM:SS has colons


class TestSummarize:
    """Tests for _summarize per-category summaries."""

    def _cascade(self):
        return get_color_cascade()

    def test_new_message_shows_peer_and_preview(self):
        """new_message summary shows peer hash and content preview."""
        result = _summarize(
            "new_message",
            {"peer_hash": "abcd1234", "content": "Hello world"},
            self._cascade(),
        )
        assert "abcd1234" in result
        assert "Hello world" in result

    def test_new_message_truncates_long_content(self):
        """new_message summary truncates content at 40 chars."""
        long_content = "A" * 60
        result = _summarize(
            "new_message",
            {"peer_hash": "abcd1234", "content": long_content},
            self._cascade(),
        )
        assert "..." in result

    def test_device_discovered_shows_name(self):
        """device_discovered summary shows device name."""
        result = _summarize(
            "device_discovered",
            {"name": "test-node", "device_type": "styrene_node"},
            self._cascade(),
        )
        assert "test-node" in result

    def test_announce_sent_summary(self):
        """announce_sent produces readable summary."""
        result = _summarize("announce_sent", {}, self._cascade())
        assert "announce" in result.lower()

    def test_rpc_received_shows_command(self):
        """rpc_received summary shows command name."""
        result = _summarize(
            "rpc_received",
            {"peer_hash": "deadbeef", "command": "STATUS_REQUEST"},
            self._cascade(),
        )
        assert "STATUS_REQUEST" in result

    def test_contact_set_shows_alias(self):
        """contact_set summary shows alias."""
        result = _summarize(
            "contact_set",
            {"peer_hash": "abcd1234", "alias": "Alice"},
            self._cascade(),
        )
        assert "Alice" in result

    def test_file_offer_received_shows_filename(self):
        """file_offer_received summary shows filename and size."""
        result = _summarize(
            "file_offer_received",
            {"peer_hash": "abcd1234", "filename": "photo.jpg", "size": 1024},
            self._cascade(),
        )
        assert "photo.jpg" in result
        assert "1024" in result

    def test_pqc_established_shows_tier(self):
        """pqc_established summary shows security tier."""
        result = _summarize(
            "pqc_established",
            {"peer_hash": "abcd1234", "security_tier": "pqc_hybrid"},
            self._cascade(),
        )
        assert "abcd1234" in result
        assert "pqc_hybrid" in result

    def test_pqc_rekey_shows_rekeyed(self):
        """pqc_rekey summary shows session rekeyed."""
        result = _summarize(
            "pqc_rekey",
            {"peer_hash": "abcd1234"},
            self._cascade(),
        )
        assert "abcd1234" in result
        assert "rekeyed" in result

    def test_unknown_event_type_handled(self):
        """Unknown event_type produces fallback summary."""
        result = _summarize("some_future_event", {}, self._cascade())
        assert "some_future_event" in result


class TestEventCategories:
    """Tests for event category mappings."""

    def test_all_expected_categories_present(self):
        """All planned event types have category mappings."""
        expected = [
            "new_message",
            "delivery_status",
            "device_discovered",
            "device_updated",
            "announce_sent",
            "rpc_received",
            "contact_set",
            "contact_removed",
            "identity_changed",
            "auto_reply_changed",
            "conversation_read",
            "conversation_deleted",
            "file_offer_received",
            "file_transfer_complete",
            "pqc_established",
            "pqc_rekey",
        ]
        for event_type in expected:
            assert event_type in _EVENT_CATEGORIES, f"Missing category for {event_type}"

    def test_categories_have_valid_color_keys(self):
        """All category color keys are valid cascade attributes."""
        cascade = get_color_cascade()
        for event_type, (_tag, color_key) in _EVENT_CATEGORIES.items():
            assert hasattr(cascade, color_key), (
                f"Invalid color key '{color_key}' for {event_type}"
            )
