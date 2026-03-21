"""Installation diagnostics, version check, and setup wizard for styrened.

Provides health checks for:
- Version: installed vs latest PyPI release
- Identity: operator identity existence, permissions, LXMF app detection
- Config: config file existence and validity
- Reticulum: RNS configuration state
- Daemon: control socket existence and daemon responsiveness
- Paths: directory existence and write permissions

Usage:
    from styrened.services.doctor import run_doctor

    report = await run_doctor(offline=True)
    for finding in report.findings:
        print(f"[{finding.severity.value}] {finding.message}")
"""
from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from styrened import __version__, paths
from styrened.models.daemon_mode import DaemonMode
from styrened.services.config import load_core_config
from styrened.services.i2p import I2PAdapter
from styrened.services.reticulum import (
    _resolve_identity_path,
    detect_existing_lxmf_identity,
    find_reticulum_config,
    get_identity_sharing_status,
    get_operator_identity,
    get_reticulum_config_state,
    is_reticulum_configured,
)
from styrened.services.yggdrasil import YggdrasilAdapter

logger = logging.getLogger(__name__)

# Binary manifest path — resolved lazily to avoid import-time I/O.
_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "binary_manifest.json")


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class Severity(Enum):
    """Severity level for diagnostic findings."""

    OK = "OK"
    WARN = "WARN"
    ERROR = "ERR"


class CheckCategory(Enum):
    """Category of diagnostic check."""

    VERSION = "version"
    IDENTITY = "identity"
    CONFIG = "config"
    RETICULUM = "reticulum"
    DAEMON = "daemon"
    PATHS = "paths"
    YGGDRASIL = "yggdrasil"
    I2P = "i2p"
    BOUNDARY_LOG = "boundary_log"


# -----------------------------------------------------------------------------
# Data models
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """A single diagnostic finding."""

    category: CheckCategory
    severity: Severity
    message: str
    fix_hint: str | None = None


@dataclass
class DoctorReport:
    """Aggregated results from all diagnostic checks."""

    findings: list[Finding] = field(default_factory=list)
    version_info: dict[str, Any] = field(default_factory=dict)
    identity_info: dict[str, Any] = field(default_factory=dict)
    checked_at: str = ""

    @property
    def has_errors(self) -> bool:
        return any(f.severity == Severity.ERROR for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(f.severity == Severity.WARN for f in self.findings)

    @property
    def exit_code(self) -> int:
        if self.has_errors:
            return 2
        if self.has_warnings:
            return 1
        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [
                {
                    "category": f.category.value,
                    "severity": f.severity.value,
                    "message": f.message,
                    "fix_hint": f.fix_hint,
                }
                for f in self.findings
            ],
            "version_info": self.version_info,
            "identity_info": self.identity_info,
            "checked_at": self.checked_at,
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
            "exit_code": self.exit_code,
        }


# -----------------------------------------------------------------------------
# Check functions
# -----------------------------------------------------------------------------


def check_rust_daemon() -> list[Finding]:
    """Check if the Rust daemon binary is available.

    Returns:
        List of findings about Rust daemon availability.
    """
    from styrened.rust_daemon import find_rust_daemon

    findings: list[Finding] = []
    binary = find_rust_daemon()

    if binary:
        import subprocess

        findings.append(
            Finding(
                category=CheckCategory.DAEMON,
                severity=Severity.OK,
                message=f"Rust daemon found: {binary}",
            )
        )
        # Try to get version
        try:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                findings.append(
                    Finding(
                        category=CheckCategory.DAEMON,
                        severity=Severity.OK,
                        message=f"Rust daemon version: {result.stdout.strip()}",
                    )
                )
        except (subprocess.TimeoutExpired, OSError):
            pass  # Version check is best-effort
    else:
        findings.append(
            Finding(
                category=CheckCategory.DAEMON,
                severity=Severity.WARN,
                message="Rust daemon (reticulumd) not found — using Python daemon fallback",
                fix_hint=(
                    "Install via: cargo install styrened-rs\n"
                    "  Or download from GitHub releases\n"
                    "  Or set STYRENED_RS_BIN=/path/to/reticulumd"
                ),
            )
        )

    return findings


def check_version(offline: bool = False) -> list[Finding]:
    """Check installed version and compare to latest PyPI release.

    Args:
        offline: If True, skip the PyPI check.

    Returns:
        List of findings about version status.
    """
    findings: list[Finding] = []
    findings.append(
        Finding(
            category=CheckCategory.VERSION,
            severity=Severity.OK,
            message=f"styrened {__version__} installed",
        )
    )

    if offline:
        return findings

    try:
        import urllib.request

        from packaging.version import Version

        url = "https://pypi.org/pypi/styrened/json"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            import json

            data = json.loads(resp.read())
            latest = data.get("info", {}).get("version", "")

        if latest:
            installed_v = Version(__version__)
            latest_v = Version(latest)
            if installed_v < latest_v:
                findings.append(
                    Finding(
                        category=CheckCategory.VERSION,
                        severity=Severity.WARN,
                        message=f"Newer version available: {latest} (installed: {__version__})",
                        fix_hint="pip install --upgrade styrened",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=CheckCategory.VERSION,
                        severity=Severity.OK,
                        message="Up to date with PyPI",
                    )
                )
    except Exception as e:
        logger.debug(f"PyPI version check failed: {e}")
        findings.append(
            Finding(
                category=CheckCategory.VERSION,
                severity=Severity.WARN,
                message=f"Could not check PyPI for updates: {e}",
                fix_hint="Check network connectivity or use --offline",
            )
        )

    return findings


def check_identity() -> list[Finding]:
    """Check operator identity status.

    Returns:
        List of findings about identity configuration.
    """
    findings: list[Finding] = []

    # Check if identity exists
    identity_hash = get_operator_identity()
    identity_path = _resolve_identity_path()

    if identity_hash and identity_path:
        findings.append(
            Finding(
                category=CheckCategory.IDENTITY,
                severity=Severity.OK,
                message=f"Operator identity: {identity_hash[:16]}...",
            )
        )

        # Check file permissions (should not be world-readable)
        try:
            st = os.stat(identity_path)
            if st.st_mode & stat.S_IROTH:
                findings.append(
                    Finding(
                        category=CheckCategory.IDENTITY,
                        severity=Severity.WARN,
                        message=f"Identity file is world-readable: {identity_path}",
                        fix_hint=f"chmod 600 {identity_path}",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=CheckCategory.IDENTITY,
                        severity=Severity.OK,
                        message="Identity file permissions OK",
                    )
                )
        except OSError as e:
            findings.append(
                Finding(
                    category=CheckCategory.IDENTITY,
                    severity=Severity.WARN,
                    message=f"Could not check identity file permissions: {e}",
                )
            )
    else:
        findings.append(
            Finding(
                category=CheckCategory.IDENTITY,
                severity=Severity.ERROR,
                message="No operator identity found",
                fix_hint="Run 'styrened identity --create' or 'styrened doctor --setup'",
            )
        )

    # Check for existing LXMF identities from other apps
    existing = detect_existing_lxmf_identity()
    if existing:
        app_name, app_path = existing
        if not identity_hash:
            findings.append(
                Finding(
                    category=CheckCategory.IDENTITY,
                    severity=Severity.OK,
                    message=f"Found existing identity from {app_name}: {app_path}",
                    fix_hint="Run 'styrened doctor --setup' to adopt it",
                )
            )
        else:
            findings.append(
                Finding(
                    category=CheckCategory.IDENTITY,
                    severity=Severity.OK,
                    message=f"Existing identity detected from {app_name}",
                )
            )

    # Check sharing status
    try:
        sharing_status = get_identity_sharing_status()
        shared_apps = [
            app for app, info in sharing_status.items() if info.get("points_to_styrened")
        ]
        independent_apps = [
            app
            for app, info in sharing_status.items()
            if info.get("exists") and not info.get("points_to_styrened") and not info.get("is_symlink")
        ]

        if shared_apps:
            findings.append(
                Finding(
                    category=CheckCategory.IDENTITY,
                    severity=Severity.OK,
                    message=f"Identity shared with: {', '.join(shared_apps)}",
                )
            )
        if independent_apps:
            findings.append(
                Finding(
                    category=CheckCategory.IDENTITY,
                    severity=Severity.WARN,
                    message=f"Independent identities: {', '.join(independent_apps)}",
                    fix_hint="Run 'styrened identity-share' to unify identities",
                )
            )
    except Exception as e:
        logger.debug(f"Identity sharing status check failed: {e}")

    return findings


def check_config() -> list[Finding]:
    """Check configuration file status.

    Returns:
        List of findings about configuration.
    """
    findings: list[Finding] = []

    config_path = paths.config_file()

    if not config_path.exists():
        findings.append(
            Finding(
                category=CheckCategory.CONFIG,
                severity=Severity.WARN,
                message=f"Config file not found: {config_path}",
                fix_hint="Run 'styrened doctor --setup' to create one, or start with defaults",
            )
        )
        return findings

    # Try to load config
    try:
        config = load_core_config()
        findings.append(
            Finding(
                category=CheckCategory.CONFIG,
                severity=Severity.OK,
                message=f"Config loaded from {config_path}",
            )
        )

        # Check if display_name is customized
        display_name = getattr(config, "identity", None)
        display_name = getattr(display_name, "display_name", None) if display_name else None
        if display_name in ("", "styrene-node", "Anonymous Styrene", None):
            findings.append(
                Finding(
                    category=CheckCategory.CONFIG,
                    severity=Severity.WARN,
                    message="Display name not customized (using default)",
                    fix_hint="Set 'display_name' in config or run 'styrened doctor --setup'",
                )
            )
        else:
            findings.append(
                Finding(
                    category=CheckCategory.CONFIG,
                    severity=Severity.OK,
                    message=f"Display name: {display_name}",
                )
            )
    except Exception as e:
        findings.append(
            Finding(
                category=CheckCategory.CONFIG,
                severity=Severity.ERROR,
                message=f"Config parse error: {e}",
                fix_hint=f"Check YAML syntax in {config_path}",
            )
        )

    return findings


def check_reticulum() -> list[Finding]:
    """Check Reticulum configuration status.

    Returns:
        List of findings about Reticulum.
    """
    findings: list[Finding] = []

    rns_config_dir = find_reticulum_config()
    if not rns_config_dir:
        findings.append(
            Finding(
                category=CheckCategory.RETICULUM,
                severity=Severity.WARN,
                message="No Reticulum config directory found",
                fix_hint="RNS will create a default config on first run",
            )
        )
        return findings

    findings.append(
        Finding(
            category=CheckCategory.RETICULUM,
            severity=Severity.OK,
            message=f"Reticulum config: {rns_config_dir}",
        )
    )

    if not is_reticulum_configured(rns_config_dir):
        findings.append(
            Finding(
                category=CheckCategory.RETICULUM,
                severity=Severity.WARN,
                message="Reticulum config exists but may not be fully configured",
            )
        )
        return findings

    # Check config state for interface details
    try:
        config_state = get_reticulum_config_state(rns_config_dir)
        if config_state:
            iface_count = getattr(config_state, "interface_count", 0)
            if iface_count > 0:
                findings.append(
                    Finding(
                        category=CheckCategory.RETICULUM,
                        severity=Severity.OK,
                        message=f"{iface_count} interface(s) configured",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=CheckCategory.RETICULUM,
                        severity=Severity.WARN,
                        message="No interfaces configured in Reticulum config",
                        fix_hint="Add interfaces to ~/.reticulum/config",
                    )
                )
    except Exception as e:
        logger.debug(f"Reticulum config state check failed: {e}")
        findings.append(
            Finding(
                category=CheckCategory.RETICULUM,
                severity=Severity.OK,
                message="Reticulum configured (detailed state unavailable)",
            )
        )

    return findings


async def check_daemon() -> list[Finding]:
    """Check daemon connectivity.

    Returns:
        List of findings about daemon status.
    """
    findings: list[Finding] = []

    socket_path = paths.control_socket()
    if not socket_path.exists():
        findings.append(
            Finding(
                category=CheckCategory.DAEMON,
                severity=Severity.WARN,
                message="Daemon not running (no control socket)",
                fix_hint="Start with 'styrened daemon' or 'systemctl start styrened'",
            )
        )
        return findings

    # Try to ping the daemon and check version
    try:
        from styrened.ipc import ControlClient, get_default_socket_path

        client = ControlClient(socket_path=get_default_socket_path(), timeout=3.0)
        try:
            await client.connect()
            pong = await client.ping(timeout=2.0)
            if pong:
                findings.append(
                    Finding(
                        category=CheckCategory.DAEMON,
                        severity=Severity.OK,
                        message="Daemon is running and responsive",
                    )
                )
                # Version mismatch check
                daemon_ver = getattr(pong, "daemon_version", None) if not isinstance(pong, bool) else None
                if daemon_ver and daemon_ver != __version__:
                    findings.append(
                        Finding(
                            category=CheckCategory.DAEMON,
                            severity=Severity.WARN,
                            message=(
                                f"Version mismatch: running daemon is v{daemon_ver}, "
                                f"installed binary is v{__version__}"
                            ),
                            fix_hint=(
                                "Restart the service to pick up the new binary: "
                                "'systemctl --user restart styrened' (Linux) or "
                                "'launchctl unload/load ~/Library/LaunchAgents/com.styrene.styrened.plist' (macOS). "
                                "Or run: just dev-daemon"
                            ),
                        )
                    )
                elif daemon_ver:
                    findings.append(
                        Finding(
                            category=CheckCategory.DAEMON,
                            severity=Severity.OK,
                            message=f"Daemon version matches: v{daemon_ver}",
                        )
                    )
            else:
                findings.append(
                    Finding(
                        category=CheckCategory.DAEMON,
                        severity=Severity.WARN,
                        message="Daemon socket exists but did not respond to ping",
                    )
                )
        finally:
            await client.disconnect()
    except Exception as e:
        logger.debug(f"Daemon ping failed: {e}")
        # Fall back to legacy get_daemon_client path
        try:
            from styrened.ipc import get_daemon_client

            client2 = await get_daemon_client()
            if client2:
                try:
                    pong = await client2.ping(timeout=2.0)
                    if pong:
                        findings.append(
                            Finding(
                                category=CheckCategory.DAEMON,
                                severity=Severity.OK,
                                message="Daemon is running and responsive",
                            )
                        )
                finally:
                    await client2.disconnect()
            else:
                findings.append(
                    Finding(
                        category=CheckCategory.DAEMON,
                        severity=Severity.WARN,
                        message="Could not connect to daemon (socket exists but connection failed)",
                        fix_hint="Check if daemon process is running",
                    )
                )
        except Exception as e2:
            findings.append(
                Finding(
                    category=CheckCategory.DAEMON,
                    severity=Severity.WARN,
                    message=f"Daemon connection error: {e2}",
                    fix_hint="Try restarting the daemon",
                )
            )

    return findings


def check_paths() -> list[Finding]:
    """Check that required directories exist and are writable.

    Returns:
        List of findings about path status.
    """
    findings: list[Finding] = []

    dirs_to_check = [
        ("Config", paths.config_dir()),
        ("Data", paths.data_dir()),
        ("State", paths.state_dir()),
        ("Runtime", paths.runtime_dir()),
    ]

    for name, dir_path in dirs_to_check:
        if dir_path.exists():
            if os.access(dir_path, os.W_OK):
                findings.append(
                    Finding(
                        category=CheckCategory.PATHS,
                        severity=Severity.OK,
                        message=f"{name}: {dir_path}",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=CheckCategory.PATHS,
                        severity=Severity.ERROR,
                        message=f"{name} directory not writable: {dir_path}",
                        fix_hint=f"chmod u+w {dir_path}",
                    )
                )
        else:
            findings.append(
                Finding(
                    category=CheckCategory.PATHS,
                    severity=Severity.WARN,
                    message=f"{name} directory missing: {dir_path}",
                    fix_hint=f"mkdir -p {dir_path}",
                )
            )

    return findings


# -----------------------------------------------------------------------------
# Optional daemon checks (Yggdrasil / I2P)
# -----------------------------------------------------------------------------


async def check_yggdrasil(config: Any | None = None) -> list[Finding]:
    """Check Yggdrasil integration status.

    Args:
        config: Pre-loaded CoreConfig; loads from disk if None.

    Returns:
        List of findings.  Empty list when mode=DISABLED.
    """
    import shutil

    if config is None:
        try:
            config = load_core_config()
        except Exception:
            return []

    ygg_cfg = config.yggdrasil

    if ygg_cfg.mode == DaemonMode.DISABLED:
        return []

    findings: list[Finding] = []

    # MANAGED — fail fast if binary is missing.
    if ygg_cfg.mode == DaemonMode.MANAGED:
        binary = shutil.which(ygg_cfg.binary_path)
        if binary is None:
            findings.append(
                Finding(
                    category=CheckCategory.YGGDRASIL,
                    severity=Severity.ERROR,
                    message="yggdrasil binary not found in PATH",
                    fix_hint="styrened setup --enable yggdrasil",
                )
            )
            return findings

    adapter = YggdrasilAdapter(ygg_cfg)  # type: ignore[arg-type]
    try:
        status = await adapter.status()
    except Exception as exc:
        logger.debug("Yggdrasil status check failed: %s", exc)
        findings.append(
            Finding(
                category=CheckCategory.YGGDRASIL,
                severity=Severity.WARN,
                message=f"Yggdrasil status check error: {exc}",
            )
        )
        return findings

    if not status.running:
        if ygg_cfg.mode == DaemonMode.ADOPT:
            findings.append(
                Finding(
                    category=CheckCategory.YGGDRASIL,
                    severity=Severity.WARN,
                    message="yggdrasil not detected at expected socket paths — is it running?",
                )
            )
        else:
            # MANAGED but not running (binary exists, process not up yet)
            findings.append(
                Finding(
                    category=CheckCategory.YGGDRASIL,
                    severity=Severity.WARN,
                    message="Managed yggdrasil process is not responding",
                    fix_hint="styrened setup --enable yggdrasil",
                )
            )
        return findings

    # Running — report details.
    address = status.details.get("address", "unknown")
    peer_count = status.details.get("peer_count", 0)
    findings.append(
        Finding(
            category=CheckCategory.YGGDRASIL,
            severity=Severity.OK,
            message=f"Yggdrasil running — address: {address}, peers: {peer_count}",
        )
    )
    return findings


async def check_i2p(config: Any | None = None) -> list[Finding]:
    """Check I2P (i2pd) integration status.

    Args:
        config: Pre-loaded CoreConfig; loads from disk if None.

    Returns:
        List of findings.  Empty list when mode=DISABLED.
    """
    import math
    import shutil

    if config is None:
        try:
            config = load_core_config()
        except Exception:
            return []

    i2p_cfg = config.i2p

    if i2p_cfg.mode == DaemonMode.DISABLED:
        return []

    findings: list[Finding] = []

    # MANAGED — fail fast if binary is missing.
    if i2p_cfg.mode == DaemonMode.MANAGED:
        binary = shutil.which("i2pd")
        if binary is None:
            findings.append(
                Finding(
                    category=CheckCategory.I2P,
                    severity=Severity.ERROR,
                    message="i2pd binary not found in PATH",
                    fix_hint="styrened setup --enable i2p",
                )
            )
            return findings

    adapter = I2PAdapter(i2p_cfg)
    try:
        status = await adapter.status()
    except Exception as exc:
        logger.debug("I2P status check failed: %s", exc)
        findings.append(
            Finding(
                category=CheckCategory.I2P,
                severity=Severity.WARN,
                message=f"I2P status check error: {exc}",
            )
        )
        return findings

    if not status.running:
        if i2p_cfg.mode == DaemonMode.ADOPT:
            host = i2p_cfg.http_proxy_host
            port = i2p_cfg.http_proxy_port
            findings.append(
                Finding(
                    category=CheckCategory.I2P,
                    severity=Severity.WARN,
                    message=f"i2pd not detected at {host}:{port}",
                )
            )
        else:
            findings.append(
                Finding(
                    category=CheckCategory.I2P,
                    severity=Severity.WARN,
                    message="Managed i2pd process is not responding",
                    fix_hint="styrened setup --enable i2p",
                )
            )
        return findings

    # Running but still warming up (MANAGED mode).
    if status.warming_up and i2p_cfg.mode == DaemonMode.MANAGED:
        remaining = max(0.0, status.warm_up_expected - status.warm_up_elapsed)
        mins = math.ceil(remaining / 60)
        findings.append(
            Finding(
                category=CheckCategory.I2P,
                severity=Severity.OK,
                message=f"i2pd warming up (~{mins} min remaining)",
            )
        )
        return findings

    # Running and ready.
    proxy_port = status.details.get("proxy_port", i2p_cfg.http_proxy_port)
    findings.append(
        Finding(
            category=CheckCategory.I2P,
            severity=Severity.OK,
            message=f"i2pd running — HTTP proxy on port {proxy_port}",
        )
    )
    return findings


# -----------------------------------------------------------------------------
# Binary checks for adapter binaries (yggdrasil, i2pd)
# -----------------------------------------------------------------------------


def _load_manifest() -> dict[str, Any]:
    """Load the binary manifest JSON. Returns empty dict on failure."""
    import json

    try:
        with open(_MANIFEST_PATH) as f:
            result: dict[str, Any] = json.load(f)
            return result
    except Exception as exc:
        logger.debug("Failed to load binary manifest: %s", exc)
        return {}


def _detect_platform() -> str:
    """Map current OS + arch to manifest platform key."""
    import platform
    import sys

    machine = platform.machine().lower()
    arch_map = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armhf",
        "armv6l": "armhf",
    }
    arch = arch_map.get(machine, machine)

    if sys.platform == "darwin":
        return f"darwin-{arch}"
    elif sys.platform.startswith("linux"):
        return f"linux-{arch}"
    return f"unknown-{arch}"


def _get_manifest_entry(adapter_name: str) -> dict[str, Any] | None:
    """Get platform-specific manifest entry for an adapter."""
    manifest = _load_manifest()
    adapter_data = manifest.get("adapters", {}).get(adapter_name)
    if not adapter_data:
        return None
    platform_key = _detect_platform()
    entry: dict[str, Any] | None = adapter_data.get("platforms", {}).get(platform_key)
    return entry


def _get_manifest_version(adapter_name: str) -> str | None:
    """Get expected version string from manifest for an adapter."""
    manifest = _load_manifest()
    adapter_data = manifest.get("adapters", {}).get(adapter_name)
    if adapter_data:
        version: str | None = adapter_data.get("version")
        return version
    return None


def _hash_file(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_binary_version(binary_path: str, adapter_name: str) -> str | None:
    """Run ``<binary> --version`` and extract the version string."""
    import re
    import subprocess

    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip() or result.stderr.strip()
        # Common patterns: "yggdrasil v0.5.13", "i2pd version 2.59.0"
        m = re.search(r"(\d+\.\d+\.\d+)", output)
        return m.group(1) if m else None
    except Exception as exc:
        logger.debug("Version check for %s failed: %s", adapter_name, exc)
        return None


def _get_provisioner() -> Any:
    """Import and return a BinaryProvisioner instance.

    Returns None if the provisioner module is not yet available
    (e.g. sibling task not merged).
    """
    try:
        from styrened.services.binary_provisioner import BinaryProvisioner

        return BinaryProvisioner()
    except ImportError:
        logger.debug("BinaryProvisioner not available — provisioner-core not merged?")
        return None


# Mapping: adapter_name → (category, config_attr)
_ADAPTER_SPECS: list[tuple[str, CheckCategory, str]] = [
    ("yggdrasil", CheckCategory.YGGDRASIL, "yggdrasil"),
    ("i2pd", CheckCategory.I2P, "i2p"),
]


def _make_adapter(adapter_name: str, cfg: Any) -> Any:
    """Instantiate the appropriate adapter for a given adapter name."""
    if adapter_name == "yggdrasil":
        return YggdrasilAdapter(cfg)
    elif adapter_name == "i2pd":
        return I2PAdapter(cfg)
    raise ValueError(f"Unknown adapter: {adapter_name}")


async def check_adapter_binaries(config: Any) -> list[Finding]:
    """Check binary presence, integrity, and version for each non-disabled adapter.

    Reports:
      ✓ found + hash matches
      ⚠ hash mismatch (expected vs actual)
      ✗ not found
    """
    findings: list[Finding] = []

    for adapter_name, category, config_attr in _ADAPTER_SPECS:
        cfg = getattr(config, config_attr, None)
        if cfg is None or cfg.mode == DaemonMode.DISABLED:
            continue

        adapter = _make_adapter(adapter_name, cfg)
        binary_path = adapter._find_binary()

        if binary_path is None:
            severity = Severity.ERROR if cfg.mode == DaemonMode.MANAGED else Severity.WARN
            findings.append(
                Finding(
                    category=category,
                    severity=severity,
                    message=f"✗ {adapter_name} binary not found",
                    fix_hint=f"Run 'styrened doctor --fix' to provision {adapter_name}",
                )
            )
            continue

        # Binary found — check integrity
        manifest_entry = _get_manifest_entry(adapter_name)
        if manifest_entry:
            actual_hash = _hash_file(binary_path)
            expected_hash = manifest_entry.get("binary_sha256", "")

            if actual_hash == expected_hash:
                findings.append(
                    Finding(
                        category=category,
                        severity=Severity.OK,
                        message=f"✓ {adapter_name} found at {binary_path}, hash matches",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=category,
                        severity=Severity.WARN,
                        message=(
                            f"⚠ {adapter_name} binary hash mismatch — "
                            f"expected {expected_hash[:12]}…, got {actual_hash[:12]}…"
                        ),
                        fix_hint=f"Run 'styrened doctor --fix' to re-provision {adapter_name}",
                    )
                )
        else:
            # No manifest entry for this platform — can't verify, just report found
            findings.append(
                Finding(
                    category=category,
                    severity=Severity.OK,
                    message=f"✓ {adapter_name} found at {binary_path} (no manifest entry for verification)",
                )
            )

        # Version check
        manifest_version = _get_manifest_version(adapter_name)
        actual_version = _check_binary_version(binary_path, adapter_name)
        if manifest_version and actual_version:
            if actual_version == manifest_version:
                findings.append(
                    Finding(
                        category=category,
                        severity=Severity.OK,
                        message=f"✓ {adapter_name} version {actual_version}",
                    )
                )
            else:
                findings.append(
                    Finding(
                        category=category,
                        severity=Severity.WARN,
                        message=(
                            f"⚠ {adapter_name} version mismatch — "
                            f"installed {actual_version}, manifest expects {manifest_version}"
                        ),
                    )
                )

    return findings


async def fix_adapter_binaries(config: Any) -> list[Finding]:
    """In --fix mode: provision missing binaries, report results.

    For binaries that already exist and pass checks, no action is taken.
    """
    findings: list[Finding] = []

    for adapter_name, category, config_attr in _ADAPTER_SPECS:
        cfg = getattr(config, config_attr, None)
        if cfg is None or cfg.mode == DaemonMode.DISABLED:
            continue

        adapter = _make_adapter(adapter_name, cfg)
        binary_path = adapter._find_binary()

        if binary_path is not None:
            # Binary exists — check if it needs re-provisioning
            manifest_entry = _get_manifest_entry(adapter_name)
            if manifest_entry:
                actual_hash = _hash_file(binary_path)
                expected_hash = manifest_entry.get("binary_sha256", "")
                if actual_hash == expected_hash:
                    # All good, skip
                    continue
                # Hash mismatch — fall through to provision
                logger.info("Re-provisioning %s due to hash mismatch", adapter_name)
            else:
                # No manifest entry — can't verify, skip
                continue

        # Need to provision
        provisioner = _get_provisioner()
        if provisioner is None:
            findings.append(
                Finding(
                    category=category,
                    severity=Severity.ERROR,
                    message=f"✗ {adapter_name} provisioner not available",
                    fix_hint="Install binary manually or upgrade styrened",
                )
            )
            continue

        try:
            await provisioner.provision(adapter_name)
            findings.append(
                Finding(
                    category=category,
                    severity=Severity.OK,
                    message=f"✓ {adapter_name} installed",
                )
            )
        except Exception as exc:
            findings.append(
                Finding(
                    category=category,
                    severity=Severity.ERROR,
                    message=f"✗ {adapter_name} provisioning failed: {exc}",
                )
            )

    return findings


# -----------------------------------------------------------------------------
# Boundary log check
# -----------------------------------------------------------------------------

# Number of records per boundary tag above which we emit a WARN instead of INFO.
_BOUNDARY_WARN_THRESHOLD = 5


async def check_boundary_log() -> list[Finding]:
    """Check boundary log snapshot from the running daemon.

    Connects to the daemon via IPC, requests ``CMD_BOUNDARY_SNAPSHOT``, and
    groups the returned records by their ``boundary`` tag.  Per-tag results:

    * **>5 records** → WARN finding (count + last-seen timestamp + fix_hint)
    * **≤5 transient-only records** → INFO finding
    * Daemon not running → skip silently (no error findings)

    Returns:
        List of findings about boundary log status.  Empty list when the
        daemon is unreachable.
    """
    from styrened import paths
    from styrened.ipc import ControlClient, IPCMessageType

    findings: list[Finding] = []

    socket_path = paths.control_socket()
    if not socket_path.exists():
        # Daemon not running — skip gracefully.
        return findings

    # CMD_BOUNDARY_SNAPSHOT is added by the ipc-command sibling task.
    # If this attribute is missing (e.g. running against an older build before
    # the merge), bail out without surfacing an error.
    snapshot_cmd = getattr(IPCMessageType, "CMD_BOUNDARY_SNAPSHOT", None)
    if snapshot_cmd is None:
        logger.debug("CMD_BOUNDARY_SNAPSHOT not available in this build — skipping boundary log check")
        return findings

    # CmdBoundarySnapshotRequest lives in ipc/messages.py (added by the
    # ipc-command sibling task).  If it is absent the build is incomplete;
    # surface a WARN rather than sending garbage via a silent fallback shim.
    try:
        from styrened.ipc.messages import (
            CmdBoundarySnapshotRequest as _BoundaryReq,  # type: ignore[attr-defined]
        )
    except ImportError as exc:
        findings.append(
            Finding(
                category=CheckCategory.BOUNDARY_LOG,
                severity=Severity.WARN,
                message=f"CmdBoundarySnapshotRequest not available — ipc-command build may be incomplete ({exc})",
                fix_hint="Ensure all sibling tasks (ipc-command) have been merged and the package rebuilt.",
            )
        )
        return findings

    try:
        client = ControlClient(socket_path=socket_path, timeout=5.0)
        await client.connect()
        try:
            raw = await client._request(_BoundaryReq(), timeout=5.0)
            records: list[dict[str, Any]] = raw if isinstance(raw, list) else []
        finally:
            await client.disconnect()
    except Exception as exc:
        logger.debug("Boundary log check skipped: %s", exc)
        return findings

    if not records:
        return findings

    # Group records by boundary tag.
    from collections import defaultdict

    by_tag: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        tag = rec.get("boundary", "UNKNOWN")
        by_tag[tag].append(rec)

    for tag, tag_records in sorted(by_tag.items()):
        count = len(tag_records)

        # Determine last-seen timestamp (most recent ts field).
        # Normalize to UTC before comparing so mixed timezone offsets sort correctly.
        def _to_utc(ts: str) -> datetime:
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt.astimezone(UTC)
            except ValueError:
                return datetime.min.replace(tzinfo=UTC)

        ts_values = [str(r["ts"]) for r in tag_records if r.get("ts")]
        last_seen_str: str
        if ts_values:
            last_seen_str = max(ts_values, key=_to_utc)
        else:
            last_seen_str = "unknown"

        # Determine whether all records are transient.
        severities = {r.get("severity", "transient") for r in tag_records}
        all_transient = severities <= {"transient"}

        if count > _BOUNDARY_WARN_THRESHOLD:
            findings.append(
                Finding(
                    category=CheckCategory.BOUNDARY_LOG,
                    severity=Severity.WARN,
                    message=(
                        f"Boundary [{tag}]: {count} error records"
                        f" (last seen: {last_seen_str})"
                    ),
                    fix_hint=(
                        f"Check logs for repeated {tag} failures. "
                        "Run 'styrened doctor --offline' for offline diagnostics "
                        "or 'journalctl -u styrened' for full service logs."
                    ),
                )
            )
        elif all_transient:
            findings.append(
                Finding(
                    category=CheckCategory.BOUNDARY_LOG,
                    severity=Severity.OK,
                    message=(
                        f"Boundary [{tag}]: {count} transient record(s)"
                        f" (last seen: {last_seen_str})"
                    ),
                )
            )
        else:
            # Non-transient records but count ≤ threshold — still INFO.
            findings.append(
                Finding(
                    category=CheckCategory.BOUNDARY_LOG,
                    severity=Severity.OK,
                    message=(
                        f"Boundary [{tag}]: {count} record(s)"
                        f" (severities: {', '.join(sorted(severities))},"
                        f" last seen: {last_seen_str})"
                    ),
                )
            )

    return findings


# -----------------------------------------------------------------------------
# Orchestrator
# -----------------------------------------------------------------------------


async def run_doctor(offline: bool = False) -> DoctorReport:
    """Run all diagnostic checks and return a report.

    Args:
        offline: If True, skip network-dependent checks (PyPI version check).

    Returns:
        DoctorReport with all findings.
    """
    report = DoctorReport(
        checked_at=datetime.now(UTC).isoformat(),
    )

    # Load config once for all checks that need it.
    try:
        _loaded_config = load_core_config()
    except Exception:
        _loaded_config = None

    # Run synchronous checks
    report.findings.extend(check_version(offline=offline))
    report.findings.extend(check_rust_daemon())
    report.findings.extend(check_identity())
    report.findings.extend(check_config())
    report.findings.extend(check_reticulum())
    report.findings.extend(check_paths())

    # Run async checks
    report.findings.extend(await check_daemon())
    report.findings.extend(await check_boundary_log())
    report.findings.extend(await check_yggdrasil(config=_loaded_config))
    report.findings.extend(await check_i2p(config=_loaded_config))

    # Binary integrity checks for adapters
    if _loaded_config:
        report.findings.extend(await check_adapter_binaries(_loaded_config))

    # Populate summary info
    report.version_info = {"installed": __version__}

    identity_hash = get_operator_identity()
    identity_path = _resolve_identity_path()
    report.identity_info = {
        "identity_hash": identity_hash,
        "identity_path": str(identity_path) if identity_path else None,
    }

    return report


def apply_fixes(report: DoctorReport) -> list[Finding]:
    """Apply automatic fixes for findings that have fix_hints.

    Currently supports:
    - Creating missing directories

    Args:
        report: DoctorReport to fix.

    Returns:
        List of findings describing what was fixed.
    """
    fixed: list[Finding] = []

    for finding in report.findings:
        if finding.severity == Severity.OK:
            continue

        # Fix missing directories
        if finding.category == CheckCategory.PATHS and "directory missing" in finding.message:
            try:
                paths.ensure_directories()
                fixed.append(
                    Finding(
                        category=CheckCategory.PATHS,
                        severity=Severity.OK,
                        message="Created missing directories",
                    )
                )
                break  # ensure_directories creates all at once
            except Exception as e:
                fixed.append(
                    Finding(
                        category=CheckCategory.PATHS,
                        severity=Severity.ERROR,
                        message=f"Failed to create directories: {e}",
                    )
                )

    return fixed


def run_setup_wizard() -> list[Finding]:
    """Run interactive setup wizard for initial configuration.

    Prompts the user to:
    1. Adopt or create an operator identity
    2. Set a display name
    3. Choose a profile (operator/endpoint/hub)
    4. Save config

    Returns:
        List of findings describing actions taken.
    """
    from styrened.services.config import get_profile_defaults, save_core_config
    from styrened.services.reticulum import ensure_operator_identity

    results: list[Finding] = []

    # Ensure directories exist first
    paths.ensure_directories()

    # Step 1: Identity
    identity_hash = get_operator_identity()
    if not identity_hash:
        existing = detect_existing_lxmf_identity()
        if existing:
            app_name, app_path = existing
            print(f"\nFound existing identity from {app_name}: {app_path}")
            answer = input("Adopt this identity? [Y/n] ").strip().lower()
            if answer in ("", "y", "yes"):
                identity_hash = ensure_operator_identity(use_existing=True)
                results.append(
                    Finding(
                        category=CheckCategory.IDENTITY,
                        severity=Severity.OK,
                        message=f"Adopted identity from {app_name}: {identity_hash[:16]}...",
                    )
                )
            else:
                identity_hash = ensure_operator_identity(use_existing=False)
                results.append(
                    Finding(
                        category=CheckCategory.IDENTITY,
                        severity=Severity.OK,
                        message=f"Created new identity: {identity_hash[:16]}...",
                    )
                )
        else:
            identity_hash = ensure_operator_identity()
            results.append(
                Finding(
                    category=CheckCategory.IDENTITY,
                    severity=Severity.OK,
                    message=f"Created new identity: {identity_hash[:16]}...",
                )
            )
    else:
        results.append(
            Finding(
                category=CheckCategory.IDENTITY,
                severity=Severity.OK,
                message=f"Identity already exists: {identity_hash[:16]}...",
            )
        )

    # Step 2: Display name
    print()
    display_name = input("Display name for this node [styrene-node]: ").strip()
    if not display_name:
        display_name = "styrene-node"

    # Step 3: Profile
    print()
    print("Node profile:")
    print("  1. operator  - Personal mesh node (default)")
    print("  2. endpoint  - IoT / edge device")
    print("  3. hub       - Transport/propagation hub")
    profile_input = input("Choose profile [1]: ").strip()

    from styrened.models.config import Profile

    profile_map = {"1": Profile.OPERATOR, "2": Profile.ENDPOINT, "3": Profile.HUB, "": Profile.OPERATOR}
    profile = profile_map.get(profile_input, Profile.OPERATOR)

    # Step 4: Load or create config, apply settings, save
    try:
        config = load_core_config()
    except Exception:
        config = get_profile_defaults(profile)

    config.identity.display_name = display_name
    config.profile = profile

    save_core_config(config)
    results.append(
        Finding(
            category=CheckCategory.CONFIG,
            severity=Severity.OK,
            message=f"Config saved to {paths.config_file()}",
        )
    )

    return results
