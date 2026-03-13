"""Reticulum Panel widget for displaying mesh connection status.

Shows compact mesh connectivity info: mode, hub, network status, interfaces.
When in degraded state, displays error category and recovery guidance.

Uses cascade hex colors for Rich markup:
- medium: primary text (values, labels)
- dim: muted text (disabled, secondary)
- bright: accents only (sparingly)

Status colors use semantic classes in CSS, but for inline Rich markup
we use medium/dim from the cascade to avoid bright green everywhere.
"""

import RNS  # type: ignore
from textual.reactive import reactive
from textual.widgets import Static

from styrened.models.rns_error import RNSErrorState
from styrened.services.hub_connection import HubStatus, get_hub_connection
from styrened.tui.services.config import load_config
from styrened.tui.services.reticulum import discover_devices, get_reticulum_status
from styrened.tui.themes.semantic import SemanticSymbols
from styrened.tui.widgets.highlighted_panel import get_color_cascade


class ReticulumPanel(Static):
    """Panel displaying compact Reticulum/mesh status.

    Shows:
    - Mode (standalone/hub/peer)
    - Hub connection status
    - Reticulum network connectivity
    - Styrene mesh participation

    When offline due to errors, displays:
    - Error category (e.g., "Identity Corrupt", "Config Error")
    - Recovery guidance (e.g., "Delete ~/.styrene/operator.key to regenerate")
    """

    DEFAULT_CSS = """
    ReticulumPanel {
        height: auto;
        padding: 0 1;
    }
    """

    mode: reactive[str] = reactive("standalone")
    hub_status: reactive[HubStatus] = reactive(HubStatus.DISABLED)
    rns_online: reactive[bool] = reactive(False)
    styrene_mesh_count: reactive[int] = reactive(0)
    interface_count: reactive[int] = reactive(0)
    interface_status: reactive[str] = reactive("")
    error_state: reactive[RNSErrorState | None] = reactive(None)

    def render(self) -> str:
        """Render compact status display with semantic formatting.

        Uses cascade hex colors for Rich markup:
        - medium: primary values and active states
        - dim: muted/disabled states
        - bright: reserved for critical accents only

        Semantic symbols provide shape differentiation independent of color.
        """
        # Get current cascade dynamically for live theme switching
        cascade = get_color_cascade()
        lines = []

        # === STYRENE SECTION ===
        lines.append(f"[{cascade.bright}]STYRENE[/]")

        # Mode - use semantic symbol and cascade colors
        mode_display = self.mode.upper()
        if self.mode == "hub":
            lines.append(f"  MODE: {SemanticSymbols.ONLINE} [{cascade.medium}]{mode_display}[/]")
        elif self.mode == "peer":
            lines.append(f"  MODE: {SemanticSymbols.PENDING} [{cascade.medium}]{mode_display}[/]")
        else:
            lines.append(f"  MODE: {SemanticSymbols.IDLE} [{cascade.dim}]{mode_display}[/]")

        # Hub connection with semantic status
        if self.hub_status == HubStatus.CONNECTED:
            lines.append(f"  HUB: {SemanticSymbols.ONLINE} [{cascade.medium}]connected[/]")
        elif self.hub_status == HubStatus.WAITING:
            lines.append(f"  HUB: {SemanticSymbols.PENDING} [{cascade.medium}]waiting...[/]")
        elif self.hub_status == HubStatus.DISCONNECTED:
            lines.append(f"  HUB: {SemanticSymbols.OFFLINE} [{cascade.dim}]disconnected[/]")
        else:  # DISABLED
            lines.append(f"  HUB: {SemanticSymbols.OFFLINE} [{cascade.dim}]disabled[/]")

        # Styrene mesh participation
        if self.styrene_mesh_count > 0:
            lines.append(
                f"  MESH: {SemanticSymbols.ONLINE} [{cascade.medium}]{self.styrene_mesh_count} nodes[/]"
            )
        elif not self.rns_online and self.error_state and self.error_state.is_error:
            # Don't show mesh status when offline due to error
            pass
        else:
            lines.append(f"  MESH: {SemanticSymbols.OFFLINE} [{cascade.dim}]no nodes[/]")

        # === RETICULUM SECTION ===
        lines.append("")  # Blank line separator
        lines.append(f"[{cascade.bright}]RETICULUM[/]")

        # Reticulum network status with interface count
        if self.rns_online:
            lines.append(
                f"  RNS: {SemanticSymbols.ONLINE} [{cascade.medium}]online ({self.interface_count} if)[/]"
            )
        else:
            # Show error state if available
            if self.error_state and self.error_state.is_error:
                lines.append(
                    f"  RNS: {SemanticSymbols.REJECTED} [{cascade.bright}]{self.error_state.title}[/]"
                )
            else:
                lines.append(f"  RNS: {SemanticSymbols.OFFLINE} [{cascade.dim}]offline[/]")

        # Interface uplink status (only show if online)
        if self.rns_online:
            if self.interface_status:
                lines.append(f"  UPLINK: {self.interface_status}")
            else:
                lines.append(f"  UPLINK: {SemanticSymbols.OFFLINE} [{cascade.dim}]no interfaces[/]")
        elif self.error_state and self.error_state.is_error:
            # Show recovery guidance instead of uplink when there's an error
            recovery = self.error_state.recovery
            if recovery:
                # Truncate long recovery messages for the panel
                if len(recovery) > 50:
                    recovery = recovery[:47] + "..."
                lines.append(f"  [{cascade.medium}]{SemanticSymbols.PROCESSING} {recovery}[/]")

        return "\n".join(lines)

    def on_mount(self) -> None:
        """Load Reticulum data on mount."""
        self._load_reticulum_data()

    def _get_error_state(self) -> RNSErrorState | None:
        """Get the RNS error state from the app's lifecycle.

        Returns:
            RNSErrorState if available, None otherwise.
        """
        try:
            # Access the app's lifecycle manager
            app = self.app
            if hasattr(app, "_lifecycle"):
                error_state: RNSErrorState = app._lifecycle.rns_error_state
                return error_state
        except Exception:
            pass
        return None

    def _load_reticulum_data(self) -> None:
        """Load Reticulum status data from RNS service."""
        # Load config once for the entire method
        config = None
        try:
            config = load_config()
            self.mode = config.reticulum.mode.value
        except Exception:
            self.mode = "standalone"

        # Get RNS status
        status = get_reticulum_status()
        self.rns_online = bool(status.get("running", False))

        # Get error state from app's lifecycle if available
        self.error_state = self._get_error_state()

        # Get interface information from RNS.Transport
        if self.rns_online and hasattr(RNS.Transport, "interfaces"):
            try:
                interfaces = RNS.Transport.interfaces
                if interfaces:
                    self.interface_count = len(interfaces)
                    # Get interface types and online status - use theme colors
                    cascade = get_color_cascade()
                    interface_parts = []
                    for interface in interfaces:
                        iface_type = type(interface).__name__
                        iface_online = getattr(interface, "online", False)

                        # Shorten common names
                        if "LocalClient" in iface_type:
                            iface_type = "Local"
                        elif "AutoInterface" in iface_type:
                            iface_type = "Auto"
                        elif "TCPClient" in iface_type:
                            iface_type = "TCP"
                        elif "UDPInterface" in iface_type:
                            iface_type = "UDP"

                        # Color by status using cascade colors
                        if iface_online:
                            interface_parts.append(f"[{cascade.medium}]{iface_type}[/]")
                        else:
                            interface_parts.append(f"[{cascade.dim}]{iface_type}[/]")

                    self.interface_status = ", ".join(interface_parts)
                else:
                    self.interface_count = 0
                    self.interface_status = ""
            except Exception:
                self.interface_count = 0
                self.interface_status = ""
        else:
            self.interface_count = 0
            self.interface_status = ""

        # Get hub connection status - try to reconnect if not connected
        hub_connection = get_hub_connection()

        # Set hub's announce interval from config (reuse loaded config)
        try:
            if config is None:
                config = load_config()
            hub_connection.set_announce_interval(config.reticulum.hub_announce_interval)

            # Try to connect/reconnect if hub is configured but not connected
            if (
                config.reticulum.hub_enabled
                and config.reticulum.hub_address
                and not hub_connection.is_connected
            ):
                hub_connection.retry_connection()
        except Exception:
            pass

        # Get status-aware hub state
        self.hub_status = hub_connection.status

        # Get styrene mesh count from discovered devices
        devices = discover_devices()
        self.styrene_mesh_count = len([d for d in devices if d.is_styrene_node])

    def refresh_data(self) -> None:
        """Refresh Reticulum data."""
        self._load_reticulum_data()
