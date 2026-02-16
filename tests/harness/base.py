"""Base types and abstract interface for test harnesses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class ExecutionBackend(Enum):
    """Backend type for command execution."""

    SSH = "ssh"
    K8S = "k8s"


@dataclass
class CommandResult:
    """Unified result from command execution across backends."""

    success: bool
    stdout: str
    stderr: str
    return_code: int
    duration: float = 0.0
    backend: ExecutionBackend = ExecutionBackend.SSH
    target: str = ""  # hostname or pod name
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def output(self) -> str:
        """Combined stdout/stderr for compatibility."""
        return self.stdout + self.stderr

    def as_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "duration": self.duration,
            "backend": self.backend.value,
            "target": self.target,
            "metadata": self.metadata,
        }


@dataclass
class NodeInfo:
    """Unified node representation across backends."""

    name: str  # Logical name (device name or pod name)
    address: str  # Connection address (hostname or pod/namespace)
    identity_hash: str | None  # LXMF identity if known
    backend: ExecutionBackend
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.name} ({self.backend.value})"


class TestHarness(ABC):
    """Abstract base for test harnesses.

    Implementations must provide methods for:
    - Command execution on nodes
    - Daemon lifecycle management
    - Device discovery
    - Identity queries
    """

    @property
    @abstractmethod
    def backend(self) -> ExecutionBackend:
        """Return the execution backend type."""
        ...

    @abstractmethod
    def get_nodes(self) -> list[NodeInfo]:
        """Return all available test nodes."""
        ...

    @abstractmethod
    def run(
        self,
        node: str | NodeInfo,
        command: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Execute command on a node."""
        ...

    @abstractmethod
    def run_styrened(
        self,
        node: str | NodeInfo,
        subcommand: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Execute styrened CLI command."""
        ...

    # Daemon lifecycle - common interface, different implementations
    @abstractmethod
    def start_daemon(self, node: str | NodeInfo) -> CommandResult:
        """Start styrened daemon on node."""
        ...

    @abstractmethod
    def stop_daemon(self, node: str | NodeInfo) -> CommandResult:
        """Stop styrened daemon on node."""
        ...

    @abstractmethod
    def is_daemon_running(self, node: str | NodeInfo) -> bool:
        """Check if daemon is running on node."""
        ...

    # Discovery operations
    @abstractmethod
    def get_identity(self, node: str | NodeInfo) -> dict[str, Any] | None:
        """Get LXMF identity info for node.

        Returns:
            Dict with at least 'identity_hash' and 'exists' keys, or None.
        """
        ...

    @abstractmethod
    def discover_devices(
        self,
        node: str | NodeInfo,
        wait_seconds: int = 10,
    ) -> list[dict[str, Any]]:
        """Discover mesh devices from node's perspective."""
        ...

    # Context managers for setup/teardown
    @contextmanager
    def daemon_running(self, node: str | NodeInfo) -> Iterator[None]:
        """Context manager ensuring daemon runs during test."""
        was_running = self.is_daemon_running(node)
        if not was_running:
            self.start_daemon(node)
        try:
            yield
        finally:
            if not was_running:
                self.stop_daemon(node)

    # Convenience methods (implemented in base, can be overridden)
    def get_version(self, node: str | NodeInfo) -> str | None:
        """Get styrened version on node."""
        result = self.run_styrened(node, "--version")
        if result.success:
            # Parse "styrened X.Y.Z" -> "X.Y.Z"
            parts = result.stdout.strip().split()
            if parts:
                return parts[-1]
        return None

    def query_status(
        self,
        source_node: str | NodeInfo,
        target_identity: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Send RPC status request from source to target."""
        return self.run_styrened(
            source_node,
            f"status {target_identity}",
            timeout=timeout,
        )

    def send_message(
        self,
        source_node: str | NodeInfo,
        target_identity: str,
        message: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Send chat message from source to target."""
        # Escape message for shell
        escaped = message.replace("'", "'\\''")
        return self.run_styrened(
            source_node,
            f"send {target_identity} '{escaped}'",
            timeout=timeout,
        )

    def exec_remote(
        self,
        source_node: str | NodeInfo,
        target_identity: str,
        command: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Execute command on remote node via RPC."""
        # Escape command for shell
        escaped = command.replace("'", "'\\''")
        return self.run_styrened(
            source_node,
            f"exec {target_identity} '{escaped}'",
            timeout=timeout,
        )

    # Alias for backward compatibility
    exec_command = exec_remote

    def get_logs(
        self,
        node: str | NodeInfo,
        lines: int = 100,
        since: str | None = None,
    ) -> CommandResult:
        """Get daemon logs from a node.

        Args:
            node: Node to get logs from
            lines: Number of lines to retrieve (default: 100)
            since: Time filter (e.g., "1h", "30m") - implementation-specific

        Returns:
            CommandResult with log content in stdout
        """
        import re
        import shlex

        # Validate lines parameter
        if not isinstance(lines, int) or lines <= 0:
            lines = 100

        # Default implementation uses journalctl for systemd-based systems
        # Subclasses can override for different log sources
        cmd = f"journalctl --user -u styrened -n {lines} --no-pager 2>/dev/null || "
        cmd += f"journalctl -u styrened -n {lines} --no-pager 2>/dev/null || "
        cmd += "echo 'Logs not available via journalctl'"

        if since:
            # Validate and sanitize since parameter to prevent shell injection
            # Only allow safe patterns like "1h", "30m", "2d", or ISO dates
            if re.match(r"^\d+[smhd]$", since) or re.match(r"^\d{4}-\d{2}-\d{2}", since):
                safe_since = shlex.quote(since)
                cmd = f"journalctl --user -u styrened -n {lines} --since {safe_since} --no-pager 2>/dev/null || "
                cmd += f"journalctl -u styrened -n {lines} --since {safe_since} --no-pager 2>/dev/null || "
                cmd += "echo 'Logs not available via journalctl'"
            # else: ignore invalid since values silently

        return self.run(node, cmd, timeout=10.0)
