"""Core configuration service for headless Styrene applications.

This module provides functions to load and save CoreConfig for headless
applications. For TUI applications, use styrene.services.config instead.
"""

from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir

from styrened.models.config import (
    ConfigLoadError,
    CoreConfig,
    DeploymentMode,
)


def get_config_dir() -> Path:
    """Return the configuration directory path.

    Returns:
        Path to configuration directory (~/.styrene/).
    """
    return Path(user_config_dir("styrene"))


def get_data_dir() -> Path:
    """Return the data directory path.

    Returns:
        Path to data directory (~/.local/share/styrene/).
    """
    from platformdirs import user_data_dir

    return Path(user_data_dir("styrene", "styrene-lab"))


def get_cache_dir() -> Path:
    """Return the cache directory path.

    Returns:
        Path to cache directory (~/.cache/styrene/).
    """
    from platformdirs import user_cache_dir

    return Path(user_cache_dir("styrene", "styrene-lab"))


def get_log_dir() -> Path:
    """Return the log directory path.

    Returns:
        Path to log directory (~/.local/share/styrene/logs/).
    """
    return get_data_dir() / "logs"


def ensure_directories() -> None:
    """Create necessary directories if they don't exist."""
    get_config_dir().mkdir(parents=True, exist_ok=True)
    get_data_dir().mkdir(parents=True, exist_ok=True)
    get_cache_dir().mkdir(parents=True, exist_ok=True)
    get_log_dir().mkdir(parents=True, exist_ok=True)


def get_default_core_config() -> CoreConfig:
    """Return a CoreConfig with default values.

    Returns:
        CoreConfig instance with sensible defaults for headless mode.
    """
    config = CoreConfig()
    # Headless mode defaults
    config.reticulum.mode = DeploymentMode.STANDALONE
    config.rpc.enabled = True
    config.discovery.enabled = True
    config.discovery.auto_announce = True
    config.chat.enabled = True
    config.chat.auto_reply_enabled = True
    return config


def load_core_config(config_path: Path | None = None) -> CoreConfig:
    """Load core configuration from YAML file.

    Args:
        config_path: Optional path to config file. If None, uses default location.

    Returns:
        CoreConfig instance loaded from file, or defaults if file doesn't exist.

    Raises:
        ConfigLoadError: If config file exists but cannot be parsed.
    """
    if config_path is None:
        config_path = get_config_dir() / "core-config.yaml"

    if not config_path.exists():
        return get_default_core_config()

    try:
        with config_path.open() as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise ConfigLoadError(f"Failed to load config from {config_path}: {e}", config_path)

    if not isinstance(data, dict):
        return get_default_core_config()

    # Parse CoreConfig from dictionary
    # For now, just return defaults - full parsing can be added later
    # This is a minimal implementation to unblock headless apps
    return get_default_core_config()


def save_core_config(config: CoreConfig, config_path: Path | None = None) -> None:
    """Save core configuration to YAML file.

    Args:
        config: CoreConfig instance to save.
        config_path: Optional path to config file. If None, uses default location.

    Raises:
        ConfigLoadError: If config cannot be written.
    """
    if config_path is None:
        config_path = get_config_dir() / "core-config.yaml"

    ensure_directories()

    # Convert CoreConfig to dictionary
    # For now, minimal implementation - full serialization can be added later
    config_dict: dict[str, Any] = {
        "reticulum": {
            "mode": config.reticulum.mode.value,
            "announce_interval": config.reticulum.announce_interval,
        },
        "rpc": {
            "enabled": config.rpc.enabled,
        },
        "discovery": {
            "enabled": config.discovery.enabled,
            "auto_announce": config.discovery.auto_announce,
        },
        "chat": {
            "enabled": config.chat.enabled,
            "auto_reply_enabled": config.chat.auto_reply_enabled,
        },
        "api": {
            "enabled": config.api.enabled,
            "host": config.api.host,
            "port": config.api.port,
        },
    }

    try:
        with config_path.open("w") as f:
            yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
    except OSError as e:
        raise ConfigLoadError(f"Failed to save config to {config_path}: {e}", config_path)
