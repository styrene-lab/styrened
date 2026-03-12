"""RPC message response models.

This module defines the response data structures used for RPC communication
over LXMF between TUI clients, daemons, and peers.

Response types:
- StatusResponse: Device status response
- ExecResult: Command execution result
- RebootResult: Reboot result
- UpdateConfigResult: Config update result
- InboxResponse: Remote inbox query response
- MessagesResponse: Remote messages query response

Note:
    Request types and wire format encoding are handled by StyreneEnvelope
    and the convenience functions in models/styrene_wire.py:
    - create_status_request()
    - create_exec()
    - create_reboot()
    - create_config_update()
    - create_inbox_query()
    - create_messages_query()

    See: models/styrene_wire.py for the wire format implementation.
"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class StatusRequest:
    """Status request message.

    Attributes:
        type: Message type identifier.
    """

    type: str = "status_request"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatusRequest":
        """Deserialize from dict."""
        return cls()


@dataclass
class ExecCommand:
    """Remote command execution request.

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
            args=data.get("args", []),
        )


@dataclass
class RebootCommand:
    """Remote reboot request.

    Attributes:
        delay: Delay in seconds before reboot (0 = immediate).
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
class UpdateConfigCommand:
    """Remote config update request.

    Attributes:
        config_updates: Dictionary of config key/value pairs to update.
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
class StatusResponse:
    """Device status response.

    Attributes:
        uptime: System uptime in seconds.
        ip: Device IP address.
        services: List of running services.
        disk_used: Used disk space in bytes.
        disk_total: Total disk space in bytes.
        styrened_version: Remote styrened version string.
        hostname: Remote hostname.
        arch: CPU architecture (e.g. x86_64, aarch64).
        os_id: OS identifier (e.g. nixos, debian, darwin).
        os_version: OS version string.
        nixos_generation: NixOS store hash prefix (7 chars), empty if not NixOS.
    """

    uptime: int
    ip: str
    services: list[str]
    disk_used: int
    disk_total: int
    styrened_version: str | None = None
    hostname: str | None = None
    arch: str | None = None
    os_id: str | None = None
    os_version: str | None = None
    nixos_generation: str | None = None
    available_commands: list[str] | None = None
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
            styrened_version=data.get("styrened_version"),
            hostname=data.get("hostname"),
            arch=data.get("arch"),
            os_id=data.get("os_id"),
            os_version=data.get("os_version"),
            nixos_generation=data.get("nixos_generation"),
            available_commands=data.get("available_commands"),
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


@dataclass
class SelfUpdateResult:
    """Self-update command result.

    Attributes:
        success: Whether update was applied successfully.
        message: Human-readable result message.
        old_version: Version before update.
        new_version: Version after update (None if update failed).
    """

    success: bool
    message: str
    old_version: str
    new_version: str | None = None
    type: str = "self_update_result"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelfUpdateResult":
        """Deserialize from dict."""
        return cls(
            success=data["success"],
            message=data["message"],
            old_version=data["old_version"],
            new_version=data.get("new_version"),
        )


@dataclass
class InboxResponse:
    """Remote inbox query response.

    Contains a list of conversations from the remote node's inbox.

    Attributes:
        conversations: List of conversation dicts (ConversationInfo.to_dict() format).
        type: Message type identifier.
    """

    conversations: list[dict[str, Any]]
    type: str = "inbox_response"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {"conversations": self.conversations, "type": self.type}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "InboxResponse":
        """Deserialize from dict."""
        return cls(conversations=data.get("conversations", []))


@dataclass
class MessagesResponse:
    """Remote messages query response.

    Contains a list of messages from the remote node for a specific peer.

    Attributes:
        messages: List of message dicts (MessageInfo.to_dict() format).
        type: Message type identifier.
    """

    messages: list[dict[str, Any]]
    type: str = "messages_response"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {"messages": self.messages, "type": self.type}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MessagesResponse":
        """Deserialize from dict."""
        return cls(messages=data.get("messages", []))


@dataclass
class ProvisionRequest:
    """Remote adapter provisioning request.

    Attributes:
        adapter: Adapter name to provision (e.g., "yggdrasil").
        type: Message type identifier.
    """

    adapter: str
    type: str = "provision"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvisionRequest":
        """Deserialize from dict."""
        return cls(adapter=data.get("adapter", ""))


@dataclass
class ProvisionResponse:
    """Remote adapter provisioning response.

    Attributes:
        success: Whether provisioning succeeded.
        adapter: Adapter name that was provisioned.
        installed_path: Path where binary was installed (on success).
        error: Error message (on failure).
    """

    success: bool
    adapter: str
    installed_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvisionResponse":
        """Deserialize from dict."""
        return cls(
            success=data.get("success", False),
            adapter=data.get("adapter", ""),
            installed_path=data.get("installed_path"),
            error=data.get("error"),
        )
