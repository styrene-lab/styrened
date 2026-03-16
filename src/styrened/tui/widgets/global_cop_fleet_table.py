"""Global COP fleet table — health-sorted, monitor-first fleet view."""

from __future__ import annotations

from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.widgets.highlighted_panel import get_color_cascade

_STYRENE_TYPES = {DeviceType.STYRENE_NODE}

_HEALTH_ORDER = {
    NodeStatus.LOST: 0,
    NodeStatus.STALE: 1,
    NodeStatus.ACTIVE: 2,
}


class GlobalCopFleetTable(DataTable[str]):
    """Health-sorted fleet table for Global COP.

    Default view: Styrene nodes only (RPC-queryable).
    Tab/f toggles to the full announce neighbourhood.
    LOST nodes are always shown and sorted first so critical issues are
    immediately visible without any operator action.
    """

    COLUMN_KEYS = ("name", "type", "status", "hops", "last_seen", "caps")

    class NodeSelected(Message):
        """Posted when the operator activates a row."""

        def __init__(self, identity_hash: str) -> None:
            super().__init__()
            self.identity_hash = identity_hash

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._all_devices: list[MeshDevice] = []
        self._styrene_only: bool = True  # Styrene-primary by default

    @property
    def styrene_only(self) -> bool:
        return self._styrene_only

    @property
    def device_count(self) -> int:
        return len(self._all_devices)

    def toggle_scope(self) -> bool:
        """Toggle between Styrene-only and full neighbourhood.

        Returns:
            New value of ``styrene_only``.
        """
        self._styrene_only = not self._styrene_only
        self._rebuild_table()
        return self._styrene_only

    def on_mount(self) -> None:
        self.add_columns(
            ("name", "NAME"),
            ("type", "TYPE"),
            ("status", "STATUS"),
            ("hops", "HOPS"),
            ("last_seen", "LAST SEEN"),
            ("caps", "CAPABILITIES"),
        )
        self.cursor_type = "row"

    def load_devices(self, devices: list[MeshDevice]) -> None:
        """Replace the device list and rebuild the table."""
        self._all_devices = devices
        self._rebuild_table()

    def _health_key(self, device: MeshDevice) -> tuple:
        """Sort key: LOST first, then STALE, then ACTIVE; tie-break by hops then name."""
        return (
            _HEALTH_ORDER.get(device.status, 2),
            device.hops if device.hops is not None else 999,
            (device.name or "").lower(),
        )

    def _rebuild_table(self) -> None:
        cascade = get_color_cascade()

        devices = self._all_devices
        if self._styrene_only:
            devices = [d for d in devices if d.device_type in _STYRENE_TYPES]

        devices = sorted(devices, key=self._health_key)

        # Preserve current cursor selection across rebuild
        selected_key: str | None = None
        if self.cursor_row is not None and self.row_count > 0:
            try:
                cell_key = self.coordinate_to_cell_key(Coordinate(self.cursor_row, 0))
                if cell_key and cell_key.row_key:
                    selected_key = str(cell_key.row_key.value)
            except Exception:
                pass

        self.clear()

        if not devices:
            scope_str = "Styrene nodes" if self._styrene_only else "peers"
            self.add_row(
                f"[{cascade.dim}]No {scope_str} discovered[/]",
                "", "", "", "", "",
            )
            return

        for device in devices:
            is_lost = device.status == NodeStatus.LOST
            is_stale = device.status == NodeStatus.STALE

            if is_lost:
                row_color = cascade.dim
                status_text = f"[{cascade.dim}]✗ LOST[/]"
            elif is_stale:
                row_color = cascade.medium
                status_text = f"[{cascade.medium}]~ STALE[/]"
            else:
                row_color = cascade.bright
                status_text = f"[{cascade.bright}]● ACTIVE[/]"

            # Name
            name = device.name or (device.destination_hash[:8] if device.destination_hash else "?")
            name_text = f"[{row_color}]{name}[/]"

            # Device type (short label)
            dt_val = device.device_type.value if hasattr(device.device_type, "value") else str(device.device_type)
            type_short = dt_val.replace("_node", "").replace("_hub", " hub").replace("_", "-")
            type_text = f"[{cascade.dim}]{type_short}[/]"

            # Hops
            if device.hops is not None:
                if device.hops == 0:
                    hops_text = f"[{cascade.medium}]direct[/]"
                else:
                    hops_text = f"[{cascade.dim}]{device.hops}[/]"
            else:
                hops_text = f"[{cascade.dim}]—[/]"

            # Last seen — use display helper if available
            last_seen = (
                getattr(device, "last_seen_display", None)
                or getattr(device, "last_announce_display", None)
                or "—"
            )
            last_seen_text = f"[{row_color}]{last_seen}[/]"

            # Capabilities (first three, space-separated)
            caps = getattr(device, "capabilities", None) or []
            caps_str = " ".join(str(c) for c in caps[:3]) if caps else "—"
            caps_text = f"[{cascade.dim}]{caps_str}[/]"

            row_key = device.identity_hash or device.destination_hash
            self.add_row(
                name_text, type_text, status_text, hops_text, last_seen_text, caps_text,
                key=row_key,
            )

        # Restore cursor to previously selected row
        if selected_key:
            try:
                for row_idx in range(self.row_count):
                    cell_key = self.coordinate_to_cell_key(Coordinate(row_idx, 0))
                    if cell_key and cell_key.row_key and str(cell_key.row_key.value) == selected_key:
                        self.move_cursor(row=row_idx)
                        break
            except Exception:
                pass

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.post_message(self.NodeSelected(str(event.row_key.value)))
