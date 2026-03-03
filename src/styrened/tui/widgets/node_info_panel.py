"""Node Info Panel - consolidated local node status.

Combines system hardware, Reticulum stack, and Styrene mesh configuration
into a single unified view of "this node" - the daemon behind the TUI.

Uses cascade colors for theme-aware rendering.
"""

import RNS  # type: ignore
from textual.reactive import reactive
from textual.widgets import Static

from styrened.models.mesh_device import DeviceType
from styrened.models.rns_error import RNSErrorState
from styrened.services.hub_connection import HubStatus, get_hub_connection
from styrened.tui.models.hardware import NetworkInterface, SystemInfo
from styrened.tui.services.config import load_config
from styrened.tui.services.hardware import (
    PlatformNotSupportedError,
    get_disks,
    get_network_interfaces,
    get_system_info,
)
from styrened.tui.services.reticulum import discover_devices, get_reticulum_status
from styrened.tui.themes.semantic import SemanticSymbols
from styrened.tui.widgets.highlighted_panel import get_color_cascade


class NodeInfoPanel(Static):
    """Consolidated panel showing local node configuration and status.

    Displays sections:
    - SYSTEM: Hardware configuration (CPU, RAM, network, storage)
    - DAEMON: IPC connection to backing daemon (only in IPC mode)
    - RETICULUM: Network stack and interface status
    - STYRENE: Mesh participation and hub connection
    """

    DEFAULT_CSS = """
    NodeInfoPanel {
        height: auto;
        padding: 0 1;
    }
    """

    # Hardware reactive vars
    system_info: reactive[SystemInfo | None] = reactive(None)
    primary_interface: reactive[NetworkInterface | None] = reactive(None)
    removable_count: reactive[int] = reactive(0)
    hardware_error: reactive[str | None] = reactive(None)

    # Styrene reactive vars
    mode: reactive[str] = reactive("standalone")
    hub_status: reactive[HubStatus] = reactive(HubStatus.DISABLED)
    styrene_mesh_count: reactive[int] = reactive(0)

    # Reticulum reactive vars
    rns_online: reactive[bool] = reactive(False)
    interface_count: reactive[int] = reactive(0)
    interface_status: reactive[str] = reactive("")
    error_state: reactive[RNSErrorState | None] = reactive(None)

    # Daemon reactive vars (IPC mode only - None means legacy/standalone mode)
    daemon_connected: reactive[bool | None] = reactive(None)
    daemon_version: reactive[str] = reactive("")
    daemon_uptime: reactive[float] = reactive(0.0)

    # Identity reactive vars
    identity_display_name: reactive[str] = reactive("")
    identity_icon: reactive[str] = reactive("")
    identity_short_name: reactive[str | None] = reactive(None)
    identity_hash: reactive[str] = reactive("")

    # Security tier (PQC session status)
    security_tier: reactive[str] = reactive("")

    # Comms reactive vars (populated from IPC or local DB)
    unread_count: reactive[int] = reactive(0)
    conversation_count: reactive[int] = reactive(0)
    contact_count: reactive[int] = reactive(0)
    messages_sent: reactive[int] = reactive(0)
    messages_received: reactive[int] = reactive(0)
    pending_deliveries: reactive[int] = reactive(0)
    auto_reply_enabled: reactive[bool] = reactive(False)
    propagation_enabled: reactive[bool] = reactive(False)
    transport_enabled: reactive[bool] = reactive(False)
    active_links: reactive[int] = reactive(0)

    # When True, skip local RNS/discovery queries (screen pushes daemon data)
    ipc_managed: reactive[bool] = reactive(False)

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """Format uptime seconds into human-readable string.

        Returns:
            Compact uptime like "45s", "12m", "2h 15m", "3d 4h".
        """
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        elif s < 3600:
            return f"{s // 60}m"
        elif s < 86400:
            h = s // 3600
            m = (s % 3600) // 60
            return f"{h}h {m}m" if m else f"{h}h"
        else:
            d = s // 86400
            h = (s % 86400) // 3600
            return f"{d}d {h}h" if h else f"{d}d"

    def _render_left_column(self, cascade: object) -> list[str]:
        """Render left column: SYSTEM, DAEMON, IDENTITY."""
        lines: list[str] = []

        # === SYSTEM ===
        lines.append(f"[{cascade.bright}]SYSTEM[/]")
        if self.hardware_error:
            lines.append(f"  [{cascade.dim}]unsupported platform[/]")
        else:
            if self.system_info:
                cpu = self.system_info.cpu_model
                if len(cpu) > 35:
                    cpu = cpu[:32] + "..."
                lines.append(f"  CPU: {cpu} ({self.system_info.cpu_cores}c, {self.system_info.ram_total_gb:.1f}GB)")
            else:
                lines.append(f"  CPU: [{cascade.dim}]detecting...[/]")

            if self.primary_interface:
                iface = self.primary_interface
                ip = iface.ip_address or f"[{cascade.dim}]no ip[/]"
                iface_type = iface.interface_type.value.upper()
                lines.append(f"  NET: {iface.name} ({iface_type}) [{cascade.medium}]{ip}[/]")
            else:
                lines.append(f"  NET: [{cascade.dim}]none[/]")

            if self.removable_count > 0:
                lines.append(f"  STORAGE: [{cascade.bright} bold]{self.removable_count} removable[/]")
            else:
                lines.append(f"  STORAGE: [{cascade.dim}]no removable[/]")

        # === DAEMON (IPC mode only) ===
        if self.daemon_connected is not None:
            lines.append("")
            lines.append(f"[{cascade.bright}]DAEMON[/]")
            if self.daemon_connected:
                lines.append(f"  IPC: {SemanticSymbols.ONLINE} [{cascade.medium}]connected[/]")
                if self.daemon_uptime > 0:
                    lines.append(f"  UP: {self._format_uptime(self.daemon_uptime)}")
            else:
                lines.append(f"  IPC: {SemanticSymbols.OFFLINE} [{cascade.dim}]disconnected[/]")

        # === IDENTITY ===
        if self.identity_display_name or self.identity_icon:
            lines.append("")
            lines.append(f"[{cascade.bright}]IDENTITY[/]")
            name_parts = []
            if self.identity_icon:
                name_parts.append(self.identity_icon)
            if self.identity_display_name:
                name_parts.append(self.identity_display_name)
            if name_parts:
                lines.append(f"  NAME: [{cascade.medium}]{' '.join(name_parts)}[/]")
            if self.identity_short_name:
                lines.append(f"  ALIAS: [{cascade.medium}]{self.identity_short_name}[/]")
            else:
                lines.append(f"  ALIAS: [{cascade.dim}]not set[/]")
            if self.identity_hash:
                lines.append(f"  HASH: [{cascade.dim}]{self.identity_hash[:16]}[/]")
            if self.security_tier:
                tier_color = cascade.bright if "PQC" in self.security_tier.upper() else cascade.medium
                lines.append(f"  SEC: [{tier_color}]{self.security_tier}[/]")

        # === COMMS ===
        lines.append("")
        lines.append(f"[{cascade.bright}]COMMS[/]")
        if self.unread_count > 0:
            lines.append(f"  INBOX: [{cascade.bright} bold]✉ {self.unread_count} unread[/]")
        else:
            lines.append(f"  INBOX: [{cascade.dim}]no unread[/]")
        if self.conversation_count > 0:
            lines.append(f"  CHATS: [{cascade.medium}]{self.conversation_count}[/]")
        else:
            lines.append(f"  CHATS: [{cascade.dim}]none[/]")
        if self.contact_count > 0:
            lines.append(f"  CONTACTS: [{cascade.medium}]{self.contact_count}[/]")
        else:
            lines.append(f"  CONTACTS: [{cascade.dim}]none[/]")
        if self.auto_reply_enabled:
            lines.append(f"  AUTO-REPLY: {SemanticSymbols.ONLINE} [{cascade.medium}]on[/]")

        return lines

    def _render_right_column(self, cascade: object) -> list[str]:
        """Render right column: RETICULUM, STYRENE, VERSION."""
        lines: list[str] = []

        # === RETICULUM ===
        lines.append(f"[{cascade.bright}]RETICULUM[/]")
        if self.rns_online:
            if self.interface_count > 0:
                lines.append(f"  RNS: {SemanticSymbols.ONLINE} [{cascade.medium}]online ({self.interface_count} if)[/]")
            else:
                lines.append(f"  RNS: {SemanticSymbols.PENDING} [{cascade.medium}]no peers[/]")
        else:
            if self.error_state and self.error_state.is_error:
                lines.append(f"  RNS: {SemanticSymbols.REJECTED} [{cascade.bright}]{self.error_state.title}[/]")
            else:
                lines.append(f"  RNS: {SemanticSymbols.OFFLINE} [{cascade.dim}]offline[/]")

        if self.rns_online:
            if self.interface_status:
                lines.append(f"  UPLINK: {self.interface_status}")
            elif self.interface_count == 0:
                lines.append(f"  UPLINK: {SemanticSymbols.OFFLINE} [{cascade.dim}]no interfaces[/]")
        elif self.error_state and self.error_state.is_error:
            recovery = self.error_state.recovery
            if recovery:
                if len(recovery) > 40:
                    recovery = recovery[:37] + "..."
                lines.append(f"  [{cascade.medium}]{SemanticSymbols.PROCESSING} {recovery}[/]")

        # === STYRENE ===
        lines.append("")
        lines.append(f"[{cascade.bright}]STYRENE[/]")

        mode_display = self.mode.upper()
        if self.mode == "hub":
            lines.append(f"  MODE: {SemanticSymbols.ONLINE} [{cascade.medium}]{mode_display}[/]")
        elif self.mode == "peer":
            lines.append(f"  MODE: {SemanticSymbols.PENDING} [{cascade.medium}]{mode_display}[/]")
        else:
            lines.append(f"  MODE: {SemanticSymbols.IDLE} [{cascade.dim}]{mode_display}[/]")

        if self.hub_status == HubStatus.CONNECTED:
            lines.append(f"  HUB: {SemanticSymbols.ONLINE} [{cascade.medium}]connected[/]")
        elif self.hub_status == HubStatus.WAITING:
            lines.append(f"  HUB: {SemanticSymbols.PENDING} [{cascade.medium}]waiting...[/]")
        elif self.hub_status == HubStatus.DISCONNECTED:
            lines.append(f"  HUB: {SemanticSymbols.OFFLINE} [{cascade.dim}]disconnected[/]")
        else:
            lines.append(f"  HUB: {SemanticSymbols.OFFLINE} [{cascade.dim}]disabled[/]")

        if self.styrene_mesh_count > 0:
            lines.append(f"  MESH: {SemanticSymbols.ONLINE} [{cascade.medium}]{self.styrene_mesh_count} peers[/]")
        elif not self.rns_online and self.error_state and self.error_state.is_error:
            pass
        else:
            lines.append(f"  MESH: {SemanticSymbols.OFFLINE} [{cascade.dim}]no peers[/]")

        # === TRAFFIC ===
        lines.append("")
        lines.append(f"[{cascade.bright}]TRAFFIC[/]")
        traffic_parts = []
        if self.messages_sent > 0:
            traffic_parts.append(f"↑{self.messages_sent}")
        if self.messages_received > 0:
            traffic_parts.append(f"↓{self.messages_received}")
        if traffic_parts:
            lines.append(f"  MSG: [{cascade.medium}]{' '.join(traffic_parts)}[/]")
        else:
            lines.append(f"  MSG: [{cascade.dim}]no traffic[/]")
        if self.pending_deliveries > 0:
            lines.append(f"  PENDING: [{cascade.bright}]{self.pending_deliveries}[/]")
        if self.active_links > 0:
            lines.append(f"  LINKS: [{cascade.medium}]{self.active_links} active[/]")
        role_parts = []
        if self.transport_enabled:
            role_parts.append("transport")
        if self.propagation_enabled:
            role_parts.append("propagation")
        if role_parts:
            lines.append(f"  ROLE: [{cascade.medium}]{', '.join(role_parts)}[/]")

        # === VERSION ===
        lines.append("")
        try:
            from styrened import __version__
            version = self.daemon_version if self.daemon_version else __version__
            lines.append(f"[{cascade.bright}]VERSION[/]")
            lines.append(f"  [{cascade.medium}]styrened {version}[/]")
        except ImportError:
            pass

        return lines

    def render(self) -> str:
        """Render two-column node info display.

        Left column: SYSTEM, DAEMON, IDENTITY
        Right column: RETICULUM, STYRENE, VERSION

        Uses Rich Columns for side-by-side layout within a single Static.
        Falls back to single-column if terminal is narrow.
        """
        cascade = get_color_cascade()
        left = self._render_left_column(cascade)
        right = self._render_right_column(cascade)

        # Pad shorter column to match heights
        max_lines = max(len(left), len(right))
        while len(left) < max_lines:
            left.append("")
        while len(right) < max_lines:
            right.append("")

        # Build side-by-side: use a fixed column width for the left side
        # Rich markup makes exact character counting unreliable, so we
        # use a generous fixed width and let the right column fill remaining space
        col_width = 44
        output_lines = []
        for l_line, r_line in zip(left, right):
            # Pad left line to fixed width (plain-text approximation)
            # Rich tags don't count toward visible width, so we strip them for padding
            import re
            visible_len = len(re.sub(r"\[.*?\]", "", l_line))
            pad = max(0, col_width - visible_len)
            output_lines.append(f"{l_line}{' ' * pad}{r_line}")

        return "\n".join(output_lines)

    def on_mount(self) -> None:
        """Load all node data on mount."""
        self._load_all_data()

    def _load_all_data(self) -> None:
        """Load hardware, Styrene, Reticulum, and comms data."""
        self._load_hardware_data()
        self._load_styrene_data()
        self._load_reticulum_data()
        if not self.ipc_managed:
            self._load_comms_data()

    def _load_hardware_data(self) -> None:
        """Load system hardware information."""
        try:
            self.system_info = get_system_info()
        except PlatformNotSupportedError as e:
            self.hardware_error = str(e)
            return

        # Network interfaces
        try:
            interfaces = get_network_interfaces()
            hardware_ifaces = [i for i in interfaces if i.is_hardware and i.is_up and i.ip_address]
            self.primary_interface = hardware_ifaces[0] if hardware_ifaces else None
        except PlatformNotSupportedError:
            self.primary_interface = None

        # Storage
        try:
            disks = get_disks()
            self.removable_count = len([d for d in disks if d.is_removable])
        except PlatformNotSupportedError:
            self.removable_count = 0

    def _load_styrene_data(self) -> None:
        """Load Styrene mesh and hub configuration."""
        # Get config for mode and identity (always relevant, even in IPC mode)
        config = None
        try:
            config = load_config()
            self.mode = config.reticulum.mode.value

            # Load identity appearance from config (always — identity is local config, not daemon state)
            if hasattr(config, "identity"):
                self.identity_display_name = config.identity.display_name
                self.identity_icon = config.identity.icon
                self.identity_short_name = config.identity.short_name
        except Exception:
            self.mode = "standalone"

        # Load operator identity hash and security tier (works in both modes)
        if not self.identity_hash:
            try:
                from styrened.services.reticulum import get_operator_identity
                op_hash = get_operator_identity()
                if op_hash:
                    self.identity_hash = op_hash
                    # Security tier reflects identity provider
                    provider = "file"
                    if config and hasattr(config, "identity"):
                        provider = getattr(config.identity, "provider", "file")
                    if provider == "yubikey":
                        self.security_tier = "YubiKey/FIDO2"
                    else:
                        self.security_tier = "X25519"
            except Exception:
                pass

        # In IPC mode, dashboard pushes mesh count and hub status from daemon
        if self.ipc_managed:
            return

        # Get hub connection status
        hub_connection = get_hub_connection()
        try:
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

        self.hub_status = hub_connection.status

        # Get Styrene mesh device count from discovery
        devices = discover_devices()

        # Count only Styrene nodes (other device types shown in Exploration screen)
        self.styrene_mesh_count = len(
            [d for d in devices if d.device_type == DeviceType.STYRENE_NODE]
        )

    def _load_reticulum_data(self) -> None:
        """Load Reticulum stack status."""
        # In IPC mode, dashboard pushes RNS status from daemon
        if self.ipc_managed:
            return

        # Get RNS status
        status = get_reticulum_status()
        self.rns_online = bool(status.get("running", False))

        # Get error state from app's lifecycle if available
        self.error_state = self._get_error_state()

        # Get interface information
        if self.rns_online and hasattr(RNS.Transport, "interfaces"):
            try:
                interfaces = RNS.Transport.interfaces
                if interfaces:
                    self.interface_count = len(interfaces)
                    # Get interface types and online status
                    interface_parts = []
                    for interface in interfaces:
                        iface_type = type(interface).__name__

                        # Shorten common names
                        if "LocalClient" in iface_type:
                            iface_type = "Local"
                        elif "AutoInterface" in iface_type:
                            iface_type = "Auto"
                        elif "TCPClient" in iface_type:
                            iface_type = "TCP"
                        elif "UDPInterface" in iface_type:
                            iface_type = "UDP"

                        # Color by status
                        cascade = get_color_cascade()
                        iface_online = getattr(interface, "online", False)
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

    def _load_comms_data(self) -> None:
        """Load local comms data from the message database (non-IPC mode).

        Uses SQL aggregates instead of loading all rows to avoid blocking
        the main thread on large message databases.
        """
        try:
            app = self.app
            if not hasattr(app, "db_engine") or app.db_engine is None:
                return

            from sqlalchemy import func, case, literal_column
            from sqlalchemy.orm import Session as SASession
            from styrened.models.messages import Message

            local_hash = getattr(app, "local_identity_hash", None)

            with SASession(app.db_engine) as session:
                base = session.query(Message).filter(Message.protocol_id == "chat")

                # Aggregate counts in one query
                if local_hash is not None:
                    row = base.with_entities(
                        func.count().label("total"),
                        func.count(case(
                            (Message.source_hash == local_hash, literal_column("1")),
                        )).label("sent"),
                        func.count(case(
                            (Message.source_hash != local_hash, literal_column("1")),
                        )).label("received"),
                        func.count(case(
                            ((Message.status == "pending") & (Message.destination_hash == local_hash), literal_column("1")),
                        )).label("unread"),
                        func.count(case(
                            (Message.status.in_(["queued", "sending"]), literal_column("1")),
                        )).label("pending_count"),
                    ).one()

                    self.messages_sent = row.sent
                    self.messages_received = row.received
                    self.unread_count = row.unread
                    self.pending_deliveries = row.pending_count

                    # Distinct peer hashes (conversation count)
                    peer_hash_expr = case(
                        (Message.source_hash != local_hash, Message.source_hash),
                        else_=Message.destination_hash,
                    )
                    conv_count = base.with_entities(
                        func.count(func.distinct(peer_hash_expr))
                    ).scalar() or 0
                    self.conversation_count = conv_count
                else:
                    # No local_hash — count distinct hashes from both columns
                    row = base.with_entities(func.count()).one()
                    self.messages_received = row[0]
                    self.messages_sent = 0

                    # Approximate conversation count
                    src_count = base.with_entities(
                        func.count(func.distinct(Message.source_hash))
                    ).scalar() or 0
                    dst_count = base.with_entities(
                        func.count(func.distinct(Message.destination_hash))
                    ).scalar() or 0
                    self.conversation_count = max(src_count, dst_count)
        except Exception:
            pass

        # Contact count from node store
        try:
            from styrened.services.node_store import get_node_store
            nodes = get_node_store().get_all_nodes()
            self.contact_count = len(nodes) if nodes else 0
        except Exception:
            pass

        # Auto-reply status from config
        try:
            config = load_config()
            if hasattr(config, "auto_reply"):
                self.auto_reply_enabled = getattr(config.auto_reply, "enabled", False)
        except Exception:
            pass

    def _get_error_state(self) -> RNSErrorState | None:
        """Get the RNS error state from the app's lifecycle.

        Returns:
            RNSErrorState if available, None otherwise.
        """
        try:
            app = self.app
            if hasattr(app, "_lifecycle"):
                error_state: RNSErrorState = app._lifecycle.rns_error_state
                return error_state
        except Exception:
            pass
        return None

    def refresh_data(self) -> None:
        """Refresh all node data."""
        self._load_all_data()
