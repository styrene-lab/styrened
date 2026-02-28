"""Deterministic path resolution for styrened.

Single source of truth for all filesystem paths. Follows the XDG Base
Directory Specification — no platformdirs, same paths on macOS and Linux.

Two modes, detected once at process start:

    USER (default):
        config  $XDG_CONFIG_HOME/styrene/    (default ~/.config/styrene/)
        data    $XDG_DATA_HOME/styrene/      (default ~/.local/share/styrene/)
        state   $XDG_STATE_HOME/styrene/     (default ~/.local/state/styrene/)
        runtime $XDG_RUNTIME_DIR/styrened/   (default ~/.local/run/styrened/)

    SYSTEM (STYRENE_SYSTEM=1 or /etc/styrene/config.yaml exists):
        config  /etc/styrene/
        data    /var/lib/styrene/
        state   /var/log/styrene/
        runtime /run/styrened/

Override precedence (highest to lowest):
    1. STYRENE_*_DIR   — per-directory override (e.g. STYRENE_CONFIG_DIR)
    2. STYRENE_HOME    — unified base (config/, data/, state/, run/)
    3. SYSTEM mode     — FHS paths
    4. XDG_*_HOME      — XDG env vars (USER mode only)
    5. XDG defaults    — ~/.config, ~/.local/share, etc.

STYRENE_HOME is useful for containers where all state lives under
a single mount: STYRENE_HOME=/app/data gives config/, data/, state/,
run/ subdirectories.
"""

import enum
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


class Mode(enum.Enum):
    USER = "user"
    SYSTEM = "system"


def mode() -> Mode:
    """Detect operating mode (USER or SYSTEM)."""
    env = os.environ.get("STYRENE_SYSTEM", "")
    if env.lower() in ("1", "true", "yes"):
        return Mode.SYSTEM
    if Path("/etc/styrene/config.yaml").exists():
        return Mode.SYSTEM
    return Mode.USER


# -- Directory resolvers -----------------------------------------------------


def _home_base() -> Path | None:
    """Return STYRENE_HOME base directory if set, else None."""
    env = os.environ.get("STYRENE_HOME")
    return Path(env) if env else None


def config_dir() -> Path:
    """Return the configuration directory ($XDG_CONFIG_HOME/styrene)."""
    override = os.environ.get("STYRENE_CONFIG_DIR")
    if override:
        return Path(override)
    home = _home_base()
    if home:
        return home / "config"
    if mode() == Mode.SYSTEM:
        return Path("/etc/styrene")
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "styrene"


def data_dir() -> Path:
    """Return the data directory ($XDG_DATA_HOME/styrene)."""
    override = os.environ.get("STYRENE_DATA_DIR")
    if override:
        return Path(override)
    home = _home_base()
    if home:
        return home / "data"
    if mode() == Mode.SYSTEM:
        return Path("/var/lib/styrene")
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "styrene"


def state_dir() -> Path:
    """Return the state directory ($XDG_STATE_HOME/styrene).

    Per XDG spec, state data persists between restarts but is not
    important enough to back up (logs, history, recently-used).
    """
    override = os.environ.get("STYRENE_STATE_DIR")
    if override:
        return Path(override)
    home = _home_base()
    if home:
        return home / "state"
    if mode() == Mode.SYSTEM:
        return Path("/var/log/styrene")
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "styrene"


def runtime_dir() -> Path:
    """Return the runtime directory ($XDG_RUNTIME_DIR/styrened).

    On Wayland sessions, XDG_RUNTIME_DIR is always set by the
    compositor or session manager (typically /run/user/<uid>).
    """
    override = os.environ.get("STYRENE_RUNTIME_DIR")
    if override:
        return Path(override)
    home = _home_base()
    if home:
        return home / "run"
    if mode() == Mode.SYSTEM:
        return Path("/run/styrened")
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "styrened"
    return Path.home() / ".local" / "run" / "styrened"


def log_dir() -> Path:
    """Return the log directory (inside state_dir).

    Moved from data_dir/logs to state_dir/logs in 0.10.7 per XDG spec.
    Auto-migrates on first access.
    """
    canonical = state_dir() / "logs"
    if not canonical.exists():
        old = data_dir() / "logs"
        try:
            if old.exists() and any(old.iterdir()):
                canonical.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(canonical))
                logger.info("Migrated log dir: %s -> %s", old, canonical)
        except OSError:
            pass
    return canonical


# -- Derived file paths ------------------------------------------------------


def config_file() -> Path:
    """Daemon / core config (was core-config.yaml)."""
    return config_dir() / "config.yaml"


def tui_config_file() -> Path:
    """TUI config (was ~/.styrene/config.yaml)."""
    return config_dir() / "tui.yaml"


def identity_file() -> Path:
    """Operator identity key file.

    Unified to "identity" in 0.10.7 (was "operator.key" in user mode,
    "identity" in system mode). Auto-migrates on first access.
    """
    canonical = config_dir() / "identity"
    if not canonical.exists():
        old = config_dir() / "operator.key"
        try:
            if old.exists():
                shutil.move(str(old), str(canonical))
                logger.info("Migrated identity file: %s -> %s", old, canonical)
        except OSError:
            pass
    return canonical


def nodes_db() -> Path:
    """Node store database."""
    return data_dir() / "nodes.db"


def messages_db() -> Path:
    """Message persistence database."""
    return data_dir() / "messages.db"


def attachments_dir() -> Path:
    """Attachment storage directory."""
    return data_dir() / "attachments"


def lxmf_storage() -> Path:
    """LXMF router storage directory."""
    return data_dir() / "lxmf"


def fleet_inventory() -> Path:
    """Fleet inventory file.

    Moved from config_dir to data_dir in 0.10.7 (mutable runtime state,
    not human-edited configuration). Auto-migrates on first access.
    """
    canonical = data_dir() / "fleet-inventory.yaml"
    if not canonical.exists():
        old = config_dir() / "fleet-inventory.yaml"
        try:
            if old.exists():
                canonical.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(canonical))
                logger.info("Migrated fleet inventory: %s -> %s", old, canonical)
        except OSError:
            pass
    return canonical


def control_socket() -> Path:
    """IPC control socket path."""
    env = os.environ.get("STYRENED_SOCKET")
    if env:
        return Path(env)
    return runtime_dir() / "control.sock"


# -- Directory creation ------------------------------------------------------


def ensure_directories() -> None:
    """Create all standard directories."""
    for d in (config_dir(), data_dir(), state_dir(), log_dir()):
        d.mkdir(parents=True, exist_ok=True)


# -- Legacy migration --------------------------------------------------------

_MIGRATION_MARKER = ".paths-migrated"


def migrate_legacy_paths() -> list[str]:
    """Copy files from legacy locations to canonical paths.

    Skips if destination already exists. Writes a marker file so
    migration only runs once. Returns a list of human-readable
    actions taken.
    """
    marker = config_dir() / _MIGRATION_MARKER
    if marker.exists():
        return []

    actions: list[str] = []

    # Only migrate in USER mode — SYSTEM mode paths are managed by packaging
    if mode() != Mode.USER:
        return actions

    home = Path.home()
    migrations: list[tuple[Path, Path]] = [
        # macOS platformdirs location
        (home / "Library" / "Application Support" / "styrene" / "core-config.yaml",
         config_file()),
        # Linux XDG location (old filename)
        (home / ".config" / "styrene" / "core-config.yaml",
         config_file()),
        # TUI config from legacy ~/.styrene/
        (home / ".styrene" / "config.yaml",
         tui_config_file()),
        # Operator identity from legacy ~/.styrene/
        (home / ".styrene" / "operator.key",
         identity_file()),
        # nodes.db from macOS platformdirs
        (home / "Library" / "Application Support" / "styrene" / "nodes.db",
         nodes_db()),
        # nodes.db from old config dir
        (home / ".config" / "styrene" / "nodes.db",
         nodes_db()),
        # messages.db from macOS platformdirs
        (home / "Library" / "Application Support" / "styrene" / "messages.db",
         messages_db()),
    ]

    ensure_directories()

    for src, dst in migrations:
        if src.exists() and not dst.exists():
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                actions.append(f"Copied {src} -> {dst}")
            except OSError as e:
                actions.append(f"Failed to copy {src} -> {dst}: {e}")

    # Write marker
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("migrated\n")
    except OSError:
        pass

    return actions
