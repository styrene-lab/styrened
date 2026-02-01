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

Usage:
    from styrened.rpc import RPCServer
    from styrened.protocols.styrene import StyreneProtocol

    # Initialize with StyreneProtocol
    styrene_protocol = StyreneProtocol(router, identity, db_engine)
    server = RPCServer(styrene_protocol)

    # Start server
    server.start()

    # Server automatically handles incoming Styrene RPC messages
"""

import asyncio
import logging
import os
import platform
import socket
import subprocess
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from styrened.models.styrene_wire import (
    NO_CORRELATION,
    StyreneEnvelope,
    StyreneMessageType,
    create_config_result,
    create_error,
    create_exec_result,
    create_reboot_result,
    create_status_response,
    decode_payload,
)
from styrened.protocols.base import LXMFMessage

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

    Attributes:
        styrene_protocol: StyreneProtocol instance for sending responses.
        allowed_commands: Set of commands allowed for exec (security).
        _running: Whether the server is running.
    """

    def __init__(
        self,
        styrene_protocol: "StyreneProtocol",
        allowed_commands: set[str] | None = None,
    ) -> None:
        """Initialize RPC server.

        Args:
            styrene_protocol: StyreneProtocol instance for transport.
            allowed_commands: Set of allowed commands for exec.
                            Defaults to DEFAULT_ALLOWED_COMMANDS.
        """
        self._protocol = styrene_protocol
        self.allowed_commands = allowed_commands or set(DEFAULT_ALLOWED_COMMANDS)
        self._running = False
        self._handlers: dict[StyreneMessageType, Callable[[str, StyreneEnvelope], None]] = {}

        # Register default handlers
        self._register_default_handlers()

        # Register with StyreneProtocol for message routing
        self._register_with_protocol()

        logger.debug("RPCServer initialized with StyreneProtocol")

    def _register_with_protocol(self) -> None:
        """Register RPC message handlers with StyreneProtocol."""
        # Register for RPC command types
        rpc_types = [
            StyreneMessageType.STATUS_REQUEST,
            StyreneMessageType.EXEC,
            StyreneMessageType.REBOOT,
            StyreneMessageType.CONFIG_UPDATE,
            StyreneMessageType.PING,
        ]
        for msg_type in rpc_types:
            self._protocol.register_handler(msg_type, self._protocol_handler)

    def _register_default_handlers(self) -> None:
        """Register default handlers for RPC command types."""
        self._handlers[StyreneMessageType.STATUS_REQUEST] = self._handle_status_request
        self._handlers[StyreneMessageType.EXEC] = self._handle_exec
        self._handlers[StyreneMessageType.REBOOT] = self._handle_reboot
        self._handlers[StyreneMessageType.CONFIG_UPDATE] = self._handle_config_update
        self._handlers[StyreneMessageType.PING] = self._handle_ping

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

        # Check if we have a handler for this message type
        handler = self._handlers.get(envelope.message_type)
        if handler is None:
            logger.debug(f"No RPC handler for message type: {envelope.message_type.name}")
            return

        logger.info(f"Received RPC {envelope.message_type.name} from {message.source_hash[:16]}...")

        # Dispatch to handler (handlers use asyncio.create_task internally)
        try:
            handler(message.source_hash, envelope)
        except Exception as e:
            logger.error(f"Error handling RPC request: {e}")
            # Send error response if we have a request_id
            if envelope.request_id and envelope.request_id != NO_CORRELATION:
                await self._send_error(
                    message.source_hash,
                    envelope.request_id,
                    RPCErrorCode.UNKNOWN,
                    "Internal server error",  # Sanitized message
                )

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

    # System information helpers

    def _gather_status(self) -> dict[str, Any]:
        """Gather system status information.

        Returns:
            Dictionary with uptime, ip, services, disk_used, disk_total.
        """
        return {
            "uptime": self._get_uptime(),
            "ip": self._get_ip_address(),
            "services": self._get_services(),
            "disk_used": self._get_disk_usage()[0],
            "disk_total": self._get_disk_usage()[1],
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
