"""Lightweight dashboard app for device-local status display.

A minimal Textual App that shows system, RNS, and Styrene status
without the full StyreneApp overhead (no RPC, chat, database, etc.).

Designed for ``styrene --dashboard`` mode in Zellij panes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from textual.app import App

from styrened.tui.models.config import ConfigLoadError, ConfigValidationErrors, StyreneConfig
from styrened.tui.screens.dashboard_local import LocalDashboardScreen
from styrened.tui.services.app_lifecycle import StyreneLifecycle
from styrened.tui.services.config import (
    ensure_directories,
    get_default_config,
    load_config,
)
from styrened.tui.themes.styrene_brand import (
    STYRENE_THEME_KEY,
    create_styrene_cascade,
    create_styrene_theme,
)
from styrened.tui.widgets.highlighted_panel import set_color_cascade

logger = logging.getLogger(__name__)


class LocalDashboardApp(App[None]):
    """Lightweight dashboard showing device-local status.

    Registers themes and color cascade, initializes RNS lifecycle
    for status display, but skips RPC, chat, and database.
    """

    TITLE = "STYRENE"
    SUB_TITLE = "Dashboard"

    CSS_PATH = Path(__file__).parent / "styles" / "imperial_crt.tcss"

    def __init__(self) -> None:
        super().__init__()

        ensure_directories()

        # Load config
        self.config: StyreneConfig
        try:
            self.config = load_config()
        except (ConfigLoadError, ConfigValidationErrors):
            self.config = get_default_config()

        # Register and apply styrene brand theme
        self.register_theme(create_styrene_theme())
        self.theme = STYRENE_THEME_KEY
        set_color_cascade(create_styrene_cascade())

        # Initialize RNS lifecycle for status display
        self._lifecycle = StyreneLifecycle(self.config)
        if not self._lifecycle.initialize():
            logger.warning("Service initialization failed - dashboard running in offline mode")

    def on_mount(self) -> None:
        """Push the dashboard screen."""
        self.push_screen(LocalDashboardScreen())

    def watch_theme(self, old_theme: str, new_theme: str) -> None:
        """Update cascade when theme changes."""
        pass

    def on_shutdown(self) -> None:
        """Clean up lifecycle on exit."""
        try:
            self._lifecycle.shutdown()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
