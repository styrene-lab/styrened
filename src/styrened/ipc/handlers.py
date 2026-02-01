"""IPC request handlers for control server.

Implements handlers for all IPC request types, accessing daemon services
to fulfill queries and execute commands.

Usage:
    from styrened.ipc.handlers import IPCHandlers

    handlers = IPCHandlers(daemon)
    response = await handlers.handle_query_devices(request)
"""

import logging
import time
from typing import TYPE_CHECKING

from styrened.ipc.messages import (
    CmdDeviceStatusRequest,
    CmdExecRequest,
    CmdSendRequest,
    DaemonStatus,
    DeviceInfo,
    ErrorResponse,
    ExecResultInfo,
    IdentityInfo,
    IPCRequest,
    IPCResponse,
    PongResponse,
    QueryDevicesRequest,
    RemoteStatusInfo,
    ResultResponse,
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

    def __init__(self, daemon: "StyreneDaemon | None") -> None:
        """Initialize handlers.

        Args:
            daemon: StyreneDaemon instance for accessing services. May be None
                during testing or partial initialization.
        """
        self.daemon = daemon

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

            info = IdentityInfo(
                identity_hash=identity_hash,
                destination_hash=destination_hash,
                lxmf_destination_hash=lxmf_destination_hash,
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

            status = DaemonStatus(
                uptime=uptime,
                daemon_version=__version__,
                rns_initialized=rns_initialized,
                lxmf_initialized=lxmf_initialized,
                device_count=device_count,
                styrene_node_count=styrene_count,
                pending_rpc_count=pending_rpc,
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
                    "auto_reply_enabled": config.chat.auto_reply_enabled,
                    "auto_reply_cooldown": config.chat.auto_reply_cooldown,
                    "persist_messages": config.chat.persist_messages,
                },
                "api": {
                    "enabled": config.api.enabled,
                    "port": config.api.port,
                },
            }

            return ResultResponse(data={"config": config_dict})

        except Exception as e:
            logger.exception(f"Error querying config: {e}")
            return ErrorResponse.internal_error(f"Failed to query config: {e}")

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

            if req.retry:
                success = lxmf_service.send_with_retry(
                    req.destination,
                    payload,
                    max_wait=req.timeout,
                )
            else:
                success = lxmf_service.send_message(req.destination, payload)

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
            )

            return ResultResponse(data=status_info.to_dict())

        except TimeoutError:
            return ErrorResponse.timeout(f"Status request timed out after {req.timeout}s")
        except Exception as e:
            logger.exception(f"Error querying device status: {e}")
            return ErrorResponse.internal_error(f"Failed to query device status: {e}")
