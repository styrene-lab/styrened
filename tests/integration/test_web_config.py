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
            "profile", "reticulum", "identity", "rpc", "discovery", "chat",
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


class TestPublicModeInConfig:
    """Tests for public_mode visibility in config API."""

    def test_public_mode_appears_in_config(self, client) -> None:
        """GET /api/config includes api.public_mode field."""
        test_client, _, _ = client
        response = test_client.get("/api/config")
        assert response.status_code == 200
        config = response.json()["config"]
        assert "public_mode" in config["api"]
        assert config["api"]["public_mode"] is False


class TestPublicModeConfigRedaction:
    """Tests for config redaction when public_mode is enabled."""

    def _make_public_client(self):
        config = CoreConfig()
        config.api.public_mode = True
        # Set up some interface data to verify redaction
        config.reticulum.interfaces.server.enabled = True
        daemon = _make_mock_daemon(config)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        return TestClient(app), daemon

    def test_config_redacts_interfaces_in_public_mode(self) -> None:
        """In public mode, interfaces only shows auto + server.enabled."""
        test_client, _ = self._make_public_client()
        response = test_client.get("/api/config")
        assert response.status_code == 200
        config = response.json()["config"]
        ifaces = config["reticulum"]["interfaces"]
        # Should only have 'auto' and 'server' keys
        assert set(ifaces.keys()) == {"auto", "server"}
        assert isinstance(ifaces["server"]["enabled"], bool)

    def test_config_full_interfaces_when_not_public(self) -> None:
        """When public_mode is off, interfaces show full details."""
        config = CoreConfig()
        config.api.public_mode = False
        config.reticulum.interfaces.server.enabled = True
        daemon = _make_mock_daemon(config)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        response = test_client.get("/api/config")
        assert response.status_code == 200
        config_resp = response.json()["config"]
        ifaces = config_resp["reticulum"]["interfaces"]
        # Should contain full interface details (server, peers, auto)
        assert "server" in ifaces
        # Server should have full details, not just {enabled: bool}
        assert "enabled" in ifaces["server"]

    def test_config_redacts_terminal_in_public_mode(self) -> None:
        """In public mode, terminal section only shows enabled status."""
        test_client, _ = self._make_public_client()
        response = test_client.get("/api/config")
        assert response.status_code == 200
        config = response.json()["config"]
        terminal = config["terminal"]
        # Should only have 'enabled' key
        assert set(terminal.keys()) == {"enabled"}
        assert isinstance(terminal["enabled"], bool)

    def test_config_redacts_filesystem_paths_in_public_mode(self) -> None:
        """In public mode, filesystem paths are stripped from config."""
        test_client, _ = self._make_public_client()
        response = test_client.get("/api/config")
        assert response.status_code == 200
        config = response.json()["config"]
        ret = config["reticulum"]
        assert "config_path_override" not in ret
        assert "operator_identity_path" not in ret
        ipc = config["ipc"]
        assert "socket_path" not in ipc
        assert "socket_mode" not in ipc


class TestPublicModeNetworkRedaction:
    """Tests for network info redaction when public_mode is enabled."""

    def test_network_omits_mac_and_ip_in_public_mode(self) -> None:
        """In public mode, MAC and IP addresses are omitted from network info."""
        config = CoreConfig()
        config.api.public_mode = True
        daemon = _make_mock_daemon(config)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        response = test_client.get("/api/system/network")
        assert response.status_code == 200
        interfaces = response.json()
        for iface in interfaces:
            assert "mac_address" not in iface
            assert "ip_address" not in iface
            # Should still have basic info
            assert "name" in iface
            assert "interface_type" in iface
            assert "category" in iface

    def test_network_includes_mac_and_ip_when_not_public(self) -> None:
        """When public_mode is off, MAC and IP addresses are included."""
        config = CoreConfig()
        config.api.public_mode = False
        daemon = _make_mock_daemon(config)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        response = test_client.get("/api/system/network")
        assert response.status_code == 200
        interfaces = response.json()
        for iface in interfaces:
            assert "mac_address" in iface
            assert "ip_address" in iface
