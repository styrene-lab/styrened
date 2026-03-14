"""HomeNodeSummaryTable — compact read-only node summary for the Home screen."""

from __future__ import annotations

import time

from textual import events
from textual.message import Message
from textual.widgets import DataTable

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
        self._mesh_nodes: list[MeshDevice] = []
        self._unread_map: dict[str, int] = {}

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
        self._mesh_nodes = list(nodes)
        self._unread_map = dict(unread_map or {})
        self._rebuild_rows()

    def on_resize(self, event: events.Resize) -> None:
        """Rebuild rows when the viewport changes so overflow stays honest."""
        if self.columns:
            self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        """Render the table from cached nodes using the current viewport budget."""
        self.clear()
        unread_map = self._unread_map
        nodes = self._mesh_nodes

        if not nodes:
            self._empty = True
            self._overflow_count = 0
            cascade = get_color_cascade()
            self.add_row(
                f"[{cascade.dim}]No mesh nodes discovered[/]",
                "",
                "",
                "",
                "",
                key="__empty__",
            )
            return

        live_nodes = [n for n in nodes if n.status != NodeStatus.LOST]

        if not live_nodes:
            self._empty = True
            self._overflow_count = 0
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

        sorted_nodes = sorted(
            live_nodes,
            key=lambda d: (
                _STATUS_SORT_ORDER.get(d.status, _UNKNOWN_STATUS_SORT_KEY),
                d.name or "",
            ),
        )

        visible_budget = self._visible_row_budget()
        overflow = max(0, len(sorted_nodes) - visible_budget)
        if overflow > 0 and visible_budget > 1:
            visible_nodes = sorted_nodes[: visible_budget - 1]
            self._overflow_count = len(sorted_nodes) - len(visible_nodes)
        else:
            visible_nodes = sorted_nodes[:visible_budget]
            self._overflow_count = max(0, len(sorted_nodes) - len(visible_nodes))

        for device in visible_nodes:
            status = device.status
            symbol = _STATUS_SYMBOLS.get(status, "?")
            label = status.value.upper()

            if status == NodeStatus.ACTIVE:
                status_text = f"[{cascade.bright}]{symbol} {label}[/]"
            elif status == NodeStatus.STALE:
                status_text = f"[{cascade.medium}]{symbol} {label}[/]"
            else:
                status_text = f"[{cascade.dim}]{symbol} {label}[/]"

            last_seen = format_relative_time(device.last_announce)
            unread_count = unread_map.get(device.identity_hash, 0)
            unread_text = str(unread_count) if unread_count > 0 else "—"
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

        if self._overflow_count > 0:
            shown = len(visible_nodes)
            total = len(sorted_nodes)
            label = (
                f"[{cascade.dim}]showing {shown} of {total} • press N for full list[/]"
            )
            self.add_row(label, "", "", "", "", key="__overflow__")

    def _visible_row_budget(self) -> int:
        """Estimate how many body rows fit in the current viewport.

        DataTable doesn't expose an exact visible-row API, so we conservatively
        reserve two lines for header/chrome and cap the result at MAX_VISIBLE_ROWS.
        """
        # During early test/layout phases Textual may report a tiny provisional
        # height (for example 1-3 rows) before the real dashboard allocation is
        # applied. Treat that as "unknown" and fall back to the summary cap.
        if self.size.height < 6:
            return MAX_VISIBLE_ROWS
        return max(1, min(MAX_VISIBLE_ROWS, self.size.height - 2))

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
