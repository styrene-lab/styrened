"""Mesh Device Detail Screen - Unified detail view with tabbed interface.

Central hub for all peer-to-peer interactions with a node: status, chat,
command execution, and future capabilities.
"""

from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static, TabbedContent, TabPane

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.rpc import RPCTimeoutError, RPCTransportError
from styrened.rpc.messages import StatusResponse
from styrened.tui.services.reticulum import discover_devices
from styrened.tui.widgets.chat_widget import ChatWidget
from styrened.tui.widgets.command_widget import CommandWidget
from styrened.tui.widgets.device_status_widget import DeviceStatusWidget
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade
from styrened.tui.widgets.page_browser import PageBrowserWidget

if TYPE_CHECKING:
    from styrened.tui.app import StyreneApp


class MeshInfoWidget(Static):
    """Widget displaying mesh discovery information about device."""

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
        yield Static(f"[bold]Identity:[/] {self.device.identity}", classes="info-field")

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


class MeshDeviceDetailScreen(Screen[None]):
    """Unified detail screen for mesh devices with tabbed interface.

    Provides a persistent header with device info and tabbed content for:
    - Status: RPC status queries with refresh
    - Chat: Peer-to-peer messaging via ChatWidget
    - Command: Remote command execution
    - SSH: Placeholder for future SSH terminal
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("r", "refresh_status", "Refresh"),
        Binding("a", "add_contact", "Add Contact"),
        Binding("y", "copy_hash", "Copy Hash"),
    ]

    def __init__(
        self,
        device_identity: str,
        initial_status: StatusResponse | None = None,
        initial_tab: str | None = None,
    ) -> None:
        """Initialize mesh device detail screen.

        Args:
            device_identity: Reticulum identity hash of device.
            initial_status: Optional pre-fetched status response.
            initial_tab: Optional tab ID to open initially (e.g. "chat", "command").
        """
        super().__init__()
        self.device_identity = device_identity
        self.initial_status = initial_status
        self.initial_tab = initial_tab
        self.device: MeshDevice | None = None
        # Load device before compose() runs
        self._load_device()

    def _load_device(self) -> None:
        """Load device from mesh discovery and NodeStore."""
        # Load from NodeStore (works in IPC mode where discover_devices is empty)
        try:
            from styrened.services.node_store import get_node_store

            stored_nodes = get_node_store().get_all_nodes()
        except Exception:
            stored_nodes = []

        # Get live discovered devices (populated in legacy/standalone mode)
        live_nodes = discover_devices()

        # Merge: live takes precedence
        all_devices = {d.destination_hash: d for d in stored_nodes}
        all_devices.update({d.destination_hash: d for d in live_nodes})

        # Find by identity
        for device in all_devices.values():
            if device.identity == self.device_identity:
                self.device = device
                return

        self.notify(
            f"Device {self.device_identity[:8]}... not found in mesh",
            title="Error",
            severity="error",
        )

    def compose(self) -> ComposeResult:
        """Compose screen layout with persistent header and tabbed content."""
        yield Header()

        if not self.device:
            # Device not found
            yield HighlightedPanel(
                Static(
                    f"[red]Device {self.device_identity[:8]}... not found[/]",
                    classes="error-message",
                ),
                title="ERROR",
            )
        else:
            with Container(id="mesh-device-detail-container"):
                # Persistent header: mesh info
                yield HighlightedPanel(
                    MeshInfoWidget(self.device),
                    title="MESH INFO",
                    id="mesh-info-panel",
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
                    # Pages tab (NomadNet nodes only)
                    if self.device.is_nomadnet_node:
                        with TabPane("Pages", id="pages"):
                            yield PageBrowserWidget(
                                destination_hash=self.device.destination_hash,
                                id="page-browser-widget",
                            )

                    # Status tab
                    with TabPane("Status", id="status"):
                        status_widget = DeviceStatusWidget(id="status-widget")
                        if self.initial_status:
                            status_widget.status = self.initial_status

                        yield Vertical(
                            Horizontal(
                                Button("Refresh", id="refresh-status-btn", variant="default"),
                                classes="panel-header",
                            ),
                            status_widget,
                        )

                    # Chat tab
                    with TabPane("Chat", id="chat"):
                        yield ChatWidget(
                            peer_hash=self.device_identity,
                            display_name=self.device.name,
                            id="chat-widget",
                        )

                    # Command tab
                    with TabPane("Command", id="command"):
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

                    # SSH tab (placeholder)
                    with TabPane("SSH", id="ssh"):
                        yield Static(
                            "[dim]SSH terminal — coming soon[/]",
                            classes="placeholder-text",
                        )

        yield Footer()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events.

        Args:
            event: Button pressed event.
        """
        if str(event.button.id) == "refresh-status-btn":
            await self.action_refresh_status()

    async def action_refresh_status(self) -> None:
        """Refresh device status via RPC call."""
        if not self.device:
            return

        # Get status widget
        try:
            status_widget = self.query_one("#status-widget", DeviceStatusWidget)
        except Exception:
            self.notify("Status widget not found", severity="error")
            return

        # Set loading state
        status_widget.loading = True
        status_widget.error = None

        try:
            # Make RPC call
            app: StyreneApp = self.app  # type: ignore[assignment]
            response = await app.rpc_client.call_status(
                self.device_identity,
                timeout=30.0,
            )

            # Update widget
            status_widget.status = response
            status_widget.error = None
            self.notify("Status updated", severity="information")

        except RPCTimeoutError:
            status_widget.error = "Device did not respond in time"
            self.notify(
                "Device did not respond - it may be offline or unreachable",
                title="Timeout",
                severity="warning",
                timeout=5,
            )

        except RPCTransportError as e:
            status_widget.error = f"Transport error: {e}"
            self.notify(
                f"Failed to send message: {e}",
                title="Transport Error",
                severity="error",
                timeout=5,
            )

        except Exception as e:
            status_widget.error = f"Error: {e}"
            self.notify(
                f"Unexpected error: {e}",
                title="Error",
                severity="error",
                timeout=5,
            )

        finally:
            status_widget.loading = False

    def action_add_contact(self) -> None:
        """Add this device as a contact."""
        if not self.device:
            return

        try:
            bridge = self.app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
        except Exception:
            self.notify("Contacts require daemon mode", severity="warning")
            return

        if bridge is None:
            self.notify("Contacts require daemon mode", severity="warning")
            return

        name = self.device.name or self.device_identity[:8]
        self.run_worker(self._save_contact(bridge, name))

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

    def action_copy_hash(self) -> None:
        """Copy the device identity hash to the clipboard."""
        try:
            self.app.copy_to_clipboard(self.device_identity)
            self.notify("Hash copied to clipboard", severity="information")
        except Exception:
            self.notify("Copy failed", severity="warning")
