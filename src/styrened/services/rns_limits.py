"""Network-safety rate limits for legacy Python Reticulum operations."""
from __future__ import annotations

import logging
import time

import RNS

logger = logging.getLogger(__name__)

MIN_PATH_REQUEST_INTERVAL: float = 300.0
MAX_PATH_REQUESTS_PER_WINDOW: int = 30
PATH_REQUEST_WINDOW: float = 3600.0

_last_path_requests: dict[str, float] = {}


def can_request_path(destination_hash: bytes) -> bool:
    """Return True when a Reticulum path request is within legacy safety limits."""
    global _last_path_requests

    now = time.time()
    key = destination_hash.hex()

    cutoff = now - PATH_REQUEST_WINDOW
    _last_path_requests = {
        hash_hex: requested_at
        for hash_hex, requested_at in _last_path_requests.items()
        if requested_at >= cutoff
    }

    last_request = _last_path_requests.get(key)
    if last_request is not None and now - last_request < MIN_PATH_REQUEST_INTERVAL:
        logger.debug(
            "[PATH] Suppressing repeated path request for %s... (%.1fs since last request)",
            key[:16],
            now - last_request,
        )
        return False

    if len(_last_path_requests) >= MAX_PATH_REQUESTS_PER_WINDOW:
        logger.warning(
            "[PATH] Suppressing path request: legacy Python daemon reached %d/hour "
            "path-request budget",
            MAX_PATH_REQUESTS_PER_WINDOW,
        )
        return False

    _last_path_requests[key] = now
    return True


def request_path_once(destination_hash: bytes, *, reason: str) -> bool:
    """Issue a bounded Reticulum path request for legacy Python code paths."""
    if not can_request_path(destination_hash):
        return False

    logger.info("[PATH] Requesting path for %s... (%s)", destination_hash.hex()[:16], reason)
    RNS.Transport.request_path(destination_hash)
    return True


def reset_path_request_budget() -> None:
    """Reset limiter state for tests."""
    _last_path_requests.clear()
