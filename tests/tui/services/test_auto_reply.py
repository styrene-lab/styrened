"""Tests for auto-reply handler.

These tests verify:
- Message handling triggers auto-reply when enabled
- Cooldown prevents spam to same sender
- LRU eviction caps memory usage
- Message formatting with placeholders
- Disabled state prevents replies
- Error handling when identity recall fails
"""

import time
from unittest.mock import Mock, patch

import pytest

from styrened.services.auto_reply import MAX_COOLDOWN_ENTRIES, AutoReplyHandler
from styrened.tui.models.config import ChatConfig


@pytest.fixture
def chat_config() -> ChatConfig:
    """Provide default chat config with auto-reply enabled."""
    return ChatConfig(
        enabled=True,
        auto_reply_enabled=True,
        auto_reply_message="Test reply from {hostname}",
        auto_reply_cooldown=300,
    )


@pytest.fixture
def mock_identity() -> Mock:
    """Provide mock RNS identity."""
    identity = Mock()
    identity.hexhash = "a1b2c3d4e5f67890abcdef1234567890"
    return identity


@pytest.fixture
def mock_router() -> Mock:
    """Provide mock LXMF router."""
    return Mock()


@pytest.fixture
def handler(
    chat_config: ChatConfig, mock_identity: Mock, mock_router: Mock
) -> AutoReplyHandler:
    """Provide initialized AutoReplyHandler."""
    return AutoReplyHandler(
        config=chat_config,
        identity=mock_identity,
        router=mock_router,
        start_time=time.time(),
    )


class TestAutoReplyHandlerInit:
    """Tests for handler initialization."""

    def test_init_stores_config(
        self, chat_config: ChatConfig, mock_identity: Mock, mock_router: Mock
    ) -> None:
        """Test handler stores config reference."""
        handler = AutoReplyHandler(chat_config, mock_identity, mock_router)
        assert handler.config is chat_config

    def test_init_empty_cooldown_cache(
        self, chat_config: ChatConfig, mock_identity: Mock, mock_router: Mock
    ) -> None:
        """Test handler starts with empty cooldown cache."""
        handler = AutoReplyHandler(chat_config, mock_identity, mock_router)
        assert len(handler._last_reply) == 0

    def test_init_uses_provided_start_time(
        self, chat_config: ChatConfig, mock_identity: Mock, mock_router: Mock
    ) -> None:
        """Test handler uses provided start time for uptime calculation."""
        start_time = 1000.0
        handler = AutoReplyHandler(
            chat_config, mock_identity, mock_router, start_time=start_time
        )
        assert handler._start_time == start_time

    def test_init_defaults_start_time_to_now(
        self, chat_config: ChatConfig, mock_identity: Mock, mock_router: Mock
    ) -> None:
        """Test handler defaults start time to current time."""
        before = time.time()
        handler = AutoReplyHandler(chat_config, mock_identity, mock_router)
        after = time.time()
        assert before <= handler._start_time <= after


class TestAutoReplyHandlerDisabled:
    """Tests for disabled auto-reply state."""

    def test_disabled_config_skips_reply(
        self, mock_identity: Mock, mock_router: Mock
    ) -> None:
        """Test disabled auto-reply doesn't send messages."""
        config = ChatConfig(auto_reply_enabled=False)
        handler = AutoReplyHandler(config, mock_identity, mock_router)

        message = Mock()
        message.source_hash = bytes.fromhex("a1b2c3d4e5f67890")
        message.content = b"Hello"
        message.fields = None

        handler.handle_message(message)

        mock_router.handle_outbound.assert_not_called()


class TestAutoReplyHandlerCooldown:
    """Tests for cooldown logic."""

    def test_first_message_passes_cooldown(self, handler: AutoReplyHandler) -> None:
        """Test first message from sender passes cooldown check."""
        source_hash = bytes.fromhex("a1b2c3d4e5f67890")
        assert handler._check_cooldown(source_hash) is True

    def test_immediate_second_message_blocked(self, handler: AutoReplyHandler) -> None:
        """Test immediate second message from same sender is blocked."""
        source_hash = bytes.fromhex("a1b2c3d4e5f67890")

        # Record a reply
        handler._record_reply(source_hash)

        # Immediate check should fail
        assert handler._check_cooldown(source_hash) is False

    def test_message_after_cooldown_passes(self, handler: AutoReplyHandler) -> None:
        """Test message after cooldown period passes."""
        source_hash = bytes.fromhex("a1b2c3d4e5f67890")

        # Record a reply in the past
        handler._last_reply[source_hash] = (
            time.time() - 400
        )  # 400s ago, cooldown is 300s

        assert handler._check_cooldown(source_hash) is True

    def test_different_senders_independent(self, handler: AutoReplyHandler) -> None:
        """Test different senders have independent cooldowns."""
        sender1 = bytes.fromhex("a1b2c3d4e5f67890")
        sender2 = bytes.fromhex("1234567890abcdef")

        # Record reply to sender1
        handler._record_reply(sender1)

        # Sender2 should still pass
        assert handler._check_cooldown(sender2) is True


class TestAutoReplyHandlerLRUEviction:
    """Tests for LRU cache eviction."""

    def test_lru_eviction_at_capacity(
        self, chat_config: ChatConfig, mock_identity: Mock, mock_router: Mock
    ) -> None:
        """Test oldest entry evicted when cache reaches capacity."""
        handler = AutoReplyHandler(chat_config, mock_identity, mock_router)

        # Fill cache to capacity with unique keys
        # Use 2-byte prefix to ensure uniqueness for 256 entries
        for i in range(MAX_COOLDOWN_ENTRIES):
            source = bytes([i >> 8, i & 0xFF]) + bytes(6)
            handler._record_reply(source)

        assert len(handler._last_reply) == MAX_COOLDOWN_ENTRIES

        # Record one more - should evict oldest
        new_source = bytes([0xFF, 0xFF]) + bytes(6)  # Unique key not in cache
        handler._record_reply(new_source)

        assert len(handler._last_reply) == MAX_COOLDOWN_ENTRIES
        assert new_source in handler._last_reply

        # First entry should be evicted
        first_source = bytes([0, 0]) + bytes(6)
        assert first_source not in handler._last_reply

    def test_existing_entry_moves_to_end(self, handler: AutoReplyHandler) -> None:
        """Test updating existing entry moves it to end (most recent)."""
        source1 = bytes.fromhex("a1b2c3d4e5f67890")
        source2 = bytes.fromhex("1234567890abcdef")

        handler._record_reply(source1)
        handler._record_reply(source2)
        handler._record_reply(source1)  # Update source1

        # source1 should now be at the end
        keys = list(handler._last_reply.keys())
        assert keys[-1] == source1


class TestAutoReplyHandlerMessageFormatting:
    """Tests for message placeholder formatting."""

    def test_hostname_placeholder(self, handler: AutoReplyHandler) -> None:
        """Test {hostname} placeholder is replaced."""
        with patch("socket.gethostname", return_value="test-node"):
            result = handler._format_message("Node: {hostname}")
            assert result == "Node: test-node"

    def test_identity_placeholder(self, handler: AutoReplyHandler) -> None:
        """Test {identity} placeholder shows first 16 chars."""
        result = handler._format_message("ID: {identity}")
        assert result == "ID: a1b2c3d4e5f67890"

    def test_version_placeholder(self, handler: AutoReplyHandler) -> None:
        """Test {version} placeholder is replaced."""
        with patch("styrened.services.auto_reply.get_version", return_value="1.2.3"):
            result = handler._format_message("v{version}")
            assert result == "v1.2.3"

    def test_uptime_placeholder_seconds(
        self, chat_config: ChatConfig, mock_identity: Mock, mock_router: Mock
    ) -> None:
        """Test {uptime} shows seconds for short uptime."""
        handler = AutoReplyHandler(
            chat_config, mock_identity, mock_router, start_time=time.time() - 45
        )
        result = handler._format_message("Up: {uptime}")
        assert result == "Up: 45s"

    def test_uptime_placeholder_minutes(
        self, chat_config: ChatConfig, mock_identity: Mock, mock_router: Mock
    ) -> None:
        """Test {uptime} shows minutes for medium uptime."""
        handler = AutoReplyHandler(
            chat_config,
            mock_identity,
            mock_router,
            start_time=time.time() - 3660,  # 61 minutes
        )
        result = handler._format_message("Up: {uptime}")
        assert result == "Up: 1h 1m"

    def test_uptime_placeholder_days(
        self, chat_config: ChatConfig, mock_identity: Mock, mock_router: Mock
    ) -> None:
        """Test {uptime} shows days for long uptime."""
        handler = AutoReplyHandler(
            chat_config,
            mock_identity,
            mock_router,
            start_time=time.time() - 90000,  # ~1 day
        )
        result = handler._format_message("Up: {uptime}")
        assert result == "Up: 1d 1h"

    def test_multiple_placeholders(self, handler: AutoReplyHandler) -> None:
        """Test multiple placeholders in same message."""
        with patch("socket.gethostname", return_value="myhost"):
            result = handler._format_message("{hostname} ({identity})")
            assert result == "myhost (a1b2c3d4e5f67890)"


class TestAutoReplyHandlerSendReply:
    """Tests for sending reply messages."""

    @patch("styrened.services.auto_reply.RNS")
    @patch("styrened.services.auto_reply.LXMF")
    def test_send_reply_creates_lxmf_message(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        handler: AutoReplyHandler,
    ) -> None:
        """Test _send_reply creates and sends LXMF message."""
        dest_hash = bytes.fromhex("1234567890abcdef")

        # Mock identity recall
        mock_dest_identity = Mock()
        mock_rns.Identity.recall.return_value = mock_dest_identity
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1

        mock_message = Mock()
        mock_lxmf.LXMessage.return_value = mock_message
        mock_lxmf.APP_NAME = "lxmf"

        handler._send_reply(dest_hash)

        # Verify message was created and sent
        mock_lxmf.LXMessage.assert_called_once()
        handler._router.handle_outbound.assert_called_once_with(mock_message)

    @patch("styrened.services.auto_reply.RNS")
    def test_send_reply_skips_unknown_identity(
        self, mock_rns: Mock, handler: AutoReplyHandler
    ) -> None:
        """Test _send_reply skips when identity not known."""
        dest_hash = bytes.fromhex("1234567890abcdef")

        # Identity not known
        mock_rns.Identity.recall.return_value = None

        handler._send_reply(dest_hash)

        # Should not attempt to send
        handler._router.handle_outbound.assert_not_called()

    @patch("styrened.services.auto_reply.RNS")
    @patch("styrened.services.auto_reply.LXMF")
    def test_send_reply_records_cooldown(
        self, mock_lxmf: Mock, mock_rns: Mock, handler: AutoReplyHandler
    ) -> None:
        """Test _send_reply records timestamp for cooldown."""
        dest_hash = bytes.fromhex("1234567890abcdef")

        mock_rns.Identity.recall.return_value = Mock()
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1
        mock_lxmf.APP_NAME = "lxmf"

        handler._send_reply(dest_hash)

        assert dest_hash in handler._last_reply


class TestAutoReplyHandlerHandleMessage:
    """Tests for full message handling flow."""

    @patch("styrened.services.auto_reply.RNS")
    @patch("styrened.services.auto_reply.LXMF")
    def test_handle_message_sends_reply(
        self, mock_lxmf: Mock, mock_rns: Mock, handler: AutoReplyHandler
    ) -> None:
        """Test handle_message sends auto-reply for valid message."""
        mock_rns.Identity.recall.return_value = Mock()
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1
        mock_rns.Transport.has_path.return_value = True
        mock_lxmf.APP_NAME = "lxmf"

        message = Mock()
        message.source_hash = bytes.fromhex("1234567890abcdef")
        message.content = b"Hello there"
        message.fields = None

        handler.handle_message(message)

        handler._router.handle_outbound.assert_called_once()

    @patch("styrened.services.auto_reply.RNS")
    @patch("styrened.services.auto_reply.LXMF")
    def test_handle_message_respects_cooldown(
        self, mock_lxmf: Mock, mock_rns: Mock, handler: AutoReplyHandler
    ) -> None:
        """Test handle_message respects cooldown for same sender."""
        mock_rns.Identity.recall.return_value = Mock()
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1
        mock_rns.Transport.has_path.return_value = True
        mock_lxmf.APP_NAME = "lxmf"

        message = Mock()
        message.source_hash = bytes.fromhex("1234567890abcdef")
        message.content = b"Hello"
        message.fields = None

        # First message - should reply
        handler.handle_message(message)
        assert handler._router.handle_outbound.call_count == 1

        # Second message immediately - should skip
        handler.handle_message(message)
        assert handler._router.handle_outbound.call_count == 1  # Still 1

    def test_handle_message_error_does_not_propagate(
        self, handler: AutoReplyHandler
    ) -> None:
        """Test errors in handle_message don't propagate."""
        message = Mock()
        message.source_hash = None  # Will cause error
        message.fields = None

        # Should not raise
        handler.handle_message(message)


class TestAutoReplyHandlerPathHandling:
    """Tests for path validation before sending replies."""

    @patch("styrened.services.auto_reply.RNS")
    @patch("styrened.services.auto_reply.LXMF")
    def test_skips_reply_when_no_path_to_sender(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        chat_config: ChatConfig,
        mock_identity: Mock,
        mock_router: Mock,
    ) -> None:
        """Test auto-reply is skipped when no path to sender exists."""
        handler = AutoReplyHandler(
            chat_config, mock_identity, mock_router, skip_reply_on_no_path=True
        )
        mock_rns.Transport.has_path.return_value = False

        message = Mock()
        message.source_hash = bytes.fromhex("1234567890abcdef")
        message.content = b"Hello"
        message.fields = None

        handler.handle_message(message)

        # Should not attempt to send
        mock_router.handle_outbound.assert_not_called()
        # Should check path
        mock_rns.Transport.has_path.assert_called_once_with(message.source_hash)

    @patch("styrened.services.auto_reply.RNS")
    @patch("styrened.services.auto_reply.LXMF")
    def test_sends_reply_when_path_exists(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        chat_config: ChatConfig,
        mock_identity: Mock,
        mock_router: Mock,
    ) -> None:
        """Test auto-reply is sent when path to sender exists."""
        handler = AutoReplyHandler(
            chat_config, mock_identity, mock_router, skip_reply_on_no_path=True
        )
        mock_rns.Transport.has_path.return_value = True
        mock_rns.Identity.recall.return_value = Mock()
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1
        mock_lxmf.APP_NAME = "lxmf"

        message = Mock()
        message.source_hash = bytes.fromhex("1234567890abcdef")
        message.content = b"Hello"
        message.fields = None

        handler.handle_message(message)

        # Should send reply
        mock_router.handle_outbound.assert_called_once()

    @patch("styrened.services.auto_reply.RNS")
    @patch("styrened.services.auto_reply.LXMF")
    def test_logs_warning_when_path_missing(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        chat_config: ChatConfig,
        mock_identity: Mock,
        mock_router: Mock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test appropriate warning is logged when path is missing."""
        handler = AutoReplyHandler(
            chat_config, mock_identity, mock_router, skip_reply_on_no_path=True
        )
        mock_rns.Transport.has_path.return_value = False

        message = Mock()
        message.source_hash = bytes.fromhex("1234567890abcdef")
        message.content = b"Hello"
        message.fields = None

        import logging

        with caplog.at_level(logging.WARNING):
            handler.handle_message(message)

        assert "No path to sender 1234567890abcdef..." in caplog.text
        assert "skipping auto-reply" in caplog.text

    @patch("styrened.services.auto_reply.RNS")
    @patch("styrened.services.auto_reply.LXMF")
    def test_skip_path_check_when_disabled(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        chat_config: ChatConfig,
        mock_identity: Mock,
        mock_router: Mock,
    ) -> None:
        """Test path check is skipped when skip_reply_on_no_path is False."""
        handler = AutoReplyHandler(
            chat_config, mock_identity, mock_router, skip_reply_on_no_path=False
        )
        mock_rns.Identity.recall.return_value = Mock()
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1
        mock_lxmf.APP_NAME = "lxmf"

        message = Mock()
        message.source_hash = bytes.fromhex("1234567890abcdef")
        message.content = b"Hello"
        message.fields = None

        handler.handle_message(message)

        # Should not check path
        mock_rns.Transport.has_path.assert_not_called()
        # Should still send reply
        mock_router.handle_outbound.assert_called_once()

    def test_skip_reply_on_no_path_defaults_to_true(
        self,
        chat_config: ChatConfig,
        mock_identity: Mock,
        mock_router: Mock,
    ) -> None:
        """Test skip_reply_on_no_path defaults to True."""
        handler = AutoReplyHandler(chat_config, mock_identity, mock_router)
        assert handler.skip_reply_on_no_path is True


class TestAutoReplyHandlerCleanup:
    """Tests for stale cooldown cleanup."""

    def test_cleanup_removes_stale_entries(self, handler: AutoReplyHandler) -> None:
        """Test cleanup_stale_cooldowns removes old entries."""
        old_source = bytes.fromhex("a1b2c3d4e5f67890")
        new_source = bytes.fromhex("1234567890abcdef")

        # Add old entry (2 hours ago)
        handler._last_reply[old_source] = time.time() - 7200

        # Add new entry
        handler._record_reply(new_source)

        # Cleanup with 1 hour max age
        handler.cleanup_stale_cooldowns(max_age=3600)

        assert old_source not in handler._last_reply
        assert new_source in handler._last_reply

    def test_cleanup_on_empty_cache(self, handler: AutoReplyHandler) -> None:
        """Test cleanup on empty cache doesn't error."""
        handler.cleanup_stale_cooldowns()
        assert len(handler._last_reply) == 0

    def test_cleanup_preserves_recent_entries(self, handler: AutoReplyHandler) -> None:
        """Test cleanup preserves entries within max_age."""
        source = bytes.fromhex("a1b2c3d4e5f67890")
        handler._record_reply(source)

        handler.cleanup_stale_cooldowns(max_age=3600)

        assert source in handler._last_reply
