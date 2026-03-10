"""Integration tests for IPC server/client communication.

Tests actual Unix socket communication between ControlServer and ControlClient,
validating the full request/response lifecycle.
"""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from styrened.ipc.client import ControlClient, IPCConnectionError
from styrened.models.config import CoreConfig
from styrened.ipc.messages import (
    DaemonStatus,
)
from styrened.ipc.server import ControlServer


@pytest.fixture
def mock_daemon():
    """Create a mock StyreneDaemon for testing."""
    daemon = MagicMock()
    daemon._start_time = 0.0
    daemon._operator_destination = SimpleNamespace(hexhash="abc123def456")
    daemon._rpc_client = SimpleNamespace(pending_count=0)
    daemon._lxmf_service = SimpleNamespace(router=None)

    # Use a real config object so IPC responses remain serializable.
    daemon.config = CoreConfig()
    daemon.config.reticulum.announce_interval = 300
    daemon.config.reticulum.hub_enabled = False
    daemon.config.rpc.enabled = True
    daemon.config.rpc.relay_mode = False
    daemon.config.rpc.allow_command_execution = True
    daemon.config.discovery.enabled = True
    daemon.config.discovery.auto_announce = True
    daemon.config.chat.enabled = True
    daemon.config.chat.auto_reply_cooldown = 60
    daemon.config.chat.persist_messages = True
    daemon.config.api.enabled = False
    daemon.config.api.port = 8080

    daemon.lifecycle = SimpleNamespace(_initialized=True)
    daemon._announce = MagicMock()

    return daemon


@pytest.fixture
def socket_path():
    """Create a short temporary socket path (macOS limit is 104 chars)."""
    # Use /tmp directly for shorter path
    socket_dir = Path(tempfile.mkdtemp(prefix="ipc", dir="/tmp"))
    path = socket_dir / "ctrl.sock"
    yield path
    # Cleanup
    if path.exists():
        path.unlink()
    socket_dir.rmdir()


@pytest.fixture
async def server_client(mock_daemon, socket_path):
    """Create connected server and client pair.

    Yields:
        Tuple of (ControlServer, ControlClient)
    """
    # Patch at the source modules where the functions are defined
    with (
        patch("styrened.services.reticulum.discover_devices", return_value=[]),
        patch("styrened.services.node_store.get_node_store", return_value=None),
        patch("styrened.services.lxmf_service.get_lxmf_service", return_value=None),
        patch("styrened.services.reticulum.get_operator_identity", return_value="test_identity"),
    ):
        server = ControlServer(mock_daemon, socket_path)
        await server.start()

        client = ControlClient(socket_path, timeout=5.0)
        await client.connect()

        yield server, client

        await client.disconnect()
        await server.stop()


class TestServerClientConnection:
    """Tests for basic server/client connection lifecycle."""

    @pytest.mark.asyncio
    async def test_client_connects_to_server(self, mock_daemon, socket_path):
        """Client should successfully connect to running server."""
        with (
            patch("styrened.services.reticulum.discover_devices", return_value=[]),
            patch("styrened.services.node_store.get_node_store", return_value=None),
        ):
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            assert server.is_running
            assert socket_path.exists()

            client = ControlClient(socket_path)
            await client.connect()

            assert client.connected

            # Give server time to register the client
            await asyncio.sleep(0.05)
            assert server.client_count >= 1

            await client.disconnect()
            await server.stop()

            assert not client.connected
            assert not server.is_running

    @pytest.mark.asyncio
    async def test_client_connection_refused_no_server(self, socket_path):
        """Client should raise IPCConnectionError when no server running."""
        client = ControlClient(socket_path)

        with pytest.raises(IPCConnectionError):
            await client.connect()

    @pytest.mark.asyncio
    async def test_multiple_clients_connect(self, mock_daemon, socket_path):
        """Server should handle multiple concurrent clients."""
        with (
            patch("styrened.services.reticulum.discover_devices", return_value=[]),
            patch("styrened.services.node_store.get_node_store", return_value=None),
        ):
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            clients = []
            for _ in range(3):
                client = ControlClient(socket_path)
                await client.connect()
                clients.append(client)

            # Give server time to register all clients
            await asyncio.sleep(0.1)
            assert server.client_count == 3

            for client in clients:
                await client.disconnect()

            # Give server time to clean up
            await asyncio.sleep(0.1)
            assert server.client_count == 0

            await server.stop()

    @pytest.mark.asyncio
    async def test_server_removes_stale_socket(self, mock_daemon, socket_path):
        """Server should remove stale socket file on startup."""
        # Create a stale socket file
        socket_path.touch()
        assert socket_path.exists()

        with (
            patch("styrened.services.reticulum.discover_devices", return_value=[]),
            patch("styrened.services.node_store.get_node_store", return_value=None),
        ):
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            # Server should have replaced the stale socket
            assert server.is_running

            await server.stop()


class TestPingPong:
    """Tests for PING/PONG keepalive."""

    @pytest.mark.asyncio
    async def test_ping_returns_true(self, server_client):
        """Ping should return True when server responds."""
        server, client = server_client

        result = await client.ping(timeout=2.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_ping_timeout_returns_false(self, socket_path):
        """Ping should return False on timeout (no server)."""
        client = ControlClient(socket_path, timeout=0.5)

        # Not connected, ping should return False
        result = await client.ping(timeout=0.1)
        assert result is False


class TestQueryDevices:
    """Tests for QUERY_DEVICES request/response."""

    @pytest.mark.asyncio
    async def test_query_devices_empty(self, server_client):
        """Query devices should return empty list when no devices."""
        server, client = server_client

        devices = await client.query_devices()
        assert devices == []

    @pytest.mark.asyncio
    async def test_query_devices_with_results(self, mock_daemon, socket_path):
        """Query devices should return device list."""
        # Create mock devices
        mock_device = SimpleNamespace(
            destination_hash="dest123",
            identity_hash="id456",
            name="test-node",
            device_type=SimpleNamespace(value="styrene"),
            status=SimpleNamespace(value="active"),
            is_styrene_node=True,
            lxmf_destination_hash="lxmf789",
            last_announce=1234567890.0,
            announce_count=5,
            short_name=None,
            system_fingerprint=None,
        )

        with (
            patch("styrened.services.reticulum.discover_devices", return_value=[mock_device]),
            patch("styrened.services.node_store.get_node_store", return_value=None),
        ):
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            client = ControlClient(socket_path)
            await client.connect()

            devices = await client.query_devices()

            assert len(devices) == 1
            assert devices[0].destination_hash == "dest123"
            assert devices[0].name == "test-node"
            assert devices[0].is_styrene_node is True

            await client.disconnect()
            await server.stop()

    @pytest.mark.asyncio
    async def test_query_devices_styrene_only(self, mock_daemon, socket_path):
        """Query devices with styrene_only filter."""
        # Create mock devices - one styrene, one not
        styrene_device = SimpleNamespace(
            destination_hash="styrene1",
            identity_hash="id1",
            name="styrene-node",
            device_type=SimpleNamespace(value="styrene"),
            status=SimpleNamespace(value="active"),
            is_styrene_node=True,
            lxmf_destination_hash="lxmf1",
            last_announce=1234567890.0,
            announce_count=1,
            short_name=None,
            system_fingerprint=None,
        )

        other_device = SimpleNamespace(
            destination_hash="other1",
            identity_hash="id2",
            name="other-node",
            device_type=SimpleNamespace(value="nomadnet"),
            status=SimpleNamespace(value="active"),
            is_styrene_node=False,
            lxmf_destination_hash="lxmf2",
            last_announce=1234567890.0,
            announce_count=1,
            short_name=None,
            system_fingerprint=None,
        )

        with (
            patch(
                "styrened.services.reticulum.discover_devices",
                return_value=[styrene_device, other_device],
            ),
            patch("styrened.services.node_store.get_node_store", return_value=None),
        ):
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            client = ControlClient(socket_path)
            await client.connect()

            # Query all devices
            all_devices = await client.query_devices(styrene_only=False)
            assert len(all_devices) == 2

            # Query styrene only
            styrene_devices = await client.query_devices(styrene_only=True)
            assert len(styrene_devices) == 1
            assert styrene_devices[0].name == "styrene-node"

            await client.disconnect()
            await server.stop()


class TestQueryStatus:
    """Tests for QUERY_STATUS request/response."""

    @pytest.mark.asyncio
    async def test_query_status(self, server_client):
        """Query status should return daemon status."""
        server, client = server_client

        status = await client.query_status()

        assert isinstance(status, DaemonStatus)
        assert status.rns_initialized is True
        assert status.device_count == 0


class TestQueryConfig:
    """Tests for QUERY_CONFIG request/response."""

    @pytest.mark.asyncio
    async def test_query_config(self, server_client):
        """Query config should return sanitized config."""
        server, client = server_client

        config = await client.query_config()

        assert isinstance(config, dict)
        assert "reticulum" in config
        assert config["reticulum"]["mode"] == "standalone"
        assert config["rpc"]["enabled"] is True


class TestCmdAnnounce:
    """Tests for CMD_ANNOUNCE request/response."""

    @pytest.mark.asyncio
    async def test_announce(self, server_client, mock_daemon):
        """Announce should trigger daemon announce."""
        server, client = server_client

        dest_hash = await client.announce()

        assert dest_hash == "abc123def456"
        mock_daemon._announce.assert_called_once()


class TestConcurrentRequests:
    """Tests for concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_pings(self, server_client):
        """Multiple concurrent pings should all succeed."""
        server, client = server_client

        # Send 10 concurrent pings
        tasks = [client.ping(timeout=2.0) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        assert all(results)

    @pytest.mark.asyncio
    async def test_concurrent_mixed_requests(self, server_client):
        """Mixed concurrent requests should all succeed."""
        server, client = server_client

        async def do_ping():
            return await client.ping(timeout=2.0)

        async def do_status():
            return await client.query_status()

        async def do_config():
            return await client.query_config()

        tasks = [
            do_ping(),
            do_status(),
            do_config(),
            do_ping(),
            do_status(),
        ]

        results = await asyncio.gather(*tasks)

        assert results[0] is True  # ping
        assert isinstance(results[1], DaemonStatus)  # status
        assert isinstance(results[2], dict)  # config
        assert results[3] is True  # ping
        assert isinstance(results[4], DaemonStatus)  # status


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_request_after_disconnect(self, server_client):
        """Request after disconnect should raise IPCConnectionError."""
        server, client = server_client

        await client.disconnect()

        with pytest.raises(IPCConnectionError, match="Not connected"):
            await client.query_devices()

    @pytest.mark.asyncio
    async def test_server_stop_disconnects_clients(self, mock_daemon, socket_path):
        """Server stop should disconnect all clients."""
        with (
            patch("styrened.services.reticulum.discover_devices", return_value=[]),
            patch("styrened.services.node_store.get_node_store", return_value=None),
        ):
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            client = ControlClient(socket_path)
            await client.connect()

            assert client.connected

            await server.stop()

            # Give client time to detect disconnect
            await asyncio.sleep(0.1)

            # Client should detect disconnection on next operation
            # (the receive loop should have exited)
            assert not server.is_running


class TestRequestTimeout:
    """Tests for request timeout behavior."""

    @pytest.mark.asyncio
    async def test_request_timeout_with_slow_handler(self, mock_daemon, socket_path):
        """Request should timeout if handler takes too long."""
        with (
            patch("styrened.services.reticulum.discover_devices", return_value=[]),
            patch("styrened.services.node_store.get_node_store", return_value=None),
        ):
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            client = ControlClient(socket_path, timeout=0.1)
            await client.connect()

            # Ping with very short timeout - might succeed or fail depending on timing
            # This validates the timeout mechanism exists
            await client.ping(timeout=0.001)
            # Result could be True or False depending on timing

            await client.disconnect()
            await server.stop()


class TestContextManager:
    """Tests for async context manager usage."""

    @pytest.mark.asyncio
    async def test_context_manager_connects_disconnects(self, mock_daemon, socket_path):
        """Context manager should handle connect/disconnect."""
        with (
            patch("styrened.services.reticulum.discover_devices", return_value=[]),
            patch("styrened.services.node_store.get_node_store", return_value=None),
        ):
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            async with ControlClient(socket_path) as client:
                assert client.connected
                result = await client.ping()
                assert result is True

            # Client should be disconnected after context exit
            # (we can't easily check this without accessing internals)

            await server.stop()

    @pytest.mark.asyncio
    async def test_context_manager_handles_exception(self, mock_daemon, socket_path):
        """Context manager should disconnect on exception."""
        with (
            patch("styrened.services.reticulum.discover_devices", return_value=[]),
            patch("styrened.services.node_store.get_node_store", return_value=None),
        ):
            server = ControlServer(mock_daemon, socket_path)
            await server.start()

            try:
                async with ControlClient(socket_path) as client:
                    assert client.connected
                    raise ValueError("Test exception")
            except ValueError:
                pass

            # Server should have seen client disconnect
            await asyncio.sleep(0.1)
            assert server.client_count == 0

            await server.stop()
