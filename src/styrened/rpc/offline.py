"""Offline RPC client for when LXMF is unavailable.

Provides the same interface as RPCClient but returns canned offline
responses. Used by the TUI when the daemon is not connected to the
mesh network.
"""
from __future__ import annotations


import asyncio

from styrened.rpc.errors import RPCTimeoutError
from styrened.rpc.messages import ExecResult, RebootResult, StatusResponse


class OfflineRPCClient:
    """RPC client stub for offline/disconnected mode.

    Returns canned responses so TUI screens can render without a live
    mesh connection.  Can be configured to simulate timeouts for testing.
    """

    def __init__(self, simulate_delay: bool = False) -> None:
        self.simulate_delay = simulate_delay
        self.call_status_count = 0
        self.call_exec_count = 0
        self.should_timeout = False
        self.timeout_after_calls = -1

    async def call_status(
        self,
        destination: str,
        timeout: float = 30.0,
    ) -> StatusResponse:
        """Return offline status response."""
        self.call_status_count += 1

        if self.should_timeout or (
            self.timeout_after_calls > 0
            and self.call_status_count > self.timeout_after_calls
        ):
            if self.simulate_delay:
                await asyncio.sleep(0.1)
            raise RPCTimeoutError(
                f"Offline — no mesh connection to {destination[:8]}...",
                request_id="offline",
                destination=destination,
                timeout=timeout,
            )

        if self.simulate_delay:
            await asyncio.sleep(0.1)

        return StatusResponse(
            uptime=0,
            ip="offline",
            services=[],
            disk_used=0,
            disk_total=0,
            available_commands=[],
        )

    async def call_exec(
        self,
        destination: str,
        command: str,
        args: list[str],
        timeout: float = 60.0,
    ) -> ExecResult:
        """Return offline exec result."""
        self.call_exec_count += 1

        if self.should_timeout:
            if self.simulate_delay:
                await asyncio.sleep(0.1)
            raise RPCTimeoutError(
                f"Offline — no mesh connection to {destination[:8]}...",
                request_id="offline",
                destination=destination,
                timeout=timeout,
            )

        if self.simulate_delay:
            await asyncio.sleep(0.1)

        return ExecResult(
            exit_code=1,
            stdout="",
            stderr="offline — no mesh connection",
        )

    async def call_reboot(
        self,
        destination: str,
        delay: int = 0,
        timeout: float = 10.0,
    ) -> RebootResult:
        """Raise timeout — reboot not available offline."""
        raise RPCTimeoutError(
            f"Offline — no mesh connection to {destination[:8]}...",
            request_id="offline",
            destination=destination,
            timeout=timeout,
        )
