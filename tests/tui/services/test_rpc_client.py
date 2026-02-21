"""Tests for RPC client."""

import asyncio
from uuid import UUID

import pytest

from styrened.rpc.messages import (
    ExecCommand,
    ExecResult,
    RebootCommand,
    RebootResult,
    StatusRequest,
    StatusResponse,
    UpdateConfigCommand,
    UpdateConfigResult,
)
from styrened.protocols.base import LXMFMessage
from styrened.services.lxmf_service import MockLXMFService
from styrened.rpc import RPCClient
from styrened.rpc.errors import (
    RPCInvalidResponseError,
    RPCTimeoutError,
    RPCTransportError,
)


@pytest.fixture
def mock_lxmf() -> MockLXMFService:
    """Create mock LXMF service."""
    return MockLXMFService()


@pytest.fixture
def rpc_client(mock_lxmf: MockLXMFService) -> RPCClient:
    """Create RPC client with mock LXMF service."""
    return RPCClient(mock_lxmf)


class TestRequestIDGeneration:
    """Test request ID generation and uniqueness."""

    def test_request_ids_are_unique(self, rpc_client: RPCClient) -> None:
        """Test that generated request IDs are unique."""
        # Generate multiple request IDs
        request_ids = [rpc_client._generate_request_id() for _ in range(100)]

        # All should be unique
        assert len(request_ids) == len(set(request_ids))

    def test_request_ids_are_valid_uuids(self, rpc_client: RPCClient) -> None:
        """Test that request IDs are valid UUIDs."""
        request_id = rpc_client._generate_request_id()

        # Should be parseable as UUID
        uuid_obj = UUID(request_id)
        assert str(uuid_obj) == request_id

        # Should be version 4 (random)
        assert uuid_obj.version == 4


class TestRequestTracking:
    """Test request tracking and pending request management."""

    @pytest.mark.asyncio
    async def test_add_pending_request(self, rpc_client: RPCClient) -> None:
        """Test adding a pending request."""
        request_id = "test-request-id"
        destination = "test-destination"
        future: asyncio.Future[StatusResponse] = asyncio.Future()

        rpc_client._add_pending_request(request_id, future, destination, "status_request")

        # Should be in pending requests
        assert request_id in rpc_client.pending_requests
        pending = rpc_client.pending_requests[request_id]
        assert pending.future is future
        assert pending.destination == destination
        assert pending.message_type == "status_request"

    @pytest.mark.asyncio
    async def test_remove_pending_request(self, rpc_client: RPCClient) -> None:
        """Test removing a pending request."""
        request_id = "test-request-id"
        destination = "test-destination"
        future: asyncio.Future[StatusResponse] = asyncio.Future()

        rpc_client._add_pending_request(request_id, future, destination, "status_request")
        rpc_client._remove_pending_request(request_id)

        # Should be removed
        assert request_id not in rpc_client.pending_requests

    @pytest.mark.asyncio
    async def test_pending_count_property(self, rpc_client: RPCClient) -> None:
        """Test pending_count property."""
        assert rpc_client.pending_count == 0

        # Add requests
        future1: asyncio.Future[StatusResponse] = asyncio.Future()
        future2: asyncio.Future[StatusResponse] = asyncio.Future()
        rpc_client._add_pending_request("req1", future1, "dest1", "status_request")
        rpc_client._add_pending_request("req2", future2, "dest2", "status_request")

        assert rpc_client.pending_count == 2

        # Remove one
        rpc_client._remove_pending_request("req1")
        assert rpc_client.pending_count == 1


class TestResponseCorrelation:
    """Test request/response correlation."""

    @pytest.mark.asyncio
    async def test_successful_request_response(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test successful request/response correlation."""
        destination = "test-device-hash"

        # Make async call in background
        async def make_call() -> StatusResponse:
            return await rpc_client.call(destination, StatusRequest(), timeout=5.0)

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify message was sent with request_id
        assert len(mock_lxmf.sent_messages) == 1
        sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        assert sent_dest == destination
        assert "request_id" in sent_payload
        assert sent_payload["type"] == "status_request"

        request_id = sent_payload["request_id"]

        # Simulate response
        response_payload = {
            "request_id": request_id,
            "type": "status_response",
            "uptime": 12345,
            "ip": "192.168.0.101",
            "services": ["reticulum", "nomadnet"],
            "disk_used": 4200000000,
            "disk_total": 28000000000,
        }
        mock_lxmf.simulate_receive(destination, response_payload)

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
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test exec command request/response."""
        destination = "test-device-hash"
        command = ExecCommand(command="systemctl", args=["status", "reticulum"])

        # Make async call in background
        async def make_call() -> ExecResult:
            result = await rpc_client.call(destination, command, timeout=5.0)
            assert isinstance(result, ExecResult)
            return result

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Get request ID from sent message
        _sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        request_id = sent_payload["request_id"]

        # Simulate response
        response_payload = {
            "request_id": request_id,
            "type": "exec_result",
            "exit_code": 0,
            "stdout": "● reticulum.service - Reticulum Network Stack\n   Active: active (running)",
            "stderr": "",
        }
        mock_lxmf.simulate_receive(destination, response_payload)

        # Wait for call to complete
        result = await call_task

        assert result.exit_code == 0
        assert "Active: active" in result.stdout
        assert result.stderr == ""


class TestTimeoutHandling:
    """Test timeout behavior."""

    @pytest.mark.asyncio
    async def test_timeout_raises_error(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test that timeout raises RPCTimeoutError."""
        destination = "test-device-hash"

        # Make call with short timeout, don't send response
        with pytest.raises(RPCTimeoutError) as exc_info:
            await rpc_client.call(destination, StatusRequest(), timeout=0.1)

        # Verify error details
        error = exc_info.value
        assert error.destination == destination
        assert error.timeout == 0.1
        assert error.request_id  # Should have a request ID

        # Pending request should be cleaned up
        assert rpc_client.pending_count == 0

    @pytest.mark.asyncio
    async def test_timeout_cleanup(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test that timeout cleans up pending requests."""
        destination = "test-device-hash"

        # Start multiple requests
        tasks = [
            asyncio.create_task(rpc_client.call(destination, StatusRequest(), timeout=0.1))
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
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test multiple concurrent requests to same device."""
        destination = "test-device-hash"

        # Start 5 concurrent requests
        async def make_call(delay: float) -> StatusResponse:
            result = await rpc_client.call(destination, StatusRequest(), timeout=5.0)
            assert isinstance(result, StatusResponse)
            return result

        tasks = [asyncio.create_task(make_call(i * 0.1)) for i in range(5)]

        # Wait for all messages to be sent
        await asyncio.sleep(0.2)

        # Should have 5 pending requests
        assert rpc_client.pending_count == 5

        # Respond to each request
        for _sent_dest, sent_payload in mock_lxmf.sent_messages:
            request_id = sent_payload["request_id"]
            response_payload = {
                "request_id": request_id,
                "type": "status_response",
                "uptime": 12345,
                "ip": "192.168.0.101",
                "services": ["reticulum"],
                "disk_used": 1000000,
                "disk_total": 10000000,
            }
            mock_lxmf.simulate_receive(destination, response_payload)

        # Wait for all calls to complete
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 5
        assert all(isinstance(r, StatusResponse) for r in results)

        # All pending requests should be cleaned up
        assert rpc_client.pending_count == 0

    @pytest.mark.asyncio
    async def test_concurrent_requests_to_different_devices(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test concurrent requests to different devices."""
        devices = [f"device-{i}" for i in range(3)]

        # Start concurrent requests to different devices
        tasks = [
            asyncio.create_task(rpc_client.call(device, StatusRequest(), timeout=5.0))
            for device in devices
        ]

        # Wait for all messages to be sent
        await asyncio.sleep(0.1)

        # Should have 3 pending requests
        assert rpc_client.pending_count == 3

        # Respond to each request
        for sent_dest, sent_payload in mock_lxmf.sent_messages:
            request_id = sent_payload["request_id"]
            response_payload = {
                "request_id": request_id,
                "type": "status_response",
                "uptime": 12345,
                "ip": f"192.168.0.{devices.index(sent_dest) + 1}",
                "services": ["reticulum"],
                "disk_used": 1000000,
                "disk_total": 10000000,
            }
            mock_lxmf.simulate_receive(sent_dest, response_payload)

        # Wait for all calls to complete
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 3
        assert all(isinstance(r, StatusResponse) for r in results)


class TestErrorHandling:
    """Test error handling paths."""

    @pytest.mark.asyncio
    async def test_transport_failure_raises_error(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test that transport failure raises RPCTransportError."""
        destination = "test-device-hash"

        # Configure mock to fail sends
        mock_lxmf.send_should_fail = True

        # Should raise transport error
        with pytest.raises(RPCTransportError) as exc_info:
            await rpc_client.call(destination, StatusRequest(), timeout=5.0)

        # Verify error details
        error = exc_info.value
        assert error.destination == destination

        # No pending requests should be left
        assert rpc_client.pending_count == 0

    @pytest.mark.asyncio
    async def test_missing_request_id_in_response(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test response without request_id raises error."""
        destination = "test-device-hash"

        # Make call in background
        call_task = asyncio.create_task(
            rpc_client.call(destination, StatusRequest(), timeout=5.0)
        )

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Send response without request_id
        response_payload = {
            "type": "status_response",
            "uptime": 12345,
            "ip": "192.168.0.101",
            "services": ["reticulum"],
            "disk_used": 1000000,
            "disk_total": 10000000,
        }
        mock_lxmf.simulate_receive(destination, response_payload)

        # Should still timeout (response ignored)
        with pytest.raises(RPCTimeoutError):
            await call_task

    @pytest.mark.asyncio
    async def test_wrong_request_id_in_response(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test response with wrong request_id is ignored."""
        destination = "test-device-hash"

        # Make call in background
        call_task = asyncio.create_task(
            rpc_client.call(destination, StatusRequest(), timeout=5.0)
        )

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Send response with wrong request_id
        response_payload = {
            "request_id": "wrong-request-id",
            "type": "status_response",
            "uptime": 12345,
            "ip": "192.168.0.101",
            "services": ["reticulum"],
            "disk_used": 1000000,
            "disk_total": 10000000,
        }
        mock_lxmf.simulate_receive(destination, response_payload)

        # Should still timeout (response ignored)
        with pytest.raises(RPCTimeoutError):
            await call_task

    @pytest.mark.asyncio
    async def test_malformed_response_payload(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test malformed response payload raises error."""
        destination = "test-device-hash"

        # Make call in background
        call_task = asyncio.create_task(
            rpc_client.call(destination, StatusRequest(), timeout=5.0)
        )

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Get request ID
        _sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        request_id = sent_payload["request_id"]

        # Send malformed response (missing required fields)
        response_payload = {
            "request_id": request_id,
            "type": "status_response",
            # Missing required fields: uptime, ip, services, disk_used, disk_total
        }
        mock_lxmf.simulate_receive(destination, response_payload)

        # Should raise invalid response error
        with pytest.raises(RPCInvalidResponseError) as exc_info:
            await call_task

        error = exc_info.value
        assert error.request_id == request_id
        assert error.payload == response_payload


class TestConvenienceMethods:
    """Test convenience methods for common operations."""

    @pytest.mark.asyncio
    async def test_call_status(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test call_status convenience method."""
        destination = "test-device-hash"

        # Make call in background
        async def make_call() -> StatusResponse:
            return await rpc_client.call_status(destination, timeout=5.0)

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify message type
        _sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        assert sent_payload["type"] == "status_request"

        # Respond
        request_id = sent_payload["request_id"]
        response_payload = {
            "request_id": request_id,
            "type": "status_response",
            "uptime": 12345,
            "ip": "192.168.0.101",
            "services": ["reticulum"],
            "disk_used": 1000000,
            "disk_total": 10000000,
        }
        mock_lxmf.simulate_receive(destination, response_payload)

        # Should return StatusResponse
        result = await call_task
        assert isinstance(result, StatusResponse)
        assert result.uptime == 12345

    @pytest.mark.asyncio
    async def test_call_exec(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test call_exec convenience method."""
        destination = "test-device-hash"

        # Make call in background
        async def make_call() -> ExecResult:
            return await rpc_client.call_exec(
                destination, "systemctl", ["status", "reticulum"], timeout=5.0
            )

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify message type and args
        _sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        assert sent_payload["type"] == "exec"
        assert sent_payload["command"] == "systemctl"
        assert sent_payload["args"] == ["status", "reticulum"]

        # Respond
        request_id = sent_payload["request_id"]
        response_payload = {
            "request_id": request_id,
            "type": "exec_result",
            "exit_code": 0,
            "stdout": "Active: active (running)",
            "stderr": "",
        }
        mock_lxmf.simulate_receive(destination, response_payload)

        # Should return ExecResult
        result = await call_task
        assert isinstance(result, ExecResult)
        assert result.exit_code == 0


class TestTimeoutConfiguration:
    """Test timeout configuration."""

    @pytest.mark.asyncio
    async def test_set_timeout_for_message_type(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test setting timeout for specific message type."""
        # Set custom timeout
        rpc_client.set_timeout("status_request", 10.0)

        # Verify timeout is stored
        assert rpc_client.get_timeout("status_request") == 10.0

    @pytest.mark.asyncio
    async def test_default_timeout(self, rpc_client: RPCClient) -> None:
        """Test default timeout fallback."""
        # Should use default timeout
        assert rpc_client.get_timeout("unknown_type") == 30.0

        # Change default
        rpc_client.default_timeout = 60.0
        assert rpc_client.get_timeout("unknown_type") == 60.0


class TestRebootCommand:
    """Test reboot command functionality."""

    @pytest.mark.asyncio
    async def test_call_reboot_immediate(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test call_reboot with immediate reboot (no delay)."""
        destination = "test-device-hash"

        # Make call in background
        async def make_call() -> RebootResult:
            return await rpc_client.call_reboot(destination, delay=0, timeout=5.0)

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify message type and payload
        sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        assert sent_dest == destination
        assert sent_payload["type"] == "reboot"
        assert sent_payload["delay"] == 0

        # Respond with reboot result
        request_id = sent_payload["request_id"]
        response_payload = {
            "request_id": request_id,
            "type": "reboot_result",
            "success": True,
            "message": "Reboot initiated",
            "scheduled_time": None,
        }
        mock_lxmf.simulate_receive(destination, response_payload)

        # Should return RebootResult
        result = await call_task
        assert isinstance(result, RebootResult)
        assert result.success is True
        assert result.message == "Reboot initiated"
        assert result.scheduled_time is None

    @pytest.mark.asyncio
    async def test_call_reboot_with_delay(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test call_reboot with delayed reboot."""
        destination = "test-device-hash"

        # Make call with 60 second delay
        async def make_call() -> RebootResult:
            return await rpc_client.call_reboot(destination, delay=60, timeout=5.0)

        call_task = asyncio.create_task(make_call())

        # Wait for message to be sent
        await asyncio.sleep(0.1)

        # Verify delay is sent
        _sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        assert sent_payload["delay"] == 60

        # Respond with scheduled reboot
        request_id = sent_payload["request_id"]
        scheduled_time = 1700000000.0  # Future timestamp
        response_payload = {
            "request_id": request_id,
            "type": "reboot_result",
            "success": True,
            "message": "Reboot scheduled in 60 seconds",
            "scheduled_time": scheduled_time,
        }
        mock_lxmf.simulate_receive(destination, response_payload)

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
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test call_update_config method."""
        destination = "test-device-hash"
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

        # Verify message type and payload
        sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        assert sent_dest == destination
        assert sent_payload["type"] == "update_config"
        assert sent_payload["config"] == config_updates

        # Respond with update result
        request_id = sent_payload["request_id"]
        response_payload = {
            "request_id": request_id,
            "type": "update_config_result",
            "success": True,
            "message": "Configuration updated",
            "updated_keys": ["log_level", "max_retries", "enable_telemetry"],
        }
        mock_lxmf.simulate_receive(destination, response_payload)

        # Should return UpdateConfigResult
        result = await call_task
        assert isinstance(result, UpdateConfigResult)
        assert result.success is True
        assert result.message == "Configuration updated"
        assert len(result.updated_keys) == 3
        assert "log_level" in result.updated_keys

    @pytest.mark.asyncio
    async def test_call_update_config_partial_failure(
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """Test update_config with some keys failing."""
        destination = "test-device-hash"
        config_updates = {
            "log_level": "INVALID",  # Will fail
            "max_retries": 3,  # Will succeed
        }

        async def make_call() -> UpdateConfigResult:
            return await rpc_client.call_update_config(
                destination, config_updates, timeout=5.0
            )

        call_task = asyncio.create_task(make_call())

        await asyncio.sleep(0.1)

        # Get request ID
        _sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        request_id = sent_payload["request_id"]

        # Respond with partial success
        response_payload = {
            "request_id": request_id,
            "type": "update_config_result",
            "success": False,
            "message": "Invalid log_level value",
            "updated_keys": ["max_retries"],  # Only one key updated
        }
        mock_lxmf.simulate_receive(destination, response_payload)

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

    def test_rpc_client_can_handle_rpc_message(self, rpc_client: RPCClient) -> None:
        """RPCClient should handle messages with protocol='rpc'."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={"protocol": "rpc"},
        )

        assert rpc_client.can_handle(msg)

    def test_rpc_client_cannot_handle_non_rpc_message(self, rpc_client: RPCClient) -> None:
        """RPCClient should not handle messages without protocol='rpc'."""
        msg = LXMFMessage(
            source_hash="source",
            destination_hash="dest",
            timestamp=123.0,
            fields={"protocol": "chat"},
        )

        assert not rpc_client.can_handle(msg)

    def test_rpc_client_cannot_handle_no_protocol(self, rpc_client: RPCClient) -> None:
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
        self, rpc_client: RPCClient, mock_lxmf: MockLXMFService
    ) -> None:
        """RPCClient should handle incoming RPC messages."""
        # Send request first
        destination = "device_hash"

        async def make_call():
            return await rpc_client.call_status(destination)

        call_task = asyncio.create_task(make_call())

        # Wait for request to be sent
        await asyncio.sleep(0.1)

        # Get request_id from sent message
        _sent_dest, sent_payload = mock_lxmf.sent_messages[0]
        request_id = sent_payload["request_id"]

        # Create RPC response message
        msg = LXMFMessage(
            source_hash=destination,
            destination_hash="local_hash",
            timestamp=123.0,
            content=None,
            fields={
                "protocol": "rpc",
                "request_id": request_id,
                "type": "status_response",
                "uptime": 12345,
                "ip": "192.168.1.100",
                "services": ["reticulum", "styrene-bond-rpc"],
                "disk_used": 1000000000,
                "disk_total": 10000000000,
            },
            protocol_id="rpc",
        )

        # Handle message (should correlate response to pending request)
        await rpc_client.handle_message(msg)

        # Request should complete
        result = await asyncio.wait_for(call_task, timeout=1.0)
        assert isinstance(result, StatusResponse)
        assert result.uptime == 12345
