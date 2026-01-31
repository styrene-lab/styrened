"""RPC server for handling incoming requests.

This module implements the server-side RPC handler that processes incoming
RPC requests and sends responses. It complements the RPCClient which sends
requests.

The RPC server handles:
- status_request: Returns system status (uptime, IP, disk, services)
- exec: Executes commands and returns output
- reboot: Schedules system reboot
- update_config: Updates local configuration

Usage:
    from styrened.rpc import RPCServer
    from styrened.services.lxmf_service import get_lxmf_service

    # Initialize server
    server = RPCServer(get_lxmf_service())

    # Server automatically handles incoming RPC messages via LXMF callback
"""

import asyncio
import logging
import os
import platform
import socket
import subprocess
import time
from typing import Any

from styrened.rpc.messages import (
    ExecCommand,
    ExecResult,
    RebootCommand,
    RebootResult,
    StatusRequest,
    StatusResponse,
    UpdateConfigCommand,
    UpdateConfigResult,
    deserialize_message,
)
from styrened.services.lxmf_service import LXMFService

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


class RPCServer:
    """RPC server for handling incoming requests.

    Listens for incoming RPC messages via LXMF and dispatches them to
    appropriate handlers. Responses are sent back to the requesting node.

    Attributes:
        lxmf_service: LXMF transport service for sending responses.
        allowed_commands: Set of commands allowed for exec (security).
        _running: Whether the server is running.
    """

    def __init__(
        self,
        lxmf_service: LXMFService,
        allowed_commands: set[str] | None = None,
    ) -> None:
        """Initialize RPC server.

        Args:
            lxmf_service: LXMF transport service.
            allowed_commands: Set of allowed commands for exec.
                            Defaults to DEFAULT_ALLOWED_COMMANDS.
        """
        self.lxmf_service = lxmf_service
        self.allowed_commands = allowed_commands or set(DEFAULT_ALLOWED_COMMANDS)
        self._running = False
        self._original_callback: Any = None

        logger.debug("RPCServer initialized")

    def start(self) -> None:
        """Start the RPC server.

        Registers the message handler with LXMF service.
        """
        if self._running:
            logger.warning("RPC server already running")
            return

        # Register our handler with LXMF
        self.lxmf_service.register_callback(self._handle_incoming_message)
        self._running = True
        logger.info("RPC server started")

    def stop(self) -> None:
        """Stop the RPC server."""
        self._running = False
        logger.info("RPC server stopped")

    def _handle_incoming_message(self, source_hash: str, payload: dict[str, Any]) -> None:
        """Handle incoming LXMF message.

        Checks if this is an RPC request and dispatches to appropriate handler.

        Args:
            source_hash: Source destination hash.
            payload: Message payload.
        """
        if not self._running:
            return

        # Check if this is an RPC message
        if payload.get("protocol") != "rpc":
            logger.debug(f"Ignoring non-RPC message from {source_hash}")
            return

        # Extract request_id for response correlation
        request_id = payload.get("request_id")
        if not request_id:
            logger.warning(f"RPC message from {source_hash} missing request_id")
            return

        msg_type = payload.get("type")
        logger.info(f"Received RPC {msg_type} from {source_hash[:16]}...")

        # Dispatch to handler
        try:
            message = deserialize_message(payload)
            response = self._dispatch_request(message)

            # Send response
            self._send_response(source_hash, request_id, response)

        except Exception as e:
            logger.error(f"Error handling RPC request: {e}")
            # Send error response
            self._send_error_response(source_hash, request_id, str(e))

    def _dispatch_request(
        self,
        message: StatusRequest | ExecCommand | RebootCommand | UpdateConfigCommand,
    ) -> StatusResponse | ExecResult | RebootResult | UpdateConfigResult:
        """Dispatch request to appropriate handler.

        Args:
            message: Deserialized RPC request message.

        Returns:
            Response message.

        Raises:
            ValueError: If message type is not a request type.
        """
        if isinstance(message, StatusRequest):
            return self._handle_status_request()
        elif isinstance(message, ExecCommand):
            return self._handle_exec_command(message)
        elif isinstance(message, RebootCommand):
            return self._handle_reboot_command(message)
        elif isinstance(message, UpdateConfigCommand):
            return self._handle_update_config_command(message)
        else:
            raise ValueError(f"Unknown request type: {type(message)}")

    def _handle_status_request(self) -> StatusResponse:
        """Handle status request - gather system information.

        Returns:
            StatusResponse with system status.
        """
        logger.debug("Handling status_request")

        # Get uptime
        uptime = self._get_uptime()

        # Get IP address
        ip = self._get_ip_address()

        # Get running services (simplified)
        services = self._get_services()

        # Get disk usage
        disk_used, disk_total = self._get_disk_usage()

        return StatusResponse(
            uptime=uptime,
            ip=ip,
            services=services,
            disk_used=disk_used,
            disk_total=disk_total,
        )

    def _handle_exec_command(self, cmd: ExecCommand) -> ExecResult:
        """Handle exec command - run command and return output.

        Args:
            cmd: ExecCommand with command and args.

        Returns:
            ExecResult with output and exit code.
        """
        logger.info(f"Executing command: {cmd.command} {' '.join(cmd.args)}")

        # Security check - command whitelist
        if cmd.command not in self.allowed_commands:
            logger.warning(f"Command not allowed: {cmd.command}")
            return ExecResult(
                exit_code=126,
                stdout="",
                stderr=f"Command not allowed: {cmd.command}",
            )

        try:
            # Build full command
            full_cmd = [cmd.command, *cmd.args]

            # Execute with timeout
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            return ExecResult(
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        except subprocess.TimeoutExpired:
            return ExecResult(
                exit_code=124,
                stdout="",
                stderr="Command timed out after 30 seconds",
            )
        except FileNotFoundError:
            return ExecResult(
                exit_code=127,
                stdout="",
                stderr=f"Command not found: {cmd.command}",
            )
        except Exception as e:
            return ExecResult(
                exit_code=1,
                stdout="",
                stderr=str(e),
            )

    def _handle_reboot_command(self, cmd: RebootCommand) -> RebootResult:
        """Handle reboot command - schedule system reboot.

        Args:
            cmd: RebootCommand with optional delay.

        Returns:
            RebootResult with scheduled time.
        """
        logger.info(f"Reboot requested with delay: {cmd.delay}s")

        try:
            scheduled_time = time.time() + cmd.delay

            if cmd.delay == 0:
                # Immediate reboot - schedule for 5 seconds to allow response
                asyncio.get_event_loop().call_later(5, self._do_reboot)
                return RebootResult(
                    success=True,
                    message="Rebooting in 5 seconds",
                    scheduled_time=time.time() + 5,
                )
            else:
                # Delayed reboot
                asyncio.get_event_loop().call_later(cmd.delay, self._do_reboot)
                return RebootResult(
                    success=True,
                    message=f"Reboot scheduled in {cmd.delay} seconds",
                    scheduled_time=scheduled_time,
                )

        except Exception as e:
            logger.error(f"Failed to schedule reboot: {e}")
            return RebootResult(
                success=False,
                message=f"Failed to schedule reboot: {e}",
            )

    def _handle_update_config_command(self, cmd: UpdateConfigCommand) -> UpdateConfigResult:
        """Handle update_config command - update local configuration.

        Args:
            cmd: UpdateConfigCommand with config updates.

        Returns:
            UpdateConfigResult with updated keys.
        """
        logger.info(f"Config update requested: {list(cmd.config_updates.keys())}")

        # For now, just acknowledge - actual config updates would need
        # integration with config service
        updated_keys = list(cmd.config_updates.keys())

        return UpdateConfigResult(
            success=True,
            message=f"Updated {len(updated_keys)} config keys",
            updated_keys=updated_keys,
        )

    def _send_response(
        self,
        destination: str,
        request_id: str,
        response: StatusResponse | ExecResult | RebootResult | UpdateConfigResult,
    ) -> None:
        """Send RPC response to requester.

        Args:
            destination: Destination hash to send response to.
            request_id: Request ID for correlation.
            response: Response message.
        """
        payload = response.to_dict()
        payload["request_id"] = request_id
        payload["protocol"] = "rpc"

        logger.debug(f"Sending {response.type} response to {destination[:16]}...")

        if not self.lxmf_service.send_message(destination, payload):
            logger.error(f"Failed to send response to {destination}")

    def _send_error_response(
        self,
        destination: str,
        request_id: str,
        error: str,
    ) -> None:
        """Send error response to requester.

        Args:
            destination: Destination hash.
            request_id: Request ID for correlation.
            error: Error message.
        """
        payload = {
            "type": "error",
            "request_id": request_id,
            "protocol": "rpc",
            "error": error,
        }

        logger.debug(f"Sending error response to {destination[:16]}...")
        self.lxmf_service.send_message(destination, payload)

    # System information helpers

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
            ip = s.getsockname()[0]
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


def get_rpc_server(lxmf_service: LXMFService | None = None) -> RPCServer:
    """Get the singleton RPCServer instance.

    Args:
        lxmf_service: LXMF service (required on first call).

    Returns:
        The singleton RPCServer instance.

    Raises:
        ValueError: If called without lxmf_service before initialization.
    """
    global _rpc_server

    if _rpc_server is None:
        if lxmf_service is None:
            raise ValueError("lxmf_service required for first initialization")
        _rpc_server = RPCServer(lxmf_service)

    return _rpc_server
