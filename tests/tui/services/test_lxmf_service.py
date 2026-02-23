"""Tests for LXMF service lifecycle management.

These tests verify:
- LXMF initialization with RNS identity
- Singleton pattern for LXMFService
- Message sending capabilities
- Message receiving via callbacks
- Integration with RNSService
- Error handling when LXMF fails to initialize

Note: These tests use patching rather than module-level mocking to avoid
polluting sys.modules and affecting other tests.
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Import service - it will import real LXMF/RNS, but we patch at test time
from styrened.services.lxmf_service import LXMFService, get_lxmf_service


@pytest.fixture
def mock_lxmf():
    """Provide a fresh LXMF mock for each test."""
    with patch("styrened.services.lxmf_service.LXMF") as mock:
        mock.APP_NAME = "lxmf"
        mock.FIELD_RENDERER = 0x0F
        mock.RENDERER_PLAIN = 0x00
        mock.LXMessage.DIRECT = 2
        mock.LXMessage.PROPAGATED = 3
        yield mock


@pytest.fixture
def mock_rns():
    """Provide a fresh RNS mock for each test."""
    with patch("styrened.services.lxmf_service.RNS") as mock:
        mock.Destination.OUT = 2
        mock.Destination.SINGLE = 1
        # Provide a default destination mock with proper hash bytes
        default_dest = Mock()
        default_dest.hash = bytes.fromhex("b1c2d3e4f5a67890")
        mock.Destination.return_value = default_dest
        yield mock


@pytest.fixture
def mock_rns_service():
    """Provide a mock RNS service that appears initialized."""
    with patch("styrened.services.lxmf_service.get_rns_service") as mock_get_rns:
        mock_service = Mock()
        mock_service.is_initialized = True
        mock_get_rns.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_platformdirs(tmp_path: Path):
    """Provide a mock paths module pointing to tmp_path."""
    with patch("styrened.services.lxmf_service.paths") as mock:
        mock.lxmf_storage.return_value = tmp_path / "lxmf"
        yield mock


class TestLXMFServiceSingleton:
    """Tests for LXMFService singleton pattern."""

    def test_get_lxmf_service_returns_instance(self) -> None:
        """Test get_lxmf_service returns LXMFService instance."""
        service = get_lxmf_service()
        assert isinstance(service, LXMFService)

    def test_get_lxmf_service_returns_same_instance(self) -> None:
        """Test get_lxmf_service returns same instance (singleton)."""
        service1 = get_lxmf_service()
        service2 = get_lxmf_service()
        assert service1 is service2


class TestLXMFServiceInitialization:
    """Tests for LXMF initialization."""

    def test_service_starts_not_initialized(self) -> None:
        """Test service starts in uninitialized state."""
        service = LXMFService()
        assert service.is_initialized is False
        assert service.router is None

    @patch("styrened.services.lxmf_service.get_rns_service")
    def test_initialize_requires_rns_initialized(self, mock_get_rns: Mock) -> None:
        """Test initialize requires RNS to be initialized first."""
        # RNS not initialized
        mock_rns_service = Mock()
        mock_rns_service.is_initialized = False
        mock_get_rns.return_value = mock_rns_service

        service = LXMFService()
        mock_identity = Mock()
        result = service.initialize(mock_identity)

        assert result is False
        assert service.is_initialized is False

    def test_initialize_creates_lxmf_router(
        self, mock_lxmf: Mock, mock_rns_service: Mock, mock_platformdirs: Mock
    ) -> None:
        """Test initialize creates LXMF router instance."""
        mock_router = Mock()
        mock_delivery_dest = Mock()
        mock_delivery_dest.hexhash = "a1b2c3d4e5f67890abcdef1234567890"
        mock_delivery_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_router.register_delivery_identity.return_value = mock_delivery_dest
        mock_lxmf.LXMRouter.return_value = mock_router

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        result = service.initialize(mock_identity)

        assert result is True
        assert service.is_initialized is True
        assert service.router is mock_router

    def test_initialize_returns_false_on_failure(
        self, mock_lxmf: Mock, mock_rns_service: Mock, mock_platformdirs: Mock
    ) -> None:
        """Test initialize returns False when LXMF fails to start."""
        # Make router creation fail
        mock_lxmf.LXMRouter.side_effect = Exception("LXMF init failed")

        service = LXMFService()
        mock_identity = Mock()
        result = service.initialize(mock_identity)

        assert result is False
        assert service.is_initialized is False
        assert service.router is None

    def test_initialize_is_idempotent(
        self, mock_lxmf: Mock, mock_rns_service: Mock, mock_platformdirs: Mock
    ) -> None:
        """Test multiple initialize calls don't break the service."""
        mock_router = Mock()
        mock_delivery_dest = Mock()
        mock_delivery_dest.hexhash = "a1b2c3d4e5f67890abcdef1234567890"
        mock_delivery_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_router.register_delivery_identity.return_value = mock_delivery_dest
        mock_lxmf.LXMRouter.return_value = mock_router

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"

        result1 = service.initialize(mock_identity)
        result2 = service.initialize(mock_identity)

        assert result1 is True
        assert result2 is True
        assert service.is_initialized is True


class TestLXMFServiceSendMessage:
    """Tests for sending LXMF messages."""

    def test_send_message_requires_initialization(self) -> None:
        """Test send_message returns None if not initialized."""
        service = LXMFService()

        result = service.send_message(
            destination_hash="a1b2c3d4e5f6",
            payload={"type": "status_request"},
        )

        assert result is None

    def test_send_message_creates_lxmf_message(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        mock_rns_service: Mock,
        mock_platformdirs: Mock,
    ) -> None:
        """Test send_message creates and sends LXMF message."""
        mock_router = Mock()
        mock_delivery_dest = Mock()
        mock_delivery_dest.hexhash = "a1b2c3d4e5f67890abcdef1234567890"
        mock_delivery_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_router.register_delivery_identity.return_value = mock_delivery_dest
        mock_lxmf.LXMRouter.return_value = mock_router

        mock_message = Mock()
        mock_message.hash = bytes.fromhex("deadbeef12345678")
        mock_lxmf.LXMessage.return_value = mock_message

        # Mock RNS.Identity.recall to return a valid identity with proper hash
        mock_dest_identity = Mock()
        mock_dest_identity.hash = bytes.fromhex("c1d2e3f4a5b67890")
        mock_rns.Identity.recall.return_value = mock_dest_identity

        # Mock path exists
        mock_rns.Transport.has_path.return_value = True

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        result = service.send_message("a1b2c3d4", {"type": "test"})

        assert result is not None
        mock_router.handle_outbound.assert_called_once_with(mock_message)

    def test_send_message_handles_error(
        self, mock_lxmf: Mock, mock_rns_service: Mock, mock_platformdirs: Mock
    ) -> None:
        """Test send_message handles errors gracefully."""
        mock_router = Mock()
        mock_delivery_dest = Mock()
        mock_delivery_dest.hexhash = "a1b2c3d4e5f67890abcdef1234567890"
        mock_delivery_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_router.register_delivery_identity.return_value = mock_delivery_dest
        mock_lxmf.LXMRouter.return_value = mock_router

        # Make message creation fail
        mock_lxmf.LXMessage.side_effect = Exception("Message creation failed")

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        result = service.send_message("a1b2c3d4", {"type": "test"})

        assert result is None

    def test_send_message_sends_even_without_direct_path(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        mock_rns_service: Mock,
        mock_platformdirs: Mock,
    ) -> None:
        """Test send_message sends via propagation when no direct path exists."""
        mock_router = Mock()
        mock_delivery_dest = Mock()
        mock_delivery_dest.hexhash = "a1b2c3d4e5f67890abcdef1234567890"
        mock_delivery_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_router.register_delivery_identity.return_value = mock_delivery_dest
        mock_lxmf.LXMRouter.return_value = mock_router

        mock_message = Mock()
        mock_message.hash = bytes.fromhex("deadbeef12345678")
        mock_lxmf.LXMessage.return_value = mock_message

        # Mock RNS.Identity.recall to return a valid identity with proper hash
        mock_dest_identity = Mock()
        mock_dest_identity.hash = bytes.fromhex("c1d2e3f4a5b67890")
        mock_rns.Identity.recall.return_value = mock_dest_identity

        # Mock no direct path exists - service will use propagated delivery
        mock_rns.Transport.has_path.return_value = False

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        result = service.send_message("a1b2c3d4", {"type": "test"})

        # With AUTO delivery, message is sent via propagation even without direct path
        assert result is not None
        mock_router.handle_outbound.assert_called_once()

    def test_send_message_requests_path_when_missing(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        mock_rns_service: Mock,
        mock_platformdirs: Mock,
    ) -> None:
        """Test send_message calls request_path when path is missing."""
        mock_router = Mock()
        mock_lxmf.LXMRouter.return_value = mock_router

        mock_message = Mock()
        mock_message.hash = bytes.fromhex("deadbeef12345678")
        mock_lxmf.LXMessage.return_value = mock_message
        mock_lxmf.FIELD_RENDERER = 0x0F
        mock_lxmf.RENDERER_PLAIN = 0x00

        # Mock RNS.Identity.recall to return a valid identity with proper hash
        mock_dest_identity = Mock()
        mock_dest_identity.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_rns.Identity.recall.return_value = mock_dest_identity

        # Mock destination with hash attribute
        mock_dest = Mock()
        mock_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_rns.Destination.return_value = mock_dest

        # Mock no path exists
        mock_rns.Transport.has_path.return_value = False

        # Create service and manually set initialized state (bypass real init)
        service = LXMFService()
        service._router = mock_router
        service._identity = Mock()
        service._initialized = True

        service.send_message("a1b2c3d4", {"type": "test"})

        # Should have requested path (via _ensure_path)
        mock_rns.Transport.request_path.assert_called_once_with(mock_dest.hash)


class TestLXMFServiceSendWithRetry:
    """Tests for send_with_retry method."""

    def test_send_with_retry_requires_initialization(self) -> None:
        """Test send_with_retry returns False if not initialized."""
        service = LXMFService()

        result = service.send_with_retry(
            destination_hash="a1b2c3d4e5f6",
            payload={"type": "status_request"},
        )

        assert result is False

    def test_send_with_retry_sends_when_path_exists(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        mock_rns_service: Mock,
        mock_platformdirs: Mock,
    ) -> None:
        """Test send_with_retry sends immediately when path exists."""
        mock_router = Mock()
        mock_delivery_dest = Mock()
        mock_delivery_dest.hexhash = "a1b2c3d4e5f67890abcdef1234567890"
        mock_delivery_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_router.register_delivery_identity.return_value = mock_delivery_dest
        mock_lxmf.LXMRouter.return_value = mock_router

        mock_message = Mock()
        mock_lxmf.LXMessage.return_value = mock_message

        # Mock RNS.Identity.recall to return a valid identity with proper hash
        mock_dest_identity = Mock()
        mock_dest_identity.hash = bytes.fromhex("c1d2e3f4a5b67890")
        mock_rns.Identity.recall.return_value = mock_dest_identity

        # Mock destination with hash attribute for _ensure_path
        mock_dest = Mock()
        mock_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_rns.Destination.return_value = mock_dest

        # Mock path exists immediately
        mock_rns.Transport.has_path.return_value = True

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        result = service.send_with_retry("a1b2c3d4", {"type": "test"}, max_wait=1.0)

        assert result is True
        mock_router.handle_outbound.assert_called_once_with(mock_message)

    @patch("styrened.services.lxmf_service.time")
    def test_send_with_retry_waits_for_path(
        self,
        mock_time: Mock,
        mock_lxmf: Mock,
        mock_rns: Mock,
        mock_rns_service: Mock,
        mock_platformdirs: Mock,
    ) -> None:
        """Test send_with_retry waits for path and sends when available."""
        mock_router = Mock()
        mock_delivery_dest = Mock()
        mock_delivery_dest.hexhash = "a1b2c3d4e5f67890abcdef1234567890"
        mock_delivery_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_router.register_delivery_identity.return_value = mock_delivery_dest
        mock_lxmf.LXMRouter.return_value = mock_router

        mock_message = Mock()
        mock_lxmf.LXMessage.return_value = mock_message

        # Mock RNS.Identity.recall to return a valid identity with proper hash
        mock_dest_identity = Mock()
        mock_dest_identity.hash = bytes.fromhex("c1d2e3f4a5b67890")
        mock_rns.Identity.recall.return_value = mock_dest_identity

        # Mock destination with hash attribute for _ensure_path
        mock_dest = Mock()
        mock_dest.hash = bytes.fromhex("a1b2c3d4e5f67890")
        mock_rns.Destination.return_value = mock_dest

        # Mock path becomes available after some time
        # Calls: _ensure_path(False), loop check(True)
        mock_rns.Transport.has_path.side_effect = [False, True]

        # Mock time to simulate passage of time
        mock_time.monotonic.side_effect = [
            0.0,
            0.0,
            2.0,
            2.0,
        ]  # Start, check, after sleep, final check
        mock_time.sleep = Mock()

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        result = service.send_with_retry(
            "a1b2c3d4", {"type": "test"}, max_wait=10.0, check_interval=2.0
        )

        assert result is True
        mock_router.handle_outbound.assert_called_once_with(mock_message)
        # Should have slept while waiting
        mock_time.sleep.assert_called()

    @patch("styrened.services.lxmf_service.time")
    def test_send_with_retry_returns_false_on_timeout(
        self,
        mock_time: Mock,
        mock_lxmf: Mock,
        mock_rns: Mock,
        mock_rns_service: Mock,
        mock_platformdirs: Mock,
    ) -> None:
        """Test send_with_retry returns False when path timeout occurs."""
        mock_router = Mock()
        mock_lxmf.LXMRouter.return_value = mock_router

        # Mock RNS.Identity.recall to return a valid identity
        mock_dest_identity = Mock()
        mock_rns.Identity.recall.return_value = mock_dest_identity

        # Mock path never becomes available
        mock_rns.Transport.has_path.return_value = False

        # Mock time to simulate timeout
        mock_time.monotonic.side_effect = [
            0.0,
            0.0,
            2.0,
            4.0,
            6.0,
        ]  # Exceeds max_wait of 5.0
        mock_time.sleep = Mock()

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        result = service.send_with_retry(
            "a1b2c3d4", {"type": "test"}, max_wait=5.0, check_interval=2.0
        )

        assert result is False
        # Should not have attempted to send
        mock_router.handle_outbound.assert_not_called()

    def test_send_with_retry_fails_for_unknown_identity(
        self,
        mock_lxmf: Mock,
        mock_rns: Mock,
        mock_rns_service: Mock,
        mock_platformdirs: Mock,
    ) -> None:
        """Test send_with_retry returns False when identity is not known."""
        mock_router = Mock()
        mock_lxmf.LXMRouter.return_value = mock_router

        # Mock RNS.Identity.recall returns None (identity not known)
        mock_rns.Identity.recall.return_value = None

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        result = service.send_with_retry("a1b2c3d4", {"type": "test"})

        assert result is False


class TestLXMFServiceReceiveMessage:
    """Tests for receiving LXMF messages."""

    def test_register_callback(
        self, mock_lxmf: Mock, mock_rns_service: Mock, mock_platformdirs: Mock
    ) -> None:
        """Test register_callback stores callback function."""
        mock_router = Mock()
        mock_lxmf.LXMRouter.return_value = mock_router

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        # Register callback
        callback = Mock()
        service.register_callback(callback)

        # Verify callback stored (callbacks are stored as (callback, raw_mode) tuples)
        assert len(service._message_callbacks) >= 1
        assert service._message_callbacks[-1] == (callback, False)

    def test_incoming_message_invokes_callback(
        self, mock_lxmf: Mock, mock_rns_service: Mock, mock_platformdirs: Mock
    ) -> None:
        """Test incoming LXMF message invokes registered callback."""
        mock_router = Mock()
        mock_lxmf.LXMRouter.return_value = mock_router

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        # Register callback
        callback = Mock()
        service.register_callback(callback)

        # Simulate incoming message
        source_hash = "a1b2c3d4e5f6"
        payload = {"type": "status_response", "uptime": 12345}

        mock_message = Mock()
        mock_message.source_hash = bytes.fromhex(source_hash)
        mock_message.content = json.dumps(payload).encode("utf-8")

        # Trigger internal message handler
        service._handle_lxmf_message(mock_message)

        # Verify callback invoked
        callback.assert_called_once_with(source_hash, payload)

    def test_incoming_message_without_callback_does_not_error(
        self, mock_lxmf: Mock, mock_rns_service: Mock, mock_platformdirs: Mock
    ) -> None:
        """Test incoming message without callback doesn't raise error."""
        mock_router = Mock()
        mock_lxmf.LXMRouter.return_value = mock_router

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        # Don't register callback

        # Simulate incoming message
        mock_message = Mock()
        mock_message.source_hash = bytes.fromhex("a1b2c3d4e5f6")
        mock_message.content = json.dumps({"type": "test"}).encode("utf-8")

        # Should not raise error
        service._handle_lxmf_message(mock_message)


class TestLXMFServiceShutdown:
    """Tests for service shutdown."""

    def test_shutdown_when_not_initialized(self) -> None:
        """Test shutdown works when service never initialized."""
        service = LXMFService()
        # Should not raise exception
        service.shutdown()
        assert service.is_initialized is False

    def test_shutdown_cleans_up_router(
        self, mock_lxmf: Mock, mock_rns_service: Mock, mock_platformdirs: Mock
    ) -> None:
        """Test shutdown cleans up LXMF router instance."""
        mock_router = Mock()
        mock_lxmf.LXMRouter.return_value = mock_router

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        # Shutdown
        service.shutdown()

        assert service.is_initialized is False
        assert service.router is None

    def test_shutdown_is_idempotent(
        self, mock_lxmf: Mock, mock_rns_service: Mock, mock_platformdirs: Mock
    ) -> None:
        """Test multiple shutdown calls don't break the service."""
        mock_router = Mock()
        mock_lxmf.LXMRouter.return_value = mock_router

        service = LXMFService()
        mock_identity = Mock()
        mock_identity.hexhash = "a1b2c3d4e5f67890"
        service.initialize(mock_identity)

        # Shutdown twice
        service.shutdown()
        service.shutdown()

        assert service.is_initialized is False


class TestLXMFServicePropagationSync:
    """Tests for propagation node message sync."""

    def test_sync_when_not_initialized(self) -> None:
        """Sync should return False when service not initialized."""
        service = LXMFService()
        assert service.request_messages_from_propagation_node() is False

    def test_sync_calls_router(self) -> None:
        """Sync should call router.request_messages_from_propagation_node."""
        service = LXMFService()

        mock_router = Mock()
        mock_identity = Mock()

        # Set internal state directly to avoid full init complexity
        service._initialized = True
        service._router = mock_router
        service._identity = mock_identity

        result = service.request_messages_from_propagation_node()

        assert result is True
        mock_router.request_messages_from_propagation_node.assert_called_once_with(
            mock_identity
        )

        # Cleanup
        service._initialized = False
        service._router = None
        service._identity = None
