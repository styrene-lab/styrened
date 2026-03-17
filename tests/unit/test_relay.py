"""Unit tests for RelayService, relay config parsing, and config round-trip."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from styrened.models.rbac import Capability, RBACPolicy, Role, RosterEntry
from styrened.models.relay import (
    RelayByteLimitExceeded,
    RelayConfig,
    RelayDisabled,
    RelayMaxPerIdentity,
    RelayMaxSessions,
    RelayPermanentConsentDenied,
    RelayPermanentDenied,
    RelaySession,
    RelayTargetOffline,
    RelayTargetRejected,
    RelayUnauthorized,
)
from styrened.services.relay import RelayService


def _operator_svc(cfg: RelayConfig) -> RelayService:
    """Create a RelayService with OPERATOR-default RBAC (grants permanent/priority)."""
    svc = RelayService(cfg)
    policy = RBACPolicy(default_role=Role.OPERATOR)
    svc.set_rbac_policy(policy)
    svc.set_target_rbac_policy(policy)
    return svc


# ---------------------------------------------------------------------------
# RelayService — creation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_basic():
    """Creating a session within limits succeeds."""
    svc = RelayService(RelayConfig(enabled=True))
    session = await svc.create_session("aaa", "bbb")
    assert session.requester_hash == "aaa"
    assert session.target_hash == "bbb"
    assert len(svc._sessions) == 1


@pytest.mark.asyncio
async def test_create_session_disabled():
    """Relay disabled rejects all requests."""
    svc = RelayService(RelayConfig(enabled=False))
    with pytest.raises(RelayDisabled):
        await svc.create_session("aaa", "bbb")


@pytest.mark.asyncio
async def test_create_session_global_cap():
    """Global session cap enforced — raises RelayMaxSessions."""
    cfg = RelayConfig(enabled=True, max_sessions=2)
    svc = RelayService(cfg)
    await svc.create_session("a1", "b1")
    await svc.create_session("a2", "b2")
    with pytest.raises(RelayMaxSessions):
        await svc.create_session("a3", "b3")


@pytest.mark.asyncio
async def test_create_session_per_identity_cap():
    """Per-identity cap enforced — raises RelayMaxPerIdentity."""
    cfg = RelayConfig(enabled=True, max_per_identity=2)
    svc = RelayService(cfg)
    await svc.create_session("aaa", "b1")
    await svc.create_session("aaa", "b2")
    with pytest.raises(RelayMaxPerIdentity):
        await svc.create_session("aaa", "b3")


@pytest.mark.asyncio
async def test_create_session_target_offline():
    """Target offline check raises RelayTargetOffline."""
    cfg = RelayConfig(enabled=True)
    svc = RelayService(cfg)
    svc._is_target_online = lambda h: False
    with pytest.raises(RelayTargetOffline):
        await svc.create_session("aaa", "bbb")


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_teardown_session():
    """Teardown removes session from dict."""
    svc = RelayService(RelayConfig(enabled=True))
    session = await svc.create_session("aaa", "bbb")
    sid = id(session)
    await svc.teardown_session(sid)
    assert sid not in svc._sessions


@pytest.mark.asyncio
async def test_teardown_nonexistent():
    """Teardown of unknown session is a no-op."""
    svc = RelayService(RelayConfig(enabled=True))
    await svc.teardown_session(999)  # should not raise


# ---------------------------------------------------------------------------
# Disconnect propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnect_propagation_default():
    """Non-permanent session: disconnect tears down both halves."""
    svc = RelayService(RelayConfig(enabled=True))
    session = await svc.create_session("aaa", "bbb")
    sid = id(session)
    await svc.disconnect_peer(sid, "aaa")
    assert sid not in svc._sessions


@pytest.mark.asyncio
async def test_disconnect_propagation_permanent():
    """Permanent session: disconnect keeps surviving half alive."""
    cfg = RelayConfig(enabled=True, allow_permanent=True)
    svc = _operator_svc(cfg)
    session = await svc.create_session("aaa", "bbb", permanent=True)
    sid = id(session)
    await svc.disconnect_peer(sid, "aaa")
    # Session should remain (surviving half stays)
    assert sid in svc._sessions


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lru_eviction_oldest_non_priority():
    """Oldest non-priority session evicted when full and new priority arrives."""
    cfg = RelayConfig(enabled=True, max_sessions=2)
    svc = _operator_svc(cfg)
    s1 = await svc.create_session("a1", "b1")
    s1.created_at = datetime(2020, 1, 1, tzinfo=UTC)
    s2 = await svc.create_session("a2", "b2", priority=True)
    s2.created_at = datetime(2021, 1, 1, tzinfo=UTC)

    # Now at cap. New priority request should evict s1 (oldest non-priority).
    s3 = await svc.create_session("a3", "b3", priority=True)
    assert id(s1) not in svc._sessions
    assert id(s3) in svc._sessions


@pytest.mark.asyncio
async def test_lru_eviction_all_priority():
    """All priority sessions — no evictable, raises RelayMaxSessions."""
    cfg = RelayConfig(enabled=True, max_sessions=2)
    svc = _operator_svc(cfg)
    await svc.create_session("a1", "b1", priority=True)
    await svc.create_session("a2", "b2", priority=True)
    with pytest.raises(RelayMaxSessions):
        await svc.create_session("a3", "b3")


# ---------------------------------------------------------------------------
# Byte limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_byte_limit_exceeded():
    """Byte limit raises RelayByteLimitExceeded and tears down session."""
    cfg = RelayConfig(enabled=True, max_bytes_per_session=1000)
    svc = RelayService(cfg)
    session = await svc.create_session("aaa", "bbb")
    sid = id(session)
    session.record_bytes(900)
    with pytest.raises(RelayByteLimitExceeded):
        await svc.enforce_byte_limit(sid, 200)
    assert sid not in svc._sessions


@pytest.mark.asyncio
async def test_byte_limit_permanent_exempt():
    """Permanent sessions skip byte limit enforcement."""
    cfg = RelayConfig(enabled=True, max_bytes_per_session=1000, allow_permanent=True)
    svc = _operator_svc(cfg)
    session = await svc.create_session("aaa", "bbb", permanent=True)
    sid = id(session)
    session.record_bytes(2000)
    # Should not raise
    await svc.enforce_byte_limit(sid, 200)
    assert sid in svc._sessions


# ---------------------------------------------------------------------------
# Idle timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_timeout():
    """Idle check tears down sessions past idle_timeout."""
    cfg = RelayConfig(enabled=True, idle_timeout=5)
    svc = RelayService(cfg)
    session = await svc.create_session("aaa", "bbb")
    sid = id(session)
    # Simulate stale last_activity
    session.last_activity = datetime.now(UTC) - timedelta(seconds=10)
    await svc.idle_check()
    assert sid not in svc._sessions


@pytest.mark.asyncio
async def test_idle_timeout_permanent_exempt():
    """Permanent sessions are exempt from idle timeout."""
    cfg = RelayConfig(enabled=True, idle_timeout=5, allow_permanent=True)
    svc = _operator_svc(cfg)
    session = await svc.create_session("aaa", "bbb", permanent=True)
    sid = id(session)
    session.last_activity = datetime.now(UTC) - timedelta(seconds=1800)
    await svc.idle_check()
    assert sid in svc._sessions


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


def test_relay_config_in_core_config_default():
    """CoreConfig has relay field defaulting to RelayConfig()."""
    from styrened.models.config import CoreConfig

    cc = CoreConfig()
    assert isinstance(cc.relay, RelayConfig)
    assert cc.relay.enabled is False


def test_relay_config_parse_full():
    """Full relay config parsed from YAML dict."""
    import yaml

    yaml_str = """
relay:
  enabled: true
  max_sessions: 8
  max_per_identity: 1
  idle_timeout: 300
  allow_permanent: true
"""
    data = yaml.safe_load(yaml_str)
    # Use internal parsing path
    from styrened.models.config import CoreConfig
    from styrened.services.config import _parse_relay

    config = CoreConfig()
    _parse_relay(config, data)
    assert config.relay.enabled is True
    assert config.relay.max_sessions == 8
    assert config.relay.max_per_identity == 1
    assert config.relay.idle_timeout == 300
    assert config.relay.allow_permanent is True


def test_relay_config_round_trip():
    """Serialize and load back preserves relay config."""
    import yaml

    from styrened.models.config import CoreConfig
    from styrened.services.config import serialize_config

    config = CoreConfig()
    config.relay = RelayConfig(enabled=True, max_sessions=32)
    serialized = serialize_config(config)
    assert serialized["relay"]["enabled"] is True
    assert serialized["relay"]["max_sessions"] == 32

    # Round-trip through YAML
    yaml_str = yaml.dump(serialized)
    data = yaml.safe_load(yaml_str)
    from styrened.services.config import _parse_relay

    config2 = CoreConfig()
    _parse_relay(config2, data)
    assert config2.relay.enabled is True
    assert config2.relay.max_sessions == 32


def test_relay_config_default_when_no_section():
    """No relay section in YAML → defaults."""
    from styrened.models.config import CoreConfig
    from styrened.services.config import _parse_relay

    config = CoreConfig()
    _parse_relay(config, {})
    assert config.relay.enabled is False
    assert config.relay.max_sessions == 16


# ---------------------------------------------------------------------------
# DirectLink — link_type field
# ---------------------------------------------------------------------------


def test_link_info_default_link_type():
    """LinkInfo defaults to LinkType.DIRECT link_type."""
    from styrened.models.relay import LinkType
    from styrened.services.direct_link import LinkInfo

    info = LinkInfo(destination_hash="abc123", status="active")
    assert info.link_type == LinkType.DIRECT


def test_link_info_relayed_link_type():
    """LinkInfo can be set to LinkType.RELAYED."""
    from styrened.models.relay import LinkType
    from styrened.services.direct_link import LinkInfo

    info = LinkInfo(destination_hash="abc123", status="active", link_type=LinkType.RELAYED)
    assert info.link_type == LinkType.RELAYED


def test_link_entry_default_link_type():
    """_LinkEntry defaults to LinkType.DIRECT link_type."""
    from unittest.mock import MagicMock

    from styrened.models.relay import LinkType
    from styrened.services.direct_link import _LinkEntry

    entry = _LinkEntry(
        link=MagicMock(),
        destination_hash="abc123",
        datalink_hash="def456",
    )
    assert entry.link_type == LinkType.DIRECT


def test_link_entry_relayed_link_type():
    """_LinkEntry can be set to LinkType.RELAYED."""
    from unittest.mock import MagicMock

    from styrened.models.relay import LinkType
    from styrened.services.direct_link import _LinkEntry

    entry = _LinkEntry(
        link=MagicMock(),
        destination_hash="abc123",
        datalink_hash="def456",
        link_type=LinkType.RELAYED,
    )
    assert entry.link_type == LinkType.RELAYED


# ---------------------------------------------------------------------------
# RelayService — set_rbac_policy
# ---------------------------------------------------------------------------


def test_relay_service_set_rbac_policy():
    """RelayService accepts RBAC policy injection."""
    from unittest.mock import MagicMock

    svc = RelayService(RelayConfig(enabled=True))
    policy = MagicMock()
    svc.set_rbac_policy(policy)
    assert svc._rbac_policy is policy


# ---------------------------------------------------------------------------
# Daemon — relay service lifecycle (unit-testable without RNS)
# ---------------------------------------------------------------------------


def test_daemon_has_relay_service_attr():
    """StyreneDaemon has _relay_service attribute initialized to None."""
    from unittest.mock import MagicMock

    with patch("styrened.daemon.load_core_config") as mock_load:
        mock_load.return_value = MagicMock()
        from styrened.daemon import StyreneDaemon

        daemon = StyreneDaemon.__new__(StyreneDaemon)
        daemon.config = MagicMock()
        daemon._direct_link_service = None
        daemon._datalink_destination = None
        daemon._mesh_vpn_service = None
        daemon._relay_service = None
        assert daemon._relay_service is None


def test_start_relay_service_creates_service():
    """_start_relay_service instantiates RelayService from config."""
    from unittest.mock import MagicMock

    daemon = MagicMock()
    daemon.config = MagicMock()
    daemon.config.relay = RelayConfig(enabled=True, max_sessions=4)
    daemon.config.rbac = RBACPolicy()
    daemon._relay_service = None

    from styrened.daemon import StyreneDaemon
    StyreneDaemon._start_relay_service(daemon)

    assert daemon._relay_service is not None
    assert daemon._relay_service._config.enabled is True
    assert daemon._relay_service._config.max_sessions == 4


def test_start_relay_service_injects_rbac():
    """_start_relay_service injects RBAC policy when available."""
    from unittest.mock import MagicMock

    daemon = MagicMock()
    daemon.config = MagicMock()
    daemon.config.relay = RelayConfig(enabled=True)
    rbac_policy = MagicMock()
    daemon.config.rbac = rbac_policy
    daemon._relay_service = None

    from styrened.daemon import StyreneDaemon
    StyreneDaemon._start_relay_service(daemon)

    assert daemon._relay_service is not None
    assert daemon._relay_service._rbac_policy is rbac_policy


# ---------------------------------------------------------------------------
# /relay endpoint handler
# ---------------------------------------------------------------------------


def test_serve_relay_no_service():
    """/relay returns error when relay service is None."""
    import json as _json
    from unittest.mock import MagicMock

    from styrened.daemon import StyreneDaemon

    daemon = MagicMock()
    daemon._relay_service = None
    daemon._datalink_identity_hex = StyreneDaemon._datalink_identity_hex.__get__(daemon)
    daemon._datalink_rl = MagicMock()
    daemon._datalink_rl.check.return_value = True
    daemon._datalink_rbac_role = MagicMock(return_value=10)  # PEER

    result = StyreneDaemon._serve_datalink_relay(
        daemon, "/relay",
        _json.dumps({"target_hash": "bbb"}).encode(),
        None, None, MagicMock(hash=bytes.fromhex("aa" * 16)), None,
    )
    resp = _json.loads(result)
    assert resp["error"] == "relay.disabled"


def test_serve_relay_blocked_identity():
    """/relay rejects blocked identities."""
    import json as _json
    from unittest.mock import MagicMock

    from styrened.daemon import StyreneDaemon

    daemon = MagicMock()
    daemon._relay_service = MagicMock()
    daemon._datalink_identity_hex = StyreneDaemon._datalink_identity_hex.__get__(daemon)
    daemon._datalink_rl = MagicMock()
    daemon._datalink_rl.check.return_value = True
    daemon._datalink_rbac_role = MagicMock(return_value=0)  # BLOCKED

    result = StyreneDaemon._serve_datalink_relay(
        daemon, "/relay",
        _json.dumps({"target_hash": "bbb"}).encode(),
        None, None, MagicMock(hash=bytes.fromhex("aa" * 16)), None,
    )
    resp = _json.loads(result)
    assert resp["error"] == "unauthorized"


def test_serve_relay_missing_target():
    """/relay rejects requests without target_hash."""
    import json as _json
    from unittest.mock import MagicMock

    from styrened.daemon import StyreneDaemon

    daemon = MagicMock()
    daemon._relay_service = MagicMock()
    daemon._datalink_identity_hex = StyreneDaemon._datalink_identity_hex.__get__(daemon)
    daemon._datalink_rl = MagicMock()
    daemon._datalink_rl.check.return_value = True
    daemon._datalink_rbac_role = MagicMock(return_value=10)  # PEER

    result = StyreneDaemon._serve_datalink_relay(
        daemon, "/relay",
        _json.dumps({}).encode(),
        None, None, MagicMock(hash=bytes.fromhex("aa" * 16)), None,
    )
    resp = _json.loads(result)
    assert resp["error"] == "missing_target_hash"


def test_serve_relay_target_offline():
    """/relay rejects when target has no active DirectLink."""
    import json as _json
    from unittest.mock import MagicMock

    from styrened.daemon import StyreneDaemon

    daemon = MagicMock()
    daemon._relay_service = MagicMock()
    daemon._direct_link_service = MagicMock()
    daemon._direct_link_service.get_link.return_value = None
    daemon._datalink_identity_hex = StyreneDaemon._datalink_identity_hex.__get__(daemon)
    daemon._datalink_rl = MagicMock()
    daemon._datalink_rl.check.return_value = True
    daemon._datalink_rbac_role = MagicMock(return_value=10)  # PEER

    result = StyreneDaemon._serve_datalink_relay(
        daemon, "/relay",
        _json.dumps({"target_hash": "bbb"}).encode(),
        None, None, MagicMock(hash=bytes.fromhex("aa" * 16)), None,
    )
    resp = _json.loads(result)
    assert resp["error"] == "target_offline"


def test_serve_relay_success():
    """/relay creates session and returns established status."""
    import json as _json
    import threading
    from unittest.mock import MagicMock

    from styrened.daemon import StyreneDaemon

    session = RelaySession(requester_hash="aaa", target_hash="bbb")

    daemon = MagicMock()
    daemon._relay_service = MagicMock()

    # Run event loop in background thread so run_coroutine_threadsafe works
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    daemon._event_loop = loop

    async def mock_create(requester_hash, target_hash, permanent):
        return session

    daemon._relay_service.create_session = mock_create
    daemon._direct_link_service = MagicMock()
    link_info = MagicMock()
    link_info.status = "active"
    daemon._direct_link_service.get_link.return_value = link_info
    daemon._datalink_identity_hex = StyreneDaemon._datalink_identity_hex.__get__(daemon)
    daemon._datalink_rl = MagicMock()
    daemon._datalink_rl.check.return_value = True
    daemon._datalink_rbac_role = MagicMock(return_value=10)  # PEER

    try:
        result = StyreneDaemon._serve_datalink_relay(
            daemon, "/relay",
            _json.dumps({"target_hash": "bbb"}).encode(),
            None, None, MagicMock(hash=bytes.fromhex("aa" * 16)), None,
        )
        resp = _json.loads(result)
        assert resp["status"] == "established"
        assert resp["target_hash"] == "bbb"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()


def test_serve_relay_error_propagation():
    """/relay returns relay error codes."""
    import json as _json
    import threading
    from unittest.mock import MagicMock

    from styrened.daemon import StyreneDaemon
    from styrened.models.relay import RelayDisabled

    daemon = MagicMock()
    daemon._relay_service = MagicMock()

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    daemon._event_loop = loop

    async def mock_create(requester_hash, target_hash, permanent):
        raise RelayDisabled("Relay is disabled")

    daemon._relay_service.create_session = mock_create
    daemon._direct_link_service = MagicMock()
    link_info = MagicMock()
    link_info.status = "active"
    daemon._direct_link_service.get_link.return_value = link_info
    daemon._datalink_identity_hex = StyreneDaemon._datalink_identity_hex.__get__(daemon)
    daemon._datalink_rl = MagicMock()
    daemon._datalink_rl.check.return_value = True
    daemon._datalink_rbac_role = MagicMock(return_value=10)  # PEER

    try:
        result = StyreneDaemon._serve_datalink_relay(
            daemon, "/relay",
            _json.dumps({"target_hash": "bbb"}).encode(),
            None, None, MagicMock(hash=bytes.fromhex("aa" * 16)), None,
        )
        resp = _json.loads(result)
        assert resp["error"] == "relay.disabled"
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()


# ---------------------------------------------------------------------------
# RBAC enforcement in RelayService
# ---------------------------------------------------------------------------


def _make_policy(
    default_role: Role = Role.PEER,
    roster: dict | None = None,
) -> RBACPolicy:
    """Helper to build an RBACPolicy for relay tests."""
    entries = {}
    if roster:
        for h, entry_data in roster.items():
            entries[h] = RosterEntry(
                identity_hash=h,
                role=entry_data.get("role", default_role),
                grants=frozenset(entry_data.get("grants", [])),
            )
    return RBACPolicy(default_role=default_role, roster=entries)


@pytest.mark.asyncio
async def test_rbac_relay_request_authorized():
    """PEER role has relay.request — session creation succeeds."""
    policy = _make_policy(default_role=Role.PEER)
    svc = RelayService(RelayConfig(enabled=True))
    svc.set_rbac_policy(policy)
    session = await svc.create_session("aaa", "bbb")
    assert session.requester_hash == "aaa"


@pytest.mark.asyncio
async def test_rbac_relay_request_unauthorized_none():
    """NONE role lacks relay.request — RelayUnauthorized raised."""
    policy = _make_policy(default_role=Role.NONE)
    svc = RelayService(RelayConfig(enabled=True))
    svc.set_rbac_policy(policy)
    with pytest.raises(RelayUnauthorized):
        await svc.create_session("aaa", "bbb")


@pytest.mark.asyncio
async def test_rbac_relay_request_unauthorized_blocked():
    """BLOCKED role — RelayUnauthorized raised."""
    policy = _make_policy(default_role=Role.PEER, roster={
        "aaa": {"role": Role.BLOCKED},
    })
    svc = RelayService(RelayConfig(enabled=True))
    svc.set_rbac_policy(policy)
    with pytest.raises(RelayUnauthorized):
        await svc.create_session("aaa", "bbb")


@pytest.mark.asyncio
async def test_rbac_permanent_requires_operator():
    """PEER role requesting permanent relay — RelayPermanentDenied."""
    policy = _make_policy(default_role=Role.PEER)
    svc = RelayService(RelayConfig(enabled=True, allow_permanent=True))
    svc.set_rbac_policy(policy)
    with pytest.raises(RelayPermanentDenied):
        await svc.create_session("aaa", "bbb", permanent=True)


@pytest.mark.asyncio
async def test_rbac_permanent_operator_allowed():
    """OPERATOR role can request permanent relay."""
    policy = _make_policy(default_role=Role.OPERATOR)
    svc = RelayService(RelayConfig(enabled=True, allow_permanent=True))
    svc.set_rbac_policy(policy)
    # Target also needs OPERATOR for accept_permanent — set target policy
    svc.set_target_rbac_policy(policy)
    session = await svc.create_session("aaa", "bbb", permanent=True)
    assert session.is_permanent is True


@pytest.mark.asyncio
async def test_rbac_target_reject():
    """Target has relay.reject for requester — RelayTargetRejected."""
    hub_policy = _make_policy(default_role=Role.PEER)
    target_policy = _make_policy(default_role=Role.PEER, roster={
        "aaa": {"role": Role.PEER, "grants": frozenset({Capability.RELAY_REJECT})},
    })
    svc = RelayService(RelayConfig(enabled=True))
    svc.set_rbac_policy(hub_policy)
    svc.set_target_rbac_policy(target_policy)
    with pytest.raises(RelayTargetRejected):
        await svc.create_session("aaa", "bbb")


@pytest.mark.asyncio
async def test_rbac_target_accept_default_peer():
    """Target at PEER role has relay.accept by default — relay succeeds."""
    hub_policy = _make_policy(default_role=Role.PEER)
    target_policy = _make_policy(default_role=Role.PEER)
    svc = RelayService(RelayConfig(enabled=True))
    svc.set_rbac_policy(hub_policy)
    svc.set_target_rbac_policy(target_policy)
    session = await svc.create_session("aaa", "bbb")
    assert session is not None


@pytest.mark.asyncio
async def test_rbac_permanent_target_consent_denied():
    """Target at PEER lacks relay.accept_permanent — RelayPermanentConsentDenied."""
    hub_policy = _make_policy(default_role=Role.OPERATOR)
    target_policy = _make_policy(default_role=Role.PEER)  # PEER lacks accept_permanent
    svc = RelayService(RelayConfig(enabled=True, allow_permanent=True))
    svc.set_rbac_policy(hub_policy)
    svc.set_target_rbac_policy(target_policy)
    with pytest.raises(RelayPermanentConsentDenied):
        await svc.create_session("aaa", "bbb", permanent=True)


@pytest.mark.asyncio
async def test_rbac_permanent_target_consent_granted():
    """Target at OPERATOR has relay.accept_permanent — permanent relay succeeds."""
    hub_policy = _make_policy(default_role=Role.OPERATOR)
    target_policy = _make_policy(default_role=Role.OPERATOR)
    svc = RelayService(RelayConfig(enabled=True, allow_permanent=True))
    svc.set_rbac_policy(hub_policy)
    svc.set_target_rbac_policy(target_policy)
    session = await svc.create_session("aaa", "bbb", permanent=True)
    assert session.is_permanent is True


@pytest.mark.asyncio
async def test_rbac_default_policy_allows_peer():
    """Default RBACPolicy (PEER) allows relay.request for create_session."""
    svc = RelayService(RelayConfig(enabled=True))
    # Default policy has default_role=PEER which grants relay.request
    session = await svc.create_session("aaa", "bbb")
    assert session.requester_hash == "aaa"


@pytest.mark.asyncio
async def test_rbac_default_policy_blocks_permanent():
    """Default RBACPolicy (PEER) denies relay.request_permanent."""
    svc = RelayService(RelayConfig(enabled=True, allow_permanent=True))
    with pytest.raises(RelayPermanentDenied):
        await svc.create_session("aaa", "bbb", permanent=True)
