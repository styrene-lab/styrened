"""HomeNodeSummaryTable — compact read-only node summary for the Home screen."""

from __future__ import annotations

import time

from textual.message import Message
from textual.widgets import DataTable, Static

from styrened.models.mesh_device import MeshDevice, NodeStatus
from styrened.tui.widgets.highlighted_panel import get_color_cascade

__all__ = ["HomeNodeSummaryTable", "format_relative_time", "MAX_VISIBLE_ROWS"]

# Maximum number of node rows shown before the overflow affordance is appended.
# Keeps the NODES panel compact without masking fleet-scale awareness.
MAX_VISIBLE_ROWS: int = 10

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

    class OverflowSelected(Message):
        """Posted when the overflow affordance row is selected.

        Callers (e.g. DashboardScreen) should navigate to the Nodes workspace
        so the operator can see the full fleet list.
        """

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self.cursor_type = "row"
        self.zebra_stripes = True
        self._empty: bool = True
        self._overflow_count: int = 0

    @property
    def overflow_count(self) -> int:
        """Number of nodes hidden behind the overflow affordance (0 = none)."""
        return self._overflow_count

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

        # Clamp to viewport budget and track hidden surplus for overflow affordance
        if len(sorted_nodes) > MAX_VISIBLE_ROWS:
            self._overflow_count = len(sorted_nodes) - MAX_VISIBLE_ROWS
            sorted_nodes = sorted_nodes[:MAX_VISIBLE_ROWS]
        else:
            self._overflow_count = 0

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

        # Overflow affordance — shown when the fleet is larger than the viewport budget
        if self._overflow_count > 0:
            n = self._overflow_count
            noun = "node" if n == 1 else "nodes"
            label = f"[{cascade.dim}]  + {n} more {noun} — press N to browse all  [/]"
            self.add_row(label, "", "", "", "", key="__overflow__")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Post NodeSelected (or OverflowSelected) when a row is activated."""
        if self._empty:
            return
        key_value = event.row_key.value if event.row_key else None
        if key_value == "__overflow__":
            self.post_message(self.OverflowSelected())
            return
        if key_value:
            self.post_message(self.NodeSelected(str(key_value)))
