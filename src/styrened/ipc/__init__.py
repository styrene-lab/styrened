"""IPC control interface for styrened.

Provides Unix socket communication between CLI tools and the running daemon,
eliminating the need for CLI commands to initialize their own RNS/LXMF stack.

Components:
    ControlServer: Unix socket server (runs in daemon)
    ControlClient: Client library (used by CLI/TUI)
    IPCMessageType: Protocol message types

Usage (daemon side):
    from styrened.ipc import ControlServer

    server = ControlServer(daemon)
    await server.start()
    # ... daemon runs ...
    await server.stop()

Usage (CLI side):
    from styrened.ipc import ControlClient, get_daemon_client

    # Context manager style
    async with ControlClient() as client:
        devices = await client.query_devices()

    # Or check for running daemon
    client = await get_daemon_client()
    if client:
        try:
            devices = await client.query_devices()
        finally:
            await client.disconnect()
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


# ControlServer removed — daemon is now Rust (styrened binary).
# Kept for backward-compatible imports that only reference the name.
ControlServer = None

__all__ = [
    # Bridge (high-level client)
    "IPCBridge",
    # Server (deprecated — daemon is Rust)
    "ControlServer",
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
