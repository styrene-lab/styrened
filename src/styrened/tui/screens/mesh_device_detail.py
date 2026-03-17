from __future__ import annotations

"""Mesh Device Detail Screen - Unified detail view with tabbed interface.

Central hub for all peer-to-peer interactions with a node: status, chat,
fleet operations (structured RPC), and terminal (PTY-over-RNS).
"""

from typing import TYPE_CHECKING, Any, ClassVar

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Static, TabbedContent, TabPane
from textual.worker import Worker

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.services.reticulum import discover_devices
from styrened.tui.widgets.chat_widget import ChatWidget
from styrened.tui.widgets.command_widget import CommandWidget
from styrened.tui.widgets.device_status_widget import DeviceStatusWidget
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade
from styrened.tui.widgets.page_browser import PageBrowserWidget
from styrened.tui.widgets.safe_header import Header
from styrened.tui.widgets.terminal_widget import TerminalWidget
from styrened.ui_state import (
    PeerWorkspaceContext,
    PeerWorkspaceFocus,
    WorkspaceId,
    build_peer_workspace_context,
)

if TYPE_CHECKING:
    from styrened.rpc.messages import StatusResponse

# ── Status cache ──────────────────────────────────────────────────
# LRU TTL cache: {identity_hash: (StatusResponse, timestamp)}
# Shows cached data instantly on re-open; background refresh still runs.
import time

_STATUS_CACHE: dict[str, tuple[Any, float]] = {}
_STATUS_CACHE_TTL = 120.0  # 2 minutes
_STATUS_CACHE_MAX = 64  # Max cached devices — evict oldest on overflow


def _cache_status(identity: str, status: Any) -> None:
    _STATUS_CACHE[identity] = (status, time.time())
    # Evict oldest entries if over capacity
    if len(_STATUS_CACHE) > _STATUS_CACHE_MAX:
        oldest_key = min(_STATUS_CACHE, key=lambda k: _STATUS_CACHE[k][1])
        _STATUS_CACHE.pop(oldest_key, None)


def _get_cached_status(identity: str) -> Any | None:
    entry = _STATUS_CACHE.get(identity)
    if entry and (time.time() - entry[1]) < _STATUS_CACHE_TTL:
        return entry[0]
    # Expired — remove it
    if entry:
        _STATUS_CACHE.pop(identity, None)
    return None


def _format_bytes(n: int) -> str:
    """Format byte count as human-readable label."""
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.0f}MB"
    elif n >= 1024:
        return f"{n / 1024:.0f}KB"
    return f"{n}B"


class MeshInfoWidget(Static):
    """Widget displaying mesh discovery information about device."""

    CSS = """
    MeshInfoWidget {
        height: auto;
    }

    .info-actions {
        height: auto;
        margin-top: 1;
        padding: 0;
    }

    .info-actions Button {
        margin: 0 1 0 0;
        min-width: 16;
    }
    """

    def __init__(self, device: MeshDevice, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """Initialize mesh info widget.

        Args:
            device: MeshDevice to display.
            **kwargs: Additional widget arguments.
        """
        super().__init__(**kwargs)
        self.device = device

    def compose(self) -> ComposeResult:
        """Compose mesh info fields."""
        cascade = get_color_cascade()

        # Device name with type-based styling
        if self.device.is_styrene_node:
            yield Static(f"[{cascade.bright} bold]Name:[/] {self.device.name}", classes="info-field")
        elif self.device.is_rnode:
            yield Static(f"[{cascade.medium} bold]Name:[/] {self.device.name}", classes="info-field")
        else:
            yield Static(f"[bold]Name:[/] {self.device.name}", classes="info-field")

        # Device type
        type_display = {
            DeviceType.STYRENE_NODE: f"[{cascade.bright} bold]STYRENE NODE[/]",
            DeviceType.RNODE: f"[{cascade.medium} bold]RNODE[/]",
            DeviceType.HUB: f"[{cascade.bright} bold]HUB[/]",
            DeviceType.LXMF_PEER: f"[{cascade.medium}]LXMF PEER[/]",
            DeviceType.PROPAGATION_NODE: f"[{cascade.medium} bold]PROPAGATION[/]",
            DeviceType.NOMADNET_NODE: f"[{cascade.medium} bold]NOMADNET NODE[/]",
            DeviceType.GENERIC: f"[{cascade.dim}]GENERIC[/]",
            DeviceType.UNKNOWN: f"[{cascade.dim}]UNKNOWN[/]",
        }
        type_text = type_display.get(self.device.device_type, f"[{cascade.dim}]?[/]")
        yield Static(f"[bold]Type:[/] {type_text}", classes="info-field")

        # Identity (full hash — not truncated)
        yield Static(f"[bold]Identity:[/] {self.device.identity_hash}", classes="info-field")

        # Last seen
        yield Static(f"[bold]Last Seen:[/] {self.device.last_seen_display}", classes="info-field")

        # Announce count
        if self.device.announce_count > 1:
            yield Static(f"[bold]Announces:[/] {self.device.announce_count}", classes="info-field")

        # Capabilities (if Styrene node)
        if self.device.capabilities:
            caps_str = ", ".join(self.device.capabilities)
            yield Static(f"[bold]Capabilities:[/] {caps_str}", classes="info-field")

        # Version (if available)
        if self.device.version:
            yield Static(f"[bold]Version:[/] {self.device.version}", classes="info-field")

        # Routing info — hops and discovery interface
        if self.device.hops is not None:
            hops_label = "direct" if self.device.hops == 0 else f"{self.device.hops} hop{'s' if self.device.hops != 1 else ''}"
            yield Static(f"[bold]Hops:[/] {hops_label}", classes="info-field")

        if self.device.discovered_via:
            yield Static(f"[bold]Via:[/] [{cascade.dim}]{self.device.discovered_via}[/]", classes="info-field")

        # LXMF destination (for messaging routing)
        if self.device.lxmf_destination_hash:
            yield Static(f"[bold]LXMF:[/] [{cascade.dim}]{self.device.lxmf_destination_hash}[/]", classes="info-field")

        # Action buttons (ASCII labels — emoji cause width issues in terminals)
        with Horizontal(classes="info-actions"):
            yield Button("Message", id="btn-message", variant="primary")
            yield Button("Add Contact", id="btn-add-contact", variant="success")
            yield Button("Copy Hash", id="btn-copy-hash", variant="default")


class MeshDeviceDetailScreen(Screen[None]):
    """Unified detail screen for mesh devices with tabbed interface.

    Provides a persistent header with device info and tabbed content for:
    - Status: RPC status queries with refresh
    - Chat: Peer-to-peer messaging via ChatWidget
    - Fleet Ops: Structured fleet operations over LXMF store-and-forward
    - Terminal: PTY-over-RNS interactive shell (future)
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "go_back", "Back"),
        Binding("r", "refresh_status", "Refresh"),
        Binding("l", "establish_link", "Link"),
        Binding("t", "run_speedtest", "Speedtest"),
        Binding("ctrl+n", "add_contact", "Add Contact"),
        Binding("y", "copy_hash", "Copy Hash"),
    ]

    def __init__(
        self,
        device_identity: str,
        initial_status: StatusResponse | None = None,
        initial_tab: str | None = None,
        device: MeshDevice | None = None,
        origin_workspace: WorkspaceId | str | None = None,
        peer_context: PeerWorkspaceContext | None = None,
    ) -> None:
        """Initialize mesh device detail screen.

        Args:
            device_identity: Reticulum identity hash of device.
            initial_status: Optional pre-fetched status response.
            initial_tab: Optional tab ID to open initially (e.g. "chat", "fleet-ops", "terminal").
            device: Optional pre-resolved MeshDevice (avoids re-query).
            origin_workspace: Aggregate workspace that launched the peer workspace.
            peer_context: Optional pre-built canonical peer workspace context.
        """
        super().__init__()
        self.device_identity = device_identity
        self.initial_status = initial_status
        self.initial_tab = initial_tab
        self.device: MeshDevice | None = device
        self.peer_context = peer_context or build_peer_workspace_context(
            device_identity,
            origin_workspace,
            focus=initial_tab,
        )
        self._device_load_worker: Worker | None = None
        self._status_worker: Worker | None = None
        self._link_worker: Worker | None = None
        self._speedtest_worker: Worker | None = None
        self._contact_worker: Worker | None = None
        self._device_lookup_complete = device is not None

    @property
    def origin_workspace(self) -> WorkspaceId:
        """Aggregate workspace that launched this peer workspace."""
        return self.peer_context.origin_workspace

    @property
    def requested_focus(self) -> PeerWorkspaceFocus:
        """Requested initial focus within the peer workspace."""
        return self.peer_context.focus

    @property
    def _dest_hash(self) -> str:
        """Destination hash for datalink operations.

        DirectLinkService needs a destination hash (not identity hash)
        for RNS.Identity.recall(). Falls back to identity hash if
        device object lacks a destination_hash.
        """
        if self.device and self.device.destination_hash:
            return self.device.destination_hash
        return self.device_identity

    def _find_live_device(self) -> MeshDevice | None:
        """Find the device in current live discovery, if present."""
        live_nodes: list[MeshDevice] = []

        try:
            cache = getattr(self.app, "device_cache", None)
        except Exception:
            cache = None

        if cache is not None:
            try:
                live_nodes = list(cache.get())
            except Exception:
                live_nodes = []

        # An existing cache may still be unprimed on first detail-screen mount.
        # Fall back to direct discovery rather than treating empty cache state as
        # authoritative absence.
        if not live_nodes:
            live_nodes = discover_devices()

        for device in live_nodes:
            if device.identity_hash == self.device_identity:
                return device

        return None

    def compose(self) -> ComposeResult:
        """Compose screen layout with persistent header and tabbed content."""
        yield Header()

        if not self.device:
            message = (
                f"[{get_color_cascade().color_warning}]Loading device {self.device_identity[:8]}...[/]"
                if not self._device_lookup_complete
                else f"[{get_color_cascade().color_danger}]Device {self.device_identity[:8]}... not found[/]"
            )
            title = "LOADING" if not self._device_lookup_complete else "ERROR"
            yield HighlightedPanel(
                Static(message, classes="error-message"),
                title=title,
                classes="panel-alert-error",
            )
        else:
            with Container(id="mesh-device-detail-container"):
                # Persistent header: mesh info
                yield HighlightedPanel(
                    MeshInfoWidget(self.device),
                    title="MESH INFO",
                    id="mesh-info-panel",
                    classes="panel-info",
                )

                # Default to pages tab for NomadNet nodes
                default_tab = self.initial_tab
                if not default_tab and self.device.is_nomadnet_node:
                    default_tab = "pages"

                # Tabbed content
                with TabbedContent(
                    initial=default_tab or "status",
                    id="device-tabs",
                ):
                    # Status tab — two-column dashboard with announce + link data
                    with TabPane("Status", id="status"):
                        status_widget = DeviceStatusWidget(
                            device=self.device, id="status-widget"
                        )
                        if self.initial_status:
                            status_widget.status = self.initial_status
                        yield status_widget

                    # Mail tab — peer-scoped thread list (placeholder for 0.16.1;
                    # full implementation filters InboxScreen by identity_hash)
                    with TabPane("Mail", id="mail"):
                        yield Static(
                            f"[{get_color_cascade().dim}]Mail for peer[/]\n"
                            f"[{get_color_cascade().dim}]({self.device_identity[:16]}...)[/]\n\n"
                            f"[{get_color_cascade().dim}]Full per-peer mail view coming in a future release.[/]",
                            id="mail-placeholder",
                        )

                    # Chat / Comms tab
                    with TabPane("Chat", id="chat"):
                        yield ChatWidget(
                            peer_hash=self.device_identity,
                            display_name=self.device.name,
                            id="chat-widget",
                        )

                    # Fleet Ops tab
                    with TabPane("Fleet Ops", id="fleet-ops"):
                        initial_cmds = (
                            self.initial_status.available_commands
                            if self.initial_status
                            and self.initial_status.available_commands
                            else None
                        )
                        yield CommandWidget(
                            device_identity=self.device_identity,
                            initial_available_commands=initial_cmds,
                            id="command-widget",
                        )

                    # Pages tab — shown for NomadNet nodes, or any node whose
                    # identity also has a NomadNet announce (e.g., Styrene hubs)
                    pages_dest = self._resolve_nomadnet_destination()
                    if pages_dest:
                        with TabPane("Pages", id="pages"):
                            yield PageBrowserWidget(
                                destination_hash=pages_dest,
                                id="page-browser-widget",
                            )

                    # Terminal tab
                    with TabPane("Terminal", id="terminal"):
                        yield TerminalWidget(
                            device_identity=self.device_identity,
                            id="terminal-widget",
                        )

        yield Footer()

    def _resolve_nomadnet_destination(self) -> str | None:
        """Find a NomadNet destination hash for page browsing.

        Resolution order:
        1. Device is a NOMADNET_NODE directly → use its destination hash
        2. Device advertises 'pages' capability → compute the NomadNet
           destination hash from its identity (same identity, different aspect)
        3. Another device in the store/live list shares the same identity_hash
           and is a NOMADNET_NODE → use that destination hash

        Strategy 2 covers Styrene hubs that run both styrened (with page_server
        enabled) and NomadNet — they share an RNS identity but the NomadNet
        announce may arrive on a different destination hash.
        """
        if self.device is None:
            return None

        if self.device.is_nomadnet_node:
            return self.device.destination_hash

        # Check if the announce includes a NomadNet destination hash directly
        # (set when page_server is active, including bridge mode with NomadNet)
        if self.device.nomadnet_destination_hash:
            return self.device.nomadnet_destination_hash

        target_identity = self.device.identity_hash
        if not target_identity:
            return None

        from styrened.models.mesh_device import DeviceType

        # Check live discovered devices via the shared DeviceCache first, but
        # do not treat an empty cache as authoritative absence during startup.
        try:
            cache = getattr(self.app, "device_cache", None)
            live_nodes: list[MeshDevice] = list(cache.get()) if cache is not None else []
            if not live_nodes:
                live_nodes = discover_devices()
            for node in live_nodes:
                if (
                    node.identity_hash == target_identity
                    and node.device_type == DeviceType.NOMADNET_NODE
                ):
                    return node.destination_hash
        except Exception:
            pass

        return None

    def _start_device_load(self) -> Worker:
        """Start or replace the device-resolution worker."""
        self._device_load_worker = self.run_worker(
            self._async_load_device(),
            group="device-load",
            exclusive=True,
        )
        return self._device_load_worker

    def _start_status_refresh(self) -> Worker:
        """Start or replace the status-refresh worker."""
        self._status_worker = self.run_worker(
            self._auto_fetch_status(),
            group="device-status",
            exclusive=True,
        )
        return self._status_worker

    def on_mount(self) -> None:
        """Auto-fetch status when the screen mounts if no initial data."""
        if self.device is None:
            # Device not found in live discovery — try stored nodes via IPC
            self._start_device_load()
        elif self.initial_status is None:
            self._start_status_refresh()

    def _cancel_inflight_workers(self) -> None:
        """Cancel and clear any tracked screen-owned workers."""
        for attr in (
            "_device_load_worker",
            "_status_worker",
            "_link_worker",
            "_speedtest_worker",
            "_contact_worker",
        ):
            worker = getattr(self, attr)
            if worker is not None:
                worker.cancel()
                setattr(self, attr, None)

    def _start_link_establish(self, bridge: Any) -> Worker:
        """Start or replace the direct-link worker."""
        self._link_worker = self.run_worker(
            self._do_establish_link(bridge),
            group="device-link",
            exclusive=True,
        )
        return self._link_worker

    def _start_speedtest(self, bridge: Any) -> Worker:
        """Start or replace the speedtest worker."""
        self._speedtest_worker = self.run_worker(
            self._do_speedtest(bridge),
            group="device-speedtest",
            exclusive=True,
        )
        return self._speedtest_worker

    def _start_contact_save(self, bridge: Any, default_name: str) -> Worker:
        """Start or replace the contact-save worker."""
        self._contact_worker = self.run_worker(
            self._save_contact(bridge, default_name),
            group="device-contact-save",
            exclusive=True,
        )
        return self._contact_worker

    def on_screen_suspend(self, event: events.ScreenSuspend) -> None:
        """Cancel in-flight detail workers while the peer workspace is inactive."""
        self._cancel_inflight_workers()

    def on_screen_resume(self, event: events.ScreenResume) -> None:
        """Refresh peer detail when returning to this workspace."""
        if self.device is None:
            self._start_device_load()
        else:
            self._start_status_refresh()

    def on_unmount(self) -> None:
        """Cancel in-flight detail workers when the peer workspace is removed."""
        self._cancel_inflight_workers()

    async def _async_load_device(self) -> None:
        """Resolve the device from live discovery first, then stored IPC nodes."""
        try:
            live_device = self._find_live_device()
            if live_device is not None:
                self.device = live_device
                self._device_lookup_complete = True
                self.refresh(recompose=True)
                self.call_after_refresh(self._start_status_refresh)
                return

            bridge = getattr(getattr(self.app, "services", None), "bridge", None)
            if bridge is not None:
                stored_raw = await bridge.get_nodes(styrene_only=False)
                from styrened.tui.utils import device_info_to_mesh

                for info in stored_raw:
                    device = device_info_to_mesh(info)
                    if device.identity_hash == self.device_identity:
                        self.device = device
                        self._device_lookup_complete = True
                        self.refresh(recompose=True)
                        self.call_after_refresh(self._start_status_refresh)
                        return
        except Exception:
            pass

        self._device_lookup_complete = True
        self.refresh(recompose=True)
        self.notify(
            f"Device {self.device_identity[:8]}... not found in mesh",
            title="Error",
            severity="error",
        )

    async def _auto_fetch_status(self) -> None:
        """Silently fetch status on mount — tries datalink first, then RPC.

        Falls back gracefully: datalink query → RPC over LXMF → no data.
        Also queries datalink status to populate the LINK panel.
        """
        try:
            status_widget = self.query_one("#status-widget", DeviceStatusWidget)
        except Exception:
            return

        status_widget.loading = True
        status_widget.error = None

        # Check datalink status (non-blocking, just reads cached state)
        bridge = None
        try:
            bridge = self.app.services.bridge
            if bridge:
                link_info = await bridge.datalink_status(
                    destination_hash=self._dest_hash,
                )
                status_widget.link_info = link_info
        except Exception:
            pass

        # Check status cache — show stale data instantly, then refresh
        got_status = False
        cached = _get_cached_status(self.device_identity)
        if cached is not None:
            status_widget.status = cached
            status_widget.loading = False  # Stop spinner, show cached data
            # Don't set got_status — still attempt a fresh fetch below

        # Try datalink query (low latency if link exists)
        if not got_status:
            try:
                if bridge and status_widget.link_info and status_widget.link_info.get("connected"):
                    result = await bridge.datalink_query(
                        destination_hash=self._dest_hash,
                    )
                    if result and "status_data" in result:
                        sd = result["status_data"]
                        from styrened.rpc.messages import StatusResponse

                        resp = StatusResponse(
                            uptime=sd.get("uptime", 0),
                            ip=sd.get("ip", ""),
                            services=sd.get("services", []),
                            disk_used=sd.get("disk_used", 0),
                            disk_total=sd.get("disk_total", 0),
                            styrened_version=sd.get("styrened_version"),
                            hostname=sd.get("hostname"),
                            arch=sd.get("arch"),
                            os_id=sd.get("os_id"),
                            os_version=sd.get("os_version"),
                            nixos_generation=sd.get("nixos_generation"),
                            available_commands=sd.get("available_commands"),
                        )
                        status_widget.status = resp
                        _cache_status(self.device_identity, resp)
                        got_status = True
            except Exception:
                pass

        # Fall back to RPC-over-LXMF via IPC bridge
        if not got_status:
            try:
                bridge = getattr(getattr(self.app, "services", None), "bridge", None)
                if bridge is not None:
                    response = await bridge.query_device_status(
                        destination=self.device_identity,
                        timeout=30.0,
                    )
                    status_widget.status = response
                    _cache_status(self.device_identity, response)
            except Exception:
                # No RPC data — status widget shows announce data only
                pass

        status_widget.loading = False

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: Button pressed event.
        """
        if str(event.button.id) == "btn-message":
            self._switch_to_chat()
        elif str(event.button.id) == "btn-add-contact":
            self.action_add_contact()
        elif str(event.button.id) == "btn-copy-hash":
            self.action_copy_hash()


    def action_go_back(self) -> None:
        """Leave peer workspace and return to the originating screen stack context."""
        self.app.pop_screen()

    async def action_refresh_status(self) -> None:
        """Refresh device status — tries datalink, falls back to RPC."""
        if not self.device:
            return
        self._start_status_refresh()
        self.notify("Refreshing...", severity="information")

    async def action_establish_link(self) -> None:
        """Establish a direct data link to this peer."""
        if not self.device:
            return

        try:
            bridge = self.app.services.bridge
        except Exception:
            self.notify("Direct links require daemon mode", severity="warning")
            return
        if not bridge:
            self.notify("Direct links require daemon mode", severity="warning")
            return

        # Only for Styrene-enabled nodes
        if not self.device.is_styrene_node:
            self.notify("Direct links require a Styrene-enabled peer", severity="warning")
            return

        self.notify("Establishing direct link...", severity="information")
        self._start_link_establish(bridge)

    async def _do_establish_link(self, bridge: Any) -> None:
        """Background worker: establish datalink and refresh status."""
        try:
            result = await bridge.datalink_establish(
                destination_hash=self._dest_hash,
            )
            status = result.get("status", "failed")

            try:
                sw = self.query_one("#status-widget", DeviceStatusWidget)
                link_info = await bridge.datalink_status(
                    destination_hash=self._dest_hash,
                )
                sw.link_info = link_info
            except Exception:
                pass

            if status == "active":
                self.notify("Direct link established ●", severity="information")
                # Auto-query status over the new link
                self._start_status_refresh()
            else:
                self.notify(f"Link status: {status}", severity="warning")

        except Exception as e:
            self.notify(f"Link failed: {e}", severity="error")

    async def action_run_speedtest(self) -> None:
        """Run bandwidth test over the direct link."""
        if not self.device:
            return

        try:
            bridge = self.app.services.bridge
        except Exception:
            self.notify("Speedtest requires daemon mode", severity="warning")
            return
        if not bridge:
            self.notify("Speedtest requires daemon mode", severity="warning")
            return

        # Check if link is active — auto-establish if not
        needs_link = True
        try:
            link_info = await bridge.datalink_status(
                destination_hash=self._dest_hash,
            )
            needs_link = not link_info.get("connected")
        except Exception:
            pass  # status call failed — assume link needed

        if needs_link:
            self.notify("Establishing link for speedtest...", severity="information")
            try:
                result = await bridge.datalink_establish(
                    destination_hash=self._dest_hash,
                )
                if result.get("status") != "active":
                    self.notify("Could not establish link — peer may be unreachable directly", severity="warning")
                    return
            except Exception as e:
                self.notify(f"Link failed: {e}", severity="error")
                return

        self.notify("Running speedtest... (adaptive payload sizes)", severity="information")
        self._start_speedtest(bridge)

    async def _do_speedtest(self, bridge: Any) -> None:
        """Background worker: run speedtest and display results."""
        try:
            result = await bridge.datalink_speedtest(
                destination_hash=self._dest_hash,
            )
            results = result.get("results", [])

            if not results:
                self.notify("Speedtest returned no results", severity="warning")
                return

            # Format results for notification and status widget
            lines = ["[bold]─── SPEEDTEST RESULTS ───[/]"]
            link_rtt = None
            for r in results:
                size = r.get("size", 0)
                status = r.get("status", "?")
                if not link_rtt and r.get("link_rtt"):
                    link_rtt = r["link_rtt"]

                if status == "ok":
                    rtt = r.get("rtt", 0)
                    kbps = r.get("throughput_kbps", 0)
                    peer_rx = r.get("peer_received", 0)
                    size_label = _format_bytes(size)
                    lines.append(
                        f"  {size_label:>6}  →  "
                        f"RTT {rtt:.2f}s  "
                        f"{kbps:.1f} kbps  "
                        f"(peer rx: {peer_rx}B)"
                    )
                elif status == "skipped":
                    lines.append(f"  {_format_bytes(size):>6}  →  [{get_color_cascade().dim}]skipped[/]")
                elif status == "timeout":
                    lines.append(f"  {_format_bytes(size):>6}  →  [{get_color_cascade().color_warning}]timeout[/]")
                else:
                    lines.append(f"  {_format_bytes(size):>6}  →  [{get_color_cascade().color_danger}]{status}[/]")

            if link_rtt:
                lines.insert(1, f"  Link RTT: {link_rtt:.3f}s")

            # Find the best throughput
            ok_results = [r for r in results if r.get("status") == "ok"]
            if ok_results:
                best = max(ok_results, key=lambda r: r.get("throughput_kbps", 0))
                lines.append(f"  [bold]Peak: {best['throughput_kbps']:.1f} kbps[/]")

            # Push results into status widget
            try:
                sw = self.query_one("#status-widget", DeviceStatusWidget)
                sw.speedtest_results = results
            except Exception:
                pass

            self.notify("\n".join(lines), severity="information", timeout=15)

        except Exception as e:
            self.notify(f"Speedtest failed: {e}", severity="error")

    def action_add_contact(self) -> None:
        """Add this device as a contact."""
        if not self.device:
            return

        try:
            bridge = self.app.services.bridge
        except Exception:
            self.notify("Contacts require daemon mode", severity="warning")
            return

        if bridge is None:
            self.notify("Contacts require daemon mode", severity="warning")
            return

        name = self.device.name or self.device_identity[:8]
        self._start_contact_save(bridge, name)

    async def _save_contact(self, bridge: Any, default_name: str) -> None:
        """Save device as contact via IPCBridge."""
        try:
            await bridge.set_contact(
                peer_hash=self.device_identity,
                alias=default_name,
            )
            self.notify(f"Contact saved: {default_name}", severity="information")
        except Exception as e:
            self.notify(f"Failed to save contact: {e}", severity="error")

    def _switch_to_chat(self) -> None:
        """Switch to the Chat tab."""
        try:
            tabs = self.query_one("#device-tabs", TabbedContent)
            tabs.active = "chat"
        except Exception:
            pass

    def action_copy_hash(self) -> None:
        """Copy the device identity hash to the clipboard."""
        try:
            self.app.copy_to_clipboard(self.device_identity)
            self.notify("Hash copied to clipboard", severity="information")
        except Exception:
            self.notify("Copy failed", severity="warning")
