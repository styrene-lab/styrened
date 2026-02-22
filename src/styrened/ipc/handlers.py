"""IPC request handlers for control server.

Implements handlers for all IPC request types, accessing daemon services
to fulfill queries and execute commands.

Usage:
    from styrened.ipc.handlers import IPCHandlers

    handlers = IPCHandlers(daemon)
    response = await handlers.handle_query_devices(request)
"""

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
    CmdRemoveContactRequest,
    CmdRetryMessageRequest,
    CmdSendChatRequest,
    CmdSendRequest,
    CmdSetAutoReplyRequest,
    CmdSetContactRequest,
    DaemonStatus,
    DeviceInfo,
    ErrorResponse,
    ExecResultInfo,
    IdentityInfo,
    IPCRequest,
    IPCResponse,
    PongResponse,
    QueryContactsRequest,
    QueryConversationsRequest,
    QueryDevicesRequest,
    QueryMessagesRequest,
    QueryResolveNameRequest,
    QuerySearchMessagesRequest,
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
                result = lxmf_service.send_message(req.destination, payload)
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
            )

            return ResultResponse(data=status_info.to_dict())

        except TimeoutError:
            return ErrorResponse.timeout(f"Status request timed out after {req.timeout}s")
        except Exception as e:
            logger.exception(f"Error querying device status: {e}")
            return ErrorResponse.internal_error(f"Failed to query device status: {e}")

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

    async def handle_query_conversations(self, request: IPCRequest) -> IPCResponse:
        """Handle QUERY_CONVERSATIONS request.

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
            conv_list = [c.to_dict() for c in conversations]

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

            messages = self.daemon._conversation_service.get_messages(
                peer_hash=req.peer_hash,
                limit=limit,
                before_timestamp=req.before_timestamp,
                status_filter=req.status_filter,
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
        if not req.content or not isinstance(req.content, str):
            return ErrorResponse.invalid_request("content is required and must be a string")

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

            # Build message fields
            fields: dict[str, object] = {"protocol": "chat"}
            if req.title:
                fields["title"] = req.title

            # Build LXMF payload
            payload: dict[str, object] = {
                "type": "chat",
                "protocol": "chat",
                "content": req.content,
            }
            if req.title:
                payload["title"] = req.title

            # Get conversation service reference for callbacks
            conversation_service = self.daemon._conversation_service

            # Step 1: Save message FIRST (avoids race with fast delivery callbacks)
            msg_id = conversation_service.save_outgoing_message(
                destination_hash=req.peer_hash,
                content=req.content,
                title=req.title,
                fields=fields,
                reply_to_hash=req.reply_to_hash,
                # Don't pass lxmf_hash yet - we register tracking after send
            )

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

            # Step 4: Send via LXMF with race-safe callbacks
            result = lxmf_service.send_message(
                req.peer_hash,
                payload,
                on_delivery=register_and_callback_delivery,
                on_failed=register_and_callback_failed,
                delivery_method=delivery_method,
                lxmf_fields=lxmf_fields if lxmf_fields else None,
            )

            if result is None:
                # Send failed - mark message as failed
                conversation_service.update_message_status(msg_id, "failed")
                return ErrorResponse.internal_error(
                    f"Failed to send message to {req.peer_hash[:16]}... "
                    "(no path or identity not known)"
                )

            # Extract hash, method, and actual destination hash from result
            lxmf_hash: bytes = result["hash"]
            delivery_method_used: str = result.get("method", delivery_method)
            actual_dest_hash: str = result.get("destination_hash", req.peer_hash)

            # Step 5: Update destination_hash to the full resolved hash
            # This normalizes truncated peer_hash inputs to full 32-char hashes
            if actual_dest_hash != req.peer_hash:
                conversation_service.update_destination_hash(msg_id, actual_dest_hash)

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

            count = self.daemon._conversation_service.mark_read(req.peer_hash)

            # Send read receipts to peer for ecosystem compatibility
            # This is fire-and-forget; don't fail the mark_read if receipts fail
            try:
                await self.daemon.send_read_receipts(req.peer_hash)
            except Exception as receipt_err:
                logger.warning(f"Failed to send read receipts: {receipt_err}")

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

            count = self.daemon._conversation_service.delete_conversation(req.peer_hash)

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

            # Send via LXMF
            result = lxmf_service.send_message(
                dest_hash,
                payload,
                on_delivery=on_delivery,
                on_failed=on_failed,
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
                    "enabled": self.daemon.config.chat.auto_reply_enabled,
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
            from styrened.services.config import save_core_config

            self.daemon.config.chat.auto_reply_enabled = req.enabled
            if req.message:
                self.daemon.config.chat.auto_reply_message = req.message
            if req.cooldown > 0:
                self.daemon.config.chat.auto_reply_cooldown = req.cooldown

            # Persist to disk
            save_core_config(self.daemon.config)

            # Re-announce to propagate capability change
            self.daemon._announce()

            return ResultResponse(
                data={
                    "enabled": self.daemon.config.chat.auto_reply_enabled,
                    "message": self.daemon.config.chat.auto_reply_message,
                    "cooldown": self.daemon.config.chat.auto_reply_cooldown,
                }
            )
        except Exception as e:
            logger.exception(f"Error setting auto-reply: {e}")
            return ErrorResponse.internal_error(f"Failed to set auto-reply: {e}")
