"""RPC server for handling incoming requests over Styrene protocol.

This module implements the server-side RPC handler that processes incoming
RPC requests and sends responses using the Styrene wire protocol.
It complements the RPCClient which sends requests.

Wire Format:
    Uses StyreneProtocol with FIELD_CUSTOM_TYPE="styrene.io" and
    FIELD_CUSTOM_DATA containing the v2 wire format with 16-byte request_id
    for correlation.

The RPC server handles:
- STATUS_REQUEST (0x10): Returns system status (uptime, IP, disk, services)
- EXEC (0x40): Executes commands and returns output
- REBOOT (0x41): Schedules system reboot
- CONFIG_UPDATE (0x42): Updates local configuration

Security:
    Every RPC message type is mapped to a capability via ``MESSAGE_TYPE_CAPABILITY``.
    The RBAC policy's ``has_capability()`` method is checked for every request —
    there are no "public" bypasses. Unmapped message types are rejected (fail-closed).

Usage:
    from styrened.rpc import RPCServer
    from styrened.protocols.styrene import StyreneProtocol
    from styrened.models.rbac import RBACPolicy, Role

    policy = RBACPolicy(default_role=Role.PEER)
    server = RPCServer(styrene_protocol, rbac_policy=policy)

    # Start server
    server.start()

    # Server automatically handles incoming Styrene RPC messages
"""

import asyncio
import logging
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable

from typing import TYPE_CHECKING, Any

from styrened import __version__ as _styrened_version
from styrened.models.rbac import Capability, RBACPolicy
from styrened.models.styrene_wire import (
    NO_CORRELATION,
    StyreneEnvelope,
    StyreneMessageType,
    create_config_result,
    create_error,
    create_exec_result,
    create_inbox_response,
    create_messages_response,
    create_reboot_result,
    create_self_update_result,
    create_status_response,
    decode_payload,
)
from styrened.protocols.base import LXMFMessage
from styrened.services.system_info import get_os_info

# Import response types for backward compatibility

if TYPE_CHECKING:
    from styrened.protocols.styrene import StyreneProtocol

logger = logging.getLogger(__name__)

# Default allowed commands for exec (security whitelist)
DEFAULT_ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "systemctl",
        "journalctl",
        "df",
        "free",
        "uptime",
        "hostname",
        "uname",
        "cat",
        "ls",
        "ps",
        "top",
        "htop",
        "ping",
        "ip",
        "ss",
        "netstat",
        "date",
        "whoami",
        "id",
        "env",
        "echo",
        "rnstatus",
        "rnpath",
        "lxmd",
    }
)

# Rate limiting defaults
DEFAULT_RPC_RATE_LIMIT = 30  # requests per minute per identity
RATE_LIMIT_WINDOW_SECONDS = 60

# Replay protection
MAX_RECENT_REQUEST_IDS = 1000  # Track this many recent request_ids
REQUEST_ID_EXPIRY_SECONDS = 300  # Request IDs older than this are expired

# Commands that are considered "dangerous" and require explicit enablement
DANGEROUS_RPC_COMMANDS: frozenset[StyreneMessageType] = frozenset(
    {
        StyreneMessageType.EXEC,
        StyreneMessageType.REBOOT,
        StyreneMessageType.CONFIG_UPDATE,
        StyreneMessageType.SELF_UPDATE,
    }
)

# Commands that don't require authorization (safe read-only commands)
PUBLIC_RPC_COMMANDS: frozenset[StyreneMessageType] = frozenset(
    {
        StyreneMessageType.PING,
        StyreneMessageType.STATUS_REQUEST,
    }
)

# RBAC: map each RPC message type to the capability required to invoke it.
# Used when an RBACPolicy is active; legacy auth is bypassed entirely.
MESSAGE_TYPE_CAPABILITY: dict[StyreneMessageType, str] = {
    StyreneMessageType.PING: Capability.PING,
    StyreneMessageType.STATUS_REQUEST: Capability.STATUS_QUERY,
    StyreneMessageType.EXEC: Capability.EXEC,
    StyreneMessageType.REBOOT: Capability.REBOOT,
    StyreneMessageType.CONFIG_UPDATE: Capability.CONFIG_UPDATE,
    StyreneMessageType.SELF_UPDATE: Capability.SELF_UPDATE,
    StyreneMessageType.PROVISION: Capability.ADAPTER_PROVISION,
    StyreneMessageType.INBOX_QUERY: Capability.INBOX_READ,
    StyreneMessageType.MESSAGES_QUERY: Capability.INBOX_READ,
}


# Error codes for RPC errors
class RPCErrorCode:
    """Standard error codes for RPC errors."""

    UNKNOWN = 0
    INVALID_REQUEST = 1
    COMMAND_NOT_ALLOWED = 2
    COMMAND_NOT_FOUND = 3
    COMMAND_TIMEOUT = 4
    COMMAND_FAILED = 5
    REBOOT_FAILED = 6
    CONFIG_FAILED = 7


class RPCServer:
    """RPC server for handling incoming Styrene protocol requests.

    Listens for incoming RPC messages via StyreneProtocol and dispatches them to
    appropriate handlers. Responses are sent back using the Styrene wire format.

    Security:
        Every message type is mapped to a capability via MESSAGE_TYPE_CAPABILITY.
        The RBAC policy's has_capability() is checked for every request.
        Unmapped message types are rejected (fail-closed).

    Attributes:
        styrene_protocol: StyreneProtocol instance for sending responses.
        allowed_commands: Set of commands allowed for exec (security).
        _running: Whether the server is running.
    """

    def __init__(
        self,
        styrene_protocol: "StyreneProtocol",
        allowed_commands: set[str] | None = None,
        rate_limit: int = DEFAULT_RPC_RATE_LIMIT,
        rbac_policy: RBACPolicy | None = None,  # None → default RBACPolicy()
    ) -> None:
        """Initialize RPC server.

        Args:
            styrene_protocol: StyreneProtocol instance for transport.
            allowed_commands: Set of allowed commands for exec.
                            Defaults to DEFAULT_ALLOWED_COMMANDS.
            rate_limit: Maximum requests per minute per identity.
            rbac_policy: RBACPolicy for capability-based authorization.
                        If None, a default PEER policy is used.
        """
        self._protocol = styrene_protocol
        self._rbac_policy = rbac_policy or RBACPolicy()
        self.allowed_commands = allowed_commands or set(DEFAULT_ALLOWED_COMMANDS)
        self._running = False
        self._handlers: dict[StyreneMessageType, Callable[[str, StyreneEnvelope], None]] = {}

        # Conversation service for inbox queries (injected after init)
        self._conversation_service: Any = None

        # Rate limiting
        self._rate_limit = rate_limit
        self._request_timestamps: dict[str, list[float]] = {}

        # Replay protection - track recent request_ids with timestamps
        self._recent_request_ids: dict[bytes, float] = {}

        # Optional daemon reference for activity event emission
        self._daemon: Any = None

        # Optional overlay adapter references for /meta enrichment
        self._ygg_adapter: Any = None
        self._i2p_adapter: Any = None

        # Optional binary provisioner for CMD_PROVISION
        self._binary_provisioner: Any = None

        # Log security configuration
        logger.info(
            f"[SECURITY] RPC server initialized with RBAC policy "
            f"(default_role={self._rbac_policy.default_role.name}, "
            f"roster={len(self._rbac_policy.roster)}, "
            f"blocked={len(self._rbac_policy.blocked)})"
        )

        # Register default handlers
        self._register_default_handlers()

        # Register with StyreneProtocol for message routing
        self._register_with_protocol()

        logger.debug("RPCServer initialized with StyreneProtocol")

    def set_conversation_service(self, service: Any) -> None:
        """Inject conversation service for inbox query handling.

        Args:
            service: ConversationService instance.
        """
        self._conversation_service = service
        logger.info("Conversation service injected into RPC server")

    def set_ygg_adapter(self, adapter: Any) -> None:
        """Inject YggdrasilAdapter for /meta enrichment.

        When the adapter is running, ygg_address and ygg_port are included
        in _gather_meta() responses. When None or not running, the keys are
        omitted entirely.

        Args:
            adapter: YggdrasilAdapter instance (or None to clear).
        """
        self._ygg_adapter = adapter
        logger.info("YggdrasilAdapter injected into RPC server")

    def set_i2p_adapter(self, adapter: Any) -> None:
        """Inject I2PAdapter for /meta enrichment.

        When the adapter knows a local b32 address, ``b32_address`` is included
        in _gather_meta() responses and the ``i2p`` capability is advertised.

        Args:
            adapter: I2PAdapter instance (or None to clear).
        """
        self._i2p_adapter = adapter
        logger.info("I2PAdapter injected into RPC server")

    def set_binary_provisioner(self, provisioner: Any) -> None:
        """Inject BinaryProvisioner for CMD_PROVISION handling.

        Args:
            provisioner: BinaryProvisioner instance (or None to clear).
        """
        self._binary_provisioner = provisioner
        logger.info("BinaryProvisioner injected into RPC server")

    def _register_with_protocol(self) -> None:
        """Register RPC message handlers with StyreneProtocol."""
        # Register for RPC command types
        rpc_types = [
            StyreneMessageType.STATUS_REQUEST,
            StyreneMessageType.EXEC,
            StyreneMessageType.REBOOT,
            StyreneMessageType.CONFIG_UPDATE,
            StyreneMessageType.SELF_UPDATE,
            StyreneMessageType.PROVISION,
            StyreneMessageType.PING,
            StyreneMessageType.INBOX_QUERY,
            StyreneMessageType.MESSAGES_QUERY,
        ]
        for msg_type in rpc_types:
            self._protocol.register_handler(msg_type, self._protocol_handler)

    def _register_default_handlers(self) -> None:
        """Register default handlers for RPC command types."""
        self._handlers[StyreneMessageType.STATUS_REQUEST] = self._handle_status_request
        self._handlers[StyreneMessageType.EXEC] = self._handle_exec
        self._handlers[StyreneMessageType.REBOOT] = self._handle_reboot
        self._handlers[StyreneMessageType.CONFIG_UPDATE] = self._handle_config_update
        self._handlers[StyreneMessageType.SELF_UPDATE] = self._handle_self_update
        self._handlers[StyreneMessageType.PROVISION] = self._handle_provision
        self._handlers[StyreneMessageType.PING] = self._handle_ping
        self._handlers[StyreneMessageType.INBOX_QUERY] = self._handle_inbox_query
        self._handlers[StyreneMessageType.MESSAGES_QUERY] = self._handle_messages_query

    async def _protocol_handler(self, message: LXMFMessage, envelope: StyreneEnvelope) -> None:
        """Handler called by StyreneProtocol for RPC messages.

        This async method bridges the StyreneProtocol dispatch to the
        internal RPC handlers.

        Args:
            message: Original LXMF message
            envelope: Decoded Styrene envelope
        """
        if not self._running:
            return

        source_hash = message.source_hash
        msg_type = envelope.message_type

        # Check if we have a handler for this message type
        handler = self._handlers.get(msg_type)
        if handler is None:
            logger.debug(f"No RPC handler for message type: {msg_type.name}")
            return

        # Security: capability check via RBAC policy
        required_cap = MESSAGE_TYPE_CAPABILITY.get(msg_type)
        if required_cap is None:
            logger.warning(
                f"[SECURITY] Rejected {msg_type.name} from {source_hash[:16]}... - "
                f"no capability mapping (fail-closed)"
            )
            if envelope.request_id and envelope.request_id != NO_CORRELATION:
                await self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.COMMAND_NOT_ALLOWED,
                    "Not authorized",
                )
            return

        if not self._rbac_policy.has_capability(source_hash, required_cap):
            logger.warning(
                f"[SECURITY] Rejected {msg_type.name} from {source_hash[:16]}... - "
                f"missing capability {required_cap}"
            )
            try:
                from styrened.web.metrics import security_events_total

                security_events_total.labels(type="auth_rejected").inc()
            except ImportError:
                pass
            if envelope.request_id and envelope.request_id != NO_CORRELATION:
                await self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.COMMAND_NOT_ALLOWED,
                    "Not authorized",
                )
            return

        # 3. Check rate limit
        rate_limit_result = self._check_rate_limit(source_hash)
        if rate_limit_result is not None:
            logger.warning(
                f"[SECURITY] Rate limited {msg_type.name} from {source_hash[:16]}... - "
                f"{rate_limit_result}"
            )
            try:
                from styrened.web.metrics import security_events_total

                security_events_total.labels(type="rate_limited").inc()
            except ImportError:
                pass
            if envelope.request_id and envelope.request_id != NO_CORRELATION:
                await self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.INVALID_REQUEST,
                    rate_limit_result,
                )
            return

        # 4. Check replay protection (skip for cheap idempotent commands)
        # PING/STATUS are capability-gated but low-risk for replay — skip to
        # avoid dict bloat.
        _skip_replay = msg_type in {StyreneMessageType.PING, StyreneMessageType.STATUS_REQUEST}
        if not _skip_replay and envelope.request_id:
            if self._is_replay(envelope.request_id):
                logger.warning(
                    f"[SECURITY] Rejected replay of {msg_type.name} from {source_hash[:16]}... - "
                    f"request_id already seen"
                )
                try:
                    from styrened.web.metrics import security_events_total

                    security_events_total.labels(type="replay_detected").inc()
                except ImportError:
                    pass
                # Don't send error response for replays (avoid amplification)
                return

        logger.info(f"Received RPC {msg_type.name} from {source_hash[:16]}...")

        try:
            from styrened.web.metrics import rpc_requests_total

            rpc_requests_total.labels(type=msg_type.name, result="dispatched").inc()
        except ImportError:
            pass

        # Dispatch to handler (handlers use asyncio.create_task internally)
        try:
            handler(source_hash, envelope)
            # Emit activity event for RPC commands.
            # Redact sensitive command names (EXEC, CONFIG_UPDATE, SELF_UPDATE)
            # to avoid leaking operational details to the activity feed.
            if self._daemon is not None and hasattr(self._daemon, "_emit_activity_event"):
                if msg_type in DANGEROUS_RPC_COMMANDS:
                    redacted_category = "rpc_privileged"
                else:
                    redacted_category = "rpc_query"
                self._daemon._emit_activity_event(
                    "rpc_received",
                    peer_hash=source_hash,
                    metadata={"category": redacted_category},
                )
        except Exception as e:
            logger.error(f"Error handling RPC request: {e}")
            # Send error response if we have a request_id
            if envelope.request_id and envelope.request_id != NO_CORRELATION:
                await self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.UNKNOWN,
                    "Internal server error",  # Sanitized message
                )

    def _check_rate_limit(self, source_hash: str) -> str | None:
        """Check rate limit for an identity.

        Args:
            source_hash: Source identity hash.

        Returns:
            None if allowed, error message string if rate limited.
        """
        current_time = time.time()
        cutoff = current_time - RATE_LIMIT_WINDOW_SECONDS

        # Clean up old timestamps
        if source_hash in self._request_timestamps:
            self._request_timestamps[source_hash] = [
                ts for ts in self._request_timestamps[source_hash] if ts > cutoff
            ]
            if not self._request_timestamps[source_hash]:
                del self._request_timestamps[source_hash]

        # Check limit
        timestamps = self._request_timestamps.get(source_hash, [])
        if len(timestamps) >= self._rate_limit:
            return f"Rate limit exceeded ({self._rate_limit} requests/minute)"

        # Record this request
        if source_hash not in self._request_timestamps:
            self._request_timestamps[source_hash] = []
        self._request_timestamps[source_hash].append(current_time)

        return None

    def _is_replay(self, request_id: bytes) -> bool:
        """Check if a request_id has been seen recently (replay detection).

        Also records the request_id if not a replay.

        Args:
            request_id: The request ID to check.

        Returns:
            True if this is a replay (request_id seen before), False otherwise.
        """
        current_time = time.time()
        cutoff = current_time - REQUEST_ID_EXPIRY_SECONDS

        # Clean up expired request_ids periodically (when dict gets large)
        if len(self._recent_request_ids) > MAX_RECENT_REQUEST_IDS:
            # Remove expired entries
            expired = [rid for rid, ts in self._recent_request_ids.items() if ts < cutoff]
            for rid in expired:
                del self._recent_request_ids[rid]

            # If still too large, remove oldest entries
            if len(self._recent_request_ids) > MAX_RECENT_REQUEST_IDS:
                sorted_items = sorted(self._recent_request_ids.items(), key=lambda x: x[1])
                # Remove oldest 10%
                to_remove = len(sorted_items) // 10
                for rid, _ in sorted_items[:to_remove]:
                    del self._recent_request_ids[rid]

        # Check if we've seen this request_id
        if request_id in self._recent_request_ids:
            # Check if it's expired
            if self._recent_request_ids[request_id] >= cutoff:
                return True  # Replay detected
            # Entry expired, will be replaced

        # Record this request_id
        self._recent_request_ids[request_id] = current_time
        return False

    def register_handler(
        self,
        message_type: StyreneMessageType,
        handler: Callable[[str, StyreneEnvelope], None],
    ) -> None:
        """Register a custom handler for a message type.

        Args:
            message_type: StyreneMessageType to handle.
            handler: Handler function taking (source_hash, envelope).
        """
        self._handlers[message_type] = handler
        logger.debug(f"Registered handler for {message_type.name}")

    def start(self) -> None:
        """Start the RPC server.

        Note: The StyreneProtocol dispatches messages to handlers.
        This method enables handling of those messages.
        """
        if self._running:
            logger.warning("RPC server already running")
            return

        self._running = True
        logger.info("RPC server started")

    def stop(self) -> None:
        """Stop the RPC server."""
        self._running = False
        logger.info("RPC server stopped")

    def _handle_ping(self, source_hash: str, envelope: StyreneEnvelope) -> None:
        """Handle PING - respond with PONG.

        Args:
            source_hash: Source identity hash.
            envelope: Decoded Styrene envelope.
        """
        logger.debug(f"PING from {source_hash[:16]}...")

        # Send PONG response
        asyncio.create_task(self._send_pong(source_hash, envelope.request_id))

    async def _send_pong(self, destination: str, request_id: bytes | None) -> None:
        """Send PONG response.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from PING.
        """
        from styrened.models.styrene_wire import create_pong

        pong_envelope = create_pong(request_id=request_id)
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=pong_envelope.message_type,
                payload=pong_envelope.payload,
                request_id=pong_envelope.request_id,
            )
        except Exception as e:
            logger.error(f"Failed to send PONG: {e}")

    def _handle_status_request(self, source_hash: str, envelope: StyreneEnvelope) -> None:
        """Handle STATUS_REQUEST - gather and return system status.

        Args:
            source_hash: Source identity hash.
            envelope: Decoded Styrene envelope.
        """
        logger.debug("Handling STATUS_REQUEST")

        # Gather status data
        status_data = self._gather_status()

        # Send response
        asyncio.create_task(
            self._send_status_response(source_hash, envelope.request_id, status_data)
        )

    async def _send_status_response(
        self,
        destination: str,
        request_id: bytes | None,
        status_data: dict[str, Any],
    ) -> None:
        """Send STATUS_RESPONSE.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from request.
            status_data: Status data dictionary.
        """
        response_envelope = create_status_response(status_data, request_id=request_id)
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=response_envelope.message_type,
                payload=response_envelope.payload,
                request_id=response_envelope.request_id,
            )
            logger.debug(f"Sent STATUS_RESPONSE to {destination[:16]}...")
        except Exception as e:
            logger.error(f"Failed to send STATUS_RESPONSE: {e}")

    def _handle_exec(self, source_hash: str, envelope: StyreneEnvelope) -> None:
        """Handle EXEC - execute command and return result.

        Args:
            source_hash: Source identity hash.
            envelope: Decoded Styrene envelope.
        """
        # Decode payload
        try:
            payload_data = decode_payload(envelope.payload) if envelope.payload else {}
        except Exception as e:
            logger.error(f"Failed to decode EXEC payload: {e}")
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.INVALID_REQUEST,
                    f"Invalid payload: {e}",
                )
            )
            return

        command = payload_data.get("command", "")
        args = payload_data.get("args", [])

        logger.info(f"Executing command: {command} {' '.join(args)}")

        # Execute command
        result = self._execute_command(command, args)

        # Send response
        asyncio.create_task(self._send_exec_result(source_hash, envelope.request_id, result))

    def _execute_command(self, command: str, args: list[str]) -> dict[str, Any]:
        """Execute a command and return result.

        Args:
            command: Command to execute.
            args: Command arguments.

        Returns:
            Dictionary with exit_code, stdout, stderr.
        """
        # Security check - command whitelist
        if command not in self.allowed_commands:
            logger.warning(f"Command not allowed: {command}")
            return {
                "exit_code": 126,
                "stdout": "",
                "stderr": f"Command not allowed: {command}",
            }

        try:
            # Build full command
            full_cmd = [command, *args]

            # Execute with timeout
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except subprocess.TimeoutExpired:
            return {
                "exit_code": 124,
                "stdout": "",
                "stderr": "Command timed out after 30 seconds",
            }
        except FileNotFoundError:
            return {
                "exit_code": 127,
                "stdout": "",
                "stderr": f"Command not found: {command}",
            }
        except Exception as e:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": str(e),
            }

    async def _send_exec_result(
        self,
        destination: str,
        request_id: bytes | None,
        result: dict[str, Any],
    ) -> None:
        """Send EXEC_RESULT response.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from request.
            result: Execution result dictionary.
        """
        response_envelope = create_exec_result(
            exit_code=result["exit_code"],
            stdout=result["stdout"],
            stderr=result["stderr"],
            request_id=request_id,
        )
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=response_envelope.message_type,
                payload=response_envelope.payload,
                request_id=response_envelope.request_id,
            )
            logger.debug(f"Sent EXEC_RESULT to {destination[:16]}...")
        except Exception as e:
            logger.error(f"Failed to send EXEC_RESULT: {e}")

    def _handle_reboot(self, source_hash: str, envelope: StyreneEnvelope) -> None:
        """Handle REBOOT - schedule system reboot.

        Args:
            source_hash: Source identity hash.
            envelope: Decoded Styrene envelope.
        """
        # Decode payload
        try:
            payload_data = decode_payload(envelope.payload) if envelope.payload else {}
        except Exception as e:
            logger.error(f"Failed to decode REBOOT payload: {e}")
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.INVALID_REQUEST,
                    f"Invalid payload: {e}",
                )
            )
            return

        delay = payload_data.get("delay", 0)
        logger.info(f"Reboot requested with delay: {delay}s")

        # Schedule reboot
        result = self._schedule_reboot(delay)

        # Send response
        asyncio.create_task(self._send_reboot_result(source_hash, envelope.request_id, result))

    def _schedule_reboot(self, delay: int) -> dict[str, Any]:
        """Schedule system reboot.

        Args:
            delay: Seconds to delay reboot (0 = immediate).

        Returns:
            Dictionary with success, message, scheduled_time.
        """
        try:
            if delay == 0:
                # Immediate reboot - schedule for 5 seconds to allow response
                asyncio.get_event_loop().call_later(5, self._do_reboot)
                return {
                    "success": True,
                    "message": "Rebooting in 5 seconds",
                    "scheduled_time": time.time() + 5,
                }
            else:
                # Delayed reboot
                asyncio.get_event_loop().call_later(delay, self._do_reboot)
                return {
                    "success": True,
                    "message": f"Reboot scheduled in {delay} seconds",
                    "scheduled_time": time.time() + delay,
                }

        except Exception as e:
            logger.error(f"Failed to schedule reboot: {e}")
            return {
                "success": False,
                "message": f"Failed to schedule reboot: {e}",
                "scheduled_time": None,
            }

    async def _send_reboot_result(
        self,
        destination: str,
        request_id: bytes | None,
        result: dict[str, Any],
    ) -> None:
        """Send REBOOT_RESULT response.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from request.
            result: Reboot result dictionary.
        """
        response_envelope = create_reboot_result(
            success=result["success"],
            message=result["message"],
            scheduled_time=result.get("scheduled_time"),
            request_id=request_id,
        )
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=response_envelope.message_type,
                payload=response_envelope.payload,
                request_id=response_envelope.request_id,
            )
            logger.debug(f"Sent REBOOT_RESULT to {destination[:16]}...")
        except Exception as e:
            logger.error(f"Failed to send REBOOT_RESULT: {e}")

    def _handle_config_update(self, source_hash: str, envelope: StyreneEnvelope) -> None:
        """Handle CONFIG_UPDATE - update local configuration.

        Args:
            source_hash: Source identity hash.
            envelope: Decoded Styrene envelope.
        """
        # Decode payload
        try:
            payload_data = decode_payload(envelope.payload) if envelope.payload else {}
        except Exception as e:
            logger.error(f"Failed to decode CONFIG_UPDATE payload: {e}")
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.INVALID_REQUEST,
                    f"Invalid payload: {e}",
                )
            )
            return

        updates = payload_data.get("updates", {})
        logger.info(f"Config update requested: {list(updates.keys())}")

        # Process config updates
        result = self._process_config_update(updates)

        # Send response
        asyncio.create_task(self._send_config_result(source_hash, envelope.request_id, result))

    def _process_config_update(self, updates: dict[str, Any]) -> dict[str, Any]:
        """Process configuration updates.

        Args:
            updates: Dictionary of config keys to update.

        Returns:
            Dictionary with success, message, updated_keys.
        """
        # For now, just acknowledge - actual config updates would need
        # integration with config service
        updated_keys = list(updates.keys())

        return {
            "success": True,
            "message": f"Updated {len(updated_keys)} config keys",
            "updated_keys": updated_keys,
        }

    async def _send_config_result(
        self,
        destination: str,
        request_id: bytes | None,
        result: dict[str, Any],
    ) -> None:
        """Send CONFIG_RESULT response.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from request.
            result: Config result dictionary.
        """
        response_envelope = create_config_result(
            success=result["success"],
            message=result["message"],
            updated_keys=result["updated_keys"],
            request_id=request_id,
        )
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=response_envelope.message_type,
                payload=response_envelope.payload,
                request_id=response_envelope.request_id,
            )
            logger.debug(f"Sent CONFIG_RESULT to {destination[:16]}...")
        except Exception as e:
            logger.error(f"Failed to send CONFIG_RESULT: {e}")

    def _handle_self_update(self, source_hash: str, envelope: StyreneEnvelope) -> None:
        """Handle SELF_UPDATE - upgrade styrened package and restart service.

        Args:
            source_hash: Source identity hash.
            envelope: Decoded Styrene envelope.
        """
        # Decode payload
        try:
            payload_data = decode_payload(envelope.payload) if envelope.payload else {}
        except Exception as e:
            logger.error(f"Failed to decode SELF_UPDATE payload: {e}")
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.INVALID_REQUEST,
                    f"Invalid payload: {e}",
                )
            )
            return

        version = payload_data.get("version")
        logger.info(f"Self-update requested (version: {version or 'latest'})")

        # Execute update
        result = self._do_self_update(version)

        # Send response
        asyncio.create_task(
            self._send_self_update_result(source_hash, envelope.request_id, result)
        )

        # On success, schedule service restart
        if result["success"]:
            logger.info("Self-update succeeded, scheduling service restart in 5s")
            asyncio.get_event_loop().call_later(5, self._restart_service)

    def _do_self_update(self, version: str | None) -> dict[str, Any]:
        """Execute pip install --upgrade for styrened.

        Args:
            version: Target version (None = latest from PyPI).

        Returns:
            Dictionary with success, message, old_version, new_version.
        """
        old_version = _styrened_version
        spec = f"styrened=={version}" if version else "styrened"

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", spec],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                # Try to detect new version from pip output
                new_version = version or "latest"
                # Parse pip output for installed version
                for line in result.stdout.splitlines():
                    if "Successfully installed" in line and "styrened-" in line:
                        for part in line.split():
                            if part.startswith("styrened-"):
                                new_version = part.split("-", 1)[1]
                                break

                return {
                    "success": True,
                    "message": f"Updated from {old_version} to {new_version}",
                    "old_version": old_version,
                    "new_version": new_version,
                }
            else:
                return {
                    "success": False,
                    "message": f"pip install failed: {result.stderr.strip()}",
                    "old_version": old_version,
                    "new_version": None,
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": "pip install timed out after 120 seconds",
                "old_version": old_version,
                "new_version": None,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Self-update failed: {e}",
                "old_version": old_version,
                "new_version": None,
            }

    async def _send_self_update_result(
        self,
        destination: str,
        request_id: bytes | None,
        result: dict[str, Any],
    ) -> None:
        """Send SELF_UPDATE_RESULT response.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from request.
            result: Self-update result dictionary.
        """
        response_envelope = create_self_update_result(
            success=result["success"],
            message=result["message"],
            old_version=result["old_version"],
            new_version=result.get("new_version"),
            request_id=request_id,
        )
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=response_envelope.message_type,
                payload=response_envelope.payload,
                request_id=response_envelope.request_id,
            )
            logger.debug(f"Sent SELF_UPDATE_RESULT to {destination[:16]}...")
        except Exception as e:
            logger.error(f"Failed to send SELF_UPDATE_RESULT: {e}")

    def _restart_service(self) -> None:
        """Restart the styrened service via systemctl."""
        logger.warning("Restarting styrened service after self-update")
        try:
            subprocess.Popen(["systemctl", "restart", "styrened"])
        except Exception as e:
            logger.error(f"Service restart failed: {e}")

    def _handle_provision(self, source_hash: str, envelope: StyreneEnvelope) -> None:
        """Handle PROVISION - remotely provision an adapter binary.

        Requires ADMIN role (adapter.provision capability, checked by RBAC layer).

        Args:
            source_hash: Source identity hash.
            envelope: Decoded Styrene envelope.
        """
        # Decode payload
        try:
            payload_data = decode_payload(envelope.payload) if envelope.payload else {}
        except Exception as e:
            logger.error(f"Failed to decode PROVISION payload: {e}")
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.INVALID_REQUEST,
                    f"Invalid payload: {e}",
                )
            )
            return

        adapter_name = payload_data.get("adapter", "")
        if not adapter_name:
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.INVALID_REQUEST,
                    "Missing required field: adapter",
                )
            )
            return

        if self._binary_provisioner is None:
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.COMMAND_FAILED,
                    "Binary provisioner not available",
                )
            )
            return

        logger.info(f"Provision requested for adapter: {adapter_name}")

        # Invoke provisioner
        result = self._binary_provisioner.provision(adapter_name)

        # Send response
        asyncio.create_task(
            self._send_provision_result(source_hash, envelope.request_id, result)
        )

    async def _send_provision_result(
        self,
        destination: str,
        request_id: bytes | None,
        result: dict[str, Any],
    ) -> None:
        """Send PROVISION_RESULT response.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from request.
            result: Provisioning result dictionary.
        """
        from styrened.models.styrene_wire import create_provision_result

        envelope = create_provision_result(result, request_id)
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=envelope.message_type,
                payload=envelope.payload,
                request_id=envelope.request_id,
            )
            logger.debug(f"Sent PROVISION_RESULT to {destination[:16]}...")
        except Exception as e:
            logger.error(f"Failed to send PROVISION_RESULT: {e}")

    async def _send_error(
        self,
        destination: str,
        request_id: bytes | None,
        error_code: int,
        message: str,
    ) -> None:
        """Send ERROR response.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from request.
            error_code: Error code.
            message: Error message.
        """
        error_envelope = create_error(
            error_code=error_code,
            message=message,
            request_id=request_id,
        )
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=error_envelope.message_type,
                payload=error_envelope.payload,
                request_id=error_envelope.request_id,
            )
            logger.debug(f"Sent ERROR to {destination[:16]}...")
        except Exception as e:
            logger.error(f"Failed to send ERROR: {e}")

    def _handle_inbox_query(self, source_hash: str, envelope: StyreneEnvelope) -> None:
        """Handle INBOX_QUERY - return conversation list from local inbox.

        Args:
            source_hash: Source identity hash.
            envelope: Decoded Styrene envelope.
        """
        logger.debug("Handling INBOX_QUERY")

        if not self._conversation_service:
            logger.warning("INBOX_QUERY received but conversation service not available")
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.COMMAND_FAILED,
                    "Conversation service not available",
                )
            )
            return

        try:
            payload_data = decode_payload(envelope.payload) if envelope.payload else {}
            limit = min(max(1, payload_data.get("limit", 50)), 500)

            conversations = self._conversation_service.list_conversations()
            conv_list = [c.to_dict() for c in conversations[:limit]]

            asyncio.create_task(
                self._send_inbox_response(source_hash, envelope.request_id, conv_list)
            )
        except Exception as e:
            logger.error(f"Error handling INBOX_QUERY: {e}")
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.COMMAND_FAILED,
                    "Failed to query inbox",
                )
            )

    async def _send_inbox_response(
        self,
        destination: str,
        request_id: bytes | None,
        conversations: list[dict[str, Any]],
    ) -> None:
        """Send INBOX_RESPONSE.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from request.
            conversations: List of conversation dicts.
        """
        response_envelope = create_inbox_response(conversations, request_id=request_id)
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=response_envelope.message_type,
                payload=response_envelope.payload,
                request_id=response_envelope.request_id,
            )
            logger.debug(f"Sent INBOX_RESPONSE to {destination[:16]}...")
        except Exception as e:
            logger.error(f"Failed to send INBOX_RESPONSE: {e}")

    def _handle_messages_query(self, source_hash: str, envelope: StyreneEnvelope) -> None:
        """Handle MESSAGES_QUERY - return messages for a specific peer.

        Args:
            source_hash: Source identity hash.
            envelope: Decoded Styrene envelope.
        """
        logger.debug("Handling MESSAGES_QUERY")

        if not self._conversation_service:
            logger.warning("MESSAGES_QUERY received but conversation service not available")
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.COMMAND_FAILED,
                    "Conversation service not available",
                )
            )
            return

        try:
            payload_data = decode_payload(envelope.payload) if envelope.payload else {}
            peer_hash = payload_data.get("peer_hash", "")
            limit = min(max(1, payload_data.get("limit", 50)), 500)

            if not peer_hash:
                asyncio.create_task(
                    self._send_error(
                        source_hash,
                        envelope.request_id,
                        RPCErrorCode.INVALID_REQUEST,
                        "peer_hash is required",
                    )
                )
                return

            messages = self._conversation_service.get_messages(
                peer_hash=peer_hash, limit=limit
            )
            msg_list = [m.to_dict() for m in messages]

            asyncio.create_task(
                self._send_messages_response(source_hash, envelope.request_id, msg_list)
            )
        except Exception as e:
            logger.error(f"Error handling MESSAGES_QUERY: {e}")
            asyncio.create_task(
                self._send_error(
                    source_hash,
                    envelope.request_id,
                    RPCErrorCode.COMMAND_FAILED,
                    "Failed to query messages",
                )
            )

    async def _send_messages_response(
        self,
        destination: str,
        request_id: bytes | None,
        messages: list[dict[str, Any]],
    ) -> None:
        """Send MESSAGES_RESPONSE.

        Args:
            destination: Destination identity hash.
            request_id: Correlation ID from request.
            messages: List of message dicts.
        """
        response_envelope = create_messages_response(messages, request_id=request_id)
        try:
            await self._protocol.send_typed_message(
                destination=destination,
                message_type=response_envelope.message_type,
                payload=response_envelope.payload,
                request_id=response_envelope.request_id,
            )
            logger.debug(f"Sent MESSAGES_RESPONSE to {destination[:16]}...")
        except Exception as e:
            logger.error(f"Failed to send MESSAGES_RESPONSE: {e}")

    # System information helpers

    def _get_available_commands(self) -> list[str]:
        """Filter allowed_commands to only those installed on this system.

        Uses shutil.which() to check each command in the whitelist.

        Returns:
            Sorted list of commands that are actually available.
        """
        return sorted(cmd for cmd in self.allowed_commands if shutil.which(cmd))

    def _gather_status(self) -> dict[str, Any]:
        """Gather system status information.

        Returns:
            Dictionary with uptime, ip, services, disk info, system identity,
            and available commands.

        Note: This response contains identifiable fields (ip, hostname).
        Over DirectLink /status it is RBAC-gated to MONITOR+ (Phase 2).
        Over RPC STATUS_REQUEST it is served to anyone with rpc.status
        capability (PEER+ by default). For anonymous node metadata, use
        _gather_meta() instead.
        """
        os_info = get_os_info()
        disk_used, disk_total = self._get_disk_usage()
        return {
            "uptime": self._get_uptime(),
            "ip": self._get_ip_address(),
            "services": self._get_services(),
            "disk_used": disk_used,
            "disk_total": disk_total,
            "styrened_version": _styrened_version,
            "hostname": socket.gethostname(),
            "arch": os_info["arch"],
            "os_id": os_info["os_id"],
            "os_version": os_info["os_version"],
            "nixos_generation": os_info["nixos_generation"],
            "available_commands": self._get_available_commands(),
        }

    def _gather_meta(self, config: Any = None) -> dict[str, Any]:
        """Gather non-identifiable node metadata for /meta requests.

        Returns only information that cannot identify the operator or node:
        - styrene_version: what software is running
        - profile: node role (node/hub/workstation/edge-router)
        - capabilities: feature flags (rpc, lxmf, datalink, yggdrasil, i2p, etc.)
        - arch: CPU architecture (aarch64, x86_64, etc.)
        - os_id: OS family (nixos, debian, darwin)
        - ygg_address: Yggdrasil IPv6 address (only when adapter is running)
        - ygg_port: Yggdrasil TCP listen port (only when adapter is running)
        - b32_address: I2P base32 address (only when adapter knows it)

        Deliberately excluded: hostname, IP address, uptime, disk usage,
        nixos_generation, operator identity, peer list.

        ygg_address, ygg_port, and b32_address are omitted entirely (not set
        to None) when the respective overlay is not available — callers must
        check key presence.
        """
        os_info = get_os_info()
        caps: list[str] = ["lxmf"]
        if config and getattr(config.rpc, "enabled", False):
            caps.append("rpc")
        if config and getattr(config.api, "enabled", False):
            caps.append("api")
        caps.append("datalink")  # always present when daemon is up

        # Yggdrasil capability — only advertised when the adapter is running
        ygg_address: str | None = None
        ygg_port: int | None = None
        if self._ygg_adapter is not None:
            try:
                addr = self._ygg_adapter.get_local_address()
                if addr:
                    ygg_address = addr
                    caps.append("yggdrasil")
                    # Port comes from the adapter's config
                    ygg_port = getattr(
                        getattr(self._ygg_adapter, "_config", None),
                        "listen_port",
                        None,
                    )
            except Exception:
                pass

        # I2P capability — only advertised when a local b32 address is known
        b32_address: str | None = None
        if self._i2p_adapter is not None:
            try:
                if hasattr(self._i2p_adapter, "get_b32_address"):
                    candidate = self._i2p_adapter.get_b32_address()
                else:
                    status = self._i2p_adapter.status()
                    details = getattr(status, "details", {}) or {}
                    candidate = details.get("b32_address")
                if candidate:
                    b32_address = candidate
                    caps.append("i2p")
            except Exception:
                pass

        profile = "node"
        if config:
            try:
                profile = config.profile.value
            except Exception:
                pass

        meta: dict[str, Any] = {
            "styrene_version": _styrened_version,
            "profile": profile,
            "capabilities": caps,
            "arch": os_info.get("arch", ""),
            "os_id": os_info.get("os_id", ""),
        }

        # Only include overlay-specific keys when available.
        if ygg_address is not None:
            meta["ygg_address"] = ygg_address
        if ygg_port is not None:
            meta["ygg_port"] = ygg_port
        if b32_address is not None:
            meta["b32_address"] = b32_address

        return meta

    def _gather_info(self, config: Any = None) -> dict[str, Any]:
        """Gather identifiable node metadata for /info requests.

        Returns operator-chosen display metadata:
        - name: display name set by operator in config
        - operator_label: optional short label set by operator

        Only served when discovery.info_respond = True in config.
        """
        name = ""
        operator_label = ""
        if config is not None:
            try:
                # Only include display_name if the operator has explicitly
                # configured it — the default "Anonymous Styrene" is a
                # placeholder and must not be broadcast as a node identifier.
                from styrened.models.config import IdentityConfig
                dn = config.identity.display_name or ""
                default_dn = IdentityConfig.__dataclass_fields__["display_name"].default
                if dn and dn != default_dn:
                    name = dn
            except Exception:
                pass
            try:
                operator_label = config.discovery.operator_label or ""
            except Exception:
                pass
        return {
            "name": name,
            "operator_label": operator_label,
        }

    def _get_uptime(self) -> int:
        """Get system uptime in seconds.

        Returns:
            Uptime in seconds.
        """
        try:
            if platform.system() == "Linux":
                with open("/proc/uptime") as f:
                    return int(float(f.read().split()[0]))
            elif platform.system() == "Darwin":
                # macOS - use sysctl
                result = subprocess.run(
                    ["sysctl", "-n", "kern.boottime"],
                    capture_output=True,
                    text=True,
                )
                # Parse: { sec = 1234567890, usec = 123456 }
                import re

                match = re.search(r"sec = (\d+)", result.stdout)
                if match:
                    boot_time = int(match.group(1))
                    return int(time.time() - boot_time)
            return 0
        except Exception as e:
            logger.warning(f"Failed to get uptime: {e}")
            return 0

    def _get_ip_address(self) -> str:
        """Get primary IP address.

        Returns:
            IP address string.
        """
        try:
            # Connect to external address to find default interface IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip: str = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _get_services(self) -> list[str]:
        """Get list of running services.

        Returns:
            List of service names.
        """
        services = []
        try:
            if platform.system() == "Linux":
                # Check for common services via systemctl
                common_services = [
                    "reticulum",
                    "lxmd",
                    "styrene",
                    "sshd",
                    "docker",
                ]
                for svc in common_services:
                    result = subprocess.run(
                        ["systemctl", "is-active", svc],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode == 0:
                        services.append(svc)
        except Exception as e:
            logger.debug(f"Failed to get services: {e}")

        return services

    def _get_disk_usage(self) -> tuple[int, int]:
        """Get disk usage for root filesystem.

        Returns:
            Tuple of (used_bytes, total_bytes).
        """
        try:
            statvfs = os.statvfs("/")
            total = statvfs.f_blocks * statvfs.f_frsize
            free = statvfs.f_bfree * statvfs.f_frsize
            used = total - free
            return (used, total)
        except Exception as e:
            logger.warning(f"Failed to get disk usage: {e}")
            return (0, 0)

    def _do_reboot(self) -> None:
        """Execute system reboot."""
        logger.warning("Executing system reboot!")
        try:
            if platform.system() == "Linux":
                subprocess.run(["systemctl", "reboot"], check=True)
            elif platform.system() == "Darwin":
                subprocess.run(["sudo", "reboot"], check=True)
        except Exception as e:
            logger.error(f"Reboot failed: {e}")


# Singleton instance
_rpc_server: RPCServer | None = None


def get_rpc_server(styrene_protocol: "StyreneProtocol | None" = None) -> RPCServer:
    """Get the singleton RPCServer instance.

    Args:
        styrene_protocol: StyreneProtocol instance (required on first call).

    Returns:
        The singleton RPCServer instance.

    Raises:
        ValueError: If called without styrene_protocol before initialization.
    """
    global _rpc_server

    if _rpc_server is None:
        if styrene_protocol is None:
            raise ValueError("styrene_protocol required for first initialization")
        _rpc_server = RPCServer(styrene_protocol)

    return _rpc_server
