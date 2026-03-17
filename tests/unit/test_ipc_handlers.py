"""Unit tests for IPC handlers.

Tests null checks and error handling for IPC request handlers,
ensuring proper error responses when daemon or dependencies are unavailable.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.ipc.handlers import IPCHandlers
from styrened.ipc.messages import (
    CmdDeleteConversationRequest,
    CmdDeviceStatusRequest,
    CmdExecRequest,
    CmdMarkReadRequest,
    CmdRemoveContactRequest,
    CmdSendRequest,
    CmdSetAutoReplyRequest,
    CmdSetContactRequest,
    CmdSetIdentityRequest,
    ErrorResponse,
    ResultResponse,
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
        self._activity_events: list[tuple[str, str, dict]] = []

    def _announce(self):
        """Mock announce method."""
        pass

    def _emit_activity_event(self, event_type, peer_hash="", metadata=None):
        """Record activity events for test assertions."""
        self._activity_events.append((event_type, peer_hash, metadata or {}))


class MockIdentityConfig:
    def __init__(self):
        self.display_name = "Test Node"
        self.icon = "🔗"
        self.short_name = None
        self.provider = "file"


class MockConfig:
    """Mock config for testing."""

    def __init__(self):
        self.reticulum = MockReticulumConfig()
        self.rpc = MockRpcConfig()
        self.discovery = MockDiscoveryConfig()
        self.chat = MockChatConfig()
        self.api = MockApiConfig()
        self.identity = MockIdentityConfig()


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
        self.auto_reply_message = ""
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
    async def test_handle_cmd_send_chat_requires_content_or_attachment(self):
        """CMD_SEND_CHAT should require content or attachment."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSendChatRequest

        request = CmdSendChatRequest(peer_hash="a" * 32, content="")

        response = await handlers.handle_cmd_send_chat(request)

        assert isinstance(response, ErrorResponse)
        assert "content or attachment is required" in response.message

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


class TestIPCHandlersIdentity:
    """Tests for identity handlers."""

    @pytest.mark.asyncio
    async def test_query_identity_includes_appearance_fields(self):
        """QUERY_IDENTITY should include display_name, icon, short_name."""
        from unittest.mock import patch

        daemon = MockDaemon()
        daemon.config.identity.display_name = "Alice"
        daemon.config.identity.icon = "🖥️"
        daemon.config.identity.short_name = "alice"
        daemon._operator_destination = MagicMock()
        daemon._operator_destination.hexhash = "def456"
        handlers = IPCHandlers(daemon=daemon)

        with (
            patch(
                "styrened.services.reticulum.get_operator_identity",
                return_value="abc123",
            ),
            patch(
                "styrened.services.lxmf_service.get_lxmf_service",
                return_value=None,
            ),
        ):
            from styrened.ipc.messages import QueryIdentityRequest

            request = QueryIdentityRequest()
            response = await handlers.handle_query_identity(request)

            from styrened.ipc.messages import ResultResponse

            assert isinstance(response, ResultResponse)
            assert response.data["display_name"] == "Alice"
            assert response.data["icon"] == "🖥️"
            assert response.data["short_name"] == "alice"

    @pytest.mark.asyncio
    async def test_set_identity_updates_display_name(self):
        """CMD_SET_IDENTITY should update display_name."""
        from unittest.mock import patch

        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSetIdentityRequest, ResultResponse

        with patch("styrened.services.config.save_core_config"):
            request = CmdSetIdentityRequest(
                display_name="New Name",
                icon="📱",
            )
            response = await handlers.handle_cmd_set_identity(request)

            assert isinstance(response, ResultResponse)
            assert response.data["display_name"] == "New Name"
            assert response.data["icon"] == "📱"
            assert daemon.config.identity.display_name == "New Name"
            assert daemon.config.identity.icon == "📱"

    @pytest.mark.asyncio
    async def test_set_identity_validates_short_name(self):
        """CMD_SET_IDENTITY should reject invalid short_name."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSetIdentityRequest

        request = CmdSetIdentityRequest(
            display_name="Test",
            short_name="INVALID-NAME!!!",
        )
        response = await handlers.handle_cmd_set_identity(request)

        assert isinstance(response, ErrorResponse)
        assert "Invalid short_name" in response.message

    @pytest.mark.asyncio
    async def test_set_identity_clears_short_name_with_empty_string(self):
        """CMD_SET_IDENTITY should clear short_name when set to empty string."""
        from unittest.mock import patch

        daemon = MockDaemon()
        daemon.config.identity.short_name = "alice"
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSetIdentityRequest, ResultResponse

        with patch("styrened.services.config.save_core_config"):
            request = CmdSetIdentityRequest(
                display_name="Alice",
                short_name="",
            )
            response = await handlers.handle_cmd_set_identity(request)

            assert isinstance(response, ResultResponse)
            assert response.data["short_name"] is None
            assert daemon.config.identity.short_name is None

    @pytest.mark.asyncio
    async def test_set_identity_rejects_long_display_name(self):
        """CMD_SET_IDENTITY should reject display_name over 100 chars."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSetIdentityRequest

        request = CmdSetIdentityRequest(
            display_name="A" * 101,
        )
        response = await handlers.handle_cmd_set_identity(request)

        assert isinstance(response, ErrorResponse)
        assert "100 characters" in response.message

    @pytest.mark.asyncio
    async def test_set_identity_triggers_announce(self):
        """CMD_SET_IDENTITY should call _announce() after saving."""
        from unittest.mock import patch

        daemon = MockDaemon()
        daemon._announce = MagicMock()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSetIdentityRequest

        with patch("styrened.services.config.save_core_config"):
            request = CmdSetIdentityRequest(display_name="Test")
            await handlers.handle_cmd_set_identity(request)

            daemon._announce.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_identity_no_daemon_returns_error(self):
        """CMD_SET_IDENTITY should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import CmdSetIdentityRequest

        request = CmdSetIdentityRequest(display_name="Test")
        response = await handlers.handle_cmd_set_identity(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message

    @pytest.mark.asyncio
    async def test_query_config_includes_identity(self):
        """QUERY_CONFIG should include identity section."""
        daemon = MockDaemon()
        daemon.config.identity.display_name = "Alice"
        daemon.config.identity.icon = "🖥️"
        daemon.config.identity.short_name = "alice"
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import QueryConfigRequest, ResultResponse

        request = QueryConfigRequest()
        response = await handlers.handle_query_config(request)

        assert isinstance(response, ResultResponse)
        assert "identity" in response.data["config"]
        assert response.data["config"]["identity"]["display_name"] == "Alice"
        assert response.data["config"]["identity"]["icon"] == "🖥️"
        assert response.data["config"]["identity"]["short_name"] == "alice"


class TestIPCHandlersAttachmentSizeGuard:
    """Tests for base64 attachment size pre-check (Batch 1b)."""

    @pytest.mark.asyncio
    async def test_send_chat_oversized_attachment_b64_rejected(self):
        """CMD_SEND_CHAT should reject oversized base64 attachments before decoding."""

        from styrened.services.attachment_store import DEFAULT_MAX_FILE_SIZE

        daemon = MockDaemon()
        daemon._conversation_service = MagicMock()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSendChatRequest

        # Create a b64 string that exceeds the limit
        max_b64_len = int(DEFAULT_MAX_FILE_SIZE * 4 / 3) + 1024
        oversized_b64 = "A" * (max_b64_len + 100)

        request = CmdSendChatRequest(
            peer_hash="a" * 32,
            content="test with huge attachment",
            attachment_data_b64=oversized_b64,
            attachment_filename="huge.bin",
        )

        response = await handlers.handle_cmd_send_chat(request)

        assert isinstance(response, ErrorResponse)
        assert "Attachment too large" in response.message

    @pytest.mark.asyncio
    async def test_send_chat_valid_attachment_accepted(self):
        """CMD_SEND_CHAT should not reject small valid attachments."""
        import base64

        daemon = MockDaemon()
        daemon._conversation_service = MagicMock()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import CmdSendChatRequest

        # Small valid attachment
        small_b64 = base64.b64encode(b"tiny data").decode()

        request = CmdSendChatRequest(
            peer_hash="a" * 32,
            content="test with small attachment",
            attachment_data_b64=small_b64,
            attachment_filename="tiny.txt",
        )

        # This won't fully succeed (no LXMF service), but it should NOT
        # fail with "Attachment too large"
        response = await handlers.handle_cmd_send_chat(request)
        if isinstance(response, ErrorResponse):
            assert "Attachment too large" not in response.message


class TestIPCHandlersActivityEmission:
    """Tests for activity event emission from IPC handlers."""

    VALID_HASH = "a" * 32

    def _make_daemon_with_conversation_service(self):
        daemon = MockDaemon()
        conv_svc = MagicMock()
        conv_svc.mark_read.return_value = 3
        conv_svc.delete_conversation.return_value = 5
        daemon._conversation_service = conv_svc
        daemon._node_store = None
        daemon._lxmf_service = None
        daemon.send_read_receipts = AsyncMock()
        return daemon

    def _make_daemon_with_contact_service(self):
        daemon = MockDaemon()
        contact_svc = MagicMock()
        contact_svc.set_alias.return_value = MagicMock(
            to_dict=lambda: {"peer_hash": self.VALID_HASH, "alias": "Alice"}
        )
        contact_svc.remove_alias.return_value = True
        daemon._contact_service = contact_svc
        return daemon

    @pytest.mark.asyncio
    async def test_mark_read_emits_conversation_read(self):
        """handle_cmd_mark_read emits conversation_read activity event."""
        daemon = self._make_daemon_with_conversation_service()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdMarkReadRequest(peer_hash=self.VALID_HASH)
        response = await handlers.handle_cmd_mark_read(request)

        assert isinstance(response, ResultResponse)
        assert len(daemon._activity_events) == 1
        event_type, peer_hash, metadata = daemon._activity_events[0]
        assert event_type == "conversation_read"
        assert peer_hash == self.VALID_HASH

    @pytest.mark.asyncio
    async def test_delete_conversation_emits_conversation_deleted(self):
        """handle_cmd_delete_conversation emits conversation_deleted activity event."""
        daemon = self._make_daemon_with_conversation_service()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdDeleteConversationRequest(peer_hash=self.VALID_HASH)
        response = await handlers.handle_cmd_delete_conversation(request)

        assert isinstance(response, ResultResponse)
        assert len(daemon._activity_events) == 1
        event_type, peer_hash, _ = daemon._activity_events[0]
        assert event_type == "conversation_deleted"
        assert peer_hash == self.VALID_HASH

    @pytest.mark.asyncio
    async def test_set_contact_emits_contact_set(self):
        """handle_cmd_set_contact emits contact_set activity event with alias."""
        daemon = self._make_daemon_with_contact_service()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdSetContactRequest(
            peer_hash=self.VALID_HASH, alias="Alice", notes=None
        )
        response = await handlers.handle_cmd_set_contact(request)

        assert isinstance(response, ResultResponse)
        assert len(daemon._activity_events) == 1
        event_type, peer_hash, metadata = daemon._activity_events[0]
        assert event_type == "contact_set"
        assert peer_hash == self.VALID_HASH
        assert metadata["alias"] == "Alice"

    @pytest.mark.asyncio
    async def test_remove_contact_emits_contact_removed(self):
        """handle_cmd_remove_contact emits contact_removed activity event."""
        daemon = self._make_daemon_with_contact_service()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdRemoveContactRequest(peer_hash=self.VALID_HASH)
        response = await handlers.handle_cmd_remove_contact(request)

        assert isinstance(response, ResultResponse)
        assert len(daemon._activity_events) == 1
        event_type, peer_hash, _ = daemon._activity_events[0]
        assert event_type == "contact_removed"
        assert peer_hash == self.VALID_HASH

    @pytest.mark.asyncio
    @patch("styrened.services.config.save_core_config")
    async def test_set_auto_reply_emits_auto_reply_changed(self, mock_save):
        """handle_cmd_set_auto_reply emits auto_reply_changed activity event."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdSetAutoReplyRequest(mode="disabled", message="", cooldown=60)
        response = await handlers.handle_cmd_set_auto_reply(request)

        assert isinstance(response, ResultResponse)
        assert len(daemon._activity_events) == 1
        event_type, peer_hash, metadata = daemon._activity_events[0]
        assert event_type == "auto_reply_changed"
        assert metadata["mode"] == "disabled"

    @pytest.mark.asyncio
    @patch("styrened.services.config.save_core_config")
    async def test_set_identity_emits_identity_changed(self, mock_save):
        """handle_cmd_set_identity emits identity_changed activity event."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        request = CmdSetIdentityRequest(
            display_name="New Name", icon="", short_name=None
        )
        response = await handlers.handle_cmd_set_identity(request)

        assert isinstance(response, ResultResponse)
        assert len(daemon._activity_events) == 1
        event_type, _, metadata = daemon._activity_events[0]
        assert event_type == "identity_changed"
        assert metadata["display_name"] == "New Name"

    @pytest.mark.asyncio
    async def test_emit_is_noop_when_notification_service_none(self):
        """_emit_activity_event should be a no-op, not crash, when called."""
        daemon = MockDaemon()
        # Verify the mock records events but doesn't crash
        daemon._emit_activity_event("test_event")
        assert len(daemon._activity_events) == 1


class TestIPCHandlersPQCStatus:
    """Tests for PQC status query handler."""

    @pytest.mark.asyncio
    async def test_pqc_status_returns_tier(self):
        """CMD_PQC_STATUS returns security_tier when PQC session exists."""
        daemon = MockDaemon()
        mock_pqc_service = MagicMock()
        mock_pqc_service.get_session_status.return_value = {
            "security_tier": "pqc_hybrid",
            "session_state": "established",
            "created_at": 1700000000.0,
            "last_rekeyed_at": 1700003600.0,
            "rekey_count": 2,
        }
        daemon._pqc_service = mock_pqc_service
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import PQCStatusRequest

        request = PQCStatusRequest(peer_hash="a" * 32)
        response = await handlers.handle_cmd_pqc_status(request)

        assert isinstance(response, ResultResponse)
        assert response.data["security_tier"] == "pqc_hybrid"
        assert response.data["session_state"] == "established"
        assert response.data["created_at"] == 1700000000.0
        assert response.data["last_rekeyed_at"] == 1700003600.0
        assert response.data["rekey_count"] == 2
        mock_pqc_service.get_session_status.assert_called_once_with("a" * 32)

    @pytest.mark.asyncio
    async def test_pqc_status_no_session(self):
        """CMD_PQC_STATUS returns rns_only when no PQC session exists."""
        daemon = MockDaemon()
        daemon._pqc_service = None
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import PQCStatusRequest

        request = PQCStatusRequest(peer_hash="b" * 32)
        response = await handlers.handle_cmd_pqc_status(request)

        assert isinstance(response, ResultResponse)
        assert response.data["security_tier"] == "rns_only"
        assert response.data["session_state"] is None
        assert response.data["created_at"] is None
        assert response.data["last_rekeyed_at"] is None
        assert response.data["rekey_count"] is None

    @pytest.mark.asyncio
    async def test_pqc_status_returns_error_when_daemon_none(self):
        """CMD_PQC_STATUS should return error when daemon is None."""
        handlers = IPCHandlers(daemon=None)

        from styrened.ipc.messages import PQCStatusRequest

        request = PQCStatusRequest(peer_hash="a" * 32)
        response = await handlers.handle_cmd_pqc_status(request)

        assert isinstance(response, ErrorResponse)
        assert "Daemon not initialized" in response.message

    @pytest.mark.asyncio
    async def test_pqc_status_requires_peer_hash(self):
        """CMD_PQC_STATUS should require peer_hash."""
        daemon = MockDaemon()
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import PQCStatusRequest

        request = PQCStatusRequest(peer_hash="")
        response = await handlers.handle_cmd_pqc_status(request)

        assert isinstance(response, ErrorResponse)
        assert "peer_hash is required" in response.message

    @pytest.mark.asyncio
    async def test_pqc_status_service_returns_none_session(self):
        """CMD_PQC_STATUS returns rns_only when PQC service has no session for peer."""
        daemon = MockDaemon()
        mock_pqc_service = MagicMock()
        mock_pqc_service.get_session_status.return_value = None
        daemon._pqc_service = mock_pqc_service
        handlers = IPCHandlers(daemon=daemon)

        from styrened.ipc.messages import PQCStatusRequest

        request = PQCStatusRequest(peer_hash="c" * 32)
        response = await handlers.handle_cmd_pqc_status(request)

        assert isinstance(response, ResultResponse)
        assert response.data["security_tier"] == "rns_only"
        assert response.data["session_state"] is None


class TestAsyncioGetRunningLoop:
    """W22: handlers.py uses asyncio.get_running_loop() instead of deprecated get_event_loop()."""

    def test_handlers_source_uses_get_running_loop(self):
        """W22: handlers.py should use get_running_loop, not get_event_loop."""
        import inspect

        import styrened.ipc.handlers as handlers_mod

        source = inspect.getsource(handlers_mod)
        # Verify the fix: get_running_loop should be present
        assert "get_running_loop()" in source, (
            "handlers.py should use asyncio.get_running_loop()"
        )
        # Verify the deprecated call is NOT present
        assert "get_event_loop()" not in source, (
            "handlers.py should NOT use deprecated asyncio.get_event_loop()"
        )


class TestRPCActivityRedaction:
    """W18: RPC command names are redacted in activity feed events."""

    def test_dangerous_rpc_commands_set_contents(self):
        """DANGEROUS_RPC_COMMANDS includes EXEC, REBOOT, CONFIG_UPDATE, SELF_UPDATE."""
        from styrened.models.styrene_wire import StyreneMessageType
        from styrened.rpc.server import DANGEROUS_RPC_COMMANDS

        assert StyreneMessageType.EXEC in DANGEROUS_RPC_COMMANDS
        assert StyreneMessageType.REBOOT in DANGEROUS_RPC_COMMANDS
        assert StyreneMessageType.CONFIG_UPDATE in DANGEROUS_RPC_COMMANDS
        assert StyreneMessageType.SELF_UPDATE in DANGEROUS_RPC_COMMANDS

    def test_safe_rpc_commands_not_in_dangerous_set(self):
        """STATUS_REQUEST and PING are NOT in DANGEROUS_RPC_COMMANDS."""
        from styrened.models.styrene_wire import StyreneMessageType
        from styrened.rpc.server import DANGEROUS_RPC_COMMANDS

        assert StyreneMessageType.PING not in DANGEROUS_RPC_COMMANDS
        assert StyreneMessageType.STATUS_REQUEST not in DANGEROUS_RPC_COMMANDS

    @pytest.mark.asyncio
    async def test_activity_event_uses_redacted_category_for_dangerous(self):
        """W18: EXEC command emits 'rpc_privileged' category, not command name."""
        from styrened.models.styrene_wire import (
            NO_CORRELATION,
            StyreneEnvelope,
            StyreneMessageType,
        )
        from styrened.rpc.server import RPCServer

        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()

        from styrened.models.rbac import RBACPolicy, Role, RosterEntry
        policy = RBACPolicy(
            roster={"a" * 32: RosterEntry(identity_hash="a" * 32, role=Role.ADMIN)},
        )
        server = RPCServer(
            mock_protocol,
            rbac_policy=policy,
        )
        server._running = True

        # Mock daemon with activity event tracker
        activity_events = []
        mock_daemon = MagicMock()
        mock_daemon._emit_activity_event = lambda evt, peer_hash="", metadata=None: (
            activity_events.append((evt, peer_hash, metadata or {}))
        )
        server._daemon = mock_daemon

        # Create a fake EXEC envelope
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.EXEC,
            payload=b"",
            request_id=NO_CORRELATION,
        )

        # Build a mock LXMF message
        mock_message = MagicMock()
        mock_message.source_hash = "a" * 32

        # Override the handler to avoid actual EXEC execution
        server._handlers[StyreneMessageType.EXEC] = MagicMock()

        await server._protocol_handler(mock_message, envelope)

        # Verify activity was emitted with redacted category
        assert len(activity_events) == 1
        event_type, peer_hash, metadata = activity_events[0]
        assert event_type == "rpc_received"
        assert metadata["category"] == "rpc_privileged"
        # Ensure raw command name is NOT leaked
        assert "command" not in metadata

    @pytest.mark.asyncio
    async def test_activity_event_uses_rpc_query_for_safe_commands(self):
        """W18: STATUS_REQUEST emits 'rpc_query' category."""
        from styrened.models.styrene_wire import (
            NO_CORRELATION,
            StyreneEnvelope,
            StyreneMessageType,
        )
        from styrened.rpc.server import RPCServer

        mock_protocol = MagicMock()
        mock_protocol.register_handler = MagicMock()

        server = RPCServer(mock_protocol)
        server._running = True

        activity_events = []
        mock_daemon = MagicMock()
        mock_daemon._emit_activity_event = lambda evt, peer_hash="", metadata=None: (
            activity_events.append((evt, peer_hash, metadata or {}))
        )
        server._daemon = mock_daemon

        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.STATUS_REQUEST,
            payload=b"",
            request_id=NO_CORRELATION,
        )

        mock_message = MagicMock()
        mock_message.source_hash = "b" * 32

        server._handlers[StyreneMessageType.STATUS_REQUEST] = MagicMock()

        await server._protocol_handler(mock_message, envelope)

        assert len(activity_events) == 1
        _, _, metadata = activity_events[0]
        assert metadata["category"] == "rpc_query"
        assert "command" not in metadata
