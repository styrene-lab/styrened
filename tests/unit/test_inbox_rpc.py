"""Unit tests for remote inbox RPC — query messages on remote Styrene nodes.

Tests cover:
- Wire format: encode/decode INBOX_QUERY, INBOX_RESPONSE, MESSAGES_QUERY, MESSAGES_RESPONSE
- Server handler: mock ConversationService, verify correct response payloads
- Client decode: verify InboxResponse/MessagesResponse construction from payloads
- Authorization: verify inbox queries require auth (not in PUBLIC_RPC_COMMANDS)
- Error cases: conversation service unavailable, invalid peer_hash, empty inbox
"""
from __future__ import annotations


import asyncio
from unittest.mock import AsyncMock, MagicMock

from styrened.models.styrene_wire import (
    STYRENE_VERSION,
    StyreneEnvelope,
    StyreneMessageType,
    decode_payload,
    encode_payload,
    generate_request_id,
)

# ---------------------------------------------------------------------------
# Wire format tests
# ---------------------------------------------------------------------------


class TestWireFormat:
    """Tests for INBOX/MESSAGES wire protocol message types."""

    def test_inbox_query_enum_value(self):
        """INBOX_QUERY should be 0x44 in the RPC commands range."""
        assert StyreneMessageType.INBOX_QUERY == 0x44

    def test_messages_query_enum_value(self):
        """MESSAGES_QUERY should be 0x45 in the RPC commands range."""
        assert StyreneMessageType.MESSAGES_QUERY == 0x45

    def test_inbox_response_enum_value(self):
        """INBOX_RESPONSE should be 0x64 in the RPC responses range."""
        assert StyreneMessageType.INBOX_RESPONSE == 0x64

    def test_messages_response_enum_value(self):
        """MESSAGES_RESPONSE should be 0x65 in the RPC responses range."""
        assert StyreneMessageType.MESSAGES_RESPONSE == 0x65

    def test_create_inbox_query(self):
        """create_inbox_query should produce a valid envelope with limit payload."""
        from styrened.models.styrene_wire import create_inbox_query

        envelope = create_inbox_query(limit=25)
        assert envelope.message_type == StyreneMessageType.INBOX_QUERY
        assert envelope.version == STYRENE_VERSION
        payload = decode_payload(envelope.payload)
        assert payload["limit"] == 25

    def test_create_inbox_query_default_limit(self):
        """create_inbox_query should default to limit=50."""
        from styrened.models.styrene_wire import create_inbox_query

        envelope = create_inbox_query()
        payload = decode_payload(envelope.payload)
        assert payload["limit"] == 50

    def test_create_inbox_response(self):
        """create_inbox_response should produce a valid envelope with conversations."""
        from styrened.models.styrene_wire import create_inbox_response

        conversations = [
            {"peer_hash": "abc123", "unread_count": 3, "message_count": 10},
        ]
        req_id = generate_request_id()
        envelope = create_inbox_response(conversations, request_id=req_id)
        assert envelope.message_type == StyreneMessageType.INBOX_RESPONSE
        assert envelope.request_id == req_id
        payload = decode_payload(envelope.payload)
        assert len(payload["conversations"]) == 1
        assert payload["conversations"][0]["peer_hash"] == "abc123"

    def test_create_messages_query(self):
        """create_messages_query should produce a valid envelope with peer_hash and limit."""
        from styrened.models.styrene_wire import create_messages_query

        envelope = create_messages_query(peer_hash="deadbeef01234567", limit=20)
        assert envelope.message_type == StyreneMessageType.MESSAGES_QUERY
        payload = decode_payload(envelope.payload)
        assert payload["peer_hash"] == "deadbeef01234567"
        assert payload["limit"] == 20

    def test_create_messages_response(self):
        """create_messages_response should produce a valid envelope with messages list."""
        from styrened.models.styrene_wire import create_messages_response

        messages = [
            {"content": "hello", "is_outgoing": False, "timestamp": 1234567890.0},
        ]
        req_id = generate_request_id()
        envelope = create_messages_response(messages, request_id=req_id)
        assert envelope.message_type == StyreneMessageType.MESSAGES_RESPONSE
        payload = decode_payload(envelope.payload)
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["content"] == "hello"

    def test_inbox_query_roundtrip(self):
        """Encode/decode roundtrip for INBOX_QUERY."""
        from styrened.models.styrene_wire import create_inbox_query

        original = create_inbox_query(limit=10)
        wire = original.encode()
        decoded = StyreneEnvelope.decode(wire)
        assert decoded.message_type == StyreneMessageType.INBOX_QUERY
        payload = decode_payload(decoded.payload)
        assert payload["limit"] == 10

    def test_messages_query_roundtrip(self):
        """Encode/decode roundtrip for MESSAGES_QUERY."""
        from styrened.models.styrene_wire import create_messages_query

        original = create_messages_query(peer_hash="aabb", limit=5)
        wire = original.encode()
        decoded = StyreneEnvelope.decode(wire)
        assert decoded.message_type == StyreneMessageType.MESSAGES_QUERY
        payload = decode_payload(decoded.payload)
        assert payload["peer_hash"] == "aabb"
        assert payload["limit"] == 5

    def test_inbox_response_roundtrip(self):
        """Encode/decode roundtrip for INBOX_RESPONSE."""
        from styrened.models.styrene_wire import create_inbox_response

        convos = [{"peer_hash": "x", "unread_count": 0, "message_count": 5}]
        req_id = generate_request_id()
        original = create_inbox_response(convos, request_id=req_id)
        wire = original.encode()
        decoded = StyreneEnvelope.decode(wire)
        assert decoded.message_type == StyreneMessageType.INBOX_RESPONSE
        assert decoded.request_id == req_id

    def test_messages_response_roundtrip(self):
        """Encode/decode roundtrip for MESSAGES_RESPONSE."""
        from styrened.models.styrene_wire import create_messages_response

        msgs = [{"content": "hi", "is_outgoing": True}]
        req_id = generate_request_id()
        original = create_messages_response(msgs, request_id=req_id)
        wire = original.encode()
        decoded = StyreneEnvelope.decode(wire)
        assert decoded.message_type == StyreneMessageType.MESSAGES_RESPONSE
        assert decoded.request_id == req_id


# ---------------------------------------------------------------------------
# RPC response model tests
# ---------------------------------------------------------------------------


class TestRPCResponseModels:
    """Tests for InboxResponse and MessagesResponse dataclasses."""

    def test_inbox_response_to_dict(self):
        """InboxResponse.to_dict() should produce expected structure."""
        from styrened.rpc.messages import InboxResponse

        resp = InboxResponse(
            conversations=[
                {"peer_hash": "abc", "unread_count": 2, "message_count": 5},
            ]
        )
        d = resp.to_dict()
        assert d["type"] == "inbox_response"
        assert len(d["conversations"]) == 1
        assert d["conversations"][0]["peer_hash"] == "abc"

    def test_inbox_response_from_dict(self):
        """InboxResponse.from_dict() should reconstruct from dict."""
        from styrened.rpc.messages import InboxResponse

        data = {
            "conversations": [{"peer_hash": "xyz", "unread_count": 0, "message_count": 1}],
            "type": "inbox_response",
        }
        resp = InboxResponse.from_dict(data)
        assert len(resp.conversations) == 1
        assert resp.conversations[0]["peer_hash"] == "xyz"

    def test_messages_response_to_dict(self):
        """MessagesResponse.to_dict() should produce expected structure."""
        from styrened.rpc.messages import MessagesResponse

        resp = MessagesResponse(
            messages=[
                {"content": "test", "is_outgoing": False, "timestamp": 1.0},
            ]
        )
        d = resp.to_dict()
        assert d["type"] == "messages_response"
        assert len(d["messages"]) == 1

    def test_messages_response_from_dict(self):
        """MessagesResponse.from_dict() should reconstruct from dict."""
        from styrened.rpc.messages import MessagesResponse

        data = {
            "messages": [{"content": "hi", "is_outgoing": True}],
            "type": "messages_response",
        }
        resp = MessagesResponse.from_dict(data)
        assert len(resp.messages) == 1
        assert resp.messages[0]["content"] == "hi"

    def test_inbox_response_empty(self):
        """InboxResponse should handle empty conversations list."""
        from styrened.rpc.messages import InboxResponse

        resp = InboxResponse(conversations=[])
        assert resp.to_dict()["conversations"] == []

    def test_messages_response_empty(self):
        """MessagesResponse should handle empty messages list."""
        from styrened.rpc.messages import MessagesResponse

        resp = MessagesResponse(messages=[])
        assert resp.to_dict()["messages"] == []


# ---------------------------------------------------------------------------
# RPC client decode tests
# ---------------------------------------------------------------------------


class TestRPCClientDecode:
    """Tests for client-side decoding of inbox/messages responses."""

    def test_decode_inbox_response(self):
        """RPCClient should decode INBOX_RESPONSE into InboxResponse."""
        from styrened.rpc.messages import InboxResponse

        payload_data = {
            "conversations": [
                {"peer_hash": "abc", "unread_count": 1, "message_count": 3},
            ]
        }
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.INBOX_RESPONSE,
            payload=encode_payload(payload_data),
            request_id=generate_request_id(),
        )

        # Import the client and use its _decode_response
        from styrened.rpc.client import RPCClient

        # Create a mock protocol to avoid real initialization
        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()
        client = RPCClient(mock_protocol)

        response = client._decode_response(envelope)
        assert isinstance(response, InboxResponse)
        assert len(response.conversations) == 1

    def test_decode_messages_response(self):
        """RPCClient should decode MESSAGES_RESPONSE into MessagesResponse."""
        from styrened.rpc.messages import MessagesResponse

        payload_data = {
            "messages": [
                {"content": "hello", "is_outgoing": False, "timestamp": 100.0},
            ]
        }
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.MESSAGES_RESPONSE,
            payload=encode_payload(payload_data),
            request_id=generate_request_id(),
        )

        from styrened.rpc.client import RPCClient

        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()
        client = RPCClient(mock_protocol)

        response = client._decode_response(envelope)
        assert isinstance(response, MessagesResponse)
        assert len(response.messages) == 1

    def test_is_rpc_response_includes_inbox(self):
        """_is_rpc_response should return True for INBOX_RESPONSE."""
        from styrened.rpc.client import RPCClient

        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()
        client = RPCClient(mock_protocol)

        assert client._is_rpc_response(StyreneMessageType.INBOX_RESPONSE) is True

    def test_is_rpc_response_includes_messages(self):
        """_is_rpc_response should return True for MESSAGES_RESPONSE."""
        from styrened.rpc.client import RPCClient

        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()
        client = RPCClient(mock_protocol)

        assert client._is_rpc_response(StyreneMessageType.MESSAGES_RESPONSE) is True


# ---------------------------------------------------------------------------
# Authorization tests
# ---------------------------------------------------------------------------


class TestAuthorization:
    """Tests verifying inbox queries require authorization."""

    def test_inbox_query_not_public(self):
        """INBOX_QUERY should NOT be in PUBLIC_RPC_COMMANDS."""
        from styrened.rpc.server import PUBLIC_RPC_COMMANDS

        assert StyreneMessageType.INBOX_QUERY not in PUBLIC_RPC_COMMANDS

    def test_messages_query_not_public(self):
        """MESSAGES_QUERY should NOT be in PUBLIC_RPC_COMMANDS."""
        from styrened.rpc.server import PUBLIC_RPC_COMMANDS

        assert StyreneMessageType.MESSAGES_QUERY not in PUBLIC_RPC_COMMANDS

    def test_inbox_query_not_dangerous(self):
        """INBOX_QUERY should NOT be in DANGEROUS_RPC_COMMANDS (read-only)."""
        from styrened.rpc.server import DANGEROUS_RPC_COMMANDS

        assert StyreneMessageType.INBOX_QUERY not in DANGEROUS_RPC_COMMANDS

    def test_messages_query_not_dangerous(self):
        """MESSAGES_QUERY should NOT be in DANGEROUS_RPC_COMMANDS (read-only)."""
        from styrened.rpc.server import DANGEROUS_RPC_COMMANDS

        assert StyreneMessageType.MESSAGES_QUERY not in DANGEROUS_RPC_COMMANDS


# ---------------------------------------------------------------------------
# RPC server handler tests
# ---------------------------------------------------------------------------


class TestRPCServerHandlers:
    """Tests for server-side inbox query handling."""

    def _make_server(self, conversation_service=None):
        """Create an RPCServer with a mock protocol and optional conversation service."""
        from styrened.rpc.server import RPCServer

        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()
        mock_protocol.send_typed_message = AsyncMock()

        server = RPCServer(mock_protocol)
        if conversation_service is not None:
            server.set_conversation_service(conversation_service)
        server.start()
        return server, mock_protocol

    def test_set_conversation_service(self):
        """set_conversation_service should store the service reference."""
        from styrened.rpc.server import RPCServer

        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()
        server = RPCServer(mock_protocol)

        mock_svc = MagicMock()
        server.set_conversation_service(mock_svc)
        assert server._conversation_service is mock_svc

    async def test_handle_inbox_query_calls_list_conversations(self):
        """_handle_inbox_query should call conversation_service.list_conversations."""
        mock_svc = MagicMock()
        mock_svc.list_conversations.return_value = []
        server, mock_protocol = self._make_server(conversation_service=mock_svc)
        mock_protocol.send_typed_message = AsyncMock()

        req_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.INBOX_QUERY,
            payload=encode_payload({"limit": 50}),
            request_id=req_id,
        )

        server._handle_inbox_query("source_hash_abc", envelope)
        # Let the created task run
        await asyncio.sleep(0)

        mock_svc.list_conversations.assert_called_once()

    async def test_handle_inbox_query_no_conversation_service(self):
        """_handle_inbox_query should send error when conversation_service is None."""
        server, mock_protocol = self._make_server(conversation_service=None)
        mock_protocol.send_typed_message = AsyncMock()

        req_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.INBOX_QUERY,
            payload=encode_payload({"limit": 50}),
            request_id=req_id,
        )

        server._handle_inbox_query("source_hash_abc", envelope)
        await asyncio.sleep(0)

        # Should have tried to send an error response
        mock_protocol.send_typed_message.assert_called()

    async def test_handle_messages_query_calls_get_messages(self):
        """_handle_messages_query should call conversation_service.get_messages."""
        mock_svc = MagicMock()
        mock_svc.get_messages.return_value = []
        server, mock_protocol = self._make_server(conversation_service=mock_svc)
        mock_protocol.send_typed_message = AsyncMock()

        req_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=StyreneMessageType.MESSAGES_QUERY,
            payload=encode_payload({"peer_hash": "deadbeef01234567", "limit": 20}),
            request_id=req_id,
        )

        server._handle_messages_query("source_hash_abc", envelope)
        await asyncio.sleep(0)

        mock_svc.get_messages.assert_called_once_with(
            peer_hash="deadbeef01234567", limit=20
        )

    def test_inbox_query_registered_with_protocol(self):
        """RPCServer should register INBOX_QUERY handler with StyreneProtocol."""
        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()

        from styrened.rpc.server import RPCServer

        RPCServer(mock_protocol)

        # Check that register_handler was called for INBOX_QUERY
        registered_types = [
            call.args[0] for call in mock_protocol.register_handler.call_args_list
        ]
        assert StyreneMessageType.INBOX_QUERY in registered_types

    def test_messages_query_registered_with_protocol(self):
        """RPCServer should register MESSAGES_QUERY handler with StyreneProtocol."""
        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()

        from styrened.rpc.server import RPCServer

        RPCServer(mock_protocol)

        registered_types = [
            call.args[0] for call in mock_protocol.register_handler.call_args_list
        ]
        assert StyreneMessageType.MESSAGES_QUERY in registered_types


# ---------------------------------------------------------------------------
# IPC message type tests
# ---------------------------------------------------------------------------


class TestIPCMessageTypes:
    """Tests for IPC protocol message types for remote inbox queries."""

    def test_cmd_remote_inbox_exists(self):
        """CMD_REMOTE_INBOX should exist in IPCMessageType."""
        from styrened.ipc.protocol import IPCMessageType

        assert hasattr(IPCMessageType, "CMD_REMOTE_INBOX")

    def test_cmd_remote_messages_exists(self):
        """CMD_REMOTE_MESSAGES should exist in IPCMessageType."""
        from styrened.ipc.protocol import IPCMessageType

        assert hasattr(IPCMessageType, "CMD_REMOTE_MESSAGES")

    def test_cmd_remote_inbox_request_class(self):
        """CmdRemoteInboxRequest should be constructible with destination and limit."""
        from styrened.ipc.messages import CmdRemoteInboxRequest

        req = CmdRemoteInboxRequest(destination="abcdef0123456789", limit=25, timeout=15.0)
        assert req.destination == "abcdef0123456789"
        assert req.limit == 25
        assert req.timeout == 15.0

    def test_cmd_remote_messages_request_class(self):
        """CmdRemoteMessagesRequest should be constructible with destination, peer_hash, limit."""
        from styrened.ipc.messages import CmdRemoteMessagesRequest

        req = CmdRemoteMessagesRequest(
            destination="abcdef0123456789",
            peer_hash="deadbeef01234567",
            limit=20,
            timeout=15.0,
        )
        assert req.destination == "abcdef0123456789"
        assert req.peer_hash == "deadbeef01234567"
        assert req.limit == 20

    def test_cmd_remote_inbox_to_payload(self):
        """CmdRemoteInboxRequest.to_payload() should include all fields."""
        from styrened.ipc.messages import CmdRemoteInboxRequest

        req = CmdRemoteInboxRequest(destination="abc", limit=10, timeout=5.0)
        payload = req.to_payload()
        assert payload["destination"] == "abc"
        assert payload["limit"] == 10
        assert payload["timeout"] == 5.0

    def test_cmd_remote_messages_to_payload(self):
        """CmdRemoteMessagesRequest.to_payload() should include all fields."""
        from styrened.ipc.messages import CmdRemoteMessagesRequest

        req = CmdRemoteMessagesRequest(
            destination="abc", peer_hash="def", limit=10, timeout=5.0
        )
        payload = req.to_payload()
        assert payload["destination"] == "abc"
        assert payload["peer_hash"] == "def"
        assert payload["limit"] == 10


# ---------------------------------------------------------------------------
# CLI subcommand existence tests
# ---------------------------------------------------------------------------


class TestCLISubcommands:
    """Tests verifying CLI subcommands are registered."""

    def test_inbox_subcommand_exists(self):
        """'inbox' should be a recognized subcommand."""
        from styrened.cli import create_parser

        parser = create_parser()
        # Parse with inbox subcommand
        args = parser.parse_args(["inbox", "abcdef0123456789"])
        assert args.command == "inbox"
        assert args.destination == "abcdef0123456789"

    def test_remote_messages_subcommand_exists(self):
        """'remote-messages' should be a recognized subcommand."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["remote-messages", "abcdef0123456789", "deadbeef01234567"])
        assert args.command == "remote-messages"
        assert args.destination == "abcdef0123456789"
        assert args.peer_hash == "deadbeef01234567"

    def test_inbox_limit_flag(self):
        """'inbox --limit' should set the limit."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["inbox", "abc123", "--limit", "25"])
        assert args.limit == 25

    def test_inbox_json_flag(self):
        """'inbox --json' should set json output mode."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["inbox", "abc123", "--json"])
        assert args.json is True

    def test_remote_messages_limit_flag(self):
        """'remote-messages --limit' should set the limit."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["remote-messages", "abc", "def", "--limit", "20"])
        assert args.limit == 20
