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
from styrened.tui.themes.color_cascade import ColorCascade, generate_all_themes
from styrened.tui.themes.imperial_crt import IMPERIAL_CRT
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

        # Register themes
        self.register_theme(IMPERIAL_CRT)
        for theme in generate_all_themes().values():
            self.register_theme(theme)

        # Apply theme from config
        theme_key = self.config.tui.theme.value
        self.theme = theme_key

        try:
            cascade = ColorCascade.from_preset(theme_key)
            set_color_cascade(cascade)
        except ValueError:
            pass

        # Initialize RNS lifecycle for status display
        self._lifecycle = StyreneLifecycle(self.config)
        if not self._lifecycle.initialize():
            logger.warning("Service initialization failed - dashboard running in offline mode")

    def on_mount(self) -> None:
        """Push the dashboard screen."""
        self.push_screen(LocalDashboardScreen())

    def watch_theme(self, old_theme: str, new_theme: str) -> None:
        """Update cascade when theme changes."""
        if old_theme == new_theme:
            return

        try:
            cascade = ColorCascade.from_preset(new_theme)
            set_color_cascade(cascade)
        except ValueError:
            return

    def on_shutdown(self) -> None:
        """Clean up lifecycle on exit."""
        try:
            self._lifecycle.shutdown()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
