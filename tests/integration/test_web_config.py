"""Integration tests for config REST endpoints.

Uses FastAPI TestClient with a mock daemon.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from styrened.models.config import CoreConfig, DeploymentMode
from styrened.web.events import SSEBroadcaster
from styrened.web.routes import create_router


def _make_mock_daemon(config: CoreConfig | None = None) -> MagicMock:
    """Create a mock daemon with a real CoreConfig."""
    daemon = MagicMock()
    daemon.config = config or CoreConfig()
    daemon._node_store = None
    daemon._conversation_service = None
    daemon._rpc_client = None
    daemon._operator_destination = None
    daemon._start_time = 1000000000.0
    daemon._contact_service = None
    return daemon


@pytest.fixture
def client(tmp_path):
    """Create a TestClient with config route mounted."""
    config = CoreConfig()
    daemon = _make_mock_daemon(config)
    broadcaster = SSEBroadcaster()

    app = FastAPI()
    router = create_router(daemon, broadcaster)
    app.include_router(router)

    return TestClient(app), daemon, tmp_path


class TestGetConfig:
    """Tests for GET /api/config."""

    def test_returns_all_10_sections(self, client) -> None:
        """GET /api/config returns all 10 config sections."""
        test_client, _, _ = client
        response = test_client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        config = data["config"]

        expected_sections = {
            "reticulum", "identity", "rpc", "discovery", "chat",
            "api", "ipc", "notifications", "lxmf", "terminal",
        }
        assert expected_sections == set(config.keys())

    def test_returns_reticulum_fields(self, client) -> None:
        """GET /api/config returns reticulum fields."""
        test_client, _, _ = client
        response = test_client.get("/api/config")
        config = response.json()["config"]

        assert "mode" in config["reticulum"]
        assert config["reticulum"]["mode"] == "standalone"
        assert "announce_interval" in config["reticulum"]
        assert "interfaces" in config["reticulum"]

    def test_sanitizes_yubikey_credential(self, client) -> None:
        """GET /api/config redacts yubikey credential_id."""
        test_client, daemon, _ = client
        daemon.config.identity.provider = "yubikey"
        daemon.config.identity.yubikey.credential_id = "secret-cred-id"

        response = test_client.get("/api/config")
        config = response.json()["config"]

        assert config["identity"]["yubikey"]["credential_id"] == "***"

    def test_sanitizes_authorized_identities(self, client) -> None:
        """GET /api/config shows count instead of actual identities."""
        test_client, daemon, _ = client
        daemon.config.terminal.authorized_identities = {"a" * 32, "b" * 32}

        response = test_client.get("/api/config")
        config = response.json()["config"]

        assert "authorized_identities" not in config["terminal"]
        assert config["terminal"]["authorized_identities_count"] == 2


class TestPutConfig:
    """Tests for PUT /api/config."""

    @patch("styrened.services.config.get_config_dir")
    def test_partial_update_returns_updated_config(self, mock_config_dir, tmp_path) -> None:
        """PUT /api/config with partial update returns updated config."""
        mock_config_dir.return_value = tmp_path

        config = CoreConfig()
        daemon = _make_mock_daemon(config)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        response = test_client.put(
            "/api/config",
            json={"chat": {"auto_reply_enabled": False}},
        )
        assert response.status_code == 200
        result = response.json()["config"]
        assert result["chat"]["auto_reply_enabled"] is False

    @patch("styrened.services.config.get_config_dir")
    def test_invalid_values_return_422(self, mock_config_dir, tmp_path) -> None:
        """PUT /api/config with invalid values returns 422."""
        mock_config_dir.return_value = tmp_path

        config = CoreConfig()
        daemon = _make_mock_daemon(config)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        response = test_client.put(
            "/api/config",
            json={"api": {"port": 0}},
        )
        assert response.status_code == 422

    def test_protected_field_rejected(self, client) -> None:
        """PUT /api/config with protected field returns 403."""
        test_client, _, _ = client

        response = test_client.put(
            "/api/config",
            json={"terminal": {"authorized_identities": ["a" * 32]}},
        )
        assert response.status_code == 403

    def test_protected_yubikey_credential_rejected(self, client) -> None:
        """PUT /api/config with yubikey credential_id returns 403."""
        test_client, _, _ = client

        response = test_client.put(
            "/api/config",
            json={"identity": {"yubikey": {"credential_id": "new-cred"}}},
        )
        assert response.status_code == 403
