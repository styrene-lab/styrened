"""SSH-based test harness for bare-metal devices."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .base import CommandResult, ExecutionBackend, NodeInfo, TestHarness


@dataclass
class SSHDeviceConfig:
    """Device configuration from registry YAML."""

    name: str
    host: str
    hardware: str
    cpu: str
    arch: str
    os: str
    venv_path: str
    config_path: str
    identity_hash: str
    capabilities: list[str] = field(default_factory=list)


class SSHHarness(TestHarness):
    """SSH-based test harness for bare-metal devices.

    Uses subprocess + ssh for simplicity and compatibility.
    SSH config (~/.ssh/config) handles user/key selection.
    """

    def __init__(
        self,
        devices_file: Path | None = None,
        ssh_timeout: float = 10.0,
    ):
        """Initialize SSH harness.

        Args:
            devices_file: Path to devices.yaml registry.
                         Defaults to tests/bare-metal/devices.yaml
            ssh_timeout: SSH connection timeout in seconds
        """
        self.ssh_timeout = ssh_timeout
        self._devices: dict[str, SSHDeviceConfig] = {}
        self._nodes: dict[str, NodeInfo] = {}

        if devices_file is None:
            devices_file = Path(__file__).parent.parent / "bare-metal" / "devices.yaml"

        self._load_devices(devices_file)

    def _load_devices(self, devices_file: Path) -> None:
        """Load device registry from YAML."""
        with open(devices_file) as f:
            data = yaml.safe_load(f)

        for name, info in data.get("devices", {}).items():
            self._devices[name] = SSHDeviceConfig(name=name, **info)
            self._nodes[name] = NodeInfo(
                name=name,
                address=info["host"],
                identity_hash=info.get("identity_hash"),
                backend=ExecutionBackend.SSH,
                capabilities=info.get("capabilities", []),
                metadata={
                    "hardware": info.get("hardware"),
                    "cpu": info.get("cpu"),
                    "arch": info.get("arch"),
                    "os": info.get("os"),
                    "venv_path": info.get("venv_path"),
                    "config_path": info.get("config_path"),
                },
            )

    @property
    def backend(self) -> ExecutionBackend:
        return ExecutionBackend.SSH

    def get_nodes(self) -> list[NodeInfo]:
        return list(self._nodes.values())

    def get_device_config(self, name: str) -> SSHDeviceConfig | None:
        """Get raw device config by name."""
        return self._devices.get(name)

    def _resolve_node(self, node: str | NodeInfo) -> tuple[NodeInfo, SSHDeviceConfig | None]:
        """Resolve node identifier to NodeInfo and optional device config."""
        if isinstance(node, NodeInfo):
            return node, self._devices.get(node.name)
        if node in self._nodes:
            return self._nodes[node], self._devices.get(node)
        # Assume it's a hostname - create ephemeral NodeInfo
        return (
            NodeInfo(
                name=node,
                address=node,
                identity_hash=None,
                backend=ExecutionBackend.SSH,
            ),
            None,
        )

    def run(
        self,
        node: str | NodeInfo,
        command: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Execute command via SSH."""
        node_info, _ = self._resolve_node(node)
        start = time.time()

        ssh_cmd = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={int(self.ssh_timeout)}",
            node_info.address,
            command,
        ]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start

            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                duration=duration,
                backend=ExecutionBackend.SSH,
                target=node_info.name,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                return_code=-1,
                duration=time.time() - start,
                backend=ExecutionBackend.SSH,
                target=node_info.name,
            )
        except Exception as e:
            return CommandResult(
                success=False,
                stdout="",
                stderr=str(e),
                return_code=-1,
                duration=time.time() - start,
                backend=ExecutionBackend.SSH,
                target=node_info.name,
            )

    def run_styrened(
        self,
        node: str | NodeInfo,
        subcommand: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Execute styrened CLI command in device's venv."""
        node_info, device_config = self._resolve_node(node)

        # If we have device config, activate venv first
        if device_config and device_config.venv_path:
            command = f"source {device_config.venv_path}/bin/activate && styrened {subcommand}"
        else:
            command = f"styrened {subcommand}"

        return self.run(node_info, command, timeout)

    def start_daemon(self, node: str | NodeInfo) -> CommandResult:
        """Start daemon via systemd (user or system)."""
        node_info, device_config = self._resolve_node(node)

        # Check capabilities to determine systemd mode
        use_user_systemd = device_config and "systemd_user" in device_config.capabilities

        if use_user_systemd:
            return self.run(node_info, "systemctl --user start styrened")
        else:
            return self.run(node_info, "sudo systemctl start styrened")

    def stop_daemon(self, node: str | NodeInfo) -> CommandResult:
        """Stop daemon via systemd."""
        node_info, device_config = self._resolve_node(node)

        use_user_systemd = device_config and "systemd_user" in device_config.capabilities

        if use_user_systemd:
            return self.run(node_info, "systemctl --user stop styrened")
        else:
            return self.run(node_info, "sudo systemctl stop styrened")

    def restart_daemon(self, node: str | NodeInfo) -> CommandResult:
        """Restart daemon via systemd."""
        node_info, device_config = self._resolve_node(node)

        use_user_systemd = device_config and "systemd_user" in device_config.capabilities

        if use_user_systemd:
            return self.run(node_info, "systemctl --user restart styrened")
        else:
            return self.run(node_info, "sudo systemctl restart styrened")

    def is_daemon_running(self, node: str | NodeInfo) -> bool:
        """Check if daemon is running on node.

        Checks both systemd service status and process existence,
        since daemon may be running via nohup or systemd.
        """
        node_info, device_config = self._resolve_node(node)

        # First check for running process (works for both systemd and nohup)
        result = self.run(node_info, "pgrep -f 'styrened daemon' >/dev/null && echo running")
        if result.stdout.strip() == "running":
            return True

        # Fall back to systemd check
        use_user_systemd = device_config and "systemd_user" in device_config.capabilities

        if use_user_systemd:
            result = self.run(node_info, "systemctl --user is-active styrened")
        else:
            result = self.run(node_info, "systemctl is-active styrened")

        return result.stdout.strip() == "active"

    def get_identity(self, node: str | NodeInfo) -> str | None:
        """Get LXMF identity hash for node."""
        result = self.run_styrened(node, "identity --json")
        if result.success:
            try:
                data = json.loads(result.stdout)
                # Handle various possible formats
                if isinstance(data, dict):
                    return data.get("identity_hash") or data.get("hash")
                return None
            except json.JSONDecodeError:
                # Try to parse non-JSON format
                for line in result.stdout.splitlines():
                    if ":" in line:
                        return line.split(":")[-1].strip()
        return None

    def discover_devices(
        self,
        node: str | NodeInfo,
        wait_seconds: int = 10,
    ) -> list[dict[str, Any]]:
        """Discover mesh devices from node's perspective."""
        result = self.run_styrened(
            node,
            f"devices -w {wait_seconds} --json",
            timeout=wait_seconds + 30,
        )
        if result.success and result.stdout.strip():
            # The output format is:
            #   Discovered X device(s):
            #
            #   [JSON array]
            # We need to extract just the JSON portion
            stdout = result.stdout
            try:
                # Find the start of the JSON array
                json_start = stdout.find("[")
                if json_start != -1:
                    return json.loads(stdout[json_start:])
                return []
            except json.JSONDecodeError:
                return []
        return []

    def wait_for_daemon(
        self,
        node: str | NodeInfo,
        timeout: float = 30.0,
        poll_interval: float = 2.0,
    ) -> bool:
        """Wait for daemon to become responsive.

        Args:
            node: Node to check
            timeout: Max seconds to wait
            poll_interval: Seconds between checks

        Returns:
            True if daemon is responsive, False if timeout
        """
        start = time.time()
        while time.time() - start < timeout:
            result = self.run_styrened(node, "devices", timeout=10)
            if result.success:
                return True
            time.sleep(poll_interval)
        return False

    def deploy_wheel(
        self,
        node: str | NodeInfo,
        wheel_path: Path,
    ) -> CommandResult:
        """Deploy wheel to device and install in venv.

        Args:
            node: Target node
            wheel_path: Local path to wheel file

        Returns:
            CommandResult indicating success/failure
        """
        node_info, device_config = self._resolve_node(node)
        start = time.time()

        # Transfer wheel via scp
        remote_path = f"/tmp/{wheel_path.name}"
        scp_result = subprocess.run(
            ["scp", str(wheel_path), f"{node_info.address}:{remote_path}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if scp_result.returncode != 0:
            return CommandResult(
                success=False,
                stdout=scp_result.stdout,
                stderr=scp_result.stderr,
                return_code=scp_result.returncode,
                duration=time.time() - start,
                backend=ExecutionBackend.SSH,
                target=node_info.name,
            )

        # Install in venv
        if device_config and device_config.venv_path:
            install_cmd = f"source {device_config.venv_path}/bin/activate && pip install --upgrade {remote_path}"
        else:
            install_cmd = f"pip install --upgrade {remote_path}"

        return self.run(node_info, install_cmd, timeout=120)

    def get_device_info(self, node: str | NodeInfo) -> dict[str, Any]:
        """Get comprehensive device info.

        Returns dict with hostname, os, kernel, arch, memory, etc.
        """
        result = self.run(
            node,
            "hostname; uname -r; uname -m; free -h | head -2; df -h / | tail -1",
        )
        if not result.success:
            return {"error": result.stderr}

        lines = result.stdout.strip().split("\n")
        return {
            "hostname": lines[0] if len(lines) > 0 else "unknown",
            "kernel": lines[1] if len(lines) > 1 else "unknown",
            "arch": lines[2] if len(lines) > 2 else "unknown",
            "memory_info": lines[3:5] if len(lines) > 4 else [],
            "disk_info": lines[5] if len(lines) > 5 else "unknown",
        }


# Backward compatibility: alias for existing tests
BareMetalHarness = SSHHarness
