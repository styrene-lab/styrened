"""Shared test primitives that work with any TestHarness backend."""

from .base import PrimitiveResult
from .connectivity import check_connectivity, check_version
from .daemon import check_daemon_running, ensure_daemon_running, restart_daemon
from .discovery import check_bidirectional_discovery, discover_peers
from .installation import (
    InstallMethod,
    check_installation_prerequisites,
    install_via_nix_flake,
    install_via_pip_git,
    install_via_pip_wheel,
    setup_systemd_service,
    uninstall_styrened,
)
from .rpc import send_exec_command, send_status_request
from .terminal import (
    check_terminal_service_config,
    check_terminal_session_cleanup,
    close_terminal_session,
    read_terminal_output,
    resize_terminal_session,
    send_terminal_input,
    send_terminal_signal,
    start_terminal_session,
    verify_terminal_roundtrip,
)

__all__ = [
    # Base types
    "PrimitiveResult",
    # Connectivity
    "check_connectivity",
    "check_version",
    # Daemon
    "check_daemon_running",
    "ensure_daemon_running",
    "restart_daemon",
    # Discovery
    "discover_peers",
    "check_bidirectional_discovery",
    # RPC
    "send_status_request",
    "send_exec_command",
    # Terminal
    "check_terminal_service_config",
    "check_terminal_session_cleanup",
    "start_terminal_session",
    "send_terminal_input",
    "read_terminal_output",
    "close_terminal_session",
    "resize_terminal_session",
    "send_terminal_signal",
    "verify_terminal_roundtrip",
    # Installation
    "InstallMethod",
    "check_installation_prerequisites",
    "install_via_pip_git",
    "install_via_pip_wheel",
    "install_via_nix_flake",
    "setup_systemd_service",
    "uninstall_styrened",
]
