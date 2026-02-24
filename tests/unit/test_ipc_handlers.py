"""Unit tests for IPC handlers.

Tests null checks and error handling for IPC request handlers,
ensuring proper error responses when daemon or dependencies are unavailable.
"""

from unittest.mock import MagicMock

import pytest

from styrened.ipc.handlers import IPCHandlers
from styrened.ipc.messages import (
    CmdDeviceStatusRequest,
    CmdExecRequest,
    CmdSendRequest,
    ErrorResponse,
)


class MockDaemon:
    """Mock daemon for testing IPC handlers."""

    def __init__(
        self,
        rpc_client=None,
        operator_destination=None,
        lxmf_service=None,
        start_time=0.0,
    ):
        self._rpc_client = rpc_client
        self._operator_destination = operator_destination
        self._lxmf_service = lxmf_service
        self._start_time = start_time
        self.config = MockConfig()
        self.lifecycle = MockLifecycle()

    def _announce(self):
        """Mock announce method."""
        pass


class MockConfig:
    """Mock config for testing."""

    def __init__(self):
        self.reticulum = MockReticulumConfig()
        self.rpc = MockRpcConfig()
        self.discovery = MockDiscoveryConfig()
        self.chat = MockChatConfig()
        self.api = MockApiConfig()


class MockReticulumConfig:
    def __init__(self):
        self.mode = MockMode()
        self.announce_interval = 300
        self.hub_enabled = False


class MockMode:
    def __init__(self):
        self.value = "standalone"


class MockRpcConfig:
    def __init__(self):
        self.enabled = True
        self.relay_mode = False
        self.allow_command_execution = True


class MockDiscoveryConfig:
    def __init__(self):
        self.enabled = True
        self.auto_announce = True


class MockChatConfig:
    def __init__(self):
        self.enabled = True
        self.auto_reply_mode = MagicMock()
        self.auto_reply_mode.value = "disabled"
        self.auto_reply_cooldown = 60
        self.persist_messages = False


class MockApiConfig:
    def __init__(self):
        self.enabled = False
        self.port = 8080


class MockLifecycle:
    def __init__(self):
        self._initialized = True


class TestIPCHandlersNullChecks:
    """Tests for null daemon/dependency checks."""

    @pytest.mark.asyncio
    async def test_handle_exec_returns_error_when_daemon_none(self):
        """CMD_EXEC should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        request = CmdExecRequest(
            destination="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            command="uptime",
        )

        response = await handlers.handle_cmd_exec(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_exec_returns_error_when_rpc_client_none(self):
        """CMD_EXEC should return error when RPC client is None."""
        daemon = MockDaemon(rpc_client=None)
        handlers = IPCHandlers(daemon=daemon)

        request = CmdExecRequest(
            destination="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            command="uptime",
        )

        response = await handlers.handle_cmd_exec(request)

        assert isinstance(response, ErrorResponse)
        assert "RPC client not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_device_status_returns_error_when_daemon_none(self):
        """CMD_DEVICE_STATUS should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        request = CmdDeviceStatusRequest(
            destination="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        )

        response = await handlers.handle_cmd_device_status(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_device_status_returns_error_when_rpc_client_none(self):
        """CMD_DEVICE_STATUS should return error when RPC client is None."""
        daemon = MockDaemon(rpc_client=None)
        handlers = IPCHandlers(daemon=daemon)

        request = CmdDeviceStatusRequest(
            destination="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        )

        response = await handlers.handle_cmd_device_status(request)

        assert isinstance(response, ErrorResponse)
        assert "RPC client not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_announce_returns_error_when_daemon_none(self):
        """CMD_ANNOUNCE should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import CmdAnnounceRequest

        request = CmdAnnounceRequest()

        response = await handlers.handle_cmd_announce(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_announce_returns_error_when_destination_none(self):
        """CMD_ANNOUNCE should return error when operator destination is None."""
        daemon = MockDaemon(operator_destination=None)
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdAnnounceRequest

        request = CmdAnnounceRequest()

        response = await handlers.handle_cmd_announce(request)

        assert isinstance(response, ErrorResponse)
        assert "Operator destination not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_query_status_returns_error_when_daemon_none(self):
        """QUERY_STATUS should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import QueryStatusRequest

        request = QueryStatusRequest()

        response = await handlers.handle_query_status(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_query_identity_returns_error_when_daemon_none(self):
        """QUERY_IDENTITY should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import QueryIdentityRequest

        request = QueryIdentityRequest()

        response = await handlers.handle_query_identity(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message


class TestIPCHandlersValidation:
    """Tests for request validation."""

    @pytest.mark.asyncio
    async def test_handle_exec_requires_destination(self):
        """CMD_EXEC should require destination."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdExecRequest(destination="", command="uptime")

        response = await handlers.handle_cmd_exec(request)

        assert isinstance(response, ErrorResponse)
        assert "destination is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_exec_requires_command(self):
        """CMD_EXEC should require command."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdExecRequest(
            destination="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            command="",
        )

        response = await handlers.handle_cmd_exec(request)

        assert isinstance(response, ErrorResponse)
        assert "command is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_device_status_requires_destination(self):
        """CMD_DEVICE_STATUS should require destination."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdDeviceStatusRequest(destination="")

        response = await handlers.handle_cmd_device_status(request)

        assert isinstance(response, ErrorResponse)
        assert "destination is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_send_requires_destination(self):
        """CMD_SEND should require destination."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdSendRequest(destination="", message="hello")

        response = await handlers.handle_cmd_send(request)

        assert isinstance(response, ErrorResponse)
        assert "destination is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_send_requires_message(self):
        """CMD_SEND should require message."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdSendRequest(
            destination="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            message="",
        )

        response = await handlers.handle_cmd_send(request)

        assert isinstance(response, ErrorResponse)
        assert "message is required" in response.message


class TestIPCHandlersPing:
    """Tests for ping handler."""

    @pytest.mark.asyncio
    async def test_handle_ping_returns_version(self):
        """PING should return daemon version."""
        # Ping doesn't require daemon
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import PingRequest

        request = PingRequest()

        response = await handlers.handle_ping(request)

        from styrened.ipc.messages import PongResponse

        assert isinstance(response, PongResponse)
        assert response.daemon_version is not None


class TestIPCHandlersQueryConfig:
    """Tests for config query handler."""

    @pytest.mark.asyncio
    async def test_handle_query_config_returns_sanitized_config(self):
        """QUERY_CONFIG should return sanitized config."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import QueryConfigRequest

        request = QueryConfigRequest()

        response = await handlers.handle_query_config(request)

        from styrened.ipc.messages import ResultResponse

        assert isinstance(response, ResultResponse)
        assert "config" in response.data
        assert "reticulum" in response.data["config"]
        assert "rpc" in response.data["config"]


class TestIPCHandlersChatValidation:
    """Tests for chat command validation."""

    @pytest.mark.asyncio
    async def test_handle_cmd_send_chat_requires_peer_hash(self):
        """CMD_SEND_CHAT should require peer_hash."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSendChatRequest

        request = CmdSendChatRequest(peer_hash="", content="hello")

        response = await handlers.handle_cmd_send_chat(request)

        assert isinstance(response, ErrorResponse)
        assert "peer_hash is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_cmd_send_chat_requires_content(self):
        """CMD_SEND_CHAT should require content."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSendChatRequest

        request = CmdSendChatRequest(peer_hash="a" * 32, content="")

        response = await handlers.handle_cmd_send_chat(request)

        assert isinstance(response, ErrorResponse)
        assert "content is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_cmd_send_chat_rejects_none_peer_hash(self):
        """CMD_SEND_CHAT should reject None peer_hash."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSendChatRequest

        request = CmdSendChatRequest(peer_hash=None, content="hello")

        response = await handlers.handle_cmd_send_chat(request)

        assert isinstance(response, ErrorResponse)
        assert "peer_hash is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_cmd_send_chat_rejects_none_content(self):
        """CMD_SEND_CHAT should reject None content."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSendChatRequest

        request = CmdSendChatRequest(peer_hash="a" * 32, content=None)

        response = await handlers.handle_cmd_send_chat(request)

        assert isinstance(response, ErrorResponse)
        assert "content is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_query_messages_requires_peer_hash(self):
        """QUERY_MESSAGES should require peer_hash."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import QueryMessagesRequest

        request = QueryMessagesRequest(peer_hash="")

        response = await handlers.handle_query_messages(request)

        assert isinstance(response, ErrorResponse)
        assert "peer_hash is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_cmd_mark_read_requires_peer_hash(self):
        """CMD_MARK_READ should require peer_hash."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdMarkReadRequest

        request = CmdMarkReadRequest(peer_hash="")

        response = await handlers.handle_cmd_mark_read(request)

        assert isinstance(response, ErrorResponse)
        assert "peer_hash is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_cmd_delete_conversation_requires_peer_hash(self):
        """CMD_DELETE_CONVERSATION should require peer_hash."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdDeleteConversationRequest

        request = CmdDeleteConversationRequest(peer_hash="")

        response = await handlers.handle_cmd_delete_conversation(request)

        assert isinstance(response, ErrorResponse)
        assert "peer_hash is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_cmd_delete_message_requires_message_id(self):
        """CMD_DELETE_MESSAGE should require message_id."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdDeleteMessageRequest

        request = CmdDeleteMessageRequest(message_id=0)

        response = await handlers.handle_cmd_delete_message(request)

        assert isinstance(response, ErrorResponse)
        assert "message_id must be a positive integer" in response.message

    @pytest.mark.asyncio
    async def test_handle_cmd_retry_message_requires_message_id(self):
        """CMD_RETRY_MESSAGE should require message_id."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdRetryMessageRequest

        request = CmdRetryMessageRequest(message_id=0)

        response = await handlers.handle_cmd_retry_message(request)

        assert isinstance(response, ErrorResponse)
        assert "message_id must be a positive integer" in response.message


class TestIPCHandlersChatNullChecks:
    """Tests for chat handlers null checks."""

    @pytest.mark.asyncio
    async def test_handle_cmd_send_chat_returns_error_when_daemon_none(self):
        """CMD_SEND_CHAT should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import CmdSendChatRequest

        request = CmdSendChatRequest(peer_hash="a" * 32, content="hello")

        response = await handlers.handle_cmd_send_chat(request)

        assert isinstance(response, ErrorResponse)

    @pytest.mark.asyncio
    async def test_handle_query_conversations_returns_error_when_daemon_none(self):
        """QUERY_CONVERSATIONS should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import QueryConversationsRequest

        request = QueryConversationsRequest()

        response = await handlers.handle_query_conversations(request)

        assert isinstance(response, ErrorResponse)

    @pytest.mark.asyncio
    async def test_handle_query_messages_returns_error_when_daemon_none(self):
        """QUERY_MESSAGES should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import QueryMessagesRequest

        request = QueryMessagesRequest(peer_hash="a" * 32)

        response = await handlers.handle_query_messages(request)

        assert isinstance(response, ErrorResponse)

    @pytest.mark.asyncio
    async def test_handle_cmd_sync_messages_returns_error_when_daemon_none(self):
        """CMD_SYNC_MESSAGES should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import CmdSyncMessagesRequest

        request = CmdSyncMessagesRequest()

        response = await handlers.handle_cmd_sync_messages(request)

        assert isinstance(response, ErrorResponse)

    @pytest.mark.asyncio
    async def test_handle_query_path_info_returns_error_when_daemon_none(self):
        """QUERY_PATH_INFO should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import QueryPathInfoRequest

        request = QueryPathInfoRequest(destination_hash="a" * 32)

        response = await handlers.handle_query_path_info(request)

        assert isinstance(response, ErrorResponse)

    @pytest.mark.asyncio
    async def test_handle_query_path_info_requires_destination_hash(self):
        """QUERY_PATH_INFO should return error when destination_hash is empty."""
        handlers = IPCHandlers(daemon=MockDaemon())

        from styrened.ipc.messages import QueryPathInfoRequest

        request = QueryPathInfoRequest(destination_hash="")

        response = await handlers.handle_query_path_info(request)

        assert isinstance(response, ErrorResponse)


class TestIPCHandlersPageBrowser:
    """Tests for page browser handlers."""

    @pytest.mark.asyncio
    async def test_handle_query_page_returns_error_when_daemon_none(self):
        """QUERY_PAGE should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import QueryPageRequest

        request = QueryPageRequest(destination_hash="a" * 32)

        response = await handlers.handle_query_page(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_query_page_returns_error_when_service_none(self):
        """QUERY_PAGE should return error when page browser service is None."""
        daemon = MockDaemon()
        daemon._page_browser_service = None
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import QueryPageRequest

        request = QueryPageRequest(destination_hash="a" * 32)

        response = await handlers.handle_query_page(request)

        assert isinstance(response, ErrorResponse)
        assert "Page browser service not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_query_page_requires_destination_hash(self):
        """QUERY_PAGE should require destination_hash."""
        daemon = MockDaemon()
        daemon._page_browser_service = True  # truthy
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import QueryPageRequest

        request = QueryPageRequest(destination_hash="")

        response = await handlers.handle_query_page(request)

        assert isinstance(response, ErrorResponse)
        assert "destination_hash is required" in response.message

    @pytest.mark.asyncio
    async def test_handle_cmd_page_disconnect_returns_error_when_daemon_none(self):
        """CMD_PAGE_DISCONNECT should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import CmdPageDisconnectRequest

        request = CmdPageDisconnectRequest(destination_hash="a" * 32)

        response = await handlers.handle_cmd_page_disconnect(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_cmd_page_disconnect_requires_destination_hash(self):
        """CMD_PAGE_DISCONNECT should require destination_hash."""
        daemon = MockDaemon()
        daemon._page_browser_service = True
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdPageDisconnectRequest

        request = CmdPageDisconnectRequest(destination_hash="")

        response = await handlers.handle_cmd_page_disconnect(request)

        assert isinstance(response, ErrorResponse)
        assert "destination_hash is required" in response.message


class TestIPCHandlersPageServer:
    """Tests for page server status handler."""

    @pytest.mark.asyncio
    async def test_handle_page_server_status_returns_error_when_daemon_none(self):
        """QUERY_PAGE_SERVER_STATUS should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import QueryPageServerStatusRequest

        request = QueryPageServerStatusRequest()
        response = await handlers.handle_query_page_server_status(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_page_server_status_returns_error_when_service_none(self):
        """QUERY_PAGE_SERVER_STATUS should return error when service is None."""
        daemon = MockDaemon()
        daemon._page_server_service = None
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import QueryPageServerStatusRequest

        request = QueryPageServerStatusRequest()
        response = await handlers.handle_query_page_server_status(request)

        assert isinstance(response, ErrorResponse)
        assert "Page server service not initialized" in response.message

    @pytest.mark.asyncio
    async def test_handle_page_server_status_returns_status(self):
        """QUERY_PAGE_SERVER_STATUS should return service status."""
        daemon = MockDaemon()

        mock_svc = MagicMock()
        mock_svc.is_started = True
        mock_svc.owns_destination = False
        mock_svc.pages_dir = "/tmp/pages"
        mock_svc.static_pages = ["index.mu", "about.mu"]
        mock_svc.registered_handlers = ["/page/styrene/status.mu"]
        daemon._page_server_service = mock_svc

        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import QueryPageServerStatusRequest, ResultResponse

        request = QueryPageServerStatusRequest()
        response = await handlers.handle_query_page_server_status(request)

        assert isinstance(response, ResultResponse)
        assert response.data["enabled"] is True
        assert response.data["started"] is True
        assert response.data["owns_destination"] is False
        assert response.data["pages_dir"] == "/tmp/pages"
        assert response.data["static_pages"] == ["index.mu", "about.mu"]
        assert response.data["registered_handlers"] == ["/page/styrene/status.mu"]
