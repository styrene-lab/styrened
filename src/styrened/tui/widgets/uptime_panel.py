"""Uptime and load average panel for dashboard mode."""

from __future__ import annotations

import os
import time

from textual.widgets import Static

from styrened.tui.widgets.highlighted_panel import get_color_cascade


class UptimePanel(Static):
    """Compact panel showing system uptime and load average.

    Uses psutil for uptime calculation with graceful fallback.
    Uses cascade colors for consistent theming.
    """

    DEFAULT_CSS = """
    UptimePanel {
        height: auto;
        padding: 0 1;
    }
    """

    def render(self) -> str:
        """Render uptime and load info."""
        cascade = get_color_cascade()
        lines = []

        lines.append(f"[{cascade.bright}]SYSTEM LOAD[/]")

        # Uptime
        uptime_str = self._get_uptime()
        lines.append(f"  UPTIME: [{cascade.medium}]{uptime_str}[/]")

        # Load average
        load_str = self._get_load_average()
        lines.append(f"  LOAD: [{cascade.medium}]{load_str}[/]")

        return "\n".join(lines)

    def _get_uptime(self) -> str:
        """Get system uptime as a human-readable string."""
        try:
            import psutil

            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            return self._format_duration(uptime_seconds)
        except (ImportError, OSError):
            return "unavailable"

    def _get_load_average(self) -> str:
        """Get system load average."""
        try:
            load1, load5, load15 = os.getloadavg()
            return f"{load1:.2f} {load5:.2f} {load15:.2f}"
        except (OSError, AttributeError):
            return "unavailable"

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """Format seconds into a human-readable duration string."""
        total = int(seconds)
        days, remainder = divmod(total, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")
        return " ".join(parts)

    def refresh_data(self) -> None:
        """Refresh uptime and load data."""
        self.refresh()
