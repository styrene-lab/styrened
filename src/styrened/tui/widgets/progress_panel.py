"""Progress panel widget."""

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Button, Static


class ProgressPanel(Container):
    """Widget for displaying provisioning progress.

    Shows a log of provisioning output with auto-scroll and abort capability.
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

    ProgressPanel .log-container {
        height: 1fr;
        border: solid $primary;
        padding: 1;
        background: $surface;
    }

    ProgressPanel .log-line {
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
        self._log_content = ""

    def compose(self) -> ComposeResult:
        """Compose the progress panel UI."""
        with Container(classes="header"):
            yield Static("PROVISIONING PROGRESS", classes="title")
            yield Button("Abort", id="abort-provision", variant="error")

        with VerticalScroll(id="log-container", classes="log-container") as scroll:
            scroll.can_focus = False
            yield Static("", id="log-content")

        yield Static("", id="status-message")

    def append_log(self, message: str) -> None:
        """Append a message to the log.

        Args:
            message: Log message to append.
        """
        log_content = self.query_one("#log-content", Static)
        if self._log_content:
            self._log_content = f"{self._log_content}\n{message}"
        else:
            self._log_content = message
        log_content.update(self._log_content)

        # Auto-scroll to bottom
        log_container = self.query_one("#log-container", VerticalScroll)
        log_container.scroll_end(animate=False)

    def set_complete(self, success: bool = True) -> None:
        """Mark provisioning as complete.

        Args:
            success: Whether provisioning succeeded.
        """
        self._is_complete = True
        self._is_error = not success

        # Update status message
        status = self.query_one("#status-message", Static)
        if success:
            status.update("✓ Provisioning completed successfully!")
            status.remove_class("status-error")
            status.add_class("status")
        else:
            status.update("✗ Provisioning failed!")
            status.remove_class("status")
            status.add_class("status-error")

        # Change abort button to close
        abort_button = self.query_one("#abort-provision", Button)
        abort_button.label = "Close"
        abort_button.variant = "primary"

    def clear_log(self) -> None:
        """Clear the log content."""
        log_content = self.query_one("#log-content", Static)
        log_content.update("")

        status = self.query_one("#status-message", Static)
        status.update("")

        self._is_complete = False
        self._is_error = False

        # Reset abort button
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
