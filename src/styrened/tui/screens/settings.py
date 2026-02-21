"""Settings screen for configuration management."""

from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from styrened.services.hub_connection import STYRENE_HUB_ADDRESS
from styrened.tui.models.config import (
    ConfigValidationErrors,
    GatewayMode,
    LogLevel,
    StyreneConfig,
    ThemeMode,
)
from styrened.tui.services.config import save_config, validate_config
from styrened.tui.themes.color_cascade import ColorCascade, list_presets
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, set_color_cascade

# Known Reticulum hubs for LXMF fleet coordination

KNOWN_HUBS = {
    "none": ("None (Disabled)", None),
    "styrene": ("Styrene Community Hub", STYRENE_HUB_ADDRESS),  # brutus cluster hub
    "custom": ("Custom Hub...", None),
}


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
    ]

    def __init__(self, config: StyreneConfig) -> None:
        """Initialize settings screen.

        Args:
            config: Current configuration to edit.
        """
        super().__init__()
        self.config = config
        self._status_message = ""

    def _get_hub_key_from_address(self, address: str | None) -> str:
        """Determine which hub key matches the given address.

        Args:
            address: Hub LXMF address to match.

        Returns:
            Hub key ("none", "styrene", or "custom").
        """
        if not address:
            return "none"

        # Check if address matches a known hub
        for key, (_, hub_address) in KNOWN_HUBS.items():
            if hub_address and hub_address == address:
                return key

        # Unknown address = custom
        return "custom"

    def compose(self) -> ComposeResult:
        """Compose the settings screen layout."""
        with VerticalScroll(id="settings-container"):
            # TUI Settings
            yield HighlightedPanel(
                Horizontal(
                    Label("Theme:", classes="setting-label"),
                    Select(
                        [(preset.name, key) for key, preset in list_presets()],
                        value=self.config.tui.theme.value,
                        id="theme",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Log Level:", classes="setting-label"),
                    Select(
                        [(level.value, level) for level in LogLevel],
                        value=self.config.tui.log_level,
                        id="log_level",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Show Hardware Panel:", classes="setting-label"),
                    Checkbox(
                        "",
                        self.config.tui.show_hardware_panel,
                        id="show_hardware_panel",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Confirm Destructive:", classes="setting-label"),
                    Checkbox(
                        "",
                        self.config.tui.confirm_destructive,
                        id="confirm_destructive",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                title="TUI SETTINGS",
            )

            # Fleet Settings
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
                    Checkbox(
                        "",
                        self.config.fleet.auto_sync_inventory,
                        id="auto_sync_inventory",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                title="FLEET SETTINGS",
            )

            # Provisioning Defaults
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
                        value=", ".join(str(p) for p in self.config.provisioning.ssh_key_paths),
                        placeholder="~/.ssh/id_ed25519.pub, ~/.ssh/id_rsa.pub",
                        id="ssh_key_paths",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                title="PROVISIONING DEFAULTS",
            )

            # Mesh Defaults
            yield HighlightedPanel(
                Horizontal(
                    Label("Enable Mesh:", classes="setting-label"),
                    Checkbox(
                        "",
                        self.config.mesh.enable,
                        id="mesh_enable",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Mesh ID:", classes="setting-label"),
                    Input(
                        value=self.config.mesh.mesh_id,
                        placeholder="styrene",
                        id="mesh_id",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Channel:", classes="setting-label"),
                    Input(
                        value=str(self.config.mesh.channel),
                        placeholder="6",
                        id="channel",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Gateway Mode:", classes="setting-label"),
                    Select(
                        [(mode.value, mode) for mode in GatewayMode],
                        value=self.config.mesh.gateway_mode,
                        id="gateway_mode",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                title="MESH DEFAULTS",
            )

            # Reticulum Settings
            yield HighlightedPanel(
                Horizontal(
                    Label("Config Path Override:", classes="setting-label"),
                    Input(
                        value=str(self.config.reticulum.config_path_override or ""),
                        placeholder="/path/to/reticulum/config",
                        id="config_path_override",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Auto Initialize:", classes="setting-label"),
                    Checkbox(
                        "",
                        self.config.reticulum.auto_initialize,
                        id="auto_initialize",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Hub:", classes="setting-label"),
                    Select(
                        [(label, key) for key, (label, _) in KNOWN_HUBS.items()],
                        value=self._get_hub_key_from_address(self.config.reticulum.hub_address),
                        id="hub_select",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Horizontal(
                    Label("Custom Hub Address:", classes="setting-label"),
                    Input(
                        value=self.config.reticulum.hub_address or "",
                        placeholder="32-char hex LXMF address",
                        id="hub_address",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                    id="custom-hub-row",
                ),
                Horizontal(
                    Label("Hub Announce Interval:", classes="setting-label"),
                    Input(
                        value=str(self.config.reticulum.hub_announce_interval),
                        placeholder="60",
                        id="hub_announce_interval",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                title="RETICULUM SETTINGS",
            )

            # Data Management
            yield HighlightedPanel(
                Horizontal(
                    Label(
                        "Clear Node History:",
                        classes="setting-label",
                    ),
                    Button(
                        "Clear All Nodes",
                        variant="warning",
                        id="clear-nodes-btn",
                        classes="setting-input",
                    ),
                    classes="setting-row",
                ),
                Static(
                    "[dim]Removes all discovered nodes from persistent storage. "
                    "New announces will repopulate the list.[/dim]",
                    classes="setting-description",
                ),
                title="DATA MANAGEMENT",
            )

            # Action buttons
            with Horizontal(id="settings-actions"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

            # Status message
            yield Static("", id="status-message")

    def on_mount(self) -> None:
        """Set initial visibility of custom hub address field."""
        self._update_custom_hub_visibility()

    def action_save(self) -> None:
        """Save configuration."""
        self._save_settings()

    def action_cancel(self) -> None:
        """Cancel and return to previous screen."""
        self.dismiss()

    @on(Select.Changed, "#theme")
    def on_theme_select_changed(self, event: Select.Changed) -> None:
        """Handle theme selection change - apply live preview.

        Args:
            event: Selection change event.
        """
        preset_key = str(event.value) if event.value else "mars"
        self._apply_theme_live(preset_key)

    def _apply_theme_live(self, preset_key: str) -> None:
        """Apply theme change immediately for live preview.

        Args:
            preset_key: Forge world preset key (e.g., "mars", "ryza").
        """
        try:
            # Update cascade for Rich markup
            cascade = ColorCascade.from_preset(preset_key)
            set_color_cascade(cascade)

            # Switch Textual theme (updates CSS-driven elements)
            self.app.theme = preset_key

            # Refresh all HighlightedPanel borders (this screen + app)
            for panel in self.query(HighlightedPanel):
                panel.refresh_theme()

        except ValueError:
            # Invalid preset, ignore for live preview
            pass

    @on(Select.Changed, "#hub_select")
    def on_hub_select_changed(self, event: Select.Changed) -> None:
        """Handle hub selection change to show/hide custom address input.

        Args:
            event: Selection change event.
        """
        self._update_custom_hub_visibility()

    def _update_custom_hub_visibility(self) -> None:
        """Show or hide the custom hub address input based on selection."""
        try:
            hub_select = self.query_one("#hub_select", Select)
            custom_row = self.query_one("#custom-hub-row")

            # Show custom input only when "custom" is selected
            if hub_select.value == "custom":
                custom_row.remove_class("hidden")
            else:
                custom_row.add_class("hidden")
        except Exception:
            # Widgets not yet mounted
            pass

    @on(Button.Pressed, "#save-btn")
    def on_save_button(self) -> None:
        """Handle save button press."""
        self._save_settings()

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

    def _save_settings(self) -> None:
        """Read form values, validate, and save configuration."""
        try:
            # Read TUI settings
            theme_select = self.query_one("#theme", Select)
            log_level_select = self.query_one("#log_level", Select)
            show_hardware = self.query_one("#show_hardware_panel", Checkbox)
            confirm_destructive = self.query_one("#confirm_destructive", Checkbox)

            # Theme is a string key from forge world presets
            theme_key = str(theme_select.value) if theme_select.value else "mars"
            try:
                self.config.tui.theme = ThemeMode(theme_key)
            except ValueError:
                self._show_error(f"Invalid theme: {theme_key}")
                return

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
                "#auto_sync_inventory", Checkbox
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
            self.config.mesh.enable = self.query_one("#mesh_enable", Checkbox).value
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

            # Read Reticulum settings
            config_override = self.query_one("#config_path_override", Input).value.strip()
            self.config.reticulum.config_path_override = (
                Path(config_override).expanduser() if config_override else None
            )

            self.config.reticulum.auto_initialize = self.query_one(
                "#auto_initialize", Checkbox
            ).value

            # Read hub selection
            hub_select = self.query_one("#hub_select", Select)
            hub_key = str(hub_select.value) if hub_select.value else "none"

            if hub_key == "none":
                # Hub disabled
                self.config.reticulum.hub_enabled = False
                self.config.reticulum.hub_address = None
            elif hub_key == "custom":
                # Custom hub - read from input
                hub_address = self.query_one("#hub_address", Input).value.strip()
                self.config.reticulum.hub_enabled = bool(hub_address)
                self.config.reticulum.hub_address = hub_address or ""
            else:
                # Known hub - use predefined address
                hub_info = KNOWN_HUBS.get(hub_key, (None, None))
                hub_address = (hub_info[1] if hub_info else "") or ""
                self.config.reticulum.hub_enabled = True
                self.config.reticulum.hub_address = hub_address

            # Read hub announce interval
            interval_str = self.query_one("#hub_announce_interval", Input).value.strip()
            try:
                self.config.reticulum.hub_announce_interval = int(interval_str)
            except ValueError:
                self._show_error("Invalid hub announce interval (must be a number)")
                return

            # Validate configuration
            errors = validate_config(self.config)
            if errors:
                error_msgs = [str(e) for e in errors]
                self._show_error(f"Validation errors: {'; '.join(error_msgs[:3])}")
                return

            # Save to file
            save_config(self.config)

            # If hub settings changed, retry connection
            if self.config.reticulum.hub_enabled and self.config.reticulum.hub_address:
                from styrened.services.hub_connection import get_hub_connection

                hub_connection = get_hub_connection()
                hub_connection.set_announce_interval(self.config.reticulum.hub_announce_interval)

                if not hub_connection.retry_connection():
                    # If connection failed, start waiting timer
                    hub_connection.start_waiting()

            # Show success and dismiss
            self._show_success("Configuration saved successfully")
            self.app.call_later(self.dismiss, 1.0)

        except ConfigValidationErrors as e:
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
