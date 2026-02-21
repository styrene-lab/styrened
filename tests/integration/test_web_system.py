"""Integration tests for system REST endpoints.

Uses FastAPI TestClient with a mock daemon.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from styrened.models.config import CoreConfig
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
def client():
    """Create a TestClient with system routes mounted."""
    daemon = _make_mock_daemon()
    broadcaster = SSEBroadcaster()

    app = FastAPI()
    router = create_router(daemon, broadcaster)
    app.include_router(router)

    return TestClient(app)


class TestSystemStatus:
    """Tests for GET /api/system/status."""

    def test_returns_system_info(self, client) -> None:
        """GET /api/system/status returns expected fields."""
        response = client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()

        assert "hostname" in data
        assert "platform" in data
        assert "cpu_model" in data
        assert "cpu_cores" in data
        assert "ram_total_bytes" in data
        assert "ram_total_gb" in data
        assert "version" in data
        assert "uptime" in data
        assert isinstance(data["cpu_cores"], int)
        assert isinstance(data["ram_total_bytes"], int)

    def test_version_matches_package(self, client) -> None:
        """GET /api/system/status version matches __version__."""
        from styrened import __version__

        response = client.get("/api/system/status")
        data = response.json()
        assert data["version"] == __version__


class TestSystemStatusPublicMode:
    """Tests for hostname redaction in public mode."""

    def test_hostname_redacted_in_public_mode(self) -> None:
        """In public mode, hostname uses display_name instead of platform.node()."""
        import platform as plat

        config = CoreConfig()
        config.api.public_mode = True
        config.identity.display_name = "Public Hub"
        daemon = _make_mock_daemon(config)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        response = test_client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert data["hostname"] == "Public Hub"
        assert data["hostname"] != plat.node()

    def test_hostname_shows_real_when_not_public(self) -> None:
        """When public_mode is off, hostname is the real system hostname."""
        import platform as plat

        config = CoreConfig()
        config.api.public_mode = False
        daemon = _make_mock_daemon(config)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        response = test_client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert data["hostname"] == plat.node()

    def test_hostname_fallback_when_no_display_name(self) -> None:
        """In public mode with no display_name, hostname falls back to 'styrened'."""
        config = CoreConfig()
        config.api.public_mode = True
        config.identity.display_name = ""
        daemon = _make_mock_daemon(config)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        response = test_client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert data["hostname"] == "styrened"


class TestReticulumStatus:
    """Tests for GET /api/system/reticulum."""

    def test_returns_rns_state(self, client) -> None:
        """GET /api/system/reticulum returns expected fields."""
        with patch("styrened.services.reticulum.get_operator_identity", return_value=None):
            response = client.get("/api/system/reticulum")

        assert response.status_code == 200
        data = response.json()

        assert "initialized" in data
        assert "transport_enabled" in data
        assert "identity_hash" in data
        assert "destination_hash" in data
        assert "interfaces" in data
        assert "path_count" in data
        assert "announce_count" in data

    @patch("styrened.services.reticulum.get_operator_identity", return_value="abcd" * 8)
    def test_initialized_when_identity_exists(self, mock_identity, client) -> None:
        """GET /api/system/reticulum shows initialized=True when identity exists."""
        response = client.get("/api/system/reticulum")
        data = response.json()
        assert data["initialized"] is True
        assert data["identity_hash"] == "abcd" * 8


class TestSystemDisks:
    """Tests for GET /api/system/disks."""

    def test_returns_disk_list(self, client) -> None:
        """GET /api/system/disks returns a list."""
        response = client.get("/api/system/disks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_disk_has_expected_fields(self, client) -> None:
        """GET /api/system/disks entries have expected fields."""
        response = client.get("/api/system/disks")
        data = response.json()
        if data:  # May be empty in CI
            disk = data[0]
            assert "name" in disk
            assert "size_bytes" in disk
            assert "disk_type" in disk


class TestSystemNetwork:
    """Tests for GET /api/system/network."""

    def test_returns_interface_list(self, client) -> None:
        """GET /api/system/network returns a list."""
        response = client.get("/api/system/network")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_interface_has_expected_fields(self, client) -> None:
        """GET /api/system/network entries have expected fields."""
        response = client.get("/api/system/network")
        data = response.json()
        if data:  # May be empty in CI
            iface = data[0]
            assert "name" in iface
            assert "interface_type" in iface
            assert "category" in iface


class TestSetupStatus:
    """Tests for GET /api/system/setup-status."""

    @patch("styrened.services.setup.get_operator_identity", return_value=None)
    @patch("styrened.services.setup.is_reticulum_configured", return_value=False)
    @patch("styrened.services.setup.get_config_dir")
    @patch("styrened.services.config.load_core_config")
    def test_returns_setup_status(
        self, mock_load, mock_dir, mock_rns, mock_identity, client, tmp_path
    ) -> None:
        """GET /api/system/setup-status returns expected fields."""
        mock_dir.return_value = tmp_path
        mock_load.return_value = CoreConfig()

        response = client.get("/api/system/setup-status")
        assert response.status_code == 200
        data = response.json()

        assert "identity_configured" in data
        assert "config_file_exists" in data
        assert "display_name_set" in data
        assert "rns_initialized" in data
        assert "is_complete" in data
        assert isinstance(data["is_complete"], bool)
