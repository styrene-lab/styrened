"""Unit tests for chatbot mode in AutoReplyHandler.

Tests the LLM-backed chatbot features: HTTP calls, message building,
bot-to-bot prevention, persistence, and broadcasting.
"""
from __future__ import annotations


import json
import os
from unittest.mock import MagicMock, patch

import pytest

from styrened.models.config import AutoReplyMode, ChatbotConfig
from styrened.services.auto_reply import AutoReplyHandler, _call_chat_completions


class MockChatConfig:
    """Mock ChatConfig for chatbot testing."""

    def __init__(
        self,
        auto_reply_mode: AutoReplyMode = AutoReplyMode.CHATBOT,
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


# ---------------------------------------------------------------------------
# _call_chat_completions tests
# ---------------------------------------------------------------------------


class TestCallChatCompletions:
    """Tests for the _call_chat_completions module-level function."""

    def test_success(self):
        """Should extract content from a valid response."""
        response_body = json.dumps({
            "choices": [{"message": {"content": "Hello, world!"}}]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _call_chat_completions(
                "http://localhost:11434/v1",
                "llama3",
                [{"role": "user", "content": "hi"}],
            )

        assert result == "Hello, world!"

    def test_http_error_returns_empty(self):
        """Should return empty string on HTTP error."""
        import urllib.error

        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                "http://localhost", 500, "Internal Error", {}, None
            ),
        ):
            result = _call_chat_completions(
                "http://localhost:11434/v1",
                "llama3",
                [{"role": "user", "content": "hi"}],
            )

        assert result == ""

    def test_timeout_returns_empty(self):
        """Should return empty string on timeout."""
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            result = _call_chat_completions(
                "http://localhost:11434/v1",
                "llama3",
                [{"role": "user", "content": "hi"}],
            )

        assert result == ""

    def test_auth_header_set_when_key_provided(self):
        """Should set Authorization header when api_key is non-empty."""
        response_body = json.dumps({
            "choices": [{"message": {"content": "ok"}}]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            _call_chat_completions(
                "http://localhost:11434/v1",
                "llama3",
                [{"role": "user", "content": "hi"}],
                api_key="sk-test-key",
            )

        req = mock_urlopen.call_args[0][0]
        assert req.get_header("Authorization") == "Bearer sk-test-key"

    def test_no_auth_header_when_key_empty(self):
        """Should not set Authorization header when api_key is empty."""
        response_body = json.dumps({
            "choices": [{"message": {"content": "ok"}}]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            _call_chat_completions(
                "http://localhost:11434/v1",
                "llama3",
                [{"role": "user", "content": "hi"}],
                api_key="",
            )

        req = mock_urlopen.call_args[0][0]
        assert not req.has_header("Authorization")

    def test_empty_choices_returns_empty(self):
        """Should return empty string when choices array is empty."""
        response_body = json.dumps({"choices": []}).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _call_chat_completions(
                "http://localhost:11434/v1",
                "llama3",
                [{"role": "user", "content": "hi"}],
            )

        assert result == ""

    def test_url_construction_strips_trailing_slash(self):
        """Should construct correct URL even if endpoint has trailing slash."""
        response_body = json.dumps({
            "choices": [{"message": {"content": "ok"}}]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = response_body
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            _call_chat_completions(
                "http://localhost:11434/v1/",
                "llama3",
                [{"role": "user", "content": "hi"}],
            )

        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "http://localhost:11434/v1/chat/completions"


# ---------------------------------------------------------------------------
# _build_llm_messages tests
# ---------------------------------------------------------------------------


class TestBuildLlmMessages:
    """Tests for _build_llm_messages conversation history building."""

    def test_with_history(self):
        """Should include system prompt + conversation history."""
        config = MockChatConfig()
        mock_conv_service = MagicMock()

        # Simulate conversation history (oldest-first, as get_messages returns)
        msg1 = MagicMock()
        msg1.is_outgoing = False
        msg1.content = "Hello"
        msg2 = MagicMock()
        msg2.is_outgoing = True
        msg2.content = "Hi there"
        mock_conv_service.get_messages.return_value = [msg1, msg2]  # oldest first

        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
            conversation_service=mock_conv_service,
        )

        messages = handler._build_llm_messages("abcdef1234567890")

        assert messages[0]["role"] == "system"
        # Chronological order (oldest first)
        assert messages[1] == {"role": "user", "content": "Hello"}
        assert messages[2] == {"role": "assistant", "content": "Hi there"}

    def test_without_conversation_service(self):
        """Should return just system prompt when no conversation service."""
        config = MockChatConfig()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        messages = handler._build_llm_messages("abcdef1234567890")

        assert len(messages) == 1
        assert messages[0]["role"] == "system"

    def test_formats_system_prompt_placeholders(self):
        """Should substitute {hostname} etc. in system prompt."""
        config = MockChatConfig()
        config.chatbot.system_prompt = "You are on {hostname}"
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        with patch("socket.gethostname", return_value="test-node"):
            messages = handler._build_llm_messages("abcdef1234567890")

        assert messages[0]["content"] == "You are on test-node"

    def test_respects_max_context_messages(self):
        """Should pass max_context_messages limit to get_messages."""
        config = MockChatConfig()
        config.chatbot.max_context_messages = 5
        mock_conv_service = MagicMock()
        mock_conv_service.get_messages.return_value = []

        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
            conversation_service=mock_conv_service,
        )

        handler._build_llm_messages("abcdef1234567890")

        mock_conv_service.get_messages.assert_called_once_with(
            peer_hash="abcdef1234567890",
            limit=5,
        )


# ---------------------------------------------------------------------------
# handle_message dispatch and bot prevention tests
# ---------------------------------------------------------------------------


class TestHandleMessageChatbot:
    """Tests for handle_message routing to chatbot mode."""

    @patch("styrened.services.auto_reply.LXMF_AVAILABLE", True)
    @patch("styrened.services.auto_reply.RNS")
    def test_dispatches_to_chatbot_mode(self, mock_rns):
        """mode=CHATBOT should call _schedule_chatbot_reply."""
        config = MockChatConfig(auto_reply_mode=AutoReplyMode.CHATBOT)
        mock_loop = MagicMock()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
            event_loop=mock_loop,
        )

        mock_rns.Transport.has_path.return_value = True

        msg = MagicMock()
        msg.source_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        msg.fields = {}
        msg.content = b"hello"

        # Patch at class level (not instance) due to __slots__
        with patch.object(AutoReplyHandler, "_schedule_chatbot_reply") as mock_schedule:
            handler.handle_message(msg)

        mock_schedule.assert_called_once_with(msg.source_hash)

    @patch("styrened.services.auto_reply.LXMF_AVAILABLE", True)
    @patch("styrened.services.auto_reply.RNS")
    def test_skips_bot_messages(self, mock_rns):
        """Messages with bot=True in fields should be skipped."""
        config = MockChatConfig(auto_reply_mode=AutoReplyMode.CHATBOT)
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        msg = MagicMock()
        msg.source_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        msg.fields = {"bot": True}
        msg.content = b"bot message"

        handler.handle_message(msg)

        # No cooldown should be recorded (message was skipped)
        assert len(handler._last_reply) == 0

    @patch("styrened.services.auto_reply.LXMF_AVAILABLE", True)
    @patch("styrened.services.auto_reply.RNS")
    def test_template_mode_does_not_skip_bot_field(self, mock_rns):
        """In template mode, bot field should still cause skip (loop prevention)."""
        config = MockChatConfig(auto_reply_mode=AutoReplyMode.TEMPLATE)
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        msg = MagicMock()
        msg.source_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        msg.fields = {"bot": True}
        msg.content = b"bot message"

        handler.handle_message(msg)

        assert len(handler._last_reply) == 0

    @patch("styrened.services.auto_reply.LXMF_AVAILABLE", True)
    @patch("styrened.services.auto_reply.RNS")
    def test_chatbot_mode_skips_cooldown(self, mock_rns):
        """Chatbot mode should respond to every message regardless of cooldown.

        Template mode uses cooldown to avoid spamming the same static message.
        Chatbot mode is conversational — silencing replies breaks the dialogue.
        Bot-to-bot loop prevention is handled by the 'bot' field marker.
        """
        mock_rns.Transport.has_path.return_value = True
        config = MockChatConfig(
            auto_reply_mode=AutoReplyMode.CHATBOT,
            auto_reply_cooldown=300,
        )
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        source = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        # Pre-record a very recent reply (simulates just having responded)
        handler._record_reply(source)

        msg = MagicMock()
        msg.source_hash = source
        msg.fields = {}
        msg.content = b"follow-up message"

        # In template mode this would be blocked by cooldown.
        # Chatbot mode should still schedule a reply.
        # Patch on the class (not instance) — __slots__ prevents instance patching.
        with patch.object(AutoReplyHandler, "_schedule_chatbot_reply") as mock_schedule:
            handler.handle_message(msg)
            mock_schedule.assert_called_once_with(source)

    def test_disabled_mode_skips_all(self):
        """DISABLED mode should skip message entirely."""
        config = MockChatConfig(auto_reply_mode=AutoReplyMode.DISABLED)
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        msg = MagicMock()
        msg.source_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        msg.fields = {}
        msg.content = b"hello"

        handler.handle_message(msg)

        assert len(handler._last_reply) == 0


# ---------------------------------------------------------------------------
# _send_chatbot_lxmf tests
# ---------------------------------------------------------------------------


class TestSendChatbotLxmf:
    """Tests for _send_chatbot_lxmf bot marker in LXMF fields."""

    @patch("styrened.services.auto_reply.RNS")
    @patch("styrened.services.auto_reply.LXMF")
    def test_includes_bot_field(self, mock_lxmf, mock_rns):
        """Chatbot LXMF messages should include bot=True in fields."""
        config = MockChatConfig()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        mock_rns.Identity.recall.return_value = MagicMock()
        mock_rns.Destination.OUT = 2
        mock_rns.Destination.SINGLE = 1
        mock_lxmf.APP_NAME = "lxmf"
        mock_lxmf.FIELD_RENDERER = 0x01
        mock_lxmf.RENDERER_PLAIN = 0x01

        dest_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        handler._send_chatbot_lxmf(dest_hash, "Bot response")

        # Verify LXMessage was created with bot=True in fields
        call_kwargs = mock_lxmf.LXMessage.call_args
        fields = call_kwargs[1]["fields"] if "fields" in call_kwargs[1] else call_kwargs[0][3]
        assert fields.get("bot") is True
        assert fields.get("protocol") == "chat"

    @patch("styrened.services.auto_reply.RNS")
    def test_skips_when_identity_unknown(self, mock_rns):
        """Should not send when destination identity is not known."""
        config = MockChatConfig()
        router = MockRouter()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=router,
        )

        mock_rns.Identity.recall.return_value = None

        dest_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        handler._send_chatbot_lxmf(dest_hash, "Bot response")

        assert len(router.outbound_messages) == 0


# ---------------------------------------------------------------------------
# _async_chatbot_reply integration tests
# ---------------------------------------------------------------------------


class TestAsyncChatbotReply:
    """Tests for the async chatbot reply flow."""

    @pytest.mark.asyncio
    async def test_persists_to_conversation_service(self):
        """Should call save_outgoing_message on success."""
        config = MockChatConfig()
        mock_conv_service = MagicMock()
        mock_conv_service.get_messages.return_value = []
        mock_conv_service.save_outgoing_message.return_value = 42

        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
            conversation_service=mock_conv_service,
        )

        with (
            patch(
                "styrened.services.auto_reply._call_chat_completions",
                return_value="Hello from LLM",
            ),
            patch.object(AutoReplyHandler, "_send_chatbot_lxmf"),
        ):
            await handler._async_chatbot_reply(b"\x01\x02\x03\x04\x05\x06\x07\x08")

        mock_conv_service.save_outgoing_message.assert_called_once()
        call_kwargs = mock_conv_service.save_outgoing_message.call_args[1]
        assert call_kwargs["content"] == "Hello from LLM"
        assert call_kwargs["fields"]["bot"] is True

    @pytest.mark.asyncio
    async def test_broadcasts_event(self):
        """Should call broadcast_callback on success."""
        config = MockChatConfig()
        mock_conv_service = MagicMock()
        mock_conv_service.get_messages.return_value = []
        mock_conv_service.save_outgoing_message.return_value = 42
        mock_broadcast = MagicMock()

        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
            conversation_service=mock_conv_service,
            broadcast_callback=mock_broadcast,
        )

        with (
            patch(
                "styrened.services.auto_reply._call_chat_completions",
                return_value="Hello from LLM",
            ),
            patch.object(AutoReplyHandler, "_send_chatbot_lxmf"),
        ):
            await handler._async_chatbot_reply(b"\x01\x02\x03\x04\x05\x06\x07\x08")

        mock_broadcast.assert_called_once()
        call_kwargs = mock_broadcast.call_args[1]
        assert call_kwargs["content"] == "Hello from LLM"
        assert call_kwargs["is_outgoing"] is True

    @pytest.mark.asyncio
    async def test_records_cooldown(self):
        """Should record cooldown after successful reply."""
        config = MockChatConfig()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        dest_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        with (
            patch(
                "styrened.services.auto_reply._call_chat_completions",
                return_value="Hello from LLM",
            ),
            patch.object(AutoReplyHandler, "_send_chatbot_lxmf"),
        ):
            await handler._async_chatbot_reply(dest_hash)

        assert dest_hash in handler._last_reply

    @pytest.mark.asyncio
    async def test_empty_response_skips_send(self):
        """Empty LLM response should not send LXMF or record cooldown."""
        config = MockChatConfig()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        dest_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"

        with patch(
            "styrened.services.auto_reply._call_chat_completions",
            return_value="",
        ):
            await handler._async_chatbot_reply(dest_hash)

        assert dest_hash not in handler._last_reply


# ---------------------------------------------------------------------------
# API key env var fallback
# ---------------------------------------------------------------------------


class TestApiKeyEnvFallback:
    """Tests for STYRENED_CHATBOT_API_KEY env var fallback."""

    @pytest.mark.asyncio
    async def test_uses_env_var_when_config_empty(self):
        """Should fall back to STYRENED_CHATBOT_API_KEY env var."""
        config = MockChatConfig()
        config.chatbot.api_key = ""
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        captured_key = {}

        def mock_completions(endpoint, model, messages, *, api_key="", **kwargs):
            captured_key["value"] = api_key
            return "response"

        with (
            patch.dict(os.environ, {"STYRENED_CHATBOT_API_KEY": "env-key-123"}),
            patch(
                "styrened.services.auto_reply._call_chat_completions",
                side_effect=mock_completions,
            ),
            patch.object(AutoReplyHandler, "_send_chatbot_lxmf"),
        ):
            await handler._async_chatbot_reply(b"\x01\x02\x03\x04\x05\x06\x07\x08")

        assert captured_key["value"] == "env-key-123"

    @pytest.mark.asyncio
    async def test_config_key_takes_precedence(self):
        """Config api_key should take precedence over env var."""
        config = MockChatConfig()
        config.chatbot.api_key = "config-key"
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
        )

        captured_key = {}

        def mock_completions(endpoint, model, messages, *, api_key="", **kwargs):
            captured_key["value"] = api_key
            return "response"

        with (
            patch.dict(os.environ, {"STYRENED_CHATBOT_API_KEY": "env-key-123"}),
            patch(
                "styrened.services.auto_reply._call_chat_completions",
                side_effect=mock_completions,
            ),
            patch.object(AutoReplyHandler, "_send_chatbot_lxmf"),
        ):
            await handler._async_chatbot_reply(b"\x01\x02\x03\x04\x05\x06\x07\x08")

        assert captured_key["value"] == "config-key"


# ---------------------------------------------------------------------------
# _schedule_chatbot_reply tests
# ---------------------------------------------------------------------------


class TestScheduleChatbotReply:
    """Tests for _schedule_chatbot_reply sync-to-async bridge."""

    def test_no_event_loop_logs_warning(self):
        """Should log warning and return when no event loop."""
        config = MockChatConfig()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
            event_loop=None,
        )

        # Should not raise
        handler._schedule_chatbot_reply(b"\x01\x02\x03\x04\x05\x06\x07\x08")

    def test_schedules_on_event_loop(self):
        """Should call run_coroutine_threadsafe with the event loop."""
        config = MockChatConfig()
        mock_loop = MagicMock()
        handler = AutoReplyHandler(
            config=config,
            identity=MockIdentity(),
            router=MockRouter(),
            event_loop=mock_loop,
        )

        with patch("styrened.services.auto_reply.asyncio.run_coroutine_threadsafe") as mock_rcts:
            handler._schedule_chatbot_reply(b"\x01\x02\x03\x04\x05\x06\x07\x08")

        mock_rcts.assert_called_once()
        assert mock_rcts.call_args[0][1] is mock_loop
