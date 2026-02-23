"""Deterministic path resolution for styrened.

Single source of truth for all filesystem paths. Uses explicit XDG paths
on all platforms — no platformdirs, same paths on macOS and Linux.

Two modes, detected once at process start:

    USER (default):
        config  ~/.config/styrene/
        data    ~/.local/share/styrene/
        cache   ~/.cache/styrene/
        runtime $XDG_RUNTIME_DIR/styrened/

    SYSTEM (STYRENE_SYSTEM=1 or /etc/styrene/config.yaml exists):
        config  /etc/styrene/
        data    /var/lib/styrene/
        cache   /var/cache/styrene/
        runtime /run/styrened/

Any STYRENE_*_DIR env var overrides the corresponding directory.
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


def config_dir() -> Path:
    """Return the configuration directory."""
    override = os.environ.get("STYRENE_CONFIG_DIR")
    if override:
        return Path(override)
    if mode() == Mode.SYSTEM:
        return Path("/etc/styrene")
    return Path.home() / ".config" / "styrene"


def data_dir() -> Path:
    """Return the data directory."""
    override = os.environ.get("STYRENE_DATA_DIR")
    if override:
        return Path(override)
    if mode() == Mode.SYSTEM:
        return Path("/var/lib/styrene")
    return Path.home() / ".local" / "share" / "styrene"


def cache_dir() -> Path:
    """Return the cache directory."""
    override = os.environ.get("STYRENE_CACHE_DIR")
    if override:
        return Path(override)
    if mode() == Mode.SYSTEM:
        return Path("/var/cache/styrene")
    return Path.home() / ".cache" / "styrene"


def runtime_dir() -> Path:
    """Return the runtime directory (for sockets, PID files)."""
    override = os.environ.get("STYRENE_RUNTIME_DIR")
    if override:
        return Path(override)
    if mode() == Mode.SYSTEM:
        return Path("/run/styrened")
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return Path(xdg) / "styrened"
    return Path.home() / ".local" / "run" / "styrened"


def log_dir() -> Path:
    """Return the log directory."""
    return data_dir() / "logs"


# -- Derived file paths ------------------------------------------------------


def config_file() -> Path:
    """Daemon / core config (was core-config.yaml)."""
    return config_dir() / "config.yaml"


def tui_config_file() -> Path:
    """TUI config (was ~/.styrene/config.yaml)."""
    return config_dir() / "tui.yaml"


def identity_file() -> Path:
    """Operator identity key file."""
    if mode() == Mode.SYSTEM:
        return config_dir() / "identity"
    return config_dir() / "operator.key"


def nodes_db() -> Path:
    """Node store database."""
    return data_dir() / "nodes.db"


def messages_db() -> Path:
    """Message persistence database."""
    return data_dir() / "messages.db"


def lxmf_storage() -> Path:
    """LXMF router storage directory."""
    return data_dir() / "lxmf"


def fleet_inventory() -> Path:
    """Fleet inventory file."""
    return config_dir() / "fleet-inventory.yaml"


def control_socket() -> Path:
    """IPC control socket path."""
    env = os.environ.get("STYRENED_SOCKET")
    if env:
        return Path(env)
    return runtime_dir() / "control.sock"


# -- Directory creation ------------------------------------------------------


def ensure_directories() -> None:
    """Create all standard directories."""
    for d in (config_dir(), data_dir(), cache_dir(), log_dir()):
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
