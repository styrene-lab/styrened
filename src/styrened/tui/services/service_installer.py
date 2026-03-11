"""Platform-aware service installer for styrened.

Handles installing styrened as a system service (launchd on macOS,
systemd on Linux) so it persists across reboots. Pure logic module —
no TUI dependencies, easily unit-testable.

Supports:
    - macOS: LaunchAgent plist in ~/Library/LaunchAgents/
    - Linux: systemd user unit in ~/.config/systemd/user/
"""

import asyncio
import logging
import shutil
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# Service identifiers
LAUNCHD_LABEL = "com.styrene.styrened"
LAUNCHD_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"

SYSTEMD_UNIT_NAME = "styrened.service"
SYSTEMD_UNIT_PATH = (
    Path.home() / ".config" / "systemd" / "user" / SYSTEMD_UNIT_NAME
)

# Log locations for launchd
LAUNCHD_LOG_DIR = Path.home() / "Library" / "Logs" / "styrened"


class ServicePlatform(Enum):
    """Supported service platforms."""

    LAUNCHD = "launchd"
    SYSTEMD = "systemd"
    UNSUPPORTED = "unsupported"


class ServiceStatus(Enum):
    """Current state of the installed service."""

    NOT_INSTALLED = "not_installed"
    INSTALLED_STOPPED = "installed_stopped"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class ServiceInfo:
    """Information about the installed service."""

    platform: ServicePlatform
    status: ServiceStatus
    unit_path: Path | None = None
    error: str | None = None
    pid: int | None = None
    extra: dict = field(default_factory=dict)


def detect_platform() -> ServicePlatform:
    """Detect the service platform for the current OS.

    Returns:
        ServicePlatform enum value.
    """
    if sys.platform == "darwin":
        return ServicePlatform.LAUNCHD
    if sys.platform == "linux":
        # Check if systemd is available
        if shutil.which("systemctl") is not None:
            return ServicePlatform.SYSTEMD
    return ServicePlatform.UNSUPPORTED


def get_styrened_executable() -> Path | None:
    """Find the styrened executable.

    Checks:
        1. shutil.which('styrened') — on PATH
        2. Sibling of sys.executable (venv bin/)

    Returns:
        Path to styrened, or None if not found.
    """
    # Try PATH first
    which_result = shutil.which("styrened")
    if which_result is not None:
        return Path(which_result)

    # Try sibling of current Python (e.g. venv bin/)
    bin_dir = Path(sys.executable).parent
    candidate = bin_dir / "styrened"
    if candidate.exists():
        return candidate

    return None


def generate_launchd_plist(styrened_path: Path) -> str:
    """Generate a launchd plist XML string for styrened.

    Args:
        styrened_path: Absolute path to the styrened executable.

    Returns:
        Valid plist XML string.
    """
    log_dir = LAUNCHD_LOG_DIR
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{styrened_path}</string>
        <string>daemon</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir / "stdout.log"}</string>
    <key>StandardErrorPath</key>
    <string>{log_dir / "stderr.log"}</string>
</dict>
</plist>
"""


def generate_systemd_unit(styrened_path: Path) -> str:
    """Generate a systemd user unit file for styrened.

    Args:
        styrened_path: Absolute path to the styrened executable.

    Returns:
        Unit file content string.
    """
    return f"""\
[Unit]
Description=Styrene Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={styrened_path} daemon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


async def get_service_status() -> ServiceInfo:
    """Check the current status of the styrened service.

    Returns:
        ServiceInfo with platform, status, and metadata.
    """
    platform = detect_platform()

    if platform == ServicePlatform.LAUNCHD:
        return await _get_launchd_status()
    elif platform == ServicePlatform.SYSTEMD:
        return await _get_systemd_status()
    else:
        return ServiceInfo(
            platform=ServicePlatform.UNSUPPORTED,
            status=ServiceStatus.NOT_INSTALLED,
        )


async def _get_launchd_status() -> ServiceInfo:
    """Check launchd service status."""
    if not LAUNCHD_PLIST_PATH.exists():
        return ServiceInfo(
            platform=ServicePlatform.LAUNCHD,
            status=ServiceStatus.NOT_INSTALLED,
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "list", LAUNCHD_LABEL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return ServiceInfo(
                platform=ServicePlatform.LAUNCHD,
                status=ServiceStatus.INSTALLED_STOPPED,
                unit_path=LAUNCHD_PLIST_PATH,
            )

        # Parse PID from launchctl list output
        output = stdout.decode("utf-8", errors="replace")
        pid = None
        for line in output.splitlines():
            if '"PID"' in line or "PID" in line:
                # Try to extract numeric PID
                parts = line.strip().rstrip(";").split()
                for part in parts:
                    part = part.rstrip(";")
                    if part.isdigit():
                        pid = int(part)
                        break

        return ServiceInfo(
            platform=ServicePlatform.LAUNCHD,
            status=ServiceStatus.RUNNING,
            unit_path=LAUNCHD_PLIST_PATH,
            pid=pid,
        )
    except Exception as e:
        return ServiceInfo(
            platform=ServicePlatform.LAUNCHD,
            status=ServiceStatus.ERROR,
            unit_path=LAUNCHD_PLIST_PATH,
            error=str(e),
        )


async def _get_systemd_status() -> ServiceInfo:
    """Check systemd user service status."""
    if not SYSTEMD_UNIT_PATH.exists():
        return ServiceInfo(
            platform=ServicePlatform.SYSTEMD,
            status=ServiceStatus.NOT_INSTALLED,
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "is-active", SYSTEMD_UNIT_NAME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        state = stdout.decode("utf-8").strip()

        if state == "active":
            return ServiceInfo(
                platform=ServicePlatform.SYSTEMD,
                status=ServiceStatus.RUNNING,
                unit_path=SYSTEMD_UNIT_PATH,
            )
        else:
            return ServiceInfo(
                platform=ServicePlatform.SYSTEMD,
                status=ServiceStatus.INSTALLED_STOPPED,
                unit_path=SYSTEMD_UNIT_PATH,
            )
    except Exception as e:
        return ServiceInfo(
            platform=ServicePlatform.SYSTEMD,
            status=ServiceStatus.ERROR,
            unit_path=SYSTEMD_UNIT_PATH,
            error=str(e),
        )


async def install_service() -> ServiceInfo:
    """Install styrened as a system service.

    Writes the appropriate service file and loads/enables it.

    Returns:
        ServiceInfo reflecting the post-install state.
    """
    platform = detect_platform()
    styrened_path = get_styrened_executable()

    if styrened_path is None:
        return ServiceInfo(
            platform=platform,
            status=ServiceStatus.ERROR,
            error="styrened executable not found",
        )

    if platform == ServicePlatform.LAUNCHD:
        return await _install_launchd(styrened_path)
    elif platform == ServicePlatform.SYSTEMD:
        return await _install_systemd(styrened_path)
    else:
        return ServiceInfo(
            platform=ServicePlatform.UNSUPPORTED,
            status=ServiceStatus.ERROR,
            error="Unsupported platform for service installation",
        )


async def _install_launchd(styrened_path: Path) -> ServiceInfo:
    """Install as launchd LaunchAgent."""
    try:
        # Ensure directories exist
        LAUNCHD_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAUNCHD_LOG_DIR.mkdir(parents=True, exist_ok=True)

        # Write plist
        plist_content = generate_launchd_plist(styrened_path)
        LAUNCHD_PLIST_PATH.write_text(plist_content)
        logger.info(f"Wrote plist to {LAUNCHD_PLIST_PATH}")

        # Load the service
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "load", str(LAUNCHD_PLIST_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            return ServiceInfo(
                platform=ServicePlatform.LAUNCHD,
                status=ServiceStatus.ERROR,
                unit_path=LAUNCHD_PLIST_PATH,
                error=f"launchctl load failed: {error_msg}",
            )

        logger.info("styrened service loaded via launchctl")
        return await _get_launchd_status()

    except Exception as e:
        return ServiceInfo(
            platform=ServicePlatform.LAUNCHD,
            status=ServiceStatus.ERROR,
            unit_path=LAUNCHD_PLIST_PATH,
            error=str(e),
        )


async def _install_systemd(styrened_path: Path) -> ServiceInfo:
    """Install as systemd user service."""
    try:
        # Ensure directory exists
        SYSTEMD_UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Write unit file
        unit_content = generate_systemd_unit(styrened_path)
        SYSTEMD_UNIT_PATH.write_text(unit_content)
        logger.info(f"Wrote unit file to {SYSTEMD_UNIT_PATH}")

        # Reload systemd
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "daemon-reload",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Enable and start
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "enable", "--now", SYSTEMD_UNIT_NAME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            return ServiceInfo(
                platform=ServicePlatform.SYSTEMD,
                status=ServiceStatus.ERROR,
                unit_path=SYSTEMD_UNIT_PATH,
                error=f"systemctl enable --now failed: {error_msg}",
            )

        logger.info("styrened service enabled and started via systemctl")
        return await _get_systemd_status()

    except Exception as e:
        return ServiceInfo(
            platform=ServicePlatform.SYSTEMD,
            status=ServiceStatus.ERROR,
            unit_path=SYSTEMD_UNIT_PATH,
            error=str(e),
        )


async def start_service() -> ServiceInfo:
    """Start the installed service (if stopped).

    Returns:
        ServiceInfo reflecting the post-start state.
    """
    platform = detect_platform()

    if platform == ServicePlatform.LAUNCHD:
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "start", LAUNCHD_LABEL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return await _get_launchd_status()

    elif platform == ServicePlatform.SYSTEMD:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "start", SYSTEMD_UNIT_NAME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return await _get_systemd_status()

    return ServiceInfo(
        platform=ServicePlatform.UNSUPPORTED,
        status=ServiceStatus.ERROR,
        error="Unsupported platform",
    )


async def stop_service() -> ServiceInfo:
    """Stop the running service.

    Returns:
        ServiceInfo reflecting the post-stop state.
    """
    platform = detect_platform()

    if platform == ServicePlatform.LAUNCHD:
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "stop", LAUNCHD_LABEL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return await _get_launchd_status()

    elif platform == ServicePlatform.SYSTEMD:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "stop", SYSTEMD_UNIT_NAME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return await _get_systemd_status()

    return ServiceInfo(
        platform=ServicePlatform.UNSUPPORTED,
        status=ServiceStatus.ERROR,
        error="Unsupported platform",
    )


async def restart_service() -> ServiceInfo:
    """Restart the installed service (stop then start).

    For launchd: unload + load (re-reads plist, picks up new binary).
    For systemd: systemctl --user restart.

    Returns:
        ServiceInfo reflecting the post-restart state.
    """
    platform = detect_platform()

    if platform == ServicePlatform.LAUNCHD:
        if not LAUNCHD_PLIST_PATH.exists():
            return ServiceInfo(
                platform=ServicePlatform.LAUNCHD,
                status=ServiceStatus.NOT_INSTALLED,
                error="Service not installed",
            )
        # unload then load so launchd re-reads the plist and picks up any new binary path
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "unload", str(LAUNCHD_PLIST_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        await asyncio.sleep(0.5)
        proc = await asyncio.create_subprocess_exec(
            "launchctl", "load", str(LAUNCHD_PLIST_PATH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            return ServiceInfo(
                platform=ServicePlatform.LAUNCHD,
                status=ServiceStatus.ERROR,
                unit_path=LAUNCHD_PLIST_PATH,
                error=f"launchctl load failed: {error_msg}",
            )
        return await _get_launchd_status()

    elif platform == ServicePlatform.SYSTEMD:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "restart", SYSTEMD_UNIT_NAME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace").strip()
            return ServiceInfo(
                platform=ServicePlatform.SYSTEMD,
                status=ServiceStatus.ERROR,
                unit_path=SYSTEMD_UNIT_PATH,
                error=f"systemctl restart failed: {error_msg}",
            )
        return await _get_systemd_status()

    return ServiceInfo(
        platform=ServicePlatform.UNSUPPORTED,
        status=ServiceStatus.ERROR,
        error="Unsupported platform",
    )


async def uninstall_service() -> ServiceInfo:
    """Uninstall the service (stop, unload/disable, remove unit file).

    Returns:
        ServiceInfo reflecting the post-uninstall state.
    """
    platform = detect_platform()

    if platform == ServicePlatform.LAUNCHD:
        return await _uninstall_launchd()
    elif platform == ServicePlatform.SYSTEMD:
        return await _uninstall_systemd()

    return ServiceInfo(
        platform=ServicePlatform.UNSUPPORTED,
        status=ServiceStatus.ERROR,
        error="Unsupported platform",
    )


async def _uninstall_launchd() -> ServiceInfo:
    """Uninstall launchd service."""
    try:
        # Unload (stops if running)
        if LAUNCHD_PLIST_PATH.exists():
            proc = await asyncio.create_subprocess_exec(
                "launchctl", "unload", str(LAUNCHD_PLIST_PATH),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            # Remove plist
            LAUNCHD_PLIST_PATH.unlink()
            logger.info(f"Removed {LAUNCHD_PLIST_PATH}")

        return ServiceInfo(
            platform=ServicePlatform.LAUNCHD,
            status=ServiceStatus.NOT_INSTALLED,
        )
    except Exception as e:
        return ServiceInfo(
            platform=ServicePlatform.LAUNCHD,
            status=ServiceStatus.ERROR,
            error=str(e),
        )


async def _uninstall_systemd() -> ServiceInfo:
    """Uninstall systemd service."""
    try:
        # Disable and stop
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "disable", "--now", SYSTEMD_UNIT_NAME,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        # Remove unit file
        if SYSTEMD_UNIT_PATH.exists():
            SYSTEMD_UNIT_PATH.unlink()
            logger.info(f"Removed {SYSTEMD_UNIT_PATH}")

        # Reload daemon
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "--user", "daemon-reload",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

        return ServiceInfo(
            platform=ServicePlatform.SYSTEMD,
            status=ServiceStatus.NOT_INSTALLED,
        )
    except Exception as e:
        return ServiceInfo(
            platform=ServicePlatform.SYSTEMD,
            status=ServiceStatus.ERROR,
            error=str(e),
        )
