"""Settings screen for configuration management."""

from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select, Static, Switch, TabbedContent, TabPane

from styrened.models.config import (
    COMMUNITY_HUB_PROPAGATION_HASH,
    WELL_KNOWN_HUBS,
    DeploymentMode,
    GroupThreadFeatureTierConfig,
    MeshAccessMode,
    PeerConfig,
    validate_short_name,
)
from styrened.tui.models.config import (
    ConfigValidationError,
    GatewayMode,
    LogLevel,
    StyreneConfig,
)
from styrened.tui.services.config import save_config, validate_config
from styrened.ui_state import ConfigDraftInputs, ConfigDraftState, build_config_draft_state

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
from styrened.tui.widgets.highlighted_panel import HighlightedPanel  # noqa: E402


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
        self._persisted_core_config = config.core.to_dict()
        self._draft_state = build_config_draft_state(
            ConfigDraftInputs(
                persisted=self._persisted_core_config,
                editable=self._persisted_core_config,
            )
        )
        self._status_message = ""
        # Appearance preview → commit state: snapshot the applied theme so
        # we can revert if the operator leaves without applying.
        self._applied_theme_name: str = config.tui.theme
        self._applied_theme_url: str = config.tui.custom_theme_url
        self._applied_theme_colors: dict[str, str] = dict(config.tui.custom_theme_colors)
        self._theme_applied: bool = False  # True once the operator commits

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge via typed services protocol."""
        try:
            return self.app.services.bridge  # type: ignore[union-attr]
        except Exception:
            return None

    async def _save_identity(
        self, display_name: str, icon: str, short_name: str
    ) -> None:
        """Notify daemon of identity change so it re-announces.

        The actual config write is handled by ``_save_settings`` which
        serializes ``self.config.core`` (including identity fields) and
        sends the full dict via ``save_core_config``.  This method only
        triggers a daemon-side re-announce for immediate effect.
        """
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
                            classes="panel-interactive",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Hide identity reminder:", classes="setting-label"),
                                Switch(
                                    value=self.config.tui.identity_nudge_dismissed,
                                    id="identity_nudge_dismissed",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "Suppress the Home screen banner that reminds you "
                                "to set a display name. Automatically enabled when "
                                "you save a non-default name above.",
                                classes="setting-description",
                            ),
                            title="NOTIFICATIONS",
                            classes="panel-interactive",
                        )

                # ── Tab 2: Network ───────────────────────────────────────
                with TabPane("Network", id="tab-network"):
                    with VerticalScroll(classes="settings-tab-scroll"):
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Connect:", classes="setting-label"),
                                Switch(
                                    value=self._community_hub_enabled(),
                                    id="community_hub_enabled",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "rns.styrene.io:4242 — public Reticulum transport + LXMF "
                                "store-and-forward delivery for offline recipients. "
                                "Enabled by default for all Styrene installs.",
                                classes="setting-description",
                            ),
                            title="STYRENE COMMUNITY HUB",
                            classes="panel-interactive",
                        )
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
                            classes="panel-interactive",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Static("[b]On[/b]", classes="peer-enabled-col peer-header"),
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
                            classes="panel-interactive",
                            id="peers-panel",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Propagation Node:", classes="setting-label"),
                                Input(
                                    value=self.config.core.lxmf.propagation_destination or "",
                                    placeholder="32-char hex hash (leave blank for none)",
                                    id="propagation_destination",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "LXMF propagation node for store-and-forward delivery. "
                                "Set automatically when Community Hub is enabled. "
                                "Custom: paste the 32-char hex hash of your preferred propagation node. "
                                "Blank: messages only deliver when recipient is online.",
                                classes="setting-description",
                            ),
                            title="PROPAGATION",
                            classes="panel-interactive",
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
                            classes="panel-interactive",
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
                            classes="panel-interactive",
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
                            classes="panel-interactive",
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
                            classes="panel-interactive",
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
                            classes="panel-interactive",
                        )

                # ── Tab 4: Security ──────────────────────────────────────
                with TabPane("Security", id="tab-security"):
                    with VerticalScroll(classes="settings-tab-scroll"):
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Access Mode:", classes="setting-label"),
                                Select(
                                    [
                                        ("Open — admit all announces", MeshAccessMode.OPEN),
                                        ("Allowlist — default deny", MeshAccessMode.ALLOWLIST),
                                    ],
                                    value=self.config.core.discovery.access_mode,
                                    id="mesh_access_mode",
                                    classes="setting-select",
                                    allow_blank=False,
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "Open: every announcing Reticulum node is accepted (default). "
                                "Allowlist: only nodes whose identity hash is listed below "
                                "will appear in the device list and be permitted to interact "
                                "with this node. All others are silently dropped at the "
                                "announce boundary.",
                                classes="setting-description",
                            ),
                            title="MESH ACCESS CONTROL",
                            classes="panel-interactive",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Static(
                                    "[b]Identity Hash[/b]",
                                    classes="allowed-peer-hash-input allowed-peer-header",
                                ),
                                Static("", classes="allowed-peer-remove-btn"),
                                classes="allowed-peer-header-row",
                            ),
                            *self._compose_allowed_peer_rows(),
                            Horizontal(
                                Button(
                                    "+ Add Identity",
                                    id="btn-add-allowed-peer",
                                    classes="setting-btn",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "32-character hex identity hash for each permitted peer. "
                                "Find a peer's identity hash in their dashboard or via "
                                "'styrened identity' on their node. "
                                "Only consulted when Access Mode is Allowlist.",
                                classes="setting-description",
                            ),
                            title="ALLOWED IDENTITIES",
                            classes="panel-interactive",
                            id="allowed-peers-panel",
                        )

                # ── Tab 5: System ────────────────────────────────────────
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
                            classes="panel-interactive",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Enable Group Threads:", classes="setting-label"),
                                Switch(
                                    value=self.config.core.group_threads.enabled,
                                    id="group_threads_enabled",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Feature Tier:", classes="setting-label"),
                                Select(
                                    [(tier.value.title(), tier) for tier in GroupThreadFeatureTierConfig],
                                    value=self.config.core.group_threads.feature_tier,
                                    id="group_threads_feature_tier",
                                    classes="setting-select",
                                    allow_blank=False,
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Bounded Retention:", classes="setting-label"),
                                Switch(
                                    value=self.config.core.group_threads.bounded_retention,
                                    id="group_threads_bounded_retention",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Metadata-first Sync:", classes="setting-label"),
                                Switch(
                                    value=self.config.core.group_threads.metadata_first_sync,
                                    id="group_threads_metadata_first_sync",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Auto-fetch Media:", classes="setting-label"),
                                Switch(
                                    value=self.config.core.group_threads.auto_media_fetch,
                                    id="group_threads_auto_media_fetch",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Background Catch-up:", classes="setting-label"),
                                Switch(
                                    value=self.config.core.group_threads.background_catchup,
                                    id="group_threads_background_catchup",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Auto-select First-run Tier:", classes="setting-label"),
                                Switch(
                                    value=self.config.core.group_threads.first_run_auto_tier,
                                    id="group_threads_first_run_auto_tier",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "Keeps one room identity across transports while tuning local storage and sync pressure. "
                                "Minimal favors bounded retention, metadata-first sync, and explicit confirmation before expensive media actions.",
                                classes="setting-description",
                            ),
                            title="GROUP THREADS",
                            classes="panel-interactive",
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
                            classes="panel-interactive",
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
                            classes="panel-interactive",
                        )
                        yield HighlightedPanel(
                            Horizontal(
                                Label("Serve Pages:", classes="setting-label"),
                                Switch(
                                    value=self.config.core.page_server.enabled,
                                    id="page_server_enabled",
                                    classes="setting-checkbox",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Label("Node Name:", classes="setting-label"),
                                Input(
                                    value=self.config.core.page_server.node_name or "",
                                    placeholder="Styrene Node",
                                    id="page_server_node_name",
                                    classes="setting-input",
                                ),
                                classes="setting-row",
                            ),
                            Horizontal(
                                Button(
                                    "Generate Node Page",
                                    id="btn-generate-page",
                                    classes="setting-btn",
                                ),
                                classes="setting-row",
                            ),
                            Static(
                                "Enable to serve a NomadNet-compatible info page for this node. "
                                "Generate Node Page creates or refreshes an index page with "
                                "version, platform, hardware, and capability info.",
                                classes="setting-description",
                            ),
                            title="PAGES",
                            classes="panel-interactive",
                        )

                # ── Tab 6: Appearance ────────────────────────────────────
                with TabPane("Appearance", id="tab-appearance"):
                    with VerticalScroll(classes="settings-tab-scroll"):
                        yield HighlightedPanel(
                            Static(
                                "Select a built-in theme to preview it immediately. "
                                "Or paste a tweakcn URL to fetch a custom palette.",
                                classes="setting-description",
                            ),
                            Label("Built-in", classes="setting-label"),
                            Horizontal(
                                Button(
                                    "styrene",
                                    id="theme-btn-styrene",
                                    classes="theme-preset-btn",
                                    variant="primary" if self.config.tui.theme == "styrene" else "default",
                                ),
                                classes="setting-row",
                            ),
                            Label("Custom", classes="setting-label"),
                            Horizontal(
                                Input(
                                    value=self.config.tui.custom_theme_url,
                                    placeholder="https://tweakcn.com/themes/...",
                                    id="custom-theme-url",
                                    classes="setting-input",
                                ),
                                Button(
                                    "Fetch",
                                    id="fetch-theme-btn",
                                    classes="setting-btn",
                                ),
                                classes="setting-row",
                            ),
                            Static("", id="theme-status"),
                            title="THEME",
                            classes="panel-interactive",
                        )
                        yield HighlightedPanel(
                            Static(
                                "Edit individual color tokens. "
                                "Changes preview live on this page.",
                                classes="setting-description",
                            ),
                            *self._compose_color_editor(),
                            Horizontal(
                                Button(
                                    "Apply Theme",
                                    id="apply-theme-btn",
                                    variant="primary",
                                    classes="setting-btn",
                                ),
                                Static("", id="apply-theme-hint", classes="setting-description"),
                                classes="setting-row",
                            ),
                            title="COLOR EDITOR",
                            classes="panel-interactive",
                        )
                        # --- Design system sampler (dev reference) ---
                        yield HighlightedPanel(
                            Horizontal(
                                Button("Default", id="btn-sample-default"),
                                Button("Primary", id="btn-sample-primary", variant="primary"),
                                Button("Error", id="btn-sample-error", variant="error"),
                                Button("Warning", id="btn-sample-warning", variant="warning"),
                                Button("Success", id="btn-sample-success", variant="success"),
                                classes="setting-row",
                            ),
                            title="BUTTONS",
                            classes="panel-info",
                        )
                        yield HighlightedPanel(
                            Static("Interactive — forms, inputs, workspaces"),
                            title="panel-interactive",
                            classes="panel-interactive",
                        )
                        yield HighlightedPanel(
                            Static("Info — status readouts, read-only display"),
                            title="panel-info",
                            classes="panel-info",
                        )
                        yield HighlightedPanel(
                            Static("Ambient — feeds, logs, background chrome"),
                            title="panel-ambient",
                            classes="panel-ambient",
                        )
                        yield HighlightedPanel(
                            Static("Container — section grouping boundary"),
                            title="panel-container",
                            classes="panel-container",
                        )
                        yield HighlightedPanel(
                            Static("Alert warning / error / focus"),
                            title="panel-alert variants",
                            classes="panel-alert",
                        )

            # Action bar — outside tabs, always visible
            with Horizontal(id="settings-actions"):
                yield Button("Save", variant="primary", id="save-btn")
                yield Button("Cancel", variant="default", id="cancel-btn")

            yield Static("", id="status-message")

    def _community_hub_enabled(self) -> bool:
        """True if the community hub peer is present and enabled in the peers list."""
        community_host = WELL_KNOWN_HUBS[0].host  # rns.styrene.io
        return any(
            p.host == community_host and p.enabled
            for p in self.config.reticulum.interfaces.peers
        )

    @staticmethod
    def _match_announce_interval(seconds: int) -> int:
        """Find the closest matching preset for an announce interval value."""
        for _label, secs in ANNOUNCE_INTERVALS:
            if secs == seconds:
                return secs
        # Find closest preset
        closest = min(ANNOUNCE_INTERVALS, key=lambda x: abs(x[1] - seconds))
        return closest[1]

    # ------------------------------------------------------------------
    # Color editor
    # ------------------------------------------------------------------

    #: Tokens exposed in the editor, grouped for display.
    _COLOR_GROUPS: ClassVar[list[tuple[str, list[str]]]] = [
        ("Base", ["background", "foreground"]),
        ("Brand", ["primary", "primary-foreground", "secondary", "accent", "destructive"]),
        ("Surfaces", ["card", "card-foreground", "popover", "muted", "muted-foreground"]),
        ("Chrome", ["border", "input", "ring"]),
    ]

    def _get_active_theme_colors(self) -> dict[str, str]:
        """Return hex color dict for the currently active theme.

        Prefers custom_theme_colors if set, otherwise extracts from the
        active TweakcnProfile (built-in styrene or fetched).
        """
        from styrened.tui.themes.tweakcn import parse_color

        if self.config.tui.custom_theme_colors:
            return dict(self.config.tui.custom_theme_colors)

        # Extract from the built-in styrene profile
        from styrened.tui.themes.styrene_brand import get_styrene_profile
        profile = get_styrene_profile()
        return {k: parse_color(v) for k, v in profile.dark.items()}

    def _compose_color_editor(self) -> list:
        """Generate color editor rows — clickable swatches open a color picker."""
        widgets: list = []
        colors = self._get_active_theme_colors()
        for group_name, tokens in self._COLOR_GROUPS:
            widgets.append(Label(f"[bold]{group_name}[/bold]", classes="color-group-label"))
            for token in tokens:
                val = colors.get(token, "")
                swatch_content = f"[on {val}]    [/]" if val else "    "
                widgets.append(
                    Horizontal(
                        Static(
                            swatch_content,
                            id=f"swatch-btn-{token}",
                            classes="color-swatch-btn",
                        ),
                        Label(token, classes="color-token-label"),
                        Label(
                            val or "—",
                            id=f"color-hex-{token}",
                            classes="color-hex-label",
                        ),
                        classes="color-row",
                    )
                )
        return widgets

    def _apply_color_editor_theme(self) -> None:
        """Rebuild and apply theme from current color editor labels (ephemeral preview)."""
        from styrened.tui.themes.tweakcn import TweakcnProfile

        colors: dict[str, str] = {}
        for _, tokens in self._COLOR_GROUPS:
            for token in tokens:
                try:
                    lbl = self.query_one(f"#color-hex-{token}", Label)
                    val = str(lbl.renderable).strip()
                    if val and val.startswith("#"):
                        colors[token] = val
                except Exception:
                    pass

        if not colors:
            return

        # Ephemeral preview only — don't mutate config until Apply
        profile = TweakcnProfile.from_color_dict(colors, name="custom-edited")
        theme = profile.to_textual_theme("dark")
        self.app.register_theme(theme)
        self.app._registered_themes[theme.name] = theme
        self.app.theme = theme.name

    def _populate_color_editor(self, colors: dict[str, str]) -> None:
        """Fill the color editor swatches and hex labels from a color dict."""
        from styrened.tui.themes.tweakcn import parse_color

        for _, tokens in self._COLOR_GROUPS:
            for token in tokens:
                raw = colors.get(token, "")
                hex_val = parse_color(raw) if raw else ""
                try:
                    swatch = self.query_one(f"#swatch-btn-{token}", Static)
                    lbl = self.query_one(f"#color-hex-{token}", Label)
                    if hex_val:
                        swatch.update(f"[on {hex_val}]    [/]")
                        lbl.update(hex_val)
                    else:
                        swatch.update("    ")
                        lbl.update("—")
                except Exception:
                    pass

    def _compose_peer_rows(self) -> list:
        """Generate peer input rows from current config."""
        rows = []
        for i, peer in enumerate(self.config.reticulum.interfaces.peers):
            rows.append(
                Horizontal(
                    Switch(
                        value=peer.enabled,
                        id=f"peer_enabled_{i}",
                        classes="setting-checkbox peer-enabled-toggle",
                    ),
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

    def _compose_allowed_peer_rows(self) -> list:
        """Generate allowed-peer hash input rows from current config."""
        rows = []
        for i, identity_hash in enumerate(sorted(self.config.core.discovery.allowed_peers)):
            rows.append(
                Horizontal(
                    Input(
                        value=identity_hash,
                        placeholder="32-char hex identity hash",
                        id=f"allowed_peer_hash_{i}",
                        classes="allowed-peer-hash-input",
                    ),
                    Button(
                        "✕",
                        id=f"btn-remove-allowed-peer-{i}",
                        classes="allowed-peer-remove-btn",
                        variant="error",
                    ),
                    classes="allowed-peer-row",
                    id=f"allowed-peer-row-{i}",
                )
            )
        return rows

    def _allowed_peer_count(self) -> int:
        """Count current allowed-peer rows in the DOM."""
        return len(list(self.query(".allowed-peer-row")))

    def _peer_count(self) -> int:
        """Count current peer rows in the DOM."""
        return len(list(self.query(".peer-row")))

    def on_mount(self) -> None:
        """Set initial visibility of server fields and access-mode-dependent panels."""
        self._update_server_visibility()
        self._update_allowed_peers_visibility()

    def _set_draft_state(self, draft_state: ConfigDraftState) -> None:
        """Store the current shared config-draft snapshot."""
        self._draft_state = draft_state

    def _validation_error_map(self, errors: list[Exception]) -> dict[str, str]:
        """Normalize validation errors into field/message mapping."""
        error_map: dict[str, str] = {}
        for index, error in enumerate(errors):
            error_map[f"config.{index}"] = str(error)
        return error_map

    def action_save(self) -> None:
        """Save configuration."""
        self.run_worker(self._save_settings())

    def action_cancel(self) -> None:
        """Cancel and return to previous screen, reverting unapplied theme."""
        self._revert_unapplied_theme()
        self.dismiss()

    def _revert_unapplied_theme(self) -> None:
        """If the operator previewed a theme but didn't Apply, revert."""
        if self._theme_applied:
            return  # Operator committed — nothing to revert
        current = str(getattr(self.app, "theme", ""))
        if current != self._applied_theme_name:
            self.app.theme = self._applied_theme_name
            self.config.tui.theme = self._applied_theme_name
            self.config.tui.custom_theme_url = self._applied_theme_url
            self.config.tui.custom_theme_colors = dict(self._applied_theme_colors)

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

        try:
            # Back up existing configs
            config_file = paths.config_file()
            if config_file.exists():
                shutil.copy2(config_file, config_file.with_suffix(".yaml.bak"))

            rns_config = Path.home() / ".reticulum" / "config"
            if rns_config.exists():
                shutil.copy2(rns_config, rns_config.with_suffix(".bak"))

            # Reset core config via IPC — serialize a fresh default CoreConfig
            from styrened.models.config import CoreConfig

            default_config = CoreConfig()
            default_dict = default_config.to_dict()

            bridge = self._ipc_bridge
            if bridge is None:
                raise RuntimeError("Not connected to daemon")
            await bridge.save_core_config(default_dict)

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
            Switch(
                value=True,
                id=f"peer_enabled_{idx}",
                classes="setting-checkbox peer-enabled-toggle",
            ),
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

    @on(Switch.Changed, "#community_hub_enabled")
    def on_community_hub_toggle(self, event: Switch.Changed) -> None:
        """When Community Hub is toggled, sync the propagation destination field."""
        try:
            prop_input = self.query_one("#propagation_destination", Input)
            if event.value:
                prop_input.value = COMMUNITY_HUB_PROPAGATION_HASH
            else:
                # Clear if it was the community hub hash; leave custom values alone
                if prop_input.value == COMMUNITY_HUB_PROPAGATION_HASH:
                    prop_input.value = ""
        except Exception:
            pass

    @on(Switch.Changed, "#server_enabled")
    def on_server_toggle(self, event: Switch.Changed) -> None:
        """Show/hide server IP and port fields."""
        self._update_server_visibility()

    @on(Select.Changed, "#mesh_access_mode")
    def on_mesh_access_mode_changed(self, event: Select.Changed) -> None:
        """Show/hide the allowed-identities panel when access mode changes."""
        self._update_allowed_peers_visibility()

    @on(Button.Pressed, "#btn-add-allowed-peer")
    def on_add_allowed_peer(self) -> None:
        """Add a new blank identity hash row to the allowed-identities panel."""
        idx = self._allowed_peer_count()
        new_row = Horizontal(
            Input(
                value="",
                placeholder="32-char hex identity hash",
                id=f"allowed_peer_hash_{idx}",
                classes="allowed-peer-hash-input",
            ),
            Button(
                "✕",
                id=f"btn-remove-allowed-peer-{idx}",
                classes="allowed-peer-remove-btn",
                variant="error",
            ),
            classes="allowed-peer-row",
            id=f"allowed-peer-row-{idx}",
        )
        try:
            add_btn = self.query_one("#btn-add-allowed-peer")
            add_btn_row = add_btn.parent
            if add_btn_row and add_btn_row.parent:
                add_btn_row.parent.mount(new_row, before=add_btn_row)
            else:
                self.query_one("#allowed-peers-panel").mount(new_row)
        except Exception:
            pass

    @on(Button.Pressed, ".allowed-peer-remove-btn")
    def on_remove_allowed_peer(self, event: Button.Pressed) -> None:
        """Remove an identity hash row from the allowed-identities panel."""
        widget = event.button.parent
        if widget and "allowed-peer-row" in widget.classes:
            widget.remove()

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

    def _update_allowed_peers_visibility(self) -> None:
        """Show or hide the allowed-identities panel based on access mode."""
        try:
            mode_select = self.query_one("#mesh_access_mode", Select)
            panel = self.query_one("#allowed-peers-panel")
            if mode_select.value == MeshAccessMode.ALLOWLIST:
                panel.remove_class("hidden")
            else:
                panel.add_class("hidden")
        except Exception:
            pass

    @on(Button.Pressed, "#save-btn")
    def on_save_button(self) -> None:
        """Handle save button press — Save implicitly applies the theme."""
        self._theme_applied = True  # Don't revert on subsequent dismiss
        self.run_worker(self._save_settings())

    @on(Button.Pressed, "#cancel-btn")
    def on_cancel_button(self) -> None:
        """Handle cancel button press — reverts unapplied theme preview."""
        self._revert_unapplied_theme()
        self.dismiss()

    @on(Button.Pressed, "#clear-nodes-btn")
    def on_clear_nodes_button(self) -> None:
        """Handle clear node history button press.

        TODO: Add a CLEAR_NODES IPC command to the daemon.
        Until then, inform the user that this requires a daemon restart.
        """
        self.notify(
            "Node history clearing requires daemon restart (IPC command not yet available)",
            severity="warning",
        )
        self.app.log.info("Clear node history requested — not yet implemented via IPC")

    @on(Button.Pressed, "#btn-generate-page")
    def on_generate_page_button(self) -> None:
        """Generate or regenerate the default node info page via IPC."""
        self._do_generate_page()

    @work(exclusive=True, group="generate-page")
    async def _do_generate_page(self) -> None:
        """Send page regenerate command to daemon."""
        try:
            bridge = self._ipc_bridge
            if bridge is None:
                self._show_error("Not connected to daemon")
                return

            result = await bridge.page_regenerate_index()
            if result:
                self._show_success("Node page generated ✓")
            else:
                self._show_error("Page generation failed — is the page server enabled?")
        except Exception as e:
            self._show_error(f"Failed to generate page: {e}")

    async def _save_settings(self) -> None:
        """Read form values, validate, and save configuration."""
        try:
            persisted_core = self._persisted_core_config
            live_config = self.config
            self._set_draft_state(
                build_config_draft_state(
                    ConfigDraftInputs(
                        persisted=persisted_core,
                        editable=persisted_core,
                        saving=True,
                    )
                )
            )
            draft_config = deepcopy(self.config)

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
            # Update in-memory config so the later save_core_config(draft_config.core)
            # at the end of this method doesn't overwrite with stale identity values.
            draft_config.core.identity.display_name = identity_display_name
            draft_config.core.identity.icon = identity_icon
            draft_config.core.identity.short_name = (
                identity_short_name if identity_short_name else None
            )

            # Read TUI settings
            log_level_select = self.query_one("#log_level", Select)
            show_hardware = self.query_one("#show_hardware_panel", Switch)
            confirm_destructive = self.query_one("#confirm_destructive", Switch)

            if not isinstance(log_level_select.value, LogLevel):
                self._show_error("Invalid log level selection")
                return
            draft_config.tui.log_level = log_level_select.value
            draft_config.tui.show_hardware_panel = show_hardware.value
            draft_config.tui.confirm_destructive = confirm_destructive.value

            # Identity nudge: auto-dismiss if operator set a real name,
            # otherwise honour the explicit switch state.
            nudge_switch = self.query_one("#identity_nudge_dismissed", Switch)
            if identity_display_name and identity_display_name not in (
                "Anonymous Styrene", ""
            ):
                draft_config.tui.identity_nudge_dismissed = True
            else:
                draft_config.tui.identity_nudge_dismissed = nudge_switch.value

            # Read Fleet settings
            edge_fleet_path = self.query_one("#edge_fleet_path", Input).value.strip()
            draft_config.fleet.edge_fleet_path = (
                Path(edge_fleet_path).expanduser() if edge_fleet_path else None
            )
            draft_config.fleet.inventory_file = self.query_one(
                "#inventory_file", Input
            ).value.strip()
            draft_config.fleet.auto_sync_inventory = self.query_one(
                "#auto_sync_inventory", Switch
            ).value

            # Read Provisioning defaults
            draft_config.provisioning.default_hostname_prefix = self.query_one(
                "#default_hostname_prefix", Input
            ).value.strip()

            # Parse SSH key paths (comma-separated)
            ssh_keys_str = self.query_one("#ssh_key_paths", Input).value.strip()
            if ssh_keys_str:
                draft_config.provisioning.ssh_key_paths = [
                    Path(p.strip()).expanduser() for p in ssh_keys_str.split(",") if p.strip()
                ]
            else:
                draft_config.provisioning.ssh_key_paths = []

            # Read Mesh defaults
            draft_config.mesh.enable = self.query_one("#mesh_enable", Switch).value
            draft_config.mesh.mesh_id = self.query_one("#mesh_id", Input).value.strip()

            channel_str = self.query_one("#channel", Input).value.strip()
            try:
                draft_config.mesh.channel = int(channel_str)
            except ValueError:
                self._show_error("Invalid channel number")
                return

            gateway_mode_select = self.query_one("#gateway_mode", Select)
            if not isinstance(gateway_mode_select.value, GatewayMode):
                self._show_error("Invalid gateway mode selection")
                return

            draft_config.mesh.gateway_mode = gateway_mode_select.value

            # Read Transport settings
            mode_select = self.query_one("#deployment_mode", Select)
            if isinstance(mode_select.value, DeploymentMode):
                draft_config.core.reticulum.mode = mode_select.value

            transport_enabled = self.query_one("#enable_transport", Switch).value
            draft_config.core.reticulum.enable_transport = transport_enabled

            announce_select = self.query_one("#announce_interval", Select)
            if isinstance(announce_select.value, int):
                draft_config.core.reticulum.announce_interval = announce_select.value
            else:
                self._show_error("Invalid announce interval selection")
                return

            # Community Hub — ensure peer and propagation_destination are in sync
            community_hub_on = self.query_one("#community_hub_enabled", Switch).value
            community_host = WELL_KNOWN_HUBS[0].host  # rns.styrene.io
            community_port = WELL_KNOWN_HUBS[0].port

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
                # Read enabled toggle
                enabled_toggles = list(row.query(".peer-enabled-toggle"))
                enabled = enabled_toggles[0].value if enabled_toggles else True
                peers.append(PeerConfig(host=host, port=port, name=name or None, enabled=enabled))
            # Apply community hub peer state
            if community_hub_on:
                # Ensure community hub is present and enabled
                has_hub = any(p.host == community_host for p in peers)
                if not has_hub:
                    peers.insert(
                        0,
                        PeerConfig(
                            host=community_host,
                            port=community_port,
                            name="Styrene Community Hub",
                            enabled=True,
                        ),
                    )
                else:
                    # Mark it enabled
                    for p in peers:
                        if p.host == community_host:
                            p.enabled = True
            else:
                # Disable (but keep) the community hub peer if present
                for p in peers:
                    if p.host == community_host:
                        p.enabled = False

            draft_config.core.reticulum.interfaces.peers = peers

            # Read propagation destination
            prop_dest = self.query_one("#propagation_destination", Input).value.strip()
            if prop_dest:
                if len(prop_dest) != 32 or not all(c in "0123456789abcdef" for c in prop_dest.lower()):
                    self._show_error("Propagation node must be a 32-character hex hash")
                    return
                draft_config.core.lxmf.propagation_destination = prop_dest
            else:
                draft_config.core.lxmf.propagation_destination = None

            # Read AutoInterface
            draft_config.core.reticulum.interfaces.auto = self.query_one(
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
            draft_config.core.reticulum.interfaces.server = ServerInterfaceConfig(
                enabled=server_enabled, listen_ip=server_ip, port=server_port,
            )

            # Read Security / mesh access control settings
            mode_select = self.query_one("#mesh_access_mode", Select)
            if isinstance(mode_select.value, MeshAccessMode):
                draft_config.core.discovery.access_mode = mode_select.value
            else:
                draft_config.core.discovery.access_mode = MeshAccessMode.OPEN

            allowed_peers: set[str] = set()
            for row in self.query(".allowed-peer-row"):
                hash_inputs = list(row.query(".allowed-peer-hash-input"))
                if not hash_inputs:
                    continue
                h = hash_inputs[0].value.strip().lower()
                if not h:
                    continue
                if len(h) != 32 or not all(c in "0123456789abcdef" for c in h):
                    self._show_error(
                        f"Invalid identity hash '{h[:16]}…': must be 32 hex characters"
                    )
                    return
                allowed_peers.add(h)
            draft_config.core.discovery.allowed_peers = allowed_peers

            # Page server settings
            draft_config.core.page_server.enabled = self.query_one(
                "#page_server_enabled", Switch
            ).value
            page_node_name = self.query_one("#page_server_node_name", Input).value.strip()
            draft_config.core.page_server.node_name = page_node_name or None

            # Group thread footprint policy
            group_thread_tier_select = self.query_one("#group_threads_feature_tier", Select)
            if not isinstance(group_thread_tier_select.value, GroupThreadFeatureTierConfig):
                self._show_error("Invalid group thread feature tier")
                return

            draft_config.core.group_threads.enabled = self.query_one(
                "#group_threads_enabled", Switch
            ).value
            draft_config.core.group_threads.feature_tier = group_thread_tier_select.value
            draft_config.core.group_threads.bounded_retention = self.query_one(
                "#group_threads_bounded_retention", Switch
            ).value
            draft_config.core.group_threads.metadata_first_sync = self.query_one(
                "#group_threads_metadata_first_sync", Switch
            ).value
            draft_config.core.group_threads.auto_media_fetch = self.query_one(
                "#group_threads_auto_media_fetch", Switch
            ).value
            draft_config.core.group_threads.background_catchup = self.query_one(
                "#group_threads_background_catchup", Switch
            ).value
            draft_config.core.group_threads.first_run_auto_tier = self.query_one(
                "#group_threads_first_run_auto_tier", Switch
            ).value

            # Validate configuration against the editable draft before mutating
            # the live in-memory config.
            errors = validate_config(draft_config)
            draft_editable = draft_config.core.to_dict()
            if errors:
                error_msgs = [str(e) for e in errors]
                self._set_draft_state(
                    build_config_draft_state(
                        ConfigDraftInputs(
                            persisted=persisted_core,
                            editable=draft_editable,
                            validation_errors=self._validation_error_map(errors),
                        )
                    )
                )
                self._show_error(f"Validation errors: {'; '.join(error_msgs[:3])}")
                return

            # Persist validated draft back into the live config object so
            # callers holding the original SettingsScreen config reference see
            # the saved values immediately.
            live_config.__dict__.update(deepcopy(draft_config.__dict__))
            self.config = live_config
            save_config(self.config)

            try:
                bridge = self._ipc_bridge
                if bridge is not None:
                    config_dict = self.config.core.to_dict()
                    await bridge.save_core_config(config_dict)
            except Exception as e:
                self._set_draft_state(
                    build_config_draft_state(
                        ConfigDraftInputs(
                            persisted=persisted_core,
                            editable=draft_editable,
                            save_error=str(e),
                        )
                    )
                )
                self._show_error(f"Failed to write network config: {e}")
                return

            self._persisted_core_config = self.config.core.to_dict()
            self._set_draft_state(
                build_config_draft_state(
                    ConfigDraftInputs(
                        persisted=self._persisted_core_config,
                        editable=self._persisted_core_config,
                        save_succeeded=True,
                    )
                )
            )

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

    # ------------------------------------------------------------------
    # Appearance tab handlers
    # ------------------------------------------------------------------

    @on(Button.Pressed, "#theme-btn-styrene")
    def on_select_styrene_theme(self) -> None:
        """Select the built-in Styrene theme — ephemeral preview."""
        from styrened.tui.themes.styrene_brand import (
            STYRENE_TWEAKCN_URL,
            get_styrene_profile,
        )
        from styrened.tui.themes.tweakcn import parse_color

        profile = get_styrene_profile()
        theme = profile.to_textual_theme("dark")
        self.app.register_theme(theme)
        self.app._registered_themes[theme.name] = theme
        self.app.theme = theme.name
        resolved = {k: parse_color(v) for k, v in profile.dark.items()}
        self._populate_color_editor(resolved)
        # Update URL field to match
        try:
            self.query_one("#custom-theme-url", Input).value = STYRENE_TWEAKCN_URL
        except Exception:
            pass
        # Update button states
        try:
            btn = self.query_one("#theme-btn-styrene", Button)
            btn.variant = "primary"
        except Exception:
            pass
        self._set_theme_status("Previewing Styrene theme — Apply to keep.", "info")

    @on(Button.Pressed, "#fetch-theme-btn")
    def on_fetch_theme(self) -> None:
        """Fetch a custom tweakcn theme — ephemeral preview only."""
        self._fetch_and_preview_theme()

    @on(Button.Pressed, "#apply-theme-btn")
    def on_apply_theme(self) -> None:
        """Commit the previewed theme to config (persists across sessions)."""
        from styrened.tui.themes.tweakcn import parse_color

        # Read current editor state as the committed colors
        colors: dict[str, str] = {}
        for _, tokens in self._COLOR_GROUPS:
            for token in tokens:
                try:
                    lbl = self.query_one(f"#color-hex-{token}", Label)
                    val = str(lbl.renderable).strip()
                    if val and val.startswith("#"):
                        colors[token] = val
                except Exception:
                    pass

        url = ""
        try:
            url = self.query_one("#custom-theme-url", Input).value.strip()
        except Exception:
            pass

        # Snapshot as the new applied state
        self._applied_theme_name = str(getattr(self.app, "theme", "styrene"))
        self._applied_theme_url = url
        self._applied_theme_colors = dict(colors)
        self._theme_applied = True

        # Update config for the main Save to persist
        self.config.tui.theme = self._applied_theme_name
        self.config.tui.custom_theme_url = url
        self.config.tui.custom_theme_colors = colors

        self._set_theme_status("Theme applied ✓", "success")
        try:
            self.query_one("#apply-theme-hint", Static).update(
                "Theme will persist after Save."
            )
        except Exception:
            pass

    @on(Click, ".color-swatch-btn")
    def _on_swatch_btn_pressed(self, event: Click) -> None:
        """Open color picker when a swatch is clicked."""
        widget = event.widget
        if not widget.id or not widget.id.startswith("swatch-btn-"):
            return
        event.stop()
        token = widget.id[len("swatch-btn-"):]
        # Get current hex value
        current = ""
        try:
            lbl = self.query_one(f"#color-hex-{token}", Label)
            val = str(lbl.renderable).strip()
            if val.startswith("#"):
                current = val
        except Exception:
            pass

        from styrened.tui.widgets.color_picker import ColorPickerDialog

        def _on_picker_result(result: str | None) -> None:
            if result is None:
                return
            try:
                swatch = self.query_one(f"#swatch-btn-{token}", Static)
                lbl = self.query_one(f"#color-hex-{token}", Label)
                swatch.update(f"[on {result}]    [/]")
                lbl.update(result)
            except Exception:
                pass
            self._apply_color_editor_theme()

        self.app.push_screen(
            ColorPickerDialog(token_name=token, initial_color=current or "#000000"),
            _on_picker_result,
        )

    @work
    async def _fetch_and_preview_theme(self) -> None:
        """Worker: fetch tweakcn URL, register, and preview (ephemeral)."""
        import asyncio

        from styrened.tui.themes.tweakcn import TweakcnProfile

        url_input = self.query_one("#custom-theme-url", Input)
        url = url_input.value.strip()

        if not url:
            self._set_theme_status("Enter a tweakcn URL first.", "error")
            return

        self._set_theme_status("Fetching theme…", "info")
        try:
            profile = await asyncio.get_event_loop().run_in_executor(
                None, TweakcnProfile.from_url, url
            )
            theme = profile.to_textual_theme("dark")
            self.app.register_theme(theme)
            self.app._registered_themes[theme.name] = theme
            self.app.theme = theme.name
            # Populate the color editor with the fetched palette
            from styrened.tui.themes.tweakcn import parse_color
            resolved = {
                k: parse_color(v) for k, v in profile.dark.items()
            }
            self._populate_color_editor(resolved)
            # De-select styrene button since we're previewing a custom theme
            try:
                self.query_one("#theme-btn-styrene", Button).variant = "default"
            except Exception:
                pass
            self._set_theme_status(
                f'Previewing "{theme.name}" — Apply to keep.',
                "success",
            )
        except ValueError as e:
            self._set_theme_status(f"Invalid URL: {e}", "error")
        except Exception as e:
            self._set_theme_status(f"Fetch failed: {e}", "error")

    def _set_theme_status(self, text: str, style: str = "info") -> None:
        """Update the theme status label (safe to call from worker).

        Args:
            text: Plain text message.
            style: One of 'success', 'error', 'info'.
        """
        try:
            widget = self.query_one("#theme-status", Static)
            widget.update(text)
            for cls in ("status-success", "status-error", "status-info"):
                widget.remove_class(cls)
            widget.add_class(f"status-{style}")
        except Exception:
            pass

    def _show_error(self, message: str) -> None:
        """Display error message."""
        status = self.query_one("#status-message", Static)
        status.update(f"ERROR: {message}")
        status.remove_class("status-success")
        status.add_class("status-error")

    def _show_success(self, message: str) -> None:
        """Display success message."""
        status = self.query_one("#status-message", Static)
        status.update(message)
        status.remove_class("status-error")
        status.add_class("status-success")
