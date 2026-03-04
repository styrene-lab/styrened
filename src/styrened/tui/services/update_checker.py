"""PyPI update checker for styrened.

Checks for newer versions on PyPI at every TUI launch. Runs as a
background worker with a short timeout so it never blocks startup.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import NamedTuple

logger = logging.getLogger(__name__)

PYPI_URL = "https://pypi.org/pypi/styrened/json"
REQUEST_TIMEOUT = 3  # seconds


class UpdateInfo(NamedTuple):
    """Result of an update check."""

    current: str
    latest: str
    update_available: bool


def check_for_update(current_version: str) -> UpdateInfo | None:
    """Check PyPI for a newer version of styrened.

    Args:
        current_version: The currently running version string.

    Returns:
        UpdateInfo if check succeeded, None if it failed (network error, timeout, etc).
    """
    try:
        req = urllib.request.Request(
            PYPI_URL,
            headers={"Accept": "application/json", "User-Agent": "styrened-update-check"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read())

        latest = data["info"]["version"]

        from packaging.version import Version

        update_available = Version(latest) > Version(current_version)

        return UpdateInfo(
            current=current_version,
            latest=latest,
            update_available=update_available,
        )
    except Exception:
        logger.debug("Update check failed", exc_info=True)
        return None
