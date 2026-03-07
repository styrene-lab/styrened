"""Tests for RBAC-based authorization in RPCServer.

Verifies that when an RBACPolicy is provided, RPCServer uses capability
checks (has_capability) instead of legacy authorized_identities / dangerous
commands gating.  Also verifies legacy fallback when rbac_policy=None.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from styrened.models.rbac import Capability, RBACPolicy, Role, RosterEntry
from styrened.models.styrene_wire import (
    NO_CORRELATION,
    StyreneEnvelope,
    StyreneMessageType,
)
from styrened.rpc.server import (
    MESSAGE_TYPE_CAPABILITY,
    RPCServer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_protocol() -> MagicMock:
    """Create a mock StyreneProtocol."""
    proto = MagicMock()
    proto.register_handler = MagicMock()
    proto.send_typed_message = AsyncMock()
    return proto


def _make_envelope(msg_type: StyreneMessageType) -> StyreneEnvelope:
    return StyreneEnvelope(
        version=2,
        message_type=msg_type,
        payload=b"",
        request_id=b"\x00" * 16,
    )


def _make_message(source: str) -> MagicMock:
    msg = MagicMock()
    msg.source_hash = source
    return msg


def _policy(
    default_role: Role = Role.PEER,
    roster: dict[str, RosterEntry] | None = None,
    blocked: list[str] | None = None,
) -> RBACPolicy:
    return RBACPolicy(
        default_role=default_role,
        roster=roster or {},
        blocked=blocked or [],
    )


ADMIN_HASH = "a" * 32
OPERATOR_HASH = "b" * 32
MONITOR_HASH = "c" * 32
PEER_HASH = "d" * 32
BLOCKED_HASH = "e" * 32
UNKNOWN_HASH = "f" * 32  # falls to default_role


def _full_policy() -> RBACPolicy:
    """Policy with one identity per role and default_role=PEER."""
    return _policy(
        default_role=Role.PEER,
        roster={
            ADMIN_HASH: RosterEntry(identity_hash=ADMIN_HASH, role=Role.ADMIN),
            OPERATOR_HASH: RosterEntry(identity_hash=OPERATOR_HASH, role=Role.OPERATOR),
            MONITOR_HASH: RosterEntry(identity_hash=MONITOR_HASH, role=Role.MONITOR),
            PEER_HASH: RosterEntry(identity_hash=PEER_HASH, role=Role.PEER),
            BLOCKED_HASH: RosterEntry(identity_hash=BLOCKED_HASH, role=Role.BLOCKED),
        },
    )


# ---------------------------------------------------------------------------
# MESSAGE_TYPE_CAPABILITY mapping completeness
# ---------------------------------------------------------------------------

class TestMessageTypeCapabilityMapping:
    """Verify the mapping covers all registered RPC types."""

    def test_ping_maps_to_ping_cap(self):
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.PING] == Capability.PING

    def test_status_request_maps_to_status_query(self):
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.STATUS_REQUEST] == Capability.STATUS_QUERY

    def test_exec_maps_to_exec(self):
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.EXEC] == Capability.EXEC

    def test_reboot_maps_to_reboot(self):
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.REBOOT] == Capability.REBOOT

    def test_config_update_maps_to_config_update(self):
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.CONFIG_UPDATE] == Capability.CONFIG_UPDATE

    def test_self_update_maps_to_self_update(self):
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.SELF_UPDATE] == Capability.SELF_UPDATE

    def test_inbox_query_maps_to_inbox_read(self):
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.INBOX_QUERY] == Capability.INBOX_READ

    def test_messages_query_maps_to_inbox_read(self):
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.MESSAGES_QUERY] == Capability.INBOX_READ


# ---------------------------------------------------------------------------
# RBAC authorization in _protocol_handler
# ---------------------------------------------------------------------------

class TestRBACProtocolHandler:
    """Test RBAC-gated dispatch in _protocol_handler."""

    @pytest.fixture()
    def server(self):
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=_full_policy())
        srv._running = True
        # Stub all handlers so dispatch doesn't error
        for mt in MESSAGE_TYPE_CAPABILITY:
            srv._handlers[mt] = MagicMock()
        return srv

    @pytest.mark.asyncio
    async def test_blocked_role_denied_for_all_types(self, server):
        """BLOCKED identity cannot invoke any RPC."""
        for msg_type in MESSAGE_TYPE_CAPABILITY:
            envelope = _make_envelope(msg_type)
            message = _make_message(BLOCKED_HASH)
            await server._protocol_handler(message, envelope)
        # No handler should have been called
        for mt in MESSAGE_TYPE_CAPABILITY:
            server._handlers[mt].assert_not_called()

    @pytest.mark.asyncio
    async def test_peer_can_ping(self, server):
        envelope = _make_envelope(StyreneMessageType.PING)
        await server._protocol_handler(_make_message(PEER_HASH), envelope)
        server._handlers[StyreneMessageType.PING].assert_called_once()

    @pytest.mark.asyncio
    async def test_peer_can_status(self, server):
        envelope = _make_envelope(StyreneMessageType.STATUS_REQUEST)
        await server._protocol_handler(_make_message(PEER_HASH), envelope)
        server._handlers[StyreneMessageType.STATUS_REQUEST].assert_called_once()

    @pytest.mark.asyncio
    async def test_peer_cannot_exec(self, server):
        envelope = _make_envelope(StyreneMessageType.EXEC)
        await server._protocol_handler(_make_message(PEER_HASH), envelope)
        server._handlers[StyreneMessageType.EXEC].assert_not_called()

    @pytest.mark.asyncio
    async def test_peer_cannot_reboot(self, server):
        envelope = _make_envelope(StyreneMessageType.REBOOT)
        await server._protocol_handler(_make_message(PEER_HASH), envelope)
        server._handlers[StyreneMessageType.REBOOT].assert_not_called()

    @pytest.mark.asyncio
    async def test_peer_cannot_inbox_read(self, server):
        """PEER role does not include rpc.inbox_read."""
        envelope = _make_envelope(StyreneMessageType.INBOX_QUERY)
        await server._protocol_handler(_make_message(PEER_HASH), envelope)
        server._handlers[StyreneMessageType.INBOX_QUERY].assert_not_called()

    @pytest.mark.asyncio
    async def test_monitor_can_inbox_read(self, server):
        """MONITOR role includes rpc.inbox_read — real policy check, no mock."""
        envelope = _make_envelope(StyreneMessageType.INBOX_QUERY)
        await server._protocol_handler(_make_message(MONITOR_HASH), envelope)
        server._handlers[StyreneMessageType.INBOX_QUERY].assert_called_once()

    @pytest.mark.asyncio
    async def test_operator_can_config_update(self, server):
        envelope = _make_envelope(StyreneMessageType.CONFIG_UPDATE)
        await server._protocol_handler(_make_message(OPERATOR_HASH), envelope)
        server._handlers[StyreneMessageType.CONFIG_UPDATE].assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_can_exec(self, server):
        envelope = _make_envelope(StyreneMessageType.EXEC)
        await server._protocol_handler(_make_message(ADMIN_HASH), envelope)
        server._handlers[StyreneMessageType.EXEC].assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_can_reboot(self, server):
        envelope = _make_envelope(StyreneMessageType.REBOOT)
        await server._protocol_handler(_make_message(ADMIN_HASH), envelope)
        server._handlers[StyreneMessageType.REBOOT].assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_can_self_update(self, server):
        envelope = _make_envelope(StyreneMessageType.SELF_UPDATE)
        await server._protocol_handler(_make_message(ADMIN_HASH), envelope)
        server._handlers[StyreneMessageType.SELF_UPDATE].assert_called_once()

    @pytest.mark.asyncio
    async def test_default_role_peer_fail_closed_for_dangerous(self, server):
        """Unknown identity gets default_role=PEER, cannot exec."""
        envelope = _make_envelope(StyreneMessageType.EXEC)
        await server._protocol_handler(_make_message(UNKNOWN_HASH), envelope)
        server._handlers[StyreneMessageType.EXEC].assert_not_called()

    @pytest.mark.asyncio
    async def test_default_role_peer_can_ping(self, server):
        """Unknown identity gets default_role=PEER, can ping."""
        envelope = _make_envelope(StyreneMessageType.PING)
        await server._protocol_handler(_make_message(UNKNOWN_HASH), envelope)
        server._handlers[StyreneMessageType.PING].assert_called_once()

    @pytest.mark.asyncio
    async def test_blocked_peer_receives_error_response(self):
        """BLOCKED peer gets COMMAND_NOT_ALLOWED error sent back."""
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=_full_policy())
        srv._running = True
        for mt in MESSAGE_TYPE_CAPABILITY:
            srv._handlers[mt] = MagicMock()

        # Use a real request_id (non-zero) so error response is sent
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.PING,
            payload=b"",
            request_id=b"\x01" * 16,
        )
        await srv._protocol_handler(_make_message(BLOCKED_HASH), envelope)

        # Handler should NOT have been called
        srv._handlers[StyreneMessageType.PING].assert_not_called()
        # Error response should have been sent via protocol
        proto.send_typed_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_monitor_cannot_exec(self, server):
        """MONITOR role does not include rpc.exec."""
        envelope = _make_envelope(StyreneMessageType.EXEC)
        await server._protocol_handler(_make_message(MONITOR_HASH), envelope)
        server._handlers[StyreneMessageType.EXEC].assert_not_called()

    @pytest.mark.asyncio
    async def test_operator_cannot_exec(self, server):
        """OPERATOR role does not include rpc.exec."""
        envelope = _make_envelope(StyreneMessageType.EXEC)
        await server._protocol_handler(_make_message(OPERATOR_HASH), envelope)
        server._handlers[StyreneMessageType.EXEC].assert_not_called()


# ---------------------------------------------------------------------------
# Fail-closed: unmapped message type
# ---------------------------------------------------------------------------

class TestRBACFailClosed:
    """Unmapped message types must be rejected in RBAC mode."""

    @pytest.mark.asyncio
    async def test_unmapped_message_type_rejected(self):
        """A message type with no capability mapping is fail-closed."""
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=_full_policy())
        srv._running = True

        # Register a handler for TERMINAL_REQUEST (not in MESSAGE_TYPE_CAPABILITY)
        srv._handlers[StyreneMessageType.TERMINAL_REQUEST] = MagicMock()

        envelope = _make_envelope(StyreneMessageType.TERMINAL_REQUEST)
        await srv._protocol_handler(_make_message(ADMIN_HASH), envelope)

        srv._handlers[StyreneMessageType.TERMINAL_REQUEST].assert_not_called()

    @pytest.mark.asyncio
    async def test_unmapped_message_type_sends_error(self):
        """Unmapped message type sends error response when request_id is set."""
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=_full_policy())
        srv._running = True

        srv._handlers[StyreneMessageType.TERMINAL_REQUEST] = MagicMock()

        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.TERMINAL_REQUEST,
            payload=b"",
            request_id=b"\x01" * 16,
        )
        await srv._protocol_handler(_make_message(ADMIN_HASH), envelope)

        proto.send_typed_message.assert_called_once()


# ---------------------------------------------------------------------------
# Server not running
# ---------------------------------------------------------------------------

class TestServerNotRunning:
    """Messages are silently dropped when server is not running."""

    @pytest.mark.asyncio
    async def test_rbac_mode_not_running(self):
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=_full_policy())
        srv._running = False
        srv._handlers[StyreneMessageType.PING] = MagicMock()

        await srv._protocol_handler(_make_message(ADMIN_HASH), _make_envelope(StyreneMessageType.PING))
        srv._handlers[StyreneMessageType.PING].assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_mode_not_running(self):
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=None)
        srv._running = False
        srv._handlers[StyreneMessageType.PING] = MagicMock()

        await srv._protocol_handler(_make_message("anyone"), _make_envelope(StyreneMessageType.PING))
        srv._handlers[StyreneMessageType.PING].assert_not_called()


# ---------------------------------------------------------------------------
# NO_CORRELATION suppresses error response
# ---------------------------------------------------------------------------

class TestNoCorrelationSuppressesError:
    """Rejected messages with NO_CORRELATION don't trigger error responses."""

    @pytest.mark.asyncio
    async def test_rbac_denied_no_error_when_no_correlation(self):
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=_full_policy())
        srv._running = True
        srv._handlers[StyreneMessageType.EXEC] = MagicMock()

        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.EXEC,
            payload=b"",
            request_id=NO_CORRELATION,
        )
        await srv._protocol_handler(_make_message(PEER_HASH), envelope)

        srv._handlers[StyreneMessageType.EXEC].assert_not_called()
        proto.send_typed_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_envelope_rejects_empty_request_id(self):
        """StyreneEnvelope enforces 16-byte request_id — empty is invalid."""
        with pytest.raises(ValueError, match="request_id must be 16 bytes"):
            StyreneEnvelope(
                version=2,
                message_type=StyreneMessageType.EXEC,
                payload=b"",
                request_id=b"",
            )


# ---------------------------------------------------------------------------
# Replay protection in RBAC mode
# ---------------------------------------------------------------------------

class TestReplayProtectionRBAC:
    """Replay protection in RBAC mode uses explicit skip set."""

    @pytest.mark.asyncio
    async def test_exec_replay_caught_in_rbac_mode(self):
        """Duplicate EXEC request_id is rejected as replay."""
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=_full_policy())
        srv._running = True
        srv._handlers[StyreneMessageType.EXEC] = MagicMock()

        req_id = b"\xaa" * 16
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.EXEC,
            payload=b"",
            request_id=req_id,
        )

        # First call — dispatched
        await srv._protocol_handler(_make_message(ADMIN_HASH), envelope)
        assert srv._handlers[StyreneMessageType.EXEC].call_count == 1

        # Second call — replay
        await srv._protocol_handler(_make_message(ADMIN_HASH), envelope)
        assert srv._handlers[StyreneMessageType.EXEC].call_count == 1  # still 1

    @pytest.mark.asyncio
    async def test_ping_replay_not_tracked_in_rbac_mode(self):
        """PING replays are not tracked (skip set) in RBAC mode."""
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=_full_policy())
        srv._running = True
        srv._handlers[StyreneMessageType.PING] = MagicMock()

        req_id = b"\xbb" * 16
        envelope = StyreneEnvelope(
            version=2,
            message_type=StyreneMessageType.PING,
            payload=b"",
            request_id=req_id,
        )

        await srv._protocol_handler(_make_message(PEER_HASH), envelope)
        await srv._protocol_handler(_make_message(PEER_HASH), envelope)
        assert srv._handlers[StyreneMessageType.PING].call_count == 2


# ---------------------------------------------------------------------------
# Rate limiting fires after RBAC auth
# ---------------------------------------------------------------------------

class TestRateLimitingWithRBAC:
    """Rate limiting still applies after RBAC authorization succeeds."""

    @pytest.mark.asyncio
    async def test_rate_limit_after_rbac_pass(self):
        """Authorized identity is rate-limited after exceeding threshold."""
        proto = _make_protocol()
        srv = RPCServer(proto, rbac_policy=_full_policy(), rate_limit=3)
        srv._running = True
        srv._handlers[StyreneMessageType.STATUS_REQUEST] = MagicMock()

        for i in range(5):
            envelope = StyreneEnvelope(
                version=2,
                message_type=StyreneMessageType.STATUS_REQUEST,
                payload=b"",
                request_id=i.to_bytes(16, "big"),
            )
            await srv._protocol_handler(_make_message(ADMIN_HASH), envelope)

        # First 3 should succeed, rest rate-limited
        assert srv._handlers[StyreneMessageType.STATUS_REQUEST].call_count == 3


# ---------------------------------------------------------------------------
# Explicit grant overrides role tier
# ---------------------------------------------------------------------------

class TestExplicitGrants:
    """Explicit grants on roster entries override role-based capabilities."""

    @pytest.mark.asyncio
    async def test_peer_with_exec_grant_can_exec(self):
        """PEER with explicit rpc.exec grant can execute EXEC."""
        proto = _make_protocol()
        policy = _policy(
            default_role=Role.NONE,
            roster={
                PEER_HASH: RosterEntry(
                    identity_hash=PEER_HASH,
                    role=Role.PEER,
                    grants=frozenset([Capability.EXEC]),
                ),
            },
        )
        srv = RPCServer(proto, rbac_policy=policy)
        srv._running = True
        srv._handlers[StyreneMessageType.EXEC] = MagicMock()

        envelope = _make_envelope(StyreneMessageType.EXEC)
        await srv._protocol_handler(_make_message(PEER_HASH), envelope)

        srv._handlers[StyreneMessageType.EXEC].assert_called_once()

    @pytest.mark.asyncio
    async def test_peer_without_grant_cannot_exec(self):
        """PEER without explicit grant still cannot EXEC."""
        proto = _make_protocol()
        policy = _policy(
            default_role=Role.NONE,
            roster={
                PEER_HASH: RosterEntry(identity_hash=PEER_HASH, role=Role.PEER),
            },
        )
        srv = RPCServer(proto, rbac_policy=policy)
        srv._running = True
        srv._handlers[StyreneMessageType.EXEC] = MagicMock()

        envelope = _make_envelope(StyreneMessageType.EXEC)
        await srv._protocol_handler(_make_message(PEER_HASH), envelope)

        srv._handlers[StyreneMessageType.EXEC].assert_not_called()
