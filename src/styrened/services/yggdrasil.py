"""
YggdrasilAdapter — optional Yggdrasil daemon integration.

Supports three modes:
- DISABLED: Yggdrasil integration is off.
- ADOPT:    An externally-managed Yggdrasil process is detected and used.
- MANAGED:  Styrened spawns and supervises its own Yggdrasil process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from styrened.services.daemon_adapter import DaemonAdapter, DaemonMode

log = logging.getLogger(__name__)

# Managed port — distinct from the system default (9001) to avoid conflicts.
MANAGED_PORT = 9002

# Admin socket path for styrened-managed instances.
MANAGED_ADMIN_SOCKET = Path.home() / ".styrene" / "yggdrasil" / "yggdrasil.sock"

# Fallback socket paths to check when probing an adopted instance.
SYSTEM_SOCKET_PATHS = [
    Path("/var/run/yggdrasil/yggdrasil.sock"),
    Path("/run/yggdrasil.sock"),
    Path("/tmp/yggdrasil.sock"),
]

# Nix store paths to check for the yggdrasil binary.
NIX_STORE_PREFIXES = [
    Path("/nix/store"),
    Path("/run/current-system/sw/bin"),
    Path(os.path.expanduser("~/.nix-profile/bin")),
]


@dataclass
class YggdrasilConfig:
    """Configuration for the Yggdrasil adapter."""

    mode: DaemonMode = DaemonMode.DISABLED
    binary_path: str = "yggdrasil"
    listen_port: int = MANAGED_PORT
    admin_socket: str = ""  # empty → use managed default
    multicast: bool = True
    bootstrap_from_rns: bool = True
    initial_peers: list[str] = field(default_factory=list)


class YggdrasilAdapter(DaemonAdapter):
    """Adapter for the Yggdrasil overlay network daemon.

    warm_up_seconds = 30.0 — Yggdrasil bootstraps quickly; 30 s is
    enough time for the admin socket to become available and for initial
    peer connections to be established.
    """

    warm_up_seconds: float = 30.0

    def __init__(self, config: YggdrasilConfig) -> None:
        super().__init__(config.mode)
        self._config = config
        self._local_address: str | None = None
        self._active_socket: Path | None = None  # set by _probe()

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _managed_config_dir(self) -> Path:
        return Path.home() / ".styrene" / "yggdrasil"

    def _managed_conf_path(self) -> Path:
        return self._managed_config_dir() / "yggdrasil.conf"

    def _managed_socket_path(self) -> Path:
        return MANAGED_ADMIN_SOCKET

    def _ensure_yggdrasil_config(self) -> None:
        """Write the yggdrasil.conf for the managed instance."""
        config_dir = self._managed_config_dir()
        self._ensure_config_dir(config_dir)

        peers_json = json.dumps(self._config.initial_peers)
        multicast_listen = "true" if self._config.multicast else "false"
        conf = (
            "{\n"
            f'  "Listen": ["tcp://0.0.0.0:{MANAGED_PORT}"],\n'
            f'  "AdminListen": "unix://{self._managed_socket_path()}",\n'
            f'  "Peers": {peers_json},\n'
            f'  "MulticastInterfaces": [\n'
            f'    {{\n'
            f'      "Regex": ".*",\n'
            f'      "Beacon": {multicast_listen},\n'
            f'      "Listen": {multicast_listen},\n'
            f'      "Port": 0,\n'
            f'      "Priority": 0\n'
            f'    }}\n'
            f'  ]\n'
            "}\n"
        )
        conf_path = self._managed_conf_path()
        conf_path.write_text(conf)
        conf_path.chmod(0o600)

    # ------------------------------------------------------------------
    # Abstract method implementations
    # ------------------------------------------------------------------

    async def _start_managed(self) -> None:
        """Start the yggdrasil process (MANAGED mode only).

        Fails fast if the binary is not found — does NOT provision.
        """
        binary = shutil.which(self._config.binary_path)
        if binary is None:
            # Also check common Nix store paths
            for prefix in NIX_STORE_PREFIXES:
                candidate = prefix / "yggdrasil"
                if candidate.exists() and os.access(candidate, os.X_OK):
                    binary = str(candidate)
                    break

        if binary is None:
            raise FileNotFoundError(
                f"yggdrasil binary not found (looked for "
                f"'{self._config.binary_path}' in PATH and Nix store). "
                f"Run 'styrened setup --enable yggdrasil' to install."
            )

        self._ensure_yggdrasil_config()

        self._process = await asyncio.create_subprocess_exec(
            binary,
            "-useconffile",
            str(self._managed_conf_path()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        log.info("Started managed yggdrasil (pid=%s)", self._process.pid)

    async def _stop_managed(self) -> None:
        """Stop the managed yggdrasil process: SIGTERM → wait 5 s → SIGKILL."""
        if self._process is None:
            return
        try:
            self._process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            log.warning("yggdrasil did not exit after SIGTERM; sending SIGKILL")
            try:
                self._process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                log.error("yggdrasil process did not respond to SIGKILL")
        finally:
            self._process = None

    async def _probe(self) -> bool:
        """Try admin socket paths and return True if any responds.

        Order: managed socket first, then common system paths.
        Sets _active_socket to the first responsive path.
        """
        candidates: list[Path] = []

        # Managed socket takes priority.
        if self._config.mode == DaemonMode.MANAGED:
            candidates.append(self._managed_socket_path())
        elif self._config.admin_socket:
            candidates.append(Path(self._config.admin_socket))

        candidates.extend(SYSTEM_SOCKET_PATHS)

        for sock_path in candidates:
            try:
                result = await self._admin_call_on(sock_path, "getself")
                if result is not None:
                    self._active_socket = sock_path
                    return True
            except Exception:
                continue

        self._active_socket = None
        return False

    async def _gather_details(self) -> dict:
        """Gather address and peer count from the admin socket."""
        details: dict[str, Any] = {}

        try:
            self_info = await self._admin_call("getSelf")
            if self_info:
                addr = self_info.get("address") or self_info.get("self", {}).get("address")
                if addr:
                    self._local_address = addr
                    details["address"] = addr
        except Exception as exc:
            log.debug("getSelf failed: %s", exc)

        try:
            peers_info = await self._admin_call("getPeers")
            if peers_info is not None:
                peers = peers_info.get("peers", peers_info if isinstance(peers_info, list) else [])
                details["peer_count"] = len(peers)
        except Exception as exc:
            log.debug("getPeers failed: %s", exc)

        return details

    # ------------------------------------------------------------------
    # Admin socket helpers
    # ------------------------------------------------------------------

    async def _admin_call_on(
        self,
        sock_path: Path,
        method: str,
        params: dict | None = None,
        timeout: float = 5.0,
    ) -> Any:
        """Send a JSON-RPC request over a specific Unix socket."""
        request = json.dumps({"request": method, "keepalive": False, **(params or {})}).encode()

        loop = asyncio.get_event_loop()

        def _blocking_call() -> Any:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(sock_path))
                sock.sendall(request)
                # Read until the connection closes or we get a complete JSON object.
                buf = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    try:
                        data = json.loads(buf)
                        return data
                    except json.JSONDecodeError:
                        continue
            return None

        return await asyncio.wait_for(
            loop.run_in_executor(None, _blocking_call),
            timeout=timeout + 1.0,
        )

    async def _admin_call(
        self,
        method: str,
        params: dict | None = None,
        timeout: float = 5.0,
    ) -> Any:
        """Send a JSON-RPC request over the active admin socket."""
        if self._active_socket is None:
            raise RuntimeError("No active admin socket — call _probe() first")
        return await self._admin_call_on(self._active_socket, method, params, timeout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_local_address(self) -> str | None:
        """Return the cached Yggdrasil IPv6 address, or None if not yet known."""
        return self._local_address

    async def add_peer(self, address: str, port: int = 9001) -> bool:
        """Ephemerally add a peer via the admin socket.

        This does NOT write to the config file — the peer is lost on restart.
        Use initial_peers in the config for persistent peers.
        """
        if self._active_socket is None:
            # Try to probe first.
            if not await self._probe():
                log.warning("add_peer: yggdrasil not running or unreachable")
                return False

        try:
            uri = f"tcp://{address}:{port}"
            result = await self._admin_call("addPeer", {"uri": uri})
            if result is not None:
                log.info("Added ephemeral peer %s", uri)
                return True
        except Exception as exc:
            log.warning("add_peer failed: %s", exc)
        return False

    async def provision(self) -> None:  # type: ignore[override]
        """Check for the yggdrasil binary and print install instructions if missing.

        Does NOT install automatically.
        """
        binary = shutil.which(self._config.binary_path)
        if binary is None:
            for prefix in NIX_STORE_PREFIXES:
                candidate = prefix / "yggdrasil"
                if candidate.exists() and os.access(candidate, os.X_OK):
                    binary = str(candidate)
                    break

        if binary:
            print(f"✓ yggdrasil found at: {binary}")
        else:
            print(
                "✗ yggdrasil binary not found.\n"
                "\n"
                "To install via Nix:\n"
                "  nix profile install nixpkgs#yggdrasil\n"
                "\n"
                "After installation, run:\n"
                "  styrened setup --enable yggdrasil\n"
            )
