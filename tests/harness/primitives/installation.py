"""Installation test primitives.

Handles deployment and provisioning of styrened on bare-metal devices.
Supports multiple installation methods:
- pip (git-based PyPI, wheel files)
- nix (flake-based)
- container (podman/docker)
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from .base import PrimitiveResult

if TYPE_CHECKING:
    from ..base import NodeInfo
    from ..ssh import SSHHarness

# Module logger
logger = logging.getLogger(__name__)


class InstallMethod(Enum):
    """Supported installation methods."""

    PIP_GIT = "pip_git"  # pip install git+https://...
    PIP_WHEEL = "pip_wheel"  # pip install /path/to/wheel.whl
    NIX_FLAKE = "nix_flake"  # nix profile install github:...
    NIX_SHELL = "nix_shell"  # nix develop / nix-shell


def check_installation_prerequisites(
    harness: SSHHarness,
    node: str | NodeInfo,
    method: InstallMethod,
) -> PrimitiveResult:
    """Check if prerequisites for installation method are met.

    Args:
        harness: SSH harness instance
        node: Target node
        method: Installation method to check

    Returns:
        PrimitiveResult indicating readiness
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.info("Checking prerequisites for %s on %s", method.value, node_name)

    checks = []

    if method == InstallMethod.PIP_GIT or method == InstallMethod.PIP_WHEEL:
        # Check for Python and pip
        logger.debug("[%s] Checking python3...", node_name)
        result = harness.run(node, "python3 --version")
        checks.append(("python3", result.success))
        if result.success:
            logger.debug("[%s] python3: %s", node_name, result.stdout.strip())
        else:
            logger.warning("[%s] python3 not found: %s", node_name, result.stderr.strip())

        logger.debug("[%s] Checking pip...", node_name)
        result = harness.run(node, "pip3 --version || python3 -m pip --version")
        checks.append(("pip", result.success))
        if result.success:
            logger.debug("[%s] pip: %s", node_name, result.stdout.strip())
        else:
            logger.warning("[%s] pip not found: %s", node_name, result.stderr.strip())

    elif method == InstallMethod.NIX_FLAKE or method == InstallMethod.NIX_SHELL:
        # Check for Nix
        logger.debug("[%s] Checking nix...", node_name)
        result = harness.run(node, "nix --version")
        checks.append(("nix", result.success))
        if result.success:
            logger.debug("[%s] nix: %s", node_name, result.stdout.strip())
        else:
            logger.warning("[%s] nix not found: %s", node_name, result.stderr.strip())

        # Check for flakes support
        logger.debug("[%s] Checking flakes support...", node_name)
        result = harness.run(node, "nix flake --help >/dev/null 2>&1 && echo ok")
        checks.append(("flakes", "ok" in result.stdout))
        if "ok" in result.stdout:
            logger.debug("[%s] flakes: enabled", node_name)
        else:
            logger.warning("[%s] flakes not enabled", node_name)

    failed = [name for name, ok in checks if not ok]
    duration = time.time() - start

    if failed:
        logger.error(
            "[%s] Prerequisites check FAILED for %s: missing %s (%.2fs)",
            node_name,
            method.value,
            ", ".join(failed),
            duration,
        )
        return PrimitiveResult(
            success=False,
            name="check_prerequisites",
            node=node_name,
            duration=duration,
            error=f"Missing prerequisites: {', '.join(failed)}",
            data={"method": method.value, "checks": dict(checks)},
        )

    logger.info("[%s] Prerequisites check PASSED for %s (%.2fs)", node_name, method.value, duration)
    return PrimitiveResult(
        success=True,
        name="check_prerequisites",
        node=node_name,
        duration=duration,
        message=f"All prerequisites met for {method.value}",
        data={"method": method.value, "checks": dict(checks)},
    )


def install_via_pip_git(
    harness: SSHHarness,
    node: str | NodeInfo,
    repo_url: str = "https://github.com/styrene-lab/styrened.git",
    ref: str | None = None,
    venv_path: str | None = None,
    extras: list[str] | None = None,
) -> PrimitiveResult:
    """Install styrened via pip from git repository.

    Args:
        harness: SSH harness instance
        node: Target node
        repo_url: Git repository URL
        ref: Git ref (branch, tag, commit) - None for default branch
        venv_path: Path to virtualenv - None to use system pip
        extras: Package extras to install (e.g., ["dev"])

    Returns:
        PrimitiveResult indicating installation success
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    # Build pip URL
    pip_url = f"git+{repo_url}"
    if ref:
        pip_url += f"@{ref}"

    # Add extras
    if extras:
        pip_url += f"[{','.join(extras)}]"

    logger.info("[%s] Installing via pip from git: %s", node_name, pip_url)
    if venv_path:
        logger.debug("[%s] Using virtualenv: %s", node_name, venv_path)

    # Build install command
    if venv_path:
        cmd = f"source {venv_path}/bin/activate && pip install --upgrade '{pip_url}'"
    else:
        cmd = f"pip install --user --upgrade '{pip_url}'"

    logger.debug("[%s] Running: %s", node_name, cmd)
    result = harness.run(node, cmd, timeout=300)
    duration = time.time() - start

    if not result.success:
        # Log detailed error info
        logger.error(
            "[%s] pip install FAILED (exit=%d, %.2fs)", node_name, result.return_code, duration
        )
        logger.error("[%s] stderr:\n%s", node_name, _indent(result.stderr))
        if result.stdout:
            logger.debug("[%s] stdout:\n%s", node_name, _indent(result.stdout))

        return PrimitiveResult(
            success=False,
            name="install_pip_git",
            node=node_name,
            duration=duration,
            error=f"pip install failed: {result.stderr}",
            data={
                "pip_url": pip_url,
                "return_code": result.return_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )

    logger.debug("[%s] pip install completed, verifying...", node_name)

    # Verify installation
    verify_result = harness.run_styrened(node, "--version")

    if verify_result.success:
        version = verify_result.stdout.strip()
        logger.info("[%s] Installation SUCCEEDED: %s (%.2fs)", node_name, version, duration)
        return PrimitiveResult(
            success=True,
            name="install_pip_git",
            node=node_name,
            duration=duration,
            message=f"Installed: {version}",
            data={"pip_url": pip_url, "version": version},
        )
    else:
        logger.error("[%s] Install succeeded but verification FAILED (%.2fs)", node_name, duration)
        logger.error("[%s] verify stderr: %s", node_name, verify_result.stderr)
        return PrimitiveResult(
            success=False,
            name="install_pip_git",
            node=node_name,
            duration=duration,
            error="Install succeeded but verification failed",
            data={
                "pip_url": pip_url,
                "version": None,
                "verify_stderr": verify_result.stderr,
            },
        )


def install_via_pip_wheel(
    harness: SSHHarness,
    node: str | NodeInfo,
    wheel_path: Path,
    venv_path: str | None = None,
) -> PrimitiveResult:
    """Install styrened from a wheel file.

    Args:
        harness: SSH harness instance
        node: Target node
        wheel_path: Local path to wheel file (will be copied to node)
        venv_path: Path to virtualenv - None to use system pip

    Returns:
        PrimitiveResult indicating installation success
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.info("[%s] Installing from wheel: %s", node_name, wheel_path.name)
    logger.debug("[%s] Local wheel path: %s", node_name, wheel_path)
    if venv_path:
        logger.debug("[%s] Using virtualenv: %s", node_name, venv_path)

    # Deploy wheel using harness method
    logger.debug("[%s] Copying wheel to remote...", node_name)
    deploy_result = harness.deploy_wheel(node, wheel_path)

    if not deploy_result.success:
        duration = time.time() - start
        logger.error(
            "[%s] Wheel deployment FAILED (exit=%d, %.2fs)",
            node_name,
            deploy_result.return_code,
            duration,
        )
        logger.error("[%s] stderr:\n%s", node_name, _indent(deploy_result.stderr))
        return PrimitiveResult(
            success=False,
            name="install_pip_wheel",
            node=node_name,
            duration=duration,
            error=f"Wheel deployment failed: {deploy_result.stderr}",
            data={
                "wheel": wheel_path.name,
                "return_code": deploy_result.return_code,
                "stderr": deploy_result.stderr,
            },
        )

    logger.debug("[%s] Wheel deployed, verifying installation...", node_name)

    # Verify installation
    verify_result = harness.run_styrened(node, "--version")
    duration = time.time() - start

    if verify_result.success:
        version = verify_result.stdout.strip()
        logger.info("[%s] Installation SUCCEEDED: %s (%.2fs)", node_name, version, duration)
        return PrimitiveResult(
            success=True,
            name="install_pip_wheel",
            node=node_name,
            duration=duration,
            message=f"Installed: {version}",
            data={"wheel": wheel_path.name, "version": version},
        )
    else:
        logger.error("[%s] Install succeeded but verification FAILED (%.2fs)", node_name, duration)
        logger.error("[%s] verify stderr: %s", node_name, verify_result.stderr)
        return PrimitiveResult(
            success=False,
            name="install_pip_wheel",
            node=node_name,
            duration=duration,
            error="Install succeeded but verification failed",
            data={
                "wheel": wheel_path.name,
                "version": None,
                "verify_stderr": verify_result.stderr,
            },
        )


def install_via_nix_flake(
    harness: SSHHarness,
    node: str | NodeInfo,
    flake_ref: str = "github:styrene-lab/styrened",
    profile: str | None = None,
) -> PrimitiveResult:
    """Install styrened via Nix flake.

    Args:
        harness: SSH harness instance
        node: Target node
        flake_ref: Flake reference (e.g., "github:styrene-lab/styrened#default")
        profile: Nix profile name - None for default profile

    Returns:
        PrimitiveResult indicating installation success
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.info("[%s] Installing via nix flake: %s", node_name, flake_ref)
    if profile:
        logger.debug("[%s] Using profile: %s", node_name, profile)

    # Build install command
    cmd = f"nix profile install {flake_ref}"
    if profile:
        cmd += f" --profile {profile}"

    logger.debug("[%s] Running: %s", node_name, cmd)
    result = harness.run(node, cmd, timeout=600)
    duration = time.time() - start

    if not result.success:
        logger.error(
            "[%s] nix profile install FAILED (exit=%d, %.2fs)",
            node_name,
            result.return_code,
            duration,
        )
        logger.error("[%s] stderr:\n%s", node_name, _indent(result.stderr))
        if result.stdout:
            logger.debug("[%s] stdout:\n%s", node_name, _indent(result.stdout))

        return PrimitiveResult(
            success=False,
            name="install_nix_flake",
            node=node_name,
            duration=duration,
            error=f"nix profile install failed: {result.stderr}",
            data={
                "flake_ref": flake_ref,
                "return_code": result.return_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )

    logger.debug("[%s] nix install completed, verifying...", node_name)

    # Verify installation
    verify_result = harness.run(node, "styrened --version")

    if verify_result.success:
        version = verify_result.stdout.strip()
        logger.info("[%s] Installation SUCCEEDED: %s (%.2fs)", node_name, version, duration)
        return PrimitiveResult(
            success=True,
            name="install_nix_flake",
            node=node_name,
            duration=duration,
            message=f"Installed: {version}",
            data={"flake_ref": flake_ref, "version": version},
        )
    else:
        logger.error("[%s] Install succeeded but verification FAILED (%.2fs)", node_name, duration)
        logger.error("[%s] verify stderr: %s", node_name, verify_result.stderr)
        return PrimitiveResult(
            success=False,
            name="install_nix_flake",
            node=node_name,
            duration=duration,
            error="Install succeeded but verification failed",
            data={
                "flake_ref": flake_ref,
                "version": None,
                "verify_stderr": verify_result.stderr,
            },
        )


def setup_systemd_service(
    harness: SSHHarness,
    node: str | NodeInfo,
    user_service: bool = True,
    enable: bool = True,
    start: bool = True,
    exec_start: str | None = None,
) -> PrimitiveResult:
    """Set up systemd service for styrened.

    Args:
        harness: SSH harness instance
        node: Target node
        user_service: Use systemd user service (vs system service)
        enable: Enable service to start on boot
        start: Start service immediately
        exec_start: Custom ExecStart command (auto-detected if None)

    Returns:
        PrimitiveResult indicating setup success
    """
    start_time = time.time()
    node_name = node if isinstance(node, str) else node.name

    service_type = "user" if user_service else "system"
    logger.info(
        "[%s] Setting up systemd %s service (enable=%s, start=%s)",
        node_name,
        service_type,
        enable,
        start,
    )

    systemctl = "systemctl --user" if user_service else "sudo systemctl"

    # Determine ExecStart if not provided
    if exec_start is None:
        # Try to detect venv path from device config
        device_config = (
            harness.get_device_config(node_name) if hasattr(harness, "get_device_config") else None
        )
        if device_config and device_config.venv_path:
            exec_start = f"{device_config.venv_path}/bin/styrened daemon"
        elif user_service:
            exec_start = "%h/.local/styrene-venv/bin/styrened daemon"
        else:
            exec_start = "/usr/local/bin/styrened daemon"

    logger.debug("[%s] ExecStart: %s", node_name, exec_start)

    # Create service file content
    if user_service:
        service_dir = "~/.config/systemd/user"
        service_content = f"""[Unit]
Description=Styrened Mesh Daemon
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
Environment=STYRENE_LOG_LEVEL=INFO

[Install]
WantedBy=default.target
"""
    else:
        service_dir = "/etc/systemd/system"
        service_content = f"""[Unit]
Description=Styrened Mesh Daemon
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
User=styrene
Environment=STYRENE_LOG_LEVEL=INFO

[Install]
WantedBy=multi-user.target
"""

    steps_completed = []

    # Step 1: Create service directory
    logger.debug("[%s] Creating service directory: %s", node_name, service_dir)
    result = harness.run(node, f"mkdir -p {service_dir}")
    if not result.success:
        duration = time.time() - start_time
        logger.error("[%s] Failed to create service directory: %s", node_name, result.stderr)
        return PrimitiveResult(
            success=False,
            name="setup_systemd_service",
            node=node_name,
            duration=duration,
            error=f"Failed to create service directory: {result.stderr}",
            data={"steps_completed": steps_completed},
        )
    steps_completed.append("create_dir")

    # Step 2: Write service file
    logger.debug("[%s] Writing service file...", node_name)
    escaped_content = service_content.replace("'", "'\\''")
    result = harness.run(node, f"echo '{escaped_content}' > {service_dir}/styrened.service")
    if not result.success:
        duration = time.time() - start_time
        logger.error("[%s] Failed to write service file: %s", node_name, result.stderr)
        return PrimitiveResult(
            success=False,
            name="setup_systemd_service",
            node=node_name,
            duration=duration,
            error=f"Failed to write service file: {result.stderr}",
            data={"steps_completed": steps_completed},
        )
    steps_completed.append("write_service")

    # Step 3: Reload systemd
    logger.debug("[%s] Reloading systemd daemon...", node_name)
    result = harness.run(node, f"{systemctl} daemon-reload")
    if not result.success:
        duration = time.time() - start_time
        logger.error("[%s] Failed to reload systemd: %s", node_name, result.stderr)
        return PrimitiveResult(
            success=False,
            name="setup_systemd_service",
            node=node_name,
            duration=duration,
            error=f"Failed to reload systemd: {result.stderr}",
            data={"steps_completed": steps_completed},
        )
    steps_completed.append("daemon_reload")

    # Step 4: Enable if requested
    if enable:
        logger.debug("[%s] Enabling service...", node_name)
        result = harness.run(node, f"{systemctl} enable styrened.service")
        if not result.success:
            duration = time.time() - start_time
            logger.error("[%s] Failed to enable service: %s", node_name, result.stderr)
            return PrimitiveResult(
                success=False,
                name="setup_systemd_service",
                node=node_name,
                duration=duration,
                error=f"Failed to enable service: {result.stderr}",
                data={"steps_completed": steps_completed},
            )
        steps_completed.append("enable")

    # Step 5: Start if requested
    if start:
        logger.debug("[%s] Starting service...", node_name)
        result = harness.run(node, f"{systemctl} start styrened.service")
        if not result.success:
            duration = time.time() - start_time
            logger.error("[%s] Failed to start service: %s", node_name, result.stderr)
            # Get journal logs for debugging
            journal_result = harness.run(
                node,
                f"{systemctl.replace('systemctl', 'journalctl')} -u styrened.service -n 50 --no-pager",
            )
            logger.error("[%s] Journal logs:\n%s", node_name, _indent(journal_result.stdout))
            return PrimitiveResult(
                success=False,
                name="setup_systemd_service",
                node=node_name,
                duration=duration,
                error=f"Failed to start service: {result.stderr}",
                data={
                    "steps_completed": steps_completed,
                    "journal": journal_result.stdout,
                },
            )
        steps_completed.append("start")

        # Wait for service to be active
        logger.debug("[%s] Waiting for service to become active...", node_name)
        time.sleep(2)
        result = harness.run(node, f"{systemctl} is-active styrened.service")
        is_active = result.stdout.strip() == "active"

        if not is_active:
            duration = time.time() - start_time
            status = result.stdout.strip()
            logger.error("[%s] Service not active after start: %s", node_name, status)

            # Get service status and journal for debugging
            status_result = harness.run(node, f"{systemctl} status styrened.service")
            journal_result = harness.run(
                node,
                f"{systemctl.replace('systemctl', 'journalctl')} -u styrened.service -n 50 --no-pager",
            )
            logger.error("[%s] Service status:\n%s", node_name, _indent(status_result.stdout))
            logger.error("[%s] Journal logs:\n%s", node_name, _indent(journal_result.stdout))

            return PrimitiveResult(
                success=False,
                name="setup_systemd_service",
                node=node_name,
                duration=duration,
                error=f"Service not active after start: {status}",
                data={
                    "steps_completed": steps_completed,
                    "status": status_result.stdout,
                    "journal": journal_result.stdout,
                },
            )
        steps_completed.append("verify_active")

    duration = time.time() - start_time
    logger.info(
        "[%s] Systemd service setup SUCCEEDED (%.2fs): %s",
        node_name,
        duration,
        ", ".join(steps_completed),
    )

    return PrimitiveResult(
        success=True,
        name="setup_systemd_service",
        node=node_name,
        duration=duration,
        message=f"Service configured ({service_type}, enabled={enable}, started={start})",
        data={
            "user_service": user_service,
            "enabled": enable,
            "started": start,
            "steps_completed": steps_completed,
            "exec_start": exec_start,
        },
    )


def uninstall_styrened(
    harness: SSHHarness,
    node: str | NodeInfo,
    method: InstallMethod,
    venv_path: str | None = None,
    stop_service: bool = True,
    remove_service: bool = True,
) -> PrimitiveResult:
    """Uninstall styrened from a node.

    Args:
        harness: SSH harness instance
        node: Target node
        method: Installation method used
        venv_path: Path to virtualenv (for pip methods)
        stop_service: Stop systemd service before uninstall
        remove_service: Remove systemd service files

    Returns:
        PrimitiveResult indicating uninstall success
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.info("[%s] Uninstalling styrened (method=%s)", node_name, method.value)

    steps_completed = []

    # Stop services if requested
    if stop_service:
        logger.debug("[%s] Stopping systemd services...", node_name)
        harness.run(node, "systemctl --user stop styrened.service 2>/dev/null || true")
        harness.run(node, "sudo systemctl stop styrened.service 2>/dev/null || true")
        steps_completed.append("stop_service")

    # Remove service files if requested
    if remove_service:
        logger.debug("[%s] Removing systemd service files...", node_name)
        harness.run(node, "systemctl --user disable styrened.service 2>/dev/null || true")
        harness.run(node, "rm -f ~/.config/systemd/user/styrened.service 2>/dev/null || true")
        harness.run(node, "systemctl --user daemon-reload 2>/dev/null || true")
        harness.run(node, "sudo systemctl disable styrened.service 2>/dev/null || true")
        harness.run(node, "sudo rm -f /etc/systemd/system/styrened.service 2>/dev/null || true")
        harness.run(node, "sudo systemctl daemon-reload 2>/dev/null || true")
        steps_completed.append("remove_service")

    # Uninstall based on method
    if method == InstallMethod.PIP_GIT or method == InstallMethod.PIP_WHEEL:
        logger.debug("[%s] Uninstalling via pip...", node_name)
        if venv_path:
            cmd = f"source {venv_path}/bin/activate && pip uninstall -y styrened"
        else:
            cmd = "pip uninstall -y styrened"
        result = harness.run(node, cmd)
        if result.success:
            steps_completed.append("pip_uninstall")
        else:
            logger.warning("[%s] pip uninstall returned error: %s", node_name, result.stderr)

    elif method == InstallMethod.NIX_FLAKE:
        logger.debug("[%s] Uninstalling via nix...", node_name)
        result = harness.run(node, "nix profile remove styrened 2>/dev/null || true")
        steps_completed.append("nix_uninstall")

    else:
        logger.warning("[%s] Unknown uninstall method: %s", node_name, method.value)

    duration = time.time() - start

    # Verify removal
    logger.debug("[%s] Verifying removal...", node_name)
    verify_result = harness.run(node, "which styrened 2>/dev/null || echo 'not found'")
    removed = "not found" in verify_result.stdout

    if removed:
        logger.info(
            "[%s] Uninstall SUCCEEDED (%.2fs): %s", node_name, duration, ", ".join(steps_completed)
        )
    else:
        logger.warning(
            "[%s] Uninstall completed but styrened still found at: %s",
            node_name,
            verify_result.stdout.strip(),
        )

    return PrimitiveResult(
        success=removed,
        name="uninstall_styrened",
        node=node_name,
        duration=duration,
        message="Uninstalled successfully" if removed else "Uninstall may have failed",
        data={
            "method": method.value,
            "removed": removed,
            "steps_completed": steps_completed,
        },
    )


def _indent(text: str, prefix: str = "    ") -> str:
    """Indent multiline text for logging."""
    if not text:
        return "(empty)"
    lines = text.strip().split("\n")
    return "\n".join(f"{prefix}{line}" for line in lines)
