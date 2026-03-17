"""DaemonMode enum — standalone to avoid circular import.

This module exists so that models/config.py can reference DaemonMode
without creating a circular dependency through services/__init__.py.

The canonical public API remains styrened.services.daemon_adapter.DaemonMode,
which re-exports this enum.
"""
from __future__ import annotations

from enum import StrEnum


class DaemonMode(StrEnum):
    """Operating mode for an optional daemon integration."""

    DISABLED = "disabled"
    ADOPT = "adopt"
    MANAGED = "managed"
