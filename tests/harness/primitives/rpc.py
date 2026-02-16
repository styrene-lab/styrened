"""RPC test primitives."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .base import PrimitiveResult

if TYPE_CHECKING:
    from ..base import NodeInfo, TestHarness

logger = logging.getLogger(__name__)


def send_status_request(
    harness: TestHarness,
    source_node: str | NodeInfo,
    target_identity: str,
    timeout: float = 30.0,
) -> PrimitiveResult:
    """Send RPC status request from source to target.

    Args:
        harness: Test harness instance
        source_node: Node to send request from
        target_identity: Target's LXMF identity hash
        timeout: Request timeout

    Returns:
        PrimitiveResult with status response data
    """
    start = time.time()
    source_name = source_node if isinstance(source_node, str) else source_node.name
    target_short = target_identity[:8] if target_identity else "unknown"

    logger.info(
        "[%s] Sending STATUS_REQUEST to %s... (timeout=%.1fs)", source_name, target_short, timeout
    )

    result = harness.query_status(source_node, target_identity, timeout=timeout)
    duration = time.time() - start

    if result.success:
        logger.info(
            "[%s] STATUS_REQUEST to %s... SUCCEEDED (%.2fs)", source_name, target_short, duration
        )
        logger.debug(
            "[%s] Response: %s", source_name, result.stdout[:200] if result.stdout else "(empty)"
        )
        return PrimitiveResult(
            success=True,
            name="send_status_request",
            node=source_name,
            duration=duration,
            message=f"Status request to {target_short}... succeeded",
            data={
                "target": target_identity,
                "response": result.stdout,
            },
        )
    else:
        logger.warning(
            "[%s] STATUS_REQUEST to %s... FAILED (%.2fs): %s",
            source_name,
            target_short,
            duration,
            result.stderr or "unknown error",
        )
        return PrimitiveResult(
            success=False,
            name="send_status_request",
            node=source_name,
            duration=duration,
            error=result.stderr or "Status request failed",
            data={
                "target": target_identity,
                "return_code": result.return_code,
                "stderr": result.stderr,
            },
        )


def send_exec_command(
    harness: TestHarness,
    source_node: str | NodeInfo,
    target_identity: str,
    command: str,
    timeout: float = 30.0,
) -> PrimitiveResult:
    """Send RPC exec command from source to target.

    Args:
        harness: Test harness instance
        source_node: Node to send command from
        target_identity: Target's LXMF identity hash
        command: Command to execute on target
        timeout: Request timeout

    Returns:
        PrimitiveResult with exec response data
    """
    start = time.time()
    source_name = source_node if isinstance(source_node, str) else source_node.name
    target_short = target_identity[:8] if target_identity else "unknown"

    logger.info(
        "[%s] Sending EXEC to %s...: '%s' (timeout=%.1fs)",
        source_name,
        target_short,
        command,
        timeout,
    )

    result = harness.exec_remote(source_node, target_identity, command, timeout=timeout)
    duration = time.time() - start

    if result.success:
        logger.info(
            "[%s] EXEC '%s' to %s... SUCCEEDED (%.2fs)",
            source_name,
            command,
            target_short,
            duration,
        )
        logger.debug(
            "[%s] stdout: %s", source_name, result.stdout[:200] if result.stdout else "(empty)"
        )
        if result.stderr:
            logger.debug("[%s] stderr: %s", source_name, result.stderr[:200])
        return PrimitiveResult(
            success=True,
            name="send_exec_command",
            node=source_name,
            duration=duration,
            message=f"Exec '{command}' to {target_short}... succeeded",
            data={
                "target": target_identity,
                "command": command,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
    else:
        logger.warning(
            "[%s] EXEC '%s' to %s... FAILED (%.2fs): %s",
            source_name,
            command,
            target_short,
            duration,
            result.stderr or "unknown error",
        )
        return PrimitiveResult(
            success=False,
            name="send_exec_command",
            node=source_name,
            duration=duration,
            error=result.stderr or "Exec command failed",
            data={
                "target": target_identity,
                "command": command,
                "return_code": result.return_code,
                "stderr": result.stderr,
            },
        )
