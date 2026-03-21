"""RPC types for Styrene mesh communication.

Provides request/response types, error classes, and the RPC client
for fleet management over LXMF. The RPC server has moved to Rust.
"""
from __future__ import annotations

# Client
from styrened.rpc.client import RPCClient

# Errors
from styrened.rpc.errors import (
    RPCError,
    RPCInvalidResponseError,
    RPCTimeoutError,
    RPCTransportError,
)

# Message types (requests + responses)
from styrened.rpc.messages import (
    ExecCommand,
    ExecResult,
    RebootCommand,
    RebootResult,
    SelfUpdateResult,
    StatusRequest,
    StatusResponse,
    UpdateConfigCommand,
    UpdateConfigResult,
)

__all__ = [
    # Client
    "RPCClient",
    # Request types
    "StatusRequest",
    "ExecCommand",
    "RebootCommand",
    "UpdateConfigCommand",
    # Response types
    "StatusResponse",
    "ExecResult",
    "RebootResult",
    "UpdateConfigResult",
    "SelfUpdateResult",
    # Errors
    "RPCError",
    "RPCTimeoutError",
    "RPCTransportError",
    "RPCInvalidResponseError",
]
