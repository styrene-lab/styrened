"""
I2PAdapter — DISABLED / ADOPT / MANAGED integration with i2pd.

HTTP proxy port layout:
  - Adopted i2pd:  4444 (system default)
  - Managed i2pd:  4445 (distinct to avoid conflict)

I2PControl API port layout:
  - Adopted i2pd:  7650 (system default)
  - Managed i2pd:  7651 (distinct to avoid conflict)

Warm-up: i2pd requires ~8 minutes on first start to build its router table.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import socket
import struct
from pathlib import Path

from styrened.models.config import CoreConfig, I2PConfig
from styrened.services.binary_errors import BinaryIntegrityError
from styrened.services.daemon_adapter import DaemonAdapter, DaemonMode

log = logging.getLogger(__name__)

# User-local binary location for provisioned binaries
_STYRENE_BIN = Path.home() / ".styrene" / "bin"

_I2PD_CONF_TEMPLATE = """\
# i2pd configuration managed by styrened — do not edit manually.
[httpproxy]
enabled = true
port = {http_proxy_port}

[i2pcontrol]
enabled = true
port = {i2pcontrol_port}

[http]
enabled = true

[sam]
enabled = false
"""

# I2PControl password is empty by default in i2pd
_I2PCONTROL_PASSWORD = ""


class I2PAdapter(DaemonAdapter):
    """Adapter for i2pd, the I2P router daemon."""

    warm_up_seconds: float = 480.0

    def __init__(
        self,
        config: I2PConfig,
        *,
        core_config: "CoreConfig | None" = None,
    ) -> None:
        super().__init__(config.mode)
        self._config = config
        self._core_config = core_config
        self._conf_path = Path.home() / ".styrene" / "i2pd" / "i2pd.conf"

    # ------------------------------------------------------------------
    # Config generation
    # ------------------------------------------------------------------

    def _generate_i2pd_conf(self) -> None:
        """Write ~/.styrene/i2pd/i2pd.conf with managed ports."""
        self._ensure_config_dir(self._conf_path.parent)
        content = _I2PD_CONF_TEMPLATE.format(
            http_proxy_port=self._config.managed_http_proxy_port,
            i2pcontrol_port=self._config.managed_i2pcontrol_port,
        )
        self._conf_path.write_text(content)
        self._conf_path.chmod(0o600)

    # ------------------------------------------------------------------
    # Binary discovery
    # ------------------------------------------------------------------

    def _find_binary(self) -> str | None:
        """Locate the i2pd binary.

        Search order:
        1. ~/.styrene/bin/i2pd (user-local provisioned)
        2. System PATH via shutil.which()
        """
        styrene_bin = _STYRENE_BIN / "i2pd"
        if styrene_bin.exists() and os.access(styrene_bin, os.X_OK):
            return str(styrene_bin)

        found = shutil.which("i2pd")
        if found is not None:
            return found

        return None

    # ------------------------------------------------------------------
    # DaemonAdapter abstract methods
    # ------------------------------------------------------------------

    async def _start_managed(self) -> None:
        """Start managed i2pd process. Fails fast if binary is missing."""
        binary = self._find_binary()
        if binary is None:
            raise RuntimeError(
                "i2pd binary not found in PATH or ~/.styrene/bin/. "
                "Run 'styrened setup --enable i2p' for installation instructions."
            )

        # Binary integrity verification
        if self._core_config is not None:
            vr = self.verify_binary_integrity("i2pd", binary)
            if vr.match is None:
                log.debug("Skipping binary verification for i2pd (not in manifest)")
            elif vr.match is False:
                strict = self._core_config.security.strict_binary_verification
                if strict:
                    raise BinaryIntegrityError("i2pd", vr.expected or "?", vr.actual or "?")
                log.warning("i2pd binary integrity mismatch — starting anyway (strict=false)")
        else:
            log.debug("Skipping binary verification: core_config is None")

        self._generate_i2pd_conf()
        self._process = await asyncio.create_subprocess_exec(
            binary,
            "--conf", str(self._conf_path),
            "--datadir", str(self._conf_path.parent),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        log.info("Started managed i2pd (pid=%s)", self._process.pid)

    async def _stop_managed(self) -> None:
        """Stop managed i2pd: SIGTERM, wait 10s, SIGKILL."""
        if self._process is None:
            return
        try:
            self._process.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(self._process.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            log.warning("i2pd did not stop after SIGTERM; sending SIGKILL")
            try:
                self._process.send_signal(signal.SIGKILL)
                await self._process.wait()
            except ProcessLookupError:
                pass
        self._process = None

    async def _probe(self) -> bool:
        """TCP connect to the HTTP proxy port with a 2s timeout."""
        host = self._config.http_proxy_host
        port = (
            self._config.managed_http_proxy_port
            if self.mode == DaemonMode.MANAGED
            else self._config.http_proxy_port
        )
        try:
            async with asyncio.timeout(2.0):
                _, writer = await asyncio.open_connection(host, port)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return True
        except (OSError, TimeoutError):
            return False

    # ------------------------------------------------------------------
    # I2PControl helper
    # ------------------------------------------------------------------

    async def _i2pcontrol_call(self, port: int, method: str, params: dict | None = None) -> dict | None:
        """Make a JSON-RPC call to the I2PControl API."""
        payload = json.dumps({
            "id": "styrened",
            "method": method,
            "params": params or {"Token": ""},
            "jsonrpc": "2.0",
        }).encode()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._config.http_proxy_host, port),
                timeout=3.0,
            )
        except (OSError, asyncio.TimeoutError):
            return None

        try:
            # Minimal HTTP wrapper required by I2PControl
            http_req = (
                f"POST / HTTP/1.1\r\n"
                f"Host: {self._config.http_proxy_host}:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(payload)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + payload
            writer.write(http_req)
            await writer.drain()

            # Read response
            raw = await asyncio.wait_for(reader.read(16384), timeout=5.0)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            # Strip HTTP headers
            if b"\r\n\r\n" in raw:
                body = raw.split(b"\r\n\r\n", 1)[1]
            else:
                body = raw
            parsed = json.loads(body.decode())
            return dict(parsed) if isinstance(parsed, dict) else None
        except Exception as exc:
            log.debug("I2PControl call failed: %s", exc)
            try:
                writer.close()
            except Exception:
                pass
            return None

    # ------------------------------------------------------------------
    # b32 address detection
    # ------------------------------------------------------------------

    async def _detect_b32_address(self) -> str | None:
        """Detect the local b32 address.

        Tries:
        1. I2PControl API on managed port (7651) or adopted port (7650).
        2. config.b32_address string.
        Returns None if both fail.
        """
        control_port = (
            self._config.managed_i2pcontrol_port
            if self.mode == DaemonMode.MANAGED
            else 7650
        )

        # Step 1: I2PControl
        result = await self._i2pcontrol_call(
            control_port,
            "RouterInfo",
            {"Token": "", "i2p.router.net.bw.inbound.1s": ""},
        )
        if result is not None:
            # Try to get b32 from Authenticate first
            auth = await self._i2pcontrol_call(
                control_port,
                "Authenticate",
                {"API": 1, "Password": _I2PCONTROL_PASSWORD},
            )
            if auth and "result" in auth:
                token = auth["result"].get("Token", "")
                info = await self._i2pcontrol_call(
                    control_port,
                    "RouterInfo",
                    {"Token": token, "i2p.router.id": ""},
                )
                if info and "result" in info:
                    router_id = info["result"].get("i2p.router.id", "")
                    if router_id:
                        return router_id if router_id.endswith(".b32.i2p") else None

        # Step 2: static config fallback
        if self._config.b32_address:
            return self._config.b32_address

        return None

    # ------------------------------------------------------------------
    # Details gathering
    # ------------------------------------------------------------------

    async def _gather_details(self) -> dict:
        """Gather proxy port and b32 address."""
        b32 = await self._detect_b32_address()
        proxy_port = (
            self._config.managed_http_proxy_port
            if self.mode == DaemonMode.MANAGED
            else self._config.http_proxy_port
        )
        return {
            "b32_address": b32,
            "proxy_port": proxy_port,
        }

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_http_proxy_url(self) -> str | None:
        """Return 'http://host:port' for the effective proxy, or None if not running.

        Uses cached details if available; does not re-probe.
        """
        if self.mode == DaemonMode.DISABLED:
            return None
        if self._cached_details is None:
            return None
        port = self._cached_details.get("proxy_port")
        if port is None:
            return None
        return f"http://{self._config.http_proxy_host}:{port}"

    def get_b32_address(self) -> str | None:
        """Return the cached local `.b32.i2p` address, if known.

        Uses cached details only; does not perform network I/O.
        """
        if self.mode == DaemonMode.DISABLED or self._cached_details is None:
            return None
        b32 = self._cached_details.get("b32_address")
        return b32 if isinstance(b32, str) and b32 else None

    async def provision(self) -> None:
        """Check for i2pd binary. Print instructions if not found. Does NOT install."""
        binary = self._find_binary()
        if binary is not None:
            log.info("i2pd found at %s", binary)
            print(f"✓ i2pd found at {binary}")
            return

        print(
            "✗ i2pd binary not found.\n"
            "\n"
            "To install i2pd:\n"
            "  Nix:     nix profile install nixpkgs#i2pd\n"
            "  Debian:  sudo apt install i2pd\n"
            "  macOS:   brew install i2pd\n"
            "\n"
            "Or use the built-in provisioner:\n"
            "  styrened setup --enable i2p\n"
            "\n"
            "Note: i2pd requires 5–10 minutes to warm up after first start."
        )
