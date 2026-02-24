"""Device status widget for displaying RPC status responses."""

from datetime import datetime

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Static

from styrened.rpc.messages import StatusResponse


class DeviceStatusWidget(Static):
    """Widget for displaying device status from RPC response.

    Uses reactive properties to update display when status changes.
    Shows comprehensive system, network, and storage info organized
    in sections.

    Attributes:
        status: Current status response (or None if no data).
        loading: Whether status request is in progress.
        error: Error message to display (or None if no error).
    """

    status: reactive[StatusResponse | None] = reactive(None)
    loading: reactive[bool] = reactive(False)
    error: reactive[str | None] = reactive(None)
    last_updated: reactive[str | None] = reactive(None)

    def compose(self) -> ComposeResult:
        """Compose widget content based on current state."""
        # Priority: loading > error > status > no data
        if self.loading:
            yield Static("[dim]Fetching status...[/]", classes="status-loading")
        elif self.error:
            if self.last_updated:
                yield Static(
                    f"[dim]Updated: {self.last_updated}[/]",
                    classes="status-updated-ts",
                )
            yield Static(f"[red]{self.error}[/]", classes="status-error")
        elif self.status:
            yield from self._compose_status(self.status)
        else:
            yield Static(
                "[dim]Fetching status...[/]", classes="status-placeholder"
            )

    def _compose_status(self, s: StatusResponse) -> ComposeResult:
        """Compose the full status display from a StatusResponse."""
        # Updated timestamp
        if self.last_updated:
            yield Static(
                f"[dim]Updated: {self.last_updated}[/]",
                classes="status-updated-ts",
            )

        # -- System section --
        yield Static(
            "[bold]-- System ---------------------------------------------------------[/]",
            classes="status-section-header",
        )
        if s.hostname:
            yield Static(f"  [bold]Hostname:[/]  {s.hostname}", classes="status-field")

        # OS line: combine os_id + os_version + arch
        os_parts: list[str] = []
        if s.os_id:
            os_parts.append(s.os_id)
        if s.os_version:
            os_parts.append(s.os_version)
        if s.arch:
            os_parts.append(f"({s.arch})")
        if os_parts:
            yield Static(f"  [bold]OS:[/]        {' '.join(os_parts)}", classes="status-field")

        yield Static(f"  [bold]Uptime:[/]    {s.format_uptime()}", classes="status-field")

        if s.styrened_version:
            yield Static(
                f"  [bold]Styrened:[/]  {s.styrened_version}",
                classes="status-field",
            )

        if s.nixos_generation:
            yield Static(
                f"  [bold]NixOS Gen:[/] {s.nixos_generation}",
                classes="status-field",
            )

        # -- Network section --
        yield Static(
            "[bold]-- Network --------------------------------------------------------[/]",
            classes="status-section-header",
        )
        yield Static(f"  [bold]IP Address:[/] {s.ip}", classes="status-field")

        if s.services:
            yield Static(
                f"  [bold]Services:[/]   {', '.join(s.services)}",
                classes="status-field",
            )
        else:
            yield Static("  [bold]Services:[/]   [dim]none[/]", classes="status-field")

        # -- Storage section --
        yield Static(
            "[bold]-- Storage --------------------------------------------------------[/]",
            classes="status-section-header",
        )
        yield Static(
            f"  [bold]Disk:[/]  {s.format_disk_usage()}",
            classes="status-field",
        )

    def watch_status(self, status: StatusResponse | None) -> None:
        """React to status changes by re-composing widget."""
        if status is not None:
            self.last_updated = datetime.now().strftime("%H:%M:%S")
        if self.is_mounted:
            self._recompose()

    def watch_loading(self, loading: bool) -> None:
        """React to loading state changes."""
        if self.is_mounted:
            self._recompose()

    def watch_error(self, error: str | None) -> None:
        """React to error changes."""
        if self.is_mounted:
            self._recompose()

    def _recompose(self) -> None:
        """Remove children and re-compose with current state."""
        for child in list(self.children):
            child.remove()

        new_children = list(self.compose())
        if new_children:
            self.mount(*new_children)
