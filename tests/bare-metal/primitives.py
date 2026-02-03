"""Low-level test primitives for bare-metal hardware testing.

These primitives are composable building blocks for test scenarios.
Each primitive tests a single, atomic operation and returns a structured result.

Design Principles:
    - Each primitive tests ONE thing
    - Primitives return Result objects with success/failure and details
    - Primitives are stateless - they don't modify the harness
    - Primitives have configurable timeouts and retry logic
    - Primitives log their actions for debugging

Usage:
    from primitives import (
        check_ssh_connectivity,
        check_daemon_running,
        check_mesh_discovery,
        send_rpc_status,
    )

    # Single check
    result = check_ssh_connectivity(harness, "styrene-node")
    assert result.success

    # Compose into scenarios
    for device in ["styrene-node", "t100ta"]:
        assert check_ssh_connectivity(harness, device).success
        assert check_daemon_running(harness, device).success
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from harness import BareMetalHarness

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Result Types
# -----------------------------------------------------------------------------


@dataclass
class TestResult:
    """Result of a test primitive execution.

    Attributes:
        success: Whether the test passed.
        name: Name of the primitive that was executed.
        device: Device the test was run on/from.
        duration: Execution time in seconds.
        message: Human-readable result description.
        data: Arbitrary result data for further inspection.
        error: Exception or error message if failed.
    """

    success: bool
    name: str
    device: str
    duration: float = 0.0
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        status = "PASS" if self.success else "FAIL"
        return f"<{status}> {self.name}@{self.device}: {self.message}"


# -----------------------------------------------------------------------------
# Connectivity Primitives
# -----------------------------------------------------------------------------


def check_ssh_connectivity(
    harness: BareMetalHarness,
    device: str,
    timeout: int = 10,
) -> TestResult:
    """Check if device is reachable via SSH.

    Args:
        harness: Test harness instance.
        device: Device name from registry.
        timeout: Connection timeout in seconds.

    Returns:
        TestResult with success=True if SSH connection succeeds.
    """
    start = time.time()
    try:
        result = harness.run(device, "echo ok", timeout=timeout)
        duration = time.time() - start
        if result.stdout.strip() == "ok":
            return TestResult(
                success=True,
                name="check_ssh_connectivity",
                device=device,
                duration=duration,
                message=f"SSH connection successful ({duration:.2f}s)",
            )
        else:
            return TestResult(
                success=False,
                name="check_ssh_connectivity",
                device=device,
                duration=duration,
                message=f"Unexpected response: {result.stdout[:50]}",
                error=result.stderr,
            )
    except subprocess.TimeoutExpired:
        return TestResult(
            success=False,
            name="check_ssh_connectivity",
            device=device,
            duration=timeout,
            message=f"SSH connection timed out after {timeout}s",
            error="TimeoutExpired",
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_ssh_connectivity",
            device=device,
            duration=time.time() - start,
            message=f"SSH connection failed: {e}",
            error=str(e),
        )


def check_network_reachability(
    harness: BareMetalHarness,
    from_device: str,
    to_device: str,
    timeout: int = 5,
) -> TestResult:
    """Check if one device can ping another.

    Args:
        harness: Test harness instance.
        from_device: Device to ping from.
        to_device: Device to ping to.
        timeout: Ping timeout in seconds.

    Returns:
        TestResult with success=True if ping succeeds.
    """
    start = time.time()
    to_host = harness.registry[to_device].host
    try:
        result = harness.run(
            from_device,
            f"ping -c 1 -W {timeout} {to_host}",
            timeout=timeout + 5,
            check=False,
        )
        duration = time.time() - start
        if result.returncode == 0:
            return TestResult(
                success=True,
                name="check_network_reachability",
                device=from_device,
                duration=duration,
                message=f"Can reach {to_device} ({to_host})",
                data={"target": to_device, "target_host": to_host},
            )
        else:
            return TestResult(
                success=False,
                name="check_network_reachability",
                device=from_device,
                duration=duration,
                message=f"Cannot reach {to_device}",
                data={"target": to_device, "target_host": to_host},
                error=result.stderr,
            )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_network_reachability",
            device=from_device,
            duration=time.time() - start,
            message=f"Ping failed: {e}",
            error=str(e),
        )


# -----------------------------------------------------------------------------
# Installation Primitives
# -----------------------------------------------------------------------------


def check_venv_exists(
    harness: BareMetalHarness,
    device: str,
) -> TestResult:
    """Check if Python venv exists on device.

    Args:
        harness: Test harness instance.
        device: Device name from registry.

    Returns:
        TestResult with success=True if venv exists.
    """
    start = time.time()
    info = harness.registry[device]
    try:
        result = harness.run(
            device,
            f"test -d {info.venv_path} && test -f {info.venv_path}/bin/activate && echo exists",
            check=False,
        )
        duration = time.time() - start
        exists = result.stdout.strip() == "exists"
        return TestResult(
            success=exists,
            name="check_venv_exists",
            device=device,
            duration=duration,
            message=f"venv {'exists' if exists else 'missing'} at {info.venv_path}",
            data={"venv_path": info.venv_path},
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_venv_exists",
            device=device,
            duration=time.time() - start,
            message=f"Check failed: {e}",
            error=str(e),
        )


def check_styrened_installed(
    harness: BareMetalHarness,
    device: str,
) -> TestResult:
    """Check if styrened is installed and get version.

    Args:
        harness: Test harness instance.
        device: Device name from registry.

    Returns:
        TestResult with version in data if installed.
    """
    start = time.time()
    try:
        version = harness.get_version(device)
        duration = time.time() - start
        return TestResult(
            success=True,
            name="check_styrened_installed",
            device=device,
            duration=duration,
            message=f"styrened {version} installed",
            data={"version": version},
        )
    except subprocess.CalledProcessError as e:
        return TestResult(
            success=False,
            name="check_styrened_installed",
            device=device,
            duration=time.time() - start,
            message="styrened not installed or not in PATH",
            error=e.stderr,
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_styrened_installed",
            device=device,
            duration=time.time() - start,
            message=f"Check failed: {e}",
            error=str(e),
        )


def check_config_exists(
    harness: BareMetalHarness,
    device: str,
) -> TestResult:
    """Check if styrene config exists on device.

    Args:
        harness: Test harness instance.
        device: Device name from registry.

    Returns:
        TestResult with success=True if config exists.
    """
    start = time.time()
    info = harness.registry[device]
    config_file = f"{info.config_path}/core-config.yaml"
    try:
        result = harness.run(
            device,
            f"test -f {config_file} && echo exists",
            check=False,
        )
        duration = time.time() - start
        exists = result.stdout.strip() == "exists"
        return TestResult(
            success=exists,
            name="check_config_exists",
            device=device,
            duration=duration,
            message=f"Config {'exists' if exists else 'missing'} at {config_file}",
            data={"config_path": config_file},
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_config_exists",
            device=device,
            duration=time.time() - start,
            message=f"Check failed: {e}",
            error=str(e),
        )


# -----------------------------------------------------------------------------
# Identity Primitives
# -----------------------------------------------------------------------------


def check_identity_exists(
    harness: BareMetalHarness,
    device: str,
) -> TestResult:
    """Check if device has a valid identity.

    Args:
        harness: Test harness instance.
        device: Device name from registry.

    Returns:
        TestResult with identity info in data if exists.
    """
    start = time.time()
    try:
        identity = harness.get_identity(device)
        duration = time.time() - start
        exists = identity.get("exists", False)
        identity_hash = identity.get("identity_hash", "")
        return TestResult(
            success=exists and len(identity_hash) == 32,
            name="check_identity_exists",
            device=device,
            duration=duration,
            message=f"Identity {'exists' if exists else 'missing'}: {identity_hash[:16]}...",
            data=identity,
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_identity_exists",
            device=device,
            duration=time.time() - start,
            message=f"Check failed: {e}",
            error=str(e),
        )


def check_identity_matches_registry(
    harness: BareMetalHarness,
    device: str,
) -> TestResult:
    """Check if device identity matches registry.

    Args:
        harness: Test harness instance.
        device: Device name from registry.

    Returns:
        TestResult with success=True if identity matches.
    """
    start = time.time()
    expected_hash = harness.registry[device].identity_hash
    try:
        identity = harness.get_identity(device)
        actual_hash = identity.get("identity_hash", "")
        duration = time.time() - start
        matches = actual_hash == expected_hash
        return TestResult(
            success=matches,
            name="check_identity_matches_registry",
            device=device,
            duration=duration,
            message=f"Identity {'matches' if matches else 'MISMATCH'}",
            data={
                "expected": expected_hash,
                "actual": actual_hash,
            },
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_identity_matches_registry",
            device=device,
            duration=time.time() - start,
            message=f"Check failed: {e}",
            error=str(e),
        )


# -----------------------------------------------------------------------------
# Daemon Primitives
# -----------------------------------------------------------------------------


def check_daemon_running(
    harness: BareMetalHarness,
    device: str,
) -> TestResult:
    """Check if styrened daemon is running.

    Args:
        harness: Test harness instance.
        device: Device name from registry.

    Returns:
        TestResult with success=True if daemon is active.
    """
    start = time.time()
    try:
        running = harness.is_daemon_running(device)
        duration = time.time() - start
        return TestResult(
            success=running,
            name="check_daemon_running",
            device=device,
            duration=duration,
            message=f"Daemon {'running' if running else 'not running'}",
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_daemon_running",
            device=device,
            duration=time.time() - start,
            message=f"Check failed: {e}",
            error=str(e),
        )


def start_daemon(
    harness: BareMetalHarness,
    device: str,
    wait_timeout: int = 30,
) -> TestResult:
    """Start daemon and wait for it to become responsive.

    Args:
        harness: Test harness instance.
        device: Device name from registry.
        wait_timeout: Seconds to wait for daemon to become responsive.

    Returns:
        TestResult with success=True if daemon started and responsive.
    """
    start = time.time()
    try:
        # Start daemon
        started = harness.start_daemon(device)
        if not started:
            return TestResult(
                success=False,
                name="start_daemon",
                device=device,
                duration=time.time() - start,
                message="Failed to start daemon (systemctl returned error)",
            )

        # Wait for responsiveness
        responsive = harness.wait_for_daemon(device, timeout=wait_timeout)
        duration = time.time() - start
        return TestResult(
            success=responsive,
            name="start_daemon",
            device=device,
            duration=duration,
            message=f"Daemon {'started and responsive' if responsive else 'started but not responsive'}",
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="start_daemon",
            device=device,
            duration=time.time() - start,
            message=f"Start failed: {e}",
            error=str(e),
        )


def stop_daemon(
    harness: BareMetalHarness,
    device: str,
) -> TestResult:
    """Stop daemon.

    Args:
        harness: Test harness instance.
        device: Device name from registry.

    Returns:
        TestResult with success=True if daemon stopped.
    """
    start = time.time()
    try:
        stopped = harness.stop_daemon(device)
        duration = time.time() - start
        return TestResult(
            success=stopped,
            name="stop_daemon",
            device=device,
            duration=duration,
            message=f"Daemon {'stopped' if stopped else 'failed to stop'}",
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="stop_daemon",
            device=device,
            duration=time.time() - start,
            message=f"Stop failed: {e}",
            error=str(e),
        )


def restart_daemon(
    harness: BareMetalHarness,
    device: str,
    wait_timeout: int = 30,
) -> TestResult:
    """Restart daemon and wait for responsiveness.

    Args:
        harness: Test harness instance.
        device: Device name from registry.
        wait_timeout: Seconds to wait after restart.

    Returns:
        TestResult with success=True if daemon restarted and responsive.
    """
    start = time.time()
    try:
        restarted = harness.restart_daemon(device)
        if not restarted:
            return TestResult(
                success=False,
                name="restart_daemon",
                device=device,
                duration=time.time() - start,
                message="Failed to restart daemon",
            )

        responsive = harness.wait_for_daemon(device, timeout=wait_timeout)
        duration = time.time() - start
        return TestResult(
            success=responsive,
            name="restart_daemon",
            device=device,
            duration=duration,
            message=f"Daemon {'restarted' if responsive else 'restarted but not responsive'}",
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="restart_daemon",
            device=device,
            duration=time.time() - start,
            message=f"Restart failed: {e}",
            error=str(e),
        )


# -----------------------------------------------------------------------------
# Mesh Discovery Primitives
# -----------------------------------------------------------------------------


def discover_devices(
    harness: BareMetalHarness,
    from_device: str,
    wait: int = 15,
) -> TestResult:
    """Run device discovery from a device.

    Args:
        harness: Test harness instance.
        from_device: Device to run discovery from.
        wait: Seconds to wait for announces.

    Returns:
        TestResult with discovered devices in data.
    """
    start = time.time()
    try:
        devices = harness.discover_devices(from_device, wait=wait)
        duration = time.time() - start
        return TestResult(
            success=True,
            name="discover_devices",
            device=from_device,
            duration=duration,
            message=f"Discovered {len(devices)} device(s)",
            data={"devices": devices, "count": len(devices)},
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="discover_devices",
            device=from_device,
            duration=time.time() - start,
            message=f"Discovery failed: {e}",
            error=str(e),
        )


def check_device_discovered(
    harness: BareMetalHarness,
    from_device: str,
    target_device: str,
    wait: int = 20,
) -> TestResult:
    """Check if target device is discovered from source device.

    Args:
        harness: Test harness instance.
        from_device: Device to run discovery from.
        target_device: Device that should be discovered.
        wait: Seconds to wait for announces.

    Returns:
        TestResult with success=True if target was discovered.
    """
    start = time.time()
    target_hash = harness.registry[target_device].identity_hash
    try:
        devices = harness.discover_devices(from_device, wait=wait)
        duration = time.time() - start

        # Check if target is in discovered devices
        found = any(
            d.get("identity_hash", "").startswith(target_hash[:16])
            or d.get("destination", "").startswith(target_hash[:16])
            for d in devices
        )

        return TestResult(
            success=found,
            name="check_device_discovered",
            device=from_device,
            duration=duration,
            message=f"{'Found' if found else 'Did not find'} {target_device}",
            data={
                "target": target_device,
                "target_hash": target_hash,
                "devices_found": len(devices),
            },
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_device_discovered",
            device=from_device,
            duration=time.time() - start,
            message=f"Discovery failed: {e}",
            error=str(e),
        )


# -----------------------------------------------------------------------------
# RPC Primitives
# -----------------------------------------------------------------------------


def send_rpc_status(
    harness: BareMetalHarness,
    from_device: str,
    to_device: str,
    timeout: int = 60,
) -> TestResult:
    """Send RPC status query from one device to another.

    Args:
        harness: Test harness instance.
        from_device: Device to send query from.
        to_device: Device to query.
        timeout: RPC timeout in seconds.

    Returns:
        TestResult with status info in data if successful.
    """
    start = time.time()
    to_hash = harness.registry[to_device].identity_hash
    try:
        status = harness.query_status(from_device, to_hash, timeout=timeout)
        duration = time.time() - start

        if status is not None:
            return TestResult(
                success=True,
                name="send_rpc_status",
                device=from_device,
                duration=duration,
                message=f"Status query to {to_device} succeeded",
                data={"target": to_device, "status": status},
            )
        else:
            return TestResult(
                success=False,
                name="send_rpc_status",
                device=from_device,
                duration=duration,
                message=f"Status query to {to_device} returned None",
                data={"target": to_device},
            )
    except Exception as e:
        return TestResult(
            success=False,
            name="send_rpc_status",
            device=from_device,
            duration=time.time() - start,
            message=f"Status query failed: {e}",
            error=str(e),
        )


def send_rpc_exec(
    harness: BareMetalHarness,
    from_device: str,
    to_device: str,
    command: str,
    timeout: int = 60,
) -> TestResult:
    """Execute command on remote device via RPC.

    Args:
        harness: Test harness instance.
        from_device: Device to send command from.
        to_device: Device to execute command on.
        command: Command to execute.
        timeout: RPC timeout in seconds.

    Returns:
        TestResult with command output in data if successful.
    """
    start = time.time()
    to_hash = harness.registry[to_device].identity_hash
    try:
        result = harness.exec_command(from_device, to_hash, command, timeout=timeout)
        duration = time.time() - start

        if result is not None:
            exit_code = result.get("exit_code", -1)
            return TestResult(
                success=exit_code == 0,
                name="send_rpc_exec",
                device=from_device,
                duration=duration,
                message=f"Exec '{command}' on {to_device}: exit={exit_code}",
                data={
                    "target": to_device,
                    "command": command,
                    "result": result,
                },
            )
        else:
            return TestResult(
                success=False,
                name="send_rpc_exec",
                device=from_device,
                duration=duration,
                message=f"Exec command on {to_device} returned None",
                data={"target": to_device, "command": command},
            )
    except Exception as e:
        return TestResult(
            success=False,
            name="send_rpc_exec",
            device=from_device,
            duration=time.time() - start,
            message=f"Exec command failed: {e}",
            error=str(e),
        )


# -----------------------------------------------------------------------------
# Chat/LXMF Primitives
# -----------------------------------------------------------------------------


def send_chat_message(
    harness: BareMetalHarness,
    from_device: str,
    to_device: str,
    message: str,
    timeout: int = 60,
) -> TestResult:
    """Send chat message from one device to another.

    Args:
        harness: Test harness instance.
        from_device: Device to send from.
        to_device: Device to send to.
        message: Message content.
        timeout: Send timeout in seconds.

    Returns:
        TestResult with success=True if message sent/queued.
    """
    start = time.time()
    to_hash = harness.registry[to_device].identity_hash
    try:
        result = harness.run_styrened(
            from_device,
            f'send {to_hash} "{message}"',
            timeout=timeout,
            check=False,
        )
        duration = time.time() - start

        # Check for success indicators
        success = result.returncode == 0 or "queued" in result.stdout.lower()
        return TestResult(
            success=success,
            name="send_chat_message",
            device=from_device,
            duration=duration,
            message=f"Chat to {to_device}: {'sent' if success else 'failed'}",
            data={
                "target": to_device,
                "message": message,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="send_chat_message",
            device=from_device,
            duration=time.time() - start,
            message=f"Send failed: {e}",
            error=str(e),
        )


# -----------------------------------------------------------------------------
# Deployment Primitives
# -----------------------------------------------------------------------------


def deploy_wheel(
    harness: BareMetalHarness,
    device: str,
    wheel_path: str,
) -> TestResult:
    """Deploy wheel to device.

    Args:
        harness: Test harness instance.
        device: Device to deploy to.
        wheel_path: Path to wheel file.

    Returns:
        TestResult with success=True if deployment succeeded.
    """
    from pathlib import Path

    start = time.time()
    wheel = Path(wheel_path)
    if not wheel.exists():
        return TestResult(
            success=False,
            name="deploy_wheel",
            device=device,
            duration=0,
            message=f"Wheel not found: {wheel_path}",
            error="FileNotFoundError",
        )

    try:
        success = harness.deploy_wheel(device, wheel)
        duration = time.time() - start
        return TestResult(
            success=success,
            name="deploy_wheel",
            device=device,
            duration=duration,
            message=f"Deployed {wheel.name}: {'success' if success else 'failed'}",
            data={"wheel": str(wheel)},
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="deploy_wheel",
            device=device,
            duration=time.time() - start,
            message=f"Deploy failed: {e}",
            error=str(e),
        )


def check_version_matches(
    harness: BareMetalHarness,
    device: str,
    expected_version: str,
) -> TestResult:
    """Check if installed version matches expected.

    Args:
        harness: Test harness instance.
        device: Device to check.
        expected_version: Expected version string.

    Returns:
        TestResult with success=True if versions match.
    """
    start = time.time()
    try:
        actual = harness.get_version(device)
        duration = time.time() - start
        # Handle "styrened X.Y.Z" format
        actual_version = actual.replace("styrened ", "").strip()
        matches = actual_version == expected_version
        return TestResult(
            success=matches,
            name="check_version_matches",
            device=device,
            duration=duration,
            message=f"Version {'matches' if matches else 'MISMATCH'}: {actual_version}",
            data={
                "expected": expected_version,
                "actual": actual_version,
            },
        )
    except Exception as e:
        return TestResult(
            success=False,
            name="check_version_matches",
            device=device,
            duration=time.time() - start,
            message=f"Check failed: {e}",
            error=str(e),
        )


# -----------------------------------------------------------------------------
# Composite Primitives (built from other primitives)
# -----------------------------------------------------------------------------


def ensure_daemon_running(
    harness: BareMetalHarness,
    device: str,
    wait_timeout: int = 30,
) -> TestResult:
    """Ensure daemon is running, starting it if necessary.

    Args:
        harness: Test harness instance.
        device: Device to check/start.
        wait_timeout: Seconds to wait if starting.

    Returns:
        TestResult with success=True if daemon is running.
    """
    # Check if already running
    check_result = check_daemon_running(harness, device)
    if check_result.success:
        return TestResult(
            success=True,
            name="ensure_daemon_running",
            device=device,
            duration=check_result.duration,
            message="Daemon already running",
        )

    # Start daemon
    start_result = start_daemon(harness, device, wait_timeout=wait_timeout)
    return TestResult(
        success=start_result.success,
        name="ensure_daemon_running",
        device=device,
        duration=start_result.duration,
        message=start_result.message,
        error=start_result.error,
    )


def check_bidirectional_discovery(
    harness: BareMetalHarness,
    device_a: str,
    device_b: str,
    wait: int = 20,
) -> TestResult:
    """Check if two devices can discover each other.

    Args:
        harness: Test harness instance.
        device_a: First device.
        device_b: Second device.
        wait: Discovery wait time in seconds.

    Returns:
        TestResult with success=True if both can see each other.
    """
    start = time.time()

    # A discovers B
    a_sees_b = check_device_discovered(harness, device_a, device_b, wait=wait)
    if not a_sees_b.success:
        return TestResult(
            success=False,
            name="check_bidirectional_discovery",
            device=f"{device_a},{device_b}",
            duration=time.time() - start,
            message=f"{device_a} cannot discover {device_b}",
            data={"a_sees_b": False, "b_sees_a": None},
        )

    # B discovers A
    b_sees_a = check_device_discovered(harness, device_b, device_a, wait=wait)
    duration = time.time() - start

    return TestResult(
        success=b_sees_a.success,
        name="check_bidirectional_discovery",
        device=f"{device_a},{device_b}",
        duration=duration,
        message=f"Bidirectional discovery {'succeeded' if b_sees_a.success else 'failed (B cannot see A)'}",
        data={"a_sees_b": True, "b_sees_a": b_sees_a.success},
    )


def check_bidirectional_rpc(
    harness: BareMetalHarness,
    device_a: str,
    device_b: str,
    timeout: int = 60,
) -> TestResult:
    """Check if two devices can exchange RPC status queries.

    Args:
        harness: Test harness instance.
        device_a: First device.
        device_b: Second device.
        timeout: RPC timeout in seconds.

    Returns:
        TestResult with success=True if both directions work.
    """
    start = time.time()

    # A queries B
    a_to_b = send_rpc_status(harness, device_a, device_b, timeout=timeout)
    if not a_to_b.success:
        return TestResult(
            success=False,
            name="check_bidirectional_rpc",
            device=f"{device_a},{device_b}",
            duration=time.time() - start,
            message=f"RPC {device_a} -> {device_b} failed",
            data={"a_to_b": False, "b_to_a": None},
        )

    # B queries A
    b_to_a = send_rpc_status(harness, device_b, device_a, timeout=timeout)
    duration = time.time() - start

    return TestResult(
        success=b_to_a.success,
        name="check_bidirectional_rpc",
        device=f"{device_a},{device_b}",
        duration=duration,
        message=f"Bidirectional RPC {'succeeded' if b_to_a.success else 'failed (B->A)'}",
        data={"a_to_b": True, "b_to_a": b_to_a.success},
    )
