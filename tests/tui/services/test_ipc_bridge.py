"""Tests for IPCBridge — service abstraction layer for daemon communication.

All ControlClient interactions are mocked. No real socket connections.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from styrened.ipc.bridge import (
    _MAX_RECONNECT_ATTEMPTS,
    _RECONNECT_BACKOFF_FACTOR,
    _RECONNECT_DELAY_INITIAL,
    _RECONNECT_DELAY_MAX,
    IPCBridge,
)


@pytest.fixture
def mock_client():
    """Patch ControlClient at import location in ipc_bridge module."""
    with patch("styrened.ipc.bridge.ControlClient") as mock_client_cls:
        client = AsyncMock()
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        client.ping = AsyncMock(return_value=True)
        client.connected = True

        # Query methods
        client.query_devices = AsyncMock(return_value=[])
        client.query_status = AsyncMock(return_value={"uptime": 100})
        client.query_identity = AsyncMock(return_value={"hash": "abc"})
        client.query_messages = AsyncMock(return_value=[])
        client.query_conversations = AsyncMock(return_value=[])
        client.query_contacts = AsyncMock(return_value=[])
        client.query_config = AsyncMock(return_value={})

        # Command methods
        client.send_chat = AsyncMock(return_value={"id": 1})
        client.send_message = AsyncMock(return_value=True)
        client.announce = AsyncMock(return_value="abc123")
        client.mark_read = AsyncMock(return_value=5)
        client.search_messages = AsyncMock(return_value=[])
        client.delete_conversation = AsyncMock(return_value=3)
        client.delete_message = AsyncMock(return_value=True)
        client.retry_message = AsyncMock(return_value={"id": 1})
        client.device_status = AsyncMock(return_value={"uptime": 50})
        client.exec_command = AsyncMock(return_value={"output": "ok"})
        client.set_contact = AsyncMock(return_value={"alias": "test"})
        client.remove_contact = AsyncMock(return_value=True)
        client.resolve_name = AsyncMock(return_value="abc123")
        client.sync_messages = AsyncMock(return_value={"synced": True})
        client.query_path_info = AsyncMock(
            return_value={"found": True, "hops": 2, "interface_name": "TCPClient"}
        )

        # Subscription methods
        client.subscribe_messages = AsyncMock(return_value=True)
        client.subscribe_devices = AsyncMock(return_value=True)
        client.unsubscribe = AsyncMock(return_value=True)

        # Event handlers
        client.on_event = Mock()
        client.remove_event_handler = Mock()

        mock_client_cls.return_value = client
        yield client


# ===================================================================
# Init
# ===================================================================


class TestIPCBridgeInit:
    """Test IPCBridge construction."""

    def test_default_socket(self):
        bridge = IPCBridge()
        assert bridge._socket_path is not None

    def test_custom_socket(self, tmp_path):
        sock = tmp_path / "custom.sock"
        bridge = IPCBridge(socket_path=sock)
        assert bridge._socket_path == sock

    def test_custom_timeout(self):
        bridge = IPCBridge(timeout=60.0)
        assert bridge._timeout == 60.0

    def test_auto_reconnect_default(self):
        bridge = IPCBridge()
        assert bridge._auto_reconnect is True

    def test_auto_reconnect_disabled(self):
        bridge = IPCBridge(auto_reconnect=False)
        assert bridge._auto_reconnect is False

    def test_not_connected_initially(self):
        bridge = IPCBridge()
        assert bridge.connected is False


# ===================================================================
# Connect
# ===================================================================


class TestConnect:
    """Test connect behavior."""

    @pytest.mark.asyncio
    async def test_creates_client_and_pings(self, mock_client):
        bridge = IPCBridge()
        result = await bridge.connect()

        assert result is True
        assert bridge.connected is True
        mock_client.connect.assert_called_once()
        mock_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_on_ping_failure(self, mock_client):
        mock_client.ping.return_value = False

        bridge = IPCBridge()
        result = await bridge.connect()

        assert result is False
        assert bridge.connected is False
        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleans_up_on_connection_error(self, mock_client):
        from styrened.ipc import IPCConnectionError

        mock_client.connect.side_effect = IPCConnectionError("refused")

        bridge = IPCBridge()
        result = await bridge.connect()

        assert result is False
        assert bridge._client is None

    @pytest.mark.asyncio
    async def test_cleans_up_on_unexpected_error(self, mock_client):
        mock_client.connect.side_effect = RuntimeError("unexpected")

        bridge = IPCBridge()
        result = await bridge.connect()

        assert result is False
        assert bridge._client is None

    @pytest.mark.asyncio
    async def test_idempotent_when_connected(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        # Second connect should return True without reconnecting
        mock_client.connect.reset_mock()
        result = await bridge.connect()

        assert result is True
        mock_client.connect.assert_not_called()


# ===================================================================
# Disconnect
# ===================================================================


class TestDisconnect:
    """Test disconnect behavior."""

    @pytest.mark.asyncio
    async def test_calls_client_disconnect(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()
        await bridge.disconnect()

        assert bridge.connected is False
        mock_client.disconnect.assert_called()
        assert bridge._client is None

    @pytest.mark.asyncio
    async def test_cancels_reconnect_task(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        mock_task = Mock()
        mock_task.cancel = Mock()
        bridge._reconnect_task = mock_task

        await bridge.disconnect()
        mock_task.cancel.assert_called_once()
        assert bridge._reconnect_task is None

    @pytest.mark.asyncio
    async def test_handles_disconnect_errors(self, mock_client):
        mock_client.disconnect.side_effect = RuntimeError("socket gone")

        bridge = IPCBridge()
        await bridge.connect()
        await bridge.disconnect()  # Should not raise

        assert bridge._client is None

    @pytest.mark.asyncio
    async def test_noop_when_not_connected(self):
        bridge = IPCBridge()
        await bridge.disconnect()  # Should not raise


# ===================================================================
# Connected property
# ===================================================================


class TestConnectedProperty:
    """Test connected property logic."""

    @pytest.mark.asyncio
    async def test_requires_internal_flag_and_client(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        assert bridge.connected is True

        # Clear internal flag
        bridge._connected = False
        assert bridge.connected is False

    @pytest.mark.asyncio
    async def test_false_when_client_disconnected(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        mock_client.connected = False
        assert bridge.connected is False


# ===================================================================
# Ensure connected
# ===================================================================


class TestEnsureConnected:
    """Test _ensure_connected() auto-reconnection logic."""

    @pytest.mark.asyncio
    async def test_returns_client_when_connected(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        client = await bridge._ensure_connected()
        assert client is mock_client

    @pytest.mark.asyncio
    async def test_auto_reconnects(self, mock_client):
        bridge = IPCBridge()
        # Not connected, but auto_reconnect enabled
        bridge._connected = False

        with patch.object(bridge, "_reconnect", return_value=True):
            bridge._client = mock_client
            bridge._connected = True
            mock_client.connected = True
            client = await bridge._ensure_connected()
            assert client is not None

    @pytest.mark.asyncio
    async def test_raises_when_disabled(self):
        from styrened.ipc import IPCConnectionError

        bridge = IPCBridge(auto_reconnect=False)

        with pytest.raises(IPCConnectionError):
            await bridge._ensure_connected()

    @pytest.mark.asyncio
    async def test_raises_when_reconnect_exhausted(self, mock_client):
        from styrened.ipc import IPCConnectionError

        bridge = IPCBridge()

        with patch.object(bridge, "_reconnect", return_value=False):
            with pytest.raises(IPCConnectionError):
                await bridge._ensure_connected()


# ===================================================================
# Reconnect
# ===================================================================


class TestReconnect:
    """Test _reconnect() exponential backoff."""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self, mock_client):
        bridge = IPCBridge()
        result = await bridge._reconnect()
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_after_all_attempts(self, mock_client):
        mock_client.ping.return_value = False

        bridge = IPCBridge()

        with patch("styrened.ipc.bridge.asyncio.sleep", new_callable=AsyncMock):
            result = await bridge._reconnect()

        assert result is False

    @pytest.mark.asyncio
    async def test_exponential_backoff(self, mock_client):
        mock_client.ping.return_value = False
        delays = []

        async def track_sleep(delay):
            delays.append(delay)

        bridge = IPCBridge()

        with patch("styrened.ipc.bridge.asyncio.sleep", side_effect=track_sleep):
            await bridge._reconnect()

        # Should have _MAX_RECONNECT_ATTEMPTS - 1 delays (no delay after last attempt)
        assert len(delays) == _MAX_RECONNECT_ATTEMPTS - 1

        # Verify exponential growth with cap
        for i, d in enumerate(delays):
            expected = min(
                _RECONNECT_DELAY_INITIAL * (_RECONNECT_BACKOFF_FACTOR ** i),
                _RECONNECT_DELAY_MAX,
            )
            assert d == expected

    @pytest.mark.asyncio
    async def test_five_attempts_max(self, mock_client):
        mock_client.ping.return_value = False

        bridge = IPCBridge()

        with patch("styrened.ipc.bridge.asyncio.sleep", new_callable=AsyncMock):
            await bridge._reconnect()

        # connect() is called once per attempt
        assert mock_client.connect.call_count == _MAX_RECONNECT_ATTEMPTS


# ===================================================================
# _call dynamic dispatch
# ===================================================================


class TestCall:
    """Test _call() method dispatch with reconnection."""

    @pytest.mark.asyncio
    async def test_dispatches_via_getattr(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge._call("query_status")
        mock_client.query_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_args_kwargs(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge._call("query_devices", styrene_only=True)
        mock_client.query_devices.assert_called_once_with(styrene_only=True)

    @pytest.mark.asyncio
    async def test_auto_reconnects_on_connection_error(self, mock_client):
        from styrened.ipc import IPCConnectionError

        bridge = IPCBridge()
        await bridge.connect()

        # First call fails, reconnect succeeds, second call works
        call_count = 0

        async def _query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise IPCConnectionError("lost")
            return {"status": "ok"}

        mock_client.query_status = AsyncMock(side_effect=_query)

        with patch.object(bridge, "_reconnect", return_value=True):
            bridge._connected = True
            mock_client.connected = True
            result = await bridge._call("query_status")

        assert result == {"status": "ok"}


# ===================================================================
# Query methods
# ===================================================================


class TestQueryMethods:
    """Test all get_* query methods delegate correctly."""

    @pytest.mark.asyncio
    async def test_get_devices(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.get_devices()
        mock_client.query_devices.assert_called_once_with(styrene_only=False)

    @pytest.mark.asyncio
    async def test_get_devices_styrene_only(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.get_devices(styrene_only=True)
        mock_client.query_devices.assert_called_once_with(styrene_only=True)

    @pytest.mark.asyncio
    async def test_get_status(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.get_status()
        mock_client.query_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_identity(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.get_identity()
        mock_client.query_identity.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_messages(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.get_messages("peer123", limit=10)
        mock_client.query_messages.assert_called_once_with(
            peer_hash="peer123", limit=10,
            before_timestamp=None, status_filter=None,
        )

    @pytest.mark.asyncio
    async def test_get_conversations(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.get_conversations()
        mock_client.query_conversations.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_contacts(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.get_contacts()
        mock_client.query_contacts.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_config(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.get_config()
        mock_client.query_config.assert_called_once()


# ===================================================================
# Command methods
# ===================================================================


class TestCommandMethods:
    """Test all command methods delegate correctly."""

    @pytest.mark.asyncio
    async def test_send_chat(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.send_chat("peer123", "hello")
        mock_client.send_chat.assert_called_once_with(
            peer_hash="peer123", content="hello",
            title=None, delivery_method="auto",
            reply_to_hash=None,
            attachment_data_b64=None, attachment_filename=None, attachment_mime=None,
        )

    @pytest.mark.asyncio
    async def test_send_message(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.send_message("dest123", "test msg")
        mock_client.send_message.assert_called_once_with(
            destination="dest123", message="test msg",
            protocol="chat", retry=False, timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_announce(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        result = await bridge.announce()
        mock_client.announce.assert_called_once()
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_mark_read(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        result = await bridge.mark_read("peer123")
        mock_client.mark_read.assert_called_once_with(peer_hash="peer123")
        assert result == 5

    @pytest.mark.asyncio
    async def test_delete_conversation(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.delete_conversation("peer123")
        mock_client.delete_conversation.assert_called_once_with(peer_hash="peer123")

    @pytest.mark.asyncio
    async def test_delete_message(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.delete_message(42)
        mock_client.delete_message.assert_called_once_with(message_id=42)

    @pytest.mark.asyncio
    async def test_retry_message(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.retry_message(42)
        mock_client.retry_message.assert_called_once_with(message_id=42)

    @pytest.mark.asyncio
    async def test_query_device_status(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.query_device_status("dest123", timeout=15.0)
        mock_client.device_status.assert_called_once_with(
            destination="dest123", timeout=15.0,
        )

    @pytest.mark.asyncio
    async def test_send_rpc(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.send_rpc("dest123", "uptime", args=["-a"])
        mock_client.exec_command.assert_called_once_with(
            destination="dest123", command="uptime",
            args=["-a"], timeout=60.0,
        )


# ===================================================================
# Subscription methods
# ===================================================================


class TestSubscriptionMethods:
    """Test event subscription methods."""

    @pytest.mark.asyncio
    async def test_subscribe_messages(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        result = await bridge.subscribe_messages(peer_hashes=["a", "b"])
        mock_client.subscribe_messages.assert_called_once_with(peer_hashes=["a", "b"])
        assert result is True

    @pytest.mark.asyncio
    async def test_subscribe_devices(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        result = await bridge.subscribe_devices()
        mock_client.subscribe_devices.assert_called_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_unsubscribe(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.unsubscribe("messages")
        mock_client.unsubscribe.assert_called_once_with(subscription_type="messages")


# ===================================================================
# Event handlers
# ===================================================================


class TestEventHandlers:
    """Test event handler registration."""

    @pytest.mark.asyncio
    async def test_on_event_delegates(self, mock_client):
        from styrened.ipc import IPCMessageType

        bridge = IPCBridge()
        await bridge.connect()

        callback = Mock()
        bridge.on_event(IPCMessageType.EVENT_DEVICE, callback)
        mock_client.on_event.assert_called_once_with(IPCMessageType.EVENT_DEVICE, callback)

    @pytest.mark.asyncio
    async def test_remove_event_handler_delegates(self, mock_client):
        from styrened.ipc import IPCMessageType

        bridge = IPCBridge()
        await bridge.connect()

        callback = Mock()
        bridge.remove_event_handler(IPCMessageType.EVENT_DEVICE, callback)
        mock_client.remove_event_handler.assert_called_once_with(
            IPCMessageType.EVENT_DEVICE, callback,
        )

    def test_on_event_noop_when_no_client(self):
        from styrened.ipc import IPCMessageType

        bridge = IPCBridge()
        bridge.on_event(IPCMessageType.EVENT_DEVICE, Mock())  # Should not raise

    def test_remove_event_handler_noop_when_no_client(self):
        from styrened.ipc import IPCMessageType

        bridge = IPCBridge()
        bridge.remove_event_handler(IPCMessageType.EVENT_DEVICE, Mock())  # Should not raise


# ===================================================================
# Contact methods
# ===================================================================


class TestContactMethods:
    """Test contact management methods."""

    @pytest.mark.asyncio
    async def test_set_contact(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.set_contact("peer123", "Alice", notes="friend")
        mock_client.set_contact.assert_called_once_with(
            peer_hash="peer123", alias="Alice", notes="friend",
        )

    @pytest.mark.asyncio
    async def test_remove_contact(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        result = await bridge.remove_contact("peer123")
        mock_client.remove_contact.assert_called_once_with(peer_hash="peer123")
        assert result is True

    @pytest.mark.asyncio
    async def test_resolve_name(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        result = await bridge.resolve_name("Ali")
        mock_client.resolve_name.assert_called_once_with(
            name="Ali", prefix_match=True,
        )
        assert result == "abc123"

    @pytest.mark.asyncio
    async def test_search_messages(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        await bridge.search_messages("hello", peer_hash="abc")
        mock_client.search_messages.assert_called_once_with(
            query="hello", peer_hash="abc", limit=50,
        )

    @pytest.mark.asyncio
    async def test_sync_messages(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        result = await bridge.sync_messages()
        mock_client.sync_messages.assert_called_once()
        assert result == {"synced": True}

    @pytest.mark.asyncio
    async def test_get_path_info(self, mock_client):
        bridge = IPCBridge()
        await bridge.connect()

        result = await bridge.get_path_info("abcd1234" * 4)
        mock_client.query_path_info.assert_called_once_with(
            destination_hash="abcd1234" * 4,
        )
        assert result["found"] is True
        assert result["hops"] == 2
