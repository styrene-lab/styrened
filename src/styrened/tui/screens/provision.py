"""Provisioning screen."""

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Static
from textual.worker import Worker

from styrened.tui.models.device_hardware import Hardware
from styrened.tui.models.profiles import Profile
from styrened.tui.services.catalog import load_catalog, query_hardware, query_profiles
from styrened.tui.services.provisioner import provision_device
from styrened.tui.services.storage import StorageDevice, detect_storage
from styrened.tui.widgets.config_form import ConfigForm
from styrened.tui.widgets.hardware_picker import HardwarePicker
from styrened.tui.widgets.profile_picker import ProfilePicker
from styrened.tui.widgets.progress_panel import ProgressPanel
from styrened.tui.widgets.storage_picker import StoragePicker


class ProvisionScreen(Screen[None]):
    """Screen for device provisioning workflow.

    Provides a complete provisioning UI with profile, hardware, storage selection,
    configuration input, and progress tracking.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back", show=True),
    ]

    CSS = """
    ProvisionScreen {
        background: $surface;
    }

    ProvisionScreen .main-container {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    ProvisionScreen .selection-panel {
        width: 1fr;
        height: 100%;
    }

    ProvisionScreen .left-column {
        width: 50%;
        height: 100%;
    }

    ProvisionScreen .right-column {
        width: 50%;
        height: 100%;
    }

    ProvisionScreen .summary-panel {
        height: auto;
        border: solid $primary;
        padding: 1;
        margin-top: 1;
    }

    ProvisionScreen .summary-title {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    ProvisionScreen .summary-item {
        color: $text;
        margin-bottom: 0;
    }

    ProvisionScreen .actions {
        height: auto;
        layout: horizontal;
        margin-top: 1;
    }

    ProvisionScreen Button {
        margin-right: 1;
    }

    ProvisionScreen .progress-container {
        width: 100%;
        height: 100%;
        display: none;
    }

    ProvisionScreen .progress-container.visible {
        display: block;
    }
    """

    def __init__(self) -> None:
        """Initialize provision screen."""
        super().__init__()
        self._selected_profile: Profile | None = None
        self._selected_hardware: Hardware | None = None
        self._selected_storage: StorageDevice | None = None
        self._config: dict[str, str] = {}
        self._provisioning_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        """Compose the provision screen UI."""
        with Container(classes="main-container"):
            # Selection panel (visible initially)
            with Vertical(classes="selection-panel", id="selection-panel"):
                with Horizontal():
                    # Left column: Profile and Hardware
                    with Vertical(classes="left-column"):
                        yield ProfilePicker([], id="profile-picker")
                        yield HardwarePicker([], id="hardware-picker")

                    # Right column: Storage and Config
                    with Vertical(classes="right-column"):
                        yield StoragePicker([], id="storage-picker")
                        yield ConfigForm(id="config-form")

                # Summary and actions
                with Vertical(classes="summary-panel", id="summary-panel"):
                    yield Static("SUMMARY", classes="summary-title")
                    yield Static(
                        "Profile: Not selected", id="summary-profile", classes="summary-item"
                    )
                    yield Static(
                        "Hardware: Not selected", id="summary-hardware", classes="summary-item"
                    )
                    yield Static(
                        "Storage: Not selected", id="summary-storage", classes="summary-item"
                    )
                    yield Static("Hostname: Not set", id="summary-hostname", classes="summary-item")

                with Container(classes="actions"):
                    yield Button(
                        "Provision Device", id="btn-provision", variant="success", disabled=True
                    )
                    yield Button("Cancel", id="btn-cancel", variant="default")

            # Progress panel (hidden initially)
            with Container(classes="progress-container", id="progress-container"):
                yield ProgressPanel(id="progress-panel")

    async def on_mount(self) -> None:
        """Load catalog and storage devices when screen mounts."""
        # Load catalog (gracefully handle missing catalog files)
        try:
            catalog = load_catalog()
            profiles = query_profiles(catalog)
            hardware_list = query_hardware(catalog)

            # Update pickers
            profile_picker = self.query_one("#profile-picker", ProfilePicker)
            profile_picker.profiles = profiles
            await profile_picker.recompose()

            hardware_picker = self.query_one("#hardware-picker", HardwarePicker)
            hardware_picker.hardware_list = hardware_list
            await hardware_picker.recompose()

            # Detect storage devices
            await self._refresh_storage()
        except Exception as e:
            # Show error and allow graceful navigation
            self.notify(
                f"Provisioning unavailable: {e}",
                title="Catalog Error",
                severity="error",
            )

    async def _refresh_storage(self) -> None:
        """Refresh the list of storage devices."""
        devices = await detect_storage()
        storage_picker = self.query_one("#storage-picker", StoragePicker)
        storage_picker.update_devices(devices)

    def on_profile_picker_changed(self, message: ProfilePicker.Changed) -> None:
        """Handle profile selection change."""
        self._selected_profile = message.profile
        self._update_summary()

    def on_hardware_picker_changed(self, message: HardwarePicker.Changed) -> None:
        """Handle hardware selection change."""
        self._selected_hardware = message.hardware
        self._update_summary()

    def on_storage_picker_changed(self, message: StoragePicker.Changed) -> None:
        """Handle storage selection change."""
        self._selected_storage = message.storage
        self._update_summary()

    async def on_storage_picker_refresh_requested(
        self, message: StoragePicker.RefreshRequested
    ) -> None:
        """Handle storage refresh request."""
        await self._refresh_storage()

    def on_config_form_changed(self, message: ConfigForm.Changed) -> None:
        """Handle configuration change."""
        self._config = message.config
        self._update_summary()

    def _update_summary(self) -> None:
        """Update the summary panel and provision button state."""
        # Update summary text
        self.query_one("#summary-profile", Static).update(
            f"Profile: {self._selected_profile.label if self._selected_profile else 'Not selected'}"
        )
        self.query_one("#summary-hardware", Static).update(
            f"Hardware: {self._selected_hardware.label if self._selected_hardware else 'Not selected'}"
        )
        self.query_one("#summary-storage", Static).update(
            f"Storage: {self._selected_storage.display_name if self._selected_storage else 'Not selected'}"
        )
        self.query_one("#summary-hostname", Static).update(
            f"Hostname: {self._config.get('hostname', 'Not set')}"
        )

        # Enable provision button if all required selections are made
        can_provision = all(
            [
                self._selected_profile,
                self._selected_hardware,
                self._selected_storage,
                self._config.get("hostname"),
            ]
        )
        self.query_one("#btn-provision", Button).disabled = not can_provision

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-cancel":
            self.app.pop_screen()
        elif event.button.id == "btn-provision":
            await self._start_provisioning()
        elif event.button.id == "abort-provision":
            await self._handle_abort_or_close()

    async def _start_provisioning(self) -> None:
        """Start the provisioning process."""
        # Validate configuration
        config_form = self.query_one("#config-form", ConfigForm)
        is_valid, _errors = config_form.validate()

        if not is_valid:
            # Show error notification (would use notify() in real implementation)
            self.app.bell()
            return

        # Validate storage is not mounted
        if self._selected_storage and self._selected_storage.mounted:
            # Show error notification
            self.app.bell()
            return

        # Hide selection panel, show progress panel
        self.query_one("#selection-panel").add_class("hidden")
        self.query_one("#progress-container").add_class("visible")

        # Clear progress panel
        progress_panel = self.query_one("#progress-panel", ProgressPanel)
        progress_panel.clear_log()

        # Start provisioning worker
        self._provisioning_worker = self.run_worker(self._provision_worker(), exclusive=True)

    async def _provision_worker(self) -> None:
        """Worker method that runs provisioning."""
        progress_panel = self.query_one("#progress-panel", ProgressPanel)

        def progress_callback(message: str) -> None:
            """Callback for progress updates."""
            progress_panel.append_log(message)

        # Run provisioning
        result = await provision_device(
            profile=self._selected_profile,  # type: ignore
            hardware=self._selected_hardware,  # type: ignore
            storage=self._selected_storage,  # type: ignore
            config=self._config,
            progress_callback=progress_callback,
            mock=True,  # Use mock provisioning for now
        )

        # Update progress panel with result
        progress_panel.set_complete(result.success)

    async def _handle_abort_or_close(self) -> None:
        """Handle abort/close button in progress panel."""
        progress_panel = self.query_one("#progress-panel", ProgressPanel)

        if progress_panel.is_complete:
            # Close the progress panel and return to selection
            self.query_one("#progress-container").remove_class("visible")
            self.query_one("#selection-panel").remove_class("hidden")
        else:
            # Abort provisioning (would implement abort logic)
            if self._provisioning_worker:
                self._provisioning_worker.cancel()
            self.query_one("#progress-container").remove_class("visible")
            self.query_one("#selection-panel").remove_class("hidden")
