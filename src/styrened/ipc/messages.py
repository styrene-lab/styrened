"""IPC message dataclasses for control socket protocol.

Provides typed request/response/event messages for CLI/TUI communication
with the styrened daemon. Follows patterns from terminal/messages.py.

Usage:
    from styrened.ipc.messages import (
        QueryDevicesRequest,
        QueryDevicesResponse,
        ResultResponse,
        ErrorResponse,
    )

    # Create a request
    request = QueryDevicesRequest()

    # Serialize for transmission
    msg_type, payload = request.to_wire()

    # Deserialize a response
    response = ResultResponse.from_payload(payload)
"""

from dataclasses import dataclass, field
from typing import Any

from styrened.ipc.protocol import IPCMessageType

# -----------------------------------------------------------------------------
# Error codes
# -----------------------------------------------------------------------------


class IPCErrorCode:
    """Error codes for ERROR responses."""

    UNKNOWN = 0
    INVALID_REQUEST = 1
    NOT_FOUND = 2
    TIMEOUT = 3
    TRANSPORT_ERROR = 4
    NOT_INITIALIZED = 5
    PERMISSION_DENIED = 6
    INTERNAL_ERROR = 7


# -----------------------------------------------------------------------------
# Base classes
# -----------------------------------------------------------------------------


@dataclass
class IPCRequest:
    """Base class for IPC requests."""

    MSG_TYPE: IPCMessageType = field(init=False, repr=False)

    def to_payload(self) -> dict[str, Any]:
        """Convert request to payload dict for wire format.

        Returns:
            Dict suitable for msgpack encoding.
        """
        return {}

    def to_wire(self) -> tuple[IPCMessageType, dict[str, Any]]:
        """Get message type and payload for transmission.

        Returns:
            Tuple of (message_type, payload_dict).
        """
        return self.MSG_TYPE, self.to_payload()


@dataclass
class IPCResponse:
    """Base class for IPC responses."""

    MSG_TYPE: IPCMessageType = field(init=False, repr=False)
    success: bool = True

    def to_payload(self) -> dict[str, Any]:
        """Convert response to payload dict for wire format.

        Returns:
            Dict suitable for msgpack encoding.
        """
        return {"success": self.success}

    def to_wire(self) -> tuple[IPCMessageType, dict[str, Any]]:
        """Get message type and payload for transmission.

        Returns:
            Tuple of (message_type, payload_dict).
        """
        return self.MSG_TYPE, self.to_payload()


# -----------------------------------------------------------------------------
# Query requests
# -----------------------------------------------------------------------------


@dataclass
class PingRequest(IPCRequest):
    """Keepalive/health check request."""

    MSG_TYPE = IPCMessageType.PING


@dataclass
class QueryDevicesRequest(IPCRequest):
    """Request list of discovered devices."""

    MSG_TYPE = IPCMessageType.QUERY_DEVICES
    styrene_only: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {"styrene_only": self.styrene_only}


@dataclass
class QueryIdentityRequest(IPCRequest):
    """Request local identity information."""

    MSG_TYPE = IPCMessageType.QUERY_IDENTITY


@dataclass
class QueryStatusRequest(IPCRequest):
    """Request daemon status."""

    MSG_TYPE = IPCMessageType.QUERY_STATUS


@dataclass
class QueryConfigRequest(IPCRequest):
    """Request current configuration."""

    MSG_TYPE = IPCMessageType.QUERY_CONFIG


@dataclass
class QueryConversationsRequest(IPCRequest):
    """Request list of conversations."""

    MSG_TYPE = IPCMessageType.QUERY_CONVERSATIONS
    include_unread_count: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {"include_unread_count": self.include_unread_count}


@dataclass
class QueryMessagesRequest(IPCRequest):
    """Request message history for a conversation."""

    MSG_TYPE = IPCMessageType.QUERY_MESSAGES
    peer_hash: str = ""
    limit: int = 50
    before_timestamp: float | None = None
    status_filter: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "peer_hash": self.peer_hash,
            "limit": self.limit,
        }
        if self.before_timestamp is not None:
            payload["before_timestamp"] = self.before_timestamp
        if self.status_filter is not None:
            payload["status_filter"] = self.status_filter
        return payload


# -----------------------------------------------------------------------------
# Command requests
# -----------------------------------------------------------------------------


@dataclass
class CmdSendRequest(IPCRequest):
    """Send a message via the mesh."""

    MSG_TYPE = IPCMessageType.CMD_SEND
    destination: str = ""
    message: str = ""
    protocol: str = "chat"
    retry: bool = False
    timeout: float = 30.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "message": self.message,
            "protocol": self.protocol,
            "retry": self.retry,
            "timeout": self.timeout,
        }


@dataclass
class CmdExecRequest(IPCRequest):
    """Execute a command on a remote node."""

    MSG_TYPE = IPCMessageType.CMD_EXEC
    destination: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    timeout: float = 60.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "command": self.command,
            "args": self.args,
            "timeout": self.timeout,
        }


@dataclass
class CmdAnnounceRequest(IPCRequest):
    """Trigger a local announce."""

    MSG_TYPE = IPCMessageType.CMD_ANNOUNCE


@dataclass
class CmdDeviceStatusRequest(IPCRequest):
    """Query status of a specific remote device."""

    MSG_TYPE = IPCMessageType.CMD_DEVICE_STATUS
    destination: str = ""
    timeout: float = 30.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "timeout": self.timeout,
        }


@dataclass
class CmdSendChatRequest(IPCRequest):
    """Send a chat message to a peer."""

    MSG_TYPE = IPCMessageType.CMD_SEND_CHAT
    peer_hash: str = ""
    content: str = ""
    title: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "peer_hash": self.peer_hash,
            "content": self.content,
        }
        if self.title is not None:
            payload["title"] = self.title
        return payload


@dataclass
class CmdMarkReadRequest(IPCRequest):
    """Mark all messages in a conversation as read."""

    MSG_TYPE = IPCMessageType.CMD_MARK_READ
    peer_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"peer_hash": self.peer_hash}


@dataclass
class CmdDeleteConversationRequest(IPCRequest):
    """Delete all messages in a conversation."""

    MSG_TYPE = IPCMessageType.CMD_DELETE_CONVERSATION
    peer_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"peer_hash": self.peer_hash}


@dataclass
class CmdDeleteMessageRequest(IPCRequest):
    """Delete a specific message."""

    MSG_TYPE = IPCMessageType.CMD_DELETE_MESSAGE
    message_id: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {"message_id": self.message_id}


# -----------------------------------------------------------------------------
# Responses
# -----------------------------------------------------------------------------


@dataclass
class PongResponse(IPCResponse):
    """Response to PING."""

    MSG_TYPE = IPCMessageType.PONG
    daemon_version: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "daemon_version": self.daemon_version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PongResponse":
        return cls(
            success=payload.get("success", True),
            daemon_version=payload.get("daemon_version", ""),
        )


@dataclass
class ResultResponse(IPCResponse):
    """Success response with data."""

    MSG_TYPE = IPCMessageType.RESULT
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ResultResponse":
        return cls(
            success=payload.get("success", True),
            data=payload.get("data", {}),
        )


@dataclass
class ErrorResponse(IPCResponse):
    """Error response."""

    MSG_TYPE = IPCMessageType.ERROR
    success: bool = False
    code: int = IPCErrorCode.UNKNOWN
    message: str = ""
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "success": False,
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            payload["details"] = self.details
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ErrorResponse":
        return cls(
            code=payload.get("code", IPCErrorCode.UNKNOWN),
            message=payload.get("message", "Unknown error"),
            details=payload.get("details"),
        )

    @classmethod
    def not_found(cls, message: str) -> "ErrorResponse":
        """Create a NOT_FOUND error response."""
        return cls(code=IPCErrorCode.NOT_FOUND, message=message)

    @classmethod
    def timeout(cls, message: str) -> "ErrorResponse":
        """Create a TIMEOUT error response."""
        return cls(code=IPCErrorCode.TIMEOUT, message=message)

    @classmethod
    def invalid_request(cls, message: str) -> "ErrorResponse":
        """Create an INVALID_REQUEST error response."""
        return cls(code=IPCErrorCode.INVALID_REQUEST, message=message)

    @classmethod
    def internal_error(cls, message: str) -> "ErrorResponse":
        """Create an INTERNAL_ERROR error response."""
        return cls(code=IPCErrorCode.INTERNAL_ERROR, message=message)


# -----------------------------------------------------------------------------
# Response data helpers
# -----------------------------------------------------------------------------


@dataclass
class DeviceInfo:
    """Device information for query responses."""

    destination_hash: str
    identity_hash: str
    name: str
    device_type: str
    status: str
    is_styrene_node: bool
    lxmf_destination_hash: str | None
    last_announce: float
    announce_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination_hash": self.destination_hash,
            "identity_hash": self.identity_hash,
            "name": self.name,
            "device_type": self.device_type,
            "status": self.status,
            "is_styrene_node": self.is_styrene_node,
            "lxmf_destination_hash": self.lxmf_destination_hash,
            "last_announce": self.last_announce,
            "announce_count": self.announce_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceInfo":
        return cls(
            destination_hash=data.get("destination_hash", ""),
            identity_hash=data.get("identity_hash", ""),
            name=data.get("name", ""),
            device_type=data.get("device_type", "unknown"),
            status=data.get("status", "unknown"),
            is_styrene_node=data.get("is_styrene_node", False),
            lxmf_destination_hash=data.get("lxmf_destination_hash"),
            last_announce=data.get("last_announce", 0.0),
            announce_count=data.get("announce_count", 0),
        )

    @classmethod
    def from_mesh_device(cls, device) -> "DeviceInfo":
        """Create DeviceInfo from a MeshDevice instance.

        Args:
            device: MeshDevice instance from node_store.

        Returns:
            DeviceInfo with data copied from MeshDevice.
        """
        return cls(
            destination_hash=device.destination_hash or "",
            identity_hash=device.identity_hash or "",
            name=device.name or "",
            device_type=device.device_type.value if device.device_type else "unknown",
            status=device.status.value if device.status else "unknown",
            is_styrene_node=device.is_styrene_node,
            lxmf_destination_hash=device.lxmf_destination_hash,
            last_announce=device.last_announce or 0.0,
            announce_count=device.announce_count or 0,
        )


@dataclass
class IdentityInfo:
    """Local identity information."""

    identity_hash: str
    destination_hash: str
    lxmf_destination_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_hash": self.identity_hash,
            "destination_hash": self.destination_hash,
            "lxmf_destination_hash": self.lxmf_destination_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IdentityInfo":
        return cls(
            identity_hash=data.get("identity_hash", ""),
            destination_hash=data.get("destination_hash", ""),
            lxmf_destination_hash=data.get("lxmf_destination_hash", ""),
        )


@dataclass
class DaemonStatus:
    """Daemon status information."""

    uptime: float
    daemon_version: str
    rns_initialized: bool
    lxmf_initialized: bool
    device_count: int
    styrene_node_count: int
    pending_rpc_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "uptime": self.uptime,
            "daemon_version": self.daemon_version,
            "rns_initialized": self.rns_initialized,
            "lxmf_initialized": self.lxmf_initialized,
            "device_count": self.device_count,
            "styrene_node_count": self.styrene_node_count,
            "pending_rpc_count": self.pending_rpc_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DaemonStatus":
        return cls(
            uptime=data.get("uptime", 0.0),
            daemon_version=data.get("daemon_version", ""),
            rns_initialized=data.get("rns_initialized", False),
            lxmf_initialized=data.get("lxmf_initialized", False),
            device_count=data.get("device_count", 0),
            styrene_node_count=data.get("styrene_node_count", 0),
            pending_rpc_count=data.get("pending_rpc_count", 0),
        )


@dataclass
class ExecResultInfo:
    """Remote command execution result."""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecResultInfo":
        return cls(
            exit_code=data.get("exit_code", -1),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
        )


@dataclass
class RemoteStatusInfo:
    """Remote device status information."""

    uptime: float
    ip: str
    services: list[str]
    disk_used: int
    disk_total: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "uptime": self.uptime,
            "ip": self.ip,
            "services": self.services,
            "disk_used": self.disk_used,
            "disk_total": self.disk_total,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RemoteStatusInfo":
        return cls(
            uptime=data.get("uptime", 0.0),
            ip=data.get("ip", ""),
            services=data.get("services", []),
            disk_used=data.get("disk_used", 0),
            disk_total=data.get("disk_total", 0),
        )


# -----------------------------------------------------------------------------
# Request factory
# -----------------------------------------------------------------------------


def create_request(msg_type: IPCMessageType, payload: dict[str, Any]) -> IPCRequest:
    """Create a request object from message type and payload.

    Args:
        msg_type: Message type enum.
        payload: Decoded payload dict.

    Returns:
        Appropriate IPCRequest subclass instance.

    Raises:
        ValueError: If message type is not a request type.
    """
    if msg_type == IPCMessageType.PING:
        return PingRequest()
    elif msg_type == IPCMessageType.QUERY_DEVICES:
        return QueryDevicesRequest(styrene_only=payload.get("styrene_only", False))
    elif msg_type == IPCMessageType.QUERY_IDENTITY:
        return QueryIdentityRequest()
    elif msg_type == IPCMessageType.QUERY_STATUS:
        return QueryStatusRequest()
    elif msg_type == IPCMessageType.QUERY_CONFIG:
        return QueryConfigRequest()
    elif msg_type == IPCMessageType.QUERY_CONVERSATIONS:
        return QueryConversationsRequest(
            include_unread_count=payload.get("include_unread_count", True)
        )
    elif msg_type == IPCMessageType.QUERY_MESSAGES:
        return QueryMessagesRequest(
            peer_hash=payload.get("peer_hash", ""),
            limit=payload.get("limit", 50),
            before_timestamp=payload.get("before_timestamp"),
            status_filter=payload.get("status_filter"),
        )
    elif msg_type == IPCMessageType.CMD_SEND:
        return CmdSendRequest(
            destination=payload.get("destination", ""),
            message=payload.get("message", ""),
            protocol=payload.get("protocol", "chat"),
            retry=payload.get("retry", False),
            timeout=payload.get("timeout", 30.0),
        )
    elif msg_type == IPCMessageType.CMD_EXEC:
        return CmdExecRequest(
            destination=payload.get("destination", ""),
            command=payload.get("command", ""),
            args=payload.get("args", []),
            timeout=payload.get("timeout", 60.0),
        )
    elif msg_type == IPCMessageType.CMD_ANNOUNCE:
        return CmdAnnounceRequest()
    elif msg_type == IPCMessageType.CMD_DEVICE_STATUS:
        return CmdDeviceStatusRequest(
            destination=payload.get("destination", ""),
            timeout=payload.get("timeout", 30.0),
        )
    elif msg_type == IPCMessageType.CMD_SEND_CHAT:
        return CmdSendChatRequest(
            peer_hash=payload.get("peer_hash", ""),
            content=payload.get("content", ""),
            title=payload.get("title"),
        )
    elif msg_type == IPCMessageType.CMD_MARK_READ:
        return CmdMarkReadRequest(peer_hash=payload.get("peer_hash", ""))
    elif msg_type == IPCMessageType.CMD_DELETE_CONVERSATION:
        return CmdDeleteConversationRequest(peer_hash=payload.get("peer_hash", ""))
    elif msg_type == IPCMessageType.CMD_DELETE_MESSAGE:
        return CmdDeleteMessageRequest(message_id=payload.get("message_id", 0))
    else:
        raise ValueError(f"Unknown request type: {msg_type}")
