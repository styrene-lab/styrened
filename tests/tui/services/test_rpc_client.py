"""Tests for RPC client."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from styrened.models.styrene_wire import (
    STYRENE_VERSION,
    StyreneEnvelope,
    StyreneMessageType,
    encode_payload,
    generate_request_id,
)
from styrened.protocols.base import LXMFMessage
from styrened.rpc import RPCClient
from styrened.rpc.errors import (
    RPCInvalidResponseError,
    RPCTimeoutError,
    RPCTransportError,
)
from styrened.rpc.messages import (
    ExecResult,
    RebootCommand,
    RebootResult,
    StatusResponse,
    UpdateConfigCommand,
    UpdateConfigResult,
)


class MockStyreneProtocol:
    """Mock StyreneProtocol for testing RPCClient.

    Provides the register_handler, send_typed_message, and can_handle methods
    that RPCClient uses from StyreneProtocol.
    """

    def __init__(self):
        self.handlers: dict[StyreneMessageType, list] = {}
        self.sent_messages: list[tuple[str, StyreneMessageType, bytes, bytes | None]] = []
        self.send_should_fail = False

    def register_handler(self, message_type: StyreneMessageType, handler) -> None:
        """Register handler for a message type."""
        if message_type not in self.handlers:
            self.handlers[message_type] = []
        self.handlers[message_type].append(handler)

    async def send_typed_message(
        self,
        destination: str,
        message_type: StyreneMessageType,
        payload: bytes,
        request_id: bytes | None = None,
    ) -> None:
        """Mock send_typed_message."""
        if self.send_should_fail:
            raise Exception("Send failed")
        self.sent_messages.append((destination, message_type, payload, request_id))

    def can_handle(self, message: LXMFMessage) -> bool:
        """Mock can_handle - check for styrene.io custom type."""
        custom_type = message.fields.get("protocol")
        return custom_type == "rpc" or "styrene" in str(message.fields.get(0xFB, ""))

    async def simulate_response(
        self,
        client: RPCClient,
        request_id: bytes,
        message_type: StyreneMessageType,
        payload_data: dict[str, Any],
    ) -> None:
        """Simulate receiving a response by calling the registered handler."""
        envelope = StyreneEnvelope(
            version=STYRENE_VERSION,
            message_type=message_type,
            payload=encode_payload(payload_data),
            request_id=request_id,
        )
        message = LXMFMessage(
            source_hash="remote",
            destination_hash="local",
            timestamp=123.0,
            fields={},
        )

        # Find and call the registered handler for this message type
        handlers = self.handlers.get(message_type, [])
        for handler in handlers:
            await handler(message, envelope)


@pytest.fixture
def mock_protocol() -> MockStyreneProtocol:
    """Create mock Styrene protocol."""
    return MockStyreneProtocol()


@pytest.fixture
def rpc_client(mock_protocol: MockStyreneProtocol) -> RPCClient:
    """Create RPC client with mock protocol."""
    return RPCClient(mock_protocol)


class TestRequestIDGeneration:
    """Test request ID generation and uniqueness."""

    def test_request_ids_are_unique(self) -> None:
        """Test that generated request IDs are unique."""
        request_ids = [generate_request_id() for _ in range(100)]

        # All should be unique
        assert len(request_ids) == len(set(request_ids))

    def test_request_ids_are_16_bytes(self) -> None:
        """Test that request IDs are 16 bytes."""
        request_id = generate_request_id()

        assert isinstance(request_id, bytes)
        assert len(request_id) == 16


class TestRequestTracking:
    """Test request tracking and pending request management."""

    @pytest.mark.asyncio
    async def test_add_pending_request(self, rpc_client: RPCClient) -> None:
        """Test adding a pending request."""
        request_id = generate_request_id()
        destination = "test-destination"
        future: asyncio.Future = asyncio.Future()

        rpc_client._add_pending_request(
            request_id, future, destination, StyreneMessageType.STATUS_REQUEST
        )

        # Should be in pending requests
        assert request_id in rpc_client.pending_requests
        pending = rpc_client.pending_requests[request_id]
        assert pending.future is future
        assert pending.destination == destination
        assert pending.message_type == StyreneMessageType.STATUS_REQUEST

    @pytest.mark.asyncio
    async def test_remove_pending_request(self, rpc_client: RPCClient) -> None:
        """Test removing a pending request."""
        request_id = generate_request_id()
        destination = "test-destination"
        future: asyncio.Future = asyncio.Future()

        rpc_client._add_pending_request(
            request_id, future, destination, StyreneMessageType.STATUS_REQUEST
        )
        rpc_client._remove_pending_request(request_id)

        # Should be removed
        assert request_id not in rpc_client.pending_requests

    @pytest.mark.asyncio
    async def test_pending_count_property(self, rpc_client: RPCClient) -> None:
        """Test pending_count property."""
        assert rpc_client.pending_count == 0

        # Add requests
        future1: asyncio.Future = asyncio.Future()
        future2: asyncio.Future = asyncio.Future()
        rid1 = generate_request_id()
        rid2 = generate_request_id()
        rpc_client._add_pending_request(
            rid1, future1, "dest1", StyreneMessageType.STATUS_REQUEST
        )
        rpc_client._add_pending_request(
            rid2, future2, "dest2", StyreneMessageType.STATUS_REQUEST
        )

        assert rpc_client.pending_count == 2

        # Remove one
        rpc_client._remove_pending_request(rid1)
        assert rpc_client.pending_count == 1


class TestResponseCorrelation:
    """Test request/response correlation."""

    @pytest.mark.asyncio
    async def test_successful_request_response(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test successful request/response correlation."""
        destination = "test-device-hash1234"

        # Make async call in background
        async def make_call() -> StatusResponse:
            return await rpc_client.call_status(destination, timeout=5.0)

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify message was sent
        assert len(mock_protocol.sent_messages) == 1
        sent_dest, sent_type, sent_payload, sent_rid = mock_protocol.sent_messages[0]
        assert sent_dest == destination
        assert sent_type == StyreneMessageType.STATUS_REQUEST
        assert sent_rid is not None

        # Simulate response via the registered handler
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.STATUS_RESPONSE,
            {
                "uptime": 12345,
                "ip": "192.168.0.101",
                "services": ["reticulum", "nomadnet"],
                "disk_used": 4200000000,
                "disk_total": 28000000000,
            },
        )

        # Wait for call to complete
        result = await call_task

        # Verify response
        assert isinstance(result, StatusResponse)
        assert result.uptime == 12345
        assert result.ip == "192.168.0.101"
        assert result.services == ["reticulum", "nomadnet"]

        # Pending request should be cleaned up
        assert rpc_client.pending_count == 0

    @pytest.mark.asyncio
    async def test_exec_request_response(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test exec command request/response."""
        destination = "test-device-hash1234"

        # Make async call in background
        async def make_call() -> ExecResult:
            result = await rpc_client.call_exec(
                destination, "systemctl", ["status", "reticulum"], timeout=5.0
            )
            assert isinstance(result, ExecResult)
            return result

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Get request ID from sent message
        _sent_dest, _sent_type, _sent_payload, sent_rid = mock_protocol.sent_messages[0]

        # Simulate response
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.EXEC_RESULT,
            {
                "exit_code": 0,
                "stdout": "Active: active (running)",
                "stderr": "",
            },
        )

        # Wait for call to complete
        result = await call_task

        assert result.exit_code == 0
        assert "Active: active" in result.stdout
        assert result.stderr == ""


class TestTimeoutHandling:
    """Test timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_raises_error(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test that timeout raises RPCTimeoutError."""
        destination = "test-device-hash1234"

        # Make call with short timeout, don't send response
        with pytest.raises(RPCTimeoutError) as exc_info:
            await rpc_client.call_status(destination, timeout=0.1)

        # Verify error details
        error = exc_info.value
        assert error.destination == destination
        assert error.timeout == 0.1
        assert error.request_id  # Should have a request ID

        # Pending request should be cleaned up
        assert rpc_client.pending_count == 0

    @pytest.mark.asyncio
    async def test_timeout_cleanup(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test that timeout cleans up pending requests."""
        destination = "test-device-hash1234"

        # Start multiple requests
        tasks = [
            asyncio.create_task(rpc_client.call_status(destination, timeout=0.1))
            for _ in range(3)
        ]

        # All should timeout
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(r, RPCTimeoutError) for r in results)

        # All pending requests should be cleaned up
        assert rpc_client.pending_count == 0


class TestConcurrentRequests:
    """Test concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_to_same_device(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test multiple concurrent requests to same device."""
        destination = "test-device-hash1234"

        # Start 5 concurrent requests
        tasks = [
            asyncio.create_task(rpc_client.call_status(destination, timeout=5.0))
            for _ in range(5)
        ]

        # Wait for all messages to be sent
        await asyncio.sleep(0.2)

        # Should have 5 pending requests
        assert rpc_client.pending_count == 5

        # Respond to each request
        for _sent_dest, _sent_type, _sent_payload, sent_rid in mock_protocol.sent_messages:
            await mock_protocol.simulate_response(
                rpc_client,
                sent_rid,
                StyreneMessageType.STATUS_RESPONSE,
                {
                    "uptime": 12345,
                    "ip": "192.168.0.101",
                    "services": ["reticulum"],
                    "disk_used": 1000000,
                    "disk_total": 10000000,
                },
            )

        # Wait for all calls to complete
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 5
        assert all(isinstance(r, StatusResponse) for r in results)

        # All pending requests should be cleaned up
        assert rpc_client.pending_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_requests_to_different_devices(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test concurrent requests to different devices."""
        devices = [f"device-{i}-hash12345" for i in range(3)]

        # Start concurrent requests to different devices
        tasks = [
            asyncio.create_task(rpc_client.call_status(device, timeout=5.0))
            for device in devices
        ]

        # Wait for all messages to be sent
        await asyncio.sleep(0.1)

        # Should have 3 pending requests
        assert rpc_client.pending_count == 3

        # Respond to each request
        for sent_dest, _sent_type, _sent_payload, sent_rid in mock_protocol.sent_messages:
            await mock_protocol.simulate_response(
                rpc_client,
                sent_rid,
                StyreneMessageType.STATUS_RESPONSE,
                {
                    "uptime": 12345,
                    "ip": f"192.168.0.{devices.index(sent_dest) + 1}",
                    "services": ["reticulum"],
                    "disk_used": 1000000,
                    "disk_total": 10000000,
                },
            )

        # Wait for all calls to complete
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 3
        assert all(isinstance(r, StatusResponse) for r in results)


class TestErrorHandling:
    """Test error handling paths."""

    @pytest.mark.asyncio
    async def test_transport_failure_raises_error(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test that transport failure raises RPCTransportError."""
        destination = "test-device-hash1234"

        # Configure mock to fail sends
        mock_protocol.send_should_fail = True

        # Should raise transport error
        with pytest.raises(RPCTransportError) as exc_info:
            await rpc_client.call_status(destination, timeout=5.0)

        # Verify error details
        error = exc_info.value
        assert error.destination == destination

        # No pending requests should be left
        assert rpc_client.pending_count == 0

    @pytest.mark.asyncio
    async def test_missing_request_id_in_response(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test response without matching request_id times out."""
        destination = "test-device-hash1234"

        # Make call in background
        call_task = asyncio.create_task(
            rpc_client.call_status(destination, timeout=0.5)
        )

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Send response with wrong request_id (won't match)
        wrong_rid = generate_request_id()
        await mock_protocol.simulate_response(
            rpc_client,
            wrong_rid,
            StyreneMessageType.STATUS_RESPONSE,
            {
                "uptime": 12345,
                "ip": "192.168.0.101",
                "services": ["reticulum"],
                "disk_used": 1000000,
                "disk_total": 10000000,
            },
        )

        # Should still timeout (response ignored)
        with pytest.raises(RPCTimeoutError):
            await call_task

    @pytest.mark.asyncio
    async def test_wrong_request_id_in_response(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test response with wrong request_id is ignored."""
        destination = "test-device-hash1234"

        # Make call in background
        call_task = asyncio.create_task(
            rpc_client.call_status(destination, timeout=0.5)
        )

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Send response with wrong request_id
        wrong_rid = generate_request_id()
        await mock_protocol.simulate_response(
            rpc_client,
            wrong_rid,
            StyreneMessageType.STATUS_RESPONSE,
            {
                "uptime": 12345,
                "ip": "192.168.0.101",
                "services": ["reticulum"],
                "disk_used": 1000000,
                "disk_total": 10000000,
            },
        )

        # Should still timeout (response ignored)
        with pytest.raises(RPCTimeoutError):
            await call_task

    @pytest.mark.asyncio
    async def test_malformed_response_payload(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test malformed response payload raises error."""
        destination = "test-device-hash1234"

        # Make call in background
        call_task = asyncio.create_task(
            rpc_client.call_status(destination, timeout=5.0)
        )

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Get request ID
        _sent_dest, _sent_type, _sent_payload, sent_rid = mock_protocol.sent_messages[0]

        # Send response with an ERROR type (which raises ValueError in _decode_response)
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.ERROR,
            {"code": 1, "message": "Something went wrong"},
        )

        # Should raise RPCInvalidResponseError (ERROR responses are converted to exceptions)
        with pytest.raises(RPCInvalidResponseError):
            await call_task


class TestConvenienceMethods:
    """Test convenience methods for common operations."""

    @pytest.mark.asyncio
    async def test_call_status(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test call_status convenience method."""
        destination = "test-device-hash1234"

        # Make call in background
        async def make_call() -> StatusResponse:
            return await rpc_client.call_status(destination, timeout=5.0)

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify message type
        _sent_dest, sent_type, _sent_payload, sent_rid = mock_protocol.sent_messages[0]
        assert sent_type == StyreneMessageType.STATUS_REQUEST

        # Respond
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.STATUS_RESPONSE,
            {
                "uptime": 12345,
                "ip": "192.168.0.101",
                "services": ["reticulum"],
                "disk_used": 1000000,
                "disk_total": 10000000,
            },
        )

        # Should return StatusResponse
        result = await call_task
        assert isinstance(result, StatusResponse)
        assert result.uptime == 12345

    @pytest.mark.asyncio
    async def test_call_exec(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test call_exec convenience method."""
        destination = "test-device-hash1234"

        # Make call in background
        async def make_call() -> ExecResult:
            return await rpc_client.call_exec(
                destination, "systemctl", ["status", "reticulum"], timeout=5.0
            )

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify message type
        _sent_dest, sent_type, _sent_payload, sent_rid = mock_protocol.sent_messages[0]
        assert sent_type == StyreneMessageType.EXEC

        # Respond
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.EXEC_RESULT,
            {
                "exit_code": 0,
                "stdout": "Active: active (running)",
                "stderr": "",
            },
        )

        # Should return ExecResult
        result = await call_task
        assert isinstance(result, ExecResult)
        assert result.exit_code == 0


class TestTimeoutConfiguration:
    """Test timeout configuration."""

    def test_set_timeout_for_message_type(
        self, rpc_client: RPCClient,
    ) -> None:
        """Test setting timeout for specific message type."""
        rpc_client.set_timeout(StyreneMessageType.STATUS_REQUEST, 10.0)

        assert rpc_client.get_timeout(StyreneMessageType.STATUS_REQUEST) == 10.0

    def test_default_timeout(self, rpc_client: RPCClient) -> None:
        """Test default timeout fallback."""
        # Should use default timeout for unknown types
        assert rpc_client.get_timeout(StyreneMessageType.CHAT) == 30.0

        # Change default
        rpc_client.default_timeout = 60.0
        assert rpc_client.get_timeout(StyreneMessageType.CHAT) == 60.0


class TestRebootCommand:
    """Test reboot command functionality."""

    @pytest.mark.asyncio
    async def test_call_reboot_immediate(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test call_reboot with immediate reboot (no delay)."""
        destination = "test-device-hash1234"

        # Make call in background
        async def make_call() -> RebootResult:
            return await rpc_client.call_reboot(destination, delay=0, timeout=5.0)

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify message type
        sent_dest, sent_type, sent_payload, sent_rid = mock_protocol.sent_messages[0]
        assert sent_dest == destination
        assert sent_type == StyreneMessageType.REBOOT

        # Respond with reboot result
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.REBOOT_RESULT,
            {
                "success": True,
                "message": "Reboot initiated",
                "scheduled_time": None,
            },
        )

        # Should return RebootResult
        result = await call_task
        assert isinstance(result, RebootResult)
        assert result.success is True
        assert result.message == "Reboot initiated"

    @pytest.mark.asyncio
    async def test_call_reboot_with_delay(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test call_reboot with delayed reboot."""
        destination = "test-device-hash1234"

        # Make call with 60 second delay
        async def make_call() -> RebootResult:
            return await rpc_client.call_reboot(destination, delay=60, timeout=5.0)

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        _sent_dest, _sent_type, _sent_payload, sent_rid = mock_protocol.sent_messages[0]

        # Respond with scheduled reboot
        scheduled_time = 1700000000.0
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.REBOOT_RESULT,
            {
                "success": True,
                "message": "Reboot scheduled in 60 seconds",
                "scheduled_time": scheduled_time,
            },
        )

        # Should return RebootResult with scheduled time
        result = await call_task
        assert isinstance(result, RebootResult)
        assert result.success is True
        assert result.scheduled_time == scheduled_time

    @pytest.mark.asyncio
    async def test_reboot_command_serialization(self) -> None:
        """Test RebootCommand serialization/deserialization."""
        # Test immediate reboot
        cmd = RebootCommand(delay=0)
        data = cmd.to_dict()
        assert data["type"] == "reboot"
        assert data["delay"] == 0

        # Round-trip
        cmd_restored = RebootCommand.from_dict(data)
        assert cmd_restored.delay == 0

        # Test delayed reboot
        cmd = RebootCommand(delay=120)
        data = cmd.to_dict()
        assert data["delay"] == 120

        cmd_restored = RebootCommand.from_dict(data)
        assert cmd_restored.delay == 120


class TestUpdateConfigCommand:
    """Test update config command functionality."""

    @pytest.mark.asyncio
    async def test_call_update_config(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test call_update_config method."""
        destination = "test-device-hash1234"
        config_updates = {
            "log_level": "DEBUG",
            "max_retries": 5,
            "enable_telemetry": False,
        }

        # Make call in background
        async def make_call() -> UpdateConfigResult:
            return await rpc_client.call_update_config(
                destination, config_updates, timeout=5.0
            )

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify message type
        sent_dest, sent_type, sent_payload, sent_rid = mock_protocol.sent_messages[0]
        assert sent_dest == destination
        assert sent_type == StyreneMessageType.CONFIG_UPDATE

        # Respond with update result
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.CONFIG_RESULT,
            {
                "success": True,
                "message": "Configuration updated",
                "updated_keys": ["log_level", "max_retries", "enable_telemetry"],
            },
        )

        # Should return UpdateConfigResult
        result = await call_task
        assert isinstance(result, UpdateConfigResult)
        assert result.success is True
        assert result.message == "Configuration updated"
        assert len(result.updated_keys) == 3
        assert "log_level" in result.updated_keys

    @pytest.mark.asyncio
    async def test_call_update_config_partial_failure(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """Test update_config with some keys failing."""
        destination = "test-device-hash1234"
        config_updates = {
            "log_level": "INVALID",
            "max_retries": 3,
        }

        async def make_call() -> UpdateConfigResult:
            return await rpc_client.call_update_config(
                destination, config_updates, timeout=5.0
            )

        call_task = asyncio.create_task(make_call())

        await asyncio.sleep(0.1)

        # Get request ID
        _sent_dest, _sent_type, _sent_payload, sent_rid = mock_protocol.sent_messages[0]

        # Respond with partial success
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.CONFIG_RESULT,
            {
                "success": False,
                "message": "Invalid log_level value",
                "updated_keys": ["max_retries"],
            },
        )

        # Should return result with partial success
        result = await call_task
        assert isinstance(result, UpdateConfigResult)
        assert result.success is False
        assert result.updated_keys == ["max_retries"]

    @pytest.mark.asyncio
    async def test_update_config_command_serialization(self) -> None:
        """Test UpdateConfigCommand serialization/deserialization."""
        config_updates = {
            "timeout": 30,
            "debug": True,
            "hostname": "device-01",
        }

        cmd = UpdateConfigCommand(config_updates=config_updates)
        data = cmd.to_dict()

        assert data["type"] == "update_config"
        assert data["config"] == config_updates

        # Round-trip
        cmd_restored = UpdateConfigCommand.from_dict(data)
        assert cmd_restored.config_updates == config_updates


class TestProtocolInterface:
    """Test RPCClient's Protocol interface compliance."""

    def test_rpc_client_protocol_id(self, rpc_client: RPCClient) -> None:
        """RPCClient should have protocol_id 'rpc'."""
        assert rpc_client.protocol_id == "rpc"

    def test_rpc_client_can_handle_rpc_message(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """RPCClient should handle messages with protocol='rpc'."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={"protocol": "rpc"},
        )

        assert rpc_client.can_handle(msg)

    def test_rpc_client_cannot_handle_non_rpc_message(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """RPCClient should not handle messages without protocol='rpc'."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={"protocol": "chat"},
        )

        assert not rpc_client.can_handle(msg)

    def test_rpc_client_cannot_handle_no_protocol(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """RPCClient should not handle messages without protocol field."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={},
        )

        assert not rpc_client.can_handle(msg)

    @pytest.mark.asyncio
    async def test_rpc_client_handle_message(
        self, rpc_client: RPCClient, mock_protocol: MockStyreneProtocol
    ) -> None:
        """RPCClient should handle incoming RPC messages."""
        # Send request first
        destination = "device_hash12345678"

        async def make_call():
            return await rpc_client.call_status(destination, timeout=5.0)

        call_task = asyncio.create_task(make_call())

        # Wait for request to be sent
        await asyncio.sleep(0.1)

        # Get request_id from sent message
        _sent_dest, _sent_type, _sent_payload, sent_rid = mock_protocol.sent_messages[0]

        # Simulate response via protocol handler
        await mock_protocol.simulate_response(
            rpc_client,
            sent_rid,
            StyreneMessageType.STATUS_RESPONSE,
            {
                "uptime": 12345,
                "ip": "192.168.1.100",
                "services": ["reticulum", "styrene-bond-rpc"],
                "disk_used": 1000000000,
                "disk_total": 10000000000,
            },
        )

        # Request should complete
        result = await asyncio.wait_for(call_task, timeout=1.0)
        assert isinstance(result, StatusResponse)
        assert result.uptime == 12345
