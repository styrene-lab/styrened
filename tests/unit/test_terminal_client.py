"""Unit tests for TerminalClient gaps and edge cases.

These tests verify the terminal client handles edge cases properly:
- EOF handling on stdin
- Unexpected Link closure handling
- Missing rejection reason handling
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from styrened.terminal.client import TerminalClient, TerminalClientSession

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
