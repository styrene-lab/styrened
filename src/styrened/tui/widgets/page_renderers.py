"""Type-specific renderers for structured page data.

When a fetched page contains Styrene directives with structured data,
these renderers produce enhanced Rich markup using Textual's full widget
capabilities. Each renderer takes a page_type string and data dict, and
returns Rich-compatible markup text.

Falls back to None when no renderer matches, allowing the caller to
use standard micron rendering.
"""
from __future__ import annotations

from typing import Any

from styrened.tui.widgets.highlighted_panel import get_color_cascade


def render_structured_page(page_type: str, data: dict[str, Any]) -> str | None:
    """Dispatch to a type-specific renderer.

    Args:
        page_type: Page type from Styrene metadata (e.g. "node_status", "fleet").
        data: Decoded structured data dict.

    Returns:
        Rich markup string, or None if no renderer handles this page type.
    """
    renderer = _RENDERERS.get(page_type)
    if renderer is None:
        return None
    try:
        return renderer(data)
    except Exception:
        return None


def render_node_status(data: dict[str, Any]) -> str:
    """Render a node status page from structured data.

    Expected data shape::

        {
            "node_name": "edge-03",
            "status": "active",
            "uptime": 86400,
            "version": "0.9.1",
            "services": ["rpc", "pages", "terminal"],
            "interfaces": [
                {"name": "AutoInterface", "status": "up", "peers": 3}
            ]
        }
    """
    lines: list[str] = []

    node_name = data.get("node_name", "Unknown")
    status = data.get("status", "unknown")
    c = get_color_cascade()
    status_color = c.bright if status == "active" else c.color_warning if status == "degraded" else c.color_danger

    lines.append(f"[bold]{node_name}[/bold]  [{status_color}]{status.upper()}[/]")
    lines.append("")

    # Uptime
    uptime = data.get("uptime")
    if uptime is not None:
        lines.append(f"  Uptime: {_format_duration(uptime)}")

    # Version
    version = data.get("version")
    if version:
        lines.append(f"  Version: {version}")

    # Services
    services = data.get("services", [])
    if services:
        lines.append(f"  Services: {', '.join(services)}")

    # Interfaces
    interfaces = data.get("interfaces", [])
    if interfaces:
        lines.append("")
        lines.append("[bold]Interfaces[/bold]")
        for iface in interfaces:
            name = iface.get("name", "?")
            iface_status = iface.get("status", "?")
            peers = iface.get("peers", 0)
            iface_color = "green" if iface_status == "up" else "red"
            lines.append(
                f"  {name}: [{iface_color}]{iface_status}[/{iface_color}]"
                f"  ({peers} peer{'s' if peers != 1 else ''})"
            )

    return "\n".join(lines)


def render_fleet_overview(data: dict[str, Any]) -> str:
    """Render a fleet overview page from structured data.

    Expected data shape::

        {
            "nodes": [
                {"name": "edge-03", "status": "active", "uptime": 86400},
                {"name": "edge-07", "status": "active", "uptime": 259200},
                {"name": "edge-12", "status": "offline", "uptime": 0},
            ],
            "total": 3,
            "active": 2,
        }
    """
    lines: list[str] = []

    total = data.get("total", 0)
    active = data.get("active", 0)
    offline = total - active

    lines.append(f"[bold]Fleet Overview[/bold]  {active} active / {total} total")
    if offline > 0:
        lines.append(f"  [{get_color_cascade().color_warning}]{offline} offline[/]")
    lines.append("")

    nodes = data.get("nodes", [])
    if nodes:
        # Header
        lines.append(f"  {'Name':<20} {'Status':<10} {'Uptime':<15}")
        lines.append(f"  {'─' * 20} {'─' * 10} {'─' * 15}")

        for node in nodes:
            name = node.get("name", "?")
            status = node.get("status", "unknown")
            uptime = node.get("uptime", 0)

            c = get_color_cascade()
            status_color = (
                c.bright if status == "active"
                else c.color_warning if status == "degraded"
                else c.color_danger
            )
            uptime_str = _format_duration(uptime) if uptime > 0 else "-"

            lines.append(
                f"  {name:<20} [{status_color}]{status:<10}[/] {uptime_str:<15}"
            )
    else:
        lines.append(f"  [{get_color_cascade().dim}]No nodes reported[/]")

    return "\n".join(lines)


def _format_duration(seconds: int | float) -> str:
    """Format seconds into a human-readable duration string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    return f"{days}d {hours}h" if hours else f"{days}d"


# Registry of page type → renderer function
_RENDERERS: dict[str, Any] = {
    "node_status": render_node_status,
    "fleet": render_fleet_overview,
}
