"""Backward-compatibility shim — IPCBridge has moved to styrened.ipc.bridge.

All new code should import from ``styrened.ipc``::

    from styrened.ipc import IPCBridge

This module re-exports IPCBridge so existing TUI code continues to work
during the migration period.

.. deprecated:: 0.15.1
    Import from ``styrened.ipc`` instead. This shim will be removed in 0.16.0.
"""
from __future__ import annotations

import warnings

from styrened.ipc.bridge import IPCBridge

warnings.warn(
    "styrened.tui.services.ipc_bridge is deprecated — "
    "import IPCBridge from styrened.ipc instead. "
    "This shim will be removed in 0.16.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["IPCBridge"]
