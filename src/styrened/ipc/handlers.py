"""IPC request handlers for control server.

Implements handlers for all IPC request types, accessing daemon services
to fulfill queries and execute commands.

Usage:
    from styrened.ipc.handlers import IPCHandlers

    handlers = IPCHandlers(daemon)
    response = await handlers.handle_query_devices(request)
"""
from __future__ import annotations

import asyncio
import base64
import logging
import re
import threading
import time
from typing import TYPE_CHECKING, Any

# Constants for input validation
MAX_CHAT_CONTENT_LENGTH = 65536  # 64KB - reasonable limit for chat messages
MAX_TITLE_LENGTH = 256  # Max title length
MAX_MESSAGE_LIMIT = 1000  # Max messages per query
HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{16,32}$")  # 16-32 hex chars (truncated or full)
LXMF_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")  # 64 hex chars for LXMF message hash
VALID_DELIVERY_METHODS = {"auto", "direct", "propagated"}

try:
    import LXMF

    LXMF_AVAILABLE = True
except ImportError:
    LXMF_AVAILABLE = False

from styrened.ipc.messages import (
    CmdDeleteConversationRequest,
    CmdDeleteMessageRequest,
    CmdDeviceStatusRequest,
    CmdExecRequest,
    CmdMarkReadRequest,
    CmdPageDisconnectRequest,
    CmdRebootDeviceRequest,
    CmdRemoteInboxRequest,
    CmdRemoteMessagesRequest,
    CmdRemoveContactRequest,
    CmdRetryMessageRequest,
    CmdSelfUpdateRequest,
    CmdSendChatRequest,
    CmdSendRequest,
    CmdSetAutoReplyRequest,
    CmdSetContactRequest,
    CmdSetIdentityRequest,
    CmdTerminalCloseRequest,
    CmdTerminalInputRequest,
    CmdTerminalOpenRequest,
    CmdTerminalResizeRequest,
    DaemonStatus,
    DeviceInfo,
    ErrorResponse,
    ExecResultInfo,
    IdentityInfo,
    IPCRequest,
    IPCResponse,
    PongResponse,
    PQCStatusRequest,
    QueryAttachmentRequest,
    QueryContactsRequest,
    QueryConversationsRequest,
    QueryDevicesRequest,
    QueryMessagesRequest,
    QueryPageRequest,
    QueryPathInfoRequest,
    QueryResolveNameRequest,
    QuerySearchMessagesRequest,
    RebootResultInfo,
    RemoteStatusInfo,
    ResultResponse,
    SelfUpdateResultInfo,
)

if TYPE_CHECKING:
    from styrened.daemon import StyreneDaemon

logger = logging.getLogger(__name__)


class IPCHandlers:
    """Request handlers for IPC control server.

    Each handler method corresponds to an IPC message type and returns
    an appropriate response.

    Attributes:
        daemon: Reference to the StyreneDaemon instance (may be None during tests).
    """

    def __init__(self, daemon: StyreneDaemon | None) -> None:
        """Initialize handlers.

        Args:
            daemon: StyreneDaemon instance for accessing services. May be None
                during testing or partial initialization.
        """
        self.daemon = daemon
        # Terminal session tracking: session_id_hex -> (TerminalClientSession, client_ref)
        self._terminal_sessions: dict[str, Any] = {}
        # Cache for peer hash resolution (identity mappings are stable)
        self._peer_hash_cache: dict[str, list[str]] = {}

    def _check_daemon(self) -> ErrorResponse | None:
        """Check if daemon is available.

        Returns:
            ErrorResponse if daemon is not available, None otherwise.
        """
        if not self.daemon:
            return ErrorResponse.internal_error("Daemon not initialized")
        return None

    def _check_rpc_client(self) -> ErrorResponse | None:
        """Check if RPC client is available.

        Returns:
            ErrorResponse if RPC client is not available, None otherwise.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None  # For type narrowing after _check_daemon
        if not self.daemon._rpc_client:
            return ErrorResponse.internal_error("RPC client not initialized")
        return None

    # -------------------------------------------------------------------------
    # Query handlers
    # -------------------------------------------------------------------------

    async def handle_ping(self, request: IPCRequest) -> IPCResponse:
        """Handle PING request.

        Args:
            request: PingRequest instance.

        Returns:
            PongResponse with daemon version.
        """
        from styrened import __version__

        return PongResponse(daemon_version=__version__)

    async def handle_query_devices(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_DEVICES request.

        Args:
            request: QueryDevicesRequest instance.

        Returns:
            ResultResponse with list of discovered devices.
        """
        from styrened.services.node_store import get_node_store
        from styrened.services.reticulum import discover_devices

        req = request if isinstance(request, QueryDevicesRequest) else QueryDevicesRequest()

        try:
            # Get devices from discovery (in-memory) and node store (persisted)
            devices = discover_devices()

            # Also check node store for persisted devices
            node_store = get_node_store()
            if node_store:
                if req.styrene_only:
                    stored = node_store.get_styrene_nodes()
                else:
                    stored = node_store.get_all_nodes()

                # Merge stored devices (prefer in-memory for freshness)
                seen = {d.destination_hash for d in devices}
                for stored_device in stored:
                    if stored_device.destination_hash not in seen:
                        devices.append(stored_device)

            # Filter if styrene_only requested
            if req.styrene_only:
                devices = [d for d in devices if d.is_styrene_node]

            # Convert to DeviceInfo
            device_list = [DeviceInfo.from_mesh_device(d).to_dict() for d in devices]

            return ResultResponse(data={"devices": device_list})

        except Exception as e:
            logger.exception(f"Error querying devices: {e}")
            return ErrorResponse.internal_error(f"Failed to query devices: {e}")

    async def handle_query_identity(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_IDENTITY request.

        Args:
            request: QueryIdentityRequest instance.

        Returns:
            ResultResponse with local identity information.
        """
        from styrened.services.lxmf_service import get_lxmf_service
        from styrened.services.reticulum import get_operator_identity

        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None  # For type narrowing

        try:
            identity_hash = get_operator_identity()
            if not identity_hash:
                return ErrorResponse.not_found("No operator identity configured")

            # Get destination hashes
            destination_hash = ""
            lxmf_destination_hash = ""

            if self.daemon._operator_destination:
                destination_hash = self.daemon._operator_destination.hexhash

            lxmf_service = get_lxmf_service()
            if lxmf_service and lxmf_service._destination:
                lxmf_destination_hash = lxmf_service._destination.hexhash

            # Populate appearance fields from config
            display_name = ""
            icon = ""
            short_name = None
            if hasattr(self.daemon.config, "identity"):
                id_cfg = self.daemon.config.identity
                display_name = getattr(id_cfg, "display_name", "")
                icon = getattr(id_cfg, "icon", "")
                short_name = getattr(id_cfg, "short_name", None)

            info = IdentityInfo(
                identity_hash=identity_hash,
                destination_hash=destination_hash,
                lxmf_destination_hash=lxmf_destination_hash,
                display_name=display_name,
                icon=icon,
                short_name=short_name,
            )

            return ResultResponse(data=info.to_dict())

        except Exception as e:
            logger.exception(f"Error querying identity: {e}")
            return ErrorResponse.internal_error(f"Failed to query identity: {e}")

    async def handle_query_status(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_STATUS request.

        Args:
            request: QueryStatusRequest instance.

        Returns:
            ResultResponse with daemon status information.
        """
        from styrened import __version__
        from styrened.services.reticulum import discover_devices

        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None  # For type narrowing

        try:
            # Calculate uptime
            uptime = time.time() - self.daemon._start_time

            # Check service status
            rns_initialized = self.daemon.lifecycle._initialized
            lxmf_initialized = False
            if hasattr(self.daemon, "_lxmf_service") and self.daemon._lxmf_service:
                lxmf_initialized = True

            # Count devices
            devices = discover_devices()
            device_count = len(devices)
            styrene_count = sum(1 for d in devices if d.is_styrene_node)

            # Count pending RPC requests
            pending_rpc = 0
            if self.daemon._rpc_client:
                pending_rpc = self.daemon._rpc_client.pending_count

            # Count RNS interfaces and collect details
            interface_count = 0
            interfaces: list[dict[str, Any]] = []
            transport_enabled = False
            active_links = 0
            try:
                import RNS

                if hasattr(RNS.Transport, "interfaces") and RNS.Transport.interfaces:
                    interface_count = len(RNS.Transport.interfaces)
                    for iface in RNS.Transport.interfaces:
                        interfaces.append({
                            "name": getattr(iface, "name", "unnamed"),
                            "type": type(iface).__name__,
                            "online": getattr(iface, "online", True),
                        })

                transport_enabled = getattr(RNS.Transport, "transport_enabled", False)
                active_links = len(getattr(RNS.Transport, "active_links", []))
            except Exception:
                pass

            # Hub status
            hub_status = "disabled"
            hub_address: str | None = None
            try:
                from styrened.services.hub_connection import get_hub_connection

                hub = get_hub_connection()
                hub_status = hub.status.value
                hub_address = hub.hub_address
            except Exception:
                pass

            # LXMF propagation state
            propagation_enabled = False
            try:
                if self.daemon._lxmf_service and self.daemon._lxmf_service.router:
                    propagation_enabled = getattr(
                        self.daemon._lxmf_service.router, "propagation_enabled", False
                    )
            except Exception:
                pass

            status = DaemonStatus(
                uptime=uptime,
                daemon_version=__version__,
                rns_initialized=rns_initialized,
                lxmf_initialized=lxmf_initialized,
                device_count=device_count,
                styrene_node_count=styrene_count,
                pending_rpc_count=pending_rpc,
                interface_count=interface_count,
                hub_status=hub_status,
                hub_address=hub_address,
                interfaces=interfaces,
                propagation_enabled=propagation_enabled,
                transport_enabled=transport_enabled,
                active_links=active_links,
            )

            return ResultResponse(data=status.to_dict())

        except Exception as e:
            logger.exception(f"Error querying status: {e}")
            return ErrorResponse.internal_error(f"Failed to query status: {e}")

    async def handle_query_config(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_CONFIG request.

        Args:
            request: QueryConfigRequest instance.

        Returns:
            ResultResponse with current configuration (sanitized).
        """
        if not self.daemon:
            return ErrorResponse.internal_error("Daemon not initialized")

        try:
            # Return a sanitized view of config (no sensitive paths)
            config = self.daemon.config
            config_dict = {
                "reticulum": {
                    "mode": config.reticulum.mode.value,
                    "announce_interval": config.reticulum.announce_interval,
                    "hub_enabled": config.reticulum.hub_enabled,
                },
                "rpc": {
                    "enabled": config.rpc.enabled,
                    "relay_mode": config.rpc.relay_mode,
                    "allow_command_execution": config.rpc.allow_command_execution,
                },
                "discovery": {
                    "enabled": config.discovery.enabled,
                    "auto_announce": config.discovery.auto_announce,
                },
                "chat": {
                    "enabled": config.chat.enabled,
                    "auto_reply_mode": config.chat.auto_reply_mode.value,
                    "auto_reply_cooldown": config.chat.auto_reply_cooldown,
                    "persist_messages": config.chat.persist_messages,
                },
                "api": {
                    "enabled": config.api.enabled,
                    "port": config.api.port,
                },
            }

            # Include identity section if available
            if hasattr(config, "identity"):
                config_dict["identity"] = {
                    "display_name": config.identity.display_name,
                    "icon": config.identity.icon,
                    "short_name": config.identity.short_name,
                }

            return ResultResponse(data={"config": config_dict})

        except Exception as e:
            logger.exception(f"Error querying config: {e}")
            return ErrorResponse.internal_error(f"Failed to query config: {e}")

    # -------------------------------------------------------------------------
    # TUI-specific handlers (nodes, core config, hub, unread)
    # -------------------------------------------------------------------------

    async def handle_get_nodes(self, request: IPCRequest) -> IPCResponse:
        """Handle GET_NODES request.

        Returns nodes from the persisted node store, not the in-memory
        discovery cache.  Used by TUI dashboard and exploration screens.

        Args:
            request: GetNodesRequest instance.

        Returns:
            ResultResponse with list of node dicts.
        """
        from styrened.ipc.messages import GetNodesRequest
        from styrened.services.node_store import get_node_store

        req = request if isinstance(request, GetNodesRequest) else GetNodesRequest()

        try:
            node_store = get_node_store()
            if node_store is None:
                return ResultResponse(data={"nodes": []})

            if req.styrene_only:
                nodes = node_store.get_styrene_nodes()
            else:
                nodes = node_store.get_all_nodes()

            node_list = [DeviceInfo.from_mesh_device(n).to_dict() for n in nodes]
            return ResultResponse(data={"nodes": node_list})

        except Exception as e:
            logger.exception(f"Error getting nodes: {e}")
            return ErrorResponse.internal_error(f"Failed to get nodes: {e}")

    async def handle_get_core_config(self, request: IPCRequest) -> IPCResponse:
        """Handle GET_CORE_CONFIG request.

        Returns the full serialized CoreConfig dict (round-trippable via
        load_core_config / save_core_config).  Unlike QUERY_CONFIG which
        returns a sanitized subset, this returns everything.

        Args:
            request: GetCoreConfigRequest instance.

        Returns:
            ResultResponse with full config dict.
        """
        try:
            from styrened.services.config import load_core_config, serialize_config

            config = load_core_config()
            config_dict = serialize_config(config)
            return ResultResponse(data={"config": config_dict})

        except Exception as e:
            logger.exception(f"Error getting core config: {e}")
            return ErrorResponse.internal_error(f"Failed to get core config: {e}")

    async def handle_save_core_config(self, request: IPCRequest) -> IPCResponse:
        """Handle SAVE_CORE_CONFIG request.

        Deserializes the provided config dict, writes it to disk via
        save_core_config, and reloads the daemon config.

        Args:
            request: SaveCoreConfigRequest instance.

        Returns:
            ResultResponse with {saved: true}.
        """
        from styrened.ipc.messages import SaveCoreConfigRequest

        req = request if isinstance(request, SaveCoreConfigRequest) else SaveCoreConfigRequest()

        if not req.config_dict:
            return ErrorResponse.invalid_request("config_dict is required")

        try:
            import tempfile
            from pathlib import Path

            import yaml

            from styrened import paths
            from styrened.services.config import load_core_config, save_core_config
            from styrened.services.reticulum import generate_rns_config

            # Validate by round-tripping through CoreConfig.
            # Write to a temp file, parse with load_core_config (full validation),
            # then persist the validated object canonically. This ensures
            # malformed dicts cannot corrupt the config file.
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".yaml", delete=False
                ) as tmp:
                    yaml.dump(req.config_dict, tmp, default_flow_style=False)
                    tmp_path = Path(tmp.name)
                try:
                    parsed_config = load_core_config(tmp_path)
                finally:
                    tmp_path.unlink(missing_ok=True)
            except Exception as e:
                return ErrorResponse.invalid_request(f"Invalid config: {e}")

            config_path = paths.config_file()
            save_core_config(parsed_config, config_path)

            # Keep Reticulum config generation daemon-side so TUI screens do not
            # need to import transport internals just to persist network changes.
            rns_config_path = Path.home() / ".reticulum" / "config"
            rns_config_path.parent.mkdir(parents=True, exist_ok=True)
            rns_config_path.write_text(generate_rns_config(parsed_config))

            # Emit config_changed to EventBus
            if self.daemon and hasattr(self.daemon, "event_bus"):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        self.daemon.event_bus.emit("config_changed", action="saved")
                    )
                except RuntimeError:
                    pass

            return ResultResponse(data={"saved": True})

        except Exception as e:
            logger.exception(f"Error saving core config: {e}")
            return ErrorResponse.internal_error(f"Failed to save core config: {e}")

    async def handle_get_hub_status(self, request: IPCRequest) -> IPCResponse:
        """Handle GET_HUB_STATUS request.

        Returns hub connection status as a dict.

        Args:
            request: GetHubStatusRequest instance.

        Returns:
            ResultResponse with hub status dict.
        """
        try:
            from styrened.services.hub_connection import get_hub_connection

            hub = get_hub_connection()
            hub_dict = {
                "is_connected": hub.is_connected,
                "hub_address": hub.hub_address,
                "status": hub.status.value if hasattr(hub, "status") else "unknown",
            }
            # Include hub_destination hash if available
            if hub.hub_destination:
                hub_dict["hub_destination_hash"] = hub.hub_destination.hexhash
            return ResultResponse(data=hub_dict)

        except Exception as e:
            logger.exception(f"Error getting hub status: {e}")
            return ErrorResponse.internal_error(f"Failed to get hub status: {e}")

    async def handle_get_unread_counts(self, request: IPCRequest) -> IPCResponse:
        """Handle GET_UNREAD_COUNTS request.

        Returns per-peer unread message counts from the conversation service.

        Args:
            request: GetUnreadCountsRequest instance.

        Returns:
            ResultResponse with {counts: {peer_hash: count, ...}}.
        """
        try:
            err = self._check_daemon()
            if err:
                return err
            assert self.daemon is not None

            if not self.daemon._conversation_service:
                return ResultResponse(data={"counts": {}})

            # Access the internal unread counts dict from conversation service
            counts = dict(self.daemon._conversation_service._unread_counts)
            return ResultResponse(data={"counts": counts})

        except Exception as e:
            logger.exception(f"Error getting unread counts: {e}")
            return ErrorResponse.internal_error(f"Failed to get unread counts: {e}")

    async def handle_get_adapter_state(self, request: IPCRequest) -> IPCResponse:
        """Handle GET_ADAPTER_STATE request.

        Returns current state of all registered adapters so TUI clients can
        seed their adapter status display immediately on connect without
        waiting for the next probe cycle (up to 30 s).

        Returns:
            ResultResponse with {adapters: [{name, state, details}, ...]}.
        """
        try:
            err = self._check_daemon()
            if err:
                return err
            assert self.daemon is not None

            registry = getattr(self.daemon, "_adapter_registry", None)
            if registry is None:
                return ResultResponse(data={"adapters": []})

            adapters = []
            for aid in list(registry.adapter_ids()):
                record = registry.get(aid)
                if record is None:
                    continue
                adapters.append({
                    "adapter_name": aid,
                    "state": record.state.value,
                    "details": getattr(record, "details", {}),
                })
            return ResultResponse(data={"adapters": adapters})

        except Exception as e:
            logger.exception(f"Error getting adapter state: {e}")
            return ErrorResponse.internal_error(f"Failed to get adapter state: {e}")

    # -------------------------------------------------------------------------
    # Command handlers
    # -------------------------------------------------------------------------

    async def handle_cmd_send(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_SEND request.

        Args:
            request: CmdSendRequest instance.

        Returns:
            ResultResponse with send status.
        """
        from styrened.services.lxmf_service import get_lxmf_service

        req = request if isinstance(request, CmdSendRequest) else CmdSendRequest()

        if not req.destination:
            return ErrorResponse.invalid_request("destination is required")
        if not req.message:
            return ErrorResponse.invalid_request("message is required")

        try:
            lxmf_service = get_lxmf_service()
            if not lxmf_service:
                return ErrorResponse.internal_error("LXMF service not initialized")

            payload: dict[str, object] = {
                "type": req.protocol,
                "protocol": req.protocol,
                "content": req.message,
            }

            loop = asyncio.get_running_loop()
            if req.retry:
                success = await loop.run_in_executor(
                    None,
                    lambda: lxmf_service.send_with_retry(
                        req.destination,
                        payload,
                        max_wait=req.timeout,
                    ),
                )
            else:
                result = await loop.run_in_executor(
                    None,
                    lambda: lxmf_service.send_message(req.destination, payload),
                )
                success = result is not None

            return ResultResponse(data={"sent": success})

        except Exception as e:
            logger.exception(f"Error sending message: {e}")
            return ErrorResponse.internal_error(f"Failed to send message: {e}")

    async def handle_cmd_exec(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_EXEC request.

        Args:
            request: CmdExecRequest instance.

        Returns:
            ResultResponse with execution result.
        """
        req = request if isinstance(request, CmdExecRequest) else CmdExecRequest()

        if not req.destination:
            return ErrorResponse.invalid_request("destination is required")
        if not req.command:
            return ErrorResponse.invalid_request("command is required")

        try:
            err = self._check_rpc_client()
            if err:
                return err
            assert self.daemon is not None and self.daemon._rpc_client is not None

            result = await self.daemon._rpc_client.call_exec(
                destination=req.destination,
                command=req.command,
                args=req.args,
                timeout=req.timeout,
            )

            exec_info = ExecResultInfo(
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )

            return ResultResponse(data=exec_info.to_dict())

        except TimeoutError:
            return ErrorResponse.timeout(f"Exec timed out after {req.timeout}s")
        except Exception as e:
            logger.exception(f"Error executing command: {e}")
            return ErrorResponse.internal_error(f"Failed to execute command: {e}")

    async def handle_cmd_announce(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_ANNOUNCE request.

        Args:
            request: CmdAnnounceRequest instance.

        Returns:
            ResultResponse with announce status.
        """
        try:
            err = self._check_daemon()
            if err:
                return err
            assert self.daemon is not None  # For type narrowing
            if not self.daemon._operator_destination:
                return ErrorResponse.internal_error("Operator destination not initialized")

            # Trigger announce
            self.daemon._announce()

            return ResultResponse(
                data={
                    "announced": True,
                    "destination_hash": self.daemon._operator_destination.hexhash,
                }
            )

        except Exception as e:
            logger.exception(f"Error announcing: {e}")
            return ErrorResponse.internal_error(f"Failed to announce: {e}")

    async def handle_cmd_device_status(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_DEVICE_STATUS request.

        Queries status of a specific remote device via RPC.

        Args:
            request: CmdDeviceStatusRequest instance.

        Returns:
            ResultResponse with remote device status.
        """
        req = request if isinstance(request, CmdDeviceStatusRequest) else CmdDeviceStatusRequest()

        if not req.destination:
            return ErrorResponse.invalid_request("destination is required")

        try:
            err = self._check_rpc_client()
            if err:
                return err
            assert self.daemon is not None and self.daemon._rpc_client is not None

            result = await self.daemon._rpc_client.call_status(
                destination=req.destination,
                timeout=req.timeout,
            )

            status_info = RemoteStatusInfo(
                uptime=result.uptime,
                ip=result.ip,
                services=result.services,
                disk_used=result.disk_used,
                disk_total=result.disk_total,
                available_commands=result.available_commands or [],
            )

            return ResultResponse(data=status_info.to_dict())

        except TimeoutError:
            return ErrorResponse.timeout(f"Status request timed out after {req.timeout}s")
        except Exception as e:
            logger.exception(f"Error querying device status: {e}")
            return ErrorResponse.internal_error(f"Failed to query device status: {e}")

    async def handle_cmd_reboot_device(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_REBOOT_DEVICE request.

        Reboots a specific remote device via RPC.

        Args:
            request: CmdRebootDeviceRequest instance.

        Returns:
            ResultResponse with reboot result.
        """
        req = (
            request
            if isinstance(request, CmdRebootDeviceRequest)
            else CmdRebootDeviceRequest()
        )

        if not req.destination:
            return ErrorResponse.invalid_request("destination is required")

        try:
            err = self._check_rpc_client()
            if err:
                return err
            assert self.daemon is not None and self.daemon._rpc_client is not None

            result = await self.daemon._rpc_client.call_reboot(
                destination=req.destination,
                delay=req.delay,
                timeout=req.timeout,
            )

            reboot_info = RebootResultInfo(
                success=result.success,
                message=result.message,
                scheduled_time=result.scheduled_time,
            )

            return ResultResponse(data=reboot_info.to_dict())

        except TimeoutError:
            return ErrorResponse.timeout(f"Reboot request timed out after {req.timeout}s")
        except Exception as e:
            logger.exception(f"Error rebooting device: {e}")
            return ErrorResponse.internal_error(f"Failed to reboot device: {e}")

    async def handle_cmd_self_update(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_SELF_UPDATE request.

        Triggers self-update on a remote device via RPC.

        Args:
            request: CmdSelfUpdateRequest instance.

        Returns:
            ResultResponse with update result.
        """
        req = (
            request
            if isinstance(request, CmdSelfUpdateRequest)
            else CmdSelfUpdateRequest()
        )

        if not req.destination:
            return ErrorResponse.invalid_request("destination is required")

        try:
            err = self._check_rpc_client()
            if err:
                return err
            assert self.daemon is not None and self.daemon._rpc_client is not None

            result = await self.daemon._rpc_client.call_self_update(
                destination=req.destination,
                version=req.version,
                timeout=req.timeout,
            )

            update_info = SelfUpdateResultInfo(
                success=result.success,
                message=result.message,
                old_version=result.old_version,
                new_version=result.new_version,
            )

            return ResultResponse(data=update_info.to_dict())

        except TimeoutError:
            return ErrorResponse.timeout(f"Self-update request timed out after {req.timeout}s")
        except Exception as e:
            logger.exception(f"Error updating device: {e}")
            return ErrorResponse.internal_error(f"Failed to update device: {e}")

    # -------------------------------------------------------------------------
    # Remote inbox handlers (RPC over LXMF)
    # -------------------------------------------------------------------------

    async def handle_cmd_remote_inbox(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_REMOTE_INBOX request.

        Queries a remote node's inbox via RPC over LXMF.

        Args:
            request: CmdRemoteInboxRequest instance.

        Returns:
            ResultResponse with remote conversation list.
        """
        req = (
            request
            if isinstance(request, CmdRemoteInboxRequest)
            else CmdRemoteInboxRequest()
        )

        if not req.destination:
            return ErrorResponse.invalid_request("destination is required")

        try:
            err = self._check_rpc_client()
            if err:
                return err
            assert self.daemon is not None and self.daemon._rpc_client is not None

            result = await self.daemon._rpc_client.call_inbox(
                destination=req.destination,
                limit=req.limit,
                timeout=req.timeout,
            )

            return ResultResponse(data={"conversations": result.conversations})

        except Exception as e:
            if "timed out" in str(e):
                return ErrorResponse.timeout(f"Remote inbox query timed out after {req.timeout}s")
            logger.exception(f"Error querying remote inbox: {e}")
            return ErrorResponse.internal_error(f"Failed to query remote inbox: {e}")

    async def handle_cmd_remote_messages(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_REMOTE_MESSAGES request.

        Queries messages for a specific peer on a remote node via RPC over LXMF.

        Args:
            request: CmdRemoteMessagesRequest instance.

        Returns:
            ResultResponse with remote message list.
        """
        req = (
            request
            if isinstance(request, CmdRemoteMessagesRequest)
            else CmdRemoteMessagesRequest()
        )

        if not req.destination:
            return ErrorResponse.invalid_request("destination is required")
        if not req.peer_hash:
            return ErrorResponse.invalid_request("peer_hash is required")

        try:
            err = self._check_rpc_client()
            if err:
                return err
            assert self.daemon is not None and self.daemon._rpc_client is not None

            result = await self.daemon._rpc_client.call_messages(
                destination=req.destination,
                peer_hash=req.peer_hash,
                limit=req.limit,
                timeout=req.timeout,
            )

            return ResultResponse(data={"messages": result.messages})

        except Exception as e:
            if "timed out" in str(e):
                return ErrorResponse.timeout(
                    f"Remote messages query timed out after {req.timeout}s"
                )
            logger.exception(f"Error querying remote messages: {e}")
            return ErrorResponse.internal_error(f"Failed to query remote messages: {e}")

    # -------------------------------------------------------------------------
    # Conversation handlers
    # -------------------------------------------------------------------------

    def _check_conversation_service(self) -> ErrorResponse | None:
        """Check if conversation service is available.

        Returns:
            ErrorResponse if service is not available, None otherwise.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None
        if not self.daemon._conversation_service:
            return ErrorResponse.internal_error("Conversation service not initialized")
        return None

    def _resolve_peer_hashes(self, peer_hash: str) -> list[str]:
        """Resolve a peer hash to all known hash types for the same identity.

        Device discovery uses operator destination hashes (e.g. styrene_node.operator)
        while LXMF uses delivery destination hashes (lxmf.delivery). Both are derived
        from the same RNS identity but have different values. This method finds
        related hashes so message queries can match both outgoing (operator hash)
        and incoming (LXMF hash) messages.

        Results are cached because identity mappings are stable — a peer's
        operator hash and LXMF delivery hash don't change.

        Args:
            peer_hash: Hash to resolve (operator or LXMF delivery hash).

        Returns:
            List of additional hashes (may be empty if resolution fails).
        """
        # Check cache first (avoids repeated RNS crypto)
        if peer_hash in self._peer_hash_cache:
            return self._peer_hash_cache[peer_hash]

        additional: list[str] = []
        try:
            from styrened.services.lxmf_service import get_lxmf_service

            lxmf_service = get_lxmf_service()
            if lxmf_service is None:
                return additional

            # Try to resolve identity from the peer_hash
            import RNS

            identity = lxmf_service._resolve_identity(peer_hash)
            if identity is None:
                # Don't cache misses — identity may appear later
                return additional

            # Compute the LXMF delivery destination hash from the identity
            lxmf_dest = RNS.Destination(
                identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                "lxmf",
                "delivery",
            )
            lxmf_hash = lxmf_dest.hash.hex()
            if lxmf_hash != peer_hash:
                additional.append(lxmf_hash)

            # Also add the raw identity hash (in case messages were stored with it)
            identity_hash = identity.hash.hex()
            if identity_hash != peer_hash and identity_hash != lxmf_hash:
                additional.append(identity_hash)

        except Exception as e:
            logger.debug(f"Could not resolve peer hashes for {peer_hash[:16]}...: {e}")

        # Cache the result (including empty lists for successful but
        # single-hash identities)
        self._peer_hash_cache[peer_hash] = additional
        return additional

    async def handle_query_conversations(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_CONVERSATIONS request.

        Merges conversations that belong to the same Reticulum identity but
        use different hash types (operator destination vs LXMF delivery hash).

        Args:
            request: QueryConversationsRequest instance.

        Returns:
            ResultResponse with list of conversations.
        """
        req = (
            request
            if isinstance(request, QueryConversationsRequest)
            else QueryConversationsRequest()
        )
        _ = req  # Currently unused but available for future filtering

        try:
            err = self._check_conversation_service()
            if err:
                return err
            assert self.daemon is not None and self.daemon._conversation_service is not None

            conversations = self.daemon._conversation_service.list_conversations()

            # Merge conversations from the same identity under different hashes.
            # Build a mapping from each hash to its canonical peer_hash.
            canonical: dict[str, str] = {}  # hash -> canonical peer_hash
            for conv in conversations:
                if conv.peer_hash in canonical:
                    continue
                # Resolve all hashes for this peer
                additional = self._resolve_peer_hashes(conv.peer_hash)
                all_hashes = [conv.peer_hash, *additional]
                # Check if any of these hashes already have a canonical mapping
                existing_canonical = None
                for h in all_hashes:
                    if h in canonical:
                        existing_canonical = canonical[h]
                        break
                if existing_canonical is not None:
                    # Map all hashes to the existing canonical
                    for h in all_hashes:
                        canonical[h] = existing_canonical
                else:
                    # New identity — map all hashes to this peer_hash
                    for h in all_hashes:
                        canonical[h] = conv.peer_hash

            # Merge conversations by canonical hash
            merged: dict[str, dict[str, Any]] = {}
            for conv in conversations:
                key = canonical.get(conv.peer_hash, conv.peer_hash)
                if key not in merged:
                    merged[key] = conv.to_dict()
                else:
                    # Merge into existing: sum counts, keep most recent message
                    existing = merged[key]
                    existing["message_count"] += conv.message_count
                    existing["unread_count"] += conv.unread_count
                    existing["attachment_count"] += conv.attachment_count
                    # Keep the more recent last_message
                    conv_time = conv.last_message_time or 0
                    existing_time = existing.get("last_message_time") or 0
                    if conv_time > existing_time:
                        existing["last_message_time"] = conv.last_message_time
                        existing["last_message_preview"] = conv.last_message_preview
                        existing["last_message_outgoing"] = conv.last_message_outgoing
                    # Prefer non-None display name
                    if not existing.get("display_name") and conv.display_name:
                        existing["display_name"] = conv.display_name

            conv_list = sorted(
                merged.values(),
                key=lambda c: c.get("last_message_time") or 0,
                reverse=True,
            )

            return ResultResponse(data={"conversations": conv_list})

        except Exception as e:
            logger.exception(f"Error querying conversations: {e}")
            return ErrorResponse.internal_error(f"Failed to query conversations: {e}")

    async def handle_query_messages(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_MESSAGES request.

        Args:
            request: QueryMessagesRequest instance.

        Returns:
            ResultResponse with message history.
        """
        req = request if isinstance(request, QueryMessagesRequest) else QueryMessagesRequest()

        if not req.peer_hash:
            return ErrorResponse.invalid_request("peer_hash is required")

        # Validate peer_hash format
        if not HASH_PATTERN.match(req.peer_hash):
            return ErrorResponse.invalid_request(
                f"peer_hash must be 16-32 hex characters, got {len(req.peer_hash)} chars"
            )

        # Validate and bound limit parameter
        limit = min(max(1, req.limit), MAX_MESSAGE_LIMIT) if req.limit else MAX_MESSAGE_LIMIT

        try:
            err = self._check_conversation_service()
            if err:
                return err
            assert self.daemon is not None and self.daemon._conversation_service is not None

            # Resolve additional hashes for the peer so we find messages
            # stored under different hash types (operator vs LXMF delivery)
            additional_hashes = self._resolve_peer_hashes(req.peer_hash)

            messages = self.daemon._conversation_service.get_messages(
                peer_hash=req.peer_hash,
                limit=limit,
                before_timestamp=req.before_timestamp,
                status_filter=req.status_filter,
                additional_peer_hashes=additional_hashes,
            )
            msg_list = [m.to_dict() for m in messages]

            return ResultResponse(data={"messages": msg_list})

        except Exception as e:
            logger.exception(f"Error querying messages: {e}")
            return ErrorResponse.internal_error(f"Failed to query messages: {e}")

    async def handle_query_search_messages(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_SEARCH_MESSAGES request.

        Searches messages using full-text search.

        Args:
            request: QuerySearchMessagesRequest instance.

        Returns:
            ResultResponse with matching messages.
        """
        req = (
            request
            if isinstance(request, QuerySearchMessagesRequest)
            else QuerySearchMessagesRequest()
        )

        if not req.query or len(req.query.strip()) < 2:
            return ErrorResponse.invalid_request("Query must be at least 2 characters")

        # Validate and bound limit parameter
        limit = min(max(1, req.limit), MAX_MESSAGE_LIMIT) if req.limit else MAX_MESSAGE_LIMIT

        try:
            err = self._check_conversation_service()
            if err:
                return err
            assert self.daemon is not None and self.daemon._conversation_service is not None

            messages = self.daemon._conversation_service.search_messages(
                query=req.query,
                peer_hash=req.peer_hash,
                limit=limit,
            )
            msg_list = [m.to_dict() for m in messages]

            return ResultResponse(
                data={
                    "messages": msg_list,
                    "count": len(msg_list),
                }
            )

        except Exception as e:
            logger.exception(f"Error searching messages: {e}")
            return ErrorResponse.internal_error(f"Failed to search messages: {e}")

    async def handle_query_attachment(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_ATTACHMENT request.

        Returns base64-encoded attachment data for a message.

        Args:
            request: QueryAttachmentRequest instance.

        Returns:
            ResultResponse with {data_b64, filename, mime, size}.
        """
        req = (
            request
            if isinstance(request, QueryAttachmentRequest)
            else QueryAttachmentRequest()
        )

        if not req.message_id:
            return ErrorResponse.invalid_request("message_id is required")

        try:
            err = self._check_conversation_service()
            if err:
                return err
            assert self.daemon is not None and self.daemon._conversation_service is not None

            from sqlalchemy.orm import Session as SASession

            from styrened.models.messages import Message

            with SASession(self.daemon._conversation_service._db_engine) as session:
                msg = session.query(Message).filter(Message.id == req.message_id).first()
                if msg is None:
                    return ErrorResponse.not_found(f"Message {req.message_id} not found")
                if not msg.has_attachment or not msg.attachment_path:
                    return ErrorResponse.not_found(
                        f"Message {req.message_id} has no stored attachment"
                    )

                att_path = msg.attachment_path
                att_name = msg.attachment_name
                att_mime = msg.attachment_mime
                att_size = msg.attachment_size

            from styrened.services.attachment_store import get_attachment_store

            store = get_attachment_store()
            data = store.load(att_path)

            return ResultResponse(
                data={
                    "data_b64": base64.b64encode(data).decode("ascii"),
                    "filename": att_name,
                    "mime": att_mime,
                    "size": att_size or len(data),
                }
            )

        except FileNotFoundError:
            return ErrorResponse.not_found(
                f"Attachment file not found for message {req.message_id}"
            )
        except Exception as e:
            logger.exception(f"Error querying attachment: {e}")
            return ErrorResponse.internal_error(f"Failed to query attachment: {e}")

    async def handle_cmd_send_chat(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_SEND_CHAT request.

        Sends a chat message and persists it via ConversationService.
        Registers delivery callbacks to track message status.

        Args:
            request: CmdSendChatRequest instance.

        Returns:
            ResultResponse with message ID and delivery method.
        """
        from styrened.services.lxmf_service import get_lxmf_service

        req = request if isinstance(request, CmdSendChatRequest) else CmdSendChatRequest()

        # Validate required fields (handle None, empty string, and wrong types)
        if not req.peer_hash or not isinstance(req.peer_hash, str):
            return ErrorResponse.invalid_request("peer_hash is required and must be a string")
        if req.content is None or not isinstance(req.content, str):
            return ErrorResponse.invalid_request("content is required and must be a string")
        # Allow empty content when attachment is provided
        if not req.content and not req.attachment_data_b64:
            return ErrorResponse.invalid_request("content or attachment is required")

        # Validate peer_hash format (16-32 hex chars)
        if not HASH_PATTERN.match(req.peer_hash):
            return ErrorResponse.invalid_request(
                f"peer_hash must be 16-32 hex characters, got {len(req.peer_hash)} chars"
            )

        # Validate content size limits
        if len(req.content) > MAX_CHAT_CONTENT_LENGTH:
            return ErrorResponse.invalid_request(
                f"content exceeds maximum length of {MAX_CHAT_CONTENT_LENGTH} bytes"
            )

        # Validate title length if provided
        if req.title and len(req.title) > MAX_TITLE_LENGTH:
            return ErrorResponse.invalid_request(
                f"title exceeds maximum length of {MAX_TITLE_LENGTH} characters"
            )

        # Validate reply_to_hash format if provided (64 hex chars for LXMF message hash)
        if req.reply_to_hash:
            if not isinstance(req.reply_to_hash, str) or not LXMF_HASH_PATTERN.match(
                req.reply_to_hash
            ):
                return ErrorResponse.invalid_request(
                    "reply_to_hash must be a 64-character hex string"
                )

        # Validate and extract delivery method
        delivery_method = req.delivery_method if req.delivery_method else "auto"
        if delivery_method not in VALID_DELIVERY_METHODS:
            return ErrorResponse.invalid_request(
                f"delivery_method must be one of: {', '.join(sorted(VALID_DELIVERY_METHODS))}"
            )

        try:
            err = self._check_conversation_service()
            if err:
                return err
            assert self.daemon is not None and self.daemon._conversation_service is not None

            lxmf_service = get_lxmf_service()
            if not lxmf_service:
                return ErrorResponse.internal_error("LXMF service not initialized")

            # Build message fields (stored in DB for protocol routing)
            fields: dict[str, object] = {"protocol": "chat"}
            if req.title:
                fields["title"] = req.title

            # LXMF message body is plain content text — NOT a JSON envelope.
            # Standard LXMF clients (Sideband, NomadNet, echo bots) display
            # the body as-is; wrapping it in JSON makes the message unreadable
            # to non-Styrene peers.
            payload = req.content

            # Get conversation service reference for callbacks
            conversation_service = self.daemon._conversation_service

            # Process attachment if provided
            has_attachment = False
            attachment_type: str | None = None
            attachment_name: str | None = None
            attachment_size: int | None = None
            attachment_mime: str | None = None
            attachment_path: str | None = None
            attachment_raw: bytes | None = None

            if req.attachment_data_b64:
                # Pre-check base64 length before decoding to prevent
                # memory exhaustion from oversized payloads.
                # 10 MB raw ≈ 13.4 MB base64; add 1 KB headroom.
                from styrened.services.attachment_store import DEFAULT_MAX_FILE_SIZE

                max_b64_len = int(DEFAULT_MAX_FILE_SIZE * 4 / 3) + 1024
                if len(req.attachment_data_b64) > max_b64_len:
                    return ErrorResponse.invalid_request(
                        f"Attachment too large (base64 length {len(req.attachment_data_b64)} "
                        f"exceeds limit {max_b64_len})"
                    )

                try:
                    attachment_raw = base64.b64decode(req.attachment_data_b64)
                    attachment_name = req.attachment_filename or "attachment"
                    attachment_mime = req.attachment_mime
                    attachment_size = len(attachment_raw)
                    has_attachment = True

                    # Determine attachment type from mime
                    if attachment_mime and attachment_mime.startswith("image/"):
                        attachment_type = "image"
                    elif attachment_mime and attachment_mime.startswith("audio/"):
                        attachment_type = "audio"
                    else:
                        attachment_type = "file"

                    # Save to attachment store
                    from styrened.services.attachment_store import get_attachment_store

                    store = get_attachment_store()
                    saved = store.save(
                        req.peer_hash, 0, attachment_name, attachment_raw,
                        mime=attachment_mime,
                    )
                    attachment_path = str(saved)
                except Exception as e:
                    logger.warning(f"Failed to process attachment: {e}")
                    # Continue without attachment — message still sends

            # Step 1: Save message FIRST (avoids race with fast delivery callbacks)
            msg_id = conversation_service.save_outgoing_message(
                destination_hash=req.peer_hash,
                content=req.content,
                title=req.title,
                fields=fields,
                reply_to_hash=req.reply_to_hash,
                has_attachment=has_attachment,
                attachment_type=attachment_type,
                attachment_name=attachment_name,
                attachment_size=attachment_size,
                attachment_mime=attachment_mime,
                attachment_path=attachment_path,
                # Don't pass lxmf_hash yet - we register tracking after send
            )

            # Rename attachment to include real message_id
            if attachment_path:
                try:
                    from pathlib import Path

                    from styrened.services.attachment_store import get_attachment_store

                    att_store = get_attachment_store()
                    new_path = att_store.rename_for_message(Path(attachment_path), msg_id)
                    if str(new_path) != attachment_path:
                        conversation_service.update_attachment_path(msg_id, str(new_path))
                        attachment_path = str(new_path)
                except Exception as e:
                    logger.warning(f"Failed to rename attachment: {e}")

            # Step 2: Create thread-safe tracking registration and callbacks
            # We use a closure to capture the message_id and handle the race condition
            # where callbacks might fire before we can register tracking.
            # IMPORTANT: Use a separate lock for tracking_registered state to avoid
            # deadlock - conversation_service methods acquire their own internal lock.
            tracking_lock = threading.Lock()
            tracking_registered: dict[str, bytes | None] = {"hash": None}

            # Capture daemon reference for delivery status broadcasts
            daemon = self.daemon

            def register_and_callback_delivery(lxmf_message: Any) -> None:
                """Handle successful delivery with race-safe tracking."""
                try:
                    # Check if service is still running (could be shutting down)
                    if not conversation_service._initialized:
                        logger.debug(
                            f"Delivery callback for msg {msg_id} ignored - service shutdown"
                        )
                        return

                    msg_hash = lxmf_message.hash
                    needs_registration = False
                    with tracking_lock:
                        # Check if tracking wasn't registered yet (race condition)
                        if tracking_registered["hash"] is None:
                            tracking_registered["hash"] = msg_hash
                            needs_registration = True
                    # Register OUTSIDE the lock to avoid deadlock
                    if needs_registration:
                        conversation_service.register_delivery_tracking(msg_id, msg_hash)
                    conversation_service.on_delivery_callback(msg_hash)
                    logger.debug(f"Chat message {msg_id} delivered: {msg_hash.hex()[:16]}...")

                    # Broadcast delivery status event
                    if daemon is not None:
                        daemon._broadcast_delivery_status_event(
                            msg_id, req.peer_hash, "delivered"
                        )
                except Exception as e:
                    logger.warning(f"Error in delivery callback: {e}")

            def register_and_callback_failed(lxmf_message: Any) -> None:
                """Handle delivery failure with race-safe tracking."""
                try:
                    # Check if service is still running (could be shutting down)
                    if not conversation_service._initialized:
                        logger.debug(f"Failed callback for msg {msg_id} ignored - service shutdown")
                        return

                    msg_hash = lxmf_message.hash
                    needs_registration = False
                    with tracking_lock:
                        # Check if tracking wasn't registered yet (race condition)
                        if tracking_registered["hash"] is None:
                            tracking_registered["hash"] = msg_hash
                            needs_registration = True
                    # Register OUTSIDE the lock to avoid deadlock
                    if needs_registration:
                        conversation_service.register_delivery_tracking(msg_id, msg_hash)
                    conversation_service.on_failed_callback(msg_hash)
                    logger.warning(
                        f"Chat message {msg_id} delivery failed: {msg_hash.hex()[:16]}..."
                    )

                    # Broadcast delivery failure event
                    if daemon is not None:
                        daemon._broadcast_delivery_status_event(
                            msg_id, req.peer_hash, "failed"
                        )
                except Exception as e:
                    logger.warning(f"Error in failed callback: {e}")

            # Step 3: Build LXMF fields for ecosystem interoperability
            # FIELD_RENDERER tells clients how to render the message content
            lxmf_fields: dict[int, Any] = {}
            if LXMF_AVAILABLE:
                lxmf_fields[LXMF.FIELD_RENDERER] = LXMF.RENDERER_PLAIN

                # Add threading info if this is a reply (FIELD_THREAD = 0x08)
                if req.reply_to_hash:
                    lxmf_fields[LXMF.FIELD_THREAD] = {
                        "reply_to": req.reply_to_hash,
                    }

                # Add attachment data to LXMF fields for ecosystem interop.
                # For Styrene peers, we also attempt RNS.Resource transfer
                # which provides full quality and progress tracking.
                styrene_transfer_used = False
                if has_attachment and attachment_raw is not None:
                    # Try Styrene link-based transfer for Styrene peers
                    if (
                        self.daemon is not None
                        and hasattr(self.daemon, "_file_transfer_service")
                        and self.daemon._file_transfer_service is not None
                    ):
                        try:
                            from styrened.services.node_store import get_node_store

                            node_store = get_node_store()
                            is_styrene = False
                            if node_store:
                                node = node_store.get_node_by_destination(req.peer_hash)
                                if node and node.is_styrene_node:
                                    is_styrene = True
                            if is_styrene:
                                loop = asyncio.get_running_loop()
                                loop.create_task(
                                    self.daemon._file_transfer_service.send_file(
                                        req.peer_hash,
                                        attachment_raw,
                                        attachment_name or "attachment",
                                        mime_type=attachment_mime,
                                    )
                                )
                                styrene_transfer_used = True
                                logger.info(
                                    f"Using Styrene link transfer for "
                                    f"{attachment_name} to {req.peer_hash[:8]}"
                                )
                        except Exception as e:
                            logger.debug(
                                f"Styrene transfer not available, using LXMF: {e}"
                            )

                    # Include LXMF attachment fields only when Styrene transfer not used.
                    # When Styrene transfer is active, the file goes via RNS.Resource
                    # and embedding it in LXMF fields would duplicate the payload.
                    if not styrene_transfer_used:
                        if attachment_type == "image":
                            # FIELD_IMAGE: (mime_type, data)
                            lxmf_fields[LXMF.FIELD_IMAGE] = (
                                attachment_mime or "image/jpeg",
                                attachment_raw,
                            )
                        elif attachment_type == "audio":
                            # FIELD_AUDIO: (mime_type, data)
                            lxmf_fields[LXMF.FIELD_AUDIO] = (
                                attachment_mime or "audio/opus",
                                attachment_raw,
                            )
                        else:
                            # FIELD_FILE_ATTACHMENTS: [(filename, data, mime)]
                            file_entry: tuple[str, bytes] | tuple[str, bytes, str]
                            if attachment_mime:
                                file_entry = (attachment_name or "file", attachment_raw, attachment_mime)
                            else:
                                file_entry = (attachment_name or "file", attachment_raw)
                            lxmf_fields[LXMF.FIELD_FILE_ATTACHMENTS] = [file_entry]

            # Step 4: Send via LXMF with race-safe callbacks
            # Run in executor because send_message may block up to 10s
            # if identity resolution requires a path request + wait.
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: lxmf_service.send_message(
                    req.peer_hash,
                    payload,
                    on_delivery=register_and_callback_delivery,
                    on_failed=register_and_callback_failed,
                    delivery_method=delivery_method,
                    lxmf_fields=lxmf_fields if lxmf_fields else None,
                ),
            )

            if result is None:
                # Send failed - mark message as failed
                conversation_service.update_message_status(msg_id, "failed")
                return ErrorResponse.internal_error(
                    f"Failed to send message to {req.peer_hash[:16]}... "
                    "(no path or identity not known)"
                )

            # Extract hash and method from result
            lxmf_hash: bytes = result["hash"]
            delivery_method_used: str = result.get("method", delivery_method)

            # NOTE: We intentionally do NOT update destination_hash to the LXMF
            # delivery hash. The saved message uses the peer's operator hash
            # (from device discovery), which is what the TUI uses for queries.
            # The LXMF delivery hash is a different aspect of the same identity
            # and would break get_messages() lookups.

            # Step 6: Register delivery tracking (if not already done by callback race)
            # Use the tracking_lock to safely check/update state.
            needs_registration = False
            with tracking_lock:
                if tracking_registered["hash"] is None:
                    tracking_registered["hash"] = lxmf_hash
                    needs_registration = True
            if needs_registration:
                conversation_service.register_delivery_tracking(msg_id, lxmf_hash)

            # Step 7: Mark as sent (handed off to network)
            conversation_service.mark_sent(msg_id)

            return ResultResponse(
                data={
                    "message_id": msg_id,
                    "sent": True,
                    "lxmf_hash": lxmf_hash.hex(),
                    "delivery_method": delivery_method_used,
                }
            )

        except Exception as e:
            logger.exception(f"Error sending chat message: {e}")
            return ErrorResponse.internal_error(f"Failed to send chat message: {e}")

    async def handle_cmd_mark_read(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_MARK_READ request.

        Marks all messages in a conversation as read.

        Args:
            request: CmdMarkReadRequest instance.

        Returns:
            ResultResponse with count of messages marked read.
        """
        req = request if isinstance(request, CmdMarkReadRequest) else CmdMarkReadRequest()

        if not req.peer_hash:
            return ErrorResponse.invalid_request("peer_hash is required")

        # Validate peer_hash format
        if not HASH_PATTERN.match(req.peer_hash):
            return ErrorResponse.invalid_request(
                f"peer_hash must be 16-32 hex characters, got {len(req.peer_hash)} chars"
            )

        try:
            err = self._check_conversation_service()
            if err:
                return err
            assert self.daemon is not None and self.daemon._conversation_service is not None

            # Resolve additional hashes for the peer so we mark messages
            # stored under different hash types (operator vs LXMF delivery)
            additional_hashes = self._resolve_peer_hashes(req.peer_hash)

            count = self.daemon._conversation_service.mark_read(
                req.peer_hash,
                additional_peer_hashes=additional_hashes,
            )

            # Send read receipts to peer for ecosystem compatibility
            # This is fire-and-forget; don't fail the mark_read if receipts fail
            try:
                await self.daemon.send_read_receipts(req.peer_hash)
            except Exception as receipt_err:
                logger.warning(f"Failed to send read receipts: {receipt_err}")

            self.daemon._emit_activity_event(
                "conversation_read", peer_hash=req.peer_hash
            )
            return ResultResponse(data={"marked_read": count})

        except Exception as e:
            logger.exception(f"Error marking messages as read: {e}")
            return ErrorResponse.internal_error(f"Failed to mark messages as read: {e}")

    async def handle_cmd_delete_conversation(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_DELETE_CONVERSATION request.

        Deletes all messages in a conversation.

        Args:
            request: CmdDeleteConversationRequest instance.

        Returns:
            ResultResponse with count of messages deleted.
        """
        req = (
            request
            if isinstance(request, CmdDeleteConversationRequest)
            else CmdDeleteConversationRequest()
        )

        if not req.peer_hash:
            return ErrorResponse.invalid_request("peer_hash is required")

        # Validate peer_hash format
        if not HASH_PATTERN.match(req.peer_hash):
            return ErrorResponse.invalid_request(
                f"peer_hash must be 16-32 hex characters, got {len(req.peer_hash)} chars"
            )

        try:
            err = self._check_conversation_service()
            if err:
                return err
            assert self.daemon is not None and self.daemon._conversation_service is not None

            # Resolve additional hashes so we delete messages stored
            # under different hash types (operator vs LXMF delivery)
            additional_hashes = self._resolve_peer_hashes(req.peer_hash)

            count = self.daemon._conversation_service.delete_conversation(
                req.peer_hash,
                additional_peer_hashes=additional_hashes,
            )

            self.daemon._emit_activity_event(
                "conversation_deleted", peer_hash=req.peer_hash
            )
            return ResultResponse(data={"deleted": count})

        except Exception as e:
            logger.exception(f"Error deleting conversation: {e}")
            return ErrorResponse.internal_error(f"Failed to delete conversation: {e}")

    async def handle_cmd_delete_message(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_DELETE_MESSAGE request.

        Deletes a specific message.

        Args:
            request: CmdDeleteMessageRequest instance.

        Returns:
            ResultResponse with deletion status.
        """
        req = request if isinstance(request, CmdDeleteMessageRequest) else CmdDeleteMessageRequest()

        if not isinstance(req.message_id, int) or req.message_id <= 0:
            return ErrorResponse.invalid_request("message_id must be a positive integer")

        try:
            err = self._check_conversation_service()
            if err:
                return err
            assert self.daemon is not None and self.daemon._conversation_service is not None

            deleted = self.daemon._conversation_service.delete_message(req.message_id)

            if not deleted:
                return ErrorResponse.not_found(f"Message {req.message_id} not found")

            return ResultResponse(data={"deleted": True})

        except Exception as e:
            logger.exception(f"Error deleting message: {e}")
            return ErrorResponse.internal_error(f"Failed to delete message: {e}")

    async def handle_cmd_retry_message(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_RETRY_MESSAGE request.

        Retries sending a failed message.

        Args:
            request: CmdRetryMessageRequest instance.

        Returns:
            ResultResponse with new LXMF hash if successful.
        """
        req = request if isinstance(request, CmdRetryMessageRequest) else CmdRetryMessageRequest()

        if not isinstance(req.message_id, int) or req.message_id <= 0:
            return ErrorResponse.invalid_request("message_id must be a positive integer")

        try:
            from styrened.services.lxmf_service import get_lxmf_service

            err = self._check_conversation_service()
            if err:
                return err
            assert self.daemon is not None and self.daemon._conversation_service is not None

            lxmf_service = get_lxmf_service()
            if not lxmf_service:
                return ErrorResponse.internal_error("LXMF service not initialized")

            conversation_service = self.daemon._conversation_service

            # Get message details and reset to PENDING
            retry_data = conversation_service.prepare_retry(req.message_id)
            if retry_data is None:
                return ErrorResponse.not_found(
                    f"Message {req.message_id} not found or not in FAILED state"
                )

            dest_hash, content, fields = retry_data

            # Build LXMF payload
            payload: dict[str, object] = {
                "type": "chat",
                "protocol": "chat",
                "content": content,
            }
            if fields.get("title"):
                payload["title"] = fields["title"]

            # Create delivery callbacks
            msg_id = req.message_id
            daemon = self.daemon

            def on_delivery(lxmf_message: Any) -> None:
                """Handle successful delivery."""
                try:
                    msg_hash = lxmf_message.hash
                    conversation_service.on_delivery_callback(msg_hash)
                    logger.debug(f"Retried message {msg_id} delivered: {msg_hash.hex()[:16]}...")

                    # Broadcast delivery status event
                    if daemon is not None:
                        daemon._broadcast_delivery_status_event(
                            msg_id, dest_hash, "delivered"
                        )
                except Exception as e:
                    logger.warning(f"Error in delivery callback: {e}")

            def on_failed(lxmf_message: Any) -> None:
                """Handle delivery failure."""
                try:
                    msg_hash = lxmf_message.hash
                    conversation_service.on_failed_callback(msg_hash)
                    logger.warning(
                        f"Retried message {msg_id} delivery failed: {msg_hash.hex()[:16]}..."
                    )

                    # Broadcast delivery failure event
                    if daemon is not None:
                        daemon._broadcast_delivery_status_event(
                            msg_id, dest_hash, "failed"
                        )
                except Exception as e:
                    logger.warning(f"Error in failed callback: {e}")

            # Send via LXMF (run in executor — may block on identity resolution)
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                lambda: lxmf_service.send_message(
                    dest_hash,
                    payload,
                    on_delivery=on_delivery,
                    on_failed=on_failed,
                ),
            )

            if result is None:
                # Send failed again - mark as failed
                conversation_service.update_message_status(msg_id, "failed")
                return ErrorResponse.internal_error(
                    f"Failed to retry message to {dest_hash[:16]}... "
                    "(no path or identity not known)"
                )

            # Extract hash and method from result
            lxmf_hash = result["hash"]
            delivery_method_used = result.get("method", "direct")

            # Register delivery tracking and mark as sent
            conversation_service.register_delivery_tracking(msg_id, lxmf_hash)
            conversation_service.mark_sent(msg_id)

            return ResultResponse(
                data={
                    "message_id": msg_id,
                    "retried": True,
                    "lxmf_hash": lxmf_hash.hex(),
                    "delivery_method": delivery_method_used,
                }
            )

        except Exception as e:
            logger.exception(f"Error retrying message: {e}")
            return ErrorResponse.internal_error(f"Failed to retry message: {e}")

    # -------------------------------------------------------------------------
    # Contact handlers
    # -------------------------------------------------------------------------

    def _check_contact_service(self) -> ErrorResponse | None:
        """Check that contact service is available."""
        error = self._check_daemon()
        if error:
            return error
        if not getattr(self.daemon, "_contact_service", None):
            return ErrorResponse.internal_error("Contact service not initialized")
        return None

    async def handle_query_contacts(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_CONTACTS request."""
        error = self._check_contact_service()
        if error:
            return error
        assert self.daemon is not None

        req = request if isinstance(request, QueryContactsRequest) else QueryContactsRequest()
        _ = req  # Currently unused but available for future filtering

        try:
            contacts = self.daemon._contact_service.list_contacts()
            return ResultResponse(
                data={"contacts": [c.to_dict() for c in contacts]}
            )
        except Exception as e:
            logger.exception(f"Error listing contacts: {e}")
            return ErrorResponse.internal_error(f"Failed to list contacts: {e}")

    async def handle_query_resolve_name(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_RESOLVE_NAME request."""
        error = self._check_contact_service()
        if error:
            return error
        assert self.daemon is not None

        req = (
            request
            if isinstance(request, QueryResolveNameRequest)
            else QueryResolveNameRequest()
        )

        if not req.name or len(req.name) < 1:
            return ErrorResponse.invalid_request("Name is required")

        try:
            peer_hash = self.daemon._contact_service.resolve_name(
                req.name, prefix_match=req.prefix_match
            )
            return ResultResponse(data={"peer_hash": peer_hash})
        except Exception as e:
            logger.exception(f"Error resolving name: {e}")
            return ErrorResponse.internal_error(f"Failed to resolve name: {e}")

    async def handle_cmd_set_contact(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_SET_CONTACT request."""
        error = self._check_contact_service()
        if error:
            return error
        assert self.daemon is not None

        req = (
            request
            if isinstance(request, CmdSetContactRequest)
            else CmdSetContactRequest()
        )

        if not req.peer_hash or not HASH_PATTERN.match(req.peer_hash):
            return ErrorResponse.invalid_request(
                "Invalid peer_hash: must be 16-32 hex characters"
            )

        if not req.alias or len(req.alias.strip()) == 0:
            return ErrorResponse.invalid_request("Alias is required")

        if len(req.alias) > 100:
            return ErrorResponse.invalid_request("Alias too long (max 100 characters)")

        if req.notes is not None and len(req.notes) > 500:
            return ErrorResponse.invalid_request("Notes too long (max 500 characters)")

        try:
            contact = self.daemon._contact_service.set_alias(
                req.peer_hash, req.alias.strip(), notes=req.notes
            )
            self.daemon._emit_activity_event(
                "contact_set",
                peer_hash=req.peer_hash,
                metadata={"alias": req.alias.strip()},
            )
            return ResultResponse(data=contact.to_dict())
        except Exception as e:
            logger.exception(f"Error setting contact: {e}")
            return ErrorResponse.internal_error(f"Failed to set contact: {e}")

    async def handle_cmd_remove_contact(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_REMOVE_CONTACT request."""
        error = self._check_contact_service()
        if error:
            return error
        assert self.daemon is not None

        req = (
            request
            if isinstance(request, CmdRemoveContactRequest)
            else CmdRemoveContactRequest()
        )

        if not req.peer_hash or not HASH_PATTERN.match(req.peer_hash):
            return ErrorResponse.invalid_request(
                "Invalid peer_hash: must be 16-32 hex characters"
            )

        try:
            removed = self.daemon._contact_service.remove_alias(req.peer_hash)
            if not removed:
                return ErrorResponse.not_found(
                    f"Contact not found: {req.peer_hash[:16]}..."
                )
            self.daemon._emit_activity_event(
                "contact_removed", peer_hash=req.peer_hash
            )
            return ResultResponse(data={"removed": True})
        except Exception as e:
            logger.exception(f"Error removing contact: {e}")
            return ErrorResponse.internal_error(f"Failed to remove contact: {e}")

    # -------------------------------------------------------------------------
    # Auto-reply handlers
    # -------------------------------------------------------------------------

    async def handle_query_auto_reply(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_AUTO_REPLY request.

        Returns current auto-reply configuration from daemon config.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None

        try:
            return ResultResponse(
                data={
                    "mode": self.daemon.config.chat.auto_reply_mode.value,
                    "message": self.daemon.config.chat.auto_reply_message,
                    "cooldown": self.daemon.config.chat.auto_reply_cooldown,
                }
            )
        except Exception as e:
            logger.exception(f"Error querying auto-reply: {e}")
            return ErrorResponse.internal_error(f"Failed to query auto-reply: {e}")

    async def handle_cmd_set_auto_reply(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_SET_AUTO_REPLY request.

        Updates auto-reply configuration, persists to disk, and re-announces.
        Same pattern as web route POST /api/auto-reply.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None

        req = (
            request
            if isinstance(request, CmdSetAutoReplyRequest)
            else CmdSetAutoReplyRequest()
        )

        try:
            from styrened.models.config import AutoReplyMode
            from styrened.services.config import save_core_config

            try:
                self.daemon.config.chat.auto_reply_mode = AutoReplyMode(req.mode)
            except ValueError:
                return ErrorResponse.invalid_request(
                    f"Invalid auto_reply_mode: {req.mode}"
                )
            if req.message:
                self.daemon.config.chat.auto_reply_message = req.message
            if req.cooldown > 0:
                self.daemon.config.chat.auto_reply_cooldown = req.cooldown

            # Persist to disk
            save_core_config(self.daemon.config)

            # Re-announce to propagate capability change
            self.daemon._announce()

            self.daemon._emit_activity_event(
                "auto_reply_changed",
                metadata={"mode": self.daemon.config.chat.auto_reply_mode.value},
            )
            return ResultResponse(
                data={
                    "mode": self.daemon.config.chat.auto_reply_mode.value,
                    "message": self.daemon.config.chat.auto_reply_message,
                    "cooldown": self.daemon.config.chat.auto_reply_cooldown,
                }
            )
        except Exception as e:
            logger.exception(f"Error setting auto-reply: {e}")
            return ErrorResponse.internal_error(f"Failed to set auto-reply: {e}")

    async def handle_cmd_set_identity(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_SET_IDENTITY request.

        Updates operator identity appearance fields, persists to disk,
        and triggers re-announce to propagate changes.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None

        req = (
            request
            if isinstance(request, CmdSetIdentityRequest)
            else CmdSetIdentityRequest()
        )

        try:
            from styrened.models.config import validate_short_name
            from styrened.services.config import save_core_config

            identity_cfg = self.daemon.config.identity

            # Validate display_name length
            if req.display_name and len(req.display_name) > 100:
                return ErrorResponse.invalid_request(
                    "display_name exceeds maximum length of 100 characters"
                )

            # Update display_name if provided
            if req.display_name:
                identity_cfg.display_name = req.display_name

            # Update icon if provided
            if req.icon:
                identity_cfg.icon = req.icon

            # Handle short_name: explicit empty string clears it, None means no change
            if req.short_name is not None:
                if req.short_name == "":
                    identity_cfg.short_name = None
                else:
                    if not validate_short_name(req.short_name):
                        return ErrorResponse.invalid_request(
                            "Invalid short_name: must be 3-20 chars, "
                            "lowercase alphanumeric + hyphens, no leading/trailing hyphens"
                        )
                    identity_cfg.short_name = req.short_name

            # Persist to disk
            save_core_config(self.daemon.config)

            # Re-announce to propagate identity changes
            self.daemon._announce()

            self.daemon._emit_activity_event(
                "identity_changed",
                metadata={
                    "display_name": identity_cfg.display_name,
                    "icon": identity_cfg.icon or "",
                },
            )
            return ResultResponse(
                data={
                    "display_name": identity_cfg.display_name,
                    "icon": identity_cfg.icon,
                    "short_name": identity_cfg.short_name,
                }
            )
        except Exception as e:
            logger.exception(f"Error setting identity: {e}")
            return ErrorResponse.internal_error(f"Failed to set identity: {e}")

    async def handle_cmd_pqc_status(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_PQC_STATUS request.

        Queries PQC session status for a given peer. Returns security tier,
        session state, and rekey metadata. If no PQC service or no session
        exists, returns security_tier "rns_only" with null state fields.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None

        req = (
            request
            if isinstance(request, PQCStatusRequest)
            else PQCStatusRequest()
        )

        if not req.peer_hash:
            return ErrorResponse.invalid_request("peer_hash is required")

        try:
            pqc_service = getattr(self.daemon, "_pqc_service", None)
            if pqc_service is None:
                return ResultResponse(
                    data={
                        "security_tier": "rns_only",
                        "session_state": None,
                        "created_at": None,
                        "last_rekeyed_at": None,
                        "rekey_count": None,
                    }
                )

            session_status = pqc_service.get_session_status(req.peer_hash)
            if session_status is None:
                return ResultResponse(
                    data={
                        "security_tier": "rns_only",
                        "session_state": None,
                        "created_at": None,
                        "last_rekeyed_at": None,
                        "rekey_count": None,
                    }
                )

            return ResultResponse(data=session_status)
        except Exception as e:
            logger.exception(f"Error querying PQC status: {e}")
            return ErrorResponse.internal_error(f"Failed to query PQC status: {e}")

    async def handle_cmd_sync_messages(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_SYNC_MESSAGES request.

        Triggers LXMF propagation node sync to pull pending messages.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None

        try:
            from styrened.services.lxmf_service import get_lxmf_service

            lxmf = get_lxmf_service()
            if not lxmf.is_initialized:
                return ErrorResponse.internal_error("LXMF service not initialized")

            success = lxmf.request_messages_from_propagation_node()
            return ResultResponse(data={"synced": success})

        except Exception as e:
            logger.exception(f"Error syncing messages: {e}")
            return ErrorResponse.internal_error(f"Failed to sync messages: {e}")

    async def handle_query_path_info(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_PATH_INFO request.

        Returns path information (hops, interface, etc.) for a destination.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None

        req = (
            request
            if isinstance(request, QueryPathInfoRequest)
            else QueryPathInfoRequest()
        )

        destination_hash = req.destination_hash.strip()
        if not destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            from styrened.services.node_store import get_node_store

            store = get_node_store()
            path = store.get_path(destination_hash)

            if path is None:
                return ResultResponse(data={"found": False})

            return ResultResponse(
                data={
                    "found": True,
                    "hops": path.get("hops", 0),
                    "next_hop": path.get("next_hop"),
                    "interface_type": path.get("interface_type"),
                    "interface_name": path.get("interface_name"),
                    "bitrate": path.get("bitrate"),
                    "expires": path.get("expires"),
                    "updated_at": path.get("updated_at"),
                }
            )

        except Exception as e:
            logger.exception(f"Error querying path info: {e}")
            return ErrorResponse.internal_error(f"Failed to query path info: {e}")

    # -------------------------------------------------------------------------
    # Page browser handlers
    # -------------------------------------------------------------------------

    def _check_page_browser(self) -> ErrorResponse | None:
        """Check if page browser service is available."""
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None
        if not getattr(self.daemon, "_page_browser_service", None):
            return ErrorResponse.internal_error("Page browser service not initialized")
        return None

    async def handle_query_page(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_PAGE request.

        Fetches a page from a NomadNet node via the PageBrowserService.

        Args:
            request: QueryPageRequest instance.

        Returns:
            ResultResponse with page content and metadata.
        """
        err = self._check_page_browser()
        if err:
            return err
        assert self.daemon is not None

        req = request if isinstance(request, QueryPageRequest) else QueryPageRequest()

        using_url = bool(getattr(req, "url", ""))
        if not using_url and not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        if not using_url and not HASH_PATTERN.match(req.destination_hash):
            return ErrorResponse.invalid_request(
                f"destination_hash must be 16-32 hex characters, got {len(req.destination_hash)} chars"
            )

        try:
            if using_url:
                response = await self.daemon._page_browser_service.fetch_url(
                    url=req.url,
                    timeout=req.timeout,
                )
            else:
                response = await self.daemon._page_browser_service.fetch_page(
                    destination_hash=req.destination_hash,
                    path=req.path,
                    form_data=req.form_data,
                    timeout=req.timeout,
                )

            data: dict[str, object] = {
                "content": response.content,
                "status": response.status.value,
                "destination_hash": response.destination_hash,
                "path": response.path,
                "transfer_time": response.transfer_time,
                "content_length": response.content_length,
                "cache_ttl": response.cache_ttl,
            }
            if response.error_message:
                data["error_message"] = response.error_message

            # Include Styrene structured data if present
            if response.structured_data is not None:
                data["structured_data"] = response.structured_data
            if response.page_metadata is not None:
                meta = response.page_metadata
                data["page_metadata"] = {
                    "version": meta.version,
                    "page_type": meta.page_type,
                    "capabilities": meta.capabilities,
                    "timestamp": meta.timestamp,
                    "etag": meta.etag,
                    "refresh": meta.refresh,
                }

            # Write-through cache on success
            cache_svc = getattr(self.daemon, "_page_cache_service", None)
            if cache_svc and response.status.value == "ok" and response.content:
                if using_url:
                    cache_svc.cache_url(req.url, response.content)
                else:
                    cache_svc.cache_page(req.destination_hash, req.path, response.content)

            # On failure, try cache fallback
            if response.status.value != "ok" and cache_svc:
                if using_url:
                    cached = cache_svc.get_cached_url(
                        req.url,
                        max_age=cache_svc.get_cache_ttl_for_url(req.url),
                    )
                else:
                    cached = cache_svc.get_cached_page(req.destination_hash, req.path)
                if cached:
                    data["cached_content"] = cached["content"]
                    data["cached_at"] = cached["fetched_at"]
                    data["cached_content_length"] = cached["content_length"]

            return ResultResponse(data=data)

        except Exception as e:
            logger.exception(f"Error fetching page: {e}")
            # Try cache fallback even on exception
            cache_svc = getattr(self.daemon, "_page_cache_service", None)
            if cache_svc:
                if using_url:
                    cached = cache_svc.get_cached_url(
                        req.url,
                        max_age=cache_svc.get_cache_ttl_for_url(req.url),
                    )
                else:
                    cached = cache_svc.get_cached_page(req.destination_hash, req.path)
                if cached:
                    return ResultResponse(data={
                        "content": "",
                        "status": "error",
                        "destination_hash": req.destination_hash,
                        "path": req.path,
                        "transfer_time": 0.0,
                        "content_length": 0,
                        "error_message": str(e),
                        "cached_content": cached["content"],
                        "cached_at": cached["fetched_at"],
                        "cached_content_length": cached["content_length"],
                    })
            return ErrorResponse.internal_error(f"Failed to fetch page: {e}")

    def _check_page_server(self) -> ErrorResponse | None:
        """Check if page server service is available."""
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None
        if not getattr(self.daemon, "_page_server_service", None):
            return ErrorResponse.internal_error("Page server service not initialized")
        return None

    async def handle_query_page_server_status(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_PAGE_SERVER_STATUS request.

        Returns page server status including pages directory, destination
        ownership, registered handlers, and static pages.

        Args:
            request: QueryPageServerStatusRequest instance.

        Returns:
            ResultResponse with page server status.
        """
        err = self._check_page_server()
        if err:
            return err
        assert self.daemon is not None

        svc = self.daemon._page_server_service
        try:
            data: dict[str, object] = {
                "enabled": True,
                "started": svc.is_started,
                "owns_destination": svc.owns_destination,
                "pages_dir": str(svc.pages_dir) if svc.pages_dir else None,
                "static_pages": svc.static_pages,
                "registered_handlers": svc.registered_handlers,
            }
            return ResultResponse(data=data)

        except Exception as e:
            logger.exception(f"Error querying page server status: {e}")
            return ErrorResponse.internal_error(f"Failed to query page server status: {e}")

    async def handle_cmd_page_regenerate(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_PAGE_REGENERATE request.

        Regenerates the default node info index page with current
        system and capability information.

        Returns:
            ResultResponse with regeneration status.
        """
        err = self._check_page_server()
        if err:
            return err
        assert self.daemon is not None

        try:
            svc = self.daemon._page_server_service
            success = svc.regenerate_index()
            return ResultResponse(data={
                "regenerated": success,
                "pages_dir": str(svc.pages_dir) if svc.pages_dir else None,
            })
        except Exception as e:
            logger.exception(f"Error regenerating index page: {e}")
            return ErrorResponse.internal_error(f"Failed to regenerate index page: {e}")

    async def handle_cmd_page_disconnect(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_PAGE_DISCONNECT request.

        Disconnects a cached link to a NomadNet node.

        Args:
            request: CmdPageDisconnectRequest instance.

        Returns:
            ResultResponse with disconnect status.
        """
        err = self._check_page_browser()
        if err:
            return err
        assert self.daemon is not None

        req = (
            request
            if isinstance(request, CmdPageDisconnectRequest)
            else CmdPageDisconnectRequest()
        )

        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            disconnected = await self.daemon._page_browser_service.disconnect(
                req.destination_hash
            )

            return ResultResponse(data={"disconnected": disconnected})

        except Exception as e:
            logger.exception(f"Error disconnecting page link: {e}")
            return ErrorResponse.internal_error(f"Failed to disconnect page link: {e}")

    def _check_page_cache(self) -> ErrorResponse | None:
        """Check if page cache service is available."""
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None
        if not getattr(self.daemon, "_page_cache_service", None):
            return ErrorResponse.internal_error("Page cache service not initialized")
        return None

    async def handle_cmd_page_save_site(self, request: IPCRequest) -> IPCResponse:
        """Save a NomadNet node for periodic background crawling."""
        err = self._check_page_cache()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdPageSaveSiteRequest

        req = request if isinstance(request, CmdPageSaveSiteRequest) else CmdPageSaveSiteRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            self.daemon._page_cache_service.save_site(
                destination_hash=req.destination_hash,
                display_name=req.display_name,
                refresh_interval=req.refresh_interval,
                max_depth=req.max_depth,
            )
            return ResultResponse(data={"saved": True})
        except Exception as e:
            return ErrorResponse.internal_error(f"Failed to save site: {e}")

    async def handle_cmd_page_remove_site(self, request: IPCRequest) -> IPCResponse:
        """Remove a saved NomadNet site."""
        err = self._check_page_cache()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdPageRemoveSiteRequest

        req = request if isinstance(request, CmdPageRemoveSiteRequest) else CmdPageRemoveSiteRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            removed = self.daemon._page_cache_service.remove_site(req.destination_hash)
            return ResultResponse(data={"removed": removed})
        except Exception as e:
            return ErrorResponse.internal_error(f"Failed to remove site: {e}")

    async def handle_cmd_page_list_sites(self, request: IPCRequest) -> IPCResponse:
        """List all saved NomadNet sites."""
        err = self._check_page_cache()
        if err:
            return err
        assert self.daemon is not None

        try:
            sites = self.daemon._page_cache_service.list_saved_sites()
            return ResultResponse(data={"sites": sites})
        except Exception as e:
            return ErrorResponse.internal_error(f"Failed to list saved sites: {e}")

    async def handle_cmd_page_crawl_site(self, request: IPCRequest) -> IPCResponse:
        """Manually trigger a full site crawl."""
        err = self._check_page_cache()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdPageCrawlSiteRequest

        req = request if isinstance(request, CmdPageCrawlSiteRequest) else CmdPageCrawlSiteRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            import asyncio

            # Fire-and-forget: crawl can take minutes over mesh,
            # far exceeding the 30s IPC timeout.  Return immediately.
            asyncio.create_task(
                self.daemon._page_cache_service.crawl_site(
                    destination_hash=req.destination_hash,
                    max_depth=req.max_depth,
                )
            )
            return ResultResponse(data={"started": True})
        except Exception as e:
            return ErrorResponse.internal_error(f"Failed to start crawl: {e}")

    async def handle_cmd_page_get_cached(self, request: IPCRequest) -> IPCResponse:
        """Get a cached page by destination and path."""
        err = self._check_page_cache()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdPageGetCachedRequest

        req = request if isinstance(request, CmdPageGetCachedRequest) else CmdPageGetCachedRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            cached = self.daemon._page_cache_service.get_cached_page(
                req.destination_hash, req.path
            )
            if cached:
                return ResultResponse(data={
                    "found": True,
                    "content": cached["content"],
                    "content_length": cached["content_length"],
                    "fetched_at": cached["fetched_at"],
                })
            return ResultResponse(data={"found": False})
        except Exception as e:
            return ErrorResponse.internal_error(f"Failed to get cached page: {e}")

    # -------------------------------------------------------------------------
    # Terminal handlers
    # -------------------------------------------------------------------------

    def _check_styrene_protocol(self) -> ErrorResponse | None:
        """Check if StyreneProtocol is available for terminal operations."""
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None
        if not getattr(self.daemon, "_styrene_protocol", None):
            return ErrorResponse.internal_error("Styrene protocol not initialized")
        return None

    async def handle_cmd_terminal_open(
        self, request: IPCRequest, client: Any = None
    ) -> IPCResponse:
        """Handle CMD_TERMINAL_OPEN request.

        Creates a TerminalClient, connects to the remote node, and wires
        callbacks to push terminal events to the originating IPC client.

        Args:
            request: CmdTerminalOpenRequest instance.
            client: ClientConnection that opened this session (for event routing).

        Returns:
            ResultResponse with session_id on success.
        """
        err = self._check_styrene_protocol()
        if err:
            return err
        assert self.daemon is not None

        req = (
            request
            if isinstance(request, CmdTerminalOpenRequest)
            else CmdTerminalOpenRequest()
        )

        if not req.destination:
            return ErrorResponse.invalid_request("destination is required")

        try:
            from styrened.ipc.protocol import IPCMessageType
            from styrened.terminal import TerminalClient

            terminal_client = TerminalClient(self.daemon._styrene_protocol)

            session = await terminal_client.connect(
                destination=req.destination,
                term_type=req.term_type,
                rows=req.rows,
                cols=req.cols,
                shell=req.shell,
                timeout=30.0,
            )

            if session is None:
                return ErrorResponse.internal_error(
                    f"Terminal connection rejected by {req.destination[:16]}..."
                )

            session_id_hex = session.session_id.hex()

            # Store session with client reference for event routing
            self._terminal_sessions[session_id_hex] = {
                "session": session,
                "client": client,
                "terminal_client": terminal_client,
            }

            # Get the event loop for thread-safe callback scheduling
            loop = asyncio.get_running_loop()

            # Wire callbacks from TerminalClientSession to IPC events
            def on_output(data: bytes) -> None:
                """Forward terminal output to IPC client (runs in RNS thread)."""
                if client is None or client.closed:
                    return
                payload = {
                    "session_id": session_id_hex,
                    "data_b64": base64.b64encode(data).decode("ascii"),
                }
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    client.send_event(IPCMessageType.EVENT_TERMINAL_OUTPUT, payload),
                )

            def on_exit(exit_code: int) -> None:
                """Forward terminal exit to IPC client (runs in RNS thread)."""
                payload = {
                    "session_id": session_id_hex,
                    "exit_code": exit_code,
                }
                if client is not None and not client.closed:
                    loop.call_soon_threadsafe(
                        asyncio.ensure_future,
                        client.send_event(IPCMessageType.EVENT_TERMINAL_EXITED, payload),
                    )
                # Clean up session
                self._terminal_sessions.pop(session_id_hex, None)

            def on_error(message: str) -> None:
                """Forward terminal error to IPC client (runs in RNS thread)."""
                if client is None or client.closed:
                    return
                payload = {
                    "session_id": session_id_hex,
                    "error": message,
                }
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    client.send_event(IPCMessageType.EVENT_TERMINAL_ERROR, payload),
                )

            session.on_output = on_output
            session.on_exit = on_exit
            session.on_error = on_error

            # Establish RNS Link for data plane
            connected = await session.connect()
            if not connected:
                self._terminal_sessions.pop(session_id_hex, None)
                return ErrorResponse.internal_error(
                    "Failed to establish RNS Link to remote terminal"
                )

            # Send READY event
            if client is not None and not client.closed:
                await client.send_event(
                    IPCMessageType.EVENT_TERMINAL_READY,
                    {"session_id": session_id_hex},
                )

            return ResultResponse(
                data={
                    "session_id": session_id_hex,
                    "connected": True,
                }
            )

        except Exception as e:
            logger.exception(f"Error opening terminal: {e}")
            return ErrorResponse.internal_error(f"Failed to open terminal: {e}")

    async def handle_cmd_terminal_input(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_TERMINAL_INPUT request.

        Forwards input data to the terminal session.

        Args:
            request: CmdTerminalInputRequest instance.

        Returns:
            ResultResponse on success.
        """
        req = (
            request
            if isinstance(request, CmdTerminalInputRequest)
            else CmdTerminalInputRequest()
        )

        if not req.session_id:
            return ErrorResponse.invalid_request("session_id is required")

        entry = self._terminal_sessions.get(req.session_id)
        if not entry:
            return ErrorResponse.not_found(f"Terminal session not found: {req.session_id[:16]}...")

        try:
            data = base64.b64decode(req.data_b64)
            session = entry["session"]
            sent = session.send_input(data)
            return ResultResponse(data={"sent": sent})
        except Exception as e:
            logger.warning(f"Error sending terminal input: {e}")
            return ErrorResponse.internal_error(f"Failed to send terminal input: {e}")

    async def handle_cmd_terminal_resize(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_TERMINAL_RESIZE request.

        Sends window resize to the terminal session.

        Args:
            request: CmdTerminalResizeRequest instance.

        Returns:
            ResultResponse on success.
        """
        req = (
            request
            if isinstance(request, CmdTerminalResizeRequest)
            else CmdTerminalResizeRequest()
        )

        if not req.session_id:
            return ErrorResponse.invalid_request("session_id is required")

        entry = self._terminal_sessions.get(req.session_id)
        if not entry:
            return ErrorResponse.not_found(f"Terminal session not found: {req.session_id[:16]}...")

        try:
            session = entry["session"]
            sent = session.send_resize(req.rows, req.cols)
            return ResultResponse(data={"resized": sent})
        except Exception as e:
            logger.warning(f"Error resizing terminal: {e}")
            return ErrorResponse.internal_error(f"Failed to resize terminal: {e}")

    async def handle_cmd_terminal_close(self, request: IPCRequest) -> IPCResponse:
        """Handle CMD_TERMINAL_CLOSE request.

        Closes a terminal session gracefully.

        Args:
            request: CmdTerminalCloseRequest instance.

        Returns:
            ResultResponse on success.
        """
        req = (
            request
            if isinstance(request, CmdTerminalCloseRequest)
            else CmdTerminalCloseRequest()
        )

        if not req.session_id:
            return ErrorResponse.invalid_request("session_id is required")

        entry = self._terminal_sessions.pop(req.session_id, None)
        if not entry:
            return ErrorResponse.not_found(f"Terminal session not found: {req.session_id[:16]}...")

        try:
            session = entry["session"]
            await session.close()
            return ResultResponse(data={"closed": True})
        except Exception as e:
            logger.warning(f"Error closing terminal: {e}")
            return ErrorResponse.internal_error(f"Failed to close terminal: {e}")

    # ── Direct data link handlers ──────────────────────────────────

    def _check_direct_link(self) -> ErrorResponse | None:
        """Check if direct link service is available."""
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None
        if not getattr(self.daemon, "_direct_link_service", None):
            return ErrorResponse.internal_error("Direct link service not initialized")
        return None

    async def handle_cmd_block_peer(self, request: IPCRequest) -> IPCResponse:
        """Block a peer — silently drop all future messages.

        Accepts identity_hash (preferred) or peer_hash (deprecated compat shim).
        If only peer_hash is provided, resolves to identity_hash via NodeStore.
        Shim is removed at 0.17.0.
        """
        from styrened.ipc.messages import CmdBlockPeerRequest

        assert isinstance(request, CmdBlockPeerRequest)
        identity_hash = request.identity_hash
        lxmf_dest_hash = request.lxmf_dest_hash
        alias = request.alias

        # Compat shim: resolve deprecated peer_hash → identity_hash via NodeStore
        if not identity_hash and lxmf_dest_hash:
            try:
                from styrened.services.node_store import get_node_store
                store = get_node_store()
                resolved = store.get_identity_for_lxmf_destination(lxmf_dest_hash)
                if resolved:
                    identity_hash = resolved
                    logger.debug(
                        "block_peer: resolved peer_hash %s → identity_hash %s (compat shim)",
                        lxmf_dest_hash[:16], identity_hash[:16],
                    )
                else:
                    # Best-effort: use dest hash as identity key (self-heals on next announce)
                    identity_hash = lxmf_dest_hash
                    logger.debug(
                        "block_peer: peer_hash %s not in NodeStore, using as identity key (best-effort)",
                        lxmf_dest_hash[:16],
                    )
            except Exception as e:
                logger.warning("block_peer: NodeStore lookup failed: %s", e)
                identity_hash = lxmf_dest_hash

        if not identity_hash:
            return ErrorResponse(message="identity_hash required")
        if len(identity_hash) < 16 or not all(c in "0123456789abcdefABCDEF" for c in identity_hash):
            return ErrorResponse(message="identity_hash must be a valid hex string (min 16 chars)")

        from styrened.services.lxmf_service import get_lxmf_service

        svc = get_lxmf_service()
        if svc.block_peer(identity_hash, lxmf_dest_hash=lxmf_dest_hash, alias=alias):
            return ResultResponse(data={"blocked": True, "identity_hash": identity_hash})
        return ErrorResponse(message="Failed to block peer")

    async def handle_cmd_unblock_peer(self, request: IPCRequest) -> IPCResponse:
        """Unblock a previously blocked peer."""
        from styrened.ipc.messages import CmdUnblockPeerRequest

        assert isinstance(request, CmdUnblockPeerRequest)
        identity_hash = request.identity_hash
        if not identity_hash:
            return ErrorResponse(message="identity_hash required")

        from styrened.services.lxmf_service import get_lxmf_service

        svc = get_lxmf_service()
        if svc.unblock_peer(identity_hash):
            return ResultResponse(data={"unblocked": True, "identity_hash": identity_hash})
        return ErrorResponse(message="Failed to unblock peer")

    async def handle_query_blocked_peers(self, request: IPCRequest) -> IPCResponse:
        """List all blocked peers."""
        from styrened.services.lxmf_service import get_lxmf_service

        svc = get_lxmf_service()
        blocked = svc.get_blocked_peers()
        return ResultResponse(data={"blocked_peers": blocked})

    async def handle_cmd_datalink_establish(self, request: IPCRequest) -> IPCResponse:
        """Establish a direct data link to a Styrene peer."""
        err = self._check_direct_link()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdDatalinkEstablishRequest

        req = request if isinstance(request, CmdDatalinkEstablishRequest) else CmdDatalinkEstablishRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            import asyncio
            info = await asyncio.wait_for(
                self.daemon._direct_link_service.establish(req.destination_hash),
                timeout=60.0,
            )
            return ResultResponse(data={
                "status": info.status,
                "rtt": info.rtt,
                "established_at": info.established_at,
            })
        except TimeoutError:
            return ErrorResponse.internal_error("Link establishment timed out (60s)")
        except Exception as e:
            return ErrorResponse.internal_error(f"Failed to establish link: {e}")

    async def handle_cmd_datalink_teardown(self, request: IPCRequest) -> IPCResponse:
        """Tear down a direct data link."""
        err = self._check_direct_link()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdDatalinkTeardownRequest

        req = request if isinstance(request, CmdDatalinkTeardownRequest) else CmdDatalinkTeardownRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            result = await self.daemon._direct_link_service.teardown(req.destination_hash)
            return ResultResponse(data={"torn_down": result})
        except Exception as e:
            return ErrorResponse.internal_error(f"Failed to teardown link: {e}")

    async def handle_cmd_datalink_status(self, request: IPCRequest) -> IPCResponse:
        """Get direct link status for a peer."""
        err = self._check_direct_link()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdDatalinkStatusRequest

        req = request if isinstance(request, CmdDatalinkStatusRequest) else CmdDatalinkStatusRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            info = self.daemon._direct_link_service.get_link_info(req.destination_hash)
            if info is None:
                return ResultResponse(data={"connected": False, "status": "none"})
            return ResultResponse(data={
                "connected": info.status == "active",
                "status": info.status,
                "rtt": info.rtt,
                "established_at": info.established_at,
                "last_activity": info.last_activity,
            })
        except Exception as e:
            return ErrorResponse.internal_error(f"Failed to get link status: {e}")

    async def handle_cmd_datalink_query(self, request: IPCRequest) -> IPCResponse:
        """Query peer status over an established direct link."""
        err = self._check_direct_link()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdDatalinkQueryRequest

        req = request if isinstance(request, CmdDatalinkQueryRequest) else CmdDatalinkQueryRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            status = await self.daemon._direct_link_service.request_status(req.destination_hash)
            if status is None:
                return ErrorResponse.not_found("No active link or query failed")
            return ResultResponse(data={"status_data": status})
        except Exception as e:
            return ErrorResponse.internal_error(f"Datalink query failed: {e}")

    async def handle_cmd_datalink_meta(self, request: IPCRequest) -> IPCResponse:
        """Request non-identifiable metadata from peer over direct link."""
        err = self._check_direct_link()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdDatalinkMetaRequest

        req = request if isinstance(request, CmdDatalinkMetaRequest) else CmdDatalinkMetaRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            meta = await self.daemon._direct_link_service.request_meta(req.destination_hash)
            return ResultResponse(data={"meta": meta})
        except Exception as e:
            return ErrorResponse.internal_error(f"Datalink meta request failed: {e}")

    async def handle_cmd_datalink_info(self, request: IPCRequest) -> IPCResponse:
        """Request identifiable metadata from peer over direct link.

        A None result in the response means the remote node declined (default).
        This is not an error — it means info_respond=False on the remote.
        """
        err = self._check_direct_link()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdDatalinkInfoRequest

        req = request if isinstance(request, CmdDatalinkInfoRequest) else CmdDatalinkInfoRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            info = await self.daemon._direct_link_service.request_info(req.destination_hash)
            return ResultResponse(data={"info": info})
        except Exception as e:
            return ErrorResponse.internal_error(f"Datalink info request failed: {e}")

    async def handle_cmd_datalink_speedtest(self, request: IPCRequest) -> IPCResponse:
        """Run bandwidth test over direct link — fire-and-forget style.

        Returns results directly since the test is self-timed and the
        IPC timeout (30s default) should be sufficient for the default
        payload set.  For very large payloads or slow links, increase
        the client timeout.
        """
        err = self._check_direct_link()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdDatalinkSpeedtestRequest

        req = request if isinstance(request, CmdDatalinkSpeedtestRequest) else CmdDatalinkSpeedtestRequest()
        if not req.destination_hash:
            return ErrorResponse.invalid_request("destination_hash is required")

        try:
            # run_speedtest auto-scales timeouts per-transfer based on link RTT.
            # No total timeout here — the individual transfers handle their own.
            results = await self.daemon._direct_link_service.run_speedtest(
                req.destination_hash,
            )
            return ResultResponse(data={"results": results})
        except Exception as e:
            return ErrorResponse.internal_error(f"Speedtest failed: {e}")

    # -------------------------------------------------------------------------
    # Boundary logging
    # -------------------------------------------------------------------------

    async def handle_cmd_boundary_snapshot(self, request: IPCRequest) -> IPCResponse:
        """Return a snapshot of the boundary log ring buffer.

        Returns up to 200 serialized boundary records with keys:
        ts, boundary, severity, retryable, stack_name, operation, message.
        Returns an empty list if the handler is not initialised.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None

        boundary_handler = getattr(self.daemon, "_boundary_handler", None)
        if boundary_handler is None:
            return ResultResponse(data={"records": []})

        try:
            records = boundary_handler.snapshot()
            return ResultResponse(data={"records": records})
        except Exception as e:
            return ErrorResponse.internal_error(f"Boundary snapshot failed: {e}")

    async def handle_cmd_provision_adapter(self, request: IPCRequest) -> IPCResponse:
        """Provision an adapter binary locally.

        LOCAL (IPC) context bypasses RBAC — the operator is on the local machine.
        """
        err = self._check_daemon()
        if err:
            return err
        assert self.daemon is not None

        from styrened.ipc.messages import CmdProvisionAdapterRequest

        req = request if isinstance(request, CmdProvisionAdapterRequest) else CmdProvisionAdapterRequest()
        if not req.adapter_name:
            return ErrorResponse.invalid_request("adapter_name is required")

        provisioner = getattr(self.daemon, "_binary_provisioner", None)
        if provisioner is None:
            return ErrorResponse.internal_error("Binary provisioner not available")

        try:
            result = provisioner.provision(req.adapter_name)
            return ResultResponse(data=result)
        except Exception as e:
            return ErrorResponse.internal_error(f"Provisioning failed: {e}")

