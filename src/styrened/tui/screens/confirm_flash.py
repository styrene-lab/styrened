from __future__ import annotations

"""Confirmation modal for destructive flash operations."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from styrened.tui.widgets.highlighted_panel import HighlightedPanel, get_color_cascade


class ConfirmFlash(ModalScreen[bool]):
    """Modal confirmation dialog for flash operations.

    Shows device info, target disk, and a destructive warning.
    Returns True on confirm, False on cancel/escape.
    """

    CSS = """
    ConfirmFlash {
        align: center middle;
    }

    #confirm-flash-container {
        width: 64;
        height: auto;
        max-height: 80%;
    }

    #confirm-flash-content {
        padding: 1 2;
    }

    #confirm-flash-warning {
        margin: 1 0;
        text-style: bold;
    }

    #confirm-flash-details {
        margin: 1 0;
    }

    .confirm-flash-row {
        height: auto;
    }

    .confirm-flash-label {
        width: 12;
        color: $panel;
    }

    .confirm-flash-value {
        width: 1fr;
    }

    #confirm-flash-actions {
        height: auto;
        margin-top: 1;
        align: center middle;
    }

    #confirm-flash-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        device_label: str,
        device_model: str,
        disk_path: str,
        disk_name: str,
        disk_size: str,
    ) -> None:
        super().__init__()
        self._device_label = device_label
        self._device_model = device_model
        self._disk_path = disk_path
        self._disk_name = disk_name
        self._disk_size = disk_size

    def compose(self) -> ComposeResult:
        cascade = get_color_cascade()

        with HighlightedPanel(title="CONFIRM FLASH", id="confirm-flash-container", classes="panel-alert"):
            with Vertical(id="confirm-flash-content"):
                yield Static(
                    f"[{cascade.bright} bold]ALL DATA ON THIS DEVICE WILL BE ERASED[/]",
                    id="confirm-flash-warning",
                )

                with Vertical(id="confirm-flash-details"):
                    with Horizontal(classes="confirm-flash-row"):
                        yield Static("Device:", classes="confirm-flash-label")
                        yield Static(
                            f"[{cascade.medium}]{self._device_label}[/] ({self._device_model})",
                            classes="confirm-flash-value",
                        )
                    with Horizontal(classes="confirm-flash-row"):
                        yield Static("Disk:", classes="confirm-flash-label")
                        yield Static(
                            f"[{cascade.medium}]{self._disk_path}[/]",
                            classes="confirm-flash-value",
                        )
                    with Horizontal(classes="confirm-flash-row"):
                        yield Static("Name:", classes="confirm-flash-label")
                        yield Static(
                            f"[{cascade.dim}]{self._disk_name}[/]",
                            classes="confirm-flash-value",
                        )
                    with Horizontal(classes="confirm-flash-row"):
                        yield Static("Size:", classes="confirm-flash-label")
                        yield Static(
                            f"[{cascade.dim}]{self._disk_size}[/]",
                            classes="confirm-flash-value",
                        )

                with Horizontal(id="confirm-flash-actions"):
                    yield Button(
                        "Confirm Flash",
                        id="btn-confirm-flash",
                        variant="error",
                    )
                    yield Button(
                        "Cancel",
                        id="btn-cancel-flash",
                        variant="default",
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm-flash":
            self.dismiss(True)
        elif event.button.id == "btn-cancel-flash":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
