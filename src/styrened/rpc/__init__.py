"""RPC bidirectional communication over LXMF.

This module provides request/response RPC semantics over asynchronous LXMF
messaging, enabling bidirectional communication between TUI clients, daemons,
and peers.

Components:
- RPCClient: Send RPC requests and receive responses
- RPCServer: Receive RPC requests and send responses
- Message classes: StatusRequest, ExecCommand, etc.
- Errors: RPCTimeoutError, RPCTransportError, etc.

Example (Client):
    from styrened.rpc import RPCClient
    from styrened.services.lxmf_service import get_lxmf_service

    client = RPCClient(get_lxmf_service())
    status = await client.call_status(device_hash)
    print(f"Uptime: {status.format_uptime()}")

Example (Server):
    from styrened.rpc import RPCServer
    from styrened.services.lxmf_service import get_lxmf_service

    server = RPCServer(get_lxmf_service())
    server.start()
"""

# Client
from styrened.rpc.client import RPCClient

# Server
from styrened.rpc.server import RPCServer, get_rpc_server

# Messages
from styrened.rpc.messages import (
    ExecCommand,
    ExecResult,
    RebootCommand,
    RebootResult,
    RPCMessage,
    StatusRequest,
    StatusResponse,
    UpdateConfigCommand,
    UpdateConfigResult,
    deserialize_message,
)

# Errors
from styrened.rpc.errors import (
    RPCError,
    RPCInvalidResponseError,
    RPCTimeoutError,
    RPCTransportError,
)

__all__ = [
    # Client
    "RPCClient",
    # Server
    "RPCServer",
    "get_rpc_server",
    # Messages
    "RPCMessage",
    "StatusRequest",
    "StatusResponse",
    "ExecCommand",
    "ExecResult",
    "RebootCommand",
    "RebootResult",
    "UpdateConfigCommand",
    "UpdateConfigResult",
    "deserialize_message",
    # Errors
    "RPCError",
    "RPCTimeoutError",
    "RPCTransportError",
    "RPCInvalidResponseError",
]
