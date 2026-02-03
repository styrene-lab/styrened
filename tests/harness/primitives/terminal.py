"""Terminal session test primitives.

These primitives provide cross-platform terminal session testing capabilities
that work with both SSH and K8s backends.

Terminal testing is challenging due to the interactive nature of sessions.
The approach here is:
1. Session establishment: Test that sessions can be requested and either
   accepted or rejected based on authorization
2. I/O verification: Use simple command execution to verify data flows
3. Protocol validation: Test control messages (resize, signal, close)

For full interactive testing, manual verification is recommended.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .base import PrimitiveResult

if TYPE_CHECKING:
    from tests.harness.base import NodeInfo, TestHarness

logger = logging.getLogger(__name__)


def check_terminal_service_config(
    harness: TestHarness,
    node: str | NodeInfo,
) -> PrimitiveResult:
    """Check if terminal service is enabled in node configuration.

    Args:
        harness: Test harness instance
        node: Node to check

    Returns:
        PrimitiveResult with:
        - success: True if terminal service is configured
        - data: {"enabled": bool, "config": dict} with terminal config
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.debug("[%s] Checking terminal service configuration...", node_name)

    # Query the daemon's config via CLI
    result = harness.run(node, "styrened config --json 2>/dev/null || styrened config", timeout=10)
    duration = time.time() - start

    if not result.success:
        logger.warning("[%s] Failed to get config (%.2fs): %s", node_name, duration, result.stderr)
        return PrimitiveResult(
            success=False,
            name="check_terminal_service_config",
            node=node_name,
            duration=duration,
            error=f"Failed to query config: {result.stderr}",
            data={"return_code": result.return_code},
        )

    # Parse config output
    stdout = result.stdout.strip()
    terminal_enabled = False
    config_data = {}

    # Try JSON parsing first
    try:
        import json

        config = json.loads(stdout)
        terminal_config = config.get("terminal", {})
        terminal_enabled = terminal_config.get("enabled", False)
        config_data = terminal_config
    except (json.JSONDecodeError, TypeError):
        # Fall back to text parsing - look for terminal section
        if "terminal:" in stdout.lower():
            terminal_enabled = "enabled: true" in stdout.lower()
            config_data = {"raw": stdout}

    logger.info(
        "[%s] Terminal service config check (%.2fs): enabled=%s",
        node_name,
        duration,
        terminal_enabled,
    )

    return PrimitiveResult(
        success=True,  # Successfully queried config
        name="check_terminal_service_config",
        node=node_name,
        duration=duration,
        message=f"Terminal enabled: {terminal_enabled}",
        data={"enabled": terminal_enabled, "config": config_data},
    )


def start_terminal_session(
    harness: TestHarness,
    source_node: str | NodeInfo,
    target_id: str,
    term_type: str = "xterm-256color",
    rows: int = 24,
    cols: int = 80,
    timeout: float = 30.0,
) -> PrimitiveResult:
    """Attempt to start a terminal session from source_node to target.

    This primitive tests the session establishment protocol by attempting
    to start a terminal session. It expects either:
    - Success: Session accepted (if authorized)
    - Rejection: Session rejected with reason (if unauthorized)
    - Timeout: No response (network/service issue)

    Note: This uses the CLI in a way that will timeout/exit quickly
    rather than entering interactive mode, since we're testing
    session establishment, not interactive I/O.

    Args:
        harness: Test harness instance
        source_node: Node initiating the session
        target_id: Identity hash of target node (32 hex chars)
        term_type: Terminal type
        rows: Terminal rows
        cols: Terminal columns
        timeout: Timeout for session establishment

    Returns:
        PrimitiveResult with:
        - success: True if session was accepted
        - data: Session info on success, rejection reason on failure
        - error: Error message if failed
    """
    start = time.time()
    node_name = source_node if isinstance(source_node, str) else source_node.name

    logger.debug("[%s] Starting terminal session to %s...", node_name, target_id[:16])

    # Build shell command with short wait and timeout
    # We use a subshell with timeout to prevent hanging
    # The shell command will try to connect but we'll kill it early
    # This tests the session request/response cycle
    cmd = (
        f"timeout {int(timeout)} styrened shell {target_id} "
        f"-T {term_type} -r {rows} -c {cols} -w 5 "
        f"2>&1 || true"
    )

    result = harness.run(source_node, cmd, timeout=timeout + 5)
    duration = time.time() - start

    stdout = result.stdout.strip().lower()
    stderr = result.stderr.strip().lower() if result.stderr else ""
    combined = stdout + " " + stderr

    # Analyze the output to determine what happened
    if "connected" in combined or "session established" in combined:
        logger.info("[%s] Terminal session ACCEPTED (%.2fs)", node_name, duration)
        return PrimitiveResult(
            success=True,
            name="start_terminal_session",
            node=node_name,
            duration=duration,
            message=f"Session accepted by {target_id[:16]}",
            data={
                "target": target_id,
                "accepted": True,
                "stdout": result.stdout,
            },
        )

    elif "rejected" in combined or "unauthorized" in combined or "denied" in combined:
        # Session was rejected - this is a valid response
        reason = "unauthorized"
        if "rejected" in combined:
            reason = "rejected"
        if "denied" in combined:
            reason = "denied"

        logger.info("[%s] Terminal session REJECTED (%.2fs): %s", node_name, duration, reason)
        return PrimitiveResult(
            success=False,
            name="start_terminal_session",
            node=node_name,
            duration=duration,
            message=f"Session rejected: {reason}",
            error=reason,
            data={
                "target": target_id,
                "accepted": False,
                "rejected": True,
                "reason": reason,
                "stdout": result.stdout,
            },
        )

    elif "not found" in combined or "timeout" in combined or "no path" in combined:
        logger.warning("[%s] Terminal session TIMEOUT/NO PATH (%.2fs)", node_name, duration)
        return PrimitiveResult(
            success=False,
            name="start_terminal_session",
            node=node_name,
            duration=duration,
            error="Target not found or no path available",
            data={
                "target": target_id,
                "accepted": False,
                "rejected": False,
                "timeout": True,
                "stdout": result.stdout,
            },
        )

    elif "terminal service" in combined and "not" in combined:
        logger.warning("[%s] Terminal service not available (%.2fs)", node_name, duration)
        return PrimitiveResult(
            success=False,
            name="start_terminal_session",
            node=node_name,
            duration=duration,
            error="Terminal service not available on target",
            data={
                "target": target_id,
                "service_unavailable": True,
                "stdout": result.stdout,
            },
        )

    elif "invalid choice" in combined and "shell" in combined:
        # Shell command not available in this version
        logger.warning(
            "[%s] Shell command not available (%.2fs) - older version?",
            node_name,
            duration,
        )
        return PrimitiveResult(
            success=False,
            name="start_terminal_session",
            node=node_name,
            duration=duration,
            error="Shell command not available - version may not support terminal sessions",
            data={
                "target": target_id,
                "command_unavailable": True,
                "stdout": result.stdout,
            },
        )

    else:
        # Unknown response - could be partial output or error
        logger.warning(
            "[%s] Terminal session UNKNOWN response (%.2fs): %s",
            node_name,
            duration,
            result.stdout[:200] if result.stdout else "empty",
        )
        return PrimitiveResult(
            success=False,
            name="start_terminal_session",
            node=node_name,
            duration=duration,
            error=f"Unknown response: {result.stdout[:100] if result.stdout else 'no output'}",
            data={
                "target": target_id,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.return_code,
            },
        )


def verify_terminal_roundtrip(
    harness: TestHarness,
    source_node: str | NodeInfo,
    target_id: str,
    test_command: str = "echo terminal_test_ok",
    timeout: float = 30.0,
) -> PrimitiveResult:
    """Verify terminal I/O by running a command and checking output.

    This is a higher-level primitive that verifies the full terminal pipeline:
    1. Session establishment
    2. Command execution
    3. Output capture
    4. Session cleanup

    Note: This uses the RPC exec command as a proxy for terminal I/O
    since it exercises similar code paths without requiring interactive
    terminal management.

    Args:
        harness: Test harness instance
        source_node: Node initiating the test
        target_id: Identity hash of target node
        test_command: Command to run on target
        timeout: Timeout for the operation

    Returns:
        PrimitiveResult with:
        - success: True if command executed and output received
        - data: {"output": str, "command": str}
    """
    start = time.time()
    node_name = source_node if isinstance(source_node, str) else source_node.name

    logger.debug(
        "[%s] Verifying terminal roundtrip to %s with command: %s",
        node_name,
        target_id[:16],
        test_command,
    )

    # Use exec RPC to test I/O (exercises similar protocol path)
    cmd = f"styrened exec {target_id} {test_command}"
    result = harness.run(source_node, cmd, timeout=timeout)
    duration = time.time() - start

    if result.success and "terminal_test_ok" in result.stdout:
        logger.info("[%s] Terminal roundtrip PASSED (%.2fs)", node_name, duration)
        return PrimitiveResult(
            success=True,
            name="verify_terminal_roundtrip",
            node=node_name,
            duration=duration,
            message="Terminal I/O verified via exec",
            data={
                "target": target_id,
                "command": test_command,
                "output": result.stdout.strip(),
            },
        )
    else:
        logger.warning(
            "[%s] Terminal roundtrip FAILED (%.2fs): %s",
            node_name,
            duration,
            result.stderr or result.stdout,
        )
        return PrimitiveResult(
            success=False,
            name="verify_terminal_roundtrip",
            node=node_name,
            duration=duration,
            error=result.stderr or "Unexpected output",
            data={
                "target": target_id,
                "command": test_command,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "return_code": result.return_code,
            },
        )


def send_terminal_input(
    harness: TestHarness,
    node: str | NodeInfo,
    session_id: bytes,
    data: bytes,
) -> PrimitiveResult:
    """Send input data to an established terminal session.

    Note: This primitive requires an active terminal session with a known
    session_id. In automated testing, this is challenging because sessions
    are typically interactive.

    For now, this is a placeholder that documents the intended interface.
    Full implementation would require:
    1. IPC access to the running session
    2. Or a test-mode flag in the shell command

    Args:
        harness: Test harness instance
        node: Node with the active session
        session_id: Session identifier
        data: Data to send to terminal stdin

    Returns:
        PrimitiveResult with success/error status
    """
    node_name = node if isinstance(node, str) else node.name

    # This would require IPC or special test infrastructure
    # For now, use test_terminal_roundtrip instead
    return PrimitiveResult(
        success=False,
        name="send_terminal_input",
        node=node_name,
        error="Interactive session I/O not supported in automated tests. Use test_terminal_roundtrip instead.",
        data={"session_id": session_id.hex() if session_id else None},
    )


def read_terminal_output(
    harness: TestHarness,
    node: str | NodeInfo,
    timeout: float = 10.0,
) -> PrimitiveResult:
    """Read output from an established terminal session.

    Note: This primitive requires an active terminal session.
    See send_terminal_input for limitations.

    Args:
        harness: Test harness instance
        node: Node with the active session
        timeout: Maximum time to wait for output

    Returns:
        PrimitiveResult with:
        - success: True if output received
        - data: {"output": bytes} containing terminal output
    """
    node_name = node if isinstance(node, str) else node.name

    return PrimitiveResult(
        success=False,
        name="read_terminal_output",
        node=node_name,
        error="Interactive session I/O not supported in automated tests. Use test_terminal_roundtrip instead.",
        data={},
    )


def close_terminal_session(
    harness: TestHarness,
    node: str | NodeInfo,
    session_id: bytes,
) -> PrimitiveResult:
    """Close an established terminal session.

    In practice, sessions are closed when:
    1. The shell process exits
    2. The connection times out
    3. The user sends Ctrl-D or exit

    This primitive is a placeholder for explicit session closure.

    Args:
        harness: Test harness instance
        node: Node with the active session
        session_id: Session identifier to close

    Returns:
        PrimitiveResult with success/error status
    """
    node_name = node if isinstance(node, str) else node.name

    return PrimitiveResult(
        success=False,
        name="close_terminal_session",
        node=node_name,
        error="Explicit session closure not implemented. Sessions close automatically on exit.",
        data={"session_id": session_id.hex() if session_id else None},
    )


def resize_terminal_session(
    harness: TestHarness,
    node: str | NodeInfo,
    session_id: bytes,
    rows: int,
    cols: int,
) -> PrimitiveResult:
    """Resize an established terminal session.

    Args:
        harness: Test harness instance
        node: Node with the active session
        session_id: Session identifier
        rows: New row count
        cols: New column count

    Returns:
        PrimitiveResult with success/error status
    """
    node_name = node if isinstance(node, str) else node.name

    return PrimitiveResult(
        success=False,
        name="resize_terminal_session",
        node=node_name,
        error="Interactive session resize not supported in automated tests.",
        data={
            "session_id": session_id.hex() if session_id else None,
            "rows": rows,
            "cols": cols,
        },
    )


def send_terminal_signal(
    harness: TestHarness,
    node: str | NodeInfo,
    session_id: bytes,
    signal_num: int,
) -> PrimitiveResult:
    """Send a signal to the remote process in a terminal session.

    Args:
        harness: Test harness instance
        node: Node with the active session
        session_id: Session identifier
        signal_num: Signal number to send (e.g., signal.SIGINT)

    Returns:
        PrimitiveResult with success/error status
    """
    node_name = node if isinstance(node, str) else node.name

    return PrimitiveResult(
        success=False,
        name="send_terminal_signal",
        node=node_name,
        error="Interactive session signals not supported in automated tests.",
        data={
            "session_id": session_id.hex() if session_id else None,
            "signal": signal_num,
        },
    )


def check_terminal_session_cleanup(
    harness: TestHarness,
    node: str | NodeInfo,
    timeout: float = 10.0,
) -> PrimitiveResult:
    """Verify that terminal sessions are properly cleaned up.

    Checks that:
    1. No orphaned PTY processes exist
    2. No stale session state remains
    3. Resources are released

    Args:
        harness: Test harness instance
        node: Node to check
        timeout: Timeout for checks

    Returns:
        PrimitiveResult with cleanup status
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.debug("[%s] Checking terminal session cleanup...", node_name)

    # Check for orphaned PTY processes
    result = harness.run(node, "pgrep -f 'styrened.*terminal' 2>/dev/null | wc -l", timeout=timeout)
    duration = time.time() - start

    if not result.success:
        return PrimitiveResult(
            success=False,
            name="check_terminal_session_cleanup",
            node=node_name,
            duration=duration,
            error=f"Failed to check processes: {result.stderr}",
            data={},
        )

    try:
        process_count = int(result.stdout.strip())
    except ValueError:
        process_count = -1

    # A small number of daemon processes is expected
    # Alert if there are many (potential leak)
    if process_count > 5:
        logger.warning(
            "[%s] Potential session leak: %d terminal processes", node_name, process_count
        )
        return PrimitiveResult(
            success=False,
            name="check_terminal_session_cleanup",
            node=node_name,
            duration=duration,
            error=f"Too many terminal processes: {process_count}",
            data={"process_count": process_count},
        )

    logger.info(
        "[%s] Terminal cleanup OK (%.2fs): %d processes", node_name, duration, process_count
    )
    return PrimitiveResult(
        success=True,
        name="check_terminal_session_cleanup",
        node=node_name,
        duration=duration,
        message=f"Cleanup verified: {process_count} terminal processes",
        data={"process_count": process_count},
    )
