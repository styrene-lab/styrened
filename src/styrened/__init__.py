"""Styrened - Unified Styrene library and headless daemon.

This package provides:
1. Core library for RNS/LXMF mesh networking (models, protocols, rpc, services)
2. Headless daemon for edge deployments

Library usage:

```python
from styrened import CoreConfig, RPCClient, RPCServer
from styrened.models import MeshDevice, DeviceType
from styrened.services import load_core_config
```

Daemon usage:

```python
from styrened import StyreneDaemon, main
# or run via: styrened command
```
"""

__version__ = "0.10.41"

# Path resolution
from styrened import paths  # noqa: F401

# Daemon exports
from styrened.daemon import StyreneDaemon, main

# Core model exports
from styrened.models import (
    RNS_ERROR_INFO,
    APIConfig,
    ChatConfig,
    ConfigFieldError,
    ConfigLoadError,
    ConfigValidationError,
    # Config
    CoreConfig,
    DeploymentMode,
    DeviceType,
    DiscoveryConfig,
    GatewayMode,
    LogLevel,
    # Mesh devices
    MeshDevice,
    NodeStatus,
    ReticulumConfig,
    ReticulumIdentity,
    ReticulumInterface,
    ReticulumNotConfiguredError,
    # Reticulum state
    ReticulumState,
    RNSErrorCategory,
    # RNS errors
    RNSErrorState,
    RPCConfig,
    # Wire protocol
    StyreneEnvelope,
    StyreneMessageType,
    StyreneWireError,
    create_announce,
    create_chat,
    create_mesh_device,
    create_ping,
    create_pong,
    create_status_request,
    create_status_response,
    decode_payload,
    encode_payload,
    parse_announce_data,
)

# Protocol exports
from styrened.protocols import (
    ChatProtocol,
    LXMFMessage,
    Protocol,
    ProtocolNotFoundError,
    ProtocolRegistry,
    StyreneProtocol,
)

# RPC exports (most commonly used from library)
# Note: Request classes removed in wire protocol migration.
# Use RPCClient.call_status(), call_exec(), etc. or create_*() from styrene_wire.
from styrened.rpc import (
    ExecResult,
    RebootResult,
    RPCClient,
    # Errors
    RPCError,
    RPCInvalidResponseError,
    RPCServer,
    RPCTimeoutError,
    RPCTransportError,
    SelfUpdateResult,
    # Response types (for type hints and deserialization)
    StatusResponse,
    UpdateConfigResult,
    get_rpc_server,
)

# Service exports (path helpers are deprecated — use paths module directly)
from styrened.services import (
    ensure_directories,
    get_config_dir,
    get_data_dir,
    get_default_core_config,
    get_log_dir,
    load_core_config,
    save_core_config,
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
    # RPC Response Types
    "StatusResponse",
    "ExecResult",
    "RebootResult",
    "UpdateConfigResult",
    "SelfUpdateResult",
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
    "ConfigFieldError",
    "ConfigLoadError",
    "ConfigValidationError",
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
    # Path resolution
    "paths",
    # Config services
    "load_core_config",
    "save_core_config",
    "get_default_core_config",
    "get_config_dir",
    "get_data_dir",
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
