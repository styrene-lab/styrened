"""Authentication middleware for the styrened web API.

Reads daemon.config.api.auth on each request so runtime config changes
take effect immediately without restart.
"""

from __future__ import annotations

import ipaddress
import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from styrened.web.auth import SessionStore, extract_session

logger = logging.getLogger(__name__)

# Loopback addresses for localhost exemption
_LOOPBACK_V4 = ipaddress.ip_network("127.0.0.0/8")
_LOOPBACK_V6 = ipaddress.ip_address("::1")


def _is_loopback(client_host: str | None) -> bool:
    """Check if a client address is a loopback address."""
    if not client_host:
        return False
    try:
        addr = ipaddress.ip_address(client_host)
        if isinstance(addr, ipaddress.IPv4Address):
            return addr in _LOOPBACK_V4
        return addr == _LOOPBACK_V6
    except ValueError:
        return False


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce RNS identity-based authentication on API endpoints.

    Decision flow per request:
    1. Auth disabled → pass through
    2. Path starts with /api/auth/ → always exempt (auth endpoints)
    3. Not /api/ or /events → always exempt (static files, metrics)
    4. exempt_localhost + loopback client → pass through
    5. Valid session token → attach identity_hash to request.state
    6. Otherwise → 401
    """

    def __init__(self, app, session_store: SessionStore) -> None:  # noqa: ANN001
        super().__init__(app)
        self._session_store = session_store

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Only gate /api/ and /events paths
        if not (path.startswith("/api/") or path == "/events"):
            return await call_next(request)

        # Auth endpoints are always accessible (tightened to exact set)
        if path in {
            "/api/auth/challenge",
            "/api/auth/verify",
            "/api/auth/logout",
            "/api/auth/session",
            "/api/auth/status",
        }:
            return await call_next(request)

        # Read config per-request for live reload
        daemon = request.app.state.daemon
        auth_config = daemon.config.api.auth

        # Auth disabled → pass through
        if not auth_config.enabled:
            return await call_next(request)

        # Localhost exemption
        # NOTE: exempt_localhost checks request.client.host only (the TCP
        # peer address). It does NOT inspect X-Forwarded-For or similar
        # proxy headers. When running behind a reverse proxy, all requests
        # appear to originate from the proxy's address. Do NOT enable
        # exempt_localhost behind a reverse proxy without additional
        # configuration to verify the real client address.
        client_host = request.client.host if request.client else None
        if auth_config.exempt_localhost and _is_loopback(client_host):
            return await call_next(request)

        # Check for valid session
        session = extract_session(request, self._session_store)
        if session is not None:
            request.state.identity_hash = session.identity_hash

            # RBAC write gate: mutating methods require WEB_WRITE capability
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                from styrened.models.rbac import Capability

                if not daemon.config.rbac.has_capability(session.identity_hash, Capability.WEB_WRITE):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Write access denied (RBAC)"},
                    )

            return await call_next(request)

        # No valid session — reject
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
        )
