"""Tests for RNS LocalInterface reconnection handling.

These tests verify that the RNSService and LXMFService properly handle
LocalInterface disconnections and reconnections without spamming
"already registered destination" errors.
"""
from __future__ import annotations


import threading
import time
from unittest.mock import MagicMock, patch


class TestRNSServiceReconnection:
    """Tests for RNSService interface monitoring and reconnection handling."""

    def test_reconnect_callback_registration(self):
        """Test that reconnect callbacks can be registered."""
        from styrened.services.rns_service import RNSService

        service = RNSService()
        callback = MagicMock()

        service.register_reconnect_callback(callback)

        assert len(service._reconnect_callbacks) == 1
        assert service._reconnect_callbacks[0] is callback

    def test_multiple_reconnect_callbacks(self):
        """Test that multiple callbacks can be registered."""
        from styrened.services.rns_service import RNSService

        service = RNSService()
        callback1 = MagicMock()
        callback2 = MagicMock()

        service.register_reconnect_callback(callback1)
        service.register_reconnect_callback(callback2)

        assert len(service._reconnect_callbacks) == 2

    def test_handle_reconnection_clears_destinations(self):
        """Test that reconnection clears cached destinations."""
        from styrened.services.rns_service import RNSService

        service = RNSService()
        # Simulate cached destinations
        service._destinations = {
            "styrene_node.operator": MagicMock(),
            "lxmf.delivery": MagicMock(),
        }

        service._handle_reconnection("LocalInterface", "rns/default")

        assert len(service._destinations) == 0

    def test_handle_reconnection_invokes_callbacks(self):
        """Test that reconnection invokes all registered callbacks."""
        from styrened.services.rns_service import RNSService

        service = RNSService()
        callback1 = MagicMock()
        callback2 = MagicMock()
        service._reconnect_callbacks = [callback1, callback2]

        service._handle_reconnection("LocalInterface", "rns/default")

        callback1.assert_called_once()
        callback2.assert_called_once()

    def test_handle_reconnection_continues_on_callback_error(self):
        """Test that one failing callback doesn't prevent others from running."""
        from styrened.services.rns_service import RNSService

        service = RNSService()
        callback1 = MagicMock(side_effect=Exception("Callback failed"))
        callback2 = MagicMock()
        service._reconnect_callbacks = [callback1, callback2]

        # Should not raise
        service._handle_reconnection("LocalInterface", "rns/default")

        callback1.assert_called_once()
        callback2.assert_called_once()

    def test_capture_interface_states(self):
        """Test that interface states are captured correctly."""
        from styrened.services.rns_service import RNSService

        service = RNSService()

        # Mock RNS.Transport.interfaces
        mock_interface = MagicMock()
        mock_interface.name = "LocalInterface[rns/default]"
        mock_interface.online = True

        with patch("RNS.Transport") as mock_transport:
            mock_transport.interfaces = [mock_interface]
            service._capture_interface_states()

        assert "LocalInterface[rns/default]" in service._last_interface_states
        assert service._last_interface_states["LocalInterface[rns/default]"] is True

    def test_check_interface_states_detects_disconnect(self):
        """Test that interface disconnect is detected."""
        from styrened.services.rns_service import RNSService

        service = RNSService()
        service._last_interface_states = {"LocalInterface[rns/default]": True}

        # Mock interface now offline
        mock_interface = MagicMock()
        mock_interface.name = "LocalInterface[rns/default]"
        mock_interface.online = False
        type(mock_interface).__name__ = "LocalInterface"

        with patch("RNS.Transport") as mock_transport:
            mock_transport.interfaces = [mock_interface]
            service._check_interface_states()

        # Should have recorded disconnect time for this interface
        assert "LocalInterface[rns/default]" in service._disconnect_times
        assert service._disconnect_times["LocalInterface[rns/default]"] is not None
        # State should be updated
        assert service._last_interface_states["LocalInterface[rns/default]"] is False

    def test_check_interface_states_handles_reconnect(self):
        """Test that interface reconnection triggers cache clearing."""
        from styrened.services.rns_service import RNSService

        service = RNSService()
        iface_name = "LocalInterface[rns/default]"
        service._last_interface_states = {iface_name: False}
        service._disconnect_times[iface_name] = time.monotonic() - 5.0  # 5 seconds ago
        service._destinations = {"test": MagicMock()}
        callback = MagicMock()
        service._reconnect_callbacks = [callback]

        # Mock interface now online
        mock_interface = MagicMock()
        mock_interface.name = iface_name
        mock_interface.online = True
        type(mock_interface).__name__ = "LocalInterface"

        with patch("RNS.Transport") as mock_transport:
            mock_transport.interfaces = [mock_interface]
            service._check_interface_states()

        # Destinations should be cleared
        assert len(service._destinations) == 0
        # Callback should be invoked
        callback.assert_called_once()
        # Disconnect time should be cleared for this interface
        assert iface_name not in service._disconnect_times

    def test_shutdown_stops_monitor(self):
        """Test that shutdown stops the interface monitor thread."""
        from styrened.services.rns_service import RNSService

        service = RNSService()
        service._initialized = True
        service._reticulum = MagicMock()

        # Create a mock monitor thread
        mock_thread = MagicMock()
        service._interface_monitor_thread = mock_thread
        service._monitor_stop_event = threading.Event()

        service.shutdown()

        # Stop event should be set
        assert service._monitor_stop_event.is_set()
        # Thread should have been joined (before being set to None)
        mock_thread.join.assert_called_once()
        # Thread reference should be cleared
        assert service._interface_monitor_thread is None

    def test_shutdown_clears_callbacks(self):
        """Test that shutdown clears reconnect callbacks."""
        from styrened.services.rns_service import RNSService

        service = RNSService()
        service._initialized = True
        service._reticulum = MagicMock()
        service._reconnect_callbacks = [MagicMock(), MagicMock()]

        service.shutdown()

        assert len(service._reconnect_callbacks) == 0


class TestLXMFServiceReconnection:
    """Tests for LXMFService reconnection handling."""

    def test_handle_reconnection_clears_delivery_destination(self):
        """Test that LXMF reconnection clears cached delivery destination."""
        from styrened.services.lxmf_service import LXMFService

        service = LXMFService()
        mock_dest = MagicMock()
        mock_dest.hexhash = "abcd1234567890ef"
        service._delivery_destination = mock_dest

        service._handle_reconnection()

        assert service._delivery_destination is None

    def test_handle_reconnection_preserves_router(self):
        """Test that LXMF reconnection preserves the router instance."""
        from styrened.services.lxmf_service import LXMFService

        service = LXMFService()
        mock_router = MagicMock()
        service._router = mock_router
        mock_dest = MagicMock()
        mock_dest.hexhash = "abcd1234567890ef"
        service._delivery_destination = mock_dest

        service._handle_reconnection()

        # Router should still be there
        assert service._router is mock_router

    def test_handle_reconnection_noop_when_no_destination(self):
        """Test that LXMF reconnection is safe when no destination cached."""
        from styrened.services.lxmf_service import LXMFService

        service = LXMFService()
        service._delivery_destination = None

        # Should not raise
        service._handle_reconnection()

        assert service._delivery_destination is None
