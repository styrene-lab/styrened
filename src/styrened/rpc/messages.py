"""RPC message models for communication over LXMF.

This module defines the message data structures used for RPC communication
over LXMF between TUI clients, daemons, and peers.

Message types:
- StatusRequest: Request device status
- StatusResponse: Device status response
- ExecCommand: Execute command on device
- ExecResult: Command execution result
- RebootCommand: Reboot device
- RebootResult: Reboot result
- UpdateConfigCommand: Update configuration
- UpdateConfigResult: Config update result
"""

from dataclasses import asdict, dataclass
from typing import Any, Protocol


class RPCMessage(Protocol):
    """Protocol for RPC messages.

    All RPC messages must implement this protocol to be serializable
    and identifiable by type.
    """

    @property
    def type(self) -> str:
        """Message type identifier."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Serialize message to JSON-compatible dict."""
        ...


@dataclass
class StatusRequest:
    """Request device status information.

    This is an empty message - the request type itself is the signal.
    """

    type: str = "status_request"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {"type": self.type}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatusRequest":
        """Deserialize from dict."""
        return cls()


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
class ExecCommand:
    """Execute command on device.

    Attributes:
        command: Command to execute.
        args: Command arguments.
    """

    command: str
    args: list[str]
    type: str = "exec"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecCommand":
        """Deserialize from dict."""
        return cls(
            command=data["command"],
            args=data["args"],
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
class RebootCommand:
    """Reboot device command.

    Attributes:
        delay: Seconds to delay reboot (0 = immediate).
    """

    delay: int = 0
    type: str = "reboot"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RebootCommand":
        """Deserialize from dict."""
        return cls(delay=data.get("delay", 0))


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
class UpdateConfigCommand:
    """Update device configuration command.

    Attributes:
        config_updates: Dictionary of config keys to update with new values.
    """

    config_updates: dict[str, Any]
    type: str = "update_config"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {"type": self.type, "config": self.config_updates}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateConfigCommand":
        """Deserialize from dict."""
        return cls(config_updates=data.get("config", {}))


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


# Message type registry for deserialization
MESSAGE_TYPES: dict[
    str,
    type[
        StatusRequest
        | StatusResponse
        | ExecCommand
        | ExecResult
        | RebootCommand
        | RebootResult
        | UpdateConfigCommand
        | UpdateConfigResult
    ],
] = {
    "status_request": StatusRequest,
    "status_response": StatusResponse,
    "exec": ExecCommand,
    "exec_result": ExecResult,
    "reboot": RebootCommand,
    "reboot_result": RebootResult,
    "update_config": UpdateConfigCommand,
    "update_config_result": UpdateConfigResult,
}


def deserialize_message(
    data: dict[str, Any],
) -> (
    StatusRequest
    | StatusResponse
    | ExecCommand
    | ExecResult
    | RebootCommand
    | RebootResult
    | UpdateConfigCommand
    | UpdateConfigResult
):
    """Deserialize RPC message from dict.

    Args:
        data: Message data with 'type' field.

    Returns:
        Deserialized message instance.

    Raises:
        ValueError: If message type is unknown.
    """
    msg_type = data.get("type")
    if not msg_type:
        raise ValueError("Message missing 'type' field")

    if msg_type not in MESSAGE_TYPES:
        raise ValueError(f"Unknown message type: {msg_type}")

    return MESSAGE_TYPES[msg_type].from_dict(data)
