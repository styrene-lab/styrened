"""Unit tests for AuthMiddleware.

Tests authentication enforcement, localhost exemption, path exemptions,
and disabled-auth passthrough using FastAPI TestClient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from styrened.web.auth import SessionStore
from styrened.web.auth_middleware import AuthMiddleware

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakeAuthConfig:
    """Minimal auth config for testing."""

    enabled: bool = False
    authorized_identities: set[str] = field(default_factory=set)
    allow_unauthenticated: bool = False
    exempt_localhost: bool = True
    session_ttl: int = 86400


@dataclass
class FakeAPIConfig:
    """Minimal API config for testing."""

    auth: FakeAuthConfig = field(default_factory=FakeAuthConfig)
    public_mode: bool = False


@dataclass
class FakeDaemonConfig:
    """Minimal daemon config for testing."""

    api: FakeAPIConfig = field(default_factory=FakeAPIConfig)


def _create_app(
    auth_enabled: bool = False,
    exempt_localhost: bool = True,
    session_store: SessionStore | None = None,
) -> tuple[FastAPI, SessionStore]:
    """Create a minimal FastAPI app with AuthMiddleware."""
    app = FastAPI()
    store = session_store or SessionStore()

    daemon = MagicMock()
    daemon.config = FakeDaemonConfig(
        api=FakeAPIConfig(
            auth=FakeAuthConfig(
                enabled=auth_enabled,
                exempt_localhost=exempt_localhost,
            ),
        ),
    )
    app.state.daemon = daemon

    app.add_middleware(AuthMiddleware, session_store=store)

    @app.get("/api/devices")
    async def devices():
        return {"devices": []}

    @app.get("/api/auth/status")
    async def auth_status():
        return {"ok": True}

    @app.get("/events")
    async def events():
        return {"events": []}

    @app.get("/static/index.html")
    async def static_page():
        return {"page": "index"}

    return app, store


# ---------------------------------------------------------------------------
# Tests: Auth disabled
# ---------------------------------------------------------------------------


class TestAuthDisabled:
    """When auth is disabled, all requests pass through."""

    def test_api_accessible_without_token(self) -> None:
        """API endpoints accessible without authentication."""
        app, _ = _create_app(auth_enabled=False)
        client = TestClient(app)
        resp = client.get("/api/devices")
        assert resp.status_code == 200

    def test_events_accessible_without_token(self) -> None:
        """SSE endpoint accessible without authentication."""
        app, _ = _create_app(auth_enabled=False)
        client = TestClient(app)
        resp = client.get("/events")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: Auth enabled
# ---------------------------------------------------------------------------


class TestAuthEnabled:
    """When auth is enabled, unauthenticated requests are rejected."""

    def test_api_requires_auth(self) -> None:
        """API requests without token get 401."""
        app, _ = _create_app(auth_enabled=True, exempt_localhost=False)
        client = TestClient(app)
        resp = client.get("/api/devices")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication required"

    def test_events_requires_auth(self) -> None:
        """SSE endpoint requires auth when enabled."""
        app, _ = _create_app(auth_enabled=True, exempt_localhost=False)
        client = TestClient(app)
        resp = client.get("/events")
        assert resp.status_code == 401

    def test_bearer_token_allows_access(self) -> None:
        """Valid bearer token grants access."""
        store = SessionStore()
        session = store.create("test_identity_hash_000000000000")
        app, _ = _create_app(auth_enabled=True, exempt_localhost=False, session_store=store)
        client = TestClient(app)
        resp = client.get(
            "/api/devices",
            headers={"Authorization": f"Bearer {session.token}"},
        )
        assert resp.status_code == 200

    def test_cookie_token_allows_access(self) -> None:
        """Valid cookie token grants access."""
        store = SessionStore()
        session = store.create("test_identity_hash_000000000000")
        app, _ = _create_app(auth_enabled=True, exempt_localhost=False, session_store=store)
        client = TestClient(app)
        resp = client.get(
            "/api/devices",
            cookies={"styrened_session": session.token},
        )
        assert resp.status_code == 200

    def test_query_token_allows_access(self) -> None:
        """Valid query param token grants access (SSE fallback)."""
        store = SessionStore()
        session = store.create("test_identity_hash_000000000000")
        app, _ = _create_app(auth_enabled=True, exempt_localhost=False, session_store=store)
        client = TestClient(app)
        resp = client.get(f"/events?token={session.token}")
        assert resp.status_code == 200

    def test_invalid_token_rejected(self) -> None:
        """Invalid token gets 401."""
        app, _ = _create_app(auth_enabled=True, exempt_localhost=False)
        client = TestClient(app)
        resp = client.get(
            "/api/devices",
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert resp.status_code == 401

    def test_expired_token_rejected(self) -> None:
        """Expired token gets 401."""
        import time

        store = SessionStore(_default_ttl=0)
        session = store.create("test_identity_hash_000000000000")
        time.sleep(0.01)

        app, _ = _create_app(auth_enabled=True, exempt_localhost=False, session_store=store)
        client = TestClient(app)
        resp = client.get(
            "/api/devices",
            headers={"Authorization": f"Bearer {session.token}"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Path exemptions
# ---------------------------------------------------------------------------


class TestPathExemptions:
    """Certain paths are always exempt from auth."""

    def test_auth_endpoints_always_exempt(self) -> None:
        """/api/auth/* paths bypass authentication."""
        app, _ = _create_app(auth_enabled=True, exempt_localhost=False)
        client = TestClient(app)
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200

    def test_static_files_always_exempt(self) -> None:
        """Non-API paths bypass authentication."""
        app, _ = _create_app(auth_enabled=True, exempt_localhost=False)
        client = TestClient(app)
        resp = client.get("/static/index.html")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests: Localhost exemption
# ---------------------------------------------------------------------------


class TestLocalhostExemption:
    """When exempt_localhost is true, loopback requests bypass auth."""

    def test_localhost_exempt_by_default(self) -> None:
        """Localhost requests pass through when exempt_localhost=True.

        Note: TestClient connects via 'testclient' which is not loopback.
        This test documents the behavior — real localhost exemption works
        in production with actual loopback connections.
        """
        # TestClient doesn't use real loopback, so this just verifies
        # the middleware doesn't crash with exempt_localhost enabled
        app, _ = _create_app(auth_enabled=True, exempt_localhost=True)
        client = TestClient(app)
        # TestClient's client host is 'testclient', not 127.0.0.1,
        # so this should still require auth
        resp = client.get("/api/devices")
        assert resp.status_code == 401

    def test_localhost_not_exempt_when_disabled(self) -> None:
        """When exempt_localhost=False, localhost requests need auth."""
        app, _ = _create_app(auth_enabled=True, exempt_localhost=False)
        client = TestClient(app)
        resp = client.get("/api/devices")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: Adversarial scenarios
# ---------------------------------------------------------------------------


class TestLoopbackVerification:
    """Unit tests for the _is_loopback helper."""

    def test_ipv4_loopback(self) -> None:
        """127.0.0.1 is loopback."""
        from styrened.web.auth_middleware import _is_loopback
        assert _is_loopback("127.0.0.1") is True

    def test_ipv4_loopback_range(self) -> None:
        """127.x.x.x range is loopback."""
        from styrened.web.auth_middleware import _is_loopback
        assert _is_loopback("127.255.255.255") is True

    def test_ipv6_loopback(self) -> None:
        """::1 is loopback."""
        from styrened.web.auth_middleware import _is_loopback
        assert _is_loopback("::1") is True

    def test_non_loopback_ipv4(self) -> None:
        """192.168.1.1 is not loopback."""
        from styrened.web.auth_middleware import _is_loopback
        assert _is_loopback("192.168.1.1") is False

    def test_non_loopback_ipv6(self) -> None:
        """fe80::1 is not loopback."""
        from styrened.web.auth_middleware import _is_loopback
        assert _is_loopback("fe80::1") is False

    def test_none_client(self) -> None:
        """None client host is not loopback."""
        from styrened.web.auth_middleware import _is_loopback
        assert _is_loopback(None) is False

    def test_invalid_address(self) -> None:
        """Invalid IP string is not loopback."""
        from styrened.web.auth_middleware import _is_loopback
        assert _is_loopback("not-an-ip") is False

    def test_testclient_host_not_loopback(self) -> None:
        """Starlette TestClient host 'testclient' is not loopback."""
        from styrened.web.auth_middleware import _is_loopback
        assert _is_loopback("testclient") is False
