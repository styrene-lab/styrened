"""Integration tests for the auto-reply web API endpoints.

Tests GET /api/auto-reply and POST /api/auto-reply with a test FastAPI client.
"""
from __future__ import annotations


from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from styrened.models.config import AutoReplyMode, CoreConfig


@pytest.fixture
def daemon():
    """Create a minimal mock daemon for testing."""
    from styrened.daemon import StyreneDaemon

    config = CoreConfig()
    config.chat.enabled = True
    config.chat.auto_reply_mode = AutoReplyMode.DISABLED
    config.chat.auto_reply_message = "Test auto-reply"
    config.chat.auto_reply_cooldown = 300
    config.api.enabled = True

    d = StyreneDaemon(config)
    d._operator_destination = MagicMock()
    d._node_store = None
    return d


@pytest.fixture
def client(daemon):
    """Create a test client for the web API."""
    from styrened.web import create_app

    app = create_app(daemon)
    return TestClient(app)


class TestAutoReplyAPI:
    """Tests for GET/POST /api/auto-reply."""

    def test_get_auto_reply_status(self, client, daemon):
        """GET should return current auto-reply state."""
        resp = client.get("/api/auto-reply")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "disabled"
        assert data["message"] == "Test auto-reply"
        assert data["cooldown"] == 300

    def test_post_toggle_enables(self, client, daemon):
        """POST with mode=template should enable auto-reply."""
        resp = client.post("/api/auto-reply", json={"mode": "template"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "template"
        assert daemon.config.chat.auto_reply_mode == AutoReplyMode.TEMPLATE

    def test_post_toggle_disables(self, client, daemon):
        """POST with mode=disabled should disable auto-reply."""
        daemon.config.chat.auto_reply_mode = AutoReplyMode.TEMPLATE
        resp = client.post("/api/auto-reply", json={"mode": "disabled"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "disabled"

    def test_post_updates_message(self, client, daemon):
        """POST with message should update the auto-reply message."""
        resp = client.post(
            "/api/auto-reply",
            json={"mode": "template", "message": "New OOO message"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "New OOO message"
        assert daemon.config.chat.auto_reply_message == "New OOO message"

    def test_post_preserves_message_when_not_provided(self, client, daemon):
        """POST without message should keep the existing message."""
        original = daemon.config.chat.auto_reply_message
        resp = client.post("/api/auto-reply", json={"mode": "template"})
        assert resp.status_code == 200
        assert resp.json()["message"] == original

    @patch("styrened.services.config.save_core_config")
    def test_post_persists_to_disk(self, mock_save, client, daemon):
        """POST should call save_core_config to persist changes."""
        resp = client.post("/api/auto-reply", json={"mode": "template"})
        assert resp.status_code == 200
        mock_save.assert_called_once_with(daemon.config)

    def test_post_triggers_reannounce(self, client, daemon):
        """POST should trigger a re-announce to propagate capability."""
        daemon._operator_destination = MagicMock()
        resp = client.post("/api/auto-reply", json={"mode": "template"})
        assert resp.status_code == 200
        # _announce calls _operator_destination.announce()
        daemon._operator_destination.announce.assert_called()

    def test_get_reflects_post_changes(self, client, daemon):
        """GET after POST should reflect the updated state."""
        client.post(
            "/api/auto-reply",
            json={"mode": "chatbot", "message": "Changed"},
        )
        resp = client.get("/api/auto-reply")
        data = resp.json()
        assert data["mode"] == "chatbot"
        assert data["message"] == "Changed"

    def test_post_chatbot_mode(self, client, daemon):
        """POST with mode=chatbot should set chatbot mode."""
        resp = client.post("/api/auto-reply", json={"mode": "chatbot"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "chatbot"
        assert daemon.config.chat.auto_reply_mode == AutoReplyMode.CHATBOT
