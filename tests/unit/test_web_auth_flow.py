"""Unit tests for the full challenge-response authentication flow.

Tests the auth router endpoints using FastAPI TestClient with mock
RNS identity operations.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from styrened.web.auth import (
    ChallengeStore,
    SessionStore,
    create_auth_router,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


from styrened.models.rbac import RBACPolicy, Role, RosterEntry


@dataclass
class FakeAuthConfig:
    enabled: bool = True
    exempt_localhost: bool = True
    session_ttl: int = 86400


@dataclass
class FakeAPIConfig:
    auth: FakeAuthConfig = field(default_factory=FakeAuthConfig)


@dataclass
class FakeDaemonConfig:
    api: FakeAPIConfig = field(default_factory=FakeAPIConfig)
    rbac: RBACPolicy = field(default_factory=RBACPolicy)


def _make_fake_identity() -> tuple[bytes, str]:
    """Generate a fake 64-byte public key and its identity hash."""
    pub_bytes = os.urandom(64)
    identity_hash = hashlib.sha256(pub_bytes).digest()[:16].hex()
    return pub_bytes, identity_hash


def _create_test_app(
    rbac_policy: RBACPolicy | None = None,
) -> tuple[TestClient, ChallengeStore, SessionStore]:
    """Create a test app with auth router."""
    app = FastAPI()
    challenge_store = ChallengeStore()
    session_store = SessionStore()

    daemon = MagicMock()
    daemon.config = FakeDaemonConfig(
        rbac=rbac_policy or RBACPolicy(default_role=Role.MONITOR),
    )

    router = create_auth_router(daemon, challenge_store, session_store)
    app.include_router(router)

    return TestClient(app), challenge_store, session_store


# ---------------------------------------------------------------------------
# Challenge endpoint
# ---------------------------------------------------------------------------


class TestChallengeEndpoint:
    """Tests for POST /api/auth/challenge."""

    def test_challenge_success(self) -> None:
        """Valid identity gets a challenge nonce."""
        pub_bytes, identity_hash = _make_fake_identity()
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity_hash: RosterEntry(identity_hash=identity_hash, role=Role.MONITOR)},
        )
        client, _, _ = _create_test_app(rbac_policy=policy)

        resp = client.post("/api/auth/challenge", json={
            "identity_hash": identity_hash,
            "public_key": pub_bytes.hex(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "challenge" in data
        assert len(data["challenge"]) == 64  # 32 bytes hex
        assert data["expires_in"] == 60

    def test_challenge_unauthorized_identity(self) -> None:
        """Identity not in RBAC roster gets 403."""
        pub_bytes, identity_hash = _make_fake_identity()
        _, other_hash = _make_fake_identity()
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={other_hash: RosterEntry(identity_hash=other_hash, role=Role.MONITOR)},
        )
        client, _, _ = _create_test_app(rbac_policy=policy)

        resp = client.post("/api/auth/challenge", json={
            "identity_hash": identity_hash,
            "public_key": pub_bytes.hex(),
        })
        assert resp.status_code == 403

    def test_challenge_default_monitor_allows_all(self) -> None:
        """With default_role=MONITOR, any identity gets a challenge."""
        pub_bytes, identity_hash = _make_fake_identity()
        client, _, _ = _create_test_app()

        resp = client.post("/api/auth/challenge", json={
            "identity_hash": identity_hash,
            "public_key": pub_bytes.hex(),
        })
        assert resp.status_code == 200

    def test_challenge_empty_roster_default_none_denies_all(self) -> None:
        """Empty roster with default_role=NONE denies all."""
        pub_bytes, identity_hash = _make_fake_identity()
        policy = RBACPolicy(default_role=Role.NONE)
        client, _, _ = _create_test_app(rbac_policy=policy)

        resp = client.post("/api/auth/challenge", json={
            "identity_hash": identity_hash,
            "public_key": pub_bytes.hex(),
        })
        assert resp.status_code == 403

    def test_challenge_pubkey_hash_mismatch(self) -> None:
        """Public key that doesn't match identity_hash gets 400."""
        pub_bytes, _ = _make_fake_identity()
        wrong_hash = "a" * 32
        client, _, _ = _create_test_app()

        resp = client.post("/api/auth/challenge", json={
            "identity_hash": wrong_hash,
            "public_key": pub_bytes.hex(),
        })
        assert resp.status_code == 400

    def test_challenge_rate_limiting(self) -> None:
        """After 10 challenges, 429 is returned."""
        pub_bytes, identity_hash = _make_fake_identity()
        client, _, _ = _create_test_app()

        for _ in range(10):
            resp = client.post("/api/auth/challenge", json={
                "identity_hash": identity_hash,
                "public_key": pub_bytes.hex(),
            })
            assert resp.status_code == 200

        resp = client.post("/api/auth/challenge", json={
            "identity_hash": identity_hash,
            "public_key": pub_bytes.hex(),
        })
        assert resp.status_code == 429

    def test_challenge_invalid_identity_hash_format(self) -> None:
        """Identity hash with wrong length gets 422 (Pydantic validation)."""
        client, _, _ = _create_test_app()
        resp = client.post("/api/auth/challenge", json={
            "identity_hash": "tooshort",
            "public_key": "aa" * 64,
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Verify endpoint
# ---------------------------------------------------------------------------


class TestVerifyEndpoint:
    """Tests for POST /api/auth/verify."""

    def test_verify_success_with_mock_rns(self) -> None:
        """Full challenge-verify flow with mocked RNS signature verification."""
        pub_bytes, identity_hash = _make_fake_identity()
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity_hash: RosterEntry(identity_hash=identity_hash, role=Role.MONITOR)},
        )
        client, challenge_store, session_store = _create_test_app(rbac_policy=policy)

        # Step 1: Get challenge
        resp = client.post("/api/auth/challenge", json={
            "identity_hash": identity_hash,
            "public_key": pub_bytes.hex(),
        })
        assert resp.status_code == 200
        nonce_hex = resp.json()["challenge"]

        # Step 2: Verify with mocked signature
        fake_signature = os.urandom(64).hex()
        with patch("styrened.web.auth._verify_signature", return_value=True):
            resp = client.post("/api/auth/verify", json={
                "identity_hash": identity_hash,
                "challenge": nonce_hex,
                "signature": fake_signature,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["identity_hash"] == identity_hash
        assert data["expires_in"] == 86400

        # Verify session cookie is set
        assert "styrened_session" in resp.cookies

        # Verify token works
        session = session_store.validate(data["token"])
        assert session is not None
        assert session.identity_hash == identity_hash

    def test_verify_invalid_challenge(self) -> None:
        """Verify with unknown challenge gets 400."""
        client, _, _ = _create_test_app()
        resp = client.post("/api/auth/verify", json={
            "identity_hash": "a" * 32,
            "challenge": "b" * 64,
            "signature": "c" * 128,
        })
        assert resp.status_code == 400

    def test_verify_identity_mismatch(self) -> None:
        """Verify with different identity than challenge gets 400."""
        pub_bytes, identity_hash = _make_fake_identity()
        _, other_hash = _make_fake_identity()
        client, _, _ = _create_test_app()

        # Get challenge for identity_hash
        resp = client.post("/api/auth/challenge", json={
            "identity_hash": identity_hash,
            "public_key": pub_bytes.hex(),
        })
        nonce_hex = resp.json()["challenge"]

        # Try verify with other_hash
        resp = client.post("/api/auth/verify", json={
            "identity_hash": other_hash,
            "challenge": nonce_hex,
            "signature": "aa" * 64,
        })
        assert resp.status_code == 400

    def test_verify_bad_signature(self) -> None:
        """Invalid signature gets 401."""
        pub_bytes, identity_hash = _make_fake_identity()
        client, _, _ = _create_test_app()

        resp = client.post("/api/auth/challenge", json={
            "identity_hash": identity_hash,
            "public_key": pub_bytes.hex(),
        })
        nonce_hex = resp.json()["challenge"]

        with patch("styrened.web.auth._verify_signature", return_value=False):
            resp = client.post("/api/auth/verify", json={
                "identity_hash": identity_hash,
                "challenge": nonce_hex,
                "signature": "aa" * 64,
            })
        assert resp.status_code == 401

    def test_challenge_single_use(self) -> None:
        """Challenge can only be used once."""
        pub_bytes, identity_hash = _make_fake_identity()
        client, _, _ = _create_test_app()

        resp = client.post("/api/auth/challenge", json={
            "identity_hash": identity_hash,
            "public_key": pub_bytes.hex(),
        })
        nonce_hex = resp.json()["challenge"]

        # First verify (mocked success)
        with patch("styrened.web.auth._verify_signature", return_value=True):
            resp = client.post("/api/auth/verify", json={
                "identity_hash": identity_hash,
                "challenge": nonce_hex,
                "signature": "aa" * 64,
            })
        assert resp.status_code == 200

        # Second verify with same nonce fails
        with patch("styrened.web.auth._verify_signature", return_value=True):
            resp = client.post("/api/auth/verify", json={
                "identity_hash": identity_hash,
                "challenge": nonce_hex,
                "signature": "aa" * 64,
            })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


class TestStatusEndpoint:
    """Tests for GET /api/auth/status."""

    def test_status_unauthenticated(self) -> None:
        """Status returns auth_required but not authenticated."""
        client, _, _ = _create_test_app()
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["auth_required"] is True
        assert data["authenticated"] is False
        assert data["identity_hash"] is None

    def test_status_authenticated(self) -> None:
        """Status returns authenticated with identity when token provided."""
        pub_bytes, identity_hash = _make_fake_identity()
        policy = RBACPolicy(
            default_role=Role.NONE,
            roster={identity_hash: RosterEntry(identity_hash=identity_hash, role=Role.MONITOR)},
        )
        client, challenge_store, session_store = _create_test_app(rbac_policy=policy)

        # Create a session directly
        session = session_store.create(identity_hash)

        resp = client.get(
            "/api/auth/status",
            headers={"Authorization": f"Bearer {session.token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert data["identity_hash"] == identity_hash


# ---------------------------------------------------------------------------
# Logout endpoint
# ---------------------------------------------------------------------------


class TestLogoutEndpoint:
    """Tests for POST /api/auth/logout."""

    def test_logout_revokes_session(self) -> None:
        """Logout revokes the session token."""
        client, _, session_store = _create_test_app()
        session = session_store.create("test_identity_hash_000000000000")

        resp = client.post(
            "/api/auth/logout",
            headers={"Authorization": f"Bearer {session.token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["logged_out"] is True

        # Session should now be invalid
        assert session_store.validate(session.token) is None

    def test_logout_without_session(self) -> None:
        """Logout without a session still succeeds (idempotent)."""
        client, _, _ = _create_test_app()
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
