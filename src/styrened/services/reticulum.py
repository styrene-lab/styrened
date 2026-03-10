"""Reticulum configuration and device discovery service.

This module provides core Reticulum functionality for headless applications:

- Detecting if Reticulum is configured
- Reading identity from storage/identity
- Parsing interface configuration from config file
- Following Reticulum's config path priority order
- Managing operator identity
- Device discovery via RNS announces

Config path priority (matches Reticulum behavior):
1. Explicit override from config
2. /etc/reticulum (system-wide)
3. ~/.config/reticulum (XDG compliant)
4. ~/.reticulum (legacy default)

## Hash Architecture for RNS/LXMF

Understanding the three hash types is CRITICAL for message delivery:

1. **identity_hash** (16 bytes, 32 hex chars)
   - Hash of the RNS Identity's public key (Ed25519/X25519)
   - Computed as: `RNS.Identity.full_hash(public_key)[:16]`
   - Used for: `RNS.Identity.recall(hash, from_identity_hash=True)`
   - Stored by RNS after `RNS.Identity.remember()` calls
   - This is the KEY to look up an identity for sending messages

2. **destination_hash** (16 bytes, 32 hex chars)
   - Hash of identity + app_name + aspects
   - Computed as: `RNS.Identity.full_hash(identity_hash + app_name + aspects)[:16]`
   - Used for: Routing, display to users, path discovery
   - Examples:
     - Operator destination: hash(identity + "styrene_node" + "operator")
     - LXMF delivery: hash(identity + "lxmf" + "delivery")
   - SAME identity can have MULTIPLE different destination_hashes

3. **packet_hash** (32 bytes)
   - Hash of the announce packet itself
   - Used internally by RNS for deduplication
   - We pass this to `RNS.Identity.remember()` but don't use it otherwise

### Message Sending Flow

To send an LXMF message to a destination_hash:

1. Look up identity_hash from destination_hash (via NodeStore)
2. Call `RNS.Identity.recall(identity_hash, from_identity_hash=True)`
3. Create `RNS.Destination(identity, OUT, SINGLE, "lxmf", "delivery")`
4. Send message to that destination

### The Mismatch Problem

When we receive an announce for `styrene_node:operator`:
- We get destination_hash = hash(identity + "styrene_node" + "operator")
- We store identity_hash in NodeStore keyed by this destination_hash

When we want to send to LXMF:
- We have target's LXMF destination_hash = hash(identity + "lxmf" + "delivery")
- This is a DIFFERENT hash than the operator destination_hash
- NodeStore lookup by LXMF destination_hash fails!

### Solution

1. Parse LXMF destination from announce app_data (Styrene nodes include it)
2. Store LXMF destination -> identity_hash mapping in NodeStore
3. When sending, look up identity_hash by LXMF destination_hash
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from styrened import paths
from styrened.models.config import CoreConfig, DeploymentMode, MeshAccessMode
from styrened.models.mesh_device import DeviceType, MeshDevice, create_mesh_device
from styrened.models.reticulum import (
    ReticulumIdentity,
    ReticulumInterface,
    ReticulumNotConfiguredError,
)

# Conditional RNS import
if TYPE_CHECKING:
    import RNS
else:
    # Try to import RNS at runtime, but don't fail if not available
    try:
        import RNS  # type: ignore[import-untyped]
    except ImportError:
        RNS = None  # type: ignore[assignment]

# Setup logger
logger = logging.getLogger(__name__)

# Operator identity storage
SYSTEM_IDENTITY_PATH = Path("/etc/styrene/identity")

# Known LXMF application identity paths (in priority order)
# TODO(2026-04): Review identity detection paths - the LXMF ecosystem may have
# evolved with new applications or changed storage conventions. Check for:
# - New mesh chat applications (beyond NomadNet, Sideband, MeshChat)
# - Changed default paths in existing applications
# - XDG base directory adoption
# - Any standardization efforts in the Reticulum community
KNOWN_LXMF_IDENTITY_PATHS: list[tuple[str, Path]] = [
    # NomadNet - checks XDG, system, and legacy paths
    ("NomadNet", Path.home() / ".nomadnetwork" / "storage" / "identity"),
    ("NomadNet (XDG)", Path.home() / ".config" / "nomadnetwork" / "storage" / "identity"),
    ("NomadNet (system)", Path("/etc/nomadnetwork/storage/identity")),
    # Sideband - Android/desktop LXMF client
    ("Sideband", Path.home() / ".config" / "sideband" / "identity"),
    ("Sideband (legacy)", Path.home() / ".sideband" / "identity"),
    # MeshChat
    ("MeshChat", Path.home() / ".config" / "meshchat" / "identity"),
    ("MeshChat (legacy)", Path.home() / ".meshchat" / "identity"),
    # Generic LXMF storage
    ("LXMF", Path.home() / ".config" / "lxmf" / "identity"),
    ("LXMF (legacy)", Path.home() / ".lxmf" / "identity"),
]

# Preferred identity paths for symlinking (one per application, XDG preferred)
# These are the paths we'll create symlinks at when sharing styrened's identity
LXMF_SYMLINK_TARGETS: dict[str, Path] = {
    "nomadnet": Path.home() / ".nomadnetwork" / "storage" / "identity",
    "sideband": Path.home() / ".config" / "sideband" / "identity",
    "meshchat": Path.home() / ".config" / "meshchat" / "identity",
    "lxmf": Path.home() / ".config" / "lxmf" / "identity",
}


def get_reticulum_config_paths() -> list[Path]:
    """Return Reticulum config search paths in priority order.

    Reticulum searches these locations for configuration:
    1. /etc/reticulum (system-wide)
    2. ~/.config/reticulum (XDG compliant)
    3. ~/.reticulum (legacy default)

    Returns:
        List of paths to check, in priority order.
    """
    return [
        Path("/etc/reticulum"),
        Path.home() / ".config" / "reticulum",
        Path.home() / ".reticulum",
    ]


def find_reticulum_config(override: Path | None = None) -> Path | None:
    """Find the active Reticulum configuration directory.

    Checks the override path first (if provided), then searches
    standard locations in priority order.

    Args:
        override: If provided, check this path first.

    Returns:
        Path to Reticulum config directory, or None if not found.
    """
    # Check override first
    if override and is_reticulum_configured(config_dir=override):
        return override

    # Search standard paths in priority order
    for path in get_reticulum_config_paths():
        if is_reticulum_configured(config_dir=path):
            return path

    return None


def _get_default_config_dir() -> Path:
    """Return the default Reticulum configuration directory.

    This returns the legacy default (~/.reticulum). For proper
    priority-based lookup, use find_reticulum_config() instead.
    """
    return Path.home() / ".reticulum"


def is_reticulum_configured(config_dir: Path | None = None) -> bool:
    """Check if Reticulum is properly configured.

    A proper configuration requires:
    1. The configuration directory exists
    2. The config file exists

    Note: We only check for the config file, not identity files, because:
    - RNS daemon creates storage/transport_identity automatically
    - Per-app identities are created on first use
    - Presence of config indicates intentional RNS setup

    Args:
        config_dir: Path to Reticulum config directory. Defaults to ~/.reticulum.

    Returns:
        True if Reticulum is configured, False otherwise.
    """
    if config_dir is None:
        config_dir = _get_default_config_dir()

    if not config_dir.exists():
        return False

    config_file = config_dir / "config"
    return config_file.exists()


def _read_identity(config_dir: Path) -> ReticulumIdentity:
    """Read and parse the Reticulum identity file.

    The identity file contains binary key material. We read a portion
    of it and convert to hex for display purposes.

    Args:
        config_dir: Path to Reticulum config directory.

    Returns:
        ReticulumIdentity with the hex-encoded address.

    Raises:
        ReticulumNotConfiguredError: If identity file doesn't exist.
    """
    identity_file = config_dir / "storage" / "identity"

    if not identity_file.exists():
        raise ReticulumNotConfiguredError()

    try:
        identity_bytes = identity_file.read_bytes()
    except OSError as e:
        raise ReticulumNotConfiguredError() from e

    # Convert to hex string for the address
    # Reticulum identities are typically 32+ bytes
    address = identity_bytes[:32].hex()

    return ReticulumIdentity(address=address)


def _parse_interfaces(config_file: Path) -> list[ReticulumInterface]:
    """Parse interface definitions from Reticulum config file.

    Reticulum uses a ConfigParser-like format with [[interface_name]] sections
    for interfaces. We parse these to extract interface information.

    Args:
        config_file: Path to the Reticulum config file.

    Returns:
        List of ReticulumInterface objects.
    """
    interfaces: list[ReticulumInterface] = []

    try:
        content = config_file.read_text()
    except OSError:
        return interfaces

    # Reticulum config uses [[section]] for interfaces
    # We need to parse this non-standard format
    # Pattern: [[interface_name]] followed by key=value pairs
    interface_pattern = re.compile(
        r"\[\[([^\]]+)\]\]\s*\n((?:[^[\n].*\n)*)",
        re.MULTILINE,
    )

    for match in interface_pattern.finditer(content):
        name = match.group(1).strip()
        block = match.group(2)

        # Parse key=value pairs in the block
        interface_type = "Unknown"
        enabled = True

        for line in block.split("\n"):
            line = line.strip()
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip().lower()
                value = value.strip()

                if key == "type":
                    interface_type = value
                elif key == "enabled":
                    enabled = value.lower() in ("true", "yes", "1")

        interfaces.append(
            ReticulumInterface(
                name=name,
                interface_type=interface_type,
                enabled=enabled,
            )
        )

    return interfaces


def get_reticulum_config_state(config_dir: Path | None = None) -> Any:
    """Read and return the complete Reticulum configuration.

    This function reads the Reticulum configuration directory and returns
    a ReticulumState object containing the identity and interface information.

    If config_dir is not specified, searches standard locations in priority
    order: /etc/reticulum, ~/.config/reticulum, ~/.reticulum

    Note: Returns ReticulumState (from models/reticulum.py), not ReticulumConfig
    (from models/config.py). Different concepts.

    Args:
        config_dir: Path to Reticulum config directory, or None to auto-detect.

    Returns:
        ReticulumState with identity, interfaces, and config path.

    Raises:
        ReticulumNotConfiguredError: If Reticulum is not properly configured.
    """
    from styrened.models.reticulum import ReticulumState

    # If explicit path given, use it; otherwise search standard locations
    resolved_dir = config_dir if config_dir is not None else find_reticulum_config()

    if resolved_dir is None or not is_reticulum_configured(config_dir=resolved_dir):
        raise ReticulumNotConfiguredError()

    identity = _read_identity(resolved_dir)
    config_file = resolved_dir / "config"
    interfaces = _parse_interfaces(config_file)

    return ReticulumState(
        identity=identity,
        interfaces=interfaces,
        config_path=resolved_dir,
    )


# Operator Identity Management


def detect_existing_lxmf_identity() -> tuple[str, Path] | None:
    """Detect existing LXMF identity from other applications.

    Searches known LXMF application paths for an existing identity file.
    This allows styrened to reuse an identity from NomadNet, Sideband,
    MeshChat, or other LXMF applications.

    Returns:
        Tuple of (application_name, path) if found, None otherwise.
    """
    for app_name, path in KNOWN_LXMF_IDENTITY_PATHS:
        if path.exists() and path.is_file():
            try:
                # Verify it's a valid identity file (should be readable)
                content = path.read_bytes()
                if len(content) >= 32:  # Minimum size for RNS identity
                    logger.debug(f"Found existing identity from {app_name} at {path}")
                    return (app_name, path)
            except (OSError, PermissionError) as e:
                logger.debug(f"Cannot read identity at {path}: {e}")
                continue
    return None


@dataclass
class SymlinkResult:
    """Result of a symlink operation."""

    app: str
    path: Path
    success: bool
    message: str
    was_existing: bool = False  # True if path already existed (file/symlink)
    was_symlink: bool = False  # True if was already a symlink
    backed_up_to: Path | None = None  # Backup path if original was backed up


def get_identity_sharing_status() -> dict[str, dict[str, Any]]:
    """Get the current identity sharing status for all known LXMF applications.

    Returns:
        Dictionary mapping app names to their status:
        - path: The identity path for this app
        - exists: Whether the path exists
        - is_symlink: Whether it's a symlink
        - points_to_styrened: Whether it points to styrened's identity
        - symlink_target: The symlink target if it's a symlink
    """
    status: dict[str, dict[str, Any]] = {}

    # Build known paths once (not per-app)
    known_paths: set[Path] = {SYSTEM_IDENTITY_PATH, paths.identity_file()}
    active = _resolve_identity_path()
    if active:
        known_paths.add(active.resolve())

    for app, path in LXMF_SYMLINK_TARGETS.items():
        app_status: dict[str, Any] = {
            "path": path,
            "exists": path.exists() or path.is_symlink(),  # is_symlink for broken links
            "is_symlink": path.is_symlink(),
            "points_to_styrened": False,
            "symlink_target": None,
        }

        if path.is_symlink():
            try:
                raw_target = path.readlink()
                if not raw_target.is_absolute():
                    raw_target = (path.parent / raw_target).resolve()
                app_status["symlink_target"] = raw_target
                app_status["points_to_styrened"] = raw_target in known_paths
            except OSError:
                pass  # Broken symlink

        status[app] = app_status

    return status


def share_identity_with_apps(
    apps: list[str] | None = None,
    backup: bool = True,
    force: bool = False,
) -> list[SymlinkResult]:
    """Create symlinks from other LXMF applications to styrened's identity.

    This makes styrened's identity the source of truth, with other applications
    (NomadNet, Sideband, MeshChat) symlinking to it. This is the inverse of
    detect_existing_lxmf_identity() - instead of styrened adopting an existing
    identity, other apps adopt styrened's identity.

    Args:
        apps: List of app names to create symlinks for. If None, all known apps.
              Valid names: "nomadnet", "sideband", "meshchat", "lxmf"
        backup: If True, backup existing identity files before replacing.
        force: If True, replace existing files/symlinks. If False, skip existing.

    Returns:
        List of SymlinkResult objects describing what was done for each app.

    Raises:
        FileNotFoundError: If styrened's identity doesn't exist yet.
    """
    active_identity = _resolve_identity_path()
    if not active_identity:
        raise FileNotFoundError(
            "Styrened identity not found at any known path. "
            "Run 'styrened identity --create' first."
        )

    target_apps = apps if apps else list(LXMF_SYMLINK_TARGETS.keys())
    results: list[SymlinkResult] = []

    for app in target_apps:
        if app not in LXMF_SYMLINK_TARGETS:
            results.append(
                SymlinkResult(
                    app=app,
                    path=Path(),
                    success=False,
                    message=f"Unknown application: {app}",
                )
            )
            continue

        path = LXMF_SYMLINK_TARGETS[app]

        # Check if already correctly symlinked
        if path.is_symlink():
            try:
                if path.resolve() == active_identity.resolve():
                    results.append(
                        SymlinkResult(
                            app=app,
                            path=path,
                            success=True,
                            message="Already symlinked to styrened",
                            was_existing=True,
                            was_symlink=True,
                        )
                    )
                    continue
            except OSError:
                pass  # Broken symlink, will be replaced

        # Handle existing file or symlink
        path_exists = path.exists() or path.is_symlink()
        backed_up_to: Path | None = None

        if path_exists:
            if not force:
                results.append(
                    SymlinkResult(
                        app=app,
                        path=path,
                        success=False,
                        message=f"Path exists, use force=True to replace: {path}",
                        was_existing=True,
                        was_symlink=path.is_symlink(),
                    )
                )
                continue

            # Backup or remove existing
            if backup and path.exists() and not path.is_symlink():
                backed_up_to = path.with_suffix(".key.bak")
                counter = 1
                while backed_up_to.exists():
                    backed_up_to = path.with_suffix(f".key.bak.{counter}")
                    counter += 1
                try:
                    path.rename(backed_up_to)
                    logger.info(f"Backed up {path} to {backed_up_to}")
                except OSError as e:
                    results.append(
                        SymlinkResult(
                            app=app,
                            path=path,
                            success=False,
                            message=f"Failed to backup: {e}",
                            was_existing=True,
                        )
                    )
                    continue
            else:
                # Remove existing symlink or file (if no backup requested)
                try:
                    path.unlink()
                except OSError as e:
                    results.append(
                        SymlinkResult(
                            app=app,
                            path=path,
                            success=False,
                            message=f"Failed to remove existing: {e}",
                            was_existing=True,
                            was_symlink=path.is_symlink(),
                        )
                    )
                    continue

        # Create parent directories
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            results.append(
                SymlinkResult(
                    app=app,
                    path=path,
                    success=False,
                    message=f"Failed to create directory: {e}",
                )
            )
            continue

        # Create symlink
        try:
            path.symlink_to(active_identity)
            logger.info(f"Created symlink: {path} -> {active_identity}")
            results.append(
                SymlinkResult(
                    app=app,
                    path=path,
                    success=True,
                    message=f"Symlinked to {active_identity}",
                    was_existing=path_exists,
                    backed_up_to=backed_up_to,
                )
            )
        except OSError as e:
            results.append(
                SymlinkResult(
                    app=app,
                    path=path,
                    success=False,
                    message=f"Failed to create symlink: {e}",
                )
            )

    return results


def unshare_identity_from_apps(
    apps: list[str] | None = None,
    restore_backup: bool = True,
) -> list[SymlinkResult]:
    """Remove symlinks from other LXMF applications to styrened's identity.

    This reverses share_identity_with_apps(), removing symlinks and optionally
    restoring backed-up identity files.

    Args:
        apps: List of app names to remove symlinks for. If None, all known apps.
        restore_backup: If True, restore .key.bak files if they exist.

    Returns:
        List of SymlinkResult objects describing what was done for each app.
    """
    target_apps = apps if apps else list(LXMF_SYMLINK_TARGETS.keys())
    results: list[SymlinkResult] = []

    # Build known paths once (not per-app)
    known_paths: set[Path] = {SYSTEM_IDENTITY_PATH, paths.identity_file()}
    active = _resolve_identity_path()
    if active:
        known_paths.add(active.resolve())

    for app in target_apps:
        if app not in LXMF_SYMLINK_TARGETS:
            results.append(
                SymlinkResult(
                    app=app,
                    path=Path(),
                    success=False,
                    message=f"Unknown application: {app}",
                )
            )
            continue

        path = LXMF_SYMLINK_TARGETS[app]

        # Check if it's a symlink pointing to styrened
        if not path.is_symlink():
            if path.exists():
                results.append(
                    SymlinkResult(
                        app=app,
                        path=path,
                        success=False,
                        message="Not a symlink, leaving unchanged",
                        was_existing=True,
                    )
                )
            else:
                results.append(
                    SymlinkResult(
                        app=app,
                        path=path,
                        success=True,
                        message="No symlink exists",
                    )
                )
            continue

        # Verify it points to a known styrene identity path before removing.
        # Use readlink (not resolve) so this works even if the target was deleted.
        try:
            raw_target = path.readlink()
            # Normalize to absolute for comparison
            if not raw_target.is_absolute():
                raw_target = (path.parent / raw_target).resolve()
            if raw_target not in known_paths:
                results.append(
                    SymlinkResult(
                        app=app,
                        path=path,
                        success=False,
                        message="Symlink doesn't point to styrened, leaving unchanged",
                        was_existing=True,
                        was_symlink=True,
                    )
                )
                continue
        except OSError:
            pass  # Can't read symlink target, remove it anyway

        # Remove the symlink
        try:
            path.unlink()
            logger.info(f"Removed symlink: {path}")
        except OSError as e:
            results.append(
                SymlinkResult(
                    app=app,
                    path=path,
                    success=False,
                    message=f"Failed to remove symlink: {e}",
                    was_existing=True,
                    was_symlink=True,
                )
            )
            continue

        # Try to restore backup
        restored_from: Path | None = None
        if restore_backup:
            # Look for backup files
            backup_path = path.with_suffix(".key.bak")
            if backup_path.exists():
                try:
                    backup_path.rename(path)
                    restored_from = backup_path
                    logger.info(f"Restored backup: {backup_path} -> {path}")
                except OSError as e:
                    logger.warning(f"Failed to restore backup {backup_path}: {e}")

        message = "Symlink removed"
        if restored_from:
            message += f", restored from {restored_from}"

        results.append(
            SymlinkResult(
                app=app,
                path=path,
                success=True,
                message=message,
                was_existing=True,
                was_symlink=True,
                backed_up_to=restored_from,  # Reusing field for "restored from"
            )
        )

    return results


def _resolve_identity_path(config_path: Path | None = None) -> Path | None:
    """Find the first existing identity file in priority order.

    Resolution order:
    1. Config override (explicit operator_identity_path)
    2. /etc/styrene/identity (OS-level, generated at NixOS activation)
    3. paths.identity_file() (user-level canonical path)

    Args:
        config_path: Explicit path from config override, or None.

    Returns:
        Path to existing identity file, or None if no identity exists yet.
    """
    candidates: list[Path] = []
    if config_path:
        candidates.append(config_path)
    candidates.append(SYSTEM_IDENTITY_PATH)
    candidates.append(paths.identity_file())

    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def ensure_operator_identity(
    use_existing: bool = True,
    config_path: Path | None = None,
    identity_config: Any = None,
) -> str:
    """Ensure operator has a Reticulum identity.

    Checks for an existing identity in priority order:
    0. YubiKey derivation (if identity_config.provider == "yubikey")
    1. Config override (explicit operator_identity_path)
    2. /etc/styrene/identity (system-level, generated at NixOS activation)
    3. ~/.config/styrene/identity (user-level)
    4. Detect from LXMF apps (NomadNet, Sideband, MeshChat)
    5. Generate new at user-level path

    Args:
        use_existing: If True (default), detect and copy existing LXMF identities
                      from other applications. Set to False to always create new.
        config_path: Explicit identity path from config override.
        identity_config: Optional IdentityConfig with provider and yubikey settings.

    Returns:
        Hex-encoded identity hash (destination address) - 32 hex characters (16 bytes).

    Raises:
        ImportError: If RNS library is not available.
        ValueError: If existing identity file is corrupt or invalid.
    """
    if not RNS:
        raise ImportError("RNS library not available. Install with: pip install rns")

    # YubiKey provider: derive identity from hardware token
    if identity_config and getattr(identity_config, "provider", "file") == "yubikey":
        from styrened.services.yubikey import derive_identity_bytes

        yk_config = identity_config.yubikey
        identity_bytes = derive_identity_bytes(
            credential_id_b64=yk_config.credential_id,
            rp_id=yk_config.rp_id,
            require_touch=yk_config.require_touch,
        )
        identity = RNS.Identity.from_bytes(identity_bytes)
        if identity is None:
            raise ValueError("Failed to create RNS identity from YubiKey-derived bytes")
        logger.info(f"Loaded operator identity from YubiKey (rp_id={yk_config.rp_id})")
        return str(identity.hash.hex())

    # Check for existing identity (config override -> system -> user)
    existing_path = _resolve_identity_path(config_path)
    if existing_path:
        try:
            identity = RNS.Identity.from_file(str(existing_path))
        except Exception as e:
            identity = None
            logger.warning(f"Exception loading identity from {existing_path}: {e}")

        if identity is not None:
            logger.info(f"Loaded operator identity from {existing_path}")
            return str(identity.hash.hex())

        # Corrupt or unparseable — back up and fall through to regenerate
        backup_path = existing_path.with_suffix(".key.corrupt")
        try:
            existing_path.rename(backup_path)
            logger.warning(
                f"Identity file {existing_path} is corrupt — "
                f"backed up to {backup_path}, regenerating"
            )
        except OSError as e:
            logger.error(f"Could not back up corrupt identity {existing_path}: {e}")
            raise ValueError(
                f"Identity file {existing_path} is corrupt and could not be "
                f"backed up ({e}). Remove it manually: rm {existing_path}"
            ) from e

    # No identity found at any standard path - check LXMF apps
    if use_existing:
        existing = detect_existing_lxmf_identity()
        if existing:
            app_name, source_path = existing
            logger.info(
                f"Found existing identity from {app_name} at {source_path}, "
                f"copying to {paths.identity_file()}"
            )

            # Load and verify the existing identity
            identity = RNS.Identity.from_file(str(source_path))
            if identity is not None:
                # Ensure parent directory exists
                paths.identity_file().parent.mkdir(parents=True, exist_ok=True)

                # Save a copy for styrened
                identity.to_file(str(paths.identity_file()))

                logger.info(f"Identity imported from {app_name}: {identity.hash.hex()[:16]}...")
                return str(identity.hash.hex())
            else:
                logger.warning(f"Could not load identity from {source_path}, creating new identity")

    # Generate new RNS.Identity with X25519/Ed25519 keys
    identity = RNS.Identity(create_keys=True)

    # Ensure parent directory exists
    paths.identity_file().parent.mkdir(parents=True, exist_ok=True)

    # Save identity to file
    identity.to_file(str(paths.identity_file()))

    logger.info(f"Created new operator identity: {identity.hash.hex()[:16]}...")
    return str(identity.hash.hex())


def _load_identity_config() -> Any:
    """Load IdentityConfig from core config, if available.

    Returns:
        IdentityConfig or None if config can't be loaded.
    """
    try:
        from styrened.services.config import load_core_config
        return load_core_config().identity
    except Exception:
        return None


def get_operator_identity_object() -> Any:
    """Get the operator identity as RNS.Identity object.

    Provider-aware: uses YubiKey derivation when provider == "yubikey",
    otherwise loads from file (system/user path).

    Returns:
        RNS.Identity object, or None if not initialized or RNS not available.
    """
    if not RNS:
        return None

    identity_config = _load_identity_config()

    # YubiKey provider: derive from hardware token
    if identity_config and getattr(identity_config, "provider", "file") == "yubikey":
        try:
            from styrened.services.yubikey import derive_identity_bytes
            yk_config = identity_config.yubikey
            identity_bytes = derive_identity_bytes(
                credential_id_b64=yk_config.credential_id,
                rp_id=yk_config.rp_id,
                require_touch=yk_config.require_touch,
            )
            return RNS.Identity.from_bytes(identity_bytes)
        except Exception as e:
            logger.warning(f"YubiKey identity derivation failed: {e}")
            return None

    # File provider: resolve from disk
    identity_path = _resolve_identity_path()
    if not identity_path:
        return None

    return RNS.Identity.from_file(str(identity_path))


def get_operator_identity() -> str | None:
    """Get the operator identity hash if it exists.

    Provider-aware: uses YubiKey derivation when provider == "yubikey",
    otherwise loads from file (system/user path).

    Returns:
        Hex-encoded identity hash (32 hex characters), or None if identity
        is unavailable.
    """
    if not RNS:
        logger.warning("RNS library not available, cannot compute identity hash")
        return None

    try:
        identity = get_operator_identity_object()
    except Exception as e:
        logger.warning(f"Failed to load operator identity: {e}")
        return None

    if identity is None:
        return None

    try:
        return str(identity.hash.hex())
    except Exception as e:
        logger.warning(f"Failed to get identity hash: {e}")
        return None


# Device Discovery via RNS Announces


# Known RNS application aspects for announce type detection.
# Each entry maps (app_name, *aspects) to a DeviceType.
# Used to compute expected destination hashes and match against received announces.
KNOWN_ASPECTS: list[tuple[tuple[str, ...], DeviceType]] = [
    (("lxmf", "delivery"), DeviceType.LXMF_PEER),
    (("lxmf", "propagation"), DeviceType.PROPAGATION_NODE),
    (("nomadnetwork", "node"), DeviceType.NOMADNET_NODE),
]


class StyreneAnnounceHandler:
    """Handles Reticulum announces for mesh device discovery.

    This handler listens to ALL announces on the network (no aspect filter)
    and tracks discovered devices as MeshDevice objects. Supports Styrene nodes,
    RNodes, and generic Reticulum announces.

    IMPORTANT: We explicitly opt-out of receiving path responses to avoid
    interfering with RNS path discovery. Path responses are a special type
    of announce used internally by RNS for routing, and consuming them in
    our handler would break message delivery.

    Hash Types (see module docstring for full explanation):
    - identity_hash: Hash of public key, used for RNS.Identity.recall()
    - destination_hash: Hash of identity+app+aspects, used for routing
    - LXMF destination_hash: Different from operator destination_hash but same identity
    """

    def __init__(
        self,
        callback: Callable[[MeshDevice], None] | None = None,
        node_store: Any | None = None,
        access_mode: MeshAccessMode | None = None,
        allowed_peers: set[str] | None = None,
        ygg_adapter: Any | None = None,
        ygg_config: Any | None = None,
        direct_link_service: Any | None = None,
    ):
        """Initialize announce handler.

        Args:
            callback: Optional callback to invoke when a device is discovered/updated.
            node_store: Optional node store for persistence (dependency injection).
            access_mode: Mesh admission policy (OPEN or ALLOWLIST).  Defaults to
                OPEN so that existing callers that don't pass a config are
                unaffected.
            allowed_peers: Set of lower-cased 32-char hex identity hashes
                permitted when *access_mode* is ALLOWLIST.
            ygg_adapter: Optional YggdrasilAdapter instance for capability
                detection and peer bootstrapping.
            ygg_config: Optional YggdrasilConfig (peer_discovery / bootstrap_from_rns).
            direct_link_service: Optional DirectLinkService for /meta fetches.
        """
        self.callback = callback
        self.node_store = node_store
        self.access_mode: MeshAccessMode = access_mode or MeshAccessMode.OPEN
        self._allowed_peers: set[str] = (
            {h.lower() for h in allowed_peers} if allowed_peers else set()
        )
        self._ygg_adapter = ygg_adapter
        self._ygg_config = ygg_config
        self._direct_link_service = direct_link_service
        self.aspect_filter = None  # Listen to ALL announces
        self.receive_path_responses = False  # Don't interfere with RNS path discovery
        self.discovered_devices: dict[str, MeshDevice] = {}

    def received_announce(
        self,
        destination_hash: bytes,
        announced_identity: Any,  # RNS.Identity
        app_data: bytes | None,
        announce_packet_hash: bytes | None = None,
        is_path_response: bool | None = None,
    ) -> None:
        """Handle received announce from RNS.Transport.

        This method processes announces and stores the identity mapping needed
        for sending LXMF messages later. The critical insight is that we need
        to store BOTH the operator destination -> identity mapping AND the
        LXMF destination -> identity mapping.

        Hash Types:
        - destination_hash: Hash of the destination (identity + app + aspects).
                           For operator announces: hash(identity + "styrene_node" + "operator")
                           For LXMF announces: hash(identity + "lxmf" + "delivery")
        - announced_identity.hash: Hash of just the public key (identity hash).
                                   This is what RNS.Identity.recall() needs.

        Args:
            destination_hash: Hash of the announcing destination (operator or LXMF).
            announced_identity: RNS.Identity of the announcer.
            app_data: Optional application data from the announce.
            announce_packet_hash: Hash of the announce packet (for RNS internal use).
            is_path_response: Whether this is a path response - skip these to not
                              interfere with RNS path discovery.
        """
        # Skip path responses - these are internal RNS routing messages
        # that we must not consume or we'll break message delivery
        if is_path_response:
            return

        dest_hash_hex = destination_hash.hex()

        # Extract identity hash from the announced identity
        # This is CRITICAL - we need this to send messages later
        identity_hash_hex = announced_identity.hash.hex() if announced_identity else dest_hash_hex

        logger.debug(
            f"[HASH] Announce received: "
            f"destination_hash={dest_hash_hex[:16]}... (routing), "
            f"identity_hash={identity_hash_hex[:16]}... (for recall)"
        )

        # Admission control: default-deny when access_mode is ALLOWLIST
        if self.access_mode == MeshAccessMode.ALLOWLIST:
            if identity_hash_hex.lower() not in self._allowed_peers:
                logger.debug(
                    f"[ACCESS] Blocked announce from identity "
                    f"{identity_hash_hex[:16]}... — not in allowlist"
                )
                return

        # Check if we've seen this device before
        existing = self.discovered_devices.get(dest_hash_hex)
        announce_count = existing.announce_count + 1 if existing else 1

        # Remember the identity so RNS.Identity.recall() will work later
        # RNS stores identities keyed by identity_hash, not destination_hash
        if announced_identity is not None:
            try:
                pub_key = announced_identity.get_public_key()
                logger.info(
                    f"[HASH] Storing identity: identity_hash={identity_hash_hex[:16]}... "
                    f"(source: announce from destination {dest_hash_hex[:16]}...)"
                )
                if pub_key:
                    # Use destination_hash as packet_hash if not provided
                    pkt_hash = announce_packet_hash if announce_packet_hash else destination_hash
                    RNS.Identity.remember(
                        packet_hash=pkt_hash,
                        destination_hash=destination_hash,
                        public_key=pub_key,
                        app_data=app_data,
                    )
                    logger.debug(
                        f"[HASH] Called RNS.Identity.remember(): "
                        f"destination_hash={dest_hash_hex[:16]}..., "
                        f"identity will be recalled via identity_hash={identity_hash_hex[:16]}..."
                    )

                    # Verify it worked - MUST use from_identity_hash=True
                    test_recall = RNS.Identity.recall(
                        announced_identity.hash, from_identity_hash=True
                    )
                    if test_recall:
                        logger.info(
                            f"[HASH] Recall verified: identity_hash={identity_hash_hex[:16]}... -> OK"
                        )
                    else:
                        logger.warning(
                            f"[HASH] Recall FAILED: identity_hash={identity_hash_hex[:16]}... -> None"
                        )
            except Exception as e:
                logger.warning(f"Could not remember identity: {e}")

        # Detect announce type by computing expected destination hashes
        # for known application aspects and matching against the received hash.
        detected_type: DeviceType | None = None
        if announced_identity is not None:
            for aspect_tuple, dtype in KNOWN_ASPECTS:
                try:
                    expected = RNS.Destination.hash(
                        announced_identity, aspect_tuple[0], *aspect_tuple[1:]
                    )
                    if destination_hash == expected:
                        detected_type = dtype
                        logger.debug(
                            f"[ASPECT] Matched {'.'.join(aspect_tuple)} -> {dtype.value} "
                            f"for {dest_hash_hex[:16]}..."
                        )
                        break
                except Exception:
                    pass

        # Create/update MeshDevice with both hashes
        # The create_mesh_device function extracts LXMF destination from app_data
        device = create_mesh_device(
            destination_hash=dest_hash_hex,
            identity_hash=identity_hash_hex,
            app_data=app_data,
            announce_count=announce_count,
            aspect_hint=detected_type,
        )

        # Log LXMF destination if present (parsed from app_data by create_mesh_device)
        if device.lxmf_destination_hash:
            logger.info(
                f"[HASH] Styrene node has LXMF destination: "
                f"lxmf_dest={device.lxmf_destination_hash[:16]}..., "
                f"identity_hash={identity_hash_hex[:16]}... (same identity, different destination)"
            )

        # Cross-reference: if this is an LXMF peer, check if same identity
        # has a known Styrene operator announce.  Upgrade to STYRENE_NODE so
        # nodes discovered only via LXMF relay still appear in the mesh table.
        if device.device_type == DeviceType.LXMF_PEER and identity_hash_hex:
            for existing in self.discovered_devices.values():
                if (
                    existing.identity_hash == identity_hash_hex
                    and existing.device_type == DeviceType.STYRENE_NODE
                ):
                    device.device_type = DeviceType.STYRENE_NODE
                    # Carry over Styrene metadata the LXMF announce lacks
                    if existing.version:
                        device.version = existing.version
                    if existing.capabilities:
                        device.capabilities = existing.capabilities
                    if existing.short_name:
                        device.short_name = existing.short_name
                    logger.info(
                        f"[UPGRADE] LXMF peer {device.name} upgraded to STYRENE_NODE "
                        f"(matched identity {identity_hash_hex[:16]}...)"
                    )
                    break

        # Look up receiving interface and next-hop from RNS path table
        # path_table[destination_hash] = [timestamp, received_from, hops, expires, blobs, interface, packet_hash]
        try:
            path_entry = RNS.Transport.path_table.get(destination_hash)
            if path_entry and len(path_entry) > 5:
                if path_entry[5] is not None:
                    iface = path_entry[5]
                    iface_name = getattr(iface, "name", None) or ""

                    # Include next-hop transport hash for multi-hub disambiguation
                    next_hop = path_entry[1] if len(path_entry) > 1 else None
                    if next_hop and isinstance(next_hop, bytes) and len(next_hop) > 0:
                        next_hop_short = next_hop.hex()[:8]
                        via_label = f"{iface_name} → {next_hop_short}" if iface_name else next_hop_short
                    elif iface_name:
                        via_label = iface_name
                    else:
                        via_label = None

                    if via_label:
                        device.discovered_via = via_label
                        logger.debug(
                            f"[IFACE] {device.name} discovered via: {via_label}"
                        )
                if len(path_entry) > 2 and path_entry[2] is not None:
                    device.hops = int(path_entry[2])
        except Exception as e:
            logger.debug(f"Could not determine path info: {e}")

        # ── Overlay capability detection ────────────────────────────────────
        # Addresses remain unknown until /meta fetch; announces carry only bits.
        try:
            from styrened.models.capabilities import (
                CAPABILITY_I2P,
                CAPABILITY_YGGDRASIL,
                has_capability,
            )
            from styrened.models.config import PeerDiscovery

            if has_capability(device.capabilities, CAPABILITY_I2P):
                device.b32_address = None
                logger.debug(
                    "[I2P] Peer %s advertises I2P capability",
                    identity_hash_hex[:16],
                )

            if has_capability(device.capabilities, CAPABILITY_YGGDRASIL):
                device.ygg_address = None  # address fetched via /meta on demand
                logger.debug(
                    "[YGG] Peer %s advertises Yggdrasil capability",
                    identity_hash_hex[:16],
                )

                # EAGER bootstrap: fetch /meta and call add_peer() asynchronously
                cfg = self._ygg_config
                if (
                    cfg is not None
                    and cfg.bootstrap_from_rns
                    and cfg.peer_discovery == PeerDiscovery.EAGER
                    and self._ygg_adapter is not None
                    and self._ygg_adapter.get_local_address() is not None
                ):
                    import asyncio

                    asyncio.create_task(
                        _bootstrap_ygg_peer(
                            identity_hash_hex,
                            device.lxmf_destination_hash or dest_hash_hex,
                            self._ygg_adapter,
                            direct_link=self._direct_link_service,
                        )
                    )
                    logger.debug(
                        "[YGG] Dispatched bootstrap task for peer %s",
                        identity_hash_hex[:16],
                    )
        except Exception as _overlay_err:
            logger.debug("[OVERLAY] Capability detection error: %s", _overlay_err)

        self.discovered_devices[dest_hash_hex] = device

        # Persist to store if available
        # NodeStore will index by both operator destination and LXMF destination
        if self.node_store is not None:
            try:
                self.node_store.save_node(device)
                logger.debug(
                    f"[HASH] Persisted to NodeStore: "
                    f"operator_dest={dest_hash_hex[:16]}..., "
                    f"lxmf_dest={device.lxmf_destination_hash[:16] + '...' if device.lxmf_destination_hash else 'None'}, "
                    f"identity={identity_hash_hex[:16]}..."
                )
            except Exception as e:
                logger.warning(f"Failed to persist node to store: {e}")

        if self.callback:
            self.callback(device)


async def _bootstrap_ygg_peer(
    identity_hash: str,
    lxmf_dest_hash: str,
    ygg_adapter: Any,
    direct_link: Any | None = None,
) -> None:
    """Fetch /meta from a peer and add it as a Yggdrasil peer.

    Silently ignores all errors — this is a best-effort operation.
    The next announce cycle will retry automatically.

    Args:
        identity_hash: Hex identity hash of the remote peer (for logging).
        lxmf_dest_hash: LXMF delivery destination hash used to open a
            DirectLink and request /meta.
        ygg_adapter: Running YggdrasilAdapter instance.
        direct_link: Optional DirectLinkService override (for testing).
    """
    try:
        if direct_link is None:
            logger.debug("[YGG] No DirectLinkService — skipping bootstrap for %s", identity_hash[:16])
            return

        meta = await direct_link.fetch_meta(lxmf_dest_hash)
        if meta is None:
            logger.debug("[YGG] /meta returned None for %s", identity_hash[:16])
            return

        ygg_address = meta.get("ygg_address")
        ygg_port = int(meta.get("ygg_port", 9001))
        if not ygg_address:
            logger.debug("[YGG] /meta has no ygg_address for %s", identity_hash[:16])
            return

        ok = await ygg_adapter.add_peer(ygg_address, ygg_port)
        if ok:
            logger.info(
                "[YGG] Peered with %s at %s:%d", identity_hash[:16], ygg_address, ygg_port
            )
        else:
            logger.debug(
                "[YGG] add_peer(%s:%d) failed for %s — will retry on next announce",
                ygg_address,
                ygg_port,
                identity_hash[:16],
            )
    except Exception as exc:
        logger.debug("[YGG] Bootstrap error for %s: %s", identity_hash[:16], exc)


# Global announce handler
_announce_handler: StyreneAnnounceHandler | None = None


def start_discovery(
    callback: Callable[[MeshDevice], None] | None = None,
    node_store: Any | None = None,
    access_mode: MeshAccessMode | None = None,
    allowed_peers: set[str] | None = None,
    ygg_adapter: Any | None = None,
    ygg_config: Any | None = None,
    direct_link_service: Any | None = None,
) -> None:
    """Start device discovery via RNS announces.

    Registers an announce handler with RNS.Transport to listen for all
    device announces on the network.

    Args:
        callback: Optional callback to invoke when devices are discovered/updated.
                  Receives a MeshDevice object.
        node_store: Optional node store for persistence (dependency injection).
        access_mode: Mesh admission policy.  When ``ALLOWLIST``, only nodes
            whose identity hash appears in *allowed_peers* are accepted.
        allowed_peers: Identity hashes permitted when *access_mode* is ALLOWLIST.
        ygg_adapter: Optional YggdrasilAdapter for peer bootstrapping.
        ygg_config: Optional YggdrasilConfig (peer_discovery / bootstrap_from_rns).
        direct_link_service: Optional DirectLinkService for /meta fetches.
    """
    global _announce_handler
    if _announce_handler:
        return

    _announce_handler = StyreneAnnounceHandler(
        callback,
        node_store,
        access_mode,
        allowed_peers,
        ygg_adapter=ygg_adapter,
        ygg_config=ygg_config,
        direct_link_service=direct_link_service,
    )
    try:
        if not RNS:
            logger.error("RNS library not available. Install with: pip install rns")
            _announce_handler = None
            return

        RNS.Transport.register_announce_handler(_announce_handler)
        logger.info("Started device discovery (listening for all announces)")
    except Exception as e:
        logger.error(f"Failed to register announce handler: {e}")
        _announce_handler = None


def stop_discovery() -> None:
    """Stop device discovery and deregister announce handler."""
    global _announce_handler
    if _announce_handler:
        try:
            if not RNS:
                logger.error("RNS library not available")
                _announce_handler = None
                return

            RNS.Transport.deregister_announce_handler(_announce_handler)
            logger.info("Stopped device discovery")
        except Exception as e:
            logger.error(f"Failed to deregister announce handler: {e}")
        finally:
            _announce_handler = None


def discover_devices() -> list[MeshDevice]:
    """Discover devices on the Reticulum mesh.

    Returns all discovered devices from the announce handler.

    Returns:
        List of MeshDevice objects for all discovered devices.
    """
    if not _announce_handler:
        return []
    return list(_announce_handler.discovered_devices.values())


def _deduplicate_by_identity(devices: list[MeshDevice]) -> list[MeshDevice]:
    """Deduplicate devices by identity_hash.

    The same node announces on multiple destinations (operator + LXMF).
    Keep the entry with the richest metadata (prefer STYRENE_NODE type,
    then most recent announce, then most announce counts).

    Also filters out devices that have been LOST for more than 30 minutes
    to prevent stale ghosts from cluttering the device table.
    """
    from datetime import datetime as _dt
    cutoff = _dt.now().timestamp() - 1800  # 30 minutes

    by_identity: dict[str, MeshDevice] = {}
    for device in devices:
        # Skip stale ghosts — LOST for more than 30 minutes
        if device.last_announce < cutoff:
            continue
        key = device.identity_hash or device.destination_hash
        existing = by_identity.get(key)
        if existing is None:
            by_identity[key] = device
        else:
            # Prefer STYRENE_NODE over other types
            if device.is_styrene_node and not existing.is_styrene_node:
                by_identity[key] = device
            elif device.is_styrene_node == existing.is_styrene_node:
                # Same type — prefer most recent announce
                if device.last_announce > existing.last_announce:
                    by_identity[key] = device
            # Merge LXMF destination if the winner doesn't have one
            winner = by_identity[key]
            if not winner.lxmf_destination_hash and device.lxmf_destination_hash:
                winner.lxmf_destination_hash = device.lxmf_destination_hash
    return list(by_identity.values())


def get_styrene_devices() -> list[MeshDevice]:
    """Get list of discovered Styrene nodes, deduplicated by identity.

    Returns only devices identified as Styrene nodes via announce data.
    Nodes that announce on multiple destinations (operator + LXMF) are
    merged into a single entry.

    Returns:
        List of MeshDevice objects for Styrene nodes only.
    """
    if not _announce_handler:
        return []
    styrene = [
        device for device in _announce_handler.discovered_devices.values() if device.is_styrene_node
    ]
    return _deduplicate_by_identity(styrene)


def get_rnodes() -> list[MeshDevice]:
    """Get list of discovered RNode devices.

    Returns only devices identified as RNodes via announce data.

    Returns:
        List of MeshDevice objects for RNodes only.
    """
    if not _announce_handler:
        return []
    return [device for device in _announce_handler.discovered_devices.values() if device.is_rnode]


def get_identity_for_lxmf_destination(lxmf_dest_hash: str) -> str | None:
    """Look up identity hash for an LXMF destination hash.

    Searches discovered devices for one with a matching LXMF destination
    and returns its identity hash if found.

    Args:
        lxmf_dest_hash: Hex-encoded LXMF destination hash.

    Returns:
        Hex-encoded identity hash if found, None otherwise.
    """
    if not _announce_handler:
        return None

    # Search by LXMF destination hash
    for device in _announce_handler.discovered_devices.values():
        if device.lxmf_destination_hash == lxmf_dest_hash:
            return device.identity_hash
        # Also check if the operator destination matches (fallback)
        if device.destination_hash == lxmf_dest_hash:
            return device.identity_hash

    return None


def generate_rns_config(config: CoreConfig, client_only: bool = False) -> str:
    """Generate Reticulum configuration from CoreConfig.

    Creates an INI-formatted config string for RNS based on deployment mode
    and interface settings.

    Args:
        config: CoreConfig object with deployment mode and interface settings.
        client_only: If True, don't include server interfaces (for CLI tools).

    Returns:
        INI-formatted config string for RNS.
    """
    lines = []

    # [reticulum] section
    lines.append("[reticulum]")
    enable_transport = config.reticulum.resolve_transport_enabled()
    lines.append(f"enable_transport = {str(enable_transport).lower()}")

    # In standalone mode, use our own transport instead of shared instance
    share_instance = config.reticulum.mode != DeploymentMode.STANDALONE
    lines.append(f"share_instance = {str(share_instance).lower()}")
    lines.append("")

    # [interfaces] section
    lines.append("[interfaces]")
    lines.append("")

    # TCPServerInterface (hub mode) - highest priority
    # Skip server interface in client_only mode (for CLI tools)
    if config.reticulum.interfaces.server.enabled and not client_only:
        lines.append("[[TCP Server Interface]]")
        lines.append("type = TCPServerInterface")
        lines.append("enabled = true")
        lines.append(f"listen_ip = {config.reticulum.interfaces.server.listen_ip}")
        lines.append(f"listen_port = {config.reticulum.interfaces.server.port}")
        lines.append("")

    # TCPClientInterface (peers) - only enabled peers written to RNS config
    for i, peer in enumerate(config.reticulum.interfaces.peers):
        if not peer.enabled:
            continue
        interface_name = peer.name or f"Peer {i + 1}"
        lines.append(f"[[{interface_name}]]")
        lines.append("type = TCPClientInterface")
        lines.append("enabled = true")
        lines.append(f"target_host = {peer.host}")
        lines.append(f"target_port = {peer.port}")
        lines.append("")

    # AutoInterface (local discovery) - deferred due to platform compatibility issues
    # IMPORTANT: AutoInterface is disabled by default for the following reasons:
    #   - Linux: Can error on certain network adapters (wlp3s0, etc.) blocking subsequent interfaces
    #   - macOS: Causes "No buffer space available" errors on VPN/tunnel interfaces (utun0-5)
    #   - General: Errors in AutoInterface can prevent RNS config from loading TCPClientInterface
    #
    # Enable AutoInterface only if:
    #   1. You need local multicast discovery
    #   2. Your network adapters are stable (no VPN tunnels or problematic WiFi chipsets)
    #   3. You configure ignored_interfaces to exclude problematic adapters
    #
    # Recommended: Use TCPClientInterface to connect to hub for fleet-wide discovery
    lines.append("# Local multicast discovery (disabled by default - see comments above)")
    lines.append("[[AutoInterface]]")
    lines.append("type = AutoInterface")
    lines.append(f"enabled = {str(config.reticulum.interfaces.auto).lower()}")
    if config.reticulum.interfaces.auto:
        lines.append("# To exclude problematic interfaces, add:")
        lines.append("# ignored_interfaces = utun0,utun1,utun2,utun3,utun4,utun5")
    lines.append("")

    return "\n".join(lines)
