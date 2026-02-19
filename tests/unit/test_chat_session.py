"""Unit tests for ChatSession async context manager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.chat_session import ChatEvent, ChatSession


class TestChatEvent:
    """Tests for ChatEvent dataclass."""

    def test_from_payload_parses_all_fields(self):
        """from_payload extracts all fields from event payload."""
        payload = {
            "event_type": "new",
            "message_id": 42,
            "peer_hash": "abcd1234abcd1234",
            "content": "Hello!",
            "timestamp": 1000.0,
            "status": "received",
            "is_outgoing": False,
            "delivery_method": "direct",
            "signature_valid": True,
            "transport_encrypted": True,
        }
        event = ChatEvent.from_payload(payload)
        assert event.event_type == "new"
        assert event.message_id == 42
        assert event.peer_hash == "abcd1234abcd1234"
        assert event.content == "Hello!"
        assert event.timestamp == 1000.0
        assert event.status == "received"
        assert event.is_outgoing is False
        assert event.delivery_method == "direct"
        assert event.signature_valid is True
        assert event.transport_encrypted is True

    def test_from_payload_handles_missing_fields(self):
        """from_payload uses defaults for missing fields."""
        event = ChatEvent.from_payload({})
        assert event.event_type == ""
        assert event.message_id == 0
        assert event.peer_hash == ""
        assert event.content is None
        assert event.is_outgoing is False

    def test_from_payload_handles_status_event(self):
        """from_payload handles status_changed events (no content)."""
        payload = {
            "event_type": "status_changed",
            "message_id": 10,
            "peer_hash": "abcd",
            "status": "delivered",
        }
        event = ChatEvent.from_payload(payload)
        assert event.event_type == "status_changed"
        assert event.status == "delivered"
        assert event.content is None


class TestChatSessionLifecycle:
    """Tests for ChatSession async context manager lifecycle."""

    @pytest.mark.asyncio
    async def test_creates_and_connects_client_when_none_provided(self):
        """ChatSession creates its own client when none provided."""
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.subscribe_messages = AsyncMock(return_value=True)
        mock_client.unsubscribe = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()

        with patch("styrened.chat_session.ControlClient", return_value=mock_client):
            async with ChatSession() as chat:
                assert chat._owns_client is True
                mock_client.connect.assert_called_once()
                mock_client.subscribe_messages.assert_called_once()

        mock_client.unsubscribe.assert_called_once()
        mock_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_provided_client_without_connect(self):
        """ChatSession uses provided client without calling connect."""
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.subscribe_messages = AsyncMock(return_value=True)
        mock_client.unsubscribe = AsyncMock(return_value=True)

        async with ChatSession(client=mock_client) as chat:
            assert chat._owns_client is False
            mock_client.connect.assert_not_called()

        # Should not disconnect external client
        mock_client.disconnect.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscribes_with_peer_filter(self):
        """ChatSession passes peer_filter to subscribe_messages."""
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.subscribe_messages = AsyncMock(return_value=True)
        mock_client.unsubscribe = AsyncMock(return_value=True)

        peers = ["hash1", "hash2"]
        async with ChatSession(client=mock_client, peer_filter=peers):
            mock_client.subscribe_messages.assert_called_once_with(
                peer_hashes=peers
            )

    @pytest.mark.asyncio
    async def test_cleanup_on_error(self):
        """ChatSession unsubscribes even when error occurs."""
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.subscribe_messages = AsyncMock(return_value=True)
        mock_client.unsubscribe = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()

        with pytest.raises(RuntimeError):
            with patch(
                "styrened.chat_session.ControlClient", return_value=mock_client
            ):
                async with ChatSession() as chat:
                    raise RuntimeError("Test error")

        mock_client.unsubscribe.assert_called_once()
        mock_client.disconnect.assert_called_once()


class TestChatSessionDelegation:
    """Tests for ChatSession method delegation to ControlClient."""

    @pytest.mark.asyncio
    async def test_send_delegates_to_client(self):
        """send delegates to client.send_chat."""
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.subscribe_messages = AsyncMock(return_value=True)
        mock_client.unsubscribe = AsyncMock(return_value=True)
        mock_client.send_chat = AsyncMock(return_value={"message_id": 1})

        async with ChatSession(client=mock_client) as chat:
            result = await chat.send("abcd", "Hello!", title="Test")

        mock_client.send_chat.assert_called_once_with(
            "abcd", "Hello!", title="Test"
        )
        assert result == {"message_id": 1}

    @pytest.mark.asyncio
    async def test_mark_read_delegates_to_client(self):
        """mark_read delegates to client.mark_read."""
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.subscribe_messages = AsyncMock(return_value=True)
        mock_client.unsubscribe = AsyncMock(return_value=True)
        mock_client.mark_read = AsyncMock(return_value=5)

        async with ChatSession(client=mock_client) as chat:
            result = await chat.mark_read("abcd")

        assert result == 5

    @pytest.mark.asyncio
    async def test_conversations_delegates_to_client(self):
        """conversations delegates to client.query_conversations."""
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.subscribe_messages = AsyncMock(return_value=True)
        mock_client.unsubscribe = AsyncMock(return_value=True)
        mock_client.query_conversations = AsyncMock(return_value=[{"peer_hash": "a"}])

        async with ChatSession(client=mock_client) as chat:
            result = await chat.conversations()

        assert result == [{"peer_hash": "a"}]

    @pytest.mark.asyncio
    async def test_set_contact_delegates_to_client(self):
        """set_contact delegates to client.set_contact."""
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.subscribe_messages = AsyncMock(return_value=True)
        mock_client.unsubscribe = AsyncMock(return_value=True)
        mock_client.set_contact = AsyncMock(
            return_value={"peer_hash": "abcd", "alias": "Alice"}
        )

        async with ChatSession(client=mock_client) as chat:
            result = await chat.set_contact("abcd", "Alice")

        assert result["alias"] == "Alice"

    @pytest.mark.asyncio
    async def test_resolve_name_delegates_to_client(self):
        """resolve_name delegates to client.resolve_name."""
        mock_client = AsyncMock()
        mock_client.connected = True
        mock_client.subscribe_messages = AsyncMock(return_value=True)
        mock_client.unsubscribe = AsyncMock(return_value=True)
        mock_client.resolve_name = AsyncMock(return_value="abcd1234")

        async with ChatSession(client=mock_client) as chat:
            result = await chat.resolve_name("alice")

        assert result == "abcd1234"
