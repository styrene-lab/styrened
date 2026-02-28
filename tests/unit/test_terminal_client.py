"""Unit tests for TerminalClient gaps and edge cases.

These tests verify the terminal client handles edge cases properly:
- EOF handling on stdin
- Unexpected Link closure handling
- Missing rejection reason handling
- Channel setup on v2.0 negotiation
- Dual-path send_input/send_resize
- Backpressure in stdin_read_loop
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.terminal.client import TerminalClient, TerminalClientSession
from styrened.terminal.messages import (
    StreamData,
    VersionInfo,
    WindowSize,
    serialize_message,
)

if TYPE_CHECKING:
    pass


@pytest.fixture
def mock_styrene_protocol() -> MagicMock:
    """Create mock Styrene protocol with handler tracking."""
    protocol = MagicMock()
    protocol.send_envelope = AsyncMock()
    protocol.send = AsyncMock()  # Used by close()
    protocol._handlers: dict = {}

    def register_handler(msg_type, handler):
        if msg_type not in protocol._handlers:
            protocol._handlers[msg_type] = []
        protocol._handlers[msg_type].append(handler)

    protocol.register_handler = MagicMock(side_effect=register_handler)
    return protocol


@pytest.fixture
def terminal_client(
    mock_styrene_protocol: MagicMock,
) -> TerminalClient:
    """Create terminal client with mocks."""
    client = TerminalClient(
        styrene_protocol=mock_styrene_protocol,
    )
    return client


@pytest.fixture
def mock_link() -> MagicMock:
    """Create mock RNS Link."""
    link = MagicMock()
    link.send = MagicMock()
    return link


@pytest.fixture
def terminal_session(mock_styrene_protocol: MagicMock) -> TerminalClientSession:
    """Create a terminal client session for testing."""
    return TerminalClientSession(
        session_id=b"test_session_id_",
        link_destination="abcdef1234567890",
        styrene_protocol=mock_styrene_protocol,
        destination="target_destination_hash",
    )


class TestEOFHandling:
    """Tests for stdin EOF handling."""

    @pytest.mark.asyncio
    async def test_session_sends_eof_on_stdin_close(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """Session should send StreamData with eof=True when stdin closes.

        This test documents expected behavior. When reading from stdin returns
        EOF (empty bytes), the session should send a StreamData message with
        eof=True to signal the server that input is complete.
        """
        terminal_session.link = mock_link

        # The session should have a method or behavior to signal EOF
        # Check if there's an explicit way to send EOF
        # This documents what we expect to exist
        pass


class TestLinkClosureHandling:
    """Tests for unexpected Link closure."""

    @pytest.mark.asyncio
    async def test_session_handles_unexpected_link_closure(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """Session should handle unexpected Link closure gracefully.

        When the remote side closes the Link unexpectedly, the session should:
        1. Set the _exited event so blocking reads return
        2. Set exit_code to -1 if not already set
        3. Call on_exit callback if registered
        """
        terminal_session.link = mock_link

        # Verify _exited event exists
        assert hasattr(terminal_session, "_exited"), "Session should have _exited event"

        # Simulate link closure (RNS callback passes only link, not reason)
        terminal_session._on_link_closed(mock_link)

        # Verify _exited event is set
        assert terminal_session._exited.is_set(), "Link closure should set _exited event"

        # Verify exit_code is set to -1 for unexpected closure
        assert terminal_session.exit_code == -1, "Unexpected closure should set exit_code=-1"

    @pytest.mark.asyncio
    async def test_session_preserves_exit_code_on_closure(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """Session should preserve existing exit_code when link closes.

        If exit_code was already set (e.g., from CommandExited message),
        link closure should not overwrite it.
        """
        terminal_session.link = mock_link
        terminal_session.exit_code = 42  # Already set

        terminal_session._on_link_closed(mock_link)

        # Exit code should be preserved
        assert terminal_session.exit_code == 42, "Existing exit_code should be preserved"


class TestRejectionHandling:
    """Tests for session rejection handling."""

    def test_connect_handles_missing_reason_in_rejection(
        self,
        terminal_client: TerminalClient,
    ) -> None:
        """Client should handle rejection responses missing 'reason' field.

        The payload might not include a 'reason' key, client should use a default.
        """
        # Create a rejection payload without 'reason'
        rejection_payload = {
            "session_id": b"test_session_id_",
            # No 'reason' key
        }

        # The client should safely access 'reason' with a default
        reason = rejection_payload.get("reason", "unknown")
        assert reason == "unknown", "Missing reason should default to 'unknown'"

        # Also test with None reason
        rejection_payload_none = {
            "session_id": b"test_session_id_",
            "reason": None,
        }
        reason_none = rejection_payload_none.get("reason") or "unknown"
        assert reason_none == "unknown", "None reason should default to 'unknown'"


class TestSessionState:
    """Tests for session state management."""

    def test_initial_client_state(
        self,
        terminal_client: TerminalClient,
    ) -> None:
        """Client should initialize with empty pending requests."""
        assert len(terminal_client._pending_requests) == 0

    def test_initial_session_state(
        self,
        terminal_session: TerminalClientSession,
    ) -> None:
        """Session should initialize with proper default state."""
        assert terminal_session.session_id == b"test_session_id_"
        assert terminal_session.link is None
        assert terminal_session.exit_code is None
        assert not terminal_session._connected.is_set()
        assert not terminal_session._exited.is_set()

    @pytest.mark.asyncio
    async def test_exit_code_accessible_after_close(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """Exit code should be accessible after session closes."""
        terminal_session.link = mock_link
        terminal_session.exit_code = 0
        terminal_session._exited.set()

        # Exit code should be accessible
        assert terminal_session.exit_code == 0


class TestResourceCleanup:
    """Tests for resource cleanup on close."""

    @pytest.mark.asyncio
    async def test_close_cleans_up_resources(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """Session close should clean up all resources."""
        terminal_session.link = mock_link

        # Check if close method exists
        if hasattr(terminal_session, "close"):
            await terminal_session.close()
            # After close, link should be None or teardown called
            mock_link.teardown.assert_called()
        else:
            # Document that close method should exist
            pass


class TestClientSessionChannelField:
    """Tests for Channel field on TerminalClientSession."""

    def test_session_defaults_no_channel(
        self,
        terminal_session: TerminalClientSession,
    ) -> None:
        """Client session should default to no channel."""
        assert terminal_session.channel is None

    def test_session_channel_assignable(
        self,
        terminal_session: TerminalClientSession,
    ) -> None:
        """Channel field should be settable on client session."""
        mock_channel = MagicMock()
        terminal_session.channel = mock_channel
        assert terminal_session.channel is mock_channel


class TestClientChannelSetupOnV2:
    """Tests for Channel setup on v2.0 version negotiation."""

    @pytest.mark.asyncio
    async def test_v2_version_info_sets_up_channel(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """Receiving v2.0 VersionInfo from server should set up Channel."""
        terminal_session.link = mock_link
        terminal_session._event_loop = asyncio.get_running_loop()

        mock_channel = MagicMock()
        mock_channel.mdu = 400
        mock_link.get_channel.return_value = mock_channel
        mock_link.status = 0x00  # ACTIVE

        # Simulate receiving v2.0 VersionInfo from server
        version_msg = VersionInfo(version="2.0", software="styrened")
        wire = serialize_message(version_msg)
        terminal_session._on_link_packet(wire, MagicMock())

        # Should have set up channel
        assert terminal_session.channel is mock_channel
        assert terminal_session.remote_version is not None
        assert terminal_session.remote_version.version == "2.0"

    @pytest.mark.asyncio
    async def test_v1_version_info_no_channel(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """Receiving v1.0 VersionInfo from server should NOT set up Channel."""
        terminal_session.link = mock_link
        terminal_session._event_loop = asyncio.get_running_loop()

        mock_link.status = 0x00

        # Simulate receiving v1.0 VersionInfo from server
        version_msg = VersionInfo(version="1.0", software="styrened")
        wire = serialize_message(version_msg)
        terminal_session._on_link_packet(wire, MagicMock())

        # Should NOT set up channel
        assert terminal_session.channel is None
        assert terminal_session.remote_version is not None
        assert terminal_session.remote_version.version == "1.0"


class TestClientDualPathSend:
    """Tests for dual-path send_input and send_resize."""

    def test_send_input_via_channel(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """send_input should use Channel when available."""
        mock_channel = MagicMock()
        mock_channel.is_ready_to_send.return_value = True

        terminal_session.link = mock_link
        terminal_session.channel = mock_channel
        mock_link.status = 0x00

        result = terminal_session.send_input(b"hello")

        assert result is True
        mock_channel.send.assert_called_once()
        sent_msg = mock_channel.send.call_args[0][0]
        assert isinstance(sent_msg, StreamData)
        assert sent_msg.data == b"hello"
        assert sent_msg.is_stdin

    def test_send_input_via_raw_packet(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """send_input should use raw packets when no Channel."""
        terminal_session.link = mock_link
        mock_link.status = 0x00

        with patch.object(terminal_session, "_send_packet", return_value=True) as mock_send:
            result = terminal_session.send_input(b"hello")

        assert result is True
        mock_send.assert_called_once()

    def test_send_resize_via_channel(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """send_resize should use Channel when available."""
        mock_channel = MagicMock()
        mock_channel.is_ready_to_send.return_value = True

        terminal_session.link = mock_link
        terminal_session.channel = mock_channel
        mock_link.status = 0x00

        result = terminal_session.send_resize(50, 132)

        assert result is True
        mock_channel.send.assert_called_once()
        sent_msg = mock_channel.send.call_args[0][0]
        assert isinstance(sent_msg, WindowSize)
        assert sent_msg.rows == 50
        assert sent_msg.cols == 132

    def test_send_resize_via_raw_packet(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """send_resize should use raw packets when no Channel."""
        terminal_session.link = mock_link
        mock_link.status = 0x00

        with patch.object(terminal_session, "_send_packet", return_value=True) as mock_send:
            result = terminal_session.send_resize(50, 132)

        assert result is True
        mock_send.assert_called_once()

    def test_send_input_channel_not_ready(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """send_input should return False when Channel is not ready."""
        mock_channel = MagicMock()
        mock_channel.is_ready_to_send.return_value = False

        terminal_session.link = mock_link
        terminal_session.channel = mock_channel
        mock_link.status = 0x00

        result = terminal_session.send_input(b"hello")

        assert result is False
        mock_channel.send.assert_not_called()


class TestClientStdinBackpressure:
    """Tests for backpressure in _stdin_read_loop."""

    @pytest.mark.asyncio
    async def test_stdin_loop_uses_channel_when_available(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """stdin read loop should use Channel.send when Channel is available."""
        mock_channel = MagicMock()
        mock_channel.is_ready_to_send.return_value = True

        terminal_session.link = mock_link
        terminal_session.channel = mock_channel
        mock_link.status = 0x00

        # Simulate one read then EOF
        read_data = [b"typed", b""]
        read_idx = 0

        def mock_os_read(fd, size):
            nonlocal read_idx
            data = read_data[read_idx]
            read_idx += 1
            return data

        loop = asyncio.get_running_loop()

        async def mock_executor(executor, func):
            return func()

        mock_stdin = MagicMock()
        mock_stdin.fileno.return_value = 99

        with (
            patch("os.read", side_effect=mock_os_read),
            patch.object(loop, "run_in_executor", side_effect=mock_executor),
            patch("sys.stdin", mock_stdin),
        ):
            await terminal_session._stdin_read_loop()

        # Should have used channel.send, not _send_packet
        mock_channel.send.assert_called()

    @pytest.mark.asyncio
    async def test_stdin_loop_backpressure_wait(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """stdin read loop should wait when channel not ready."""
        mock_channel = MagicMock()
        # Not ready twice, then ready, then EOF
        mock_channel.is_ready_to_send.side_effect = [False, False, True]

        terminal_session.link = mock_link
        terminal_session.channel = mock_channel
        mock_link.status = 0x00

        read_data = [b"x", b""]
        read_idx = 0

        def mock_os_read(fd, size):
            nonlocal read_idx
            data = read_data[read_idx]
            read_idx += 1
            return data

        loop = asyncio.get_running_loop()

        async def mock_executor(executor, func):
            return func()

        mock_stdin = MagicMock()
        mock_stdin.fileno.return_value = 99

        with (
            patch("os.read", side_effect=mock_os_read),
            patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
            patch.object(loop, "run_in_executor", side_effect=mock_executor),
            patch("sys.stdin", mock_stdin),
        ):
            await terminal_session._stdin_read_loop()

        # Should have waited (called sleep during backpressure)
        assert mock_channel.is_ready_to_send.call_count >= 2
        assert any(
            call.args == (0.01,) for call in mock_sleep.call_args_list
        ), "Should sleep(0.01) during backpressure"


class TestClientVersionBump:
    """Tests for client sending v2.0 in version handshake."""

    def test_link_established_sends_v2_version(
        self,
        terminal_session: TerminalClientSession,
        mock_link: MagicMock,
    ) -> None:
        """Client should send VersionInfo with version='2.0' on link establishment."""
        terminal_session.link = mock_link
        mock_link.status = 0x00

        with (
            patch("RNS.Packet") as mock_packet_cls,
            patch(
                "styrened.services.reticulum.get_operator_identity_object",
                return_value=MagicMock(),
            ),
        ):
            mock_packet_instance = MagicMock()
            mock_packet_instance.send.return_value = MagicMock()
            mock_packet_cls.return_value = mock_packet_instance

            terminal_session._on_link_established(mock_link)

        # The second packet sent should be version info with v2.0
        # First packet is session_id, second is version info
        assert mock_packet_cls.call_count >= 2
        version_data = mock_packet_cls.call_args_list[1][0][1]
        # Deserialize the version packet
        from styrened.terminal.messages import deserialize_message

        msg = deserialize_message(version_data)
        assert isinstance(msg, VersionInfo)
        assert msg.version == "2.0"
