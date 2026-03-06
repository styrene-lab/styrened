"""Tests for RBAC-gated Web API authentication (Phase 4).

TDD: Tests written BEFORE implementation.

The challenge() endpoint must check RBAC when policy is set:
- RBAC active: has_capability(identity, WEB_READ) to issue a challenge
- RBAC inactive: preserve legacy (authorized_identities + allow_unauthenticated)
- BLOCKED role: denied at challenge time (never gets a session)

Daemon wiring: create_auth_router receives rbac_policy or daemon.config.rbac
is consulted directly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from styrened.models.rbac import (
    Capability,
    RBACPolicy,
    Role,
    RosterEntry,
)


# ---------------------------------------------------------------------------
# 1. Challenge endpoint RBAC gating
# ---------------------------------------------------------------------------


class TestChallengeRBAC:
    """challenge() uses RBAC when daemon.config.rbac is set."""

    def _make_daemon(self, rbac_policy=None, allow_unauthenticated=False, authorized_identities=None):
        daemon = MagicMock()
        daemon.config = MagicMock()
        daemon.config.rbac = rbac_policy
        daemon.config.api = MagicMock()
        daemon.config.api.auth = MagicMock()
        daemon.config.api.auth.enabled = True
        daemon.config.api.auth.allow_unauthenticated = allow_unauthenticated
        daemon.config.api.auth.authorized_identities = authorized_identities or set()
        daemon.config.api.auth.session_ttl = 86400
        return daemon

    @pytest.mark.asyncio
    async def test_monitor_can_challenge(self):
        """MONITOR role has WEB_READ → challenge accepted."""
        from styrened.web.auth import ChallengeRequest, ChallengeStore, SessionStore, create_auth_router

        identity = "aa" * 16
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)},
        )
        daemon = self._make_daemon(rbac_policy=policy)
        cs = ChallengeStore()
        ss = SessionStore()
        router = create_auth_router(daemon, cs, ss)

        # Find the challenge route handler
        challenge_fn = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/auth/challenge":
                challenge_fn = route.endpoint
                break
        assert challenge_fn is not None

        # Valid public key that hashes to identity — we need to mock _verify_identity_hash
        from unittest.mock import patch
        with patch("styrened.web.auth._verify_identity_hash", return_value=True):
            body = ChallengeRequest(identity_hash=identity, public_key="ab" * 64)
            response = await challenge_fn(body)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_peer_denied_challenge(self):
        """PEER role lacks WEB_READ → challenge rejected (403)."""
        from styrened.web.auth import ChallengeRequest, ChallengeStore, SessionStore, create_auth_router

        identity = "bb" * 16
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = self._make_daemon(rbac_policy=policy)
        cs = ChallengeStore()
        ss = SessionStore()
        router = create_auth_router(daemon, cs, ss)

        challenge_fn = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/auth/challenge":
                challenge_fn = route.endpoint
                break

        from unittest.mock import patch
        with patch("styrened.web.auth._verify_identity_hash", return_value=True):
            body = ChallengeRequest(identity_hash=identity, public_key="ab" * 64)
            response = await challenge_fn(body)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_blocked_denied_challenge(self):
        """BLOCKED identity → challenge rejected (403)."""
        from styrened.web.auth import ChallengeRequest, ChallengeStore, SessionStore, create_auth_router

        identity = "cc" * 16
        policy = RBACPolicy(default_role=Role.PEER, blocked=["cc"])
        daemon = self._make_daemon(rbac_policy=policy)
        cs = ChallengeStore()
        ss = SessionStore()
        router = create_auth_router(daemon, cs, ss)

        challenge_fn = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/auth/challenge":
                challenge_fn = route.endpoint
                break

        from unittest.mock import patch
        with patch("styrened.web.auth._verify_identity_hash", return_value=True):
            body = ChallengeRequest(identity_hash=identity, public_key="ab" * 64)
            response = await challenge_fn(body)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_explicit_web_read_grant(self):
        """PEER with explicit web.read grant → challenge accepted."""
        from styrened.web.auth import ChallengeRequest, ChallengeStore, SessionStore, create_auth_router

        identity = "dd" * 16
        policy = RBACPolicy(
            default_role=Role.PEER,
            roster={
                identity: RosterEntry(
                    identity_hash=identity,
                    role=Role.PEER,
                    grants=frozenset([Capability.WEB_READ]),
                ),
            },
        )
        daemon = self._make_daemon(rbac_policy=policy)
        cs = ChallengeStore()
        ss = SessionStore()
        router = create_auth_router(daemon, cs, ss)

        challenge_fn = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/auth/challenge":
                challenge_fn = route.endpoint
                break

        from unittest.mock import patch
        with patch("styrened.web.auth._verify_identity_hash", return_value=True):
            body = ChallengeRequest(identity_hash=identity, public_key="ab" * 64)
            response = await challenge_fn(body)

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2. Legacy mode (no RBAC)
# ---------------------------------------------------------------------------


class TestChallengeLegacy:
    """Legacy behavior preserved when config.rbac is None."""

    def _make_daemon(self, allow_unauthenticated=False, authorized_identities=None):
        daemon = MagicMock()
        daemon.config = MagicMock()
        daemon.config.rbac = None
        daemon.config.api = MagicMock()
        daemon.config.api.auth = MagicMock()
        daemon.config.api.auth.enabled = True
        daemon.config.api.auth.allow_unauthenticated = allow_unauthenticated
        daemon.config.api.auth.authorized_identities = authorized_identities or set()
        daemon.config.api.auth.session_ttl = 86400
        return daemon

    @pytest.mark.asyncio
    async def test_legacy_authorized_identity(self):
        """Identity in legacy whitelist → accepted."""
        from styrened.web.auth import ChallengeRequest, ChallengeStore, SessionStore, create_auth_router

        identity = "aa" * 16
        daemon = self._make_daemon(authorized_identities={identity})
        cs = ChallengeStore()
        ss = SessionStore()
        router = create_auth_router(daemon, cs, ss)

        challenge_fn = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/auth/challenge":
                challenge_fn = route.endpoint
                break

        from unittest.mock import patch
        with patch("styrened.web.auth._verify_identity_hash", return_value=True):
            body = ChallengeRequest(identity_hash=identity, public_key="ab" * 64)
            response = await challenge_fn(body)

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_legacy_unauthorized_identity(self):
        """Identity NOT in legacy whitelist → denied."""
        from styrened.web.auth import ChallengeRequest, ChallengeStore, SessionStore, create_auth_router

        daemon = self._make_daemon(authorized_identities={"aa" * 16})
        cs = ChallengeStore()
        ss = SessionStore()
        router = create_auth_router(daemon, cs, ss)

        challenge_fn = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/auth/challenge":
                challenge_fn = route.endpoint
                break

        from unittest.mock import patch
        with patch("styrened.web.auth._verify_identity_hash", return_value=True):
            body = ChallengeRequest(identity_hash="bb" * 16, public_key="ab" * 64)
            response = await challenge_fn(body)

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_legacy_allow_unauthenticated(self):
        """allow_unauthenticated=True → any identity accepted."""
        from styrened.web.auth import ChallengeRequest, ChallengeStore, SessionStore, create_auth_router

        daemon = self._make_daemon(allow_unauthenticated=True)
        cs = ChallengeStore()
        ss = SessionStore()
        router = create_auth_router(daemon, cs, ss)

        challenge_fn = None
        for route in router.routes:
            if hasattr(route, "path") and route.path == "/api/auth/challenge":
                challenge_fn = route.endpoint
                break

        from unittest.mock import patch
        with patch("styrened.web.auth._verify_identity_hash", return_value=True):
            body = ChallengeRequest(identity_hash="ff" * 16, public_key="ab" * 64)
            response = await challenge_fn(body)

        assert response.status_code == 200
