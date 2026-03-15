"""Activity feed widget — scrolling log of daemon activity events."""

from __future__ import annotations

import time
from typing import Any

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import RichLog

from styrened.tui.widgets.highlighted_panel import get_color_cascade

# Map event_type strings to display tags and cascade color keys
_EVENT_CATEGORIES: dict[str, tuple[str, str]] = {
    # (tag, cascade_attr): bright/medium/dim
    "new_message": ("MSG", "bright"),
    "delivery_status": ("DLV", "medium"),
    "device_discovered": ("DEV", "bright"),
    "device_updated": ("DEV", "medium"),
    "announce_sent": ("ANN", "medium"),
    "rpc_received": ("RPC", "medium"),
    "contact_set": ("CON", "medium"),
    "contact_removed": ("CON", "dim"),
    "identity_changed": ("CFG", "medium"),
    "auto_reply_changed": ("CFG", "medium"),
    "conversation_read": ("MSG", "dim"),
    "conversation_deleted": ("MSG", "dim"),
    "file_offer_received": ("FIL", "bright"),
    "file_transfer_complete": ("FIL", "medium"),
    "pqc_established": ("PQC", "bright"),
    "pqc_rekey": ("PQC", "medium"),
}


def _format_event(event_type: str, payload: dict[str, Any]) -> str:
    """Format a single activity event for RichLog display.

    Returns Rich markup string: HH:MM:SS [TAG] summary
    """
    cascade = get_color_cascade()

    # Timestamp
    ts = payload.get("timestamp", 0)
    if ts:
        time_str = time.strftime("%H:%M:%S", time.localtime(ts))
    else:
        time_str = time.strftime("%H:%M:%S")

    # Category tag + color
    tag, color_key = _EVENT_CATEGORIES.get(event_type, ("EVT", "dim"))
    color = getattr(cascade, color_key, cascade.dim)

    # Summary based on event_type
    summary = _summarize(event_type, payload, cascade)

    return f"[{cascade.dim}]{time_str}[/] [{color}]{tag:3s}[/] {summary}"


def _summarize(event_type: str, payload: dict[str, Any], cascade: Any) -> str:
    """Build a human-readable summary for each event category."""
    peer = payload.get("peer_hash", "")
    peer_short = peer[:8] if peer else ""

    if event_type == "new_message":
        content = payload.get("content", "") or ""
        preview = content[:40] + ("..." if len(content) > 40 else "")
        return f"[{cascade.bright}]{peer_short}[/] {preview}"

    if event_type == "delivery_status":
        status = payload.get("status", "unknown")
        return f"[{cascade.medium}]{peer_short}[/] {status}"

    if event_type == "device_discovered":
        name = payload.get("name", peer_short)
        dtype = payload.get("device_type", "")
        return f"[{cascade.bright}]{name}[/] [{cascade.dim}]{dtype}[/]"

    if event_type == "device_updated":
        name = payload.get("name", peer_short)
        return f"[{cascade.medium}]{name}[/] updated"

    if event_type == "announce_sent":
        return f"[{cascade.medium}]local announce broadcast[/]"

    if event_type == "rpc_received":
        cmd = payload.get("command", "?")
        return f"[{cascade.medium}]{peer_short}[/] {cmd}"

    if event_type == "contact_set":
        alias = payload.get("alias", "")
        return f"[{cascade.medium}]{peer_short}[/] -> {alias}"

    if event_type == "contact_removed":
        return f"[{cascade.dim}]{peer_short}[/] removed"

    if event_type == "identity_changed":
        name = payload.get("display_name", "")
        return f"[{cascade.medium}]{name}[/]"

    if event_type == "auto_reply_changed":
        mode = payload.get("mode", "")
        return f"[{cascade.medium}]{mode}[/]"

    if event_type == "conversation_read":
        return f"[{cascade.dim}]{peer_short}[/] marked read"

    if event_type == "conversation_deleted":
        return f"[{cascade.dim}]{peer_short}[/] deleted"

    if event_type == "file_offer_received":
        fname = payload.get("filename", "?")
        size = payload.get("size", 0)
        return f"[{cascade.bright}]{peer_short}[/] {fname} ({size} bytes)"

    if event_type == "file_transfer_complete":
        fname = payload.get("filename", "?")
        return f"[{cascade.medium}]{peer_short}[/] {fname} complete"

    if event_type == "pqc_established":
        tier = payload.get("security_tier", "pqc_hybrid")
        return f"[{cascade.bright}]{peer_short}[/] {tier}"

    if event_type == "pqc_rekey":
        return f"[{cascade.medium}]{peer_short}[/] session rekeyed"

    # Fallback
    return f"[{cascade.dim}]{event_type}[/]"


class ActivityFeedWidget(Widget):
    """Scrolling activity feed powered by Textual's RichLog."""

    DEFAULT_CSS = """
    ActivityFeedWidget {
        height: 1fr;
    }

    ActivityFeedWidget RichLog {
        height: 1fr;
        background: transparent;
        scrollbar-background: transparent;
        scrollbar-color: $border;
        scrollbar-size: 1 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield RichLog(
            id="activity-log",
            max_lines=50,
            auto_scroll=True,
            markup=True,
        )

    def add_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Format and append one activity event to the log."""
        line = _format_event(event_type, payload)
        try:
            log = self.query_one("#activity-log", RichLog)
            log.write(line)
        except Exception:
            pass

    def backfill_history(self, events: list[dict[str, Any]]) -> None:
        """Seed the feed with historical events from the daemon ring buffer.

        Called once on connect so the feed isn't empty when the operator
        first opens the Diagnostics tab. Historical events are written
        before any live events and are visually dimmed to distinguish them.
        """
        if not events:
            return
        try:
            log = self.query_one("#activity-log", RichLog)
            cascade = get_color_cascade()
            log.write(f"[{cascade.dim}]── history ──[/]")
            for event in events:
                event_type = event.get("event_type", "unknown")
                line = _format_event(event_type, event)
                # Dim historical events relative to live ones
                log.write(f"[{cascade.dim}]{line}[/]")
            log.write(f"[{cascade.dim}]── live ──[/]")
        except Exception:
            pass
