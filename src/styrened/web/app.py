"""FastAPI application factory for the styrened web UI."""

from __future__ import annotations

import importlib.resources
import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from styrened.web.events import SSEBroadcaster
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

    # API routes
    router = create_router(daemon, broadcaster)
    app.include_router(router)

    # Static files (SPA frontend)
    static_dir = importlib.resources.files("styrened.web") / "static"
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app
