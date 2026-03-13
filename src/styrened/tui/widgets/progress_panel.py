"""Progress panel widget."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Button, RichLog, Static


class ProgressPanel(Container):
    """Widget for displaying provisioning progress.

    Shows a log of provisioning output with auto-scroll and abort capability.
    Uses RichLog for O(1) appends instead of rebuilding a string each time.
    """

    DEFAULT_CSS = """
    ProgressPanel {
        height: 100%;
        border: solid $accent;
        padding: 1;
    }

    ProgressPanel .header {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
    }

    ProgressPanel .title {
        color: $accent;
        text-style: bold;
        width: 1fr;
    }

    ProgressPanel Button {
        width: auto;
        margin-left: 1;
    }

    ProgressPanel RichLog {
        height: 1fr;
        border: solid $primary;
        padding: 1;
        background: $surface;
        color: $text;
    }

    ProgressPanel .status {
        color: $success;
        text-style: bold;
        margin-top: 1;
    }

    ProgressPanel .status-error {
        color: $error;
        text-style: bold;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Initialize progress panel.

        Args:
            name: Widget name.
            id: Widget ID.
            classes: CSS classes.
        """
        super().__init__(name=name, id=id, classes=classes)
        self._is_complete = False
        self._is_error = False

    def compose(self) -> ComposeResult:
        """Compose the progress panel UI."""
        with Container(classes="header"):
            yield Static("PROVISIONING PROGRESS", classes="title")
            yield Button("Abort", id="abort-provision", variant="error")

        yield RichLog(id="progress-log", highlight=False, markup=True, wrap=True)

        yield Static("", id="status-message")

    def append_log(self, message: str) -> None:
        """Append a message to the log.

        Uses RichLog.write() for O(1) appends with automatic scrolling.

        Args:
            message: Log message to append.
        """
        try:
            log = self.query_one("#progress-log", RichLog)
            log.write(message)
        except Exception:
            pass  # Widget not yet mounted

    def set_complete(self, success: bool = True) -> None:
        """Mark provisioning as complete.

        Args:
            success: Whether provisioning succeeded.
        """
        self._is_complete = True
        self._is_error = not success

        status = self.query_one("#status-message", Static)
        if success:
            status.update("✓ Provisioning completed successfully!")
            status.remove_class("status-error")
            status.add_class("status")
        else:
            status.update("✗ Provisioning failed!")
            status.remove_class("status")
            status.add_class("status-error")

        abort_button = self.query_one("#abort-provision", Button)
        abort_button.label = "Close"
        abort_button.variant = "primary"

    def clear_log(self) -> None:
        """Clear the log content."""
        try:
            log = self.query_one("#progress-log", RichLog)
            log.clear()
        except Exception:
            pass  # Widget not yet mounted

        status = self.query_one("#status-message", Static)
        status.update("")

        self._is_complete = False
        self._is_error = False

        abort_button = self.query_one("#abort-provision", Button)
        abort_button.label = "Abort"
        abort_button.variant = "error"

    @property
    def is_complete(self) -> bool:
        """Check if provisioning is complete."""
        return self._is_complete

    @property
    def is_error(self) -> bool:
        """Check if provisioning failed."""
        return self._is_error
