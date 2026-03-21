"""IPC client interface for the styrened daemon.

Provides Unix socket communication between Python tools (TUI, CLI) and
the running Rust daemon (styrened binary).

Components:
    IPCBridge: High-level async client with auto-reconnect and typed methods
    ControlClient: Low-level socket client
    IPCMessageType: Protocol message types

Usage::

    from styrened.ipc import IPCBridge

    bridge = IPCBridge()
    await bridge.connect()
    status = await bridge.get_status()
    await bridge.disconnect()
"""
from __future__ import annotations

from styrened.ipc.bridge import IPCBridge
from styrened.ipc.client import (
    ControlClient,
    IPCConnectionError,
    IPCResponseError,
    IPCTimeoutError,
    get_daemon_client,
)
from styrened.ipc.protocol import (
    DEFAULT_READ_TIMEOUT,
    FrameReadTimeoutError,
    IPCMessageType,
)
from styrened.paths import control_socket as _control_socket
from pathlib import Path


def get_default_socket_path() -> Path:
    """Determine the default socket path.

    Delegates to the central ``paths`` module. Respects ``STYRENED_SOCKET``
    env var, then mode-dependent defaults.
    """
    return _control_socket()


__all__ = [
    # Bridge (high-level client)
    "IPCBridge",
    "get_default_socket_path",
    # Client (low-level)
    "ControlClient",
    "get_daemon_client",
    # Protocol
    "IPCMessageType",
    "DEFAULT_READ_TIMEOUT",
    # Exceptions
    "IPCConnectionError",
    "IPCTimeoutError",
    "IPCResponseError",
    "FrameReadTimeoutError",
]
