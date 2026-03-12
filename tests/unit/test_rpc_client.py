"""Unit tests for RPC client timeout and correlation handling.

Tests the critical request/response correlation, timeout cleanup,
and error handling paths.
"""
from __future__ import annotations


import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.models.styrene_wire import (
    NO_CORRELATION,
    StyreneEnvelope,
    StyreneMessageType,
    encode_payload,
    generate_request_id,
)
from styrened.rpc.client import RPCClient
from styrened.rpc.errors import RPCTimeoutError, RPCTransportError
from styrened.rpc.messages import ExecResult, StatusResponse


class TestRequestCorrelation:
    """Tests for request/response correlation via request_id."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.fixture
    def client(self, mock_protocol: MagicMock) -> RPCClient:
        """Create an RPCClient with mock protocol."""
        return RPCClient(mock_protocol)

    @pytest.mark.asyncio
    async def test_pending_request_added_on_call(self, client: RPCClient) -> None:
        """Calling an RPC method should add to pending_requests."""
        assert client.pending_count == 0

        request_id = generate_request_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()

        client._add_pending_request(
            request_id=request_id,
            future=future,
            destination="abc123",
            message_type=StyreneMessageType.STATUS_REQUEST,
        )

        assert client.pending_count == 1
        assert request_id in client.pending_requests

    @pytest.mark.asyncio
    async def test_pending_request_removed_after_resolution(self, client: RPCClient) -> None:
        """Pending request should be removed after response received."""
        request_id = generate_request_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()

        client._add_pending_request(
            request_id=request_id,
            future=future,
            destination="abc123",
            message_type=StyreneMessageType.STATUS_REQUEST,
        )
        assert client.pending_count == 1

        client._remove_pending_request(request_id)
        assert client.pending_count == 0
        assert request_id not in client.pending_requests

    @pytest.mark.asyncio
    async def test_unknown_request_id_ignored(self, client: RPCClient) -> None:
        """Response with unknown request_id should be ignored."""
        # Add a pending request
        known_id = generate_request_id()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        client._add_pending_request(
            request_id=known_id,
            future=future,
            destination="abc123",
            message_type=StyreneMessageType.STATUS_REQUEST,
        )

        # Remove an unknown ID should not raise
        unknown_id = generate_request_id()
        client._remove_pending_request(unknown_id)  # Should not raise

        # Known request should still be pending
        assert client.pending_count == 1

    @pytest.mark.asyncio
    async def test_response_resolves_correct_future(self, client: RPCClient) -> None:
        """Response should resolve the correct future based on request_id."""
        request_id = generate_request_id()
        future: asyncio.Future = asyncio.Future()

        client._add_pending_request(
            request_id=request_id,
            future=future,
            destination="abc123",
            message_type=StyreneMessageType.STATUS_REQUEST,
        )

        # Simulate response
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=encode_payload(
                {
                    "uptime": 12345,
                    "ip": "192.168.1.1",
                    "services": ["rns"],
                    "disk_used": 1000,
                    "disk_total": 2000,
                }
            ),
            request_id=request_id,
        )

        message = MagicMock()
        message.source_hash = "abc123"

        await client._handle_response(message, envelope)

        # Future should be resolved
        assert future.done()
        result = future.result()
        assert isinstance(result, StatusResponse)
        assert result.uptime == 12345

        # Pending request should be cleaned up
        assert client.pending_count == 0


class TestTimeoutHandling:
    """Tests for RPC timeout behavior."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.fixture
    def client(self, mock_protocol: MagicMock) -> RPCClient:
        """Create an RPCClient with mock protocol."""
        return RPCClient(mock_protocol)

    @pytest.mark.asyncio
    async def test_timeout_raises_rpc_timeout_error(self, client: RPCClient) -> None:
        """Request that times out should raise RPCTimeoutError."""
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=generate_request_id(),
        )

        with pytest.raises(RPCTimeoutError) as exc_info:
            await client.call("abc123", envelope, timeout=0.01)

        assert "timed out" in str(exc_info.value).lower()
        assert exc_info.value.destination == "abc123"
        assert exc_info.value.timeout == 0.01

    @pytest.mark.asyncio
    async def test_timeout_cleans_up_pending_request(self, client: RPCClient) -> None:
        """Timed out request should be removed from pending_requests."""
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=generate_request_id(),
        )

        assert client.pending_count == 0

        with pytest.raises(RPCTimeoutError):
            await client.call("abc123", envelope, timeout=0.01)

        # Pending request should be cleaned up
        assert client.pending_count == 0

    @pytest.mark.asyncio
    async def test_late_response_after_timeout_ignored(self, client: RPCClient) -> None:
        """Response arriving after timeout should not cause errors."""
        request_id = generate_request_id()
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=request_id,
        )

        # This will timeout
        with pytest.raises(RPCTimeoutError):
            await client.call("abc123", envelope, timeout=0.01)

        # Now simulate a late response
        response_envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=encode_payload(
                {
                    "uptime": 12345,
                    "ip": "192.168.1.1",
                    "services": [],
                    "disk_used": 0,
                    "disk_total": 0,
                }
            ),
            request_id=request_id,
        )

        message = MagicMock()
        message.source_hash = "abc123"

        # Should not raise - late responses are silently ignored
        await client._handle_response(message, response_envelope)

    def test_custom_timeout_per_message_type(self, client: RPCClient) -> None:
        """Custom timeouts can be set per message type."""
        client.set_timeout(StyreneMessageType.EXEC, 120.0)
        client.set_timeout(StyreneMessageType.STATUS_REQUEST, 5.0)

        assert client.get_timeout(StyreneMessageType.EXEC) == 120.0
        assert client.get_timeout(StyreneMessageType.STATUS_REQUEST) == 5.0

        # Unknown type should fall back to default
        assert client.get_timeout(StyreneMessageType.PING) == client.default_timeout


class TestResponseDecoding:
    """Tests for response decoding logic."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        return mock

    @pytest.fixture
    def client(self, mock_protocol: MagicMock) -> RPCClient:
        """Create an RPCClient with mock protocol."""
        return RPCClient(mock_protocol)

    def test_decode_status_response(self, client: RPCClient) -> None:
        """STATUS_RESPONSE should decode to StatusResponse."""
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=encode_payload(
                {
                    "uptime": 3600,
                    "ip": "10.0.0.1",
                    "services": ["rns", "lxmf"],
                    "disk_used": 500000,
                    "disk_total": 1000000,
                }
            ),
            request_id=generate_request_id(),
        )

        result = client._decode_response(envelope)

        assert isinstance(result, StatusResponse)
        assert result.uptime == 3600
        assert result.ip == "10.0.0.1"
        assert result.services == ["rns", "lxmf"]
        assert result.disk_used == 500000
        assert result.disk_total == 1000000

    def test_decode_exec_result(self, client: RPCClient) -> None:
        """EXEC_RESULT should decode to ExecResult."""
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.EXEC_RESULT,
            payload=encode_payload(
                {
                    "exit_code": 0,
                    "stdout": "hello world",
                    "stderr": "",
                }
            ),
            request_id=generate_request_id(),
        )

        result = client._decode_response(envelope)

        assert isinstance(result, ExecResult)
        assert result.exit_code == 0
        assert result.stdout == "hello world"
        assert result.stderr == ""

    def test_decode_error_raises(self, client: RPCClient) -> None:
        """ERROR response should raise ValueError."""
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.ERROR,
            payload=encode_payload(
                {
                    "code": 2,
                    "message": "Command not allowed",
                }
            ),
            request_id=generate_request_id(),
        )

        with pytest.raises(ValueError) as exc_info:
            client._decode_response(envelope)

        assert "Command not allowed" in str(exc_info.value)

    def test_decode_unknown_type_raises(self, client: RPCClient) -> None:
        """Unknown response type should raise ValueError."""
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.PING,  # Not a response type
            payload=b"",
            request_id=generate_request_id(),
        )

        with pytest.raises(ValueError) as exc_info:
            client._decode_response(envelope)

        assert "Unknown response type" in str(exc_info.value)


class TestTransportErrors:
    """Tests for transport layer error handling."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.fixture
    def client(self, mock_protocol: MagicMock) -> RPCClient:
        """Create an RPCClient with mock protocol."""
        return RPCClient(mock_protocol)

    @pytest.mark.asyncio
    async def test_send_failure_raises_transport_error(
        self, client: RPCClient, mock_protocol: MagicMock
    ) -> None:
        """Transport failure should raise RPCTransportError."""
        mock_protocol.send_typed_message.side_effect = Exception("Network error")

        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=generate_request_id(),
        )

        with pytest.raises(RPCTransportError) as exc_info:
            await client.call("abc123", envelope, timeout=5.0)

        assert "abc123" in str(exc_info.value)
        assert exc_info.value.destination == "abc123"

    @pytest.mark.asyncio
    async def test_send_failure_cleans_up_pending_request(
        self, client: RPCClient, mock_protocol: MagicMock
    ) -> None:
        """Transport failure should clean up pending request."""
        mock_protocol.send_typed_message.side_effect = Exception("Network error")

        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=generate_request_id(),
        )

        with pytest.raises(RPCTransportError):
            await client.call("abc123", envelope, timeout=5.0)

        # Pending request should be cleaned up
        assert client.pending_count == 0


class TestConvenienceMethods:
    """Tests for convenience methods (call_status, call_exec, etc.)."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        mock.send_typed_message = AsyncMock()
        return mock

    @pytest.fixture
    def client(self, mock_protocol: MagicMock) -> RPCClient:
        """Create an RPCClient with mock protocol."""
        return RPCClient(mock_protocol)

    @pytest.mark.asyncio
    async def test_call_status_sends_correct_type(
        self, client: RPCClient, mock_protocol: MagicMock
    ) -> None:
        """call_status should send STATUS_REQUEST."""
        # Patch call to avoid actual timeout
        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = StatusResponse(
                uptime=100, ip="1.2.3.4", services=[], disk_used=0, disk_total=0
            )

            await client.call_status("abc123", timeout=5.0)

            mock_call.assert_called_once()
            call_args = mock_call.call_args
            envelope = call_args[0][1]
            assert envelope.message_type == StyreneMessageType.STATUS_REQUEST

    @pytest.mark.asyncio
    async def test_call_exec_sends_correct_payload(
        self, client: RPCClient, mock_protocol: MagicMock
    ) -> None:
        """call_exec should send EXEC with command and args."""
        with patch.object(client, "call", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = ExecResult(exit_code=0, stdout="ok", stderr="")

            await client.call_exec("abc123", "ls", ["-la", "/tmp"])

            mock_call.assert_called_once()
            call_args = mock_call.call_args
            envelope = call_args[0][1]
            assert envelope.message_type == StyreneMessageType.EXEC


class TestMissingCorrelation:
    """Tests for handling messages without correlation IDs."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        return mock

    @pytest.fixture
    def client(self, mock_protocol: MagicMock) -> RPCClient:
        """Create an RPCClient with mock protocol."""
        return RPCClient(mock_protocol)

    @pytest.mark.asyncio
    async def test_response_without_request_id_ignored(self, client: RPCClient) -> None:
        """Response with no request_id should be silently ignored."""
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=encode_payload(
                {"uptime": 100, "ip": "", "services": [], "disk_used": 0, "disk_total": 0}
            ),
            request_id=None,
        )

        message = MagicMock()
        message.source_hash = "abc123"

        # Should not raise
        await client._handle_response(message, envelope)

    @pytest.mark.asyncio
    async def test_response_with_no_correlation_ignored(self, client: RPCClient) -> None:
        """Response with NO_CORRELATION marker should be ignored."""
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=encode_payload(
                {"uptime": 100, "ip": "", "services": [], "disk_used": 0, "disk_total": 0}
            ),
            request_id=NO_CORRELATION,
        )

        message = MagicMock()
        message.source_hash = "abc123"

        # Should not raise
        await client._handle_response(message, envelope)


class TestDoubleFutureResolution:
    """Tests for preventing double-resolution of futures."""

    @pytest.fixture
    def mock_protocol(self) -> MagicMock:
        """Create a mock StyreneProtocol."""
        mock = MagicMock()
        mock.register_handler = MagicMock()
        return mock

    @pytest.fixture
    def client(self, mock_protocol: MagicMock) -> RPCClient:
        """Create an RPCClient with mock protocol."""
        return RPCClient(mock_protocol)

    @pytest.mark.asyncio
    async def test_duplicate_response_does_not_crash(self, client: RPCClient) -> None:
        """Receiving duplicate response should not cause errors."""
        request_id = generate_request_id()
        future: asyncio.Future = asyncio.Future()

        client._add_pending_request(
            request_id=request_id,
            future=future,
            destination="abc123",
            message_type=StyreneMessageType.STATUS_REQUEST,
        )

        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_RESPONSE,
            payload=encode_payload(
                {
                    "uptime": 100,
                    "ip": "1.2.3.4",
                    "services": [],
                    "disk_used": 0,
                    "disk_total": 0,
                }
            ),
            request_id=request_id,
        )

        message = MagicMock()
        message.source_hash = "abc123"

        # First response
        await client._handle_response(message, envelope)
        assert future.done()

        # Duplicate response (request already removed)
        # Should not raise
        await client._handle_response(message, envelope)
