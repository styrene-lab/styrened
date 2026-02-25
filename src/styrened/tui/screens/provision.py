"""Provisioning screen — forge pipeline integration.

End-to-end SD/USB flashing from device catalog selection through
forge pipeline execution and post-flash mesh detection.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static
from textual.worker import Worker

from styrened.tui.forge.models import (
    DeviceProfile,
    DiskInfo,
    FlashTarget,
    ForgeConfig,
    MediaEvent,
    load_device_catalog,
    load_forge_config,
)
from styrened.tui.widgets.config_form import ConfigForm
from styrened.tui.widgets.forge_log import ForgeLog
from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade

# ---------------------------------------------------------------------------
# Device catalog table
# ---------------------------------------------------------------------------


class DeviceCatalogTable(DataTable[str]):
    """Device selection table loaded from devices.yaml catalog."""

    def on_mount(self) -> None:
        self.add_columns("NAME", "MODEL", "ARCH", "MEDIA", "SPECS")
        self.cursor_type = "row"

    def load_catalog(self, devices: dict[str, DeviceProfile]) -> None:
        """Populate the table from a device catalog dict."""
        self.clear()
        cascade = get_color_cascade()

        for dev_id, dev in devices.items():
            arch_color = cascade.medium if dev.arch == "aarch64" else cascade.dim
            media_color = cascade.medium if dev.media_target == "sd" else cascade.dim
            specs_summary = f"{dev.specs.cpu}, {dev.specs.ram_mb}MB"

            self.add_row(
                f"[{cascade.bright}]{dev.label}[/]",
                f"[{cascade.dim}]{dev.model}[/]",
                f"[{arch_color}]{dev.arch}[/]",
                f"[{media_color}]{dev.media_target.upper()}[/]",
                f"[{cascade.dim}]{specs_summary}[/]",
                key=dev_id,
            )


# ---------------------------------------------------------------------------
# Disk detection table
# ---------------------------------------------------------------------------


class DiskDetectTable(DataTable[str]):
    """External disk listing from platform detection."""

    def on_mount(self) -> None:
        self.add_columns("DEVICE", "NAME", "SIZE", "TYPE")
        self.cursor_type = "row"

    def load_disks(self, disks: list[DiskInfo]) -> None:
        """Populate from disk detection results."""
        self.clear()
        cascade = get_color_cascade()

        if not disks:
            self.add_row(
                f"[{cascade.dim}]—[/]",
                f"[{cascade.dim}]No removable media detected[/]",
                f"[{cascade.dim}]—[/]",
                f"[{cascade.dim}]—[/]",
            )
            return

        for disk in disks:
            type_color = cascade.medium if disk.media_type == "SD" else cascade.dim
            self.add_row(
                f"[{cascade.bright}]{disk.device}[/]",
                f"[{cascade.dim}]{disk.name}[/]",
                f"[{cascade.dim}]{disk.size}[/]",
                f"[{type_color}]{disk.media_type}[/]",
                key=disk.device,
            )


# ---------------------------------------------------------------------------
# Provision screen
# ---------------------------------------------------------------------------


class ProvisionScreen(Screen[None]):
    """Device provisioning screen with progressive disclosure.

    Flow: Select device → Configure → Confirm → Flash → Mesh watch
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("r", "refresh_disks", "Refresh Disks", show=True),
    ]

    CSS = """
    ProvisionScreen {
        background: $surface;
    }

    #provision-container {
        height: 1fr;
        padding: 1;
    }

    #device-panel {
        height: auto;
        max-height: 50%;
    }

    #device-catalog-table {
        height: auto;
        max-height: 16;
    }

    #config-panel {
        height: auto;
    }

    #config-panel.hidden {
        display: none;
    }

    #config-inner {
        height: auto;
    }

    #disk-section {
        height: auto;
        margin-top: 1;
    }

    #disk-table {
        height: auto;
        max-height: 8;
    }

    #disk-actions {
        height: auto;
        margin-top: 1;
    }

    #disk-actions Button {
        margin-right: 1;
    }

    #forge-panel {
        height: 1fr;
    }

    #forge-panel.hidden {
        display: none;
    }

    .provision-flash-actions {
        height: auto;
        margin-top: 1;
    }

    .provision-flash-actions Button {
        margin-right: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._devices: dict[str, DeviceProfile] = {}
        self._selected_device: DeviceProfile | None = None
        self._selected_disk: DiskInfo | None = None
        self._detected_disks: list[DiskInfo] = []
        self._forge_config: ForgeConfig = ForgeConfig()
        self._edge_dir: Path | None = None
        self._config: dict[str, str] = {}
        self._flash_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="provision-container"):
            # Device selection panel
            with HighlightedPanel(title="SELECT DEVICE", id="device-panel"):
                yield DeviceCatalogTable(id="device-catalog-table")

            # Configuration panel (hidden until device selected)
            with HighlightedPanel(title="CONFIGURE", id="config-panel", classes="hidden"):
                with Vertical(id="config-inner"):
                    yield ConfigForm(id="config-form")

                    with Vertical(id="disk-section"):
                        yield Static("TARGET DISK", classes="title")
                        yield DiskDetectTable(id="disk-table")

                    with Horizontal(id="disk-actions"):
                        yield Button(
                            "Refresh Disks", id="btn-refresh-disks", variant="default"
                        )

                    with Horizontal(classes="provision-flash-actions"):
                        yield Button(
                            "Flash", id="btn-flash", variant="success", disabled=True
                        )

            # Forge panel (hidden until flash starts)
            with HighlightedPanel(title="FORGE", id="forge-panel", classes="hidden"):
                yield ForgeLog(id="forge-log")

        yield Footer()

    async def on_mount(self) -> None:
        """Load device catalog and forge config on mount."""
        # Resolve edge_dir from app config
        try:
            app = self.app
            config = getattr(app, "config", None)
            if config and config.fleet.edge_fleet_path:
                self._edge_dir = config.fleet.edge_fleet_path
        except Exception:
            pass

        # Load device catalog
        await self._load_catalog()

        # Load forge config
        if self._edge_dir:
            forge_yaml = self._edge_dir / "forge.yaml"
            self._forge_config = load_forge_config(forge_yaml)

    async def _load_catalog(self) -> None:
        """Load device catalog from bundled or edge_dir data."""
        try:
            catalog_path: Path | None = None

            # Try edge_dir first
            if self._edge_dir:
                edge_catalog = self._edge_dir / "forge" / "data" / "devices.yaml"
                if edge_catalog.exists():
                    catalog_path = edge_catalog

            # Fall back to bundled/user catalog
            if catalog_path is None:
                from styrened.tui.forge.models import get_device_catalog_path

                catalog_path = get_device_catalog_path()

            self._devices = load_device_catalog(catalog_path)
            table = self.query_one("#device-catalog-table", DeviceCatalogTable)
            table.load_catalog(self._devices)

        except Exception as e:
            self.notify(f"Could not load device catalog: {e}", severity="error")

    # ------------------------------------------------------------------
    # Device selection
    # ------------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle device or disk row selection."""
        if event.data_table.id == "device-catalog-table":
            self._handle_device_selected(event)
        elif event.data_table.id == "disk-table":
            self._handle_disk_selected(event)

    def _handle_device_selected(self, event: DataTable.RowSelected) -> None:
        """Handle device catalog row selection."""
        if not event.row_key or not event.row_key.value:
            return

        dev_id = str(event.row_key.value)
        device = self._devices.get(dev_id)
        if not device:
            return

        self._selected_device = device

        # Show config panel
        config_panel = self.query_one("#config-panel")
        config_panel.remove_class("hidden")

        # Rebuild ConfigForm with device/forge defaults
        self._rebuild_config_form()

        # Trigger disk detection
        self.run_worker(self._detect_disks(), group="disk-detect")

        self._update_flash_button()

    def _rebuild_config_form(self) -> None:
        """Replace the ConfigForm with one pre-populated for the selected device."""
        try:
            old_form = self.query_one("#config-form", ConfigForm)
            new_form = ConfigForm(
                forge_config=self._forge_config,
                device=self._selected_device,
                id="config-form",
            )
            old_form.replace_with(new_form)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Disk detection
    # ------------------------------------------------------------------

    async def _detect_disks(self) -> None:
        """Detect external disks."""
        from styrened.tui.forge.disk_detect import detect_external_disks

        self._detected_disks = detect_external_disks()
        try:
            table = self.query_one("#disk-table", DiskDetectTable)
            table.load_disks(self._detected_disks)
        except Exception:
            pass

    def _handle_disk_selected(self, event: DataTable.RowSelected) -> None:
        """Handle disk table row selection."""
        if not event.row_key or not event.row_key.value:
            return

        device_path = str(event.row_key.value)
        for disk in self._detected_disks:
            if disk.device == device_path:
                self._selected_disk = disk
                break

        self._update_flash_button()

    def action_refresh_disks(self) -> None:
        """Refresh disk detection."""
        self.run_worker(self._detect_disks(), group="disk-detect")

    # ------------------------------------------------------------------
    # Config form handling
    # ------------------------------------------------------------------

    def on_config_form_changed(self, message: ConfigForm.Changed) -> None:
        """Handle configuration changes."""
        self._config = message.config
        self._update_flash_button()

    def _update_flash_button(self) -> None:
        """Enable flash button only when all selections are made."""
        can_flash = all([
            self._selected_device,
            self._selected_disk,
            self._config.get("hostname"),
        ])
        try:
            self.query_one("#btn-flash", Button).disabled = not can_flash
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Flash flow
    # ------------------------------------------------------------------

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-flash":
            await self._initiate_flash()
        elif event.button.id == "btn-refresh-disks":
            self.run_worker(self._detect_disks(), group="disk-detect")

    async def _initiate_flash(self) -> None:
        """Validate, confirm, and start the flash process."""
        if not self._selected_device or not self._selected_disk:
            return

        # Validate config form
        config_form = self.query_one("#config-form", ConfigForm)
        is_valid, errors = config_form.validate()
        if not is_valid:
            for err in errors:
                self.notify(err, severity="error")
            return

        # Check edge_dir
        if not self._edge_dir:
            self.notify("Set edge fleet path in Settings", severity="error")
            return

        # Push confirmation modal
        from styrened.tui.screens.confirm_flash import ConfirmFlash

        confirmed = await self.app.push_screen_wait(
            ConfirmFlash(
                device_label=self._selected_device.label,
                device_model=self._selected_device.model,
                disk_path=self._selected_disk.device,
                disk_name=self._selected_disk.name,
                disk_size=self._selected_disk.size,
            )
        )

        if not confirmed:
            return

        # Transition to forge state
        self._show_forge_panel()

        # Build FlashTarget
        target = FlashTarget(
            device=self._selected_device,
            disk_path=self._selected_disk.device,
            disk_name=self._selected_disk.name,
            disk_size=self._selected_disk.size,
            hostname=self._config.get("hostname", self._selected_device.default_hostname),
            wifi_ssid=self._config.get("wifi_ssid", ""),
            wifi_password=self._config.get("wifi_password", ""),
            ssh_key_path=self._config.get("ssh_key_path", ""),
        )

        # Set hostname on forge log for mesh watch
        forge_log = self.query_one("#forge-log", ForgeLog)
        forge_log.set_hostname(target.hostname)

        # Start forge pipeline
        self._flash_worker = self.run_worker(
            self._run_forge(target), exclusive=True, group="forge"
        )

    def _show_forge_panel(self) -> None:
        """Hide selection panels, show forge panel."""
        try:
            self.query_one("#device-panel").add_class("hidden")
            self.query_one("#config-panel").add_class("hidden")
            forge_panel = self.query_one("#forge-panel")
            forge_panel.remove_class("hidden")

            forge_log = self.query_one("#forge-log", ForgeLog)
            forge_log.reset()
        except Exception:
            pass

    def _show_selection_panels(self) -> None:
        """Return to selection state."""
        try:
            self.query_one("#device-panel").remove_class("hidden")
            if self._selected_device:
                self.query_one("#config-panel").remove_class("hidden")
            self.query_one("#forge-panel").add_class("hidden")
        except Exception:
            pass

    async def _run_forge(self, target: FlashTarget) -> None:
        """Execute the forge media writer pipeline."""
        from styrened.tui.forge.media_writer import run_media_writer

        forge_log = self.query_one("#forge-log", ForgeLog)

        try:
            async for event in run_media_writer(target, self._edge_dir):
                forge_log.handle_event(event)
        except Exception as exc:
            forge_log.handle_event(
                MediaEvent(kind="error", message=f"Pipeline failed: {exc}")
            )

    # ------------------------------------------------------------------
    # Forge log events
    # ------------------------------------------------------------------

    def on_forge_log_aborted(self, message: ForgeLog.Aborted) -> None:
        """Handle abort/done from forge log."""
        forge_log = self.query_one("#forge-log", ForgeLog)

        if forge_log.is_complete or forge_log.is_error:
            # Done — return to selection
            self._show_selection_panels()
        else:
            # Active — cancel worker
            if self._flash_worker:
                self._flash_worker.cancel()
            self._show_selection_panels()

    def on_forge_log_flash_complete(self, message: ForgeLog.FlashComplete) -> None:
        """Handle flash completion — start mesh watch."""
        self.notify(f"Flash complete: {message.hostname}", severity="information")
        self._start_mesh_watch(message.hostname)

    # ------------------------------------------------------------------
    # Post-flash mesh detection (Step 7)
    # ------------------------------------------------------------------

    def _start_mesh_watch(self, hostname: str) -> None:
        """Begin watching for the newly provisioned node on the mesh."""
        forge_log = self.query_one("#forge-log", ForgeLog)
        forge_log.start_mesh_watch()

        try:
            from styrened.tui.services.reticulum import start_discovery

            start_discovery(callback=lambda device: self._on_mesh_device(device, hostname))
        except Exception:
            pass

    def _on_mesh_device(self, device, hostname: str) -> None:  # noqa: ANN001
        """Callback for mesh device discovery during post-flash watch."""
        try:
            if device.name and hostname.lower() in device.name.lower():
                self.app.call_from_thread(self._mesh_node_found, hostname)
        except Exception:
            pass

    def _mesh_node_found(self, hostname: str) -> None:
        """Handle mesh node detection (main thread)."""
        try:
            forge_log = self.query_one("#forge-log", ForgeLog)
            forge_log.mesh_node_found(hostname)
            self.notify(f"Node {hostname} joined the mesh")
        except Exception:
            pass
