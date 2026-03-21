"""Unit tests for web auth stores and identity verification.

Tests ChallengeStore, SessionStore, _verify_identity_hash, and extract_session.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed (web extra)")

import hashlib
import os
import time
from unittest.mock import MagicMock

import pytest

from styrened.web.auth import (
    ChallengeStore,
    SessionStore,
    _verify_identity_hash,
    extract_session,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_pubkey() -> tuple[bytes, str]:
    """Generate a random 64-byte public key and its RNS identity hash."""
    pub_bytes = os.urandom(64)
    identity_hash = hashlib.sha256(pub_bytes).digest()[:16].hex()
    return pub_bytes, identity_hash


# ---------------------------------------------------------------------------
# ChallengeStore
# ---------------------------------------------------------------------------


class TestChallengeStore:
    """Tests for ChallengeStore."""

    def test_create_returns_pending_challenge(self) -> None:
        """Creating a challenge returns a PendingChallenge with nonce."""
        store = ChallengeStore()
        pub_bytes, identity_hash = _make_fake_pubkey()

        pending = store.create(identity_hash, pub_bytes)
        assert pending is not None
        assert pending.identity_hash == identity_hash
        assert pending.public_key_bytes == pub_bytes
        assert len(pending.nonce) == 32

    def test_consume_returns_and_removes_challenge(self) -> None:
        """Consuming a challenge returns it once, then None."""
        store = ChallengeStore()
        pub_bytes, identity_hash = _make_fake_pubkey()

        pending = store.create(identity_hash, pub_bytes)
        nonce_hex = pending.nonce.hex()

        result = store.consume(nonce_hex)
        assert result is not None
        assert result.identity_hash == identity_hash

        # Second consume returns None (single-use)
        assert store.consume(nonce_hex) is None

    def test_consume_expired_returns_none(self) -> None:
        """Expired challenges are cleaned up and return None."""
        store = ChallengeStore(_challenge_ttl=0)
        pub_bytes, identity_hash = _make_fake_pubkey()

        pending = store.create(identity_hash, pub_bytes)
        nonce_hex = pending.nonce.hex()

        # Wait for expiry (TTL=0 means already expired)
        time.sleep(0.01)
        assert store.consume(nonce_hex) is None

    def test_consume_unknown_nonce_returns_none(self) -> None:
        """Consuming an unknown nonce returns None."""
        store = ChallengeStore()
        assert store.consume("deadbeef" * 8) is None

    def test_rate_limiting(self) -> None:
        """After 10 challenges in a minute, creation returns None."""
        store = ChallengeStore()
        pub_bytes, identity_hash = _make_fake_pubkey()

        for _ in range(10):
            result = store.create(identity_hash, pub_bytes)
            assert result is not None

        # 11th should be rate limited
        assert store.create(identity_hash, pub_bytes) is None

    def test_rate_limit_different_identities_independent(self) -> None:
        """Rate limiting is per-identity."""
        store = ChallengeStore()
        pub1, hash1 = _make_fake_pubkey()
        pub2, hash2 = _make_fake_pubkey()

        for _ in range(10):
            store.create(hash1, pub1)

        # hash1 is rate-limited
        assert store.create(hash1, pub1) is None
        # hash2 is not
        assert store.create(hash2, pub2) is not None


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


class TestSessionStore:
    """Tests for SessionStore."""

    def test_create_returns_session(self) -> None:
        """Creating a session returns a Session with token."""
        store = SessionStore()
        session = store.create("abcd1234" * 4)
        assert session is not None
        assert len(session.token) == 64  # 32 bytes hex
        assert session.identity_hash == "abcd1234" * 4

    def test_validate_valid_session(self) -> None:
        """A valid session can be validated."""
        store = SessionStore()
        session = store.create("abcd1234" * 4)
        result = store.validate(session.token)
        assert result is not None
        assert result.identity_hash == session.identity_hash

    def test_validate_expired_session(self) -> None:
        """An expired session returns None."""
        store = SessionStore(_default_ttl=0)
        session = store.create("abcd1234" * 4)
        time.sleep(0.01)
        assert store.validate(session.token) is None

    def test_validate_unknown_token(self) -> None:
        """An unknown token returns None."""
        store = SessionStore()
        assert store.validate("nonexistent") is None

    def test_revoke_session(self) -> None:
        """Revoking a session makes it invalid."""
        store = SessionStore()
        session = store.create("abcd1234" * 4)
        assert store.revoke(session.token) is True
        assert store.validate(session.token) is None
        # Second revoke returns False
        assert store.revoke(session.token) is False

    def test_revoke_all_for_identity(self) -> None:
        """Revoking all sessions for an identity removes them all."""
        store = SessionStore()
        identity = "abcd1234" * 4
        store.create(identity)
        store.create(identity)
        other = store.create("eeee1111" * 4)

        count = store.revoke_all_for_identity(identity)
        assert count == 2
        # Other identity's session still valid
        assert store.validate(other.token) is not None

    def test_create_with_custom_ttl(self) -> None:
        """Session can be created with custom TTL."""
        store = SessionStore()
        session = store.create("abcd1234" * 4, ttl=3600)
        assert session.expires_at - session.created_at == pytest.approx(3600, abs=1)


# ---------------------------------------------------------------------------
# _verify_identity_hash
# ---------------------------------------------------------------------------


class TestVerifyIdentityHash:
    """Tests for _verify_identity_hash."""

    def test_valid_hash(self) -> None:
        """Valid public key hashes to expected identity hash."""
        pub_bytes, identity_hash = _make_fake_pubkey()
        assert _verify_identity_hash(pub_bytes.hex(), identity_hash) is True

    def test_invalid_hash_mismatch(self) -> None:
        """Wrong identity hash is rejected."""
        pub_bytes, _ = _make_fake_pubkey()
        assert _verify_identity_hash(pub_bytes.hex(), "00" * 16) is False

    def test_invalid_key_too_short(self) -> None:
        """Key shorter than 64 bytes is rejected."""
        short_key = os.urandom(32).hex()
        assert _verify_identity_hash(short_key, "00" * 16) is False

    def test_invalid_hex_encoding(self) -> None:
        """Non-hex string is rejected."""
        assert _verify_identity_hash("not_hex_at_all", "00" * 16) is False

    def test_case_insensitive_hash(self) -> None:
        """Hash comparison is case-insensitive."""
        pub_bytes, identity_hash = _make_fake_pubkey()
        assert _verify_identity_hash(pub_bytes.hex(), identity_hash.upper()) is True


# ---------------------------------------------------------------------------
# extract_session
# ---------------------------------------------------------------------------


class TestExtractSession:
    """Tests for extract_session helper."""

    def _make_request(
        self,
        auth_header: str | None = None,
        cookie: str | None = None,
        query_token: str | None = None,
    ) -> MagicMock:
        """Create a mock request with optional auth sources."""
        request = MagicMock()
        request.headers = {}
        request.cookies = {}
        request.query_params = {}

        if auth_header:
            request.headers["authorization"] = auth_header
        if cookie:
            request.cookies["styrened_session"] = cookie
        if query_token:
            request.query_params["token"] = query_token

        return request

    def test_bearer_token(self) -> None:
        """Bearer token in header is used."""
        store = SessionStore()
        session = store.create("test_identity_hash_000000000000")
        request = self._make_request(auth_header=f"Bearer {session.token}")
        result = extract_session(request, store)
        assert result is not None
        assert result.token == session.token

    def test_cookie_token(self) -> None:
        """Cookie token is used when no Bearer header."""
        store = SessionStore()
        session = store.create("test_identity_hash_000000000000")
        request = self._make_request(cookie=session.token)
        result = extract_session(request, store)
        assert result is not None

    def test_query_param_token(self) -> None:
        """Query param token is used as last resort."""
        store = SessionStore()
        session = store.create("test_identity_hash_000000000000")
        request = self._make_request(query_token=session.token)
        result = extract_session(request, store)
        assert result is not None

    def test_bearer_takes_precedence_over_cookie(self) -> None:
        """Bearer token is preferred over cookie."""
        store = SessionStore()
        session1 = store.create("identity_one_0000000000000000")
        session2 = store.create("identity_two_0000000000000000")
        request = self._make_request(
            auth_header=f"Bearer {session1.token}",
            cookie=session2.token,
        )
        result = extract_session(request, store)
        assert result is not None
        assert result.identity_hash == "identity_one_0000000000000000"

    def test_no_token_returns_none(self) -> None:
        """No auth source returns None."""
        store = SessionStore()
        request = self._make_request()
        assert extract_session(request, store) is None

    def test_invalid_bearer_format(self) -> None:
        """Non-Bearer authorization header is ignored."""
        store = SessionStore()
        request = self._make_request(auth_header="Basic abc123")
        assert extract_session(request, store) is None


# ---------------------------------------------------------------------------
# Adversarial: memory safety and bounds
# ---------------------------------------------------------------------------


class TestSessionStoreMemorySafety:
    """Tests for SessionStore bounded memory behavior."""

    def test_session_cap_evicts_oldest(self) -> None:
        """SessionStore evicts oldest sessions when at capacity."""
        store = SessionStore(_max_sessions=5, _cleanup_interval=0)
        sessions = []
        for i in range(5):
            sessions.append(store.create(f"identity_{i:032d}"))

        # All 5 should be valid
        for s in sessions:
            assert store.validate(s.token) is not None

        # Create a 6th — should evict the oldest
        new_session = store.create("identity_new_00000000000000000")
        assert store.validate(new_session.token) is not None
        # Oldest should be gone
        assert store.validate(sessions[0].token) is None
        # Others still valid
        for s in sessions[1:]:
            assert store.validate(s.token) is not None

    def test_expired_sessions_cleaned_up(self) -> None:
        """Expired sessions are removed during cleanup."""
        store = SessionStore(_default_ttl=0, _cleanup_interval=0)
        s1 = store.create("identity_00000000000000000000000")
        time.sleep(0.01)
        # Trigger cleanup via create
        store.create("identity_11111111111111111111111")
        # Expired session should be gone
        assert store.validate(s1.token) is None


class TestChallengeStoreMemorySafety:
    """Tests for ChallengeStore bounded memory behavior."""

    def test_rate_limit_entries_pruned(self) -> None:
        """Stale rate limit entries are cleaned up."""
        store = ChallengeStore(_challenge_ttl=0, _max_rate_limit_entries=5)

        # Create challenges from many different identities
        for _i in range(10):
            pub, ihash = _make_fake_pubkey()
            store.create(ihash, pub)

        # After cleanup, rate limit entries should be bounded
        # (TTL=0 means challenges expire immediately, so entries become stale)
        time.sleep(0.01)
        store._cleanup_expired()
        assert len(store._rate_limits) <= 5
