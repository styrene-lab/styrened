"""Tests for PublicModeMiddleware.

Validates that the middleware correctly gates write operations when
public_mode is enabled, allows reads, and responds to runtime toggling.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed (web extra)")

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from styrened.models.config import CoreConfig
from styrened.web.events import SSEBroadcaster
from styrened.web.middleware import PublicModeMiddleware
from styrened.web.routes import create_router


def _make_app(public_mode: bool = True) -> tuple[FastAPI, MagicMock]:
    """Create a FastAPI app with PublicModeMiddleware and a mock daemon."""
    config = CoreConfig()
    config.api.public_mode = public_mode

    daemon = MagicMock()
    daemon.config = config
    daemon._node_store = None
    daemon._conversation_service = None
    daemon._rpc_client = None
    daemon._operator_destination = None
    daemon._start_time = 1000000000.0
    daemon._contact_service = None
    daemon._path_snapshot = None

    app = FastAPI()
    app.state.daemon = daemon

    app.add_middleware(PublicModeMiddleware)

    broadcaster = SSEBroadcaster()
    app.state.broadcaster = broadcaster
    router = create_router(daemon, broadcaster)
    app.include_router(router)

    return app, daemon


class TestPublicModeBlocks:
    """Write operations should return 403 when public_mode=True."""

    @pytest.fixture(autouse=True)
    def setup(self):
        app, self.daemon = _make_app(public_mode=True)
        self.client = TestClient(app)

    def test_put_config_blocked(self) -> None:
        """PUT /api/config returns 403 in public mode."""
        response = self.client.put(
            "/api/config",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        assert response.status_code == 403
        assert "read-only" in response.json()["detail"].lower()

    def test_post_auto_reply_blocked(self) -> None:
        """POST /api/auto-reply returns 403 in public mode."""
        response = self.client.post(
            "/api/auto-reply",
            json={"enabled": True},
        )
        assert response.status_code == 403

    def test_post_announce_blocked(self) -> None:
        """POST /api/announce returns 403 in public mode."""
        response = self.client.post("/api/announce")
        assert response.status_code == 403

    def test_delete_conversation_blocked(self) -> None:
        """DELETE /api/conversations/{hash} returns 403 in public mode."""
        response = self.client.delete("/api/conversations/abcdef0123456789")
        assert response.status_code == 403

    def test_post_send_chat_blocked(self) -> None:
        """POST /api/conversations/{hash}/messages returns 403 in public mode."""
        response = self.client.post(
            "/api/conversations/abcdef0123456789/messages",
            json={"content": "hello"},
        )
        assert response.status_code == 403

    def test_put_contact_blocked(self) -> None:
        """PUT /api/contacts/{hash} returns 403 in public mode."""
        response = self.client.put(
            "/api/contacts/abcdef0123456789",
            json={"alias": "test"},
        )
        assert response.status_code == 403

    def test_post_fleet_exec_blocked(self) -> None:
        """POST /api/fleet/{dest}/exec returns 403 in public mode."""
        response = self.client.post(
            "/api/fleet/abcdef0123456789/exec",
            json={"command": "uptime"},
        )
        assert response.status_code == 403


class TestPublicModeAllows:
    """GET requests should work normally when public_mode=True."""

    @pytest.fixture(autouse=True)
    def setup(self):
        app, self.daemon = _make_app(public_mode=True)
        self.client = TestClient(app)

    def test_get_config_allowed(self) -> None:
        """GET /api/config is allowed in public mode."""
        response = self.client.get("/api/config")
        assert response.status_code == 200

    def test_get_mesh_devices_allowed(self) -> None:
        """GET /api/mesh/devices is allowed in public mode."""
        response = self.client.get("/api/mesh/devices")
        assert response.status_code == 200

    def test_get_mesh_status_allowed(self) -> None:
        """GET /api/mesh/status is allowed in public mode."""
        response = self.client.get("/api/mesh/status")
        assert response.status_code == 200

    def test_get_fleet_status_blocked(self) -> None:
        """GET /api/fleet/{dest}/status is blocked in public mode (private endpoint)."""
        response = self.client.get("/api/fleet/abcdef0123456789/status")
        assert response.status_code == 403
        assert "not available in public mode" in response.json()["detail"].lower()


class TestPublicModeDisabled:
    """Write operations should work normally when public_mode=False."""

    @pytest.fixture(autouse=True)
    def setup(self):
        app, self.daemon = _make_app(public_mode=False)
        self.client = TestClient(app)

    def test_post_announce_allowed(self) -> None:
        """POST /api/announce works when public_mode is off."""
        # Will return 503 because no destination, but not 403
        response = self.client.post("/api/announce")
        assert response.status_code != 403

    def test_post_auto_reply_allowed(self) -> None:
        """POST /api/auto-reply works when public_mode is off."""
        from unittest.mock import patch

        with patch("styrened.services.config.save_core_config"):
            response = self.client.post(
                "/api/auto-reply",
                json={"enabled": True},
            )
        assert response.status_code != 403


class TestPublicModeDynamic:
    """Toggling public_mode at runtime takes effect immediately."""

    def test_toggle_takes_effect_immediately(self) -> None:
        """Changing daemon.config.api.public_mode is reflected on next request."""
        app, daemon = _make_app(public_mode=False)
        client = TestClient(app)

        # Should work — public_mode is off
        response = client.post("/api/announce")
        assert response.status_code != 403

        # Enable public_mode at runtime
        daemon.config.api.public_mode = True

        # Should now be blocked
        response = client.post("/api/announce")
        assert response.status_code == 403

        # Disable again
        daemon.config.api.public_mode = False

        # Should work again
        response = client.post("/api/announce")
        assert response.status_code != 403


class TestPublicModeBypass:
    """Adversarial tests probing for middleware bypass vectors.

    These tests verify that the PublicModeMiddleware cannot be circumvented
    through path manipulation, method smuggling, or other evasion techniques.
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        app, self.daemon = _make_app(public_mode=True)
        self.client = TestClient(app)

    # -----------------------------------------------------------------
    # 1. Path traversal bypass
    # -----------------------------------------------------------------

    def test_path_traversal_dot_dot_still_blocked(self) -> None:
        """PUT /api/../api/config must still be blocked.

        Starlette normalizes path traversal sequences before they reach
        middleware, so the middleware sees /api/config and blocks it.
        """
        response = self.client.put(
            "/api/../api/config",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        assert response.status_code == 403
        assert "read-only" in response.json()["detail"].lower()

    def test_path_traversal_dot_still_blocked(self) -> None:
        """PUT /api/./config must still be blocked (dot is normalized)."""
        response = self.client.put(
            "/api/./config",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        assert response.status_code == 403

    def test_case_sensitivity_uppercase_api_no_route(self) -> None:
        """PUT /API/config bypasses the middleware prefix check but gets 404.

        The middleware checks startswith('/api/') which is case-sensitive.
        /API/config does NOT match, so the middleware does not block it.
        However, no route is registered at /API/config, so FastAPI returns
        404 (or 405). The key assertion: it must NOT return 200 (no data leak).
        """
        response = self.client.put(
            "/API/config",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        # Must not succeed — either 403 (blocked) or 404/405 (no route)
        assert response.status_code != 200
        assert response.status_code in {403, 404, 405}

    def test_case_sensitivity_mixed_case_no_route(self) -> None:
        """PUT /Api/config or /aPi/config should not reach any handler."""
        for path in ["/Api/config", "/aPi/config", "/ApI/config"]:
            response = self.client.put(
                path,
                json={"chat": {"auto_reply_mode": "template"}},
            )
            assert response.status_code != 200, f"{path} returned 200"
            assert response.status_code in {403, 404, 405}, (
                f"{path} returned unexpected {response.status_code}"
            )

    # -----------------------------------------------------------------
    # 2. Method smuggling
    # -----------------------------------------------------------------

    def test_patch_method_blocked(self) -> None:
        """PATCH is not in the allow-list and must be blocked."""
        response = self.client.patch(
            "/api/config",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        assert response.status_code == 403

    def test_delete_method_blocked(self) -> None:
        """DELETE to an API path must be blocked in public mode."""
        response = self.client.delete("/api/conversations/abcdef0123456789")
        assert response.status_code == 403

    def test_post_method_blocked(self) -> None:
        """POST to an API path must be blocked in public mode."""
        response = self.client.post("/api/announce")
        assert response.status_code == 403

    def test_head_method_allowed(self) -> None:
        """HEAD requests should pass through the middleware (read-only)."""
        response = self.client.head("/api/config")
        assert response.status_code != 403

    def test_options_method_allowed(self) -> None:
        """OPTIONS requests should pass through the middleware (CORS preflight)."""
        response = self.client.options("/api/config")
        assert response.status_code != 403

    # -----------------------------------------------------------------
    # 3. Trailing slash variance
    # -----------------------------------------------------------------

    def test_trailing_slash_put_config_blocked(self) -> None:
        """PUT /api/config/ (with trailing slash) must also be blocked.

        Both /api/config and /api/config/ start with /api/ so the
        middleware should catch both.
        """
        response = self.client.put(
            "/api/config/",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        # Must be blocked (403) or not found (404) — never 200
        assert response.status_code in {403, 404, 405}

    def test_trailing_slash_post_announce_blocked(self) -> None:
        """POST /api/announce/ must be blocked just like /api/announce."""
        response = self.client.post("/api/announce/")
        assert response.status_code in {403, 404}

    def test_trailing_slash_consistency(self) -> None:
        """Trailing-slash and non-trailing-slash produce same gate behavior."""
        r_no_slash = self.client.put(
            "/api/config",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        r_with_slash = self.client.put(
            "/api/config/",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        # Both must be denied — neither should return 200
        assert r_no_slash.status_code != 200
        assert r_with_slash.status_code != 200

    # -----------------------------------------------------------------
    # 4. Non-API paths with write methods (should be ungated)
    # -----------------------------------------------------------------

    def test_post_to_events_not_gated(self) -> None:
        """POST /events is not under /api/ so middleware should not block it.

        The route only accepts GET, so we expect 405 (Method Not Allowed),
        NOT 403 (which would indicate the middleware incorrectly gated it).
        """
        response = self.client.post("/events")
        assert response.status_code != 403
        assert response.status_code == 405

    def test_put_to_root_not_gated(self) -> None:
        """PUT / is not under /api/ and should not be gated.

        Expect 404 or 405 from routing, not 403 from middleware.
        """
        response = self.client.put("/")
        assert response.status_code != 403

    def test_post_to_arbitrary_non_api_path(self) -> None:
        """POST /metrics, POST /health — non-API paths are never gated."""
        for path in ["/metrics", "/health", "/favicon.ico"]:
            response = self.client.post(path)
            assert response.status_code != 403, (
                f"POST {path} returned 403 — middleware should not gate non-API paths"
            )

    # -----------------------------------------------------------------
    # 5. Query string injection (_method override)
    # -----------------------------------------------------------------

    def test_query_string_method_override_ignored(self) -> None:
        """PUT /api/config?_method=GET must still be blocked.

        The middleware checks request.method (the actual HTTP method),
        not any query parameter. Method override params must not bypass.
        """
        response = self.client.put(
            "/api/config?_method=GET",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        assert response.status_code == 403

    def test_query_string_method_override_x_http(self) -> None:
        """PUT with X-HTTP-Method-Override header must still be blocked.

        Some frameworks honor method override headers — ours must not.
        """
        response = self.client.put(
            "/api/config",
            json={"chat": {"auto_reply_mode": "template"}},
            headers={"X-HTTP-Method-Override": "GET"},
        )
        assert response.status_code == 403

    def test_query_string_method_override_x_method(self) -> None:
        """PUT with X-Method-Override header must still be blocked."""
        response = self.client.put(
            "/api/config",
            json={"chat": {"auto_reply_mode": "template"}},
            headers={"X-Method-Override": "GET"},
        )
        assert response.status_code == 403

    # -----------------------------------------------------------------
    # 6. Empty / malformed path edge cases
    # -----------------------------------------------------------------

    def test_post_to_api_bare_blocked(self) -> None:
        """POST /api/ (the prefix itself with trailing slash) must be blocked.

        /api/ starts with /api/, so the middleware should catch it even
        though no route is registered there.
        """
        response = self.client.post("/api/")
        assert response.status_code == 403

    def test_post_to_api_no_trailing_slash_not_gated(self) -> None:
        """POST /api (no trailing slash) does NOT match startswith('/api/').

        This is a known edge case: '/api' does NOT start with '/api/'
        so the middleware does not gate it. However, no route exists at
        /api so it should return 404 or 405 — never 200.
        """
        response = self.client.post("/api")
        # The middleware won't catch this (it doesn't start with /api/)
        # but no route is registered at /api, so it's 404/405
        assert response.status_code != 200
        assert response.status_code in {404, 405}

    def test_put_to_api_no_trailing_slash_not_gated(self) -> None:
        """PUT /api bypasses the middleware but has no matching route."""
        response = self.client.put("/api", json={"test": True})
        assert response.status_code != 200
        assert response.status_code in {404, 405}

    def test_double_slash_still_blocked(self) -> None:
        """POST /api//announce should still be blocked or produce no route.

        Double slashes may be normalized by the ASGI server. Either way,
        write access must not succeed.
        """
        response = self.client.post("/api//announce")
        # /api//announce starts with /api/ so middleware blocks it,
        # or it's a 404 because the route doesn't match.
        assert response.status_code != 200
        assert response.status_code in {403, 404}

    def test_encoded_slash_in_path(self) -> None:
        """PUT /api%2Fconfig — percent-encoded slash should not bypass.

        After URL decoding, /api%2Fconfig becomes /api/config. The
        middleware must still block it, or routing must reject it.
        """
        response = self.client.put(
            "/api%2Fconfig",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        # Must not succeed — blocked or no route
        assert response.status_code != 200


class TestPrivateEndpointsBlocked:
    """Private GET endpoints should return 403 when public_mode=True."""

    @pytest.fixture(autouse=True)
    def setup(self):
        app, self.daemon = _make_app(public_mode=True)
        self.client = TestClient(app)

    def test_get_conversations_blocked(self) -> None:
        """GET /api/conversations returns 403 in public mode."""
        response = self.client.get("/api/conversations")
        assert response.status_code == 403
        assert "not available in public mode" in response.json()["detail"].lower()

    def test_get_conversation_messages_blocked(self) -> None:
        """GET /api/conversations/{hash}/messages returns 403 in public mode."""
        response = self.client.get("/api/conversations/abcdef0123456789/messages")
        assert response.status_code == 403
        assert "not available in public mode" in response.json()["detail"].lower()

    def test_get_messages_search_blocked(self) -> None:
        """GET /api/messages/search?q=test returns 403 in public mode."""
        response = self.client.get("/api/messages/search?q=test")
        assert response.status_code == 403
        assert "not available in public mode" in response.json()["detail"].lower()

    def test_get_contacts_blocked(self) -> None:
        """GET /api/contacts returns 403 in public mode."""
        response = self.client.get("/api/contacts")
        assert response.status_code == 403
        assert "not available in public mode" in response.json()["detail"].lower()

    def test_get_contacts_resolve_blocked(self) -> None:
        """GET /api/contacts/resolve?name=foo returns 403 in public mode."""
        response = self.client.get("/api/contacts/resolve?name=foo")
        assert response.status_code == 403
        assert "not available in public mode" in response.json()["detail"].lower()

    def test_get_fleet_status_blocked(self) -> None:
        """GET /api/fleet/{dest}/status returns 403 in public mode."""
        response = self.client.get("/api/fleet/abcdef0123456789/status")
        assert response.status_code == 403
        assert "not available in public mode" in response.json()["detail"].lower()

    def test_post_to_private_endpoint_gets_private_message(self) -> None:
        """POST /api/conversations/{hash}/messages gets private-endpoint 403, not read-only 403."""
        response = self.client.post(
            "/api/conversations/abcdef0123456789/messages",
            json={"content": "hello"},
        )
        assert response.status_code == 403
        # Should get the private endpoint message, not the read-only message
        assert "not available in public mode" in response.json()["detail"].lower()

    def test_public_endpoints_still_allowed(self) -> None:
        """Public GET endpoints still work in public mode."""
        # /api/config
        response = self.client.get("/api/config")
        assert response.status_code == 200

        # /api/mesh/devices
        response = self.client.get("/api/mesh/devices")
        assert response.status_code == 200

        # /api/mesh/status
        response = self.client.get("/api/mesh/status")
        assert response.status_code == 200

        # /api/system/status
        response = self.client.get("/api/system/status")
        assert response.status_code == 200


class TestPrivateEndpointsWhenDisabled:
    """Private endpoints should work normally when public_mode=False."""

    @pytest.fixture(autouse=True)
    def setup(self):
        app, self.daemon = _make_app(public_mode=False)
        self.client = TestClient(app)

    def test_conversations_allowed_when_not_public(self) -> None:
        """GET /api/conversations works when public_mode=False (returns 503, no service)."""
        response = self.client.get("/api/conversations")
        # 503 because conversation service is None, not 403
        assert response.status_code == 503

    def test_contacts_allowed_when_not_public(self) -> None:
        """GET /api/contacts works when public_mode=False (returns 503, no service)."""
        response = self.client.get("/api/contacts")
        assert response.status_code == 503

    def test_fleet_status_allowed_when_not_public(self) -> None:
        """GET /api/fleet/{dest}/status works when public_mode=False (returns 503, no RPC)."""
        response = self.client.get("/api/fleet/abcdef0123456789/status")
        assert response.status_code == 503

    def test_messages_search_allowed_when_not_public(self) -> None:
        """GET /api/messages/search works when public_mode=False (returns 503, no service)."""
        response = self.client.get("/api/messages/search?q=test")
        assert response.status_code == 503
