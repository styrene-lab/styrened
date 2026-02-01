"""RPC message response models.

This module defines the response data structures used for RPC communication
over LXMF between TUI clients, daemons, and peers.

Response types:
- StatusResponse: Device status response
- ExecResult: Command execution result
- RebootResult: Reboot result
- UpdateConfigResult: Config update result

Note:
    Request types and wire format encoding are handled by StyreneEnvelope
    and the convenience functions in models/styrene_wire.py:
    - create_status_request()
    - create_exec()
    - create_reboot()
    - create_config_update()

    See: models/styrene_wire.py for the wire format implementation.
"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class StatusResponse:
    """Device status response.

    Attributes:
        uptime: System uptime in seconds.
        ip: Device IP address.
        services: List of running services.
        disk_used: Used disk space in bytes.
        disk_total: Total disk space in bytes.
    """

    uptime: int
    ip: str
    services: list[str]
    disk_used: int
    disk_total: int
    type: str = "status_response"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    def format_uptime(self) -> str:
        """Format uptime as human-readable string."""
        days, remainder = divmod(self.uptime, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if seconds > 0 or not parts:
            parts.append(f"{seconds}s")
        return " ".join(parts)

    def format_disk_usage(self) -> str:
        """Format disk usage as human-readable string."""
        if self.disk_total == 0:
            return "N/A"
        used_gb = self.disk_used / (1024**3)
        total_gb = self.disk_total / (1024**3)
        percent = (self.disk_used / self.disk_total) * 100
        return f"{used_gb:.1f}GB / {total_gb:.1f}GB ({percent:.0f}%)"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatusResponse":
        """Deserialize from dict."""
        return cls(
            uptime=data["uptime"],
            ip=data["ip"],
            services=data["services"],
            disk_used=data["disk_used"],
            disk_total=data["disk_total"],
        )


@dataclass
class ExecResult:
    """Command execution result.

    Attributes:
        exit_code: Command exit code.
        stdout: Command stdout output.
        stderr: Command stderr output.
    """

    exit_code: int
    stdout: str
    stderr: str
    type: str = "exec_result"

    @property
    def success(self) -> bool:
        """Check if command succeeded (exit code 0)."""
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecResult":
        """Deserialize from dict."""
        return cls(
            exit_code=data["exit_code"],
            stdout=data["stdout"],
            stderr=data["stderr"],
        )


@dataclass
class RebootResult:
    """Reboot command result.

    Attributes:
        success: Whether reboot was scheduled/initiated successfully.
        message: Human-readable result message.
        scheduled_time: Unix timestamp of scheduled reboot (None if immediate).
    """

    success: bool
    message: str
    scheduled_time: float | None = None
    type: str = "reboot_result"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RebootResult":
        """Deserialize from dict."""
        return cls(
            success=data["success"],
            message=data["message"],
            scheduled_time=data.get("scheduled_time"),
        )


@dataclass
class UpdateConfigResult:
    """Update config command result.

    Attributes:
        success: Whether all config updates were applied successfully.
        message: Human-readable result message.
        updated_keys: List of config keys that were successfully updated.
    """

    success: bool
    message: str
    updated_keys: list[str]
    type: str = "update_config_result"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateConfigResult":
        """Deserialize from dict."""
        return cls(
            success=data["success"],
            message=data["message"],
            updated_keys=data.get("updated_keys", []),
        )
