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
from pathlib import Path
from typing import Any

from styrened.models.config import CoreConfig, YggdrasilConfig
from styrened.services.binary_errors import BinaryIntegrityError
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

# Also check ~/.styrene/bin/ for user-local provisioned binaries
_STYRENE_BIN = Path.home() / ".styrene" / "bin"


class YggdrasilAdapter(DaemonAdapter):
    """Adapter for the Yggdrasil overlay network daemon.

    warm_up_seconds = 30.0 — Yggdrasil bootstraps quickly; 30 s is
    enough time for the admin socket to become available and for initial
    peer connections to be established.
    """

    warm_up_seconds: float = 30.0

    def __init__(
        self,
        config: YggdrasilConfig,
        *,
        core_config: "CoreConfig | None" = None,
    ) -> None:
        super().__init__(config.mode)
        self._config = config
        self._core_config = core_config
        self._local_address: str | None = None
        self._active_socket: Path | None = None  # set by _probe()

    # ------------------------------------------------------------------
    # Binary discovery
    # ------------------------------------------------------------------

    def _find_binary(self) -> str | None:
        """Locate the yggdrasil binary.

        Search order:
        1. Explicit config.binary_path (if absolute and exists)
        2. ~/.styrene/bin/yggdrasil (user-local provisioned)
        3. System PATH via shutil.which()
        4. Common Nix store paths
        """
        # 1. Explicit absolute path
        if os.path.isabs(self._config.binary_path):
            if os.path.isfile(self._config.binary_path) and os.access(
                self._config.binary_path, os.X_OK
            ):
                return self._config.binary_path

        # 2. ~/.styrene/bin/
        styrene_bin = _STYRENE_BIN / "yggdrasil"
        if styrene_bin.exists() and os.access(styrene_bin, os.X_OK):
            return str(styrene_bin)

        # 3. System PATH
        found = shutil.which(self._config.binary_path)
        if found is not None:
            return found

        # 4. Nix store paths
        for prefix in NIX_STORE_PREFIXES:
            candidate = prefix / "yggdrasil"
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)

        return None

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
        """Write the yggdrasil.conf for the managed instance.

        Sets ``IfName`` to ``"none"`` to skip TUN device creation, which
        requires root.  Styrened uses Yggdrasil purely as an overlay peer
        network — RNS peers over Yggdrasil's TCP listener, not via the
        TUN/IPv6 stack.
        """
        config_dir = self._managed_config_dir()
        self._ensure_config_dir(config_dir)

        peers_json = json.dumps(self._config.initial_peers)
        multicast_listen = "true" if self._config.multicast else "false"
        conf = (
            "{\n"
            f'  "Listen": ["tcp://0.0.0.0:{MANAGED_PORT}"],\n'
            f'  "AdminListen": "unix://{self._managed_socket_path()}",\n'
            f'  "Peers": {peers_json},\n'
            f'  "IfName": "none",\n'
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
        Verifies binary integrity before launch when core_config is available.
        """
        binary = self._find_binary()
        if binary is None:
            raise FileNotFoundError(
                f"yggdrasil binary not found (looked for "
                f"'{self._config.binary_path}' in PATH, ~/.styrene/bin/, "
                f"and Nix store). "
                f"Run 'styrened setup --enable yggdrasil' to install."
            )

        # Binary integrity verification
        if self._core_config is not None:
            result = self.verify_binary_integrity("yggdrasil", binary)
            if result is None:
                log.debug("Skipping binary verification for yggdrasil (not in manifest)")
            elif result is False:
                strict = self._core_config.security.strict_binary_verification
                if strict:
                    raise BinaryIntegrityError("yggdrasil", "<manifest>", "<actual>")
                log.warning("Yggdrasil binary integrity mismatch — starting anyway (strict=false)")

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
                # Response format: {"status":"success","response":{"address":"...","key":"..."}}
                resp = self_info.get("response", self_info)
                addr = resp.get("address") or resp.get("self", {}).get("address")
                if addr:
                    self._local_address = addr
                    details["address"] = addr
                key = resp.get("key")
                if key:
                    details["public_key"] = key
                version = resp.get("build_version")
                if version:
                    details["version"] = version
        except Exception as exc:
            log.debug("getSelf failed: %s", exc)

        try:
            peers_info = await self._admin_call("getPeers")
            if peers_info is not None:
                resp = peers_info.get("response", peers_info)
                peers = resp.get("peers", resp if isinstance(resp, list) else [])
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
        binary = self._find_binary()

        if binary:
            print(f"✓ yggdrasil found at: {binary}")
        else:
            print(
                "✗ yggdrasil binary not found.\n"
                "\n"
                "To install:\n"
                "  Nix:     nix profile install nixpkgs#yggdrasil\n"
                "  Debian:  sudo apt install yggdrasil\n"
                "  macOS:   brew install yggdrasil\n"
                "\n"
                "Or use the built-in provisioner:\n"
                "  styrened setup --enable yggdrasil\n"
            )
