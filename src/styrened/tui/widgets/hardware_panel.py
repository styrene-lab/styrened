"""Hardware Panel widget for displaying system hardware information.

Displays compact system info in minimal space.
Uses cascade colors for theme-aware rendering.
"""
from __future__ import annotations

from textual.reactive import reactive
from textual.widgets import Static

from styrened.tui.models.hardware import (
    NetworkInterface,
    SystemInfo,
)
from styrened.tui.services.hardware import (
    PlatformNotSupportedError,
    get_disks,
    get_network_interfaces,
    get_system_info,
)
from styrened.tui.widgets.highlighted_panel import get_color_cascade


class HardwarePanel(Static):
    """Panel displaying compact hardware information.

    Shows only essential info: CPU, RAM, primary network interface.
    """

    DEFAULT_CSS = """
    HardwarePanel {
        height: auto;
        padding: 0 1;
    }
    """

    system_info: reactive[SystemInfo | None] = reactive(None)
    primary_interface: reactive[NetworkInterface | None] = reactive(None)
    removable_count: reactive[int] = reactive(0)
    error_message: reactive[str | None] = reactive(None)

    def render(self) -> str:
        """Render compact hardware display.

        Uses cascade hex colors for theme-aware Rich markup.
        """
        cascade = get_color_cascade()

        if self.error_message:
            return f"[{cascade.dim}]Hardware detection not supported on this platform[/]"

        lines = []

        # System info (CPU/RAM) - single line
        if self.system_info:
            cpu = self.system_info.cpu_model
            # Shorten CPU name if too long
            if len(cpu) > 40:
                cpu = cpu[:37] + "..."
            cores = self.system_info.cpu_cores
            ram_gb = self.system_info.ram_total_gb
            lines.append(f"SYSTEM: {cpu} ({cores}c, {ram_gb:.1f}GB)")
        else:
            lines.append(f"SYSTEM: [{cascade.dim}]detecting...[/]")

        # Network - show primary interface only
        if self.primary_interface:
            iface = self.primary_interface
            ip = iface.ip_address or f"[{cascade.dim}]no ip[/]"
            iface_type = iface.interface_type.value.upper()
            if iface.is_up:
                lines.append(f"NETWORK: {iface.name} ({iface_type}) [{cascade.medium}]{ip}[/]")
            else:
                lines.append(f"NETWORK: {iface.name} ({iface_type}) [{cascade.dim}]{ip}[/]")
        else:
            lines.append(f"NETWORK: [{cascade.dim}]none[/]")

        # Storage - show only removable count (for provisioning)
        if self.removable_count > 0:
            lines.append(
                f"STORAGE: [{cascade.bright} bold]{self.removable_count} removable device(s)[/]"
            )
        else:
            lines.append(f"STORAGE: [{cascade.dim}]no removable devices[/]")

        return "\n".join(lines)

    def on_mount(self) -> None:
        """Load hardware data on mount."""
        self._load_hardware_data()

    def _load_hardware_data(self) -> None:
        """Load hardware data from services."""
        # Load system info
        try:
            system_info = get_system_info()
            self.system_info = system_info
        except PlatformNotSupportedError as e:
            self.error_message = str(e)
            return

        # Load network interfaces - find primary
        try:
            interfaces = get_network_interfaces()
            # Find first up hardware interface with an IP
            hardware_ifaces = [i for i in interfaces if i.is_hardware and i.is_up and i.ip_address]
            self.primary_interface = hardware_ifaces[0] if hardware_ifaces else None
        except PlatformNotSupportedError:
            self.primary_interface = None

        # Load disk info - count removables
        try:
            disks = get_disks()
            self.removable_count = len([d for d in disks if d.is_removable])
        except PlatformNotSupportedError:
            self.removable_count = 0

    def refresh_data(self) -> None:
        """Refresh hardware data."""
        self._load_hardware_data()
