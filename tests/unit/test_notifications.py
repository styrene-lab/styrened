"""Unit tests for NotificationService and backends."""
from __future__ import annotations


from unittest.mock import AsyncMock, MagicMock

import pytest

from styrened.services.notifications import (
    CallbackBackend,
    IPCEventBackend,
    NotificationBackend,
    NotificationEvent,
    NotificationService,
)


def _make_event(**kwargs):
    """Create a test NotificationEvent with defaults."""
    defaults = {
        "event_type": "new_message",
        "peer_hash": "abcd1234abcd1234",
        "message_id": 1,
        "content": "Hello",
        "timestamp": 1000.0,
        "status": "received",
        "is_outgoing": False,
    }
    defaults.update(kwargs)
    return NotificationEvent(**defaults)


class TestNotificationEvent:
    """Tests for NotificationEvent dataclass."""

    def test_event_stores_all_fields(self):
        """NotificationEvent stores all provided fields."""
        event = _make_event(content="Test message")
        assert event.event_type == "new_message"
        assert event.peer_hash == "abcd1234abcd1234"
        assert event.content == "Test message"
        assert event.message_id == 1

    def test_event_metadata_defaults_to_empty_dict(self):
        """NotificationEvent metadata defaults to empty dict."""
        event = _make_event()
        assert event.metadata == {}

    def test_event_metadata_can_be_set(self):
        """NotificationEvent metadata accepts arbitrary data."""
        event = _make_event(metadata={"delivery_method": "direct"})
        assert event.metadata["delivery_method"] == "direct"


class TestCallbackBackend:
    """Tests for in-process callback backend."""

    @pytest.mark.asyncio
    async def test_dispatch_invokes_registered_callback(self):
        """dispatch calls all registered callbacks with the event."""
        backend = CallbackBackend()
        received = []
        backend.register(lambda event: received.append(event))

        event = _make_event()
        await backend.dispatch(event)
        assert len(received) == 1
        assert received[0] is event

    @pytest.mark.asyncio
    async def test_dispatch_invokes_multiple_callbacks(self):
        """dispatch calls all registered callbacks."""
        backend = CallbackBackend()
        results = []
        backend.register(lambda e: results.append("cb1"))
        backend.register(lambda e: results.append("cb2"))

        await backend.dispatch(_make_event())
        assert results == ["cb1", "cb2"]

    @pytest.mark.asyncio
    async def test_dispatch_handles_callback_errors(self):
        """dispatch continues after callback errors."""
        backend = CallbackBackend()
        results = []

        def bad_callback(event):
            raise ValueError("Oops")

        backend.register(bad_callback)
        backend.register(lambda e: results.append("ok"))

        await backend.dispatch(_make_event())
        assert results == ["ok"]

    @pytest.mark.asyncio
    async def test_dispatch_supports_async_callbacks(self):
        """dispatch awaits async callbacks."""
        backend = CallbackBackend()
        received = []

        async def async_cb(event):
            received.append(event.content)

        backend.register(async_cb)
        await backend.dispatch(_make_event(content="Async!"))
        assert received == ["Async!"]

    def test_register_prevents_duplicates(self):
        """register ignores duplicate callback registrations."""
        backend = CallbackBackend()
        cb = lambda e: None  # noqa: E731
        backend.register(cb)
        backend.register(cb)
        assert len(backend._callbacks) == 1

    def test_unregister_removes_callback(self):
        """unregister removes a previously registered callback."""
        backend = CallbackBackend()
        cb = lambda e: None  # noqa: E731
        backend.register(cb)
        backend.unregister(cb)
        assert len(backend._callbacks) == 0

    def test_unregister_ignores_unknown_callback(self):
        """unregister silently ignores unknown callbacks."""
        backend = CallbackBackend()
        backend.unregister(lambda e: None)  # Should not raise

    @pytest.mark.asyncio
    async def test_dispatch_returns_true_with_no_callbacks(self):
        """dispatch returns True even with no callbacks registered."""
        backend = CallbackBackend()
        result = await backend.dispatch(_make_event())
        assert result is True


class TestIPCEventBackend:
    """Tests for IPC event broadcasting backend."""

    @pytest.mark.asyncio
    async def test_dispatch_calls_broadcast_event(self):
        """dispatch broadcasts event via control server (targeted + activity)."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()

        backend = IPCEventBackend(mock_server)
        event = _make_event()
        result = await backend.dispatch(event)

        assert result is True
        # new_message routes to EVENT_MESSAGE + EVENT_ACTIVITY
        assert mock_server.broadcast_event.call_count == 2
        event_types = [
            call[0][0] for call in mock_server.broadcast_event.call_args_list
        ]
        assert IPCMessageType.EVENT_MESSAGE in event_types
        assert IPCMessageType.EVENT_ACTIVITY in event_types
        # Verify payload on first call
        payload = mock_server.broadcast_event.call_args_list[0][0][1]
        assert payload["event_type"] == "new_message"
        assert payload["peer_hash"] == "abcd1234abcd1234"

    @pytest.mark.asyncio
    async def test_dispatch_returns_false_when_no_server(self):
        """dispatch returns False when control server is None."""
        backend = IPCEventBackend(None)
        result = await backend.dispatch(_make_event())
        assert result is False

    @pytest.mark.asyncio
    async def test_dispatch_includes_metadata_in_payload(self):
        """dispatch merges metadata into the event payload."""
        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()

        backend = IPCEventBackend(mock_server)
        event = _make_event(metadata={"delivery_method": "direct"})
        await backend.dispatch(event)

        payload = mock_server.broadcast_event.call_args[0][1]
        assert payload["delivery_method"] == "direct"


class TestNotificationBackendFiltering:
    """Tests for should_notify filtering logic."""

    def test_should_notify_returns_false_when_disabled(self):
        """should_notify returns False when config.enabled is False."""
        config = MagicMock()
        config.enabled = False
        config.quiet_hours_start = None
        config.quiet_hours_end = None

        backend = CallbackBackend()
        assert backend.should_notify(_make_event(), config) is False

    def test_should_notify_returns_true_when_enabled(self):
        """should_notify returns True when config.enabled is True."""
        config = MagicMock()
        config.enabled = True
        config.quiet_hours_start = None
        config.quiet_hours_end = None

        backend = CallbackBackend()
        assert backend.should_notify(_make_event(), config) is True

    def test_should_notify_returns_true_with_no_config(self):
        """should_notify returns True when config is None."""
        backend = CallbackBackend()
        assert backend.should_notify(_make_event(), None) is True


class TestNotificationService:
    """Tests for NotificationService orchestration."""

    @pytest.mark.asyncio
    async def test_notify_dispatches_to_all_backends(self):
        """notify dispatches event to all registered backends."""
        service = NotificationService()
        backend1 = CallbackBackend()
        backend2 = CallbackBackend()
        results = []
        backend1.register(lambda e: results.append("b1"))
        backend2.register(lambda e: results.append("b2"))

        service.add_backend(backend1)
        service.add_backend(backend2)

        count = await service.notify(_make_event())
        assert count == 2
        assert results == ["b1", "b2"]

    @pytest.mark.asyncio
    async def test_notify_respects_muted_conversations(self):
        """notify skips events from muted conversations."""
        service = NotificationService()
        backend = CallbackBackend()
        results = []
        backend.register(lambda e: results.append(e))
        service.add_backend(backend)

        service.mute_conversation("abcd1234abcd1234")
        count = await service.notify(_make_event(peer_hash="abcd1234abcd1234"))
        assert count == 0
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_unmute_conversation_restores_notifications(self):
        """unmute_conversation allows notifications to flow again."""
        service = NotificationService()
        backend = CallbackBackend()
        results = []
        backend.register(lambda e: results.append(e))
        service.add_backend(backend)

        service.mute_conversation("abcd1234abcd1234")
        service.unmute_conversation("abcd1234abcd1234")
        count = await service.notify(_make_event(peer_hash="abcd1234abcd1234"))
        assert count == 1

    @pytest.mark.asyncio
    async def test_notify_handles_backend_errors(self):
        """notify continues dispatch when a backend raises."""
        service = NotificationService()

        class FailingBackend(NotificationBackend):
            async def dispatch(self, event):
                raise RuntimeError("Backend error")

        backend_ok = CallbackBackend()
        results = []
        backend_ok.register(lambda e: results.append(e))

        service.add_backend(FailingBackend())
        service.add_backend(backend_ok)

        count = await service.notify(_make_event())
        assert count == 1
        assert len(results) == 1

    def test_add_backend_prevents_duplicates(self):
        """add_backend ignores duplicate backend registrations."""
        service = NotificationService()
        backend = CallbackBackend()
        service.add_backend(backend)
        service.add_backend(backend)
        assert len(service._backends) == 1

    def test_remove_backend(self):
        """remove_backend removes a registered backend."""
        service = NotificationService()
        backend = CallbackBackend()
        service.add_backend(backend)
        service.remove_backend(backend)
        assert len(service._backends) == 0

    def test_remove_backend_ignores_unknown(self):
        """remove_backend silently ignores unknown backends."""
        service = NotificationService()
        service.remove_backend(CallbackBackend())  # Should not raise

    @pytest.mark.asyncio
    async def test_notify_with_no_backends_returns_zero(self):
        """notify returns 0 when no backends are registered."""
        service = NotificationService()
        count = await service.notify(_make_event())
        assert count == 0


class TestIPCEventBackendRouting:
    """Tests for IPCEventBackend event type routing."""

    @pytest.mark.asyncio
    async def test_ipc_backend_routes_new_message_to_event_message(self):
        """new_message events broadcast as EVENT_MESSAGE."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()
        backend = IPCEventBackend(mock_server)

        event = _make_event(event_type="new_message")
        await backend.dispatch(event)

        # Should be called at least once with EVENT_MESSAGE
        event_types = [
            call[0][0] for call in mock_server.broadcast_event.call_args_list
        ]
        assert IPCMessageType.EVENT_MESSAGE in event_types

    @pytest.mark.asyncio
    async def test_ipc_backend_routes_device_to_event_device(self):
        """device_discovered events broadcast as EVENT_DEVICE."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()
        backend = IPCEventBackend(mock_server)

        event = _make_event(event_type="device_discovered")
        await backend.dispatch(event)

        event_types = [
            call[0][0] for call in mock_server.broadcast_event.call_args_list
        ]
        assert IPCMessageType.EVENT_DEVICE in event_types

    @pytest.mark.asyncio
    async def test_ipc_backend_routes_unknown_to_activity_only(self):
        """config_changed events only broadcast as EVENT_ACTIVITY."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()
        backend = IPCEventBackend(mock_server)

        event = _make_event(event_type="config_changed")
        await backend.dispatch(event)

        event_types = [
            call[0][0] for call in mock_server.broadcast_event.call_args_list
        ]
        assert IPCMessageType.EVENT_ACTIVITY in event_types
        assert IPCMessageType.EVENT_MESSAGE not in event_types
        assert IPCMessageType.EVENT_DEVICE not in event_types

    @pytest.mark.asyncio
    async def test_ipc_backend_always_broadcasts_activity(self):
        """ALL events are always broadcast to EVENT_ACTIVITY."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()
        backend = IPCEventBackend(mock_server)

        for event_type in ["new_message", "delivery_status", "device_discovered", "announce_sent"]:
            mock_server.broadcast_event.reset_mock()
            event = _make_event(event_type=event_type)
            await backend.dispatch(event)

            event_types = [
                call[0][0] for call in mock_server.broadcast_event.call_args_list
            ]
            assert IPCMessageType.EVENT_ACTIVITY in event_types, (
                f"EVENT_ACTIVITY missing for {event_type}"
            )

    @pytest.mark.asyncio
    async def test_ipc_backend_routes_delivery_status_to_event_message(self):
        """delivery_status events broadcast as EVENT_MESSAGE (targeted channel)."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()
        backend = IPCEventBackend(mock_server)

        event = _make_event(event_type="delivery_status")
        await backend.dispatch(event)

        event_types = [
            call[0][0] for call in mock_server.broadcast_event.call_args_list
        ]
        assert IPCMessageType.EVENT_MESSAGE in event_types
        assert IPCMessageType.EVENT_ACTIVITY in event_types

    @pytest.mark.asyncio
    async def test_ipc_backend_routes_device_updated_to_event_device(self):
        """device_updated events broadcast as EVENT_DEVICE (targeted channel)."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()
        backend = IPCEventBackend(mock_server)

        event = _make_event(event_type="device_updated")
        await backend.dispatch(event)

        event_types = [
            call[0][0] for call in mock_server.broadcast_event.call_args_list
        ]
        assert IPCMessageType.EVENT_DEVICE in event_types
        assert IPCMessageType.EVENT_ACTIVITY in event_types

    @pytest.mark.asyncio
    async def test_ipc_backend_routes_announce_sent_to_activity_only(self):
        """W1: announce_sent events ONLY go to EVENT_ACTIVITY (not targeted)."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()
        backend = IPCEventBackend(mock_server)

        event = _make_event(event_type="announce_sent")
        await backend.dispatch(event)

        event_types = [
            call[0][0] for call in mock_server.broadcast_event.call_args_list
        ]
        assert IPCMessageType.EVENT_ACTIVITY in event_types
        assert IPCMessageType.EVENT_MESSAGE not in event_types
        assert IPCMessageType.EVENT_DEVICE not in event_types

    @pytest.mark.asyncio
    async def test_ipc_backend_routes_rpc_received_to_activity_only(self):
        """W1: rpc_received events ONLY go to EVENT_ACTIVITY (not targeted)."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()
        backend = IPCEventBackend(mock_server)

        event = _make_event(event_type="rpc_received")
        await backend.dispatch(event)

        event_types = [
            call[0][0] for call in mock_server.broadcast_event.call_args_list
        ]
        assert IPCMessageType.EVENT_ACTIVITY in event_types
        assert IPCMessageType.EVENT_MESSAGE not in event_types
        assert IPCMessageType.EVENT_DEVICE not in event_types

    @pytest.mark.asyncio
    async def test_ipc_backend_preserves_message_payload(self):
        """Regression: payload structure unchanged for EVENT_MESSAGE."""
        from styrened.ipc.protocol import IPCMessageType

        mock_server = MagicMock()
        mock_server.broadcast_event = AsyncMock()
        backend = IPCEventBackend(mock_server)

        event = _make_event(
            event_type="new_message",
            peer_hash="deadbeef",
            message_id=42,
            content="Hello",
            timestamp=1000.0,
            status="received",
            is_outgoing=False,
            metadata={"delivery_method": "direct"},
        )
        await backend.dispatch(event)

        # Find the EVENT_MESSAGE call
        for call in mock_server.broadcast_event.call_args_list:
            if call[0][0] == IPCMessageType.EVENT_MESSAGE:
                payload = call[0][1]
                assert payload["event_type"] == "new_message"
                assert payload["peer_hash"] == "deadbeef"
                assert payload["message_id"] == 42
                assert payload["content"] == "Hello"
                assert payload["delivery_method"] == "direct"
                return
        pytest.fail("EVENT_MESSAGE call not found")
