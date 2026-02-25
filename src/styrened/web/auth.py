"""RNS identity-based authentication for the styrened web API.

Implements Ed25519 challenge-response authentication using RNS identities.
A client proves possession of an authorized identity by signing a
server-issued nonce, then receives a session token for subsequent requests.

Auth flow:
    1. POST /api/auth/challenge — client sends identity_hash + public_key
    2. Server verifies identity is authorized, returns a random nonce
    3. Client signs the nonce with its Ed25519 key
    4. POST /api/auth/verify — client sends signature, gets session token
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from styrened.daemon import StyreneDaemon

logger = logging.getLogger(__name__)

# Session cookie name
SESSION_COOKIE = "styrened_session"

# Rate limit: max challenges per identity per minute
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 60  # seconds


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ChallengeRequest(BaseModel):
    """Request body for /api/auth/challenge."""

    identity_hash: str = Field(..., min_length=32, max_length=32, pattern=r"^[0-9a-fA-F]{32}$")
    public_key: str = Field(..., description="Hex-encoded 64-byte RNS public key (128 hex chars)")


class VerifyRequest(BaseModel):
    """Request body for /api/auth/verify."""

    identity_hash: str = Field(..., min_length=32, max_length=32, pattern=r"^[0-9a-fA-F]{32}$")
    challenge: str = Field(..., description="Hex-encoded nonce from challenge response")
    signature: str = Field(..., description="Hex-encoded Ed25519 signature of the nonce bytes")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PendingChallenge:
    """A pending challenge awaiting signature verification."""

    identity_hash: str
    public_key_bytes: bytes
    nonce: bytes
    created_at: float


@dataclass
class Session:
    """An authenticated session."""

    token: str
    identity_hash: str
    created_at: float
    expires_at: float


# ---------------------------------------------------------------------------
# ChallengeStore
# ---------------------------------------------------------------------------


@dataclass
class ChallengeStore:
    """In-memory store for pending authentication challenges.

    Challenges are single-use and expire after 60 seconds.
    Rate-limited to 10 challenges per identity per minute.
    """

    _challenges: dict[str, PendingChallenge] = field(default_factory=dict)
    _rate_limits: dict[str, list[float]] = field(default_factory=dict)
    _challenge_ttl: int = 60
    _max_rate_limit_entries: int = 1000

    def _cleanup_expired(self) -> None:
        """Remove expired challenges and stale rate limit entries."""
        now = time.time()
        expired = [k for k, v in self._challenges.items() if now - v.created_at > self._challenge_ttl]
        for k in expired:
            del self._challenges[k]

        # Prune rate limit entries with no recent activity
        stale = [k for k, v in self._rate_limits.items() if not v or now - v[-1] > _RATE_LIMIT_WINDOW]
        for k in stale:
            del self._rate_limits[k]

        # Hard cap: if still too many entries, drop oldest
        if len(self._rate_limits) > self._max_rate_limit_entries:
            by_recency = sorted(self._rate_limits.items(), key=lambda kv: kv[1][-1] if kv[1] else 0)
            to_drop = len(self._rate_limits) - self._max_rate_limit_entries
            for k, _ in by_recency[:to_drop]:
                del self._rate_limits[k]

    def _check_rate_limit(self, identity_hash: str) -> bool:
        """Check if identity is within rate limits.

        Returns True if allowed, False if rate-limited.
        """
        now = time.time()
        timestamps = self._rate_limits.get(identity_hash, [])
        # Prune old entries
        timestamps = [t for t in timestamps if now - t < _RATE_LIMIT_WINDOW]
        self._rate_limits[identity_hash] = timestamps
        return len(timestamps) < _RATE_LIMIT_MAX

    def _record_request(self, identity_hash: str) -> None:
        """Record a challenge request for rate limiting."""
        timestamps = self._rate_limits.setdefault(identity_hash, [])
        timestamps.append(time.time())

    def create(self, identity_hash: str, public_key_bytes: bytes) -> PendingChallenge | None:
        """Create a new challenge for the given identity.

        Returns None if rate-limited.
        """
        self._cleanup_expired()

        if not self._check_rate_limit(identity_hash):
            return None

        self._record_request(identity_hash)

        nonce = os.urandom(32)
        challenge = PendingChallenge(
            identity_hash=identity_hash,
            public_key_bytes=public_key_bytes,
            nonce=nonce,
            created_at=time.time(),
        )
        nonce_hex = nonce.hex()
        self._challenges[nonce_hex] = challenge
        return challenge

    def consume(self, nonce_hex: str) -> PendingChallenge | None:
        """Consume a challenge by nonce hex. Returns None if not found or expired."""
        self._cleanup_expired()
        return self._challenges.pop(nonce_hex, None)


# ---------------------------------------------------------------------------
# SessionStore
# ---------------------------------------------------------------------------


@dataclass
class SessionStore:
    """In-memory store for authenticated sessions.

    Sessions do not survive daemon restart — clients re-auth automatically.
    Expired sessions are cleaned up lazily on create/validate.
    """

    _sessions: dict[str, Session] = field(default_factory=dict)
    _default_ttl: int = 86400
    _max_sessions: int = 10000
    _last_cleanup: float = field(default_factory=time.time)
    _cleanup_interval: float = 300  # cleanup at most every 5 minutes

    def _cleanup_expired(self) -> None:
        """Remove expired sessions. Called lazily on create/validate."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        expired = [t for t, s in self._sessions.items() if now > s.expires_at]
        for t in expired:
            del self._sessions[t]

    def create(self, identity_hash: str, ttl: int | None = None) -> Session:
        """Create a new session for the given identity."""
        self._cleanup_expired()

        # Hard cap to prevent unbounded growth
        if len(self._sessions) >= self._max_sessions:
            # Evict oldest sessions
            by_created = sorted(self._sessions.items(), key=lambda kv: kv[1].created_at)
            to_evict = len(self._sessions) - self._max_sessions + 1
            for token, _ in by_created[:to_evict]:
                del self._sessions[token]

        token = os.urandom(32).hex()
        ttl = ttl or self._default_ttl
        now = time.time()
        session = Session(
            token=token,
            identity_hash=identity_hash,
            created_at=now,
            expires_at=now + ttl,
        )
        self._sessions[token] = session
        return session

    def validate(self, token: str) -> Session | None:
        """Validate a session token. Returns None if invalid or expired."""
        session = self._sessions.get(token)
        if session is None:
            return None
        if time.time() > session.expires_at:
            del self._sessions[token]
            return None
        return session

    def revoke(self, token: str) -> bool:
        """Revoke a session. Returns True if it existed."""
        return self._sessions.pop(token, None) is not None

    def revoke_all_for_identity(self, identity_hash: str) -> int:
        """Revoke all sessions for an identity. Returns count revoked."""
        to_remove = [t for t, s in self._sessions.items() if s.identity_hash == identity_hash]
        for t in to_remove:
            del self._sessions[t]
        return len(to_remove)


# ---------------------------------------------------------------------------
# Session extraction helper
# ---------------------------------------------------------------------------


def extract_session(request: Request, session_store: SessionStore) -> Session | None:
    """Extract and validate a session from a request.

    Checks in order:
    1. Authorization: Bearer <token> header
    2. styrened_session cookie
    3. ?token= query parameter (fallback for SSE EventSource)
    """
    # 1. Bearer token header
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return session_store.validate(token)

    # 2. Session cookie
    cookie_token = request.cookies.get(SESSION_COOKIE)
    if cookie_token:
        return session_store.validate(cookie_token)

    # 3. Query parameter (SSE EventSource fallback)
    query_token = request.query_params.get("token")
    if query_token:
        return session_store.validate(query_token)

    return None


# ---------------------------------------------------------------------------
# Identity verification
# ---------------------------------------------------------------------------


def _verify_identity_hash(public_key_hex: str, claimed_hash: str) -> bool:
    """Verify that a public key hashes to the claimed identity hash.

    RNS identity hash = SHA256(public_key_bytes)[:16] → 32 hex chars.
    """
    import hashlib

    try:
        pub_bytes = bytes.fromhex(public_key_hex)
    except ValueError:
        return False

    if len(pub_bytes) != 64:
        return False

    digest = hashlib.sha256(pub_bytes).digest()[:16]
    return digest.hex() == claimed_hash.lower()


def _verify_signature(public_key_hex: str, signature_hex: str, message: bytes) -> bool:
    """Verify an Ed25519 signature using RNS Identity.

    The public key is 64 bytes: X25519(32) || Ed25519(32).
    We use RNS.Identity to load and validate.
    """
    try:
        import RNS

        pub_bytes = bytes.fromhex(public_key_hex)
        sig_bytes = bytes.fromhex(signature_hex)

        if len(pub_bytes) != 64 or len(sig_bytes) != 64:
            return False

        identity = RNS.Identity(create_keys=False)
        identity.load_public_key(pub_bytes)
        return identity.validate(sig_bytes, message)
    except Exception:
        logger.debug("Signature verification failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Auth router
# ---------------------------------------------------------------------------


def create_auth_router(
    daemon: StyreneDaemon,
    challenge_store: ChallengeStore,
    session_store: SessionStore,
) -> APIRouter:
    """Create the authentication router.

    Routes:
        POST /api/auth/challenge  — request a nonce
        POST /api/auth/verify     — sign nonce, get session
        GET  /api/auth/status     — check auth state
        POST /api/auth/logout     — revoke session
    """
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/challenge")
    async def challenge(body: ChallengeRequest) -> JSONResponse:
        auth_config = daemon.config.api.auth

        # Check if identity is authorized
        if not auth_config.allow_unauthenticated:
            if not auth_config.authorized_identities:
                # Auth enabled but no identities configured — deny all
                return JSONResponse(
                    status_code=403,
                    content={"detail": "No authorized identities configured"},
                )
            if body.identity_hash.lower() not in {h.lower() for h in auth_config.authorized_identities}:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Identity not authorized"},
                )

        # Verify identity_hash matches public_key
        if not _verify_identity_hash(body.public_key, body.identity_hash):
            return JSONResponse(
                status_code=400,
                content={"detail": "Public key does not match identity hash"},
            )

        # Decode public key
        try:
            pub_bytes = bytes.fromhex(body.public_key)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid public key hex encoding"},
            )

        pending = challenge_store.create(body.identity_hash.lower(), pub_bytes)
        if pending is None:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limited — try again later"},
            )

        return JSONResponse(
            status_code=200,
            content={
                "challenge": pending.nonce.hex(),
                "expires_in": challenge_store._challenge_ttl,
            },
        )

    @router.post("/verify")
    async def verify(request: Request, body: VerifyRequest) -> JSONResponse:
        # Consume the challenge (single-use)
        pending = challenge_store.consume(body.challenge)
        if pending is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "Invalid or expired challenge"},
            )

        # Verify the identity matches
        if body.identity_hash.lower() != pending.identity_hash.lower():
            return JSONResponse(
                status_code=400,
                content={"detail": "Identity hash mismatch"},
            )

        # Verify the signature
        nonce_bytes = bytes.fromhex(body.challenge)
        if not _verify_signature(
            pending.public_key_bytes.hex(),
            body.signature,
            nonce_bytes,
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid signature"},
            )

        # Create session
        ttl = daemon.config.api.auth.session_ttl
        session = session_store.create(body.identity_hash.lower(), ttl=ttl)

        response = JSONResponse(
            status_code=200,
            content={
                "token": session.token,
                "expires_in": ttl,
                "identity_hash": session.identity_hash,
            },
        )
        is_https = request.url.scheme == "https"
        response.set_cookie(
            key=SESSION_COOKIE,
            value=session.token,
            max_age=ttl,
            httponly=True,
            samesite="strict",
            secure=is_https,
        )
        return response

    @router.get("/status")
    async def status(request: Request) -> JSONResponse:
        auth_config = daemon.config.api.auth
        session = extract_session(request, session_store)

        return JSONResponse(
            status_code=200,
            content={
                "auth_required": auth_config.enabled,
                "authenticated": session is not None,
                "identity_hash": session.identity_hash if session else None,
            },
        )

    @router.post("/logout")
    async def logout(request: Request) -> JSONResponse:
        session = extract_session(request, session_store)
        if session:
            session_store.revoke(session.token)

        response = JSONResponse(
            status_code=200,
            content={"logged_out": True},
        )
        response.delete_cookie(SESSION_COOKIE)
        return response

    return router
