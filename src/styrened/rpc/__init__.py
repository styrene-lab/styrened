"""RPC bidirectional communication over LXMF.

This module provides request/response RPC semantics over asynchronous LXMF
messaging, enabling bidirectional communication between TUI clients, daemons,
and peers.

Components:
- RPCClient: Send RPC requests and receive responses
- RPCServer: Receive RPC requests and send responses
- Response classes: StatusResponse, ExecResult, etc.
- Errors: RPCTimeoutError, RPCTransportError, etc.

Note:
    Request encoding uses StyreneProtocol and the convenience functions
    in models/styrene_wire.py. RPCClient and RPCServer handle this internally.

Example (Client):
    from styrened.rpc import RPCClient
    from styrened.protocols.styrene import StyreneProtocol
    from styrened.services.lxmf_service import get_lxmf_service

    lxmf = get_lxmf_service()
    protocol = StyreneProtocol(lxmf.router, lxmf._identity, lxmf.db_engine)
    client = RPCClient(protocol)
    status = await client.call_status(device_hash)
    print(f"Uptime: {status.format_uptime()}")

Example (Server):
    from styrened.rpc import RPCServer
    from styrened.protocols.styrene import StyreneProtocol
    from styrened.services.lxmf_service import get_lxmf_service

    lxmf = get_lxmf_service()
    protocol = StyreneProtocol(lxmf.router, lxmf._identity, lxmf.db_engine)
    server = RPCServer(protocol)
    server.start()
"""

# Client
from styrened.rpc.client import RPCClient

# Errors
from styrened.rpc.errors import (
    RPCError,
    RPCInvalidResponseError,
    RPCTimeoutError,
    RPCTransportError,
)

# Response types
from styrened.rpc.messages import (
    ExecResult,
    RebootResult,
    StatusResponse,
    UpdateConfigResult,
)

# Server
from styrened.rpc.server import RPCServer, get_rpc_server

__all__ = [
    # Client
    "RPCClient",
    # Server
    "RPCServer",
    "get_rpc_server",
    # Response types
    "StatusResponse",
    "ExecResult",
    "RebootResult",
    "UpdateConfigResult",
    # Errors
    "RPCError",
    "RPCTimeoutError",
    "RPCTransportError",
    "RPCInvalidResponseError",
]
