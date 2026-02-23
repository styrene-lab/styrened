"""Integration tests for PublicModeMiddleware via the real app factory.

These tests verify that the middleware stack assembled by create_app()
actually gates write operations when public_mode is enabled. This is
critical because the unit/integration tests for config endpoints build
their own FastAPI app and never call create_app(), so they don't test
the real middleware ordering.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from styrened.models.config import CoreConfig
from styrened.web.app import create_app


def _make_daemon(*, public_mode: bool = False) -> MagicMock:
    """Create a mock daemon with a real CoreConfig.

    Args:
        public_mode: Whether to enable public (read-only) mode.

    Returns:
        MagicMock configured with all attributes the web app requires.
    """
    daemon = MagicMock()
    daemon.config = CoreConfig()
    daemon.config.api.public_mode = public_mode
    daemon.config.api.metrics.enabled = False
    daemon._node_store = None
    daemon._conversation_service = None
    daemon._rpc_client = None
    daemon._operator_destination = None
    daemon._start_time = 1000000000.0
    daemon._contact_service = None
    daemon._path_snapshot = None
    return daemon


class TestPublicModeBlocksWrites:
    """Verify that create_app() applies PublicModeMiddleware correctly."""

    def test_put_config_returns_403_in_public_mode(self) -> None:
        """PUT /api/config must be rejected with 403 when public_mode=True."""
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.put(
            "/api/config",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        assert response.status_code == 403
        assert "read-only" in response.json()["detail"].lower()

    def test_post_auto_reply_returns_403_in_public_mode(self) -> None:
        """POST /api/auto-reply must be rejected with 403 when public_mode=True."""
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.post(
            "/api/auto-reply",
            json={"enabled": True},
        )
        assert response.status_code == 403
        assert "read-only" in response.json()["detail"].lower()

    def test_delete_conversation_returns_403_in_public_mode(self) -> None:
        """DELETE /api/conversations/<hash> must be rejected with 403."""
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.delete("/api/conversations/aabbccdd11223344")
        assert response.status_code == 403

    def test_post_announce_returns_403_in_public_mode(self) -> None:
        """POST /api/announce must be rejected with 403."""
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.post("/api/announce")
        assert response.status_code == 403


class TestPrivateModeAllowsWrites:
    """Verify that write operations pass through when public_mode=False."""

    def test_put_config_reaches_handler_in_private_mode(self) -> None:
        """PUT /api/config must NOT get 403 when public_mode=False.

        The request may fail for other reasons (e.g. config validation),
        but the middleware should not block it. We check that the status
        code is anything other than 403.
        """
        daemon = _make_daemon(public_mode=False)
        app = create_app(daemon)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.put(
            "/api/config",
            json={"chat": {"auto_reply_mode": "template"}},
        )
        # The route handler runs (may error for other reasons), but not 403
        assert response.status_code != 403

    def test_post_auto_reply_reaches_handler_in_private_mode(self) -> None:
        """POST /api/auto-reply must reach the handler when public_mode=False."""
        daemon = _make_daemon(public_mode=False)
        app = create_app(daemon)
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/auto-reply",
            json={"enabled": False},
        )
        assert response.status_code != 403


class TestReadOperationsUnaffected:
    """Verify that GET requests work regardless of public_mode."""

    def test_get_config_works_in_public_mode(self) -> None:
        """GET /api/config must succeed in public mode."""
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.get("/api/config")
        assert response.status_code == 200
        assert "config" in response.json()

    def test_get_mesh_status_works_in_public_mode(self) -> None:
        """GET /api/mesh/status must succeed in public mode."""
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.get("/api/mesh/status")
        assert response.status_code == 200

    def test_static_index_served_in_public_mode(self) -> None:
        """GET / must serve the SPA index.html even in public mode.

        Static files are mounted outside /api/ and should be completely
        unaffected by PublicModeMiddleware.
        """
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.get("/")
        assert response.status_code == 200
        # index.html is an HTML page
        assert "text/html" in response.headers.get("content-type", "")


class TestMiddlewareFiresBeforeRouteValidation:
    """Verify middleware rejects BEFORE pydantic/route validation runs.

    This is the key ordering test. If middleware is applied correctly,
    a write request with a malformed body should get 403 (from middleware)
    not 422 (from pydantic). This proves the middleware fires before the
    route handler even attempts to parse the request body.
    """

    def test_put_config_invalid_body_returns_403_not_422(self) -> None:
        """PUT /api/config with garbage JSON body gets 403 in public mode.

        If this returned 422, it would mean the route handler ran first
        and pydantic rejected the body -- the middleware was bypassed.
        """
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.put(
            "/api/config",
            content=b"this is not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 403

    def test_post_auto_reply_missing_required_field_returns_403_not_422(self) -> None:
        """POST /api/auto-reply with missing 'enabled' field gets 403.

        AutoReplyToggleRequest requires 'enabled'. Without middleware,
        pydantic would return 422 for the missing field.
        """
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.post(
            "/api/auto-reply",
            json={"message": "I am away"},  # missing required 'enabled'
        )
        assert response.status_code == 403

    def test_post_chat_invalid_peer_hash_returns_403_not_400(self) -> None:
        """POST /api/conversations/<bad_hash>/messages with invalid body gets 403.

        Without middleware, the route would reject the bad hash with 400
        or reject the missing body with 422. Middleware should reject first.
        """
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.post(
            "/api/conversations/ZZZZ/messages",
            json={},
        )
        assert response.status_code == 403

    def test_delete_with_invalid_path_returns_403_not_400(self) -> None:
        """DELETE /api/messages/0 gets 403, not 400 from route validation."""
        daemon = _make_daemon(public_mode=True)
        app = create_app(daemon)
        client = TestClient(app)

        response = client.delete("/api/messages/0")
        assert response.status_code == 403
