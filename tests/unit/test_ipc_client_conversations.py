"""Unit tests for IPC client conversation/message query methods.

Tests serialization round-trips and client method response parsing.
"""

from unittest.mock import AsyncMock, patch

import pytest

from styrened.ipc.messages import (
    QueryConversationsRequest,
    QueryMessagesRequest,
)
from styrened.ipc.protocol import IPCMessageType


class TestQueryConversationsRequest:
    """Tests for QueryConversationsRequest serialization."""

    def test_message_type(self):
        """Request should have correct message type."""
        req = QueryConversationsRequest()
        assert req.MSG_TYPE == IPCMessageType.QUERY_CONVERSATIONS

    def test_default_include_unread_count(self):
        """Default include_unread_count should be True."""
        req = QueryConversationsRequest()
        assert req.include_unread_count is True

    def test_to_payload(self):
        """to_payload should serialize include_unread_count."""
        req = QueryConversationsRequest(include_unread_count=False)
        payload = req.to_payload()
        assert payload == {"include_unread_count": False}

    def test_to_wire_round_trip(self):
        """to_wire should return correct type and payload."""
        req = QueryConversationsRequest(include_unread_count=True)
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.QUERY_CONVERSATIONS
        assert payload["include_unread_count"] is True


class TestQueryMessagesRequest:
    """Tests for QueryMessagesRequest serialization."""

    def test_message_type(self):
        """Request should have correct message type."""
        req = QueryMessagesRequest()
        assert req.MSG_TYPE == IPCMessageType.QUERY_MESSAGES

    def test_default_values(self):
        """Defaults: empty peer_hash, limit 50, no filters."""
        req = QueryMessagesRequest()
        assert req.peer_hash == ""
        assert req.limit == 50
        assert req.before_timestamp is None
        assert req.status_filter is None

    def test_to_payload_minimal(self):
        """to_payload with defaults should include peer_hash and limit."""
        req = QueryMessagesRequest(peer_hash="abcd1234")
        payload = req.to_payload()
        assert payload == {"peer_hash": "abcd1234", "limit": 50}
        assert "before_timestamp" not in payload
        assert "status_filter" not in payload

    def test_to_payload_with_optional_fields(self):
        """to_payload should include optional fields when set."""
        req = QueryMessagesRequest(
            peer_hash="abcd1234",
            limit=25,
            before_timestamp=1700000000.0,
            status_filter="delivered",
        )
        payload = req.to_payload()
        assert payload == {
            "peer_hash": "abcd1234",
            "limit": 25,
            "before_timestamp": 1700000000.0,
            "status_filter": "delivered",
        }

    def test_to_wire_round_trip(self):
        """to_wire should return correct type and payload."""
        req = QueryMessagesRequest(peer_hash="abcd1234", limit=10)
        msg_type, payload = req.to_wire()
        assert msg_type == IPCMessageType.QUERY_MESSAGES
        assert payload["peer_hash"] == "abcd1234"
        assert payload["limit"] == 10


class TestControlClientConversationMethods:
    """Tests for ControlClient.query_conversations and query_messages."""

    @pytest.mark.asyncio
    async def test_query_conversations_parses_response(self):
        """query_conversations should parse response payload correctly."""
        from styrened.ipc.client import ControlClient

        client = ControlClient()
        conversations = [
            {
                "peer_hash": "abcd1234",
                "unread_count": 3,
                "message_count": 15,
                "last_message_timestamp": 1700000000.0,
                "last_message_preview": "Test msg",
            }
        ]

        with patch.object(
            client,
            "_request",
            new_callable=AsyncMock,
            return_value={"conversations": conversations},
        ):
            result = await client.query_conversations()

        assert result == conversations

    @pytest.mark.asyncio
    async def test_query_conversations_empty(self):
        """query_conversations should handle empty response."""
        from styrened.ipc.client import ControlClient

        client = ControlClient()

        with patch.object(
            client,
            "_request",
            new_callable=AsyncMock,
            return_value={"conversations": []},
        ):
            result = await client.query_conversations()

        assert result == []

    @pytest.mark.asyncio
    async def test_query_messages_parses_response(self):
        """query_messages should parse response payload correctly."""
        from styrened.ipc.client import ControlClient

        client = ControlClient()
        messages = [
            {
                "id": 1,
                "peer_hash": "abcd1234",
                "content": "Hello!",
                "timestamp": 1700000000.0,
                "is_outgoing": True,
                "status": "delivered",
            }
        ]

        with patch.object(
            client,
            "_request",
            new_callable=AsyncMock,
            return_value={"messages": messages},
        ):
            result = await client.query_messages("abcd1234")

        assert result == messages

    @pytest.mark.asyncio
    async def test_query_messages_passes_optional_params(self):
        """query_messages should pass optional parameters to request."""
        from styrened.ipc.client import ControlClient

        client = ControlClient()

        with patch.object(
            client,
            "_request",
            new_callable=AsyncMock,
            return_value={"messages": []},
        ) as mock_request:
            await client.query_messages(
                "abcd1234",
                limit=25,
                before_timestamp=1700000000.0,
                status_filter="delivered",
            )

        # Check the request object passed to _request
        call_args = mock_request.call_args
        request = call_args[0][0]
        assert isinstance(request, QueryMessagesRequest)
        assert request.peer_hash == "abcd1234"
        assert request.limit == 25
        assert request.before_timestamp == 1700000000.0
        assert request.status_filter == "delivered"

    @pytest.mark.asyncio
    async def test_query_messages_defaults(self):
        """query_messages with defaults should use limit=50."""
        from styrened.ipc.client import ControlClient

        client = ControlClient()

        with patch.object(
            client,
            "_request",
            new_callable=AsyncMock,
            return_value={"messages": []},
        ) as mock_request:
            await client.query_messages("abcd1234")

        request = mock_request.call_args[0][0]
        assert request.limit == 50
        assert request.before_timestamp is None
        assert request.status_filter is None
