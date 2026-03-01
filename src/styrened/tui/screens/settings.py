"""Settings screen for configuration management."""

from pathlib import Path
from typing import Any, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select, Static, Switch, TabbedContent, TabPane

from styrened.models.config import DeploymentMode, PeerConfig, validate_short_name
from styrened.tui.models.config import (
    ConfigValidationError,
    GatewayMode,
    LogLevel,
    StyreneConfig,
)
from styrened.tui.services.config import save_config, validate_config

# Announce interval presets: (label, seconds)
ANNOUNCE_INTERVALS: list[tuple[str, int]] = [
    ("15s", 15),
    ("30s", 30),
    ("45s", 45),
    ("1m", 60),
    ("2m", 120),
    ("5m", 300),
    ("10m", 600),
    ("15m", 900),
    ("30m", 1800),
    ("1h", 3600),
    ("2h", 7200),
    ("4h", 14400),
    ("8h", 28800),
    ("1d", 86400),
]
from styrened.tui.widgets.highlighted_panel import HighlightedPanel


class SettingsScreen(Screen[None]):
    """Settings screen for editing TUI configuration.

    Provides forms for editing:
    - TUI settings (theme, log level, confirmations)
    - Fleet settings (edge-fleet path, inventory, auto-sync)
    - Provisioning defaults (SSH keys, hostname prefix)
    - Mesh defaults (mesh_id, channel, gateway_mode)
    - Reticulum settings (config path override, hub settings)
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
        Binding("left_square_bracket", "previous_tab", "Previous Tab", show=False),
        Binding("right_square_bracket", "next_tab", "Next Tab", show=False),
    ]

    def __init__(self, config: StyreneConfig) -> None:
        """Initialize settings screen.

        Args:
            config: Current configuration to edit.
        """
        super().__init__()
        self.config = config
        self._status_message = ""

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
        except Exception:
            return None

    async def _save_identity(
        self, display_name: str, icon: str, short_name: str
    ) -> None:
        """Persist identity fields to core config and optionally notify daemon.

        Always writes to core-config.yaml directly (identity is a local
        setting). Additionally notifies the daemon via IPC if connected,
        so it can re-announce with the new identity.
        """
        # Always persist to core config (source of truth for identity)
        try:
            from styrened.services.config import load_core_config, save_core_config

            core_cfg = load_core_config()
            if display_name is not None:
                core_cfg.identity.display_name = display_name
            if icon is not None:
                core_cfg.identity.icon = icon
            core_cfg.identity.short_name = (
                short_name if short_name else None
            )
            save_core_config(core_cfg)
        except Exception as e:
            self._show_error(f"Failed to save identity: {e}")
            return

        # If IPC is active, also notify the daemon so it re-announces
        bridge = self._ipc_bridge
        if bridge is not None:
            try:
                await bridge.set_identity(
                    display_name=display_name,
                    icon=icon,
                    short_name=short_name if short_name else "",
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug(
                    "Failed to notify daemon of identity change via IPC: %s", e
                )

    def compose(self) -> ComposeResult:
        """Compose the settings screen layout."""
        with Vertical(id="settings-outer"):
            with TabbedContent(id="settings-tabs"):
                # ── Tab 1: Identity ──────────────────────────────────────
                with TabPane("Identity", id="tab-identity"):
                    with VerticalScroll(classes="settings-tab-scroll"):
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Display Name:", classes="setting-label"),
                                Input(
                                    value=self.config.identity.display_name,
                                    placeholder="Anonymous Styrene",
                                    id="identity_display_name",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Icon:", classes="setting-label"),
                                Input(
                                    value=self.config.identity.icon,
                                    placeholder="🔗",
                                    id="identity_icon",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Short Name:", classes="setting-label"),
                                Input(
                                    value=self.config.identity.short_name or "",
                                    placeholder="alice (3-20 chars, lowercase)",
                                    id="identity_short_name",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "Controls how this node appears in mesh announces. "
                                "Other LXMF clients (Sideband, NomadNet) will see these values.",
                                classes="setting-description",
                            ),
                            title="OPERATOR IDENTITY",
                        )

                # ── Tab 2: Network ───────────────────────────────────────
                with TabPane("Network", id="tab-network"):
                    with VerticalScroll(classes="settings-tab-scroll"):
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Mode:", classes="setting-label"),
                                Select(
                                    [(m.value.title(), m) for m in DeploymentMode],
                                    value=self.config.reticulum.mode,
                                    id="deployment_mode",
                                    classes="setting-select",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Enable Transport:", classes="setting-label"),
                                Switch(
                                    value=self.config.reticulum.resolve_transport_enabled(),
                                    id="enable_transport",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Announce Interval:", classes="setting-label"),
                                Select(
                                    [(label, secs) for label, secs in ANNOUNCE_INTERVALS],
                                    value=self._match_announce_interval(
                                        self.config.reticulum.announce_interval
                                    ),
                                    id="announce_interval",
                                    classes="setting-select",
                                    allow_blank=False,
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "Standalone: own transport, no shared instance. "
                                "Hub: transport node accepting connections. "
                                "Peer: connects to shared RNS instance.",
                                classes="setting-description",
                            ),
                            title="TRANSPORT",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Static("", classes="peer-status-col"),
                                Static("[b]Name[/b]", classes="peer-name-input peer-header"),
                                Static("[b]Host[/b]", classes="peer-host-input peer-header"),
                                Static("[b]Port[/b]", classes="peer-port-input peer-header"),
                                Static("", classes="peer-remove-btn"),
                                classes="peer-header-row",
                            ),
                            *self._compose_peer_rows(),
                            Horizontal(
                                Button(
                                    "+ Add Peer",
                                    id="btn-add-peer",
                                    classes="setting-btn",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "TCP connections to remote Reticulum nodes. "
                                "Each peer becomes a TCPClientInterface in ~/.reticulum/config. "
                                "Changes take effect on save (daemon restart required).",
                                classes="setting-description",
                            ),
                            title="PEERS",
                            id="peers-panel",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Label("AutoInterface:", classes="setting-label"),
                                Switch(
                                    value=self.config.reticulum.interfaces.auto,
                                    id="auto_interface",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "UDP multicast discovery on local network. "
                                "Disabled by default — can cause errors on VPN/tunnel interfaces. "
                                "Enable only if your network adapters are stable.",
                                classes="setting-description",
                            ),
                            title="LOCAL DISCOVERY",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Server Interface:", classes="setting-label"),
                                Switch(
                                    value=self.config.reticulum.interfaces.server.enabled,
                                    id="server_enabled",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Listen IP:", classes="setting-label"),
                                Input(
                                    value=self.config.reticulum.interfaces.server.listen_ip,
                                    placeholder="0.0.0.0",
                                    id="server_listen_ip",
                                    classes="setting-input-narrow",
                                ),
                                classes="setting-row",
                                id="server-ip-row",
                            ),
                            Horizontal(
                                Label("Listen Port:", classes="setting-label"),
                                Input(
                                    value=str(self.config.reticulum.interfaces.server.port),
                                    placeholder="4242",
                                    id="server_port",
                                    classes="setting-input-narrow",
                                ),
                                classes="setting-row",
                                id="server-port-row",
                            ),
                            Static(
                                "Accept incoming TCP connections from other nodes. "
                                "Required for Hub mode. Creates a TCPServerInterface.",
                                classes="setting-description",
                            ),
                            title="SERVER",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Enable Mesh:", classes="setting-label"),
                                Switch(
                                    value=self.config.mesh.enable,
                                    id="mesh_enable",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Mesh ID:", classes="setting-label"),
                                Input(
                                    value=self.config.mesh.mesh_id,
                                    placeholder="styrene",
                                    id="mesh_id",
                                    classes="setting-input-narrow",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Channel:", classes="setting-label"),
                                Input(
                                    value=str(self.config.mesh.channel),
                                    placeholder="6",
                                    id="channel",
                                    classes="setting-input-narrow",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Gateway Mode:", classes="setting-label"),
                                Select(
                                    [(mode.value, mode) for mode in GatewayMode],
                                    value=self.config.mesh.gateway_mode,
                                    id="gateway_mode",
                                    classes="setting-select",
                                ),
                                classes="setting-row",
                            ),
                            title="BATMAN-ADV MESH",
                        )

                # ── Tab 3: Fleet ─────────────────────────────────────────
                with TabPane("Fleet", id="tab-fleet"):
                    with VerticalScroll(classes="settings-tab-scroll"):
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Edge Fleet Path:", classes="setting-label"),
                                Input(
                                    value=str(self.config.fleet.edge_fleet_path or ""),
                                    placeholder="/path/to/edge-fleet",
                                    id="edge_fleet_path",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Inventory File:", classes="setting-label"),
                                Input(
                                    value=self.config.fleet.inventory_file,
                                    placeholder="inventory/devices.yaml",
                                    id="inventory_file",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Auto Sync Inventory:", classes="setting-label"),
                                Switch(
                                    value=self.config.fleet.auto_sync_inventory,
                                    id="auto_sync_inventory",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            title="FLEET",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Hostname Prefix:", classes="setting-label"),
                                Input(
                                    value=self.config.provisioning.default_hostname_prefix,
                                    placeholder="node",
                                    id="default_hostname_prefix",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("SSH Key Paths:", classes="setting-label"),
                                Input(
                                    value=", ".join(
                                        str(p)
                                        for p in self.config.provisioning.ssh_key_paths
                                    ),
                                    placeholder="~/.ssh/id_ed25519.pub, ~/.ssh/id_rsa.pub",
                                    id="ssh_key_paths",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            title="PROVISIONING DEFAULTS",
                        )

                # ── Tab 4: System ────────────────────────────────────────
                with TabPane("System", id="tab-system"):
                    with VerticalScroll(classes="settings-tab-scroll"):
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Log Level:", classes="setting-label"),
                                Select(
                                    [(level.value, level) for level in LogLevel],
                                    value=self.config.tui.log_level,
                                    id="log_level",
                                    classes="setting-select",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Show Hardware Panel:", classes="setting-label"),
                                Switch(
                                    value=self.config.tui.show_hardware_panel,
                                    id="show_hardware_panel",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Confirm Destructive:", classes="setting-label"),
                                Switch(
                                    value=self.config.tui.confirm_destructive,
                                    id="confirm_destructive",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            title="TUI",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Button("Restart Daemon", id="btn-restart-daemon", classes="setting-btn"),
                                Button("Install as Service", id="btn-install-service", classes="setting-btn"),
                                Button(
                                    "Reset to Defaults",
                                    variant="warning",
                                    id="btn-reset-config",
                                    classes="setting-btn",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "Restart applies after upgrades. "
                                "Install as Service creates a launchd/systemd unit for boot persistence. "
                                "Reset regenerates all config files from defaults and restarts the daemon.",
                                classes="setting-description",
                            ),
                            title="DAEMON",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Clear Node History:", classes="setting-label"),
                                Button(
                                    "Clear All Nodes",
                                    variant="warning",
                                    id="clear-nodes-btn",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "Removes all discovered nodes from persistent storage. "
                                "New announces will repopulate the list.",
                                classes="setting-description",
                            ),
                            title="DATA",
                        )

            # Action bar — outside tabs, always visible
            with Horizontal(id="settings-actions"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

            yield Static("", id="status-message")

    @staticmethod
    def _match_announce_interval(seconds: int) -> int:
        """Find the closest matching preset for an announce interval value."""
        for _label, secs in ANNOUNCE_INTERVALS:
            if secs == seconds:
                return secs
        # Find closest preset
        closest = min(ANNOUNCE_INTERVALS, key=lambda x: abs(x[1] - seconds))
        return closest[1]

    def _compose_peer_rows(self) -> list:
        """Generate peer input rows from current config."""
        rows = []
        for i, peer in enumerate(self.config.reticulum.interfaces.peers):
            rows.append(
                Horizontal(
                    Static("●", classes="peer-status-col peer-status-unknown"),
                    Input(
                        value=peer.name or "",
                        placeholder="Name (optional)",
                        id=f"peer_name_{i}",
                        classes="peer-name-input",
                    ),
                    Input(
                        value=peer.host,
                        placeholder="host or IP",
                        id=f"peer_host_{i}",
                        classes="peer-host-input",
                    ),
                    Input(
                        value=str(peer.port),
                        placeholder="4242",
                        id=f"peer_port_{i}",
                        classes="peer-port-input",
                    ),
                    Button(
                        "✕",
                        id=f"btn-remove-peer-{i}",
                        classes="peer-remove-btn",
                        variant="error",
                    ),
                    classes="peer-row",
                    id=f"peer-row-{i}",
                )
            )
        return rows

    def _peer_count(self) -> int:
        """Count current peer rows in the DOM."""
        return len(list(self.query(".peer-row")))

    def on_mount(self) -> None:
        """Set initial visibility of server fields."""
        self._update_server_visibility()

    def action_save(self) -> None:
        """Save configuration."""
        self.run_worker(self._save_settings())

    def action_cancel(self) -> None:
        """Cancel and return to previous screen."""
        self.dismiss()

    def action_previous_tab(self) -> None:
        """Switch to the previous settings tab."""
        self.query_one("#settings-tabs", TabbedContent).action_previous_tab()

    def action_next_tab(self) -> None:
        """Switch to the next settings tab."""
        self.query_one("#settings-tabs", TabbedContent).action_next_tab()

    @on(Button.Pressed, "#btn-restart-daemon")
    def on_restart_daemon(self) -> None:
        """Trigger daemon restart via app action."""
        self.app.action_restart_daemon()

    @on(Button.Pressed, "#btn-install-service")
    def on_install_service_from_settings(self) -> None:
        """Open daemon setup screen for service installation."""
        from styrened.tui.screens.daemon_setup import DaemonSetupScreen
        self.app.push_screen(DaemonSetupScreen())

    @on(Button.Pressed, "#btn-reset-config")
    def on_reset_config(self) -> None:
        """Reset all config files to defaults and restart daemon."""
        self.run_worker(self._reset_config())

    async def _reset_config(self) -> None:
        """Regenerate config files from defaults and restart the daemon."""
        import shutil

        from styrened import paths
        from styrened.services.config import get_default_core_config, save_core_config
        from styrened.services.reticulum import generate_rns_config

        try:
            # Back up existing configs
            config_file = paths.config_file()
            if config_file.exists():
                shutil.copy2(config_file, config_file.with_suffix(".yaml.bak"))

            rns_config = Path.home() / ".reticulum" / "config"
            if rns_config.exists():
                shutil.copy2(rns_config, rns_config.with_suffix(".bak"))

            # Regenerate styrene config from defaults
            default_config = get_default_core_config()
            save_core_config(default_config)

            # Regenerate RNS config from default core config
            rns_content = generate_rns_config(default_config)
            rns_config.parent.mkdir(parents=True, exist_ok=True)
            rns_config.write_text(rns_content)

            self.notify(
                "Config reset to defaults (backups saved as .bak)",
                severity="information",
                timeout=5,
            )

            # Restart daemon to pick up new config
            self.app.action_restart_daemon()

        except Exception as e:
            self.notify(f"Reset failed: {e}", severity="error", timeout=10)

    @on(Button.Pressed, "#btn-add-peer")
    def on_add_peer(self) -> None:
        """Add a new peer row to the peers panel."""
        idx = self._peer_count()
        new_row = Horizontal(
            Static("●", classes="peer-status-col peer-status-new"),
            Input(
                value="",
                placeholder="Name (optional)",
                id=f"peer_name_{idx}",
                classes="peer-name-input",
            ),
            Input(
                value="",
                placeholder="host or IP",
                id=f"peer_host_{idx}",
                classes="peer-host-input",
            ),
            Input(
                value="4242",
                placeholder="4242",
                id=f"peer_port_{idx}",
                classes="peer-port-input",
            ),
            Button(
                "✕",
                id=f"btn-remove-peer-{idx}",
                classes="peer-remove-btn",
                variant="error",
            ),
            classes="peer-row",
            id=f"peer-row-{idx}",
        )
        # Mount inside the peers panel content area, before the Add Peer button row
        try:
            add_btn = self.query_one("#btn-add-peer")
            add_btn_row = add_btn.parent
            if add_btn_row and add_btn_row.parent:
                add_btn_row.parent.mount(new_row, before=add_btn_row)
            else:
                self.query_one("#peers-panel").mount(new_row)
        except Exception:
            pass

    @on(Button.Pressed, ".peer-remove-btn")
    def on_remove_peer(self, event: Button.Pressed) -> None:
        """Remove a peer row."""
        # Walk up to the peer-row container and remove it
        widget = event.button.parent
        if widget and "peer-row" in widget.classes:
            widget.remove()

    @on(Switch.Changed, "#server_enabled")
    def on_server_toggle(self, event: Switch.Changed) -> None:
        """Show/hide server IP and port fields."""
        self._update_server_visibility()

    def _update_server_visibility(self) -> None:
        """Show or hide server config fields based on server enabled checkbox."""
        try:
            enabled = self.query_one("#server_enabled", Switch).value
            for row_id in ("#server-ip-row", "#server-port-row"):
                row = self.query_one(row_id)
                if enabled:
                    row.remove_class("hidden")
                else:
                    row.add_class("hidden")
        except Exception:
            pass

    @on(Button.Pressed, "#save-btn")
    def on_save_button(self) -> None:
        """Handle save button press."""
        self.run_worker(self._save_settings())

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_button(self) -> None:
        """Handle cancel button press."""
        self.dismiss()

    @on(Button.Pressed, "#clear-nodes-btn")
    def on_clear_nodes_button(self) -> None:
        """Handle clear node history button press."""
        try:
            from styrened.services.node_store import get_node_store

            node_store = get_node_store()

            # Get count before clearing
            node_count = len(node_store.get_all_nodes())

            if node_count == 0:
                self._show_error("Node history is already empty")
                return

            # Clear the node store database
            cleared_count = node_store.clear_all_nodes()

            self._show_success(f"Cleared {cleared_count} node(s) from history")
            self.app.log.info(f"Cleared {cleared_count} nodes from persistent storage")

        except Exception as e:
            self._show_error(f"Failed to clear node history: {e}")
            self.app.log.error(f"Error clearing node history: {e}")

    async def _save_settings(self) -> None:
        """Read form values, validate, and save configuration."""
        try:
            # Read Operator Identity settings
            identity_display_name = self.query_one(
                "#identity_display_name", Input
            ).value.strip()
            identity_icon = self.query_one("#identity_icon", Input).value.strip()
            identity_short_name = self.query_one(
                "#identity_short_name", Input
            ).value.strip()

            if identity_display_name and len(identity_display_name) > 100:
                self._show_error("Display name exceeds 100 characters")
                return

            if identity_icon and len(identity_icon) > 4:
                self._show_error("Icon must be 4 characters or fewer")
                return

            if identity_short_name and not validate_short_name(identity_short_name):
                self._show_error(
                    "Invalid short name: 3-20 chars, lowercase alphanumeric + hyphens"
                )
                return

            # Persist identity via IPC (daemon mode) or core config (local mode).
            # Identity lives in core-config.yaml, not the TUI config, so
            # save_config() alone won't persist it.  Must be awaited so the
            # IPC roundtrip completes before the screen dismisses.
            await self._save_identity(
                identity_display_name, identity_icon, identity_short_name
            )

            # Read TUI settings
            log_level_select = self.query_one("#log_level", Select)
            show_hardware = self.query_one("#show_hardware_panel", Switch)
            confirm_destructive = self.query_one("#confirm_destructive", Switch)

            if not isinstance(log_level_select.value, LogLevel):
                self._show_error("Invalid log level selection")
                return
            self.config.tui.log_level = log_level_select.value
            self.config.tui.show_hardware_panel = show_hardware.value
            self.config.tui.confirm_destructive = confirm_destructive.value

            # Read Fleet settings
            edge_fleet_path = self.query_one("#edge_fleet_path", Input).value.strip()
            self.config.fleet.edge_fleet_path = (
                Path(edge_fleet_path).expanduser() if edge_fleet_path else None
            )
            self.config.fleet.inventory_file = self.query_one(
                "#inventory_file", Input
            ).value.strip()
            self.config.fleet.auto_sync_inventory = self.query_one(
                "#auto_sync_inventory", Switch
            ).value

            # Read Provisioning defaults
            self.config.provisioning.default_hostname_prefix = self.query_one(
                "#default_hostname_prefix", Input
            ).value.strip()

            # Parse SSH key paths (comma-separated)
            ssh_keys_str = self.query_one("#ssh_key_paths", Input).value.strip()
            if ssh_keys_str:
                self.config.provisioning.ssh_key_paths = [
                    Path(p.strip()).expanduser() for p in ssh_keys_str.split(",") if p.strip()
                ]
            else:
                self.config.provisioning.ssh_key_paths = []

            # Read Mesh defaults
            self.config.mesh.enable = self.query_one("#mesh_enable", Switch).value
            self.config.mesh.mesh_id = self.query_one("#mesh_id", Input).value.strip()

            channel_str = self.query_one("#channel", Input).value.strip()
            try:
                self.config.mesh.channel = int(channel_str)
            except ValueError:
                self._show_error("Invalid channel number")
                return

            gateway_mode_select = self.query_one("#gateway_mode", Select)
            if not isinstance(gateway_mode_select.value, GatewayMode):
                self._show_error("Invalid gateway mode selection")
                return

            self.config.mesh.gateway_mode = gateway_mode_select.value

            # Read Transport settings
            mode_select = self.query_one("#deployment_mode", Select)
            if isinstance(mode_select.value, DeploymentMode):
                self.config.core.reticulum.mode = mode_select.value

            transport_enabled = self.query_one("#enable_transport", Switch).value
            self.config.core.reticulum.enable_transport = transport_enabled

            announce_select = self.query_one("#announce_interval", Select)
            if isinstance(announce_select.value, int):
                self.config.core.reticulum.announce_interval = announce_select.value
            else:
                self._show_error("Invalid announce interval selection")
                return

            # Read Peers from dynamic rows
            peers: list[PeerConfig] = []
            for row in self.query(".peer-row"):
                host_inputs = list(row.query(".peer-host-input"))
                port_inputs = list(row.query(".peer-port-input"))
                name_inputs = list(row.query(".peer-name-input"))
                if not host_inputs:
                    continue
                host = host_inputs[0].value.strip()
                if not host:
                    continue  # Skip empty rows
                try:
                    port = int(port_inputs[0].value.strip()) if port_inputs else 4242
                except ValueError:
                    self._show_error(f"Invalid port for peer '{host}'")
                    return
                name = name_inputs[0].value.strip() if name_inputs else None
                peers.append(PeerConfig(host=host, port=port, name=name or None))
            self.config.core.reticulum.interfaces.peers = peers

            # Read AutoInterface
            self.config.core.reticulum.interfaces.auto = self.query_one(
                "#auto_interface", Switch
            ).value

            # Read Server interface
            from styrened.models.config import ServerInterfaceConfig

            server_enabled = self.query_one("#server_enabled", Switch).value
            server_ip = self.query_one("#server_listen_ip", Input).value.strip() or "0.0.0.0"
            server_port_str = self.query_one("#server_port", Input).value.strip()
            try:
                server_port = int(server_port_str)
            except ValueError:
                self._show_error("Invalid server port (must be a number)")
                return
            self.config.core.reticulum.interfaces.server = ServerInterfaceConfig(
                enabled=server_enabled, listen_ip=server_ip, port=server_port,
            )

            # Validate configuration
            errors = validate_config(self.config)
            if errors:
                error_msgs = [str(e) for e in errors]
                self._show_error(f"Validation errors: {'; '.join(error_msgs[:3])}")
                return

            # Save to file
            save_config(self.config)

            # Persist network settings to core-config.yaml and regenerate
            # ~/.reticulum/config so RNS picks up the changes on restart.
            try:
                from styrened.services.config import save_core_config
                from styrened.services.reticulum import generate_rns_config

                save_core_config(self.config.core)

                rns_content = generate_rns_config(self.config.core)
                rns_config_path = Path.home() / ".reticulum" / "config"
                rns_config_path.parent.mkdir(parents=True, exist_ok=True)
                rns_config_path.write_text(rns_content)
            except Exception as e:
                self._show_error(f"Failed to write network config: {e}")
                return

            # Show success and dismiss.  dismiss() returns an AwaitComplete
            # that raises ScreenError when awaited from the screen's own
            # message pump.  Scheduling via app.call_later ensures the
            # active_message_pump is the App, not this Screen.
            self._show_success("Configuration saved successfully")
            self.app.call_later(self.dismiss)

        except ConfigValidationError as e:
            error_msgs = [str(err) for err in e.errors]
            self._show_error(f"Validation failed: {'; '.join(error_msgs[:3])}")
        except Exception as e:
            self._show_error(f"Failed to save config: {e}")

    def _show_error(self, message: str) -> None:
        """Display error message.

        Args:
            message: Error message to display.
        """
        status = self.query_one("#status-message", Static)
        status.update(f"[red]ERROR: {message}[/red]")

    def _show_success(self, message: str) -> None:
        """Display success message.

        Args:
            message: Success message to display.
        """
        status = self.query_one("#status-message", Static)
        status.update(f"[green]{message}[/green]")
