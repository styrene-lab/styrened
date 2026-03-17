"""Integration tests for RPC over LXMF.

Tests end-to-end RPC message flow:
- Operator (RPC client) sends request
- Device (RPC server) receives, processes, responds
- Operator receives response with correct request_id

This covers the critical gaps identified in the test coverage assessment:
- Gap 2: RPC Server implementation integration
- Gap 3: Real LXMF message exchange (simulated)
- Gap 4: Device-side handler execution
- Gap 5: End-to-end operator→device→operator flow
"""
from __future__ import annotations

import asyncio
import json

# Import RPC server and handlers
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from styrened.protocols.base import LXMFMessage

# Import RPC components
from styrened.rpc import RPCClient

parent_src = Path(__file__).parent.parent.parent / "packages" / "styrene-bond-rpc" / "src"
if parent_src.exists():
    sys.path.insert(0, str(parent_src))

try:
    from styrene_bond_rpc.auth import AuthorizationService  # noqa: E402
    from styrene_bond_rpc.handlers import (  # noqa: E402
        handle_exec,
        handle_reboot,
        handle_status,
        handle_update_config,
    )
    from styrene_bond_rpc.server import RPCServer  # noqa: E402
except ImportError:
    pytest.skip("styrene_bond_rpc not available", allow_module_level=True)


class MockLXMFTransport:
    """Mock LXMF transport that simulates message delivery.

    This simulates real LXMF message exchange between operator and device.
    Messages are routed based on destination_hash.
    """

    def __init__(self):
        """Initialize mock transport."""
        self._endpoints = {}  # destination_hash -> endpoint
        self._message_log = []  # Track all messages for debugging

    def register_endpoint(self, destination_hash: str, endpoint: MockLXMFEndpoint):
        """Register an endpoint (operator or device) with this transport.

        Args:
            destination_hash: Hex string identifying this endpoint
            endpoint: Endpoint instance to receive messages
        """
        self._endpoints[destination_hash] = endpoint

    async def send_message(self, destination: str, source: str, content: dict, fields: dict):
        """Send message from source to destination.

        Args:
            destination: Destination hash
            source: Source hash
            content: Message content (will be JSON-encoded)
            fields: Message fields
        """
        # Log message
        self._message_log.append(
            {
                "from": source,
                "to": destination,
                "content": content,
                "fields": fields,
            }
        )

        # Route to destination
        if destination in self._endpoints:
            endpoint = self._endpoints[destination]

            # Create LXMF message
            msg = LXMFMessage(
                source_hash=source,
                destination_hash=destination,
                timestamp=0.0,
                content=json.dumps(content) if isinstance(content, dict) else content,
                fields=fields,
                protocol_id=fields.get("protocol", "unknown"),
            )

            # Deliver to endpoint
            await endpoint.receive_message(msg)
        else:
            raise ValueError(f"No endpoint registered for {destination}")


class MockLXMFEndpoint:
    """Mock LXMF endpoint (represents operator or device)."""

    def __init__(self, identity_hash: str, transport: MockLXMFTransport):
        """Initialize endpoint.

        Args:
            identity_hash: This endpoint's identity hash
            transport: Transport to use for sending messages
        """
        self.identity_hash = identity_hash
        self.transport = transport
        self.router = Mock()
        self.router.handle_outbound = AsyncMock(side_effect=self._handle_outbound)
        self.identity = Mock()
        self.identity.hexhash = identity_hash

        # Register with transport
        transport.register_endpoint(identity_hash, self)

        # Message handlers
        self._message_handlers = []

    def register_handler(self, handler):
        """Register a message handler.

        Args:
            handler: Async function that takes LXMFMessage
        """
        self._message_handlers.append(handler)

    async def receive_message(self, msg: LXMFMessage):
        """Handle incoming message.

        Args:
            msg: Incoming LXMF message
        """
        for handler in self._message_handlers:
            await handler(msg)

    async def _handle_outbound(self, message):
        """Handle outbound message from router.

        This is called when the RPC client/server sends a message via router.handle_outbound().

        Args:
            message: Outbound message (dict or LXMF message)
        """
        if isinstance(message, dict):
            # RPC response from server - extract destination and fields
            destination = message.get("_destination", "unknown")
            fields = message
            content = message
        else:
            # LXMF message from client
            destination = (
                message.destination_hash if hasattr(message, "destination_hash") else "unknown"
            )
            fields = message.fields if hasattr(message, "fields") else {}
            content = json.loads(message.content) if hasattr(message, "content") else {}

        await self.transport.send_message(
            destination=destination,
            source=self.identity_hash,
            content=content,
            fields=fields,
        )


@pytest.fixture
def mock_transport():
    """Create mock LXMF transport."""
    return MockLXMFTransport()


@pytest.fixture
def operator_endpoint(mock_transport):
    """Create operator endpoint."""
    return MockLXMFEndpoint("operator_hash", mock_transport)


@pytest.fixture
def device_endpoint(mock_transport):
    """Create device endpoint."""
    return MockLXMFEndpoint("device_hash", mock_transport)


@pytest.fixture
def mock_lxmf_service(operator_endpoint, mock_transport):
    """Create mock LXMF service for operator."""
    from styrened.services.lxmf_service import MockLXMFService

    service = MockLXMFService()

    # Save original send_message
    original_send = service.send_message

    # Override send_message to route through mock transport
    def patched_send(destination: str, payload: dict) -> bool:
        """Send message via mock transport.

        This must be synchronous to match the LXMFService interface,
        but we schedule async transport routing in the background.
        """
        # Track in sent_messages (for test assertions)
        result = original_send(destination, payload)

        # Extract fields from payload
        fields = {
            "protocol": payload.get("protocol", "rpc"),
            "type": payload.get("type"),
            "request_id": payload.get("request_id"),
        }

        # Add command-specific fields
        for key in ["command", "args", "delay", "config"]:
            if key in payload:
                fields[key] = payload[key]

        # Schedule async transport send in background
        # The RPC client will await the response future, giving time for this to complete
        _task = asyncio.create_task(
            mock_transport.send_message(
                destination=destination,
                source=operator_endpoint.identity_hash,
                content=payload,
                fields=fields,
            )
        )
        # Store reference to prevent garbage collection
        _ = _task

        return result

    service.send_message = patched_send

    return service


@pytest.fixture
def rpc_client(operator_endpoint, mock_lxmf_service):
    """Create RPC client for operator."""
    client = RPCClient(lxmf_service=mock_lxmf_service)

    # Register client to receive responses
    operator_endpoint.register_handler(client.handle_message)

    return client


@pytest.fixture
def rpc_server(device_endpoint):
    """Create RPC server for device."""
    server = RPCServer(
        router=device_endpoint.router,
        identity=device_endpoint.identity,
    )

    # Register device to receive requests
    device_endpoint.register_handler(server.handle_message)

    # Register command handlers
    server.register_handler("status_request", handle_status)
    server.register_handler("exec", handle_exec)
    server.register_handler("reboot", handle_reboot)
    server.register_handler("update_config", handle_update_config)

    return server


class TestRPCServerIntegration:
    """Test RPC server integration with handlers (Priority 1.2)."""

    @pytest.mark.asyncio
    async def test_server_routes_status_request_to_handler(self, rpc_server, device_endpoint):
        """Server should route status_request to handle_status and return response."""
        # Create status request message
        msg = LXMFMessage(
            source_hash="client_hash",
            destination_hash="device_hash",
            timestamp=0.0,
            fields={
                "protocol": "rpc",
                "type": "status_request",
                "request_id": "test-123",
            },
        )

        with (
            patch("psutil.boot_time", return_value=100.0),
            patch("psutil.disk_usage") as mock_disk,
            patch("time.time", return_value=200.0),
        ):
            mock_disk.return_value = Mock(used=1000000, total=10000000)
            # Server handles message
            await rpc_server.handle_message(msg)

        # Verify router.handle_outbound was called with response
        device_endpoint.router.handle_outbound.assert_called_once()
        response = device_endpoint.router.handle_outbound.call_args[0][0]

        assert response["type"] == "status_response"
        assert response["request_id"] == "test-123"
        assert response["protocol"] == "rpc"
        assert response["uptime"] == 100  # 200 - 100

    @pytest.mark.asyncio
    async def test_server_handles_unknown_command(self, rpc_server, device_endpoint):
        """Server should return error response for unknown command type."""
        msg = LXMFMessage(
            source_hash="client_hash",
            destination_hash="device_hash",
            timestamp=0.0,
            fields={
                "protocol": "rpc",
                "type": "unknown_command",
                "request_id": "test-456",
            },
        )

        await rpc_server.handle_message(msg)

        # Verify error response sent
        device_endpoint.router.handle_outbound.assert_called_once()
        response = device_endpoint.router.handle_outbound.call_args[0][0]

        assert response["type"] == "error"
        assert response["request_id"] == "test-456"
        assert "Unknown command type" in response["error"]

    @pytest.mark.asyncio
    async def test_server_handles_handler_exception(self, rpc_server, device_endpoint):
        """Server should catch handler exceptions and return error response."""

        # Register handler that raises exception
        async def failing_handler(msg):
            raise ValueError("Handler failed")

        rpc_server.register_handler("failing_command", failing_handler)

        msg = LXMFMessage(
            source_hash="client_hash",
            destination_hash="device_hash",
            timestamp=0.0,
            fields={
                "protocol": "rpc",
                "type": "failing_command",
                "request_id": "test-789",
            },
        )

        await rpc_server.handle_message(msg)

        # Verify error response sent
        device_endpoint.router.handle_outbound.assert_called_once()
        response = device_endpoint.router.handle_outbound.call_args[0][0]

        assert response["type"] == "error"
        assert response["request_id"] == "test-789"
        assert "Handler error" in response["error"]


class TestEndToEndRPCFlow:
    """Test end-to-end operator→device→operator flow (Gap 5)."""

    @pytest.mark.asyncio
    async def test_status_request_full_roundtrip(
        self,
        rpc_client,
        rpc_server,
        operator_endpoint,
        device_endpoint,
        mock_transport,
    ):
        """Test full status request roundtrip from operator to device and back."""
        # Patch system calls
        with (
            patch("psutil.boot_time", return_value=100.0),
            patch("psutil.disk_usage") as mock_disk,
            patch("time.time", return_value=1000.0),
        ):
            mock_disk.return_value = Mock(used=5000000000, total=50000000000)
            # Operator sends status request to device
            # Message routing happens automatically through fixtures:
            # 1. RPC client → mock_lxmf_service.send_message()
            # 2. mock_lxmf_service → mock_transport.send_message()
            # 3. mock_transport → device_endpoint.receive_message()
            # 4. device_endpoint → rpc_server.handle_message()
            # 5. rpc_server → device_endpoint.router.handle_outbound()
            # 6. device_endpoint → mock_transport.send_message() (back to operator)
            # 7. mock_transport → operator_endpoint.receive_message()
            # 8. operator_endpoint → rpc_client.handle_message()
            response = await rpc_client.call_status("device_hash", timeout=10.0)

        # Verify response
        assert response is not None
        assert response.uptime == 900  # 1000 - 100
        assert response.disk_used == 5000000000
        assert response.disk_total == 50000000000

    @pytest.mark.asyncio
    async def test_exec_command_full_roundtrip(
        self,
        rpc_client,
        rpc_server,
        operator_endpoint,
        device_endpoint,
        mock_transport,
    ):
        """Test full exec command roundtrip."""
        # Mock subprocess execution
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                returncode=0,
                stdout="Hello World\n",
                stderr="",
            )

            # Operator sends exec command to device
            # Message routing happens automatically through fixtures (see status test above)
            response = await rpc_client.call_exec(
                "device_hash",
                command="echo",
                args=["Hello", "World"],
                timeout=10.0,
            )

        # Verify response
        assert response is not None
        assert response.exit_code == 0
        assert response.stdout == "Hello World\n"
        assert response.stderr == ""


class TestAuthorizationIntegration:
    """Test authorization enforcement in RPC server (Priority 2.1)."""

    @pytest.fixture
    def auth_config_file(self, tmp_path):
        """Create authorization config file."""
        config_file = tmp_path / "auth.yaml"
        config_file.write_text("""
identities:
  - hash: "authorized_operator"
    name: "Authorized Operator"
    permissions:
      - status_request
      - exec

  - hash: "monitor_only"
    name: "Monitor User"
    permissions:
      - status_request

  - hash: "admin_user"
    name: "Admin"
    permissions:
      - status_request
      - exec
      - reboot
      - update_config
""")
        return config_file

    @pytest.fixture
    def auth_service(self, auth_config_file):
        """Create authorization service."""
        return AuthorizationService(str(auth_config_file))

    @pytest.fixture
    def auth_server(self, device_endpoint, auth_service):
        """Create RPC server with authorization enforcement."""
        server = RPCServer(
            router=device_endpoint.router,
            identity=device_endpoint.identity,
        )

        # Wrap handlers with authorization check
        def authorized_handler(command_type, handler):
            async def wrapper(msg: LXMFMessage):
                source_hash = msg.source_hash

                # Check authorization
                if not auth_service.is_authorized(source_hash, command_type):
                    return {
                        "type": "error",
                        "error": f"Unauthorized: {command_type} requires permission",
                        "exit_code": -1,
                    }

                # Call actual handler
                return await handler(msg)

            return wrapper

        # Register authorized handlers
        server.register_handler(
            "status_request", authorized_handler("status_request", handle_status)
        )
        server.register_handler("exec", authorized_handler("exec", handle_exec))
        server.register_handler("reboot", authorized_handler("reboot", handle_reboot))
        server.register_handler(
            "update_config", authorized_handler("update_config", handle_update_config)
        )

        device_endpoint.register_handler(server.handle_message)
        return server

    @pytest.mark.asyncio
    async def test_authorized_operator_can_execute_commands(
        self,
        auth_server,
        device_endpoint,
    ):
        """Authorized operator should be able to execute allowed commands."""
        msg = LXMFMessage(
            source_hash="authorized_operator",
            destination_hash="device_hash",
            timestamp=0.0,
            fields={
                "protocol": "rpc",
                "type": "exec",
                "request_id": "test-auth-1",
                "command": "echo",
                "args": ["test"],
            },
        )

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="test\n", stderr="")

            await auth_server.handle_message(msg)

        # Verify success response
        device_endpoint.router.handle_outbound.assert_called_once()
        response = device_endpoint.router.handle_outbound.call_args[0][0]

        assert response["type"] == "exec_result"
        assert response["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_monitor_cannot_execute_commands(
        self,
        auth_server,
        device_endpoint,
    ):
        """Monitor user should be denied exec commands."""
        msg = LXMFMessage(
            source_hash="monitor_only",
            destination_hash="device_hash",
            timestamp=0.0,
            fields={
                "protocol": "rpc",
                "type": "exec",
                "request_id": "test-auth-2",
                "command": "echo",
                "args": ["test"],
            },
        )

        await auth_server.handle_message(msg)

        # Verify error response
        device_endpoint.router.handle_outbound.assert_called_once()
        response = device_endpoint.router.handle_outbound.call_args[0][0]

        assert response["type"] == "error"
        assert "Unauthorized" in response["error"]

    @pytest.mark.asyncio
    async def test_unknown_identity_denied_all_commands(
        self,
        auth_server,
        device_endpoint,
    ):
        """Unknown identity should be denied all commands."""
        msg = LXMFMessage(
            source_hash="unknown_identity",
            destination_hash="device_hash",
            timestamp=0.0,
            fields={
                "protocol": "rpc",
                "type": "status_request",
                "request_id": "test-auth-3",
            },
        )

        await auth_server.handle_message(msg)

        # Verify error response
        device_endpoint.router.handle_outbound.assert_called_once()
        response = device_endpoint.router.handle_outbound.call_args[0][0]

        assert response["type"] == "error"
        assert "Unauthorized" in response["error"]
