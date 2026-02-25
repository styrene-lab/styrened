"""Unit tests for IPC client event dispatch and server subscription filtering."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from styrened.ipc.messages import (
    CmdSetContactRequest,
    QueryContactsRequest,
    QueryResolveNameRequest,
    SubActivityRequest,
    SubDevicesRequest,
    SubMessagesRequest,
    UnsubRequest,
    create_request,
)
from styrened.ipc.protocol import IPCMessageType, is_event_type
from styrened.ipc.server import ClientConnection


class TestIsEventType:
    """Tests for the is_event_type helper."""

    def test_event_message_is_event(self):
        """EVENT_MESSAGE is classified as event type."""
        assert is_event_type(IPCMessageType.EVENT_MESSAGE) is True

    def test_event_device_is_event(self):
        """EVENT_DEVICE is classified as event type."""
        assert is_event_type(IPCMessageType.EVENT_DEVICE) is True

    def test_query_is_not_event(self):
        """QUERY_DEVICES is not an event type."""
        assert is_event_type(IPCMessageType.QUERY_DEVICES) is False

    def test_result_is_not_event(self):
        """RESULT is not an event type."""
        assert is_event_type(IPCMessageType.RESULT) is False


class TestNewProtocolEnumValues:
    """Tests for new IPCMessageType enum values."""

    def test_query_contacts_exists(self):
        """QUERY_CONTACTS enum value is 0x17."""
        assert IPCMessageType.QUERY_CONTACTS == 0x17

    def test_query_resolve_name_exists(self):
        """QUERY_RESOLVE_NAME enum value is 0x18."""
        assert IPCMessageType.QUERY_RESOLVE_NAME == 0x18

    def test_cmd_set_contact_exists(self):
        """CMD_SET_CONTACT enum value is 0x29."""
        assert IPCMessageType.CMD_SET_CONTACT == 0x29

    def test_cmd_remove_contact_exists(self):
        """CMD_REMOVE_CONTACT enum value is 0x2A."""
        assert IPCMessageType.CMD_REMOVE_CONTACT == 0x2A


class TestNewRequestDataclasses:
    """Tests for new IPC request dataclasses."""

    def test_query_contacts_request_wire_format(self):
        """QueryContactsRequest serializes with correct MSG_TYPE."""
        req = QueryContactsRequest()
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.QUERY_CONTACTS
        assert payload == {}

    def test_query_resolve_name_request_wire_format(self):
        """QueryResolveNameRequest includes name and prefix_match."""
        req = QueryResolveNameRequest(name="alice", prefix_match=False)
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.QUERY_RESOLVE_NAME
        assert payload["name"] == "alice"
        assert payload["prefix_match"] is False

    def test_cmd_set_contact_request_wire_format(self):
        """CmdSetContactRequest includes peer_hash, alias, and notes."""
        req = CmdSetContactRequest(
            peer_hash="abcd1234", alias="Alice", notes="Friend"
        )
        _, payload = req.to_wire()
        assert payload["peer_hash"] == "abcd1234"
        assert payload["alias"] == "Alice"
        assert payload["notes"] == "Friend"

    def test_cmd_set_contact_request_omits_none_notes(self):
        """CmdSetContactRequest omits notes when None."""
        req = CmdSetContactRequest(peer_hash="abcd1234", alias="Alice")
        _, payload = req.to_wire()
        assert "notes" not in payload

    def test_sub_messages_request_wire_format(self):
        """SubMessagesRequest includes peer_hashes when provided."""
        req = SubMessagesRequest(peer_hashes=["hash1", "hash2"])
        _, payload = req.to_wire()
        assert payload["peer_hashes"] == ["hash1", "hash2"]

    def test_sub_messages_request_empty_peers(self):
        """SubMessagesRequest with no peers sends empty payload."""
        req = SubMessagesRequest()
        _, payload = req.to_wire()
        assert payload == {}

    def test_unsub_request_with_type(self):
        """UnsubRequest includes subscription_type when set."""
        req = UnsubRequest(subscription_type="messages")
        _, payload = req.to_wire()
        assert payload["subscription_type"] == "messages"


class TestCreateRequestFactory:
    """Tests for create_request() with new message types."""

    def test_create_query_contacts_request(self):
        """create_request handles QUERY_CONTACTS."""
        req = create_request(IPCMessageType.QUERY_CONTACTS, {})
        assert isinstance(req, QueryContactsRequest)

    def test_create_query_resolve_name_request(self):
        """create_request handles QUERY_RESOLVE_NAME."""
        req = create_request(
            IPCMessageType.QUERY_RESOLVE_NAME,
            {"name": "alice", "prefix_match": False},
        )
        assert isinstance(req, QueryResolveNameRequest)
        assert req.name == "alice"
        assert req.prefix_match is False

    def test_create_cmd_set_contact_request(self):
        """create_request handles CMD_SET_CONTACT."""
        req = create_request(
            IPCMessageType.CMD_SET_CONTACT,
            {"peer_hash": "abcd", "alias": "Alice", "notes": "Hi"},
        )
        assert isinstance(req, CmdSetContactRequest)
        assert req.peer_hash == "abcd"
        assert req.alias == "Alice"

    def test_create_sub_messages_request(self):
        """create_request handles SUB_MESSAGES."""
        req = create_request(
            IPCMessageType.SUB_MESSAGES, {"peer_hashes": ["h1"]}
        )
        assert isinstance(req, SubMessagesRequest)
        assert req.peer_hashes == ["h1"]

    def test_create_sub_devices_request(self):
        """create_request handles SUB_DEVICES."""
        req = create_request(IPCMessageType.SUB_DEVICES, {})
        assert isinstance(req, SubDevicesRequest)

    def test_create_unsub_request(self):
        """create_request handles UNSUB."""
        req = create_request(
            IPCMessageType.UNSUB, {"subscription_type": "devices"}
        )
        assert isinstance(req, UnsubRequest)
        assert req.subscription_type == "devices"


class TestClientConnectionSubscriptions:
    """Tests for ClientConnection subscription state."""

    def test_initial_subscriptions_empty(self):
        """ClientConnection starts with no subscriptions."""
        reader = MagicMock()
        writer = MagicMock()
        writer.is_closing.return_value = False
        conn = ClientConnection(reader, writer)
        assert conn.subscriptions == set()
        assert conn.message_peer_filter == set()

    def test_subscriptions_can_be_set(self):
        """ClientConnection subscriptions can be modified."""
        reader = MagicMock()
        writer = MagicMock()
        writer.is_closing.return_value = False
        conn = ClientConnection(reader, writer)
        conn.subscriptions.add("messages")
        conn.message_peer_filter = {"hash1", "hash2"}
        assert "messages" in conn.subscriptions
        assert conn.message_peer_filter == {"hash1", "hash2"}


class TestServerBroadcastFiltering:
    """Tests for ControlServer.broadcast_event subscription filtering."""

    @pytest.mark.asyncio
    async def test_broadcast_to_subscribed_client(self):
        """broadcast_event sends to clients subscribed for the event type."""
        from styrened.ipc.server import ControlServer

        server = ControlServer.__new__(ControlServer)
        server._clients = set()

        # Create a mock subscribed client
        client = MagicMock(spec=ClientConnection)
        client.closed = False
        client.subscriptions = {"messages"}
        client.message_peer_filter = set()
        client.send_event = AsyncMock()
        server._clients.add(client)

        await server.broadcast_event(
            IPCMessageType.EVENT_MESSAGE,
            {"event_type": "new", "peer_hash": "abcd"},
        )
        client.send_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_skips_unsubscribed_client(self):
        """broadcast_event skips clients not subscribed for the event type."""
        from styrened.ipc.server import ControlServer

        server = ControlServer.__new__(ControlServer)
        server._clients = set()

        client = MagicMock(spec=ClientConnection)
        client.closed = False
        client.subscriptions = {"devices"}  # Subscribed to devices, not messages
        client.message_peer_filter = set()
        client.send_event = AsyncMock()
        server._clients.add(client)

        await server.broadcast_event(
            IPCMessageType.EVENT_MESSAGE,
            {"event_type": "new", "peer_hash": "abcd"},
        )
        client.send_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_broadcast_applies_peer_filter(self):
        """broadcast_event applies message_peer_filter for EVENT_MESSAGE."""
        from styrened.ipc.server import ControlServer

        server = ControlServer.__new__(ControlServer)
        server._clients = set()

        client = MagicMock(spec=ClientConnection)
        client.closed = False
        client.subscriptions = {"messages"}
        client.message_peer_filter = {"allowed_hash"}
        client.send_event = AsyncMock()
        server._clients.add(client)

        # Send event for non-matching peer
        await server.broadcast_event(
            IPCMessageType.EVENT_MESSAGE,
            {"event_type": "new", "peer_hash": "other_hash"},
        )
        client.send_event.assert_not_called()

        # Send event for matching peer
        await server.broadcast_event(
            IPCMessageType.EVENT_MESSAGE,
            {"event_type": "new", "peer_hash": "allowed_hash"},
        )
        client.send_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_legacy_no_subscriptions(self):
        """broadcast_event sends to clients with no subscriptions (legacy)."""
        from styrened.ipc.server import ControlServer

        server = ControlServer.__new__(ControlServer)
        server._clients = set()

        client = MagicMock(spec=ClientConnection)
        client.closed = False
        client.subscriptions = set()  # No subscriptions = legacy mode
        client.message_peer_filter = set()
        client.send_event = AsyncMock()
        server._clients.add(client)

        await server.broadcast_event(
            IPCMessageType.EVENT_MESSAGE,
            {"event_type": "new", "peer_hash": "abcd"},
        )
        client.send_event.assert_called_once()


class TestClientEventDispatch:
    """Tests for ControlClient event dispatch."""

    @pytest.mark.asyncio
    async def test_on_event_registers_callback(self):
        """on_event registers a callback for specific event type."""
        from styrened.ipc.client import ControlClient

        client = ControlClient.__new__(ControlClient)
        client._event_callbacks = {}
        client._event_queue = asyncio.Queue()
        client._connected = True

        received = []
        client.on_event(IPCMessageType.EVENT_MESSAGE, lambda t, p: received.append(p))

        assert IPCMessageType.EVENT_MESSAGE in client._event_callbacks
        assert len(client._event_callbacks[IPCMessageType.EVENT_MESSAGE]) == 1

    @pytest.mark.asyncio
    async def test_remove_event_handler(self):
        """remove_event_handler unregisters a callback."""
        from styrened.ipc.client import ControlClient

        client = ControlClient.__new__(ControlClient)
        client._event_callbacks = {}
        client._event_queue = asyncio.Queue()

        cb = lambda t, p: None  # noqa: E731
        client.on_event(IPCMessageType.EVENT_MESSAGE, cb)
        client.remove_event_handler(IPCMessageType.EVENT_MESSAGE, cb)

        assert len(client._event_callbacks[IPCMessageType.EVENT_MESSAGE]) == 0

    @pytest.mark.asyncio
    async def test_dispatch_event_queues_and_calls_callbacks(self):
        """_dispatch_event puts event on queue and calls callbacks."""
        from styrened.ipc.client import ControlClient

        client = ControlClient.__new__(ControlClient)
        client._event_callbacks = {}
        client._event_queue = asyncio.Queue()
        client._connected = True

        received = []
        client.on_event(
            IPCMessageType.EVENT_MESSAGE, lambda t, p: received.append(p)
        )

        payload = {"event_type": "new", "peer_hash": "abcd"}
        await client._dispatch_event(IPCMessageType.EVENT_MESSAGE, payload)

        # Check queue
        evt_type, evt_payload = client._event_queue.get_nowait()
        assert evt_type == IPCMessageType.EVENT_MESSAGE
        assert evt_payload["peer_hash"] == "abcd"

        # Check callback was invoked
        assert len(received) == 1
        assert received[0]["peer_hash"] == "abcd"


class TestActivityEventProtocol:
    """Tests for SUB_ACTIVITY and EVENT_ACTIVITY protocol additions."""

    def test_sub_activity_exists(self):
        """SUB_ACTIVITY enum value is 0x32."""
        assert IPCMessageType.SUB_ACTIVITY == 0x32

    def test_event_activity_exists(self):
        """EVENT_ACTIVITY enum value is 0xC6."""
        assert IPCMessageType.EVENT_ACTIVITY == 0xC6

    def test_event_activity_is_event_type(self):
        """is_event_type() returns True for EVENT_ACTIVITY."""
        assert is_event_type(IPCMessageType.EVENT_ACTIVITY) is True

    def test_sub_activity_is_not_event_type(self):
        """SUB_ACTIVITY is a request, not an event."""
        assert is_event_type(IPCMessageType.SUB_ACTIVITY) is False

    def test_create_sub_activity_request(self):
        """create_request handles SUB_ACTIVITY."""
        req = create_request(IPCMessageType.SUB_ACTIVITY, {})
        assert isinstance(req, SubActivityRequest)

    def test_sub_activity_request_wire_format(self):
        """SubActivityRequest serializes with correct MSG_TYPE."""
        req = SubActivityRequest()
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.SUB_ACTIVITY
        assert payload == {}


class TestActivityBroadcastFiltering:
    """Tests for EVENT_ACTIVITY subscription broadcast routing."""

    @pytest.mark.asyncio
    async def test_broadcast_activity_to_subscribed_client(self):
        """broadcast_event sends EVENT_ACTIVITY to clients with 'activity' subscription."""
        from styrened.ipc.server import ControlServer

        server = ControlServer.__new__(ControlServer)
        server._clients = set()

        client = MagicMock(spec=ClientConnection)
        client.closed = False
        client.subscriptions = {"activity"}
        client.message_peer_filter = set()
        client.send_event = AsyncMock()
        server._clients.add(client)

        await server.broadcast_event(
            IPCMessageType.EVENT_ACTIVITY,
            {"event_type": "device_discovered", "peer_hash": "abcd"},
        )
        client.send_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_activity_skips_unsubscribed(self):
        """broadcast_event skips clients without 'activity' subscription."""
        from styrened.ipc.server import ControlServer

        server = ControlServer.__new__(ControlServer)
        server._clients = set()

        client = MagicMock(spec=ClientConnection)
        client.closed = False
        client.subscriptions = {"messages"}  # Only subscribed to messages
        client.message_peer_filter = set()
        client.send_event = AsyncMock()
        server._clients.add(client)

        await server.broadcast_event(
            IPCMessageType.EVENT_ACTIVITY,
            {"event_type": "device_discovered", "peer_hash": "abcd"},
        )
        client.send_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_message_subscription_unchanged(self):
        """Regression: EVENT_MESSAGE still routes to 'messages' subscribers."""
        from styrened.ipc.server import ControlServer

        server = ControlServer.__new__(ControlServer)
        server._clients = set()

        client = MagicMock(spec=ClientConnection)
        client.closed = False
        client.subscriptions = {"messages"}
        client.message_peer_filter = set()
        client.send_event = AsyncMock()
        server._clients.add(client)

        await server.broadcast_event(
            IPCMessageType.EVENT_MESSAGE,
            {"event_type": "new", "peer_hash": "abcd"},
        )
        client.send_event.assert_called_once()
