"""Daemon lifecycle test primitives."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .base import PrimitiveResult

if TYPE_CHECKING:
    from ..base import NodeInfo, TestHarness

logger = logging.getLogger(__name__)


def check_daemon_running(
    harness: TestHarness,
    node: str | NodeInfo,
) -> PrimitiveResult:
    """Check if daemon is running on a node.

    Args:
        harness: Test harness instance
        node: Target node

    Returns:
        PrimitiveResult indicating daemon status
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.debug("[%s] Checking daemon status...", node_name)

    is_running = harness.is_daemon_running(node)
    duration = time.time() - start

    if is_running:
        logger.info("[%s] Daemon is RUNNING (%.2fs)", node_name, duration)
    else:
        logger.info("[%s] Daemon is NOT RUNNING (%.2fs)", node_name, duration)

    return PrimitiveResult(
        success=is_running,
        name="check_daemon_running",
        node=node_name,
        duration=duration,
        message="Daemon is running" if is_running else "Daemon is not running",
        data={"running": is_running},
        error=None if is_running else "Daemon not running",
    )


def ensure_daemon_running(
    harness: TestHarness,
    node: str | NodeInfo,
    start_if_stopped: bool = True,
    wait_timeout: float = 30.0,
) -> PrimitiveResult:
    """Ensure daemon is running, optionally starting it.

    Args:
        harness: Test harness instance
        node: Target node
        start_if_stopped: Whether to start daemon if not running
        wait_timeout: How long to wait for daemon to start

    Returns:
        PrimitiveResult indicating final daemon status
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.debug(
        "[%s] Ensuring daemon is running (start_if_stopped=%s)...", node_name, start_if_stopped
    )

    # Check current status
    is_running = harness.is_daemon_running(node)

    if is_running:
        logger.info("[%s] Daemon already running", node_name)
        return PrimitiveResult(
            success=True,
            name="ensure_daemon_running",
            node=node_name,
            duration=time.time() - start,
            message="Daemon already running",
            data={"already_running": True},
        )

    if not start_if_stopped:
        logger.warning("[%s] Daemon not running and start_if_stopped=False", node_name)
        return PrimitiveResult(
            success=False,
            name="ensure_daemon_running",
            node=node_name,
            duration=time.time() - start,
            error="Daemon not running and start_if_stopped=False",
            data={"already_running": False},
        )

    # Start daemon
    logger.info("[%s] Starting daemon...", node_name)
    start_result = harness.start_daemon(node)
    if not start_result.success:
        logger.error("[%s] Failed to start daemon: %s", node_name, start_result.stderr)
        return PrimitiveResult(
            success=False,
            name="ensure_daemon_running",
            node=node_name,
            duration=time.time() - start,
            error=f"Failed to start daemon: {start_result.stderr}",
            data={"start_attempted": True, "start_error": start_result.stderr},
        )

    # Wait for daemon to be responsive
    logger.debug(
        "[%s] Waiting for daemon to become responsive (timeout=%.1fs)...", node_name, wait_timeout
    )
    poll_interval = 2.0
    waited = 0.0
    while waited < wait_timeout:
        if harness.is_daemon_running(node):
            logger.info("[%s] Daemon started successfully after %.1fs", node_name, waited)
            return PrimitiveResult(
                success=True,
                name="ensure_daemon_running",
                node=node_name,
                duration=time.time() - start,
                message=f"Daemon started after {waited:.1f}s",
                data={"already_running": False, "startup_time": waited},
            )
        time.sleep(poll_interval)
        waited += poll_interval

    logger.error("[%s] Daemon did not start within %.1fs", node_name, wait_timeout)
    return PrimitiveResult(
        success=False,
        name="ensure_daemon_running",
        node=node_name,
        duration=time.time() - start,
        error=f"Daemon did not start within {wait_timeout}s",
        data={"already_running": False, "timeout": wait_timeout},
    )


def restart_daemon(
    harness: TestHarness,
    node: str | NodeInfo,
    wait_timeout: float = 30.0,
) -> PrimitiveResult:
    """Restart daemon on a node.

    Args:
        harness: Test harness instance
        node: Target node
        wait_timeout: How long to wait for daemon to restart

    Returns:
        PrimitiveResult indicating restart success
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.info("[%s] Restarting daemon...", node_name)

    # Stop daemon
    logger.debug("[%s] Stopping daemon...", node_name)
    stop_result = harness.stop_daemon(node)
    if not stop_result.success:
        logger.warning(
            "[%s] Stop returned error (may be expected): %s", node_name, stop_result.stderr
        )
    # Note: stop might "fail" on K8s where lifecycle is managed differently

    # Brief pause
    time.sleep(1.0)

    # Start daemon
    logger.debug("[%s] Starting daemon...", node_name)
    start_result = harness.start_daemon(node)
    if not start_result.success:
        logger.error("[%s] Failed to start daemon: %s", node_name, start_result.stderr)

    # Wait for daemon to be responsive
    logger.debug("[%s] Waiting for daemon to become responsive...", node_name)
    poll_interval = 2.0
    waited = 0.0
    while waited < wait_timeout:
        if harness.is_daemon_running(node):
            duration = time.time() - start
            logger.info(
                "[%s] Daemon restarted successfully after %.1fs (total %.2fs)",
                node_name,
                waited,
                duration,
            )
            return PrimitiveResult(
                success=True,
                name="restart_daemon",
                node=node_name,
                duration=duration,
                message=f"Daemon restarted after {waited:.1f}s",
                data={"restart_time": waited},
            )
        time.sleep(poll_interval)
        waited += poll_interval

    duration = time.time() - start
    logger.error(
        "[%s] Daemon did not restart within %.1fs (total %.2fs)", node_name, wait_timeout, duration
    )
    return PrimitiveResult(
        success=False,
        name="restart_daemon",
        node=node_name,
        duration=duration,
        error=f"Daemon did not restart within {wait_timeout}s",
        data={"timeout": wait_timeout},
    )
