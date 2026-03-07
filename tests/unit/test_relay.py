"""Unit tests for RelayService, relay config parsing, and config round-trip."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from styrened.models.relay import (
    RelayConfig,
    RelaySession,
    RelayDisabled,
    RelayMaxSessions,
    RelayMaxPerIdentity,
    RelayByteLimitExceeded,
    RelayIdleTimeout,
    RelayTargetOffline,
    RelayEvicted,
)
from styrened.services.relay import RelayService


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
    svc = RelayService(cfg)
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
    svc = RelayService(cfg)
    s1 = await svc.create_session("a1", "b1")
    s1.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    s2 = await svc.create_session("a2", "b2", priority=True)
    s2.created_at = datetime(2021, 1, 1, tzinfo=timezone.utc)

    # Now at cap. New priority request should evict s1 (oldest non-priority).
    s3 = await svc.create_session("a3", "b3", priority=True)
    assert id(s1) not in svc._sessions
    assert id(s3) in svc._sessions


@pytest.mark.asyncio
async def test_lru_eviction_all_priority():
    """All priority sessions — no evictable, raises RelayMaxSessions."""
    cfg = RelayConfig(enabled=True, max_sessions=2)
    svc = RelayService(cfg)
    s1 = await svc.create_session("a1", "b1", priority=True)
    s2 = await svc.create_session("a2", "b2", priority=True)
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
    svc = RelayService(cfg)
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
    session.last_activity = datetime.now(timezone.utc) - timedelta(seconds=10)
    await svc.idle_check()
    assert sid not in svc._sessions


@pytest.mark.asyncio
async def test_idle_timeout_permanent_exempt():
    """Permanent sessions are exempt from idle timeout."""
    cfg = RelayConfig(enabled=True, idle_timeout=5, allow_permanent=True)
    svc = RelayService(cfg)
    session = await svc.create_session("aaa", "bbb", permanent=True)
    sid = id(session)
    session.last_activity = datetime.now(timezone.utc) - timedelta(seconds=1800)
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
    from styrened.services.config import load_core_config
    from io import StringIO
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
    from styrened.models.config import CoreConfig
    from styrened.services.config import _serialize_config
    import yaml

    config = CoreConfig()
    config.relay = RelayConfig(enabled=True, max_sessions=32)
    serialized = _serialize_config(config)
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
