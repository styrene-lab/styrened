"""Tests for RBAC-based authorization in RPCServer.

Verifies that when an RBACPolicy is provided, RPCServer uses capability
checks (has_capability) instead of legacy authorized_identities / dangerous
commands gating.  Also verifies legacy fallback when rbac_policy=None.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.INBOX_QUERY] == "rpc.inbox_read"

    def test_messages_query_maps_to_inbox_read(self):
        assert MESSAGE_TYPE_CAPABILITY[StyreneMessageType.MESSAGES_QUERY] == "rpc.inbox_read"


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
        """MONITOR role includes rpc.inbox_read (added by sibling task)."""
        # Manually ensure the policy grants this cap at MONITOR level
        # (sibling task adds it to _MONITOR_CAPS; we verify the server
        #  delegates correctly when the policy says yes)
        with patch.object(server._rbac_policy, "has_capability", return_value=True):
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


# ---------------------------------------------------------------------------
# Legacy fallback (rbac_policy=None)
# ---------------------------------------------------------------------------

class TestLegacyFallback:
    """When rbac_policy is None, legacy auth still works."""

    @pytest.fixture()
    def legacy_server(self):
        proto = _make_protocol()
        srv = RPCServer(
            proto,
            authorized_identities={"authid123"},
            enable_dangerous_commands=False,
            rbac_policy=None,
        )
        srv._running = True
        for mt in MESSAGE_TYPE_CAPABILITY:
            srv._handlers[mt] = MagicMock()
        return srv

    @pytest.mark.asyncio
    async def test_legacy_public_commands_allowed_for_anyone(self, legacy_server):
        """PING and STATUS_REQUEST are public in legacy mode."""
        for mt in [StyreneMessageType.PING, StyreneMessageType.STATUS_REQUEST]:
            envelope = _make_envelope(mt)
            await legacy_server._protocol_handler(_make_message("anon_hash"), envelope)
            legacy_server._handlers[mt].assert_called()

    @pytest.mark.asyncio
    async def test_legacy_unauthorized_rejected(self, legacy_server):
        """Non-public command from unauthorized identity is rejected."""
        envelope = _make_envelope(StyreneMessageType.INBOX_QUERY)
        await legacy_server._protocol_handler(_make_message("unknown"), envelope)
        legacy_server._handlers[StyreneMessageType.INBOX_QUERY].assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_authorized_non_dangerous_allowed(self, legacy_server):
        """Authorized identity can run non-dangerous, non-public commands."""
        envelope = _make_envelope(StyreneMessageType.INBOX_QUERY)
        await legacy_server._protocol_handler(_make_message("authid123"), envelope)
        legacy_server._handlers[StyreneMessageType.INBOX_QUERY].assert_called_once()

    @pytest.mark.asyncio
    async def test_legacy_dangerous_disabled_rejected(self, legacy_server):
        """EXEC rejected when enable_dangerous_commands=False, even for authorized id."""
        envelope = _make_envelope(StyreneMessageType.EXEC)
        await legacy_server._protocol_handler(_make_message("authid123"), envelope)
        legacy_server._handlers[StyreneMessageType.EXEC].assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_dangerous_enabled_allowed(self):
        """EXEC allowed when enable_dangerous_commands=True and authorized."""
        proto = _make_protocol()
        srv = RPCServer(
            proto,
            authorized_identities={"authid123"},
            enable_dangerous_commands=True,
            rbac_policy=None,
        )
        srv._running = True
        srv._handlers[StyreneMessageType.EXEC] = MagicMock()
        envelope = _make_envelope(StyreneMessageType.EXEC)
        await srv._protocol_handler(_make_message("authid123"), envelope)
        srv._handlers[StyreneMessageType.EXEC].assert_called_once()
