"""Connectivity test primitives."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .base import PrimitiveResult

if TYPE_CHECKING:
    from ..base import NodeInfo, TestHarness

logger = logging.getLogger(__name__)


def check_connectivity(
    harness: TestHarness,
    node: str | NodeInfo,
    timeout: float = 10.0,
) -> PrimitiveResult:
    """Check basic connectivity to a node.

    Args:
        harness: Test harness instance
        node: Target node
        timeout: Connection timeout

    Returns:
        PrimitiveResult indicating connectivity status
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.debug("[%s] Checking connectivity (timeout=%.1fs)...", node_name, timeout)

    result = harness.run(node, "echo ok", timeout=timeout)
    duration = time.time() - start

    if result.success and "ok" in result.stdout:
        logger.info("[%s] Connectivity check PASSED (%.2fs)", node_name, duration)
        return PrimitiveResult(
            success=True,
            name="check_connectivity",
            node=node_name,
            duration=duration,
            message="Node is reachable",
            data={"backend": result.backend.value},
        )
    else:
        logger.warning(
            "[%s] Connectivity check FAILED (%.2fs): %s",
            node_name,
            duration,
            result.stderr or "no response",
        )
        return PrimitiveResult(
            success=False,
            name="check_connectivity",
            node=node_name,
            duration=duration,
            error=result.stderr or "Connection failed",
            data={"return_code": result.return_code},
        )


def check_version(
    harness: TestHarness,
    node: str | NodeInfo,
    expected_version: str | None = None,
) -> PrimitiveResult:
    """Check styrened version on a node.

    Args:
        harness: Test harness instance
        node: Target node
        expected_version: Optional expected version string

    Returns:
        PrimitiveResult with version info
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.debug("[%s] Checking styrened version...", node_name)

    version = harness.get_version(node)
    duration = time.time() - start

    if version is None:
        logger.warning("[%s] Version check FAILED: could not determine version", node_name)
        return PrimitiveResult(
            success=False,
            name="check_version",
            node=node_name,
            duration=duration,
            error="Could not determine version",
        )

    if expected_version and version != expected_version:
        logger.warning(
            "[%s] Version check FAILED: expected %s, got %s", node_name, expected_version, version
        )
        return PrimitiveResult(
            success=False,
            name="check_version",
            node=node_name,
            duration=duration,
            message=f"Version mismatch: {version}",
            error=f"Expected {expected_version}, got {version}",
            data={"version": version, "expected": expected_version},
        )

    logger.info("[%s] Version check PASSED: %s (%.2fs)", node_name, version, duration)
    return PrimitiveResult(
        success=True,
        name="check_version",
        node=node_name,
        duration=duration,
        message=f"Version: {version}",
        data={"version": version},
    )
