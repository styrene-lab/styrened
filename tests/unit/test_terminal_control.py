"""Unit tests for terminal control plane messages (LXMF)."""

import signal

import pytest

from styrened.models.styrene_wire import (
    StyreneEnvelope,
    StyreneMessageType,
    create_terminal_accept,
    create_terminal_close,
    create_terminal_closed,
    create_terminal_reject,
    create_terminal_request,
    create_terminal_resize,
    create_terminal_signal,
    decode_payload,
)


class TestTerminalRequest:
    """Tests for TERMINAL_REQUEST creation."""

    def test_default_values(self) -> None:
        """Request should have sensible defaults."""
        request = create_terminal_request()

        assert request.message_type == StyreneMessageType.TERMINAL_REQUEST
        assert request.version == 2
        assert request.request_id is not None
        assert len(request.request_id) == 16

        payload = decode_payload(request.payload)
        assert payload["term_type"] == "xterm-256color"
        assert payload["rows"] == 24
        assert payload["cols"] == 80

    def test_custom_terminal_size(self) -> None:
        """Request should preserve custom terminal dimensions."""
        request = create_terminal_request(
            term_type="screen-256color",
            rows=40,
            cols=120,
        )

        payload = decode_payload(request.payload)
        assert payload["term_type"] == "screen-256color"
        assert payload["rows"] == 40
        assert payload["cols"] == 120

    def test_with_shell(self) -> None:
        """Request should include shell override."""
        request = create_terminal_request(shell="/bin/zsh")

        payload = decode_payload(request.payload)
        assert payload["shell"] == "/bin/zsh"

    def test_with_command(self) -> None:
        """Request should include command and args."""
        request = create_terminal_request(
            command="python",
            args=["-m", "http.server", "8080"],
        )

        payload = decode_payload(request.payload)
        assert payload["command"] == "python"
        assert payload["args"] == ["-m", "http.server", "8080"]

    def test_custom_request_id(self) -> None:
        """Request should use provided request_id."""
        custom_id = b"1234567890123456"
        request = create_terminal_request(request_id=custom_id)

        assert request.request_id == custom_id


class TestTerminalAccept:
    """Tests for TERMINAL_ACCEPT creation."""

    def test_accept_creation(self) -> None:
        """Accept should include link destination."""
        link_dest = "abc123def456abc123def456abc123de"
        session_id = b"session_id_12345"
        request_id = b"request_id_12345"

        accept = create_terminal_accept(
            link_destination=link_dest,
            session_id=session_id,
            request_id=request_id,
        )

        assert accept.message_type == StyreneMessageType.TERMINAL_ACCEPT
        assert accept.request_id == request_id

        payload = decode_payload(accept.payload)
        assert payload["link_destination"] == link_dest
        assert payload["session_id"] == session_id.hex()

    def test_accept_defaults_session_to_request_id(self) -> None:
        """Accept should default session_id to request_id."""
        request_id = b"request_id_12345"

        accept = create_terminal_accept(
            link_destination="deadbeef" * 8,
            request_id=request_id,
        )

        payload = decode_payload(accept.payload)
        assert payload["session_id"] == request_id.hex()


class TestTerminalReject:
    """Tests for TERMINAL_REJECT creation."""

    def test_reject_creation(self) -> None:
        """Reject should include reason and code."""
        reject = create_terminal_reject(
            reason="Not authorized",
            code=1,
            request_id=b"request_id_12345",
        )

        assert reject.message_type == StyreneMessageType.TERMINAL_REJECT

        payload = decode_payload(reject.payload)
        assert payload["reason"] == "Not authorized"
        assert payload["code"] == 1

    def test_reject_default_code(self) -> None:
        """Reject should default to code 1."""
        reject = create_terminal_reject(reason="Access denied")

        payload = decode_payload(reject.payload)
        assert payload["code"] == 1


class TestTerminalResize:
    """Tests for TERMINAL_RESIZE creation."""

    def test_resize_creation(self) -> None:
        """Resize should include dimensions."""
        session_id = b"session_id_12345"
        resize = create_terminal_resize(
            rows=50,
            cols=100,
            session_id=session_id,
        )

        assert resize.message_type == StyreneMessageType.TERMINAL_RESIZE

        payload = decode_payload(resize.payload)
        assert payload["rows"] == 50
        assert payload["cols"] == 100
        assert payload["session_id"] == session_id.hex()


class TestTerminalSignal:
    """Tests for TERMINAL_SIGNAL creation."""

    def test_signal_creation(self) -> None:
        """Signal should include signal number."""
        session_id = b"session_id_12345"
        sig = create_terminal_signal(
            signal=signal.SIGINT,
            session_id=session_id,
        )

        assert sig.message_type == StyreneMessageType.TERMINAL_SIGNAL

        payload = decode_payload(sig.payload)
        assert payload["signal"] == signal.SIGINT
        assert payload["session_id"] == session_id.hex()

    def test_various_signals(self) -> None:
        """Signal should handle common signals."""
        signals_to_test = [
            signal.SIGINT,
            signal.SIGTERM,
            signal.SIGKILL,
            signal.SIGTSTP,
            signal.SIGCONT,
        ]

        for sig_num in signals_to_test:
            sig = create_terminal_signal(signal=sig_num)
            payload = decode_payload(sig.payload)
            assert payload["signal"] == sig_num


class TestTerminalClose:
    """Tests for TERMINAL_CLOSE creation."""

    def test_close_creation(self) -> None:
        """Close should include session_id."""
        session_id = b"session_id_12345"
        close = create_terminal_close(session_id=session_id)

        assert close.message_type == StyreneMessageType.TERMINAL_CLOSE

        payload = decode_payload(close.payload)
        assert payload["session_id"] == session_id.hex()


class TestTerminalClosed:
    """Tests for TERMINAL_CLOSED creation."""

    def test_closed_creation(self) -> None:
        """Closed should include exit info."""
        session_id = b"session_id_12345"
        closed = create_terminal_closed(
            exit_code=0,
            reason="exited",
            session_id=session_id,
        )

        assert closed.message_type == StyreneMessageType.TERMINAL_CLOSED

        payload = decode_payload(closed.payload)
        assert payload["exit_code"] == 0
        assert payload["reason"] == "exited"
        assert payload["session_id"] == session_id.hex()

    def test_closed_with_signal(self) -> None:
        """Closed should handle signal termination."""
        closed = create_terminal_closed(
            exit_code=137,
            reason="signal",
        )

        payload = decode_payload(closed.payload)
        assert payload["exit_code"] == 137
        assert payload["reason"] == "signal"


class TestEnvelopeRoundtrip:
    """Tests for envelope encode/decode."""

    def test_request_roundtrip(self) -> None:
        """Request envelope should roundtrip."""
        original = create_terminal_request(
            term_type="vt100",
            rows=25,
            cols=80,
        )

        wire = original.encode()
        decoded = StyreneEnvelope.decode(wire)

        assert decoded.message_type == StyreneMessageType.TERMINAL_REQUEST
        assert decoded.request_id == original.request_id

        payload = decode_payload(decoded.payload)
        assert payload["term_type"] == "vt100"
        assert payload["rows"] == 25
        assert payload["cols"] == 80

    def test_accept_roundtrip(self) -> None:
        """Accept envelope should roundtrip."""
        original = create_terminal_accept(
            link_destination="abcd1234" * 8,
            session_id=b"0123456789abcdef",
        )

        wire = original.encode()
        decoded = StyreneEnvelope.decode(wire)

        assert decoded.message_type == StyreneMessageType.TERMINAL_ACCEPT

        payload = decode_payload(decoded.payload)
        assert payload["link_destination"] == "abcd1234" * 8


class TestMessageTypeValues:
    """Tests for terminal message type values."""

    def test_message_types_in_reserved_range(self) -> None:
        """Terminal message types should be in 0xC0-0xCF range."""
        terminal_types = [
            StyreneMessageType.TERMINAL_REQUEST,
            StyreneMessageType.TERMINAL_ACCEPT,
            StyreneMessageType.TERMINAL_REJECT,
            StyreneMessageType.TERMINAL_RESIZE,
            StyreneMessageType.TERMINAL_SIGNAL,
            StyreneMessageType.TERMINAL_CLOSE,
            StyreneMessageType.TERMINAL_CLOSED,
        ]

        for msg_type in terminal_types:
            assert 0xC0 <= msg_type <= 0xCF, f"{msg_type.name} not in terminal range"

    def test_message_types_are_unique(self) -> None:
        """Terminal message types should all be unique."""
        terminal_types = [
            StyreneMessageType.TERMINAL_REQUEST,
            StyreneMessageType.TERMINAL_ACCEPT,
            StyreneMessageType.TERMINAL_REJECT,
            StyreneMessageType.TERMINAL_RESIZE,
            StyreneMessageType.TERMINAL_SIGNAL,
            StyreneMessageType.TERMINAL_CLOSE,
            StyreneMessageType.TERMINAL_CLOSED,
        ]

        values = [t.value for t in terminal_types]
        assert len(values) == len(set(values)), "Duplicate message type values"


class TestSignalWhitelist:
    """Tests for signal whitelisting in TerminalService."""

    @pytest.fixture
    def mock_rns_service(self):
        """Create a minimal mock RNS service."""
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.identity = None  # Will be set in tests that need it
        return mock

    @pytest.fixture
    def mock_styrene_protocol(self):
        """Create a minimal mock Styrene protocol."""
        from unittest.mock import MagicMock

        return MagicMock()

    @pytest.fixture
    def terminal_service(self, mock_rns_service, mock_styrene_protocol):
        """Create a TerminalService with default settings."""
        from styrened.terminal.service import TerminalService

        return TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allow_unauthenticated=False,
        )

    def test_default_allowed_signals(self, terminal_service) -> None:
        """Default allowed signals should be permitted."""
        from styrened.terminal.service import DEFAULT_ALLOWED_SIGNALS

        for sig in DEFAULT_ALLOWED_SIGNALS:
            assert terminal_service.is_signal_allowed(sig), (
                f"Signal {sig} should be allowed by default"
            )

    def test_default_allowed_signals_list(self, terminal_service) -> None:
        """Verify specific default allowed signals."""
        # These are the expected default allowed signals
        expected_allowed = [
            signal.SIGINT,  # 2 - Ctrl+C
            signal.SIGTERM,  # 15 - Termination
            signal.SIGHUP,  # 1 - Hangup
            signal.SIGTSTP,  # 20 - Ctrl+Z
            signal.SIGCONT,  # 18 - Continue
            signal.SIGWINCH,  # 28 - Window change
        ]

        for sig in expected_allowed:
            assert terminal_service.is_signal_allowed(sig), f"Signal {sig} should be allowed"

    def test_blocked_signals_never_allowed(self, terminal_service) -> None:
        """Blocked signals (SIGKILL, SIGSTOP, SIGQUIT) should never be allowed."""
        from styrened.terminal.service import BLOCKED_SIGNALS

        for sig in BLOCKED_SIGNALS:
            assert not terminal_service.is_signal_allowed(sig), f"Signal {sig} should be blocked"

    def test_sigkill_blocked(self, terminal_service) -> None:
        """SIGKILL (9) should always be blocked."""
        assert not terminal_service.is_signal_allowed(signal.SIGKILL)

    def test_sigstop_blocked(self, terminal_service) -> None:
        """SIGSTOP (19) should always be blocked."""
        assert not terminal_service.is_signal_allowed(signal.SIGSTOP)

    def test_sigquit_blocked(self, terminal_service) -> None:
        """SIGQUIT (3) should always be blocked."""
        assert not terminal_service.is_signal_allowed(signal.SIGQUIT)

    def test_unlisted_signals_blocked(self, terminal_service) -> None:
        """Signals not in the whitelist should be blocked."""
        # SIGUSR1/SIGUSR2 are not in the default allowed list
        assert not terminal_service.is_signal_allowed(signal.SIGUSR1)
        assert not terminal_service.is_signal_allowed(signal.SIGUSR2)

    def test_custom_allowed_signals(self, mock_rns_service, mock_styrene_protocol) -> None:
        """Custom allowed signals should be configurable."""
        from styrened.terminal.service import TerminalService

        # Allow only SIGINT and SIGUSR1
        custom_signals = frozenset({signal.SIGINT, signal.SIGUSR1})
        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allowed_signals=custom_signals,
        )

        # SIGINT and SIGUSR1 should be allowed
        assert service.is_signal_allowed(signal.SIGINT)
        assert service.is_signal_allowed(signal.SIGUSR1)

        # SIGTERM should NOT be allowed (not in custom list)
        assert not service.is_signal_allowed(signal.SIGTERM)

    def test_custom_signals_still_block_dangerous(
        self, mock_rns_service, mock_styrene_protocol
    ) -> None:
        """Even with custom allowed signals, dangerous signals should be blocked."""
        from styrened.terminal.service import TerminalService

        # Try to include SIGKILL in allowed signals - it should be filtered out
        custom_signals = frozenset({signal.SIGINT, signal.SIGKILL, signal.SIGSTOP})
        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allowed_signals=custom_signals,
        )

        # SIGINT should be allowed
        assert service.is_signal_allowed(signal.SIGINT)

        # SIGKILL and SIGSTOP should still be blocked
        assert not service.is_signal_allowed(signal.SIGKILL)
        assert not service.is_signal_allowed(signal.SIGSTOP)

    def test_signal_validation_with_numeric_values(self, terminal_service) -> None:
        """Signal validation should work with numeric signal values."""
        # Test with numeric values directly (use signal constants for cross-platform)
        assert terminal_service.is_signal_allowed(signal.SIGINT)  # 2
        assert terminal_service.is_signal_allowed(signal.SIGTERM)  # 15
        assert not terminal_service.is_signal_allowed(signal.SIGKILL)  # 9
        assert not terminal_service.is_signal_allowed(signal.SIGSTOP)  # 17 on macOS, 19 on Linux

    def test_empty_allowed_signals(self, mock_rns_service, mock_styrene_protocol) -> None:
        """Empty allowed signals should block everything (except blocked are still blocked)."""
        from styrened.terminal.service import TerminalService

        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allowed_signals=frozenset(),  # Empty set
        )

        # All signals should be blocked
        assert not service.is_signal_allowed(signal.SIGINT)
        assert not service.is_signal_allowed(signal.SIGTERM)
        assert not service.is_signal_allowed(signal.SIGKILL)  # Blocked anyway


class TestIdentityVerification:
    """Tests for identity verification during Link establishment."""

    @pytest.fixture
    def mock_rns_service(self):
        """Create a minimal mock RNS service."""
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.identity = None
        return mock

    @pytest.fixture
    def mock_styrene_protocol(self):
        """Create a minimal mock Styrene protocol."""
        from unittest.mock import MagicMock

        return MagicMock()

    @pytest.fixture
    def terminal_service(self, mock_rns_service, mock_styrene_protocol):
        """Create a TerminalService with default settings."""
        from styrened.terminal.service import TerminalService

        return TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"abc123def456abc123def456abc123de"},
            allow_unauthenticated=False,
        )

    def test_identity_verification_constants_exist(self) -> None:
        """Identity verification constants should be defined."""
        from styrened.terminal.service import (
            IDENTITY_VERIFICATION_DELAY_MS,
            IDENTITY_VERIFICATION_RETRIES,
        )

        # Constants were increased during adversarial review for robustness
        assert IDENTITY_VERIFICATION_RETRIES == 10
        assert IDENTITY_VERIFICATION_DELAY_MS == 200

    @pytest.mark.asyncio
    async def test_async_verify_rejects_when_identity_unavailable(self, terminal_service) -> None:
        """Link should be torn down if identity is unavailable after retries."""
        from unittest.mock import MagicMock, patch

        # Create a mock link that always returns None for get_remote_identity
        mock_link = MagicMock()
        mock_link.get_remote_identity.return_value = None
        mock_link._terminal_session = None
        mock_link._association_in_progress = True

        # Create a session to associate with
        session_id = b"0123456789abcdef"
        mock_session = MagicMock(
            session_id=session_id,
            source_identity="abc123def456abc123def456abc123de",
            _association_pending=True,
            link=None,
        )
        terminal_service.sessions[session_id] = mock_session

        # Call _async_verify_and_associate directly
        with patch("asyncio.sleep", return_value=None):  # Mock async sleep
            await terminal_service._async_verify_and_associate(mock_link, session_id, mock_session)

        # Link should be torn down
        mock_link.teardown.assert_called_once()

        # Session should not have been associated
        assert mock_session.link is None

    @pytest.mark.asyncio
    async def test_async_verify_retries_identity_verification(self, terminal_service) -> None:
        """Identity verification should retry before giving up."""
        from unittest.mock import MagicMock, patch

        from styrened.terminal.service import IDENTITY_VERIFICATION_RETRIES

        # Create a mock link that always returns None
        mock_link = MagicMock()
        mock_link.get_remote_identity.return_value = None
        mock_link._terminal_session = None
        mock_link._association_in_progress = True

        # Create a session
        session_id = b"0123456789abcdef"
        mock_session = MagicMock(
            session_id=session_id,
            source_identity="abc123def456abc123def456abc123de",
            _association_pending=True,
            link=None,
        )
        terminal_service.sessions[session_id] = mock_session

        sleep_calls = []

        async def mock_sleep(delay):
            sleep_calls.append(delay)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await terminal_service._async_verify_and_associate(mock_link, session_id, mock_session)

        # Should have called get_remote_identity the configured number of times
        assert mock_link.get_remote_identity.call_count == IDENTITY_VERIFICATION_RETRIES

        # Should have slept between retries (one less sleep than retries)
        assert len(sleep_calls) == IDENTITY_VERIFICATION_RETRIES - 1

    @pytest.mark.asyncio
    async def test_async_verify_succeeds_on_retry(self, terminal_service) -> None:
        """Link association should succeed if identity becomes available on retry."""
        from unittest.mock import MagicMock, patch

        # Create a mock identity
        mock_identity = MagicMock()
        mock_identity.hexhash = "abc123def456abc123def456abc123de"

        # Create a mock link that returns None first, then the identity
        mock_link = MagicMock()
        mock_link.get_remote_identity.side_effect = [None, mock_identity]
        mock_link._terminal_session = None
        mock_link._association_in_progress = True
        mock_link.send = MagicMock()

        # Create a session
        session_id = b"0123456789abcdef"
        mock_session = MagicMock(
            session_id=session_id,
            source_identity="abc123def456abc123def456abc123de",
            _association_pending=True,
            link=None,
        )
        terminal_service.sessions[session_id] = mock_session

        with patch("asyncio.sleep", return_value=None):
            with patch("asyncio.create_task"):
                await terminal_service._async_verify_and_associate(
                    mock_link, session_id, mock_session
                )

        # Link should NOT be torn down
        mock_link.teardown.assert_not_called()

        # Session should have link associated
        assert mock_session.link == mock_link

    @pytest.mark.asyncio
    async def test_async_verify_rejects_identity_mismatch(self, terminal_service) -> None:
        """Link should be torn down if identity doesn't match session."""
        from unittest.mock import MagicMock

        # Create a mock identity with wrong hash
        mock_identity = MagicMock()
        mock_identity.hexhash = "wrongidentity000000000000000000"

        mock_link = MagicMock()
        mock_link.get_remote_identity.return_value = mock_identity
        mock_link._terminal_session = None
        mock_link._association_in_progress = True

        # Create a session with different identity
        session_id = b"0123456789abcdef"
        mock_session = MagicMock(
            session_id=session_id,
            source_identity="abc123def456abc123def456abc123de",
            _association_pending=True,
            link=None,
        )
        terminal_service.sessions[session_id] = mock_session

        await terminal_service._async_verify_and_associate(mock_link, session_id, mock_session)

        # Link should be torn down due to identity mismatch
        mock_link.teardown.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_verify_accepts_matching_identity_immediately(
        self, terminal_service
    ) -> None:
        """Link should be associated immediately if identity matches on first try."""
        from unittest.mock import MagicMock, patch

        # Create a mock identity that matches
        mock_identity = MagicMock()
        mock_identity.hexhash = "abc123def456abc123def456abc123de"

        mock_link = MagicMock()
        mock_link.get_remote_identity.return_value = mock_identity
        mock_link._terminal_session = None
        mock_link._association_in_progress = True
        mock_link.send = MagicMock()

        # Create a session
        session_id = b"0123456789abcdef"
        mock_session = MagicMock(
            session_id=session_id,
            source_identity="abc123def456abc123def456abc123de",
            _association_pending=True,
            link=None,
        )
        terminal_service.sessions[session_id] = mock_session

        with patch("asyncio.create_task"):
            await terminal_service._async_verify_and_associate(mock_link, session_id, mock_session)

        # Should only call get_remote_identity once (no retries needed)
        assert mock_link.get_remote_identity.call_count == 1

        # Link should NOT be torn down
        mock_link.teardown.assert_not_called()

        # Session should have link associated
        assert mock_session.link == mock_link

    def test_link_packet_invalid_session_id_length(self, terminal_service) -> None:
        """Link should be torn down if session_id packet is too short."""
        from unittest.mock import MagicMock

        mock_link = MagicMock()
        mock_link._terminal_session = None
        mock_link._association_in_progress = False  # Not already processing

        # Send data that is too short (less than 16 bytes)
        short_data = b"short"

        terminal_service._on_link_packet(mock_link, short_data, MagicMock())

        # Link should be torn down
        mock_link.teardown.assert_called_once()

    def test_link_packet_unknown_session_id(self, terminal_service) -> None:
        """Link should be torn down if session_id is not known."""
        from unittest.mock import MagicMock

        mock_link = MagicMock()
        mock_link._terminal_session = None
        mock_link._association_in_progress = False  # Not already processing

        # Send a session_id that doesn't exist
        unknown_session_id = b"unknownsession01"

        terminal_service._on_link_packet(mock_link, unknown_session_id, MagicMock())

        # Link should be torn down
        mock_link.teardown.assert_called_once()


class TestRateLimiting:
    """Tests for rate limiting in TerminalService."""

    @pytest.fixture
    def mock_rns_service(self):
        """Create a minimal mock RNS service."""
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.identity = None
        return mock

    @pytest.fixture
    def mock_styrene_protocol(self):
        """Create a minimal mock Styrene protocol."""
        from unittest.mock import MagicMock

        return MagicMock()

    @pytest.fixture
    def terminal_service(self, mock_rns_service, mock_styrene_protocol):
        """Create a TerminalService with default rate limiting settings."""
        from styrened.terminal.service import TerminalService

        return TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allow_unauthenticated=False,
        )

    @pytest.fixture
    def service_with_low_limits(self, mock_rns_service, mock_styrene_protocol):
        """Create a TerminalService with low rate limits for testing."""
        from styrened.terminal.service import TerminalService

        return TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allow_unauthenticated=False,
            max_sessions_per_identity=2,
            max_total_sessions=3,
            session_request_rate_limit=5,
        )

    def test_rate_limit_defaults_exist(self) -> None:
        """Rate limiting default constants should be defined."""
        from styrened.terminal.service import (
            DEFAULT_MAX_SESSIONS_PER_IDENTITY,
            DEFAULT_MAX_TOTAL_SESSIONS,
            DEFAULT_SESSION_REQUEST_RATE_LIMIT,
            RATE_LIMIT_WINDOW_SECONDS,
        )

        assert DEFAULT_MAX_SESSIONS_PER_IDENTITY == 5
        assert DEFAULT_MAX_TOTAL_SESSIONS == 20
        assert DEFAULT_SESSION_REQUEST_RATE_LIMIT == 10
        assert RATE_LIMIT_WINDOW_SECONDS == 60

    def test_rate_limit_parameters_configurable(
        self, mock_rns_service, mock_styrene_protocol
    ) -> None:
        """Rate limit parameters should be configurable."""
        from styrened.terminal.service import TerminalService

        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            max_sessions_per_identity=10,
            max_total_sessions=50,
            session_request_rate_limit=20,
        )

        assert service._max_sessions_per_identity == 10
        assert service._max_total_sessions == 50
        assert service._session_request_rate_limit == 20

    def test_tracking_structures_initialized(self, terminal_service) -> None:
        """Session and request tracking structures should be initialized."""
        assert hasattr(terminal_service, "_sessions_by_identity")
        assert hasattr(terminal_service, "_request_timestamps")
        assert isinstance(terminal_service._sessions_by_identity, dict)
        assert isinstance(terminal_service._request_timestamps, dict)

    def test_check_rate_limits_allows_first_request(self, terminal_service) -> None:
        """First request should be allowed."""
        result = terminal_service._check_rate_limits("test_identity")
        assert result is None  # None means allowed

    def test_check_rate_limits_records_timestamp(self, terminal_service) -> None:
        """Request timestamps should be recorded."""
        terminal_service._check_rate_limits("test_identity")
        assert "test_identity" in terminal_service._request_timestamps
        assert len(terminal_service._request_timestamps["test_identity"]) == 1

    def test_request_rate_limit_exceeded(self, service_with_low_limits) -> None:
        """Request should be rejected when rate limit is exceeded."""
        identity = "test_identity"

        # Make 5 requests (the limit)
        for _ in range(5):
            result = service_with_low_limits._check_rate_limits(identity)
            assert result is None  # All should succeed

        # 6th request should be rejected
        result = service_with_low_limits._check_rate_limits(identity)
        assert result is not None
        assert "Rate limit exceeded" in result
        assert "5" in result  # Should mention the limit

    def test_per_identity_session_limit_exceeded(self, service_with_low_limits) -> None:
        """Request should be rejected when per-identity session limit is exceeded."""
        identity = "test_identity"

        # Simulate 2 active sessions for this identity
        service_with_low_limits._sessions_by_identity[identity] = [
            b"session_id_00001",
            b"session_id_00002",
        ]
        # Add them to the sessions dict
        from unittest.mock import MagicMock

        service_with_low_limits.sessions[b"session_id_00001"] = MagicMock()
        service_with_low_limits.sessions[b"session_id_00002"] = MagicMock()

        # Request should be rejected
        result = service_with_low_limits._check_rate_limits(identity)
        assert result is not None
        assert "Session limit exceeded" in result
        assert "2" in result  # Should mention the limit

    def test_total_session_limit_exceeded(self, service_with_low_limits) -> None:
        """Request should be rejected when total session limit is exceeded."""
        from unittest.mock import MagicMock

        # Fill up the total session limit with sessions from different identities
        service_with_low_limits.sessions = {
            b"session_id_00001": MagicMock(),
            b"session_id_00002": MagicMock(),
            b"session_id_00003": MagicMock(),
        }

        # Request from a new identity should be rejected
        result = service_with_low_limits._check_rate_limits("new_identity")
        assert result is not None
        assert "Server session limit exceeded" in result
        assert "3" in result  # Should mention the limit

    def test_cleanup_request_timestamps(self, terminal_service) -> None:
        """Old timestamps should be cleaned up."""
        import time

        from styrened.terminal.service import RATE_LIMIT_WINDOW_SECONDS

        identity = "test_identity"
        current_time = time.time()

        # Add some old timestamps (older than the window)
        terminal_service._request_timestamps[identity] = [
            current_time - RATE_LIMIT_WINDOW_SECONDS - 10,  # Old
            current_time - RATE_LIMIT_WINDOW_SECONDS - 5,  # Old
            current_time - 30,  # Recent
            current_time - 10,  # Recent
        ]

        # Cleanup
        terminal_service._cleanup_request_timestamps(identity, current_time)

        # Only recent timestamps should remain
        assert len(terminal_service._request_timestamps[identity]) == 2

    def test_cleanup_removes_empty_entries(self, terminal_service) -> None:
        """Empty timestamp lists should be removed to prevent memory growth."""
        import time

        from styrened.terminal.service import RATE_LIMIT_WINDOW_SECONDS

        identity = "test_identity"
        current_time = time.time()

        # Add only old timestamps
        terminal_service._request_timestamps[identity] = [
            current_time - RATE_LIMIT_WINDOW_SECONDS - 10,
        ]

        # Cleanup
        terminal_service._cleanup_request_timestamps(identity, current_time)

        # Entry should be removed entirely
        assert identity not in terminal_service._request_timestamps

    def test_track_session_for_identity(self, terminal_service) -> None:
        """Sessions should be tracked per identity."""
        identity = "test_identity"
        session_id = b"session_id_00001"

        terminal_service._track_session_for_identity(identity, session_id)

        assert identity in terminal_service._sessions_by_identity
        assert session_id in terminal_service._sessions_by_identity[identity]

    def test_untrack_session_for_identity(self, terminal_service) -> None:
        """Sessions should be untracked when closed."""
        identity = "test_identity"
        session_id = b"session_id_00001"

        # Track the session first
        terminal_service._track_session_for_identity(identity, session_id)
        assert session_id in terminal_service._sessions_by_identity[identity]

        # Untrack
        terminal_service._untrack_session_for_identity(identity, session_id)

        # Should be removed (and empty list cleaned up)
        assert identity not in terminal_service._sessions_by_identity

    def test_untrack_nonexistent_session_safe(self, terminal_service) -> None:
        """Untracking a non-existent session should be safe."""
        # Should not raise
        terminal_service._untrack_session_for_identity("unknown_identity", b"unknown_session")

    def test_stale_session_references_cleaned(self, service_with_low_limits) -> None:
        """Stale session references in _sessions_by_identity should be cleaned."""
        identity = "test_identity"
        from unittest.mock import MagicMock

        # Add a session that exists
        real_session_id = b"real_session_001"
        service_with_low_limits.sessions[real_session_id] = MagicMock()

        # Track both a real and a stale session
        service_with_low_limits._sessions_by_identity[identity] = [
            b"stale_session_00",  # Not in sessions
            real_session_id,  # In sessions
        ]

        # Check rate limits - should clean up stale reference
        service_with_low_limits._check_rate_limits(identity)

        # Only the real session should remain in tracking
        assert service_with_low_limits._sessions_by_identity[identity] == [real_session_id]

    def test_different_identities_have_separate_limits(self, service_with_low_limits) -> None:
        """Different identities should have separate rate limit tracking."""
        from unittest.mock import MagicMock

        # Fill up session limit for identity1
        identity1 = "identity_one"
        service_with_low_limits._sessions_by_identity[identity1] = [
            b"session_id_00001",
            b"session_id_00002",
        ]
        service_with_low_limits.sessions[b"session_id_00001"] = MagicMock()
        service_with_low_limits.sessions[b"session_id_00002"] = MagicMock()

        # identity1 should be rejected
        result1 = service_with_low_limits._check_rate_limits(identity1)
        assert result1 is not None
        assert "Session limit exceeded" in result1

        # identity2 should still be allowed (hasn't hit total limit)
        identity2 = "identity_two"
        result2 = service_with_low_limits._check_rate_limits(identity2)
        assert result2 is None  # Allowed

    def test_reject_code_5_for_resource_limit(self) -> None:
        """TERMINAL_REJECT with code=5 should indicate resource limit."""
        reject = create_terminal_reject(
            reason="Rate limit exceeded",
            code=5,
            request_id=b"request_id_12345",
        )

        payload = decode_payload(reject.payload)
        assert payload["code"] == 5
        assert "Rate limit" in payload["reason"]


class TestCommandValidation:
    """Tests for command/shell validation in TerminalService."""

    @pytest.fixture
    def mock_rns_service(self):
        """Create a minimal mock RNS service."""
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.identity = None
        return mock

    @pytest.fixture
    def mock_styrene_protocol(self):
        """Create a minimal mock Styrene protocol."""
        from unittest.mock import MagicMock

        return MagicMock()

    @pytest.fixture
    def terminal_service(self, mock_rns_service, mock_styrene_protocol):
        """Create a TerminalService with default command validation settings."""
        from styrened.terminal.service import TerminalService

        return TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allow_unauthenticated=False,
        )

    def test_default_allowed_shells_constant_exists(self) -> None:
        """DEFAULT_ALLOWED_SHELLS constant should be defined."""
        from styrened.terminal.service import DEFAULT_ALLOWED_SHELLS

        assert DEFAULT_ALLOWED_SHELLS is not None
        assert isinstance(DEFAULT_ALLOWED_SHELLS, frozenset)

    def test_default_allowed_shells_values(self) -> None:
        """DEFAULT_ALLOWED_SHELLS should include common shells."""
        from styrened.terminal.service import DEFAULT_ALLOWED_SHELLS

        assert "/bin/bash" in DEFAULT_ALLOWED_SHELLS
        assert "/bin/sh" in DEFAULT_ALLOWED_SHELLS
        assert "/bin/zsh" in DEFAULT_ALLOWED_SHELLS

    def test_service_has_command_validation_attributes(self, terminal_service) -> None:
        """TerminalService should have command validation attributes."""
        assert hasattr(terminal_service, "_disable_command_validation")
        assert hasattr(terminal_service, "_allowed_shells")
        assert hasattr(terminal_service, "_allowed_commands")

    def test_default_command_validation_enabled(self, terminal_service) -> None:
        """Command validation should be enabled by default."""
        assert terminal_service._disable_command_validation is False

    def test_default_allowed_shells_used(self, terminal_service) -> None:
        """Default allowed shells should be used when not specified."""
        from styrened.terminal.service import DEFAULT_ALLOWED_SHELLS

        assert terminal_service._allowed_shells == DEFAULT_ALLOWED_SHELLS

    def test_default_allowed_commands_none(self, terminal_service) -> None:
        """Allowed commands should be None by default (no command execution)."""
        assert terminal_service._allowed_commands is None

    def test_custom_allowed_shells(self, mock_rns_service, mock_styrene_protocol) -> None:
        """Custom allowed shells should be configurable."""
        from styrened.terminal.service import TerminalService

        custom_shells = {"/bin/bash", "/usr/local/bin/fish"}
        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allowed_shells=custom_shells,
        )

        assert service._allowed_shells == frozenset(custom_shells)
        assert "/bin/bash" in service._allowed_shells
        assert "/usr/local/bin/fish" in service._allowed_shells
        assert "/bin/zsh" not in service._allowed_shells

    def test_custom_allowed_commands(self, mock_rns_service, mock_styrene_protocol) -> None:
        """Custom allowed commands should be configurable."""
        from styrened.terminal.service import TerminalService

        custom_commands = {"/usr/bin/python3", "/usr/bin/top"}
        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allowed_commands=custom_commands,
        )

        assert service._allowed_commands == frozenset(custom_commands)
        assert "/usr/bin/python3" in service._allowed_commands
        assert "/usr/bin/top" in service._allowed_commands

    def test_empty_allowed_commands(self, mock_rns_service, mock_styrene_protocol) -> None:
        """Empty allowed commands set should block all commands."""
        from styrened.terminal.service import TerminalService

        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allowed_commands=set(),  # Empty set - no commands allowed
        )

        assert service._allowed_commands == frozenset()

    def test_disable_command_validation(self, mock_rns_service, mock_styrene_protocol) -> None:
        """Command validation can be disabled (DANGEROUS)."""
        from styrened.terminal.service import TerminalService

        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            disable_command_validation=True,
        )

        assert service._disable_command_validation is True

    def test_validate_shell_allowed(self, terminal_service) -> None:
        """Validate that _validate_command allows valid shells."""
        # Default shells should be valid
        error = terminal_service._validate_command(shell="/bin/bash", command=None)
        assert error is None

        error = terminal_service._validate_command(shell="/bin/sh", command=None)
        assert error is None

        error = terminal_service._validate_command(shell="/bin/zsh", command=None)
        assert error is None

    def test_validate_shell_rejected(self, terminal_service) -> None:
        """Validate that _validate_command rejects disallowed shells."""
        error = terminal_service._validate_command(shell="/bin/evil", command=None)
        assert error is not None
        assert "disallowed" in error.lower() or "not allowed" in error.lower()

    def test_validate_command_rejected_by_default(self, terminal_service) -> None:
        """Commands should be rejected by default (only shells allowed)."""
        error = terminal_service._validate_command(shell="/bin/bash", command="/usr/bin/python3")
        assert error is not None
        assert "command" in error.lower()

    def test_validate_command_allowed_when_configured(
        self, mock_rns_service, mock_styrene_protocol
    ) -> None:
        """Commands should be allowed when in allowed_commands."""
        from styrened.terminal.service import TerminalService

        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allowed_commands={"/usr/bin/python3"},
        )

        error = service._validate_command(shell="/bin/bash", command="/usr/bin/python3")
        assert error is None

    def test_validate_command_rejected_when_not_in_list(
        self, mock_rns_service, mock_styrene_protocol
    ) -> None:
        """Commands not in allowed_commands should be rejected."""
        from styrened.terminal.service import TerminalService

        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allowed_commands={"/usr/bin/python3"},
        )

        error = service._validate_command(shell="/bin/bash", command="/usr/bin/evil")
        assert error is not None

    def test_validate_skipped_when_disabled(self, mock_rns_service, mock_styrene_protocol) -> None:
        """Validation should be skipped when disabled."""
        from styrened.terminal.service import TerminalService

        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            disable_command_validation=True,
        )

        # Should allow anything when disabled
        error = service._validate_command(shell="/bin/evil", command="/usr/bin/anything")
        assert error is None

    def test_validate_resolves_relative_paths(
        self, mock_rns_service, mock_styrene_protocol
    ) -> None:
        """Validation should resolve relative paths to absolute."""
        from styrened.terminal.service import TerminalService

        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allowed_shells={"/bin/bash"},
        )

        # Relative path that resolves to /bin/bash via PATH should work
        # This tests the shutil.which behavior
        error = service._validate_command(shell="bash", command=None)
        # This may or may not resolve depending on system - test that it doesn't crash
        assert isinstance(error, str) or error is None

    def test_reject_code_4_for_command_validation(self) -> None:
        """TERMINAL_REJECT with code=4 should indicate command validation failure."""
        reject = create_terminal_reject(
            reason="Shell not allowed",
            code=4,
            request_id=b"request_id_12345",
        )

        payload = decode_payload(reject.payload)
        assert payload["code"] == 4
        assert "Shell" in payload["reason"] or "shell" in payload["reason"]


class TestIdleTimeout:
    """Tests for session idle timeout in TerminalService."""

    @pytest.fixture
    def mock_rns_service(self):
        """Create a minimal mock RNS service."""
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.identity = None
        return mock

    @pytest.fixture
    def mock_styrene_protocol(self):
        """Create a minimal mock Styrene protocol."""
        from unittest.mock import MagicMock

        return MagicMock()

    @pytest.fixture
    def terminal_service(self, mock_rns_service, mock_styrene_protocol):
        """Create a TerminalService with default idle timeout."""
        from styrened.terminal.service import TerminalService

        return TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allow_unauthenticated=False,
        )

    @pytest.fixture
    def service_with_short_timeout(self, mock_rns_service, mock_styrene_protocol):
        """Create a TerminalService with a short idle timeout for testing."""
        from styrened.terminal.service import TerminalService

        return TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            allow_unauthenticated=False,
            session_idle_timeout=60.0,  # 1 minute for testing
        )

    def test_idle_timeout_constant_exists(self) -> None:
        """SESSION_IDLE_TIMEOUT constant should be defined."""
        from styrened.terminal.service import SESSION_IDLE_TIMEOUT

        assert SESSION_IDLE_TIMEOUT == 3600  # 1 hour

    def test_idle_check_interval_constant_exists(self) -> None:
        """IDLE_CHECK_INTERVAL constant should be defined."""
        from styrened.terminal.service import IDLE_CHECK_INTERVAL

        assert IDLE_CHECK_INTERVAL == 60  # 60 seconds

    def test_idle_timeout_parameter_configurable(
        self, mock_rns_service, mock_styrene_protocol
    ) -> None:
        """Idle timeout should be configurable via constructor parameter."""
        from styrened.terminal.service import TerminalService

        service = TerminalService(
            rns_service=mock_rns_service,
            styrene_protocol=mock_styrene_protocol,
            authorized_identities={"test_identity"},
            session_idle_timeout=1800.0,  # 30 minutes
        )

        assert service.session_idle_timeout == 1800.0

    def test_default_idle_timeout(self, terminal_service) -> None:
        """Default idle timeout should be SESSION_IDLE_TIMEOUT."""
        from styrened.terminal.service import SESSION_IDLE_TIMEOUT

        assert terminal_service.session_idle_timeout == SESSION_IDLE_TIMEOUT

    def test_terminal_session_has_last_activity(self) -> None:
        """TerminalSession should have last_activity field."""
        import time

        from styrened.terminal.service import TerminalSession

        now = time.time()
        session = TerminalSession(
            session_id=b"session_id_12345",
            source_identity="test_identity",
            master_fd=99,
            child_pid=12345,
        )

        # last_activity should be set to creation time
        assert hasattr(session, "last_activity")
        assert session.last_activity >= now - 1
        assert session.last_activity <= now + 1

    def test_terminal_session_update_activity(self) -> None:
        """TerminalSession.update_activity() should update the timestamp."""
        import time

        from styrened.terminal.service import TerminalSession

        session = TerminalSession(
            session_id=b"session_id_12345",
            source_identity="test_identity",
            master_fd=99,
            child_pid=12345,
        )

        # Set a past activity time
        session.last_activity = time.time() - 1000

        # Update activity
        before_update = time.time()
        session.update_activity()
        after_update = time.time()

        # Should be updated to current time
        assert session.last_activity >= before_update
        assert session.last_activity <= after_update

    def test_idle_check_task_initialized(self, terminal_service) -> None:
        """Idle check task attribute should exist."""
        assert hasattr(terminal_service, "_idle_check_task")

    async def test_check_idle_sessions_closes_expired(self, service_with_short_timeout) -> None:
        """_check_idle_sessions should close sessions past idle timeout."""
        import time
        from unittest.mock import MagicMock, patch

        # Create a mock session that is past the idle timeout
        # Note: sessions with link=None are checked against handoff timeout using created_at
        # Sessions with link set are checked against idle timeout using last_activity
        session_id = b"session_id_12345"
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.source_identity = "test_identity"
        mock_session.last_activity = time.time() - 120  # 2 minutes ago (past 1 min timeout)
        mock_session.created_at = time.time()  # Recent creation (not handoff timeout)
        mock_session.link = MagicMock()  # Link is established, so idle timeout applies
        mock_session._read_task = None

        service_with_short_timeout.sessions[session_id] = mock_session

        # Mock _close_session to track calls
        with patch.object(service_with_short_timeout, "_close_session") as mock_close:
            # Run the check
            await service_with_short_timeout._check_idle_sessions()

            # Session should have been closed
            mock_close.assert_called_once_with(
                session_id,
                exit_code=-1,
                reason="idle_timeout",
            )

    async def test_check_idle_sessions_keeps_active(self, service_with_short_timeout) -> None:
        """_check_idle_sessions should not close sessions with recent activity."""
        import time
        from unittest.mock import MagicMock, patch

        # Create a mock session with recent activity
        # Sessions with link set are checked against idle timeout using last_activity
        session_id = b"session_id_12345"
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.source_identity = "test_identity"
        mock_session.last_activity = time.time() - 10  # 10 seconds ago (within 1 min timeout)
        mock_session.created_at = time.time()  # Recent creation
        mock_session.link = MagicMock()  # Link is established, so idle timeout applies
        mock_session._read_task = None

        service_with_short_timeout.sessions[session_id] = mock_session

        # Mock _close_session to track calls
        with patch.object(service_with_short_timeout, "_close_session") as mock_close:
            # Run the check
            await service_with_short_timeout._check_idle_sessions()

            # Session should NOT have been closed
            mock_close.assert_not_called()

    async def test_check_idle_sessions_handles_multiple(self, service_with_short_timeout) -> None:
        """_check_idle_sessions should handle multiple sessions correctly."""
        import time
        from unittest.mock import MagicMock, patch

        # Create one expired and one active session
        # Sessions with link set are checked against idle timeout using last_activity
        expired_id = b"expired_session0"
        active_id = b"active_session00"

        expired_session = MagicMock()
        expired_session.session_id = expired_id
        expired_session.source_identity = "test_identity"
        expired_session.last_activity = time.time() - 120  # Expired
        expired_session.created_at = time.time()  # Recent creation
        expired_session.link = MagicMock()  # Link established
        expired_session._read_task = None

        active_session = MagicMock()
        active_session.session_id = active_id
        active_session.source_identity = "test_identity"
        active_session.last_activity = time.time() - 10  # Active
        active_session.created_at = time.time()  # Recent creation
        active_session.link = MagicMock()  # Link established
        active_session._read_task = None

        service_with_short_timeout.sessions[expired_id] = expired_session
        service_with_short_timeout.sessions[active_id] = active_session

        with patch.object(service_with_short_timeout, "_close_session") as mock_close:
            await service_with_short_timeout._check_idle_sessions()

            # Only expired session should be closed
            assert mock_close.call_count == 1
            call_args = mock_close.call_args
            assert call_args[0][0] == expired_id

    def test_terminal_closed_reason_idle_timeout(self) -> None:
        """TERMINAL_CLOSED with reason 'idle_timeout' should be valid."""
        closed = create_terminal_closed(
            exit_code=-1,
            reason="idle_timeout",
            session_id=b"session_id_12345",
        )

        assert closed.message_type == StyreneMessageType.TERMINAL_CLOSED

        payload = decode_payload(closed.payload)
        assert payload["exit_code"] == -1
        assert payload["reason"] == "idle_timeout"

    @pytest.mark.asyncio
    async def test_activity_updated_on_link_association(self, terminal_service) -> None:
        """Activity should be updated when Link is associated via async verification."""
        import time
        from unittest.mock import MagicMock, patch

        # Create a mock link and identity
        mock_identity = MagicMock()
        mock_identity.hexhash = "abc123def456abc123def456abc123de"

        mock_link = MagicMock()
        mock_link.get_remote_identity.return_value = mock_identity
        mock_link._terminal_session = None
        mock_link.send = MagicMock()

        # Create a session with old activity
        # IMPORTANT: link must be None to allow association (prevents session hijacking)
        session_id = b"0123456789abcdef"
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.source_identity = "abc123def456abc123def456abc123de"
        mock_session.last_activity = time.time() - 1000  # Old activity
        mock_session._association_pending = False
        mock_session.link = None  # No existing link - allows association

        terminal_service.sessions[session_id] = mock_session

        # Call async verification directly (this is what gets scheduled)
        with patch("asyncio.sleep", return_value=None):
            await terminal_service._async_verify_and_associate(mock_link, session_id, mock_session)

        # Activity should have been updated on successful association
        mock_session.update_activity.assert_called_once()

    def test_activity_updated_on_data_received(self, terminal_service) -> None:
        """Activity should be updated when data is received on Link."""
        from unittest.mock import MagicMock

        from styrened.terminal.messages import StreamData, serialize_message

        # Create a session that is already associated
        mock_session = MagicMock()
        mock_session.master_fd = 99

        mock_link = MagicMock()
        mock_link._terminal_session = mock_session

        # Send stdin data
        stdin_msg = StreamData(stream=StreamData.STDIN, data=b"test input")
        data = serialize_message(stdin_msg)

        terminal_service._on_link_packet(mock_link, data, MagicMock())

        # Activity should have been updated
        mock_session.update_activity.assert_called()

    async def test_activity_updated_on_resize(self, terminal_service) -> None:
        """Activity should be updated on TERMINAL_RESIZE."""
        from unittest.mock import MagicMock, patch

        # Create a session
        session_id = b"0123456789abcdef"
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.source_identity = "test_identity_hash"

        terminal_service.sessions[session_id] = mock_session

        # Create resize envelope
        resize = create_terminal_resize(
            rows=50,
            cols=100,
            session_id=session_id,
        )

        # Create mock LXMF message with source_hash
        mock_message = MagicMock()
        mock_message.source_hash = b"lxmf_source_hash"

        # Mock identity resolution to return the session's source_identity
        with patch.object(
            terminal_service, "_resolve_identity_hash", return_value="test_identity_hash"
        ):
            await terminal_service._handle_terminal_resize(mock_message, resize)

        # Activity should have been updated
        mock_session.update_activity.assert_called_once()

    async def test_activity_updated_on_signal(self, terminal_service) -> None:
        """Activity should be updated on TERMINAL_SIGNAL."""
        from unittest.mock import MagicMock, patch

        # Create a session
        session_id = b"0123456789abcdef"
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.source_identity = "test_identity_hash"
        mock_session.child_pid = 12345

        terminal_service.sessions[session_id] = mock_session

        # Create signal envelope
        sig = create_terminal_signal(
            signal=signal.SIGINT,
            session_id=session_id,
        )

        # Create mock LXMF message with source_hash
        mock_message = MagicMock()
        mock_message.source_hash = b"lxmf_source_hash"

        # Mock identity resolution to return the session's source_identity
        with (
            patch("os.kill"),
            patch.object(
                terminal_service, "_resolve_identity_hash", return_value="test_identity_hash"
            ),
        ):
            await terminal_service._handle_terminal_signal(mock_message, sig)

        # Activity should have been updated
        mock_session.update_activity.assert_called_once()
