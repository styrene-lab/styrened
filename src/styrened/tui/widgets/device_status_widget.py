"""Device status widget — two-column dashboard for mesh device detail.

Displays announce data (always available) enriched with RPC/datalink data
when available.  Uses the Imperial CRT cascade color system.

Layout:
    Left column:  NODE, MESH
    Right column: LINK, SYSTEM, NETWORK
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from textual.reactive import reactive
from textual.widgets import Static

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.widgets.highlighted_panel import get_color_cascade

if TYPE_CHECKING:
    from styrened.rpc.messages import StatusResponse


class DeviceStatusWidget(Static):
    """Two-column device status dashboard.

    Attributes:
        device: MeshDevice from announce data (always set).
        status: Optional RPC StatusResponse (enrichment).
        link_info: Optional direct link info dict.
        loading: Whether a request is in progress.
        error: Error message to display.
    """

    DEFAULT_CSS = """
    DeviceStatusWidget {
        height: auto;
        padding: 0 1;
    }
    """

    status: reactive[StatusResponse | None] = reactive(None)
    link_info: reactive[dict | None] = reactive(None)
    speedtest_results: reactive[list | None] = reactive(None)
    loading: reactive[bool] = reactive(False)
    error: reactive[str | None] = reactive(None)
    last_updated: reactive[str | None] = reactive(None)

    def __init__(self, device: MeshDevice | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.device = device

    def _render_left(self, cascade: Any) -> list[str]:
        """Left column: NODE + MESH from announce data."""
        lines: list[str] = []
        d = self.device

        # ── NODE ──
        lines.append(f"[{cascade.bright}]NODE[/]")
        if d:
            type_display = {
                DeviceType.STYRENE_NODE: f"[{cascade.bright} bold]STYRENE NODE[/]",
                DeviceType.HUB: f"[{cascade.bright} bold]HUB[/]",
                DeviceType.RNODE: f"[{cascade.medium} bold]RNODE[/]",
                DeviceType.LXMF_PEER: f"[{cascade.medium}]LXMF PEER[/]",
                DeviceType.PROPAGATION_NODE: f"[{cascade.medium}]PROPAGATION[/]",
                DeviceType.NOMADNET_NODE: f"[{cascade.medium}]NOMADNET[/]",
                DeviceType.GENERIC: f"[{cascade.dim}]GENERIC[/]",
                DeviceType.UNKNOWN: f"[{cascade.dim}]UNKNOWN[/]",
            }
            lines.append(f"  Type: {type_display.get(d.device_type, f'[{cascade.dim}]?[/]')}")
            if d.version:
                lines.append(f"  Version: [{cascade.medium}]{d.version}[/]")
            if d.capabilities:
                lines.append(f"  Caps: [{cascade.medium}]{', '.join(d.capabilities)}[/]")
            if d.short_name:
                lines.append(f"  Alias: [{cascade.medium}]{d.short_name}[/]")
        else:
            lines.append(f"  [{cascade.dim}]no device data[/]")

        # ── MESH ──
        lines.append("")
        lines.append(f"[{cascade.bright}]MESH[/]")
        if d:
            lines.append(f"  Identity: [{cascade.dim}]{d.identity_hash[:16]}[/]")
            lines.append(f"  Dest: [{cascade.dim}]{d.destination_hash[:16]}[/]")
            lines.append(f"  Seen: [{cascade.medium}]{d.last_seen_display}[/]")
            if d.announce_count > 0:
                lines.append(f"  Announces: [{cascade.medium}]{d.announce_count}[/]")
            if d.hops is not None:
                lines.append(f"  Hops: [{cascade.medium}]{d.hops}[/]")
            if d.discovered_via:
                via = d.discovered_via
                if len(via) > 30:
                    via = via[:27] + "..."
                lines.append(f"  Via: [{cascade.medium}]{via}[/]")
            if d.nomadnet_destination_hash:
                lines.append(f"  Pages: [{cascade.dim}]{d.nomadnet_destination_hash[:16]}[/]")

        return lines

    def _render_right(self, cascade: Any) -> list[str]:
        """Right column: LINK + SYSTEM + NETWORK."""
        lines: list[str] = []
        s = self.status
        li = self.link_info

        # ── LINK ──
        lines.append(f"[{cascade.bright}]LINK[/]")
        if li:
            link_status = li.get("status", "none")
            if link_status == "active":
                rtt = li.get("rtt")
                rtt_str = f" (RTT: {rtt:.3f}s)" if rtt else ""
                lines.append(f"  Status: ● [{cascade.bright}]active{rtt_str}[/]")
                est = li.get("established_at")
                if est:
                    ago = time.time() - est
                    if ago < 60:
                        lines.append(f"  Since: [{cascade.medium}]{int(ago)}s ago[/]")
                    elif ago < 3600:
                        lines.append(f"  Since: [{cascade.medium}]{int(ago / 60)}m ago[/]")
                    else:
                        lines.append(f"  Since: [{cascade.medium}]{int(ago / 3600)}h ago[/]")
            elif link_status == "establishing":
                lines.append(f"  Status: ◐ [{cascade.medium}]establishing...[/]")
            else:
                lines.append(f"  Status: ○ [{cascade.dim}]not connected[/]")
                lines.append(f"  [{cascade.dim}]Press L to establish[/]")
        else:
            lines.append(f"  Status: ○ [{cascade.dim}]not connected[/]")
            lines.append(f"  [{cascade.dim}]Press L to establish[/]")

        # ── SYSTEM ── (from RPC or datalink query)
        lines.append("")
        lines.append(f"[{cascade.bright}]SYSTEM[/]")
        if self.loading:
            lines.append(f"  [{cascade.dim}]⏳ Querying...[/]")
        elif self.error:
            lines.append(f"  [{cascade.dim}]⚠ {self.error}[/]")
        elif s:
            if getattr(s, "hostname", None):
                lines.append(f"  Host: [{cascade.medium}]{s.hostname}[/]")
            if s.uptime == -1:
                lines.append(f"  Uptime: [{cascade.dim}]unknown[/]")
            elif s.uptime > 0:
                lines.append(f"  Uptime: [{cascade.medium}]{s.format_uptime()}[/]")
            os_parts: list[str] = []
            if s.os_id:
                os_parts.append(str(s.os_id))
            if s.os_version:
                os_parts.append(str(s.os_version))
            if s.arch:
                os_parts.append(f"({s.arch})")
            if os_parts:
                lines.append(f"  OS: [{cascade.medium}]{' '.join(os_parts)}[/]")
            if s.nixos_generation:
                lines.append(f"  NixOS: [{cascade.medium}]{s.nixos_generation}[/]")
            if s.styrened_version:
                lines.append(f"  Daemon: [{cascade.medium}]v{s.styrened_version}[/]")
        else:
            lines.append(f"  [{cascade.dim}]No RPC data — press R to query[/]")

        # ── NETWORK ── (from RPC)
        if s and (s.ip or s.services):
            lines.append("")
            lines.append(f"[{cascade.bright}]NETWORK[/]")
            if s.ip and s.ip not in ("", "127.0.0.1", "offline"):
                lines.append(f"  IP: [{cascade.medium}]{s.ip}[/]")
            elif s.ip:
                lines.append(f"  IP: [{cascade.dim}]{s.ip}[/]")
            if s.services:
                lines.append(f"  Services: [{cascade.medium}]{', '.join(s.services)}[/]")
            if s.disk_total > 0:
                lines.append(f"  Disk: [{cascade.medium}]{s.format_disk_usage()}[/]")
            if s.available_commands:
                lines.append(f"  Commands: [{cascade.dim}]{len(s.available_commands)} available[/]")

        # ── SPEEDTEST ── (from most recent run)
        if self.speedtest_results:
            lines.append("")
            lines.append(f"[{cascade.bright}]SPEEDTEST[/]")
            ok_results = [r for r in self.speedtest_results if r.get("status") == "ok"]
            max_kbps = max((r.get("throughput_kbps", 0) for r in ok_results), default=1) or 1
            for r in ok_results:
                sz = r.get("size", 0)
                kbps = r.get("throughput_kbps", 0)
                label = f"{sz // 1024}K" if sz >= 1024 else f"{sz}B"
                bar_len = min(20, max(1, int(kbps / max_kbps * 20)))
                bar = "█" * bar_len + "░" * (20 - bar_len)
                lines.append(f"  {label:>5} [{cascade.medium}]{bar}[/] {kbps:.0f}kbps")
            if ok_results:
                best = max(ok_results, key=lambda r: r.get("throughput_kbps", 0))
                lines.append(f"  Peak: [{cascade.bright}]{best['throughput_kbps']:.1f} kbps[/]")
            # Show failed/skipped
            failed = [r for r in self.speedtest_results if r.get("status") not in ("ok", "skipped")]
            if failed:
                for r in failed:
                    sz = r.get("size", 0)
                    label = f"{sz // 1024}K" if sz >= 1024 else f"{sz}B"
                    lines.append(f"  {label:>5} [{cascade.dim}]{r['status']}[/]")

        # ── UPDATED ──
        if self.last_updated:
            lines.append("")
            lines.append(f"  [{cascade.dim}]Updated: {self.last_updated}[/]")

        return lines

    def render(self) -> str:
        """Render two-column status display."""
        cascade = get_color_cascade()

        # Show loading state when no status has arrived yet
        if self.loading and self.status is None:
            return f"[{cascade.dim}]⟳ Querying node status...[/]"

        left = self._render_left(cascade)
        right = self._render_right(cascade)

        # Pad to equal length
        max_lines = max(len(left), len(right))
        while len(left) < max_lines:
            left.append("")
        while len(right) < max_lines:
            right.append("")

        # Side-by-side with fixed left column width
        col_width = 40
        output_lines = []
        for l_line, r_line in zip(left, right, strict=True):
            visible_len = len(re.sub(r"\[.*?\]", "", l_line))
            pad = max(0, col_width - visible_len)
            output_lines.append(f"{l_line}{' ' * pad}{r_line}")

        return "\n".join(output_lines)

    def watch_status(self, status: StatusResponse | None) -> None:
        if status is not None:
            self.last_updated = datetime.now().strftime("%H:%M:%S")
        if self.is_mounted:
            self.refresh()

    def watch_link_info(self, link_info: dict | None) -> None:
        if self.is_mounted:
            self.refresh()

    def watch_speedtest_results(self, results: list | None) -> None:
        if self.is_mounted:
            self.refresh()

    def watch_loading(self, loading: bool) -> None:
        if self.is_mounted:
            self.refresh()

    def watch_error(self, error: str | None) -> None:
        if self.is_mounted:
            self.refresh()
