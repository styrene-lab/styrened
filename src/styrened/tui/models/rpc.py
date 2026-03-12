"""RPC re-exports from styrene-core.

This module provides backward compatibility by re-exporting RPC types from
styrened. All RPC functionality now lives in styrene-core.
"""
from __future__ import annotations


# Re-export all RPC types from core
from styrened.rpc import (
    ExecCommand,
    ExecResult,
    RebootCommand,
    RebootResult,
    RPCClient,
    RPCError,
    RPCInvalidResponseError,
    RPCServer,
    RPCTimeoutError,
    RPCTransportError,
    StatusRequest,
    StatusResponse,
    UpdateConfigCommand,
    UpdateConfigResult,
)

__all__ = [
    "RPCClient",
    "RPCServer",
    "StatusRequest",
    "StatusResponse",
    "ExecCommand",
    "ExecResult",
    "RebootCommand",
    "RebootResult",
    "UpdateConfigCommand",
    "UpdateConfigResult",
    "RPCError",
    "RPCTimeoutError",
    "RPCTransportError",
    "RPCInvalidResponseError",
]
