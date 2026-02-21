"""Device status widget for displaying RPC status responses."""

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from styrened.rpc.messages import StatusResponse


class DeviceStatusWidget(Static):
    """Widget for displaying device status from RPC response.

    Uses reactive properties to update display when status changes.

    Attributes:
        status: Current status response (or None if no data).
        loading: Whether status request is in progress.
        error: Error message to display (or None if no error).
    """

    status: reactive[StatusResponse | None] = reactive(None)
    loading: reactive[bool] = reactive(False)
    error: reactive[str | None] = reactive(None)

    def compose(self) -> ComposeResult:
        """Compose widget content based on current state."""
        # Priority: loading > error > status > no data
        if self.loading:
            yield Static("[dim]Requesting status...[/]", classes="status-loading")
        elif self.error:
            yield Static(f"[red]{self.error}[/]", classes="status-error")
        elif self.status:
            # Display status fields
            yield Static(f"[bold]Uptime:[/] {self.status.format_uptime()}", classes="status-field")
            yield Static(f"[bold]IP Address:[/] {self.status.ip}", classes="status-field")
            yield Static(
                f"[bold]Services:[/] {', '.join(self.status.services)}", classes="status-field"
            )
            yield Static(
                f"[bold]Disk Usage:[/] {self.status.format_disk_usage()}", classes="status-field"
            )
        else:
            yield Static(
                "[dim]No status data - press R to refresh[/]", classes="status-placeholder"
            )

    def watch_status(self, status: StatusResponse | None) -> None:
        """React to status changes by re-composing widget.

        Args:
            status: New status value (or None).
        """
        # Only recompose if widget is already mounted
        if self.is_mounted:
            self._recompose()

    def watch_loading(self, loading: bool) -> None:
        """React to loading state changes.

        Args:
            loading: New loading state.
        """
        # Only recompose if widget is already mounted
        if self.is_mounted:
            self._recompose()

    def watch_error(self, error: str | None) -> None:
        """React to error changes.

        Args:
            error: New error message (or None).
        """
        # Only recompose if widget is already mounted
        if self.is_mounted:
            self._recompose()

    def _recompose(self) -> None:
        """Remove children and re-compose with current state."""
        # Remove all current children
        for child in list(self.children):
            child.remove()

        # Re-compose with current state
        new_children = list(self.compose())
        if new_children:
            self.mount(*new_children)
