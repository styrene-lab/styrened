"""Mock RPC client for testing TUI integration.

This mock provides the same interface as the real RPCClient (from Child 1)
but with simulated responses for testing purposes.
"""
from __future__ import annotations

import asyncio

from styrened.tui.models.rpc import ExecResult, RPCTimeoutError, StatusResponse


class MockRPCClient:
    """Mock RPC client for testing without Child 1 dependencies.

    Provides canned responses for status and exec calls.
    Can be configured to simulate timeouts and errors.
    """

    def __init__(self, simulate_delay: bool = True) -> None:
        """Initialize mock RPC client.

        Args:
            simulate_delay: If True, add realistic network delays.
        """
        self.simulate_delay = simulate_delay
        self.call_status_count = 0
        self.call_exec_count = 0

        # Configuration for testing error cases
        self.should_timeout = False
        self.timeout_after_calls = -1  # Timeout after N calls (-1 = never)

    async def call_status(
        self,
        destination: str,
        timeout: float = 30.0,
    ) -> StatusResponse:
        """Return mock status response.

        Args:
            destination: Device identity (ignored in mock).
            timeout: Timeout duration (ignored in mock).

        Returns:
            Mock StatusResponse.

        Raises:
            RPCTimeoutError: If configured to simulate timeout.
        """
        self.call_status_count += 1

        # Simulate timeout if configured
        if self.should_timeout or (
            self.timeout_after_calls > 0 and self.call_status_count > self.timeout_after_calls
        ):
            if self.simulate_delay:
                await asyncio.sleep(0.1)
            raise RPCTimeoutError(
                f"Mock timeout for device {destination[:8]}...",
                request_id="mock-timeout",
                destination=destination,
                timeout=10.0
            )

        # Simulate network delay
        if self.simulate_delay:
            await asyncio.sleep(0.1)

        # Return mock status based on device identity
        return self._generate_mock_status(destination)

    async def call_exec(
        self,
        destination: str,
        command: str,
        args: list[str],
        timeout: float = 60.0,
    ) -> ExecResult:
        """Return mock exec result.

        Args:
            destination: Device identity (ignored in mock).
            command: Command to execute.
            args: Command arguments.
            timeout: Timeout duration (ignored in mock).

        Returns:
            Mock ExecResult.

        Raises:
            RPCTimeoutError: If configured to simulate timeout.
        """
        self.call_exec_count += 1

        # Simulate timeout if configured
        if self.should_timeout:
            if self.simulate_delay:
                await asyncio.sleep(0.2)
            raise RPCTimeoutError(
                f"Mock timeout for device {destination[:8]}...",
                request_id="mock-timeout",
                destination=destination,
                timeout=10.0
            )

        # Simulate network delay
        if self.simulate_delay:
            await asyncio.sleep(0.2)

        # Return mock result based on command
        return self._generate_mock_exec_result(command, args)

    def _generate_mock_status(self, destination: str) -> StatusResponse:
        """Generate mock status response for device.

        Args:
            destination: Device identity hash.

        Returns:
            Mock StatusResponse with realistic data.
        """
        # Different mock data based on device identity
        if "a3f5" in destination:
            # Device 1: rpi-01
            return StatusResponse(
                uptime=293856,  # ~3.4 days
                ip="192.168.0.101",
                services=["reticulum", "nomadnet", "ssh", "avahi-daemon"],
                disk_used=4_200_000_000,  # 4.2 GB
                disk_total=28_000_000_000,  # 28 GB
            )
        elif "b4c6" in destination:
            # Device 2: t100ta-01
            return StatusResponse(
                uptime=86400,  # 1 day
                ip="192.168.0.102",
                services=["reticulum", "ssh"],
                disk_used=12_000_000_000,  # 12 GB
                disk_total=120_000_000_000,  # 120 GB
            )
        else:
            # Default mock device
            return StatusResponse(
                uptime=123456,  # ~1.4 days
                ip="192.168.0.100",
                services=["reticulum", "nomadnet"],
                disk_used=5_000_000_000,  # 5 GB
                disk_total=32_000_000_000,  # 32 GB
            )

    def _generate_mock_exec_result(self, command: str, args: list[str]) -> ExecResult:
        """Generate mock exec result for command.

        Args:
            command: Command name.
            args: Command arguments.

        Returns:
            Mock ExecResult.
        """
        # systemctl status reticulum
        if command == "systemctl" and "status" in args and "reticulum" in args:
            return ExecResult(
                exit_code=0,
                stdout=(
                    "● reticulum.service - Reticulum Network Stack\n"
                    "     Loaded: loaded (/etc/systemd/system/reticulum.service; enabled)\n"
                    "     Active: active (running) since Mon 2024-01-15 10:23:45 UTC; 3 days ago\n"
                    "   Main PID: 1234 (rnsd)\n"
                    "      Tasks: 5 (limit: 4915)\n"
                    "     Memory: 45.2M\n"
                    "     CGroup: /system.slice/reticulum.service\n"
                    "             └─1234 /usr/bin/python3 /usr/local/bin/rnsd\n"
                ),
                stderr="",
            )

        # systemctl status nomadnet
        elif command == "systemctl" and "status" in args and "nomadnet" in args:
            return ExecResult(
                exit_code=0,
                stdout=(
                    "● nomadnet.service - Nomad Network\n"
                    "     Loaded: loaded (/etc/systemd/system/nomadnet.service; enabled)\n"
                    "     Active: active (running) since Mon 2024-01-15 10:24:12 UTC; 3 days ago\n"
                    "   Main PID: 1245 (nomadnet)\n"
                ),
                stderr="",
            )

        # uptime
        elif command == "uptime":
            return ExecResult(
                exit_code=0,
                stdout=" 14:23:45 up 3 days, 14:00,  1 user,  load average: 0.23, 0.18, 0.15",
                stderr="",
            )

        # df -h
        elif command == "df" and "-h" in args:
            return ExecResult(
                exit_code=0,
                stdout=(
                    "Filesystem      Size  Used Avail Use% Mounted on\n"
                    "/dev/mmcblk0p2   28G  4.2G   23G  16% /\n"
                    "/dev/mmcblk0p1  128M   32M   96M  25% /boot\n"
                ),
                stderr="",
            )

        # ls
        elif command == "ls":
            args[0] if args else "."
            return ExecResult(
                exit_code=0,
                stdout="README.md\nconfig.yaml\nlogs\nscripts\n",
                stderr="",
            )

        # Command not found
        elif command in ["invalidcmd", "notfound"]:
            return ExecResult(
                exit_code=127,
                stdout="",
                stderr=f"bash: {command}: command not found\n",
            )

        # Generic fallback
        else:
            return ExecResult(
                exit_code=0,
                stdout=f"Mock output for: {command} {' '.join(args)}\n",
                stderr="",
            )

    def reset_counters(self) -> None:
        """Reset call counters for testing."""
        self.call_status_count = 0
        self.call_exec_count = 0

    def configure_timeout(self, should_timeout: bool = True, after_calls: int = -1) -> None:
        """Configure timeout simulation.

        Args:
            should_timeout: If True, all calls will timeout.
            after_calls: If > 0, timeout after this many calls.
        """
        self.should_timeout = should_timeout
        self.timeout_after_calls = after_calls
