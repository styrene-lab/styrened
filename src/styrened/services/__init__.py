"""Styrene services — config helpers and TUI utilities.

Daemon services have moved to Rust (styrened binary). This package retains
config loading, doctor diagnostics, and utilities used by the TUI.
"""
from __future__ import annotations

from styrened.services.config import (
    ensure_directories,
    get_config_dir,
    get_data_dir,
    get_default_core_config,
    get_log_dir,
    load_core_config,
    save_core_config,
)

__all__ = [
    "ensure_directories",
    "get_config_dir",
    "get_data_dir",
    "get_default_core_config",
    "get_log_dir",
    "load_core_config",
    "save_core_config",
]
