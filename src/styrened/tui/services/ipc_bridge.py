"""Backward-compatibility shim — IPCBridge has moved to styrened.ipc.bridge.

All new code should import from ``styrened.ipc``::

    from styrened.ipc import IPCBridge

This module re-exports IPCBridge so existing TUI code continues to work
during the migration period.
"""

from styrened.ipc.bridge import IPCBridge

__all__ = ["IPCBridge"]
