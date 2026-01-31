"""Styrened - Unified Styrene library and headless daemon.

This package provides:
1. Core library for RNS/LXMF mesh networking (models, protocols, rpc, services)
2. Headless daemon for edge deployments

Library usage:
    from styrened import CoreConfig, RPCClient, RPCServer
    from styrened.models import MeshDevice, DeviceType
    from styrened.services import load_core_config

Daemon usage:
    from styrened import StyreneDaemon, main
    # or run via: styrened command
"""

__version__ = "0.2.0"

# Daemon exports
from styrened.daemon import StyreneDaemon, main

# RPC exports (most commonly used from library)
from styrened.rpc import (
    RPCClient,
    RPCServer,
    get_rpc_server,
    StatusRequest,
    StatusResponse,
    ExecCommand,
    ExecResult,
    RebootCommand,
    RebootResult,
    UpdateConfigCommand,
    UpdateConfigResult,
    RPCError,
    RPCTimeoutError,
    RPCTransportError,
    RPCInvalidResponseError,
)

# Core model exports
from styrened.models import (
    # Config
    CoreConfig,
    APIConfig,
    ChatConfig,
    RPCConfig,
    ReticulumConfig,
    DiscoveryConfig,
    DeploymentMode,
    GatewayMode,
    LogLevel,
    ConfigLoadError,
    ConfigValidationError,
    ConfigValidationErrors,
    # Mesh devices
    MeshDevice,
    DeviceType,
    NodeStatus,
    create_mesh_device,
    parse_announce_data,
    # Reticulum state
    ReticulumState,
    ReticulumIdentity,
    ReticulumInterface,
    ReticulumNotConfiguredError,
    # RNS errors
    RNSErrorState,
    RNSErrorCategory,
    RNS_ERROR_INFO,
    # Wire protocol
    StyreneEnvelope,
    StyreneMessageType,
    StyreneWireError,
    create_ping,
    create_pong,
    create_chat,
    create_announce,
    create_status_request,
    create_status_response,
    encode_payload,
    decode_payload,
)

# Service exports
from styrened.services import (
    load_core_config,
    save_core_config,
    get_default_core_config,
    get_config_dir,
    get_data_dir,
    get_cache_dir,
    get_log_dir,
    ensure_directories,
)

# Protocol exports
from styrened.protocols import (
    Protocol,
    LXMFMessage,
    ChatProtocol,
    StyreneProtocol,
    ProtocolRegistry,
    ProtocolNotFoundError,
)

__all__ = [
    # Version
    "__version__",
    # Daemon
    "StyreneDaemon",
    "main",
    # RPC Client/Server
    "RPCClient",
    "RPCServer",
    "get_rpc_server",
    # RPC Messages
    "StatusRequest",
    "StatusResponse",
    "ExecCommand",
    "ExecResult",
    "RebootCommand",
    "RebootResult",
    "UpdateConfigCommand",
    "UpdateConfigResult",
    # RPC Errors
    "RPCError",
    "RPCTimeoutError",
    "RPCTransportError",
    "RPCInvalidResponseError",
    # Config models
    "CoreConfig",
    "APIConfig",
    "ChatConfig",
    "RPCConfig",
    "ReticulumConfig",
    "DiscoveryConfig",
    "DeploymentMode",
    "GatewayMode",
    "LogLevel",
    "ConfigLoadError",
    "ConfigValidationError",
    "ConfigValidationErrors",
    # Mesh device models
    "MeshDevice",
    "DeviceType",
    "NodeStatus",
    "create_mesh_device",
    "parse_announce_data",
    # Reticulum state models
    "ReticulumState",
    "ReticulumIdentity",
    "ReticulumInterface",
    "ReticulumNotConfiguredError",
    # RNS error models
    "RNSErrorState",
    "RNSErrorCategory",
    "RNS_ERROR_INFO",
    # Wire protocol
    "StyreneEnvelope",
    "StyreneMessageType",
    "StyreneWireError",
    "create_ping",
    "create_pong",
    "create_chat",
    "create_announce",
    "create_status_request",
    "create_status_response",
    "encode_payload",
    "decode_payload",
    # Config services
    "load_core_config",
    "save_core_config",
    "get_default_core_config",
    "get_config_dir",
    "get_data_dir",
    "get_cache_dir",
    "get_log_dir",
    "ensure_directories",
    # Protocols
    "Protocol",
    "LXMFMessage",
    "ChatProtocol",
    "StyreneProtocol",
    "ProtocolRegistry",
    "ProtocolNotFoundError",
]
