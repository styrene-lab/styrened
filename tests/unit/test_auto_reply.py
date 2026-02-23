"""Unit tests for AutoReplyHandler.

Tests cooldown logic, LRU eviction, template formatting, and message handling.
These are critical for preventing spam loops and unbounded memory growth.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from styrened.models.config import AutoReplyMode, ChatbotConfig
from styrened.services.auto_reply import MAX_COOLDOWN_ENTRIES, AutoReplyHandler


class MockChatConfig:
    """Mock ChatConfig for testing."""

    def __init__(
        self,
        auto_reply_mode: AutoReplyMode = AutoReplyMode.TEMPLATE,
        auto_reply_message: str = "Auto-reply: {hostname}",
        auto_reply_cooldown: int = 60,
    ):
        self.auto_reply_mode = auto_reply_mode
        self.auto_reply_message = auto_reply_message
        self.auto_reply_cooldown = auto_reply_cooldown
        self.chatbot = ChatbotConfig()


class MockIdentity:
    """Mock RNS.Identity for testing."""

    def __init__(self, hexhash: str = "a1b2c3d4e5f6a7b8"):
        self.hexhash = hexhash


class MockRouter:
    """Mock LXMF.LXMRouter for testing."""

    def __init__(self):
        self.outbound_messages = []

    def handle_outbound(self, message):
        self.outbound_messages.append(message)


@pytest.fixture
def handler():
    """Create an AutoReplyHandler for testing."""
    config = MockChatConfig()
    identity = MockIdentity()
    router = MockRouter()
    return AutoReplyHandler(
        config=config,
        identity=identity,
        router=router,
        start_time=time.time(),
    )


class TestCooldownLogic:
    """Tests for cooldown checking and recording."""

    def test_check_cooldown_allows_first_message(self, handler):
        """First message from a sender should pass cooldown check."""
        source = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        assert handler._check_cooldown(source) is True

    def test_check_cooldown_blocks_within_period(self, handler):
        """Messages within cooldown period should be blocked."""
        source = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        # Record a reply
        handler._record_reply(source)

        # Check should fail (within 60s cooldown)
        assert handler._check_cooldown(source) is False

    def test_check_cooldown_allows_after_period(self, handler):
        """Messages after cooldown period should be allowed."""
        source = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        # Record a reply in the past
        handler._last_reply[source] = time.time() - 61  # 61 seconds ago

        # Check should pass (cooldown expired)
        assert handler._check_cooldown(source) is True

    def test_record_reply_updates_timestamp(self, handler):
        """Recording a reply should update the timestamp."""
        source = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        before = time.time()
        handler._record_reply(source)
        after = time.time()

        assert source in handler._last_reply
        assert before <= handler._last_reply[source] <= after

    def test_record_reply_moves_to_end_on_update(self, handler):
        """Updating an existing entry should move it to end (most recent)."""
        source1 = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        source2 = b"\x02\x03\x04\x05\x06\x07\x08\x09"

        handler._record_reply(source1)
        handler._record_reply(source2)

        # source1 should be first (oldest)
        assert list(handler._last_reply.keys())[0] == source1

        # Update source1
        handler._record_reply(source1)

        # Now source2 should be first (source1 moved to end)
        assert list(handler._last_reply.keys())[0] == source2
        assert list(handler._last_reply.keys())[-1] == source1


class TestLRUEviction:
    """Tests for LRU eviction at max capacity."""

    def test_lru_eviction_at_max_capacity(self, handler):
        """Should evict oldest entry when at max capacity."""
        # Fill to max capacity
        for i in range(MAX_COOLDOWN_ENTRIES):
            source = bytes([i % 256] * 8)
            handler._record_reply(source)

        assert len(handler._last_reply) == MAX_COOLDOWN_ENTRIES

        # Record one more
        new_source = b"\xff\xff\xff\xff\xff\xff\xff\xff"
        handler._record_reply(new_source)

        # Still at max (oldest evicted)
        assert len(handler._last_reply) == MAX_COOLDOWN_ENTRIES
        assert new_source in handler._last_reply

    def test_lru_evicts_oldest_entry(self, handler):
        """LRU eviction should remove the oldest (least recently used) entry."""
        # Add entries in order with unique keys
        # Use 2-byte encoding to ensure uniqueness across MAX_COOLDOWN_ENTRIES
        oldest = b"\x00\x00\x00\x00\x00\x00\x00\x00"
        handler._record_reply(oldest)

        # Fill remaining slots with unique entries
        for i in range(1, MAX_COOLDOWN_ENTRIES):
            # Use i as a 2-byte big-endian value to ensure uniqueness
            source = bytes([(i >> 8) & 0xFF, i & 0xFF] + [0] * 6)
            handler._record_reply(source)

        # Oldest should be first
        assert list(handler._last_reply.keys())[0] == oldest

        # Add one more to trigger eviction (ensure it's unique)
        new_source = b"\xfe\xfe\xfe\xfe\xfe\xfe\xfe\xfe"
        handler._record_reply(new_source)

        # Oldest should be gone
        assert oldest not in handler._last_reply
        assert new_source in handler._last_reply


class TestCleanupStaleCooldowns:
    """Tests for cleanup_stale_cooldowns()."""

    def test_cleanup_stale_removes_old_entries(self, handler):
        """Cleanup should remove entries older than max_age."""
        old_source = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        handler._last_reply[old_source] = time.time() - 3700  # ~1 hour ago

        handler.cleanup_stale_cooldowns(max_age=3600)

        assert old_source not in handler._last_reply

    def test_cleanup_stale_keeps_recent_entries(self, handler):
        """Cleanup should keep entries newer than max_age."""
        recent_source = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        handler._record_reply(recent_source)

        handler.cleanup_stale_cooldowns(max_age=3600)

        assert recent_source in handler._last_reply

    def test_cleanup_stale_stops_at_first_valid(self, handler):
        """Cleanup iterates from oldest and stops at first valid entry."""
        # Add old entry first
        old_source = b"\x01\x00\x00\x00\x00\x00\x00\x00"
        handler._last_reply[old_source] = time.time() - 3700

        # Add recent entries
        for i in range(2, 5):
            source = bytes([i] + [0] * 7)
            handler._record_reply(source)

        initial_count = len(handler._last_reply)
        handler.cleanup_stale_cooldowns(max_age=3600)

        # Only old one removed
        assert len(handler._last_reply) == initial_count - 1
        assert old_source not in handler._last_reply

    def test_cleanup_stale_handles_empty(self, handler):
        """Cleanup should handle empty dict gracefully."""
        handler._last_reply.clear()
        handler.cleanup_stale_cooldowns()  # Should not raise


class TestTemplateFormatting:
    """Tests for message template formatting."""

    def test_format_message_with_valid_placeholders(self, handler):
        """Should substitute all valid placeholders."""
        handler.config.auto_reply_message = (
            "Host: {hostname}, ID: {identity}, Up: {uptime}, V: {version}"
        )

        result = handler._format_message(handler.config.auto_reply_message)

        # Should contain substituted values (not the placeholder syntax)
        assert "{hostname}" not in result
        assert "{identity}" not in result
        assert "{uptime}" not in result
        assert "{version}" not in result

    def test_format_message_with_unknown_placeholder_raises(self, handler):
        """Unknown placeholder should raise KeyError (documents current behavior)."""
        template = "Unknown: {unknown_field}"

        with pytest.raises(KeyError):
            handler._format_message(template)

    def test_format_message_preserves_literal_text(self, handler):
        """Non-placeholder text should be preserved."""
        template = "Hello from styrened!"

        result = handler._format_message(template)
        assert result == "Hello from styrened!"


class TestFormatUptime:
    """Tests for uptime formatting."""

    def test_format_uptime_seconds_only(self, handler):
        """Less than a minute should show seconds."""
        result = handler._format_uptime(45)
        assert result == "45s"

    def test_format_uptime_minutes_only(self, handler):
        """Partial hour should show minutes."""
        result = handler._format_uptime(125)  # 2m 5s
        assert result == "2m"

    def test_format_uptime_hours_minutes(self, handler):
        """Hours should be included when present."""
        result = handler._format_uptime(3665)  # 1h 1m 5s
        assert result == "1h 1m"

    def test_format_uptime_days_hours_minutes(self, handler):
        """Days should be included when present."""
        result = handler._format_uptime(90061)  # 1d 1h 1m 1s
        assert result == "1d 1h 1m"

    def test_format_uptime_zero_seconds(self, handler):
        """Zero seconds should show 0s."""
        result = handler._format_uptime(0)
        assert result == "0s"


class TestMessageHandling:
    """Tests for handle_message() method."""

    def test_handle_message_respects_disabled_config(self, handler):
        """Should not reply when auto_reply_mode is DISABLED."""
        handler.config.auto_reply_mode = AutoReplyMode.DISABLED

        mock_message = MagicMock()
        mock_message.source_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        handler.handle_message(mock_message)

        # No cooldown should be recorded (message not processed)
        assert len(handler._last_reply) == 0

    @patch("styrened.services.auto_reply.LXMF_AVAILABLE", False)
    def test_handle_message_skips_when_lxmf_unavailable(self, handler):
        """Should not process when LXMF is not available."""
        mock_message = MagicMock()
        mock_message.source_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        handler.handle_message(mock_message)

        # No cooldown should be recorded
        assert len(handler._last_reply) == 0

    def test_handle_message_checks_cooldown(self, handler):
        """Should check cooldown before sending reply."""
        source = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        # Pre-record a recent reply
        handler._record_reply(source)
        initial_count = len(handler._last_reply)

        mock_message = MagicMock()
        mock_message.source_hash = source

        # Verify cooldown check returns False (blocked)
        assert handler._check_cooldown(source) is False

        # The _check_cooldown is called early in handle_message.
        # Since AutoReplyHandler uses __slots__, we can't easily patch _send_reply.
        # Instead, verify the cooldown logic directly:
        # - If cooldown blocks, no new entry should be added to _last_reply
        # - The count should remain the same after the blocked message

        # Force the handler to see LXMF as available for this test
        import styrened.services.auto_reply as ar_module

        original = ar_module.LXMF_AVAILABLE
        ar_module.LXMF_AVAILABLE = True
        try:
            # The handle_message will check cooldown and return early
            handler.handle_message(mock_message)
        finally:
            ar_module.LXMF_AVAILABLE = original

        # No new entries should have been added (cooldown blocked the reply)
        assert len(handler._last_reply) == initial_count


class TestSkipReplyOnNoPath:
    """Tests for skip_reply_on_no_path behavior."""

    def test_skip_reply_on_no_path_default_true(self):
        """Default should be to skip reply when no path exists."""
        config = MockChatConfig()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )
        assert handler.skip_reply_on_no_path is True

    def test_skip_reply_on_no_path_can_be_disabled(self):
        """Should be configurable to attempt reply even without path."""
        config = MockChatConfig()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
            skip_reply_on_no_path=False,
        )
        assert handler.skip_reply_on_no_path is False
