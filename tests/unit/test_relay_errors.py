"""Tests for relay data models and error hierarchy. TDD: written before implementation."""
from __future__ import annotations


import time
from datetime import datetime

import pytest


class TestRelayErrors:
    """All 12 error types are distinct with unique error_codes inheriting from RelayError."""

    def test_all_error_types_are_distinct_classes(self):
        from styrened.models.relay import (
            RelayBridgeDenied,
            RelayByteLimitExceeded,
            RelayDisabled,
            RelayError,
            RelayEvicted,
            RelayIdleTimeout,
            RelayMaxPerIdentity,
            RelayMaxSessions,
            RelayPermanentConsentDenied,
            RelayPermanentDenied,
            RelayTargetOffline,
            RelayTargetRejected,
            RelayUnauthorized,
        )

        subclasses = [
            RelayDisabled,
            RelayMaxSessions,
            RelayMaxPerIdentity,
            RelayByteLimitExceeded,
            RelayIdleTimeout,
            RelayUnauthorized,
            RelayPermanentDenied,
            RelayTargetRejected,
            RelayTargetOffline,
            RelayPermanentConsentDenied,
            RelayEvicted,
            RelayBridgeDenied,
        ]
        assert len(subclasses) == 12
        # All distinct classes
        assert len(set(subclasses)) == 12

    def test_all_inherit_from_relay_error(self):
        from styrened.models.relay import (
            RelayBridgeDenied,
            RelayByteLimitExceeded,
            RelayDisabled,
            RelayError,
            RelayEvicted,
            RelayIdleTimeout,
            RelayMaxPerIdentity,
            RelayMaxSessions,
            RelayPermanentConsentDenied,
            RelayPermanentDenied,
            RelayTargetOffline,
            RelayTargetRejected,
            RelayUnauthorized,
        )

        for cls in [
            RelayDisabled, RelayMaxSessions, RelayMaxPerIdentity,
            RelayByteLimitExceeded, RelayIdleTimeout, RelayUnauthorized,
            RelayPermanentDenied, RelayTargetRejected, RelayTargetOffline,
            RelayPermanentConsentDenied, RelayEvicted, RelayBridgeDenied,
        ]:
            assert issubclass(cls, RelayError)
            assert issubclass(cls, Exception)

    def test_all_error_codes_unique(self):
        from styrened.models.relay import (
            RelayBridgeDenied,
            RelayByteLimitExceeded,
            RelayDisabled,
            RelayEvicted,
            RelayIdleTimeout,
            RelayMaxPerIdentity,
            RelayMaxSessions,
            RelayPermanentConsentDenied,
            RelayPermanentDenied,
            RelayTargetOffline,
            RelayTargetRejected,
            RelayUnauthorized,
        )

        classes = [
            RelayDisabled, RelayMaxSessions, RelayMaxPerIdentity,
            RelayByteLimitExceeded, RelayIdleTimeout, RelayUnauthorized,
            RelayPermanentDenied, RelayTargetRejected, RelayTargetOffline,
            RelayPermanentConsentDenied, RelayEvicted, RelayBridgeDenied,
        ]
        codes = [cls.error_code for cls in classes]
        assert len(codes) == 12
        assert len(set(codes)) == 12, f"Duplicate error_codes: {codes}"

    def test_error_code_is_string(self):
        from styrened.models.relay import RelayDisabled

        assert isinstance(RelayDisabled.error_code, str)

    def test_relay_error_is_catchable(self):
        from styrened.models.relay import RelayDisabled, RelayError

        with pytest.raises(RelayError):
            raise RelayDisabled("relay is off")

    def test_error_message_preserved(self):
        from styrened.models.relay import RelayMaxSessions

        err = RelayMaxSessions("limit reached")
        assert str(err) == "limit reached"


class TestRelayConfig:
    """RelayConfig defaults match spec."""

    def test_defaults(self):
        from styrened.models.relay import RelayConfig

        cfg = RelayConfig()
        assert cfg.enabled is False
        assert cfg.max_sessions == 16
        assert cfg.max_per_identity == 2
        assert cfg.max_bytes_per_session == 52428800
        assert cfg.idle_timeout == 900
        assert cfg.allow_permanent is False
        assert cfg.allowed_identities == []

    def test_custom_values(self):
        from styrened.models.relay import RelayConfig

        cfg = RelayConfig(
            enabled=True,
            max_sessions=8,
            max_per_identity=1,
            idle_timeout=300,
            allow_permanent=True,
            allowed_identities=["abc123"],
        )
        assert cfg.enabled is True
        assert cfg.max_sessions == 8
        assert cfg.max_per_identity == 1
        assert cfg.idle_timeout == 300
        assert cfg.allow_permanent is True
        assert cfg.allowed_identities == ["abc123"]

    def test_allowed_identities_is_independent_list(self):
        """Each instance should have its own list."""
        from styrened.models.relay import RelayConfig

        a = RelayConfig()
        b = RelayConfig()
        a.allowed_identities.append("x")
        assert b.allowed_identities == []


class TestRelaySession:
    """RelaySession creation and byte tracking."""

    def test_creation(self):
        from styrened.models.relay import RelaySession

        s = RelaySession(requester_hash="aaa", target_hash="bbb")
        assert s.requester_hash == "aaa"
        assert s.target_hash == "bbb"
        assert s.bytes_forwarded == 0
        assert s.is_permanent is False
        assert s.is_priority is False
        assert isinstance(s.created_at, datetime)
        assert isinstance(s.last_activity, datetime)

    def test_record_bytes(self):
        from styrened.models.relay import RelaySession

        s = RelaySession(requester_hash="aaa", target_hash="bbb")
        before = s.last_activity
        time.sleep(0.01)
        s.record_bytes(1024)
        assert s.bytes_forwarded == 1024
        assert s.last_activity > before

    def test_record_bytes_accumulates(self):
        from styrened.models.relay import RelaySession

        s = RelaySession(requester_hash="aaa", target_hash="bbb")
        s.record_bytes(100)
        s.record_bytes(200)
        assert s.bytes_forwarded == 300


class TestLinkType:
    """LinkType enum values."""

    def test_values(self):
        from styrened.models.relay import LinkType

        assert LinkType.DIRECT.value == "direct"
        assert LinkType.RELAYED.value == "relayed"

    def test_members(self):
        from styrened.models.relay import LinkType

        assert set(LinkType.__members__.keys()) == {"DIRECT", "RELAYED"}
