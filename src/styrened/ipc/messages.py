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


@dataclass
class QuerySearchMessagesRequest(IPCRequest):
    """Search messages by content using full-text search."""

    MSG_TYPE = IPCMessageType.QUERY_SEARCH_MESSAGES
    query: str = ""
    peer_hash: str | None = None
    limit: int = 50

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": self.query,
            "limit": self.limit,
        }
        if self.peer_hash is not None:
            payload["peer_hash"] = self.peer_hash
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
    delivery_method: str = "auto"  # "auto", "direct", or "propagated"
    reply_to_hash: str | None = None  # LXMF hash of message being replied to
    attachment_data_b64: str | None = None  # Base64-encoded attachment data
    attachment_filename: str | None = None  # Original filename
    attachment_mime: str | None = None  # MIME type

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "peer_hash": self.peer_hash,
            "content": self.content,
            "delivery_method": self.delivery_method,
        }
        if self.title is not None:
            payload["title"] = self.title
        if self.reply_to_hash is not None:
            payload["reply_to_hash"] = self.reply_to_hash
        if self.attachment_data_b64 is not None:
            payload["attachment_data_b64"] = self.attachment_data_b64
            if self.attachment_filename is not None:
                payload["attachment_filename"] = self.attachment_filename
            if self.attachment_mime is not None:
                payload["attachment_mime"] = self.attachment_mime
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


@dataclass
class CmdRetryMessageRequest(IPCRequest):
    """Retry sending a failed message."""

    MSG_TYPE = IPCMessageType.CMD_RETRY_MESSAGE
    message_id: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {"message_id": self.message_id}


# -----------------------------------------------------------------------------
# Contact requests
# -----------------------------------------------------------------------------


@dataclass
class QueryContactsRequest(IPCRequest):
    """Request list of contacts."""

    MSG_TYPE = IPCMessageType.QUERY_CONTACTS


@dataclass
class QueryResolveNameRequest(IPCRequest):
    """Resolve a name to a peer hash."""

    MSG_TYPE = IPCMessageType.QUERY_RESOLVE_NAME
    name: str = ""
    prefix_match: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "prefix_match": self.prefix_match}


@dataclass
class CmdSetContactRequest(IPCRequest):
    """Set or update a contact alias."""

    MSG_TYPE = IPCMessageType.CMD_SET_CONTACT
    peer_hash: str = ""
    alias: str = ""
    notes: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "peer_hash": self.peer_hash,
            "alias": self.alias,
        }
        if self.notes is not None:
            payload["notes"] = self.notes
        return payload


@dataclass
class CmdRemoveContactRequest(IPCRequest):
    """Remove a contact alias."""

    MSG_TYPE = IPCMessageType.CMD_REMOVE_CONTACT
    peer_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"peer_hash": self.peer_hash}


@dataclass
class QueryAutoReplyRequest(IPCRequest):
    """Query auto-reply configuration."""

    MSG_TYPE = IPCMessageType.QUERY_AUTO_REPLY


@dataclass
class CmdSetAutoReplyRequest(IPCRequest):
    """Set auto-reply configuration."""

    MSG_TYPE = IPCMessageType.CMD_SET_AUTO_REPLY
    mode: str = "disabled"
    message: str = ""
    cooldown: int = 300

    def to_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "message": self.message,
            "cooldown": self.cooldown,
        }


@dataclass
class CmdSyncMessagesRequest(IPCRequest):
    """Request message sync from propagation node."""

    MSG_TYPE = IPCMessageType.CMD_SYNC_MESSAGES


@dataclass
class QueryPathInfoRequest(IPCRequest):
    """Query path info for a destination."""

    MSG_TYPE = IPCMessageType.QUERY_PATH_INFO
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class QueryPageRequest(IPCRequest):
    """Fetch a page from a NomadNet node or an explicit URL."""

    MSG_TYPE = IPCMessageType.QUERY_PAGE
    destination_hash: str = ""
    path: str = "/page/index.mu"
    url: str = ""
    form_data: dict[str, Any] | None = None
    timeout: float = 30.0

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "destination_hash": self.destination_hash,
            "path": self.path,
            "timeout": self.timeout,
        }
        if self.url:
            payload["url"] = self.url
        if self.form_data is not None:
            payload["form_data"] = self.form_data
        return payload


@dataclass
class QueryPageServerStatusRequest(IPCRequest):
    """Query page server status."""

    MSG_TYPE = IPCMessageType.QUERY_PAGE_SERVER_STATUS


@dataclass
class QueryAttachmentRequest(IPCRequest):
    """Request attachment data for a message."""

    MSG_TYPE = IPCMessageType.QUERY_ATTACHMENT
    message_id: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {"message_id": self.message_id}


@dataclass
class CmdPageDisconnectRequest(IPCRequest):
    """Disconnect link to a NomadNet node."""

    MSG_TYPE = IPCMessageType.CMD_PAGE_DISCONNECT
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class CmdPageRegenerateRequest(IPCRequest):
    """Regenerate the default node info page."""

    MSG_TYPE = IPCMessageType.CMD_PAGE_REGENERATE

    def to_payload(self) -> dict[str, Any]:
        return {}


@dataclass
class CmdPageSaveSiteRequest(IPCRequest):
    """Save a NomadNet node for periodic background crawling."""

    MSG_TYPE = IPCMessageType.CMD_PAGE_SAVE_SITE
    destination_hash: str = ""
    display_name: str = ""
    refresh_interval: int = 3600
    max_depth: int = 3

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination_hash": self.destination_hash,
            "display_name": self.display_name,
            "refresh_interval": self.refresh_interval,
            "max_depth": self.max_depth,
        }


@dataclass
class CmdPageRemoveSiteRequest(IPCRequest):
    """Remove a saved NomadNet site."""

    MSG_TYPE = IPCMessageType.CMD_PAGE_REMOVE_SITE
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class CmdPageListSitesRequest(IPCRequest):
    """List all saved NomadNet sites."""

    MSG_TYPE = IPCMessageType.CMD_PAGE_LIST_SITES

    def to_payload(self) -> dict[str, Any]:
        return {}


@dataclass
class CmdPageCrawlSiteRequest(IPCRequest):
    """Manually trigger a full site crawl."""

    MSG_TYPE = IPCMessageType.CMD_PAGE_CRAWL_SITE
    destination_hash: str = ""
    max_depth: int = 3

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination_hash": self.destination_hash,
            "max_depth": self.max_depth,
        }


@dataclass
class CmdPageGetCachedRequest(IPCRequest):
    """Get a cached page by destination and path."""

    MSG_TYPE = IPCMessageType.CMD_PAGE_GET_CACHED
    destination_hash: str = ""
    path: str = "/page/index.mu"

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination_hash": self.destination_hash,
            "path": self.path,
        }


# -----------------------------------------------------------------------------
# TUI-specific requests (node store, core config, hub, unread)
# -----------------------------------------------------------------------------


@dataclass
class GetNodesRequest(IPCRequest):
    """Request nodes from the persisted node store (for TUI dashboard/exploration)."""

    MSG_TYPE = IPCMessageType.GET_NODES
    styrene_only: bool = False

    def to_payload(self) -> dict[str, Any]:
        return {"styrene_only": self.styrene_only}


@dataclass
class GetCoreConfigRequest(IPCRequest):
    """Request full serialized CoreConfig (round-trippable)."""

    MSG_TYPE = IPCMessageType.GET_CORE_CONFIG

    def to_payload(self) -> dict[str, Any]:
        return {}


@dataclass
class SaveCoreConfigRequest(IPCRequest):
    """Save a modified CoreConfig dict to disk."""

    MSG_TYPE = IPCMessageType.SAVE_CORE_CONFIG
    config_dict: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {"config_dict": self.config_dict}


@dataclass
class GetHubStatusRequest(IPCRequest):
    """Request hub connection status."""

    MSG_TYPE = IPCMessageType.GET_HUB_STATUS

    def to_payload(self) -> dict[str, Any]:
        return {}


@dataclass
class GetUnreadCountsRequest(IPCRequest):
    """Request per-peer unread message counts."""

    MSG_TYPE = IPCMessageType.GET_UNREAD_COUNTS

    def to_payload(self) -> dict[str, Any]:
        return {}


@dataclass
class CmdBlockPeerRequest(IPCRequest):
    """Block a peer — silently drop all future messages from them."""

    MSG_TYPE = IPCMessageType.CMD_BLOCK_PEER
    identity_hash: str = ""
    lxmf_dest_hash: str = ""
    alias: str = ""

    def to_payload(self) -> dict:
        return {
            "identity_hash": self.identity_hash,
            "lxmf_dest_hash": self.lxmf_dest_hash,
            "alias": self.alias,
        }

    @classmethod
    def from_payload(cls, data: dict) -> "CmdBlockPeerRequest":
        return cls(
            identity_hash=data.get("identity_hash", ""),
            lxmf_dest_hash=data.get("lxmf_dest_hash", ""),
            alias=data.get("alias", ""),
        )


@dataclass
class CmdUnblockPeerRequest(IPCRequest):
    """Unblock a previously blocked peer."""

    MSG_TYPE = IPCMessageType.CMD_UNBLOCK_PEER
    identity_hash: str = ""

    def to_payload(self) -> dict:
        return {"identity_hash": self.identity_hash}

    @classmethod
    def from_payload(cls, data: dict) -> "CmdUnblockPeerRequest":
        return cls(identity_hash=data.get("identity_hash", ""))


@dataclass
class QueryBlockedPeersRequest(IPCRequest):
    """List all blocked peers."""

    MSG_TYPE = IPCMessageType.QUERY_BLOCKED_PEERS

    def to_payload(self) -> dict:
        return {}

    @classmethod
    def from_payload(cls, data: dict) -> "QueryBlockedPeersRequest":
        return cls()


@dataclass
class CmdDatalinkEstablishRequest(IPCRequest):
    """Establish a direct data link to a Styrene peer."""

    MSG_TYPE = IPCMessageType.CMD_DATALINK_ESTABLISH
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class CmdDatalinkTeardownRequest(IPCRequest):
    """Tear down a direct data link."""

    MSG_TYPE = IPCMessageType.CMD_DATALINK_TEARDOWN
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class CmdDatalinkStatusRequest(IPCRequest):
    """Get direct link status for a peer."""

    MSG_TYPE = IPCMessageType.CMD_DATALINK_STATUS
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class CmdDatalinkQueryRequest(IPCRequest):
    """Query peer status over an established direct link."""

    MSG_TYPE = IPCMessageType.CMD_DATALINK_QUERY
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class CmdDatalinkSpeedtestRequest(IPCRequest):
    """Run bandwidth test over a direct data link."""

    MSG_TYPE = IPCMessageType.CMD_DATALINK_SPEEDTEST
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class CmdDatalinkMetaRequest(IPCRequest):
    """Request non-identifiable metadata from peer over direct link."""

    MSG_TYPE = IPCMessageType.CMD_DATALINK_META
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class CmdDatalinkInfoRequest(IPCRequest):
    """Request identifiable metadata from peer over direct link.

    The remote node may decline (default) by returning an empty response.
    A None result from the handler means the node chose not to identify.
    """

    MSG_TYPE = IPCMessageType.CMD_DATALINK_INFO
    destination_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"destination_hash": self.destination_hash}


@dataclass
class CmdBoundarySnapshotRequest(IPCRequest):
    """Request a snapshot of the boundary log ring buffer."""

    MSG_TYPE = IPCMessageType.CMD_BOUNDARY_SNAPSHOT

    def to_payload(self) -> dict[str, Any]:
        return {}


@dataclass
class CmdBoundarySnapshotResponse(IPCResponse):
    """Response containing boundary log records."""

    records: list[dict[str, Any]] = field(default_factory=list)

    def to_wire(self) -> tuple["IPCMessageType", dict[str, Any]]:
        return IPCMessageType.RESULT, {"records": self.records}


@dataclass
class CmdRebootDeviceRequest(IPCRequest):
    """Reboot a remote device via RPC."""

    MSG_TYPE = IPCMessageType.CMD_REBOOT_DEVICE
    destination: str = ""
    delay: int = 0
    timeout: float = 10.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "delay": self.delay,
            "timeout": self.timeout,
        }


@dataclass
class CmdSelfUpdateRequest(IPCRequest):
    """Trigger self-update on a remote device via RPC."""

    MSG_TYPE = IPCMessageType.CMD_SELF_UPDATE
    destination: str = ""
    version: str | None = None
    timeout: float = 120.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "version": self.version,
            "timeout": self.timeout,
        }


@dataclass
class CmdSetIdentityRequest(IPCRequest):
    """Set operator identity appearance fields."""

    MSG_TYPE = IPCMessageType.CMD_SET_IDENTITY
    display_name: str = ""
    icon: str = ""
    short_name: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "display_name": self.display_name,
            "icon": self.icon,
        }
        if self.short_name is not None:
            payload["short_name"] = self.short_name
        return payload


@dataclass
class PQCStatusRequest(IPCRequest):
    """Query PQC session status for a peer."""

    MSG_TYPE = IPCMessageType.CMD_PQC_STATUS
    peer_hash: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"peer_hash": self.peer_hash}


@dataclass
class CmdRemoteInboxRequest(IPCRequest):
    """Query inbox (conversation list) on a remote node via RPC."""

    MSG_TYPE = IPCMessageType.CMD_REMOTE_INBOX
    destination: str = ""
    limit: int = 50
    timeout: float = 30.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "limit": self.limit,
            "timeout": self.timeout,
        }


@dataclass
class CmdRemoteMessagesRequest(IPCRequest):
    """Query messages for a peer on a remote node via RPC."""

    MSG_TYPE = IPCMessageType.CMD_REMOTE_MESSAGES
    destination: str = ""
    peer_hash: str = ""
    limit: int = 50
    timeout: float = 30.0

    def to_payload(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "peer_hash": self.peer_hash,
            "limit": self.limit,
            "timeout": self.timeout,
        }


# -----------------------------------------------------------------------------
# Terminal requests
# -----------------------------------------------------------------------------


@dataclass
class CmdTerminalOpenRequest(IPCRequest):
    """Open a terminal session to a remote node."""

    MSG_TYPE = IPCMessageType.CMD_TERMINAL_OPEN
    destination: str = ""
    term_type: str = "xterm-256color"
    rows: int = 24
    cols: int = 80
    shell: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "destination": self.destination,
            "term_type": self.term_type,
            "rows": self.rows,
            "cols": self.cols,
        }
        if self.shell is not None:
            payload["shell"] = self.shell
        return payload


@dataclass
class CmdTerminalInputRequest(IPCRequest):
    """Send input data to a terminal session."""

    MSG_TYPE = IPCMessageType.CMD_TERMINAL_INPUT
    session_id: str = ""
    data_b64: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "data_b64": self.data_b64,
        }


@dataclass
class CmdTerminalResizeRequest(IPCRequest):
    """Resize a terminal session."""

    MSG_TYPE = IPCMessageType.CMD_TERMINAL_RESIZE
    session_id: str = ""
    rows: int = 24
    cols: int = 80

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "rows": self.rows,
            "cols": self.cols,
        }


@dataclass
class CmdTerminalCloseRequest(IPCRequest):
    """Close a terminal session."""

    MSG_TYPE = IPCMessageType.CMD_TERMINAL_CLOSE
    session_id: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {"session_id": self.session_id}


# -----------------------------------------------------------------------------
# Subscription requests
# -----------------------------------------------------------------------------


@dataclass
class SubMessagesRequest(IPCRequest):
    """Subscribe to message events."""

    MSG_TYPE = IPCMessageType.SUB_MESSAGES
    peer_hashes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.peer_hashes:
            payload["peer_hashes"] = self.peer_hashes
        return payload


@dataclass
class SubDevicesRequest(IPCRequest):
    """Subscribe to device events."""

    MSG_TYPE = IPCMessageType.SUB_DEVICES


@dataclass
class SubActivityRequest(IPCRequest):
    """Subscribe to unified activity events."""

    MSG_TYPE = IPCMessageType.SUB_ACTIVITY


@dataclass
class UnsubRequest(IPCRequest):
    """Unsubscribe from events."""

    MSG_TYPE = IPCMessageType.UNSUB
    subscription_type: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.subscription_type:
            payload["subscription_type"] = self.subscription_type
        return payload


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
    short_name: str | None = None
    system_fingerprint: str | None = None
    discovered_via: str | None = None

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
            "short_name": self.short_name,
            "system_fingerprint": self.system_fingerprint,
            "discovered_via": self.discovered_via,
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
            short_name=data.get("short_name"),
            system_fingerprint=data.get("system_fingerprint"),
            discovered_via=data.get("discovered_via"),
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
            short_name=getattr(device, "short_name", None),
            system_fingerprint=getattr(device, "system_fingerprint", None),
            discovered_via=getattr(device, "discovered_via", None),
        )


@dataclass
class IdentityInfo:
    """Local identity information."""

    identity_hash: str
    destination_hash: str
    lxmf_destination_hash: str
    display_name: str = ""
    icon: str = ""
    short_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_hash": self.identity_hash,
            "destination_hash": self.destination_hash,
            "lxmf_destination_hash": self.lxmf_destination_hash,
            "display_name": self.display_name,
            "icon": self.icon,
            "short_name": self.short_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IdentityInfo":
        return cls(
            identity_hash=data.get("identity_hash", ""),
            destination_hash=data.get("destination_hash", ""),
            lxmf_destination_hash=data.get("lxmf_destination_hash", ""),
            display_name=data.get("display_name", ""),
            icon=data.get("icon", ""),
            short_name=data.get("short_name"),
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
    interface_count: int = 0
    hub_status: str = "disabled"
    hub_address: str | None = None
    interfaces: list[dict[str, Any]] = field(default_factory=list)
    propagation_enabled: bool = False
    transport_enabled: bool = False
    active_links: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "uptime": self.uptime,
            "daemon_version": self.daemon_version,
            "rns_initialized": self.rns_initialized,
            "lxmf_initialized": self.lxmf_initialized,
            "device_count": self.device_count,
            "styrene_node_count": self.styrene_node_count,
            "pending_rpc_count": self.pending_rpc_count,
            "interface_count": self.interface_count,
            "hub_status": self.hub_status,
            "hub_address": self.hub_address,
            "interfaces": self.interfaces,
            "propagation_enabled": self.propagation_enabled,
            "transport_enabled": self.transport_enabled,
            "active_links": self.active_links,
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
            interface_count=data.get("interface_count", 0),
            hub_status=data.get("hub_status", "disabled"),
            hub_address=data.get("hub_address"),
            interfaces=data.get("interfaces", []),
            propagation_enabled=data.get("propagation_enabled", False),
            transport_enabled=data.get("transport_enabled", False),
            active_links=data.get("active_links", 0),
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
    available_commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uptime": self.uptime,
            "ip": self.ip,
            "services": self.services,
            "disk_used": self.disk_used,
            "disk_total": self.disk_total,
            "available_commands": self.available_commands,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RemoteStatusInfo":
        return cls(
            uptime=data.get("uptime", 0.0),
            ip=data.get("ip", ""),
            services=data.get("services", []),
            disk_used=data.get("disk_used", 0),
            disk_total=data.get("disk_total", 0),
            available_commands=data.get("available_commands", []),
        )


@dataclass
class RebootResultInfo:
    """Remote reboot result."""

    success: bool
    message: str
    scheduled_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "scheduled_time": self.scheduled_time,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RebootResultInfo":
        return cls(
            success=data.get("success", False),
            message=data.get("message", ""),
            scheduled_time=data.get("scheduled_time"),
        )


@dataclass
class SelfUpdateResultInfo:
    """Remote self-update result."""

    success: bool
    message: str
    old_version: str
    new_version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "old_version": self.old_version,
            "new_version": self.new_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelfUpdateResultInfo":
        return cls(
            success=data.get("success", False),
            message=data.get("message", ""),
            old_version=data.get("old_version", ""),
            new_version=data.get("new_version"),
        )


@dataclass
class MessageEventPayload:
    """Payload for EVENT_MESSAGE notifications.

    Used to notify clients of message-related events such as new messages,
    status changes, delivery confirmations, or failures.
    """

    event_type: str  # "new", "status_changed", "delivered", "failed"
    message_id: int
    peer_hash: str
    content: str | None = None
    timestamp: float = 0.0
    status: str = "pending"
    is_outgoing: bool = False
    delivery_method: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "message_id": self.message_id,
            "peer_hash": self.peer_hash,
            "content": self.content,
            "timestamp": self.timestamp,
            "status": self.status,
            "is_outgoing": self.is_outgoing,
            "delivery_method": self.delivery_method,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "MessageEventPayload":
        return cls(
            event_type=payload.get("event_type", ""),
            message_id=payload.get("message_id", 0),
            peer_hash=payload.get("peer_hash", ""),
            content=payload.get("content"),
            timestamp=payload.get("timestamp", 0.0),
            status=payload.get("status", "pending"),
            is_outgoing=payload.get("is_outgoing", False),
            delivery_method=payload.get("delivery_method"),
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
    elif msg_type == IPCMessageType.QUERY_SEARCH_MESSAGES:
        return QuerySearchMessagesRequest(
            query=payload.get("query", ""),
            peer_hash=payload.get("peer_hash"),
            limit=payload.get("limit", 50),
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
    elif msg_type == IPCMessageType.QUERY_ATTACHMENT:
        return QueryAttachmentRequest(
            message_id=payload.get("message_id", 0),
        )
    elif msg_type == IPCMessageType.CMD_SEND_CHAT:
        # Coerce values to correct types (handle null from msgpack)
        peer_hash = payload.get("peer_hash")
        content = payload.get("content")
        return CmdSendChatRequest(
            peer_hash=peer_hash if isinstance(peer_hash, str) else "",
            content=content if isinstance(content, str) else "",
            title=payload.get("title"),
            delivery_method=payload.get("delivery_method", "auto"),
            reply_to_hash=payload.get("reply_to_hash"),
            attachment_data_b64=payload.get("attachment_data_b64"),
            attachment_filename=payload.get("attachment_filename"),
            attachment_mime=payload.get("attachment_mime"),
        )
    elif msg_type == IPCMessageType.CMD_MARK_READ:
        return CmdMarkReadRequest(peer_hash=payload.get("peer_hash", ""))
    elif msg_type == IPCMessageType.CMD_DELETE_CONVERSATION:
        return CmdDeleteConversationRequest(peer_hash=payload.get("peer_hash", ""))
    elif msg_type == IPCMessageType.CMD_DELETE_MESSAGE:
        return CmdDeleteMessageRequest(message_id=payload.get("message_id", 0))
    elif msg_type == IPCMessageType.CMD_RETRY_MESSAGE:
        return CmdRetryMessageRequest(message_id=payload.get("message_id", 0))
    elif msg_type == IPCMessageType.QUERY_CONTACTS:
        return QueryContactsRequest()
    elif msg_type == IPCMessageType.QUERY_RESOLVE_NAME:
        return QueryResolveNameRequest(
            name=payload.get("name", ""),
            prefix_match=payload.get("prefix_match", True),
        )
    elif msg_type == IPCMessageType.CMD_SET_CONTACT:
        return CmdSetContactRequest(
            peer_hash=payload.get("peer_hash", ""),
            alias=payload.get("alias", ""),
            notes=payload.get("notes"),
        )
    elif msg_type == IPCMessageType.CMD_REMOVE_CONTACT:
        return CmdRemoveContactRequest(peer_hash=payload.get("peer_hash", ""))
    elif msg_type == IPCMessageType.QUERY_AUTO_REPLY:
        return QueryAutoReplyRequest()
    elif msg_type == IPCMessageType.CMD_SET_AUTO_REPLY:
        return CmdSetAutoReplyRequest(
            mode=payload.get("mode", "disabled"),
            message=payload.get("message", ""),
            cooldown=payload.get("cooldown", 300),
        )
    elif msg_type == IPCMessageType.CMD_SYNC_MESSAGES:
        return CmdSyncMessagesRequest()
    elif msg_type == IPCMessageType.QUERY_PATH_INFO:
        return QueryPathInfoRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.QUERY_PAGE:
        return QueryPageRequest(
            destination_hash=payload.get("destination_hash", ""),
            path=payload.get("path", "/page/index.mu"),
            form_data=payload.get("form_data"),
            timeout=payload.get("timeout", 30.0),
        )
    elif msg_type == IPCMessageType.QUERY_PAGE_SERVER_STATUS:
        return QueryPageServerStatusRequest()
    elif msg_type == IPCMessageType.CMD_PAGE_DISCONNECT:
        return CmdPageDisconnectRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_PAGE_REGENERATE:
        return CmdPageRegenerateRequest()
    elif msg_type == IPCMessageType.CMD_PAGE_SAVE_SITE:
        return CmdPageSaveSiteRequest(
            destination_hash=payload.get("destination_hash", ""),
            display_name=payload.get("display_name", ""),
            refresh_interval=payload.get("refresh_interval", 3600),
            max_depth=payload.get("max_depth", 3),
        )
    elif msg_type == IPCMessageType.CMD_PAGE_REMOVE_SITE:
        return CmdPageRemoveSiteRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_PAGE_LIST_SITES:
        return CmdPageListSitesRequest()
    elif msg_type == IPCMessageType.CMD_PAGE_CRAWL_SITE:
        return CmdPageCrawlSiteRequest(
            destination_hash=payload.get("destination_hash", ""),
            max_depth=payload.get("max_depth", 3),
        )
    elif msg_type == IPCMessageType.CMD_PAGE_GET_CACHED:
        return CmdPageGetCachedRequest(
            destination_hash=payload.get("destination_hash", ""),
            path=payload.get("path", "/page/index.mu"),
        )
    elif msg_type == IPCMessageType.CMD_REBOOT_DEVICE:
        return CmdRebootDeviceRequest(
            destination=payload.get("destination", ""),
            delay=payload.get("delay", 0),
            timeout=payload.get("timeout", 10.0),
        )
    elif msg_type == IPCMessageType.CMD_SELF_UPDATE:
        return CmdSelfUpdateRequest(
            destination=payload.get("destination", ""),
            version=payload.get("version"),
            timeout=payload.get("timeout", 120.0),
        )
    elif msg_type == IPCMessageType.CMD_SET_IDENTITY:
        return CmdSetIdentityRequest(
            display_name=payload.get("display_name", ""),
            icon=payload.get("icon", ""),
            short_name=payload.get("short_name"),
        )
    elif msg_type == IPCMessageType.CMD_REMOTE_INBOX:
        return CmdRemoteInboxRequest(
            destination=payload.get("destination", ""),
            limit=payload.get("limit", 50),
            timeout=payload.get("timeout", 30.0),
        )
    elif msg_type == IPCMessageType.CMD_REMOTE_MESSAGES:
        return CmdRemoteMessagesRequest(
            destination=payload.get("destination", ""),
            peer_hash=payload.get("peer_hash", ""),
            limit=payload.get("limit", 50),
            timeout=payload.get("timeout", 30.0),
        )
    elif msg_type == IPCMessageType.CMD_PQC_STATUS:
        return PQCStatusRequest(
            peer_hash=payload.get("peer_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_TERMINAL_OPEN:
        return CmdTerminalOpenRequest(
            destination=payload.get("destination", ""),
            term_type=payload.get("term_type", "xterm-256color"),
            rows=payload.get("rows", 24),
            cols=payload.get("cols", 80),
            shell=payload.get("shell"),
        )
    elif msg_type == IPCMessageType.CMD_TERMINAL_INPUT:
        return CmdTerminalInputRequest(
            session_id=payload.get("session_id", ""),
            data_b64=payload.get("data_b64", ""),
        )
    elif msg_type == IPCMessageType.CMD_TERMINAL_RESIZE:
        return CmdTerminalResizeRequest(
            session_id=payload.get("session_id", ""),
            rows=payload.get("rows", 24),
            cols=payload.get("cols", 80),
        )
    elif msg_type == IPCMessageType.CMD_TERMINAL_CLOSE:
        return CmdTerminalCloseRequest(
            session_id=payload.get("session_id", ""),
        )
    elif msg_type == IPCMessageType.GET_NODES:
        return GetNodesRequest(styrene_only=payload.get("styrene_only", False))
    elif msg_type == IPCMessageType.GET_CORE_CONFIG:
        return GetCoreConfigRequest()
    elif msg_type == IPCMessageType.SAVE_CORE_CONFIG:
        return SaveCoreConfigRequest(config_dict=payload.get("config_dict", {}))
    elif msg_type == IPCMessageType.GET_HUB_STATUS:
        return GetHubStatusRequest()
    elif msg_type == IPCMessageType.GET_UNREAD_COUNTS:
        return GetUnreadCountsRequest()
    elif msg_type == IPCMessageType.CMD_BLOCK_PEER:
        return CmdBlockPeerRequest.from_payload(payload)
    elif msg_type == IPCMessageType.CMD_UNBLOCK_PEER:
        return CmdUnblockPeerRequest.from_payload(payload)
    elif msg_type == IPCMessageType.QUERY_BLOCKED_PEERS:
        return QueryBlockedPeersRequest.from_payload(payload)
    elif msg_type == IPCMessageType.CMD_DATALINK_ESTABLISH:
        return CmdDatalinkEstablishRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_DATALINK_TEARDOWN:
        return CmdDatalinkTeardownRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_DATALINK_STATUS:
        return CmdDatalinkStatusRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_DATALINK_QUERY:
        return CmdDatalinkQueryRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_DATALINK_SPEEDTEST:
        return CmdDatalinkSpeedtestRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_DATALINK_META:
        return CmdDatalinkMetaRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_DATALINK_INFO:
        return CmdDatalinkInfoRequest(
            destination_hash=payload.get("destination_hash", ""),
        )
    elif msg_type == IPCMessageType.CMD_BOUNDARY_SNAPSHOT:
        return CmdBoundarySnapshotRequest()
    elif msg_type == IPCMessageType.SUB_MESSAGES:
        return SubMessagesRequest(peer_hashes=payload.get("peer_hashes", []))
    elif msg_type == IPCMessageType.SUB_DEVICES:
        return SubDevicesRequest()
    elif msg_type == IPCMessageType.SUB_ACTIVITY:
        return SubActivityRequest()
    elif msg_type == IPCMessageType.UNSUB:
        return UnsubRequest(subscription_type=payload.get("subscription_type", ""))
    else:
        raise ValueError(f"Unknown request type: {msg_type}")
