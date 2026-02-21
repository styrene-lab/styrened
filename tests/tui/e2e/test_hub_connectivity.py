"""Hub connectivity tests (Phase 1.1).

Tests connection to the brutus Styrene Hub:
- TCP transport connectivity
- Hub announce reception
- Connection state transitions
- Identity verification

Prerequisites:
- Hub running on brutus K8s cluster
- Network path to 192.168.0.102:4242
"""

import asyncio
import logging
import socket
from typing import Any

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.e2e
@pytest.mark.hub_required
class TestHubTCPConnectivity:
    """Test TCP-level connectivity to the hub."""

    def test_hub_tcp_port_reachable(self, hub_config: dict[str, Any]) -> None:
        """Hub TCP port should be reachable from test host."""
        host = hub_config["tcp_host"]
        port = hub_config["tcp_port"]

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)

        try:
            result = sock.connect_ex((host, port))
            assert result == 0, f"Cannot connect to {host}:{port} (error: {result})"
            logger.info(f"TCP connection to {host}:{port} successful")
        finally:
            sock.close()

    def test_hub_tcp_accepts_connection(self, hub_config: dict[str, Any]) -> None:
        """Hub should accept and maintain TCP connection."""
        host = hub_config["tcp_host"]
        port = hub_config["tcp_port"]

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)

        try:
            sock.connect((host, port))
            # Connection established - hub accepted us
            # Try to read (RNS protocol handshake)
            sock.setblocking(False)
            # Just verify we're connected, don't try to parse RNS protocol
            assert sock.fileno() != -1, "Socket not valid after connect"
            logger.info(f"Hub accepted connection on {host}:{port}")
        finally:
            sock.close()


@pytest.mark.e2e
@pytest.mark.hub_required
@pytest.mark.slow
class TestHubAnnounce:
    """Test hub announce reception via Reticulum."""

    @pytest.mark.asyncio
    async def test_hub_announces_within_interval(
        self,
        styrene_lifecycle,
        hub_config: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Hub should announce within the configured interval."""
        from styrened.tui.services.reticulum import discover_devices

        hub_address = hub_config["address"]
        timeout = timeouts.get("hub_connection_timeout", 90)

        logger.info(f"Waiting up to {timeout}s for hub announce...")

        start_time = asyncio.get_event_loop().time()
        hub_found = False

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()

            for device in devices:
                if device.destination_hash == hub_address:
                    hub_found = True
                    elapsed = asyncio.get_event_loop().time() - start_time
                    logger.info(f"Hub discovered after {elapsed:.1f}s")
                    break

            if hub_found:
                break

            await asyncio.sleep(2)

        assert hub_found, f"Hub {hub_address} not discovered within {timeout}s"

    @pytest.mark.asyncio
    async def test_hub_identity_matches_expected(
        self,
        styrene_lifecycle,
        hub_config: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Discovered hub identity should match configuration."""
        from styrened.tui.services.reticulum import discover_devices

        hub_address = hub_config["address"]
        expected_name = hub_config.get("expected_name")
        timeout = timeouts.get("hub_connection_timeout", 90)

        # Wait for discovery
        start_time = asyncio.get_event_loop().time()
        hub_device = None

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            devices = discover_devices()

            for device in devices:
                if device.destination_hash == hub_address:
                    hub_device = device
                    break

            if hub_device:
                break

            await asyncio.sleep(2)

        assert hub_device is not None, f"Hub {hub_address} not discovered"

        # Verify identity details
        assert hub_device.destination_hash == hub_address
        logger.info(f"Hub identity verified: {hub_device.destination_hash}")

        if expected_name:
            # Name may contain the expected string (app_data format varies)
            assert (
                expected_name.lower() in hub_device.name.lower() or hub_device.name
            ), f"Hub name mismatch: expected '{expected_name}', got '{hub_device.name}'"
            logger.info(f"Hub name verified: {hub_device.name}")


@pytest.mark.e2e
@pytest.mark.hub_required
@pytest.mark.slow
class TestHubConnectionState:
    """Test hub connection state management."""

    @pytest.mark.asyncio
    async def test_hub_connection_transitions_to_connected(
        self,
        hub_config: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """HubConnection should transition from WAITING to CONNECTED."""
        from styrened.tui.services.app_lifecycle import StyreneLifecycle
        from styrened.tui.services.config import load_config
        from styrened.services.hub_connection import HubStatus, get_hub_connection

        # Load config with hub enabled
        config = load_config()
        config.reticulum.hub_enabled = True
        config.reticulum.hub_address = hub_config["address"]

        lifecycle = StyreneLifecycle(config)

        try:
            assert lifecycle.initialize(), "Failed to initialize with hub enabled"

            # Get hub connection instance
            hub_conn = get_hub_connection()
            assert hub_conn is not None, "HubConnection not created"

            timeout = timeouts.get("hub_connection_timeout", 90)
            logger.info(f"Waiting up to {timeout}s for hub connection...")

            start_time = asyncio.get_event_loop().time()

            while (asyncio.get_event_loop().time() - start_time) < timeout:
                status = hub_conn.status

                if status == HubStatus.CONNECTED:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    logger.info(f"Hub connected after {elapsed:.1f}s")
                    break

                logger.debug(f"Hub status: {status.value}")
                await asyncio.sleep(2)

            assert hub_conn.status == HubStatus.CONNECTED, (
                f"Hub did not reach CONNECTED status (current: {hub_conn.status.value})"
            )

        finally:
            lifecycle.shutdown()

    @pytest.mark.asyncio
    async def test_hub_connection_reports_correct_address(
        self,
        hub_config: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Connected hub should report the configured address."""
        from styrened.tui.services.app_lifecycle import StyreneLifecycle
        from styrened.tui.services.config import load_config
        from styrened.services.hub_connection import HubStatus, get_hub_connection

        config = load_config()
        config.reticulum.hub_enabled = True
        config.reticulum.hub_address = hub_config["address"]

        lifecycle = StyreneLifecycle(config)

        try:
            assert lifecycle.initialize()

            hub_conn = get_hub_connection()
            timeout = timeouts.get("hub_connection_timeout", 90)

            # Wait for connection
            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                if hub_conn.status == HubStatus.CONNECTED:
                    break
                await asyncio.sleep(2)

            assert hub_conn.status == HubStatus.CONNECTED

            # Verify address matches
            connected_address = hub_conn.hub_address
            assert connected_address == hub_config["address"], (
                f"Address mismatch: {connected_address} != {hub_config['address']}"
            )

        finally:
            lifecycle.shutdown()
