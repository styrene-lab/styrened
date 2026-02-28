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

import logging
import os
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from styrened import __version__, paths
from styrened.services.config import load_core_config
from styrened.services.reticulum import (
    _resolve_identity_path,
    detect_existing_lxmf_identity,
    find_reticulum_config,
    get_identity_sharing_status,
    get_operator_identity,
    get_reticulum_config_state,
    is_reticulum_configured,
)

logger = logging.getLogger(__name__)


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

    # Try to ping the daemon
    try:
        from styrened.ipc import get_daemon_client

        client = await get_daemon_client()
        if client:
            try:
                pong = await client.ping(timeout=2.0)
                if pong:
                    findings.append(
                        Finding(
                            category=CheckCategory.DAEMON,
                            severity=Severity.OK,
                            message="Daemon is running and responsive",
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
        else:
            findings.append(
                Finding(
                    category=CheckCategory.DAEMON,
                    severity=Severity.WARN,
                    message="Could not connect to daemon (socket exists but connection failed)",
                    fix_hint="Check if daemon process is running",
                )
            )
    except Exception as e:
        logger.debug(f"Daemon ping failed: {e}")
        findings.append(
            Finding(
                category=CheckCategory.DAEMON,
                severity=Severity.WARN,
                message=f"Daemon connection error: {e}",
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

    # Run synchronous checks
    report.findings.extend(check_version(offline=offline))
    report.findings.extend(check_identity())
    report.findings.extend(check_config())
    report.findings.extend(check_reticulum())
    report.findings.extend(check_paths())

    # Run async checks
    report.findings.extend(await check_daemon())

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
