"""Tests for RBAC-gated Web API authentication.

The challenge() endpoint checks RBAC has_capability(identity, WEB_READ).
The verify() endpoint re-checks RBAC before issuing a session.
The AuthMiddleware enforces WEB_WRITE for mutating endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from styrened.models.rbac import (
    Capability,
    RBACPolicy,
    Role,
    RosterEntry,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeAuthConfig:
    enabled: bool = True
    exempt_localhost: bool = True
    session_ttl: int = 86400


@dataclass
class FakeAPIConfig:
    auth: FakeAuthConfig = field(default_factory=FakeAuthConfig)
    public_mode: bool = False


@dataclass
class FakeDaemonConfig:
    api: FakeAPIConfig = field(default_factory=FakeAPIConfig)
    rbac: RBACPolicy = field(default_factory=RBACPolicy)


def _make_daemon_config(rbac_policy=None):
    return FakeDaemonConfig(rbac=rbac_policy or RBACPolicy())


def _make_daemon(rbac_policy=None):
    daemon = MagicMock()
    daemon.config = _make_daemon_config(rbac_policy)
    return daemon


def _build_app(daemon):
    """Build a FastAPI app with auth router for TestClient testing."""
    from fastapi import FastAPI

    from styrened.web.auth import ChallengeStore, SessionStore, create_auth_router
    from styrened.web.auth_middleware import AuthMiddleware

    app = FastAPI()
    cs = ChallengeStore()
    ss = SessionStore()
    app.state.daemon = daemon
    app.state.session_store = ss

    router = create_auth_router(daemon, cs, ss)
    app.include_router(router)
    app.add_middleware(AuthMiddleware, session_store=ss)
    return app, cs, ss


# ---------------------------------------------------------------------------
# 1. Challenge endpoint RBAC gating (via TestClient)
# ---------------------------------------------------------------------------


class TestChallengeRBAC:
    """challenge() uses RBAC when daemon.config.rbac is set."""

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    def test_monitor_can_challenge(self, mock_verify):
        """MONITOR role has WEB_READ → challenge accepted."""
        from starlette.testclient import TestClient

        identity = "aa" * 16
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)},
        )
        daemon = _make_daemon(rbac_policy=policy)
        app, _, _ = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity, "public_key": "ab" * 64,
            })
        assert resp.status_code == 200

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    def test_peer_denied_challenge(self, mock_verify):
        """PEER role lacks WEB_READ → challenge rejected (403)."""
        from starlette.testclient import TestClient

        identity = "bb" * 16
        policy = RBACPolicy(default_role=Role.PEER)
        daemon = _make_daemon(rbac_policy=policy)
        app, _, _ = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity, "public_key": "ab" * 64,
            })
        assert resp.status_code == 403

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    def test_blocked_denied_challenge(self, mock_verify):
        """BLOCKED identity → challenge rejected (403)."""
        from starlette.testclient import TestClient

        identity = "cc" * 16
        policy = RBACPolicy(default_role=Role.PEER, blocked=["cc"])
        daemon = _make_daemon(rbac_policy=policy)
        app, _, _ = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity, "public_key": "ab" * 64,
            })
        assert resp.status_code == 403

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    def test_explicit_web_read_grant(self, mock_verify):
        """PEER with explicit web.read grant → challenge accepted."""
        from starlette.testclient import TestClient

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
        daemon = _make_daemon(rbac_policy=policy)
        app, _, _ = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity, "public_key": "ab" * 64,
            })
        assert resp.status_code == 200

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    def test_case_insensitive_identity_hash(self, mock_verify):
        """Identity hash case should not matter — roster keyed lowercase."""
        from starlette.testclient import TestClient

        identity_lower = "aa" * 16
        identity_upper = identity_lower.upper()
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity_lower: RosterEntry(identity_hash=identity_lower, role=Role.MONITOR)},
        )
        daemon = _make_daemon(rbac_policy=policy)
        app, _, _ = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity_upper, "public_key": "ab" * 64,
            })
        # Should work because challenge() lowercases the hash before RBAC check
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. Verify endpoint RBAC re-check
# ---------------------------------------------------------------------------


class TestVerifyRBAC:
    """verify() must re-check RBAC before issuing a session token."""

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    @patch("styrened.web.auth._verify_signature", return_value=True)
    def test_verify_recheck_blocks_revoked_identity(self, mock_sig, mock_verify):
        """If RBAC blocks identity between challenge and verify, verify must deny."""
        from starlette.testclient import TestClient

        identity = "aa" * 16
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)},
        )
        daemon = _make_daemon(rbac_policy=policy)
        app, cs, ss = _build_app(daemon)

        with TestClient(app) as client:
            # Step 1: challenge succeeds
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity, "public_key": "ab" * 64,
            })
            assert resp.status_code == 200
            nonce = resp.json()["challenge"]

            # Step 2: block the identity before verify
            policy.block(identity[:2])

            # Step 3: verify should fail (RBAC re-check)
            resp = client.post("/api/auth/verify", json={
                "identity_hash": identity,
                "challenge": nonce,
                "signature": "de" * 64,
            })
            assert resp.status_code == 403

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    @patch("styrened.web.auth._verify_signature", return_value=True)
    def test_verify_allows_when_rbac_passes(self, mock_sig, mock_verify):
        """Normal verify flow with RBAC active should succeed."""
        from starlette.testclient import TestClient

        identity = "bb" * 16
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)},
        )
        daemon = _make_daemon(rbac_policy=policy)
        app, cs, ss = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity, "public_key": "ab" * 64,
            })
            assert resp.status_code == 200
            nonce = resp.json()["challenge"]

            resp = client.post("/api/auth/verify", json={
                "identity_hash": identity,
                "challenge": nonce,
                "signature": "de" * 64,
            })
            assert resp.status_code == 200
            assert "token" in resp.json()

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    @patch("styrened.web.auth._verify_signature", return_value=True)
    def test_verify_no_rbac_uses_legacy(self, mock_sig, mock_verify):
        """Without RBAC, verify should not add an RBAC gate."""
        from starlette.testclient import TestClient

        identity = "cc" * 16
        daemon = _make_daemon(rbac_policy=RBACPolicy(default_role=Role.NONE, roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)}))
        app, cs, ss = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity, "public_key": "ab" * 64,
            })
            assert resp.status_code == 200
            nonce = resp.json()["challenge"]

            resp = client.post("/api/auth/verify", json={
                "identity_hash": identity,
                "challenge": nonce,
                "signature": "de" * 64,
            })
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 3. AuthMiddleware WEB_WRITE enforcement
# ---------------------------------------------------------------------------


class TestAuthMiddlewareRBAC:
    """AuthMiddleware gates mutating endpoints on WEB_WRITE when RBAC active."""

    def _get_session_token(self, client, identity, app, daemon):
        """Helper: do full challenge-verify flow, return session token."""
        with patch("styrened.web.auth._verify_identity_hash", return_value=True), \
             patch("styrened.web.auth._verify_signature", return_value=True):
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity, "public_key": "ab" * 64,
            })
            assert resp.status_code == 200
            nonce = resp.json()["challenge"]

            resp = client.post("/api/auth/verify", json={
                "identity_hash": identity,
                "challenge": nonce,
                "signature": "de" * 64,
            })
            assert resp.status_code == 200
            return resp.json()["token"]

    def test_monitor_can_read_with_session(self):
        """MONITOR with valid session can access GET endpoints."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from styrened.web.auth import ChallengeStore, SessionStore, create_auth_router
        from styrened.web.auth_middleware import AuthMiddleware

        identity = "aa" * 16
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)},
        )
        daemon = _make_daemon(rbac_policy=policy)
        app = FastAPI()
        cs = ChallengeStore()
        ss = SessionStore()
        app.state.daemon = daemon
        app.state.session_store = ss
        app.include_router(create_auth_router(daemon, cs, ss))

        # Add a dummy read endpoint
        @app.get("/api/test-read")
        async def test_read():
            return {"ok": True}

        app.add_middleware(AuthMiddleware, session_store=ss)

        with TestClient(app) as client:
            token = self._get_session_token(client, identity, app, daemon)
            resp = client.get("/api/test-read", cookies={"styrene_session": token})
            assert resp.status_code == 200

    def test_monitor_denied_write_endpoint(self):
        """MONITOR with session but no WEB_WRITE → denied on POST."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from styrened.web.auth import ChallengeStore, SessionStore, create_auth_router
        from styrened.web.auth_middleware import AuthMiddleware

        identity = "aa" * 16
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)},
        )
        daemon = _make_daemon(rbac_policy=policy)
        app = FastAPI()
        cs = ChallengeStore()
        ss = SessionStore()
        app.state.daemon = daemon
        app.state.session_store = ss
        app.include_router(create_auth_router(daemon, cs, ss))

        @app.post("/api/test-write")
        async def test_write():
            return {"ok": True}

        app.add_middleware(AuthMiddleware, session_store=ss)

        with TestClient(app) as client:
            token = self._get_session_token(client, identity, app, daemon)
            resp = client.post("/api/test-write", cookies={"styrene_session": token})
            assert resp.status_code == 403

    def test_operator_allowed_write_endpoint(self):
        """OPERATOR with session → allowed on POST (has WEB_WRITE)."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from styrened.web.auth import ChallengeStore, SessionStore, create_auth_router
        from styrened.web.auth_middleware import AuthMiddleware

        identity = "bb" * 16
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.OPERATOR)},
        )
        daemon = _make_daemon(rbac_policy=policy)
        app = FastAPI()
        cs = ChallengeStore()
        ss = SessionStore()
        app.state.daemon = daemon
        app.state.session_store = ss
        app.include_router(create_auth_router(daemon, cs, ss))

        @app.post("/api/test-write")
        async def test_write():
            return {"ok": True}

        app.add_middleware(AuthMiddleware, session_store=ss)

        with TestClient(app) as client:
            token = self._get_session_token(client, identity, app, daemon)
            resp = client.post("/api/test-write", cookies={"styrene_session": token})
            assert resp.status_code == 200

    def test_monitor_denied_write(self):
        """MONITOR role can read but not write (missing WEB_WRITE)."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from styrened.web.auth import ChallengeStore, SessionStore, create_auth_router
        from styrened.web.auth_middleware import AuthMiddleware

        identity = "cc" * 16
        daemon = _make_daemon(rbac_policy=RBACPolicy(default_role=Role.NONE, roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)}))
        app = FastAPI()
        cs = ChallengeStore()
        ss = SessionStore()
        app.state.daemon = daemon
        app.state.session_store = ss
        app.include_router(create_auth_router(daemon, cs, ss))

        @app.post("/api/test-write")
        async def test_write():
            return {"ok": True}

        app.add_middleware(AuthMiddleware, session_store=ss)

        with TestClient(app) as client:
            token = self._get_session_token(client, identity, app, daemon)
            resp = client.post("/api/test-write", cookies={"styrene_session": token})
            assert resp.status_code == 403

    def test_get_always_read_only(self):
        """GET requests only need WEB_READ (session), not WEB_WRITE."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from styrened.web.auth import ChallengeStore, SessionStore, create_auth_router
        from styrened.web.auth_middleware import AuthMiddleware

        identity = "dd" * 16
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)},
        )
        daemon = _make_daemon(rbac_policy=policy)
        app = FastAPI()
        cs = ChallengeStore()
        ss = SessionStore()
        app.state.daemon = daemon
        app.state.session_store = ss
        app.include_router(create_auth_router(daemon, cs, ss))

        @app.get("/api/test-data")
        async def test_data():
            return {"data": "hello"}

        app.add_middleware(AuthMiddleware, session_store=ss)

        with TestClient(app) as client:
            token = self._get_session_token(client, identity, app, daemon)
            resp = client.get("/api/test-data", cookies={"styrene_session": token})
            assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 4. RBAC roster-based challenge
# ---------------------------------------------------------------------------


class TestChallengeRBACRoster:
    """RBAC roster controls challenge access."""

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    def test_rostered_identity_accepted(self, mock_verify):
        """Identity in RBAC roster → accepted."""
        from starlette.testclient import TestClient

        identity = "aa" * 16
        daemon = _make_daemon(rbac_policy=RBACPolicy(default_role=Role.NONE, roster={identity: RosterEntry(identity_hash=identity, role=Role.MONITOR)}))
        app, _, _ = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity, "public_key": "ab" * 64,
            })
        assert resp.status_code == 200

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    def test_non_rostered_identity_denied(self, mock_verify):
        """Identity NOT in RBAC roster with default_role=NONE → denied."""
        from starlette.testclient import TestClient

        daemon = _make_daemon(rbac_policy=RBACPolicy(default_role=Role.NONE, roster={"aa" * 16: RosterEntry(identity_hash="aa" * 16, role=Role.MONITOR)}))
        app, _, _ = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": "bb" * 16, "public_key": "ab" * 64,
            })
        assert resp.status_code == 403

    @patch("styrened.web.auth._verify_identity_hash", return_value=True)
    def test_default_monitor_allows_all(self, mock_verify):
        """default_role=MONITOR → any identity accepted."""
        from starlette.testclient import TestClient

        daemon = _make_daemon(rbac_policy=RBACPolicy(default_role=Role.MONITOR))
        app, _, _ = _build_app(daemon)

        with TestClient(app) as client:
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": "ff" * 16, "public_key": "ab" * 64,
            })
        assert resp.status_code == 200
