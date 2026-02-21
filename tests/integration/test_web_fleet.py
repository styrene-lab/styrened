"""Integration tests for fleet REST endpoints.

Uses FastAPI TestClient with a mock daemon and RPC client.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from styrened.models.config import CoreConfig
from styrened.rpc.messages import RebootResult, UpdateConfigResult
from styrened.web.events import SSEBroadcaster
from styrened.web.routes import create_router


def _make_mock_daemon(*, rpc_client: MagicMock | None = None) -> MagicMock:
    """Create a mock daemon with optional RPC client."""
    daemon = MagicMock()
    daemon.config = CoreConfig()
    daemon._node_store = None
    daemon._conversation_service = None
    daemon._rpc_client = rpc_client
    daemon._operator_destination = None
    daemon._start_time = 1000000000.0
    daemon._contact_service = None
    return daemon


@pytest.fixture
def rpc_client():
    """Create a mock RPC client with async methods."""
    client = MagicMock()
    client.call_reboot = AsyncMock()
    client.call_update_config = AsyncMock()
    client.call_exec = AsyncMock()
    client.call_status = AsyncMock()
    return client


@pytest.fixture
def client(rpc_client):
    """Create a TestClient with fleet routes and mock RPC."""
    daemon = _make_mock_daemon(rpc_client=rpc_client)
    broadcaster = SSEBroadcaster()

    app = FastAPI()
    router = create_router(daemon, broadcaster)
    app.include_router(router)

    return TestClient(app), rpc_client


class TestFleetReboot:
    """Tests for POST /api/fleet/{destination}/reboot."""

    def test_reboot_calls_rpc_client(self, client) -> None:
        """POST /api/fleet/{dest}/reboot calls RPC client and returns result."""
        test_client, rpc = client
        rpc.call_reboot.return_value = RebootResult(
            success=True, message="Rebooting in 5s", scheduled_time=1000000005.0
        )

        dest = "a" * 32
        response = test_client.post(f"/api/fleet/{dest}/reboot", json={"delay": 5})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["message"] == "Rebooting in 5s"
        assert data["scheduled_time"] == 1000000005.0
        rpc.call_reboot.assert_called_once_with(destination=dest, delay=5)

    def test_reboot_default_delay(self, client) -> None:
        """POST /api/fleet/{dest}/reboot with no delay uses 0."""
        test_client, rpc = client
        rpc.call_reboot.return_value = RebootResult(
            success=True, message="Rebooting now"
        )

        dest = "b" * 32
        response = test_client.post(f"/api/fleet/{dest}/reboot", json={})
        assert response.status_code == 200
        rpc.call_reboot.assert_called_once_with(destination=dest, delay=0)

    def test_reboot_invalid_dest(self, client) -> None:
        """POST /api/fleet/invalid/reboot returns 400."""
        test_client, _ = client
        response = test_client.post("/api/fleet/xyz/reboot", json={})
        assert response.status_code == 400

    def test_reboot_no_rpc_client(self) -> None:
        """POST /api/fleet/{dest}/reboot returns 503 without RPC client."""
        daemon = _make_mock_daemon(rpc_client=None)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        dest = "c" * 32
        response = test_client.post(f"/api/fleet/{dest}/reboot", json={})
        assert response.status_code == 503


class TestFleetConfigUpdate:
    """Tests for PUT /api/fleet/{destination}/config."""

    def test_config_update_calls_rpc_client(self, client) -> None:
        """PUT /api/fleet/{dest}/config calls RPC client and returns result."""
        test_client, rpc = client
        rpc.call_update_config.return_value = UpdateConfigResult(
            success=True,
            message="Config updated",
            updated_keys=["chat.enabled", "rpc.relay_mode"],
        )

        dest = "d" * 32
        response = test_client.put(
            f"/api/fleet/{dest}/config",
            json={
                "config_updates": {"chat": {"enabled": False}},
                "timeout": 15.0,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "chat.enabled" in data["updated_keys"]
        rpc.call_update_config.assert_called_once_with(
            destination=dest,
            config_updates={"chat": {"enabled": False}},
            timeout=15.0,
        )

    def test_config_update_invalid_dest(self, client) -> None:
        """PUT /api/fleet/invalid/config returns 400."""
        test_client, _ = client
        response = test_client.put(
            "/api/fleet/xyz/config",
            json={"config_updates": {}, "timeout": 10.0},
        )
        assert response.status_code == 400

    def test_config_update_no_rpc_client(self) -> None:
        """PUT /api/fleet/{dest}/config returns 503 without RPC client."""
        daemon = _make_mock_daemon(rpc_client=None)
        broadcaster = SSEBroadcaster()
        app = FastAPI()
        router = create_router(daemon, broadcaster)
        app.include_router(router)
        test_client = TestClient(app)

        dest = "e" * 32
        response = test_client.put(
            f"/api/fleet/{dest}/config",
            json={"config_updates": {"chat": {"enabled": True}}},
        )
        assert response.status_code == 503
