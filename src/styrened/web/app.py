"""FastAPI application factory for the styrened web UI."""

from __future__ import annotations

import importlib.resources
import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from styrened.web.auth import ChallengeStore, SessionStore, create_auth_router
from styrened.web.auth_middleware import AuthMiddleware
from styrened.web.events import SSEBroadcaster
from styrened.web.middleware import PublicModeMiddleware
from styrened.web.routes import create_router

if TYPE_CHECKING:
    from styrened.daemon import StyreneDaemon

logger = logging.getLogger(__name__)


def create_app(daemon: StyreneDaemon) -> FastAPI:
    """Create the FastAPI application.

    Args:
        daemon: Running StyreneDaemon instance for data access.

    Returns:
        Configured FastAPI app.
    """
    app = FastAPI(title="Styrened Mesh Explorer", docs_url=None, redoc_url=None)

    # SSE broadcaster shared between routes and daemon callback
    broadcaster = SSEBroadcaster()
    app.state.broadcaster = broadcaster
    app.state.daemon = daemon

    # Auth stores (created regardless of config — dormant when disabled)
    challenge_store = ChallengeStore()
    session_store = SessionStore(
        _default_ttl=daemon.config.api.auth.session_ttl,
    )
    app.state.challenge_store = challenge_store
    app.state.session_store = session_store

    # Middleware order: AuthMiddleware runs before PublicModeMiddleware.
    # Starlette processes middleware in reverse add order (last-added runs first).
    app.add_middleware(PublicModeMiddleware)
    app.add_middleware(AuthMiddleware, session_store=session_store)

    # Auth routes (challenge/verify/status/logout)
    auth_router = create_auth_router(daemon, challenge_store, session_store)
    app.include_router(auth_router)

    # API routes
    router = create_router(daemon, broadcaster)
    app.include_router(router)

    # Prometheus metrics endpoint (optional)
    if daemon.config.api.metrics.enabled:
        try:
            from styrened.web.metrics import create_metrics_router, init_metrics

            init_metrics(daemon)
            app.include_router(create_metrics_router())
            logger.info("Prometheus metrics endpoint enabled at /metrics")
        except ImportError:
            logger.warning("Metrics enabled but prometheus_client not installed")

    # Static files (SPA frontend)
    static_dir = importlib.resources.files("styrened.web") / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
