"""Styrene HTTP API for headless mode.

Provides REST API for remote TUI access and integration with external tools.

Endpoints:
    GET  /api/mesh/devices      - List all discovered devices
    GET  /api/mesh/styrene      - List Styrene nodes only
    GET  /api/mesh/rnodes       - List RNodes only
    GET  /api/status            - Service status
    GET  /api/config            - Configuration (sanitized)
    GET  /health                - Health check
"""
from __future__ import annotations

from typing import Any

from styrened.tui.models.config import StyreneConfig


def create_app(config: StyreneConfig) -> Any:
    """Create FastAPI application.

    Args:
        config: Application configuration.

    Returns:
        FastAPI application instance.
    """
    try:
        from fastapi import FastAPI  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError("API server requires: pip install fastapi") from e

    fastapi_app = FastAPI(
        title="Styrene API",
        description="Mesh fleet management and discovery",
        version="0.1.0",
    )

    @fastapi_app.get("/health")  # type: ignore[untyped-decorator]
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    @fastapi_app.get("/api/status")  # type: ignore[untyped-decorator]
    async def get_status() -> dict[str, Any]:
        """Get service status."""
        from styrened.tui.services.app_lifecycle import get_service_status

        return get_service_status()

    @fastapi_app.get("/api/config")  # type: ignore[untyped-decorator]
    async def get_config() -> dict[str, Any]:
        """Get sanitized configuration."""
        return {
            "mode": config.reticulum.mode.value,
            "transport_enabled": config.reticulum.resolve_transport_enabled(),
            "interfaces": {
                "auto": config.reticulum.interfaces.auto,
                "server_enabled": config.reticulum.interfaces.server.enabled,
                "peer_count": len(config.reticulum.interfaces.peers),
            },
            "api_enabled": config.api.enabled,
        }

    @fastapi_app.get("/api/mesh/devices")  # type: ignore[untyped-decorator]
    async def list_devices() -> list[dict[str, Any]]:
        """Get all discovered mesh devices."""
        from styrened.tui.services.reticulum import discover_devices

        devices = discover_devices()
        return [
            {
                "identity": device.identity_hash,
                "identity_short": device.identity_short,
                "name": device.name,
                "type": device.device_type.value,
                "status": device.status.value,
                "last_announce": device.last_announce,
                "last_seen_display": device.last_seen_display,
                "announce_count": device.announce_count,
                "capabilities": device.capabilities,
                "version": device.version,
            }
            for device in devices
        ]

    @fastapi_app.get("/api/mesh/styrene")  # type: ignore[untyped-decorator]
    async def list_styrene_nodes() -> list[dict[str, Any]]:
        """Get only Styrene nodes."""
        from styrened.tui.services.reticulum import get_styrene_devices

        devices = get_styrene_devices()
        return [
            {
                "identity": device.identity_hash,
                "identity_short": device.identity_short,
                "name": device.name,
                "type": device.device_type.value,
                "status": device.status.value,
                "last_announce": device.last_announce,
                "last_seen_display": device.last_seen_display,
                "announce_count": device.announce_count,
                "capabilities": device.capabilities,
                "version": device.version,
            }
            for device in devices
        ]

    @fastapi_app.get("/api/mesh/rnodes")  # type: ignore[untyped-decorator]
    async def list_rnodes() -> list[dict[str, Any]]:
        """Get only RNodes."""
        from styrened.tui.services.reticulum import get_rnodes

        devices = get_rnodes()
        return [
            {
                "identity": device.identity_hash,
                "identity_short": device.identity_short,
                "name": device.name,
                "type": device.device_type.value,
                "status": device.status.value,
                "last_announce": device.last_announce,
                "last_seen_display": device.last_seen_display,
                "announce_count": device.announce_count,
            }
            for device in devices
        ]

    return fastapi_app
