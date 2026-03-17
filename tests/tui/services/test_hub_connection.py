"""Tests for Styrene hub connection management."""
from __future__ import annotations

from unittest.mock import MagicMock, Mock, patch

from styrened.services.hub_connection import (
    PATH_CHECK_INTERVAL,
    HubConnection,
    HubStatus,
    get_hub_connection,
)


class TestHubConnectionInitialization:
    """Test hub connection initialization."""

    def test_hub_connection_starts_disconnected(self) -> None:
        """Test that HubConnection starts in disconnected state."""
        hub = HubConnection()

        assert hub.is_connected is False
        assert hub.hub_destination is None

    def test_connect_requires_rns_service_initialized(self) -> None:
        """Test that connect fails if RNS service is not initialized."""
        hub = HubConnection()

        result = hub.connect(hub_address="abcd1234" * 4)

        assert result is False
        assert hub.is_connected is False

    @patch("styrened.services.hub_connection.get_rns_service")
    @patch("styrened.services.hub_connection.RNS")
    def test_connect_creates_hub_destination(
        self, mock_rns: Mock, mock_get_rns_service: Mock
    ) -> None:
        """Test that connect() creates a destination for the hub."""
        # Mock RNS service
        mock_service = Mock()
        mock_service.is_initialized = True
        mock_get_rns_service.return_value = mock_service

        # Mock RNS.Identity and Destination
        mock_identity = Mock()
        mock_rns.Identity.from_hash.return_value = mock_identity

        mock_destination = Mock()
        mock_destination.hash = MagicMock()
        mock_destination.hash.hex.return_value = "abcd1234" * 4  # 32 hex chars
        mock_rns.Destination.return_value = mock_destination

        hub = HubConnection()
        hub_address = "abcd1234" * 4  # 32 hex chars (16 bytes)

        result = hub.connect(hub_address=hub_address)

        assert result is True
        assert hub.is_connected is True
        # Hub destination is no longer created - LXMF handles routing with hashes
        assert hub.hub_destination is None
        # RNS.Identity and RNS.Destination not called - using path discovery instead
        mock_rns.Identity.from_hash.assert_not_called()
        mock_rns.Destination.assert_not_called()

    @patch("styrened.services.hub_connection.get_rns_service")
    @patch("styrened.services.hub_connection.RNS")
    def test_connect_handles_invalid_address(
        self, mock_rns: Mock, mock_get_rns_service: Mock
    ) -> None:
        """Test that connect handles invalid hub addresses gracefully."""
        mock_service = Mock()
        mock_service.is_initialized = True
        mock_get_rns_service.return_value = mock_service

        # Mock Identity.from_hash to raise exception for invalid address
        mock_rns.Identity.from_hash.side_effect = ValueError("Invalid hash")

        hub = HubConnection()

        result = hub.connect(hub_address="invalid")

        assert result is False
        assert hub.is_connected is False

    @patch("styrened.services.hub_connection.get_rns_service")
    def test_disconnect_clears_connection(self, mock_get_rns_service: Mock) -> None:
        """Test that disconnect() clears the connection state."""
        hub = HubConnection()

        # Manually set connected state (simulating successful connection)
        hub._connected = True
        hub._hub_destination = Mock()

        hub.disconnect()

        assert hub.is_connected is False
        assert hub.hub_destination is None

    @patch("styrened.services.hub_connection.get_rns_service")
    def test_disconnect_is_idempotent(self, mock_get_rns_service: Mock) -> None:
        """Test that multiple disconnect calls don't cause errors."""
        hub = HubConnection()

        hub.disconnect()
        hub.disconnect()

        assert hub.is_connected is False


class TestHubConnectionSingleton:
    """Test hub connection singleton pattern."""

    def test_get_hub_connection_returns_instance(self) -> None:
        """Test get_hub_connection returns HubConnection instance."""
        hub = get_hub_connection()

        assert isinstance(hub, HubConnection)

    def test_get_hub_connection_returns_same_instance(self) -> None:
        """Test get_hub_connection returns same instance (singleton)."""
        hub1 = get_hub_connection()
        hub2 = get_hub_connection()

        assert hub1 is hub2


class TestKnownHubs:
    """Test known hub addresses."""

    def test_styrene_hub_address_is_defined(self) -> None:
        """Test that Styrene hub address is defined (or None if not deployed)."""
        from styrened.services.hub_connection import STYRENE_HUB_ADDRESS

        # Address should be None (not deployed yet) or a 32-character hex string (16 bytes)
        assert STYRENE_HUB_ADDRESS is None or (
            isinstance(STYRENE_HUB_ADDRESS, str) and len(STYRENE_HUB_ADDRESS) == 32
        )


class TestHubConnectionPathHealthCheck:
    """Test hub connection path health checking."""

    @patch("styrened.services.hub_connection.RNS")
    @patch("styrened.services.hub_connection.time")
    def test_is_connected_rechecks_path_after_interval(
        self, mock_time: Mock, mock_rns: Mock
    ) -> None:
        """Test that is_connected re-checks the path after interval expires."""
        hub = HubConnection()
        hub_address = "abcd1234" * 4  # 32 hex chars

        # Set up connected state
        hub._connected = True
        hub._hub_address = hub_address
        hub._last_path_check = 1000.0  # Last check at t=1000

        # First call: within interval (t=1010), should not re-check
        mock_time.time.return_value = 1010.0  # 10 seconds after last check
        mock_rns.Transport.has_path.return_value = True

        result = hub.is_connected

        assert result is True
        mock_rns.Transport.has_path.assert_not_called()

        # Second call: after interval (t=1035), should re-check
        mock_time.time.return_value = 1035.0  # 35 seconds after last check
        mock_rns.Transport.has_path.return_value = True

        result = hub.is_connected

        assert result is True
        mock_rns.Transport.has_path.assert_called_once()
        assert hub._last_path_check == 1035.0

    @patch("styrened.services.hub_connection.RNS")
    @patch("styrened.services.hub_connection.time")
    def test_is_connected_returns_false_when_path_lost(
        self, mock_time: Mock, mock_rns: Mock
    ) -> None:
        """Test that is_connected returns False when RNS.Transport.has_path returns False."""
        hub = HubConnection()
        hub_address = "abcd1234" * 4

        # Set up connected state
        hub._connected = True
        hub._hub_address = hub_address
        hub._last_path_check = 1000.0

        # Time after interval, path no longer available
        mock_time.time.return_value = 1035.0
        mock_rns.Transport.has_path.return_value = False

        result = hub.is_connected

        assert result is False
        assert hub._connected is False
        mock_rns.Transport.has_path.assert_called_once()

    @patch("styrened.services.hub_connection.RNS")
    @patch("styrened.services.hub_connection.time")
    def test_force_path_check_bypasses_interval(
        self, mock_time: Mock, mock_rns: Mock
    ) -> None:
        """Test that force_path_check checks immediately regardless of interval."""
        hub = HubConnection()
        hub_address = "abcd1234" * 4

        # Set up connected state with recent check
        hub._connected = True
        hub._hub_address = hub_address
        hub._last_path_check = 1000.0

        # Time is only 5 seconds after last check (within interval)
        mock_time.time.return_value = 1005.0
        mock_rns.Transport.has_path.return_value = True

        # force_path_check should still check
        result = hub.force_path_check()

        assert result is True
        mock_rns.Transport.has_path.assert_called_once()
        assert hub._last_path_check == 1005.0

    @patch("styrened.services.hub_connection.RNS")
    @patch("styrened.services.hub_connection.time")
    def test_force_path_check_disconnects_on_path_loss(
        self, mock_time: Mock, mock_rns: Mock
    ) -> None:
        """Test that force_path_check sets connected to False when path lost."""
        hub = HubConnection()
        hub_address = "abcd1234" * 4

        hub._connected = True
        hub._hub_address = hub_address
        hub._last_path_check = 1000.0

        mock_time.time.return_value = 1005.0
        mock_rns.Transport.has_path.return_value = False

        result = hub.force_path_check()

        assert result is False
        assert hub._connected is False

    def test_force_path_check_returns_false_when_not_connected(self) -> None:
        """Test that force_path_check returns False if not connected."""
        hub = HubConnection()
        hub._connected = False

        result = hub.force_path_check()

        assert result is False

    def test_force_path_check_returns_false_when_no_address(self) -> None:
        """Test that force_path_check returns False if no hub address."""
        hub = HubConnection()
        hub._connected = True
        hub._hub_address = None

        result = hub.force_path_check()

        assert result is False

    @patch("styrened.services.hub_connection.RNS")
    @patch("styrened.services.hub_connection.time")
    def test_status_uses_refreshed_is_connected(
        self, mock_time: Mock, mock_rns: Mock
    ) -> None:
        """Test that status property uses is_connected which re-validates path."""
        hub = HubConnection()
        hub_address = "abcd1234" * 4

        hub._connected = True
        hub._hub_address = hub_address
        hub._last_path_check = 1000.0
        # Set waiting_since so is_within_announce_window returns False after path loss
        # (announce_interval defaults to 60, so 1035 - 900 = 135s elapsed > 60s)
        hub._waiting_since = 900.0

        # Time after interval, path lost
        mock_time.time.return_value = 1035.0
        mock_rns.Transport.has_path.return_value = False

        # Status should trigger is_connected which checks path
        status = hub.status

        assert status == HubStatus.DISCONNECTED
        assert hub._connected is False

    def test_path_check_interval_constant_exists(self) -> None:
        """Test that PATH_CHECK_INTERVAL constant is defined."""
        assert PATH_CHECK_INTERVAL == 30


class TestHubConfiguredFlag:
    """Test _hub_configured flag and WAITING vs DISABLED semantics."""

    def test_status_is_disabled_when_not_configured_and_no_address(self) -> None:
        """Fresh install with no peers: DISABLED (operator opted out)."""
        hub = HubConnection()
        # _hub_configured defaults False, no address
        assert hub.status == HubStatus.DISABLED

    def test_status_is_waiting_when_configured_and_no_address(self) -> None:
        """Hub peers in config but no announce received yet: WAITING."""
        hub = HubConnection()
        hub.set_configured(True)
        assert hub.status == HubStatus.WAITING

    def test_status_is_disabled_when_explicitly_unconfigured(self) -> None:
        """set_configured(False) after True reverts to DISABLED."""
        hub = HubConnection()
        hub.set_configured(True)
        hub.set_configured(False)
        assert hub.status == HubStatus.DISABLED

    @patch("styrened.services.hub_connection.RNS")
    @patch("styrened.services.hub_connection.time")
    def test_status_is_waiting_after_connect_within_window(
        self, mock_time: Mock, mock_rns: Mock
    ) -> None:
        """Address set but path not available yet: WAITING within announce window."""
        hub = HubConnection()
        hub.set_configured(True)
        hub._hub_address = "abcd1234" * 4
        hub._connected = False
        hub._waiting_since = 1000.0
        hub._announce_interval = 60

        mock_time.time.return_value = 1030.0  # 30s elapsed, within 60s window
        assert hub.status == HubStatus.WAITING

    @patch("styrened.services.hub_connection.RNS")
    @patch("styrened.services.hub_connection.time")
    def test_status_is_disconnected_after_announce_window_expires(
        self, mock_time: Mock, mock_rns: Mock
    ) -> None:
        """Address set, window expired, not connected: DISCONNECTED."""
        hub = HubConnection()
        hub.set_configured(True)
        hub._hub_address = "abcd1234" * 4
        hub._connected = False
        hub._waiting_since = 1000.0
        hub._announce_interval = 60

        mock_time.time.return_value = 1065.0  # 65s elapsed, past 60s window
        assert hub.status == HubStatus.DISCONNECTED

    @patch("styrened.services.hub_connection.RNS")
    @patch("styrened.services.hub_connection.time")
    def test_status_is_connected_when_path_valid(
        self, mock_time: Mock, mock_rns: Mock
    ) -> None:
        """Connected with valid path: CONNECTED."""
        hub = HubConnection()
        hub.set_configured(True)
        hub._hub_address = "abcd1234" * 4
        hub._connected = True
        hub._last_path_check = 1000.0

        mock_time.time.return_value = 1010.0  # within PATH_CHECK_INTERVAL
        assert hub.status == HubStatus.CONNECTED

    def test_set_configured_does_not_affect_connected_status(self) -> None:
        """set_configured(False) on an already-connected hub doesn't downgrade status."""
        hub = HubConnection()
        hub._hub_address = "abcd1234" * 4
        hub._connected = True
        hub._last_path_check = float("inf")  # never triggers re-check

        # Even with configured=False, CONNECTED wins (path check is the gate)
        hub.set_configured(False)
        # is_connected still True (last_path_check logic won't fire with inf)
        assert hub._connected is True
