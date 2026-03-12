"""In-process daemon harness for operator interface testing.

Starts a `styrened` daemon as a subprocess with a temp config directory,
fixture identity key, and transport overlay config. Provides deterministic
identity hashes for test assertions and RBAC role assignments.

Usage:
    harness = DaemonHarness.from_fixture("alpha")
    await harness.start()
    print(harness.port)       # dynamically allocated TCP port
    print(harness.identity_hash)  # from fixture README
    ...
    await harness.stop()
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "test_peers"
TRANSPORTS_DIR = Path(__file__).parent.parent / "fixtures" / "transports"


def _find_free_port() -> int:
    """Bind to port 0 and return the OS-assigned port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge overlay into base (overlay wins)."""
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class DaemonHarness:
    """Manages a styrened daemon subprocess for integration testing.

    Attributes:
        name: Fixture name (host, alpha, bravo).
        port: Dynamically allocated TCP server port.
        identity_hash: RNS identity hash from fixture.
        lxmf_dest_hash: LXMF destination hash from fixture.
        config_dir: Temporary directory with merged config.
        process: The subprocess.Popen handle (after start).
    """

    def __init__(
        self,
        name: str,
        *,
        transport: str = "tcp_localhost",
        extra_config: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.transport = transport
        self.extra_config = extra_config or {}

        self.port: int = 0
        self.identity_hash: str = ""
        self.lxmf_dest_hash: str = ""
        self.config_dir: Path | None = None
        self.socket_path: Path | None = None
        self.process: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._temp_dir: str | None = None

        # Load fixture metadata
        self._fixture_dir = FIXTURES_DIR / name
        if not self._fixture_dir.exists():
            msg = f"Fixture directory not found: {self._fixture_dir}"
            raise FileNotFoundError(msg)

        self._load_fixture_metadata()

    def _load_fixture_metadata(self) -> None:
        """Parse identity_hash and lxmf_dest_hash from fixture README."""
        readme = self._fixture_dir / "README.md"
        if not readme.exists():
            msg = f"README.md not found in fixture: {self._fixture_dir}"
            raise FileNotFoundError(msg)

        text = readme.read_text()
        for line in text.splitlines():
            if "identity_hash" in line and "`" in line:
                self.identity_hash = line.split("`")[1]
            elif "lxmf_dest_hash" in line and "`" in line:
                self.lxmf_dest_hash = line.split("`")[1]

        if not self.identity_hash:
            msg = f"Could not parse identity_hash from {readme}"
            raise ValueError(msg)

    def _prepare_config_dir(self) -> Path:
        """Create temp dir with fixture identity + merged config."""
        self._temp_dir = tempfile.mkdtemp(prefix=f"styrened-test-{self.name}-")
        config_dir = Path(self._temp_dir)

        # Copy identity key
        shutil.copy2(self._fixture_dir / "identity", config_dir / "identity")

        # Load base config (fixture uses core-config.yaml, daemon reads config.yaml)
        base_config_path = self._fixture_dir / "core-config.yaml"
        if not base_config_path.exists():
            base_config_path = self._fixture_dir / "config.yaml"
        with open(base_config_path) as f:
            config = yaml.safe_load(f)

        # Load and merge transport overlay
        transport_path = TRANSPORTS_DIR / f"{self.transport}.yaml"
        if transport_path.exists():
            with open(transport_path) as f:
                transport_config = yaml.safe_load(f) or {}
            config = _deep_merge(config, transport_config)

        # Merge extra config
        if self.extra_config:
            config = _deep_merge(config, self.extra_config)

        # Allocate dynamic port and inject
        self.port = _find_free_port()
        if "reticulum" in config and "interfaces" in config["reticulum"]:
            ifaces = config["reticulum"]["interfaces"]
            if "server" in ifaces:
                ifaces["server"]["port"] = self.port

        # Set identity path to the temp dir's copy
        config.setdefault("reticulum", {})
        config["reticulum"]["operator_identity_path"] = str(config_dir / "identity")

        # Set IPC socket path inside temp dir
        self.socket_path = config_dir / "control.sock"

        # Generate RNS config so the daemon doesn't need to search for one.
        # This ensures the TCP server interface starts on our dynamic port.
        rns_dir = config_dir / ".reticulum"
        rns_dir.mkdir()
        rns_config = self._generate_rns_config(config)
        (rns_dir / "config").write_text(rns_config)

        # Point the daemon's config to use this RNS config dir
        # (must be set BEFORE writing config.yaml)
        config.setdefault("reticulum", {})
        config["reticulum"]["config_path_override"] = str(rns_dir)

        # Write migration marker to prevent copying real user data (nodes.db etc.)
        (config_dir / ".paths-migrated").write_text("test-harness\n")

        # Write merged config (daemon reads config.yaml from config_dir)
        config_path = config_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False)

        logger.info(
            f"[{self.name}] Config dir: {config_dir}, port: {self.port}, "
            f"identity: {self.identity_hash[:12]}..."
        )

        return config_dir

    @staticmethod
    def _generate_rns_config(config: dict[str, Any]) -> str:
        """Generate a minimal RNS config INI from the merged config dict."""
        lines = ["[reticulum]", "enable_transport = false", "share_instance = false", ""]
        lines.append("[interfaces]")
        lines.append("")

        ifaces = config.get("reticulum", {}).get("interfaces", {})

        # TCP server
        server = ifaces.get("server", {})
        if server.get("enabled", False):
            lines.append("[[TCP Server Interface]]")
            lines.append("type = TCPServerInterface")
            lines.append("enabled = true")
            lines.append(f"listen_ip = {server.get('listen_ip', '127.0.0.1')}")
            lines.append(f"listen_port = {server.get('port', 4242)}")
            lines.append("")

        # TCP client peers
        for i, peer in enumerate(ifaces.get("peers", [])):
            if not peer.get("enabled", True):
                continue
            name = peer.get("name", f"Peer {i + 1}")
            lines.append(f"[[{name}]]")
            lines.append("type = TCPClientInterface")
            lines.append("enabled = true")
            lines.append(f"target_host = {peer['host']}")
            lines.append(f"target_port = {peer['port']}")
            lines.append("")

        # AutoInterface
        auto = ifaces.get("auto", False)
        lines.append("[[AutoInterface]]")
        lines.append("type = AutoInterface")
        lines.append(f"enabled = {'true' if auto else 'false'}")
        lines.append("")

        return "\n".join(lines)

    def start(self, timeout: float = 15.0) -> None:
        """Start the daemon subprocess and wait for TCP port to accept connections."""
        self.config_dir = self._prepare_config_dir()

        env = os.environ.copy()
        env["STYRENE_CONFIG_DIR"] = str(self.config_dir)
        env["STYRENE_DATA_DIR"] = str(self.config_dir / "data")
        env["STYRENE_STATE_DIR"] = str(self.config_dir / "state")
        # Point RNS to isolated config to avoid shared instance
        env["RNS_CONFIG_DIR"] = str(self.config_dir / ".reticulum")
        env["STYRENED_SOCKET"] = str(self.socket_path)

        # Find styrened executable
        venv_bin = Path(__file__).parent.parent.parent / ".venv" / "bin" / "styrened"
        python = Path(__file__).parent.parent.parent / ".venv" / "bin" / "python"

        if venv_bin.exists():
            cmd = [str(venv_bin), "daemon"]
        else:
            cmd = [str(python), "-m", "styrened", "daemon"]

        logger.info(f"[{self.name}] Starting daemon: {' '.join(cmd)}")

        self.process = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # Prevent signal propagation from test runner
        )

        # Wait for TCP port to accept connections (synchronous poll)
        self._wait_for_port(timeout)
        logger.info(f"[{self.name}] Daemon ready on port {self.port}")

    def _wait_for_port(self, timeout: float) -> None:
        """Poll until TCP port accepts connections."""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                stdout = self.process.stdout.read().decode() if self.process.stdout else ""
                stderr = self.process.stderr.read().decode() if self.process.stderr else ""
                msg = (
                    f"[{self.name}] Daemon exited with code {self.process.returncode}\n"
                    f"stdout: {stdout[:500]}\nstderr: {stderr[:500]}"
                )
                raise RuntimeError(msg)

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(("127.0.0.1", self.port))
                sock.close()
                return
            except (ConnectionRefusedError, TimeoutError, OSError):
                time.sleep(0.5)

        msg = f"[{self.name}] Daemon did not start within {timeout}s on port {self.port}"
        raise TimeoutError(msg)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the daemon subprocess and clean up."""
        if self.process and self.process.poll() is None:
            logger.info(f"[{self.name}] Stopping daemon (pid={self.process.pid})")
            try:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass

            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                logger.warning(f"[{self.name}] Daemon did not stop, sending SIGKILL")
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.process.wait(timeout=2)

        # Clean up temp dir
        if self._temp_dir and Path(self._temp_dir).exists():
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            logger.info(f"[{self.name}] Cleaned up {self._temp_dir}")

        self.process = None
        self.config_dir = None

    @classmethod
    def from_fixture(
        cls,
        name: str,
        *,
        transport: str = "tcp_localhost",
        extra_config: dict[str, Any] | None = None,
    ) -> DaemonHarness:
        """Create a harness from a named fixture.

        Args:
            name: Fixture name (host, alpha, bravo).
            transport: Transport overlay name (default: tcp_localhost).
            extra_config: Additional config overrides (deep-merged on top).
        """
        return cls(name, transport=transport, extra_config=extra_config)
