"""Storage picker widget."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.message import Message
from textual.widgets import Button, DataTable, Static

from styrened.tui.services.storage import StorageDevice


class StoragePicker(Container):
    """Widget for selecting storage device.

    Displays detected storage devices in a table with refresh capability.
    """

    DEFAULT_CSS = """
    StoragePicker {
        height: auto;
        border: solid $primary;
        padding: 1;
    }

    StoragePicker .header {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
    }

    StoragePicker .title {
        color: $accent;
        text-style: bold;
        width: 1fr;
    }

    StoragePicker Button {
        width: auto;
        margin-left: 1;
    }

    StoragePicker DataTable {
        height: 10;
    }

    StoragePicker .warning {
        color: $warning;
        margin-top: 1;
    }
    """

    class Changed(Message):
        """Posted when storage selection changes."""

        def __init__(self, storage: "StorageDevice | None") -> None:
            super().__init__()
            self.storage = storage

    class RefreshRequested(Message):
        """Posted when refresh button is clicked."""

        pass

    def __init__(
        self,
        devices: list[StorageDevice],
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize storage picker.

        Args:
            devices: List of detected storage devices.
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self.devices = devices
        self._selected_storage: StorageDevice | None = None

    def compose(self) -> ComposeResult:
        """Compose the storage picker UI."""
        with Container(classes="header"):
            yield Static("SELECT STORAGE DEVICE", classes="title")
            yield Button("Refresh", id="refresh-storage", variant="primary")

        table: DataTable[str] = DataTable(id="storage-table", cursor_type="row")
        table.add_columns("Device", "Size", "Type", "Status", "Label")
        yield table

        yield Static(
            "⚠ WARNING: All data on selected device will be erased!",
            classes="warning",
        )

    def on_mount(self) -> None:
        """Populate table when widget is mounted."""
        self._populate_table()

    def _populate_table(self) -> None:
        """Populate the storage device table."""
        table = self.query_one("#storage-table", DataTable)
        table.clear()

        for device in self.devices:
            status = "Mounted" if device.mounted else "Available"
            label = device.label or "-"
            table.add_row(
                device.device,
                device.display_size,
                device.type.upper(),
                status,
                label,
                key=device.device,
            )

    def update_devices(self, devices: list[StorageDevice]) -> None:
        """Update the list of devices and refresh table.

        Args:
            devices: New list of storage devices.
        """
        self.devices = devices
        self._selected_storage = None
        self._populate_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the table."""
        device_path = str(event.row_key.value)
        self._selected_storage = next(
            (d for d in self.devices if d.device == device_path), None
        )
        self.post_message(self.Changed(self._selected_storage))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "refresh-storage":
            self.post_message(self.RefreshRequested())

    @property
    def selected_storage(self) -> "StorageDevice | None":
        """Get currently selected storage device."""
        return self._selected_storage
