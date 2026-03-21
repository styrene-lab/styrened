"""Styrene — TUI and CLI for the Styrene mesh network.

This package provides:
1. Terminal UI (TUI) for mesh network operation
2. CLI tools (devices, status, send, exec, doctor)
3. IPC bridge to the Rust daemon (styrened binary)
4. Data models for mesh devices, config, and protocol types

The daemon has moved to Rust. Install it via:
    cargo install styrened
    # or download from GitHub releases

TUI usage:
    styrene          # Launch the TUI

CLI usage:
    styrened daemon  # Start the Rust daemon
    styrened devices # List discovered mesh devices
    styrened status  # Check daemon health
    styrened doctor  # Run diagnostics
"""
from __future__ import annotations

__version__ = "0.18.0"

# Path resolution
from styrened import paths  # noqa: F401

# Core model exports
from styrened.models import (
    RNS_ERROR_INFO,
    APIConfig,
    ChatConfig,
    ConfigFieldError,
    ConfigLoadError,
    ConfigValidationError,
    CoreConfig,
    DeploymentMode,
    DeviceType,
    DiscoveryConfig,
    GatewayMode,
    LogLevel,
    MeshDevice,
    NodeStatus,
    ReticulumConfig,
    ReticulumIdentity,
    ReticulumInterface,
    ReticulumNotConfiguredError,
    ReticulumState,
    RNSErrorCategory,
    RNSErrorState,
    RPCConfig,
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

# Service exports (config helpers used by TUI)
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
    "__version__",
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
]
