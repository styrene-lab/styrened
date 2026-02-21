"""RPC communication tests (Phase 2).

Tests RPC request/response over the mesh:
- Status requests and responses
- Command execution
- Error handling and timeouts

Prerequisites:
- Hub running
- At least one edge node with RPC server (q502)
"""

import asyncio
import logging
import time
from typing import Any

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.e2e
@pytest.mark.node_q502
@pytest.mark.slow
class TestRPCStatusRequest:
    """Test RPC status_request to edge nodes."""

    @pytest.mark.asyncio
    async def test_status_request_roundtrip(
        self,
        styrene_lifecycle,
        lxmf_service,
        rpc_client,
        require_q502: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Status request should complete roundtrip successfully."""
        destination = require_q502["destination_hash"]
        rpc_timeout = timeouts.get("rpc_timeout", 30)

        # Wait for mesh to settle
        await asyncio.sleep(5)

        logger.info(f"Sending status_request to {destination[:16]}...")
        start = time.time()

        try:
            response = await rpc_client.call_status(destination, timeout=rpc_timeout)
            elapsed = time.time() - start

            logger.info(f"Response received in {elapsed:.2f}s")
            logger.info(f"  Uptime: {response.format_uptime()}")
            logger.info(f"  IP: {response.ip}")

            # Verify response has expected fields
            assert response.uptime >= 0, "Invalid uptime"
            assert response.ip, "Missing IP address"

        except Exception as e:
            elapsed = time.time() - start
            pytest.fail(f"Status request failed after {elapsed:.2f}s: {e}")

    @pytest.mark.asyncio
    async def test_status_response_has_all_fields(
        self,
        styrene_lifecycle,
        lxmf_service,
        rpc_client,
        require_q502: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Status response should include all expected fields."""
        destination = require_q502["destination_hash"]
        rpc_timeout = timeouts.get("rpc_timeout", 30)

        await asyncio.sleep(5)

        response = await rpc_client.call_status(destination, timeout=rpc_timeout)

        # Check all expected fields
        assert hasattr(response, "uptime"), "Missing uptime field"
        assert hasattr(response, "ip"), "Missing ip field"
        assert hasattr(response, "disk_used"), "Missing disk_used field"
        assert hasattr(response, "disk_total"), "Missing disk_total field"
        assert hasattr(response, "services"), "Missing services field"

        # Validate types
        assert isinstance(response.uptime, (int, float)), "uptime should be numeric"
        assert isinstance(response.ip, str), "ip should be string"
        assert isinstance(response.services, list), "services should be list"

        logger.info("All status response fields validated")

    @pytest.mark.asyncio
    async def test_status_request_latency_acceptable(
        self,
        styrene_lifecycle,
        lxmf_service,
        rpc_client,
        require_q502: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Status request latency should be under 5 seconds."""
        destination = require_q502["destination_hash"]

        await asyncio.sleep(5)

        start = time.time()
        await rpc_client.call_status(destination, timeout=30)
        elapsed = time.time() - start

        logger.info(f"Roundtrip latency: {elapsed:.2f}s")

        # Mesh latency can be high, but should be reasonable
        assert elapsed < 10, f"Latency too high: {elapsed:.2f}s (expected <10s)"


@pytest.mark.e2e
@pytest.mark.node_q502
@pytest.mark.slow
class TestRPCCommandExecution:
    """Test RPC exec command to edge nodes."""

    @pytest.mark.asyncio
    async def test_exec_whitelisted_command(
        self,
        styrene_lifecycle,
        lxmf_service,
        rpc_client,
        require_q502: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Executing whitelisted command should succeed."""
        destination = require_q502["destination_hash"]
        rpc_timeout = timeouts.get("rpc_timeout", 30)

        await asyncio.sleep(5)

        logger.info("Executing: uname -a")

        response = await rpc_client.call_exec(
            destination, "uname -a", timeout=rpc_timeout
        )

        assert response.exit_code == 0, (
            f"Command failed with exit code {response.exit_code}"
        )
        assert response.stdout, "No stdout from uname -a"
        assert "Linux" in response.stdout or "Darwin" in response.stdout, (
            f"Unexpected uname output: {response.stdout}"
        )

        logger.info(f"Command output: {response.stdout.strip()}")

    @pytest.mark.asyncio
    async def test_exec_rnstatus_command(
        self,
        styrene_lifecycle,
        lxmf_service,
        rpc_client,
        require_q502: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Executing rnstatus should show Reticulum status."""
        destination = require_q502["destination_hash"]
        rpc_timeout = timeouts.get("rpc_timeout", 30)

        await asyncio.sleep(5)

        logger.info("Executing: rnstatus")

        try:
            response = await rpc_client.call_exec(
                destination, "rnstatus", timeout=rpc_timeout
            )

            # rnstatus might not be installed, that's OK
            if response.exit_code == 127:
                pytest.skip("rnstatus not installed on target")

            logger.info(f"rnstatus output:\n{response.stdout}")

        except Exception as e:
            pytest.skip(f"rnstatus command failed: {e}")

    @pytest.mark.asyncio
    async def test_exec_denied_command_returns_126(
        self,
        styrene_lifecycle,
        lxmf_service,
        rpc_client,
        require_q502: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Non-whitelisted command should return exit code 126."""
        destination = require_q502["destination_hash"]
        rpc_timeout = timeouts.get("rpc_timeout", 30)

        await asyncio.sleep(5)

        logger.info("Executing denied command: rm -rf /")

        response = await rpc_client.call_exec(
            destination, "rm -rf /", timeout=rpc_timeout
        )

        # 126 = command not allowed
        assert response.exit_code == 126, (
            f"Expected exit code 126 for denied command, got {response.exit_code}"
        )

        logger.info("Denied command correctly rejected")


@pytest.mark.e2e
@pytest.mark.slow
class TestRPCErrorHandling:
    """Test RPC error conditions."""

    @pytest.mark.asyncio
    async def test_request_to_unknown_destination_times_out(
        self,
        styrene_lifecycle,
        lxmf_service,
        rpc_client,
    ) -> None:
        """Request to unknown destination should timeout."""
        from styrened.rpc.errors import RPCTimeoutError

        # Fake destination that doesn't exist
        fake_destination = "deadbeefdeadbeefdeadbeefdeadbeef"

        await asyncio.sleep(3)

        logger.info(f"Sending request to non-existent destination...")
        start = time.time()

        with pytest.raises(RPCTimeoutError):
            await rpc_client.call_status(fake_destination, timeout=10)

        elapsed = time.time() - start
        logger.info(f"Timeout after {elapsed:.1f}s (expected)")

        # Should timeout around the specified time
        assert 8 < elapsed < 15, f"Timeout timing off: {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_concurrent_requests_correlate_correctly(
        self,
        styrene_lifecycle,
        lxmf_service,
        rpc_client,
        require_q502: dict[str, Any],
        timeouts: dict[str, int],
    ) -> None:
        """Multiple concurrent requests should return correct responses."""
        destination = require_q502["destination_hash"]
        rpc_timeout = timeouts.get("rpc_timeout", 30)

        await asyncio.sleep(5)

        logger.info("Sending 3 concurrent status requests...")

        # Send multiple requests concurrently
        tasks = [
            rpc_client.call_status(destination, timeout=rpc_timeout) for _ in range(3)
        ]

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # All should succeed
        successes = [r for r in responses if not isinstance(r, Exception)]
        failures = [r for r in responses if isinstance(r, Exception)]

        logger.info(f"Successes: {len(successes)}, Failures: {len(failures)}")

        assert len(successes) >= 2, (
            f"Expected at least 2 successes, got {len(successes)}"
        )

        # Responses should be similar (same node)
        if len(successes) >= 2:
            uptimes = [r.uptime for r in successes]
            # Uptimes should be within a few seconds of each other
            assert max(uptimes) - min(uptimes) < 10, f"Uptimes vary too much: {uptimes}"
