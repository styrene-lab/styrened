"""Unit tests for daemon always-create auto-reply handler pattern.

Verifies that the auto-reply handler is always created (even when disabled),
enabling runtime toggle without daemon restart.
"""
from __future__ import annotations


from unittest.mock import MagicMock, patch

from styrened.models.config import AutoReplyMode, CoreConfig


class TestAlwaysCreateHandler:
    """Verify handler is created regardless of auto_reply_mode."""

    def _make_daemon(self, auto_reply_mode: AutoReplyMode):  # noqa: ANN202
        """Create a StyreneDaemon with mocked dependencies."""
        from styrened.daemon import StyreneDaemon

        config = CoreConfig()
        config.chat.enabled = True
        config.chat.auto_reply_mode = auto_reply_mode
        daemon = StyreneDaemon(config)
        return daemon

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    @patch("styrened.services.reticulum.get_operator_identity_object")
    def test_handler_created_when_disabled(
        self, mock_identity, mock_lxmf
    ):
        """Handler should exist even when auto_reply_mode=DISABLED."""
        mock_identity.return_value = MagicMock(hexhash="abcd1234")
        lxmf_svc = MagicMock()
        lxmf_svc.is_initialized = True
        lxmf_svc.router = MagicMock()
        mock_lxmf.return_value = lxmf_svc

        daemon = self._make_daemon(auto_reply_mode=AutoReplyMode.DISABLED)
        daemon._start_auto_reply()

        assert daemon._auto_reply_handler is not None

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    @patch("styrened.services.reticulum.get_operator_identity_object")
    def test_handler_noop_when_disabled(
        self, mock_identity, mock_lxmf
    ):
        """Incoming message should produce no reply when disabled."""
        mock_identity.return_value = MagicMock(hexhash="abcd1234")
        lxmf_svc = MagicMock()
        lxmf_svc.is_initialized = True
        lxmf_svc.router = MagicMock()
        mock_lxmf.return_value = lxmf_svc

        daemon = self._make_daemon(auto_reply_mode=AutoReplyMode.DISABLED)
        daemon._start_auto_reply()

        handler = daemon._auto_reply_handler
        assert handler is not None

        msg = MagicMock()
        msg.source_hash = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        msg.fields = {}
        msg.content = b"hello"

        handler.handle_message(msg)
        assert len(handler._last_reply) == 0

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    @patch("styrened.services.reticulum.get_operator_identity_object")
    def test_handler_active_after_runtime_enable(
        self, mock_identity, mock_lxmf
    ):
        """Flipping config at runtime should activate the handler."""
        mock_identity.return_value = MagicMock(hexhash="abcd1234")
        lxmf_svc = MagicMock()
        lxmf_svc.is_initialized = True
        lxmf_svc.router = MagicMock()
        mock_lxmf.return_value = lxmf_svc

        daemon = self._make_daemon(auto_reply_mode=AutoReplyMode.DISABLED)
        daemon._start_auto_reply()

        handler = daemon._auto_reply_handler
        assert handler is not None
        assert handler.config.auto_reply_mode == AutoReplyMode.DISABLED

        # Enable at runtime (simulating API toggle)
        daemon.config.chat.auto_reply_mode = AutoReplyMode.TEMPLATE
        assert handler.config.auto_reply_mode == AutoReplyMode.TEMPLATE

    @patch("styrened.services.lxmf_service.get_lxmf_service")
    @patch("styrened.services.reticulum.get_operator_identity_object")
    def test_handler_uses_config_accessor(
        self, mock_identity, mock_lxmf
    ):
        """Handler should use config accessor, not a static snapshot."""
        mock_identity.return_value = MagicMock(hexhash="abcd1234")
        lxmf_svc = MagicMock()
        lxmf_svc.is_initialized = True
        lxmf_svc.router = MagicMock()
        mock_lxmf.return_value = lxmf_svc

        daemon = self._make_daemon(auto_reply_mode=AutoReplyMode.TEMPLATE)
        daemon._start_auto_reply()

        handler = daemon._auto_reply_handler
        assert handler is not None

        # Change the cooldown on the daemon config
        daemon.config.chat.auto_reply_cooldown = 999
        assert handler.config.auto_reply_cooldown == 999
