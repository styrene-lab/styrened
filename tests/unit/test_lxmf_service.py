"""Unit tests for LXMFService identity resolution.

Tests the critical multi-strategy identity resolution that determines
whether messages can be delivered successfully.
"""
from __future__ import annotations


from unittest.mock import MagicMock, patch

import pytest


class TestIdentityResolution:
    """Tests for _resolve_identity multi-strategy lookup."""

    @pytest.fixture
    def mock_rns(self):
        """Create a mock RNS module."""
        mock = MagicMock()
        mock.Identity = MagicMock()
        mock.Identity.recall = MagicMock(return_value=None)
        mock.Transport = MagicMock()
        mock.Transport.has_path = MagicMock(return_value=True)
        mock.Destination = MagicMock()
        return mock

    @pytest.fixture
    def mock_lxmf(self):
        """Create a mock LXMF module."""
        mock = MagicMock()
        mock.LXMRouter = MagicMock()
        mock.LXMessage = MagicMock()
        mock.APP_NAME = "lxmf"
        return mock

    @pytest.fixture
    def service(self, mock_rns, mock_lxmf):
        """Create an LXMFService with mocked dependencies."""
        with patch.dict("sys.modules", {"RNS": mock_rns, "LXMF": mock_lxmf}):
            with patch("styrened.services.lxmf_service.LXMF_AVAILABLE", True):
                with patch("styrened.services.lxmf_service.RNS", mock_rns):
                    with patch("styrened.services.lxmf_service.LXMF", mock_lxmf):
                        from styrened.services.lxmf_service import LXMFService

                        service = LXMFService()
                        # Manually set initialized state for testing
                        service._initialized = True
                        service._router = MagicMock()
                        service._identity = MagicMock()
                        return service

    def test_strategy_1_direct_recall_success(self, service, mock_rns):
        """Strategy 1: Direct RNS.Identity.recall() succeeds."""
        dest_hash = "a" * 32
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = "b" * 32

        # Direct recall succeeds
        mock_rns.Identity.recall.return_value = mock_identity

        with patch("styrened.services.lxmf_service.RNS", mock_rns):
            result = service._resolve_identity(dest_hash)

        assert result == mock_identity
        mock_rns.Identity.recall.assert_called_once()

    def test_strategy_2_nodestore_operator_lookup(self, service, mock_rns):
        """Strategy 2: NodeStore lookup by operator destination hash."""
        dest_hash = "a" * 32
        identity_hash = "b" * 32
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = identity_hash

        # Direct recall fails
        mock_rns.Identity.recall.side_effect = [
            None,  # Strategy 1 fails
            mock_identity,  # Strategy found via NodeStore
        ]

        mock_store = MagicMock()
        mock_store.get_identity_for_destination.return_value = identity_hash
        mock_store.get_identity_for_lxmf_destination.return_value = None

        with patch("styrened.services.lxmf_service.RNS", mock_rns):
            with patch(
                "styrened.services.node_store.get_node_store",
                return_value=mock_store,
            ):
                result = service._resolve_identity(dest_hash)

        assert result == mock_identity
        mock_store.get_identity_for_destination.assert_called_once_with(dest_hash)

    def test_strategy_3_nodestore_lxmf_lookup(self, service, mock_rns):
        """Strategy 3: NodeStore lookup by LXMF destination hash."""
        dest_hash = "a" * 32
        identity_hash = "b" * 32
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = identity_hash

        # Direct recall fails, then succeeds for identity hash
        mock_rns.Identity.recall.side_effect = [
            None,  # Strategy 1 fails
            mock_identity,  # Strategy found via NodeStore LXMF lookup
        ]

        mock_store = MagicMock()
        mock_store.get_identity_for_destination.return_value = None
        mock_store.get_identity_for_lxmf_destination.return_value = identity_hash

        with patch("styrened.services.lxmf_service.RNS", mock_rns):
            with patch(
                "styrened.services.node_store.get_node_store",
                return_value=mock_store,
            ):
                result = service._resolve_identity(dest_hash)

        assert result == mock_identity
        mock_store.get_identity_for_lxmf_destination.assert_called_once_with(dest_hash)

    def test_strategy_4_destination_is_identity_hash(self, service, mock_rns):
        """Strategy 4: destination_hash IS the identity hash."""
        dest_hash = "a" * 32
        mock_identity = MagicMock()
        mock_identity.hash.hex.return_value = dest_hash

        # Define a function to return the right value based on call args
        def recall_side_effect(dest_bytes, from_identity_hash=False):
            if from_identity_hash:
                return mock_identity
            return None

        mock_rns.Identity.recall.side_effect = recall_side_effect

        mock_store = MagicMock()
        mock_store.get_identity_for_destination.return_value = None
        mock_store.get_identity_for_lxmf_destination.return_value = None

        with patch("styrened.services.lxmf_service.RNS", mock_rns):
            with patch(
                "styrened.services.node_store.get_node_store",
                return_value=mock_store,
            ):
                result = service._resolve_identity(dest_hash)

        assert result == mock_identity
        # Verify it was called with from_identity_hash=True
        calls = mock_rns.Identity.recall.call_args_list
        assert any(call.kwargs.get("from_identity_hash") is True for call in calls)

    def test_all_strategies_fail_returns_none(self, service, mock_rns):
        """All strategies failing should return None."""
        dest_hash = "a" * 32

        # All recalls fail
        mock_rns.Identity.recall.return_value = None

        mock_store = MagicMock()
        mock_store.get_identity_for_destination.return_value = None
        mock_store.get_identity_for_lxmf_destination.return_value = None

        with patch("styrened.services.lxmf_service.RNS", mock_rns):
            with patch(
                "styrened.services.node_store.get_node_store",
                return_value=mock_store,
            ):
                result = service._resolve_identity(dest_hash)

        assert result is None

    def test_nodestore_exception_handled(self, service, mock_rns):
        """NodeStore exceptions should not crash resolution."""
        dest_hash = "a" * 32
        mock_identity = MagicMock()

        # Strategy 1 fails, Strategy 4 succeeds
        mock_rns.Identity.recall.side_effect = [
            None,  # Strategy 1 fails
            mock_identity,  # Strategy 4 succeeds
        ]

        with patch("styrened.services.lxmf_service.RNS", mock_rns):
            with patch(
                "styrened.services.node_store.get_node_store",
                side_effect=Exception("Database error"),
            ):
                result = service._resolve_identity(dest_hash)

        # Should fall through to Strategy 4
        assert result == mock_identity


class TestCallbackRegistration:
    """Tests for message callback registration."""

    @pytest.fixture
    def service(self):
        """Create an LXMFService without RNS dependencies."""
        with patch("styrened.services.lxmf_service.LXMF_AVAILABLE", False):
            from styrened.services.lxmf_service import LXMFService

            return LXMFService()

    def test_multiple_callbacks_registered(self, service):
        """Multiple callbacks can be registered."""
        callback1 = MagicMock()
        callback2 = MagicMock()

        service.register_callback(callback1)
        service.register_callback(callback2)

        assert len(service._message_callbacks) == 2

    def test_raw_mode_callback_registration(self, service):
        """Raw mode callbacks are tracked separately."""
        parsed_callback = MagicMock()
        raw_callback = MagicMock()

        service.register_callback(parsed_callback, raw_mode=False)
        service.register_callback(raw_callback, raw_mode=True)

        assert len(service._message_callbacks) == 2
        assert service._message_callbacks[0] == (parsed_callback, False)
        assert service._message_callbacks[1] == (raw_callback, True)


class TestMessageHandling:
    """Tests for incoming message handling."""

    @pytest.fixture
    def service(self):
        """Create an LXMFService without RNS dependencies."""
        with patch("styrened.services.lxmf_service.LXMF_AVAILABLE", False):
            from styrened.services.lxmf_service import LXMFService

            return LXMFService()

    def test_no_callbacks_logs_warning(self, service, caplog):
        """No registered callbacks should log a warning."""
        import logging

        mock_message = MagicMock()
        mock_message.source_hash.hex.return_value = "a" * 32
        mock_message.content = b'{"type": "test"}'

        with caplog.at_level(logging.WARNING):
            service._handle_lxmf_message(mock_message)

        assert "No message callbacks registered" in caplog.text

    def test_parsed_callback_receives_source_and_payload(self, service):
        """Parsed mode callback receives (source_hash, payload)."""
        callback = MagicMock()
        service.register_callback(callback, raw_mode=False)

        mock_message = MagicMock()
        mock_message.source_hash.hex.return_value = "abc123"
        mock_message.content = b'{"type": "test", "data": 42}'

        service._handle_lxmf_message(mock_message)

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "abc123"
        assert args[1]["type"] == "test"
        assert args[1]["data"] == 42

    def test_raw_callback_receives_lxmf_message(self, service):
        """Raw mode callback receives the raw LXMF message."""
        callback = MagicMock()
        service.register_callback(callback, raw_mode=True)

        mock_message = MagicMock()
        mock_message.source_hash.hex.return_value = "abc123"
        mock_message.content = b'{"type": "test"}'

        service._handle_lxmf_message(mock_message)

        callback.assert_called_once_with(mock_message)

    def test_plain_text_normalized_to_chat_payload(self, service):
        """Non-JSON content should be normalized to chat payload for Sideband compatibility."""
        parsed_callback = MagicMock()
        raw_callback = MagicMock()

        service.register_callback(parsed_callback, raw_mode=False)
        service.register_callback(raw_callback, raw_mode=True)

        mock_message = MagicMock()
        mock_message.source_hash.hex.return_value = "abc123"
        mock_message.content = b"Hello from Sideband"
        mock_message.fields = {}
        mock_message.title = None

        service._handle_lxmf_message(mock_message)

        # Raw callback should still be called
        raw_callback.assert_called_once_with(mock_message)
        # Parsed callback should be called with normalized payload
        parsed_callback.assert_called_once()
        call_args = parsed_callback.call_args
        assert call_args[0][0] == "abc123"  # source_hash
        payload = call_args[0][1]
        assert payload["type"] == "chat"
        assert payload["content"] == "Hello from Sideband"
        assert payload["protocol"] == ""  # Empty for plain text

    def test_callback_exception_does_not_stop_others(self, service):
        """Exception in one callback should not prevent others."""
        failing_callback = MagicMock(side_effect=Exception("Callback failed"))
        working_callback = MagicMock()

        service.register_callback(failing_callback, raw_mode=True)
        service.register_callback(working_callback, raw_mode=True)

        mock_message = MagicMock()
        mock_message.source_hash.hex.return_value = "abc123"
        mock_message.content = b'{"type": "test"}'

        # Should not raise
        service._handle_lxmf_message(mock_message)

        # Both callbacks were attempted
        failing_callback.assert_called_once()
        working_callback.assert_called_once()


class TestServiceInitialization:
    """Tests for service initialization and shutdown."""

    def test_service_starts_uninitialized(self):
        """Service should start in uninitialized state."""
        with patch("styrened.services.lxmf_service.LXMF_AVAILABLE", False):
            from styrened.services.lxmf_service import LXMFService

            service = LXMFService()

            assert not service.is_initialized
            assert service.router is None
            assert service.delivery_destination is None

    def test_initialize_without_lxmf_fails(self):
        """Initialize should fail if LXMF not available."""
        with patch("styrened.services.lxmf_service.LXMF_AVAILABLE", False):
            from styrened.services.lxmf_service import LXMFService

            service = LXMFService()
            mock_identity = MagicMock()

            result = service.initialize(mock_identity)

            assert result is False
            assert not service.is_initialized

    def test_shutdown_clears_state(self):
        """Shutdown should clear all state."""
        with patch("styrened.services.lxmf_service.LXMF_AVAILABLE", False):
            from styrened.services.lxmf_service import LXMFService

            service = LXMFService()
            service._initialized = True
            service._router = MagicMock()
            service._identity = MagicMock()

            service.shutdown()

            assert not service.is_initialized
            assert service._router is None
            assert service._identity is None


class TestMockLXMFService:
    """Tests for the MockLXMFService test helper."""

    def test_mock_service_tracks_sent_messages(self):
        """MockLXMFService should track sent messages."""
        from styrened.services.lxmf_service import DeliveryMethod, MockLXMFService

        service = MockLXMFService()

        service.send_message("dest1", {"type": "test1"})
        service.send_message("dest2", {"type": "test2"})

        assert len(service.sent_messages) == 2
        # Now includes delivery method as third element
        assert service.sent_messages[0] == ("dest1", {"type": "test1"}, DeliveryMethod.DIRECT)
        assert service.sent_messages[1] == ("dest2", {"type": "test2"}, DeliveryMethod.DIRECT)

    def test_mock_service_can_simulate_failure(self):
        """MockLXMFService can simulate send failures."""
        from styrened.services.lxmf_service import MockLXMFService

        service = MockLXMFService()
        service.send_should_fail = True

        result = service.send_message("dest", {"type": "test"})

        assert result is None
        assert len(service.sent_messages) == 0

    def test_mock_service_can_simulate_receive(self):
        """MockLXMFService can simulate receiving messages."""
        from styrened.services.lxmf_service import MockLXMFService

        service = MockLXMFService()
        callback = MagicMock()
        service.register_callback(callback)

        service.simulate_receive("source123", {"type": "test", "data": "hello"})

        callback.assert_called_once_with("source123", {"type": "test", "data": "hello"})
