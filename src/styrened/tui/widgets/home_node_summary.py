"""HomeNodeSummaryTable — compact read-only node summary for the Home screen."""

from __future__ import annotations

import time

from textual.message import Message
from textual.widgets import DataTable, Static

from styrened.models.mesh_device import MeshDevice, NodeStatus
from styrened.tui.widgets.highlighted_panel import get_color_cascade

__all__ = ["HomeNodeSummaryTable", "format_relative_time"]

# Abnormal-first sort order: LOST > STALE > PENDING > ONLINE
# Unknown/future statuses sort between STALE and ACTIVE (abnormal-first).
_STATUS_SORT_ORDER: dict[NodeStatus, int] = {
    NodeStatus.ACTIVE: 0,
    NodeStatus.STALE: 1,
    # PENDING (if added) would be 2
    NodeStatus.LOST: 3,
}

# Unknown statuses sort at priority 2 (between STALE and LOST)
_UNKNOWN_STATUS_SORT_KEY = 2

_STATUS_SYMBOLS: dict[NodeStatus, str] = {
    NodeStatus.ACTIVE: "●",
    NodeStatus.STALE: "◐",
    NodeStatus.LOST: "○",
}


def format_relative_time(timestamp: float | None, *, now: float | None = None) -> str:
    """Format a unix timestamp as a human-readable relative time string.

    Args:
        timestamp: Unix timestamp to format.
        now: Current time (defaults to time.time()). Pass explicitly for deterministic tests.
    """
    if timestamp is None:
        return "never"
    if now is None:
        now = time.time()
    delta = now - timestamp
    if delta < 0:
        return "just now"
    if delta < 60:
        s = int(delta)
        return f"{s}s ago"
    if delta < 3600:
        m = int(delta // 60)
        return f"{m}m ago"
    if delta < 86400:
        h = int(delta // 3600)
        return f"{h}h ago"
    d = int(delta // 86400)
    return f"{d}d ago"


class HomeNodeSummaryTable(DataTable[str]):
    """Compact read-only node summary table for the Home screen.

    Displays mesh nodes sorted abnormal-first (LOST > STALE > ONLINE).
    Posts NodeSelected on row selection.
    """

    DEFAULT_CSS = """
    HomeNodeSummaryTable {
        height: auto;
    }
    """

    class NodeSelected(Message):
        """Posted when a node row is selected."""

        def __init__(self, identity_hash: str) -> None:
            super().__init__()
            self.identity_hash = identity_hash

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.cursor_type = "row"
        self.zebra_stripes = True
        self._empty: bool = True

    def on_mount(self) -> None:
        """Set up columns on mount."""
        self.add_column("NAME", key="name")
        self.add_column("STATUS", key="status")
        self.add_column("LAST SEEN", key="last_seen")
        self.add_column("UNREAD", key="unread")
        self.add_column("LINK", key="link")

    def update_nodes(
        self,
        nodes: list[MeshDevice],
        unread_map: dict[str, int] | None = None,
    ) -> None:
        """Clear and repopulate the table with sorted node data.

        Args:
            nodes: List of mesh devices to display.
            unread_map: Mapping of identity_hash -> unread message count.
        """
        self.clear()
        if unread_map is None:
            unread_map = {}

        if not nodes:
            self._empty = True
            cascade = get_color_cascade()
            # Add a single placeholder row with key to prevent duplication
            self.add_row(
                f"[{cascade.dim}]No mesh nodes discovered[/]",
                "",
                "",
                "",
                "",
                key="__empty__",
            )
            return

        # Filter out LOST nodes — they're historical noise, not actionable
        live_nodes = [n for n in nodes if n.status != NodeStatus.LOST]

        if not live_nodes:
            self._empty = True
            cascade = get_color_cascade()
            total = len(nodes)
            if total > 0:
                self.add_row(
                    f"[{cascade.dim}]{total} nodes known (all lost)[/]",
                    "", "", "", "",
                    key="__empty__",
                )
            else:
                self.add_row(
                    f"[{cascade.dim}]No mesh nodes discovered[/]",
                    "", "", "", "",
                    key="__empty__",
                )
            return

        self._empty = False
        cascade = get_color_cascade()

        # Sort active-first, then stale, then alphabetical
        sorted_nodes = sorted(
            live_nodes,
            key=lambda d: (
                _STATUS_SORT_ORDER.get(d.status, _UNKNOWN_STATUS_SORT_KEY),
                d.name or "",
            ),
        )

        for device in sorted_nodes:
            status = device.status
            symbol = _STATUS_SYMBOLS.get(status, "?")
            label = status.value.upper()

            # Color based on status
            if status == NodeStatus.ACTIVE:
                status_text = f"[{cascade.bright}]{symbol} {label}[/]"
            elif status == NodeStatus.STALE:
                status_text = f"[{cascade.medium}]{symbol} {label}[/]"
            else:
                status_text = f"[{cascade.dim}]{symbol} {label}[/]"

            last_seen = format_relative_time(device.last_announce)
            unread_count = unread_map.get(device.identity_hash, 0)
            unread_text = str(unread_count) if unread_count > 0 else "—"

            # Link quality placeholder
            hops = device.hops if device.hops is not None else "?"
            link_text = (
                f"{hops} hop{'s' if hops != 1 else ''}"
                if isinstance(hops, int)
                else str(hops)
            )

            self.add_row(
                device.name or device.identity_hash[:8],
                status_text,
                last_seen,
                unread_text,
                link_text,
                key=device.identity_hash,
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Post NodeSelected when a row is selected."""
        if self._empty:
            return
        if event.row_key and event.row_key.value:
            self.post_message(self.NodeSelected(str(event.row_key.value)))
