"""Unit tests for AutoReplyHandler config accessor pattern.

Verifies that the handler uses a config accessor callable instead of a
direct reference, enabling hot-reload when the daemon config is replaced.
"""

import time
from unittest.mock import MagicMock

from styrened.models.config import AutoReplyMode, ChatbotConfig
from styrened.services.auto_reply import AutoReplyHandler


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
    """Mock RNS.Identity."""

    def __init__(self, hexhash: str = "a1b2c3d4e5f6a7b8"):
        self.hexhash = hexhash


class MockRouter:
    """Mock LXMF.LXMRouter."""

    def __init__(self):
        self.outbound_messages = []

    def handle_outbound(self, message):
        self.outbound_messages.append(message)


class TestConfigAccessorPattern:
    """Verify the handler sees live config through the accessor."""

    def test_handler_reflects_config_change(self):
        """Swapping the accessor return value should be visible to the handler."""
        config_a = MockChatConfig(auto_reply_mode=AutoReplyMode.TEMPLATE, auto_reply_cooldown=60)
        config_b = MockChatConfig(auto_reply_mode=AutoReplyMode.TEMPLATE, auto_reply_cooldown=120)

        current = {"cfg": config_a}

        handler = AutoReplyHandler(
            config_accessor=lambda: current["cfg"],
            identity=MockIdentity(),
            router=MockRouter(),
        )

        assert handler.config.auto_reply_cooldown == 60

        # Swap config (simulates daemon.config = load_core_config())
        current["cfg"] = config_b
        assert handler.config.auto_reply_cooldown == 120

    def test_handler_respects_toggled_enabled(self):
        """Disabling auto_reply_mode via config swap should suppress replies."""
        config = MockChatConfig(auto_reply_mode=AutoReplyMode.TEMPLATE)
        handler = AutoReplyHandler(
            config_accessor=lambda: config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        msg = MagicMock()
        msg.source_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        msg.fields = {}
        msg.content = b"hello"

        # Enabled: handler should proceed (cooldown check etc.)
        assert handler.config.auto_reply_mode == AutoReplyMode.TEMPLATE

        # Disable at runtime
        config.auto_reply_mode = AutoReplyMode.DISABLED
        assert handler.config.auto_reply_mode == AutoReplyMode.DISABLED

        # handle_message should return early without recording cooldown
        handler.handle_message(msg)
        assert len(handler._last_reply) == 0

    def test_handler_uses_updated_cooldown(self):
        """Changing cooldown via accessor should take effect immediately."""
        config = MockChatConfig(auto_reply_cooldown=60)
        handler = AutoReplyHandler(
            config_accessor=lambda: config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        source = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        # Record a reply 90 seconds ago
        handler._last_reply[source] = time.time() - 90

        # With 60s cooldown, should be allowed
        assert handler._check_cooldown(source) is True

        # Increase cooldown to 120s — same timestamp now blocked
        config.auto_reply_cooldown = 120
        assert handler._check_cooldown(source) is False

    def test_handler_uses_updated_message_template(self):
        """Changing the message template should affect formatted output."""
        config = MockChatConfig(auto_reply_message="old template")
        handler = AutoReplyHandler(
            config_accessor=lambda: config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        result_old = handler._format_message(handler.config.auto_reply_message)
        assert result_old == "old template"

        config.auto_reply_message = "new template"
        result_new = handler._format_message(handler.config.auto_reply_message)
        assert result_new == "new template"
