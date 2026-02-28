"""Middleware for the styrened web API."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Paths blocked for ALL methods (including GET) in public mode.
# These expose private data or have outbound side effects.
_PRIVATE_PATH_PREFIXES = (
    "/api/conversations",
    "/api/messages/",
    "/api/contacts",
    "/api/fleet/",
)


class PublicModeMiddleware(BaseHTTPMiddleware):
    """Reject private-data endpoints and non-GET requests when public_mode is on.

    Reads daemon.config on each request so that runtime config changes
    (via IPC/RPC) take effect immediately without restart.

    Only gates /api/ paths. SSE (/events), metrics (/metrics), and
    static file serving are unaffected.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path.startswith("/api/"):
            # Auth endpoints must always be accessible (even in public mode)
            if path.startswith("/api/auth/"):
                return await call_next(request)

            daemon = request.app.state.daemon
            if daemon.config.api.public_mode:
                # Block private endpoints entirely (all methods)
                if any(path.startswith(p) for p in _PRIVATE_PATH_PREFIXES):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "This endpoint is not available in public mode."},
                    )
                # Block write methods on remaining /api/ paths
                if request.method not in {"GET", "HEAD", "OPTIONS"}:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "This node is in public read-only mode. "
                            "Write operations are not available via the web API."
                        },
                    )
        return await call_next(request)
