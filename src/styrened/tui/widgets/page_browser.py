"""Page browser widget for NomadNet node page viewing.

Embeddable widget that fetches and displays NomadNet pages via IPCBridge.
Used in MeshDeviceDetailScreen's Pages tab for NomadNet nodes.

Features:
- URL bar showing current destination:path
- Scrollable content area with rendered micron markup
- Back navigation with history stack
- Reload current page
- Link click navigation (same-node page links)
- Status bar with transfer time and content size
"""

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from styrened.tui.widgets.micron_parser import parse_micron, render_to_rich
from styrened.tui.widgets.page_renderers import render_structured_page

logger = logging.getLogger(__name__)


class _LinkClicked(Message):
    """Posted when a micron link is clicked in the page body."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__()


class _PageBody(Static):
    """Static widget with micron link click handling.

    Renders Rich markup from the micron parser.  When the user clicks a
    ``[@click="navigate_link(...)"]`` span, the action dispatches here
    and we bubble a ``_LinkClicked`` message up to ``PageBrowserWidget``.
    """

    def action_navigate_link(self, url: str) -> None:
        """Handle @click action from micron link markup."""
        self.post_message(_LinkClicked(url))


class PageBrowserWidget(Widget):
    """Widget for browsing NomadNet node pages.

    Fetches pages via IPCBridge and renders micron markup content.

    Attributes:
        destination_hash: Hex-encoded destination hash of the NomadNet node.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("backspace", "go_back", "Back", show=True),
        Binding("f5", "reload", "Reload", show=True),
        Binding("u", "focus_url", "URL", show=True),
    ]

    loading: reactive[bool] = reactive(False)
    current_path: reactive[str] = reactive("/page/index.mu")
    status_text: reactive[str] = reactive("")

    DEFAULT_CSS = """
    PageBrowserWidget {
        height: 1fr;
    }
    """

    def __init__(
        self,
        destination_hash: str,
        initial_path: str = "/page/index.mu",
        **kwargs: Any,
    ) -> None:
        """Initialize page browser widget.

        Args:
            destination_hash: Hex-encoded destination hash of the NomadNet node.
            initial_path: Initial page path to load.
            **kwargs: Additional widget arguments.
        """
        super().__init__(**kwargs)
        self.destination_hash = destination_hash
        self._initial_path = initial_path
        self._history: list[str] = []
        self._page_content: str = ""

    @property
    def _ipc_bridge(self) -> Any | None:
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        """Compose widget layout."""
        with Vertical():
            yield Static(
                f"  {self.destination_hash[:16]}...:{self._initial_path}",
                id="page-url-bar",
            )
            with VerticalScroll(id="page-content"):
                yield _PageBody("Loading...", id="page-body", classes="placeholder-text")
            yield Static("", id="page-status")

    def on_mount(self) -> None:
        """Load initial page on mount."""
        self.run_worker(self._load_page(self._initial_path), exclusive=True)

    async def _load_page(self, path: str) -> None:
        """Fetch and render a page.

        Args:
            path: Page path to fetch.
        """
        bridge = self._ipc_bridge
        if bridge is None:
            self._set_error("Page browsing requires daemon mode")
            return

        self.loading = True
        self._update_url_bar(path)
        self._set_status("Loading...")

        try:
            result = await bridge.fetch_page(
                destination_hash=self.destination_hash,
                path=path,
                timeout=30.0,
            )

            status = result.get("status", "error")

            # Server-provided detail takes precedence over hardcoded messages
            error_detail = result.get("error_message", "")

            if status == "ok":
                content = result.get("content", "")
                transfer_time = result.get("transfer_time", 0.0)
                content_length = result.get("content_length", 0)

                # Try structured data rendering first
                structured_data = result.get("structured_data")
                page_metadata = result.get("page_metadata")
                rendered = None

                if structured_data and page_metadata:
                    page_type = page_metadata.get("page_type", "")
                    rendered = render_structured_page(page_type, structured_data)

                # Fall back to micron rendering
                if rendered is None:
                    elements = parse_micron(content)
                    rendered = render_to_rich(elements)

                self._page_content = content
                self.current_path = path

                # Update display
                try:
                    body = self.query_one("#page-body", _PageBody)
                    body.update(rendered)
                    body.remove_class("placeholder-text")
                except Exception:
                    pass

                # Format size
                if content_length > 1024:
                    size_str = f"{content_length / 1024:.1f}KB"
                else:
                    size_str = f"{content_length}B"

                self._set_status(f"{size_str} in {transfer_time:.1f}s")

            elif status == "path_not_found":
                self._set_error(
                    error_detail or "Path not found — node may be offline or unreachable"
                )
            elif status == "timeout":
                self._set_error(error_detail or "Request timed out")
            elif status == "link_failed":
                self._set_error(
                    error_detail or "Failed to establish link to node"
                )
            elif status == "not_found":
                self._set_error(error_detail or f"Page not found: {path}")
            elif status == "error":
                self._set_error(
                    error_detail or "Page fetch failed — check daemon logs for details"
                )
            else:
                self._set_error(
                    error_detail or f"Unexpected response status: {status}"
                )

        except Exception as e:
            logger.error(f"Failed to load page: {e}")
            self._set_error(f"Failed to load page: {e}")

        finally:
            self.loading = False

    def _update_url_bar(self, path: str) -> None:
        """Update the URL bar display."""
        try:
            url_bar = self.query_one("#page-url-bar", Static)
            url_bar.update(f"  {self.destination_hash[:16]}...:{path}")
        except Exception:
            pass

    def _set_status(self, text: str) -> None:
        """Update the status bar."""
        try:
            status = self.query_one("#page-status", Static)
            status.update(f" {text}")
        except Exception:
            pass

    def _set_error(self, message: str) -> None:
        """Display an error in the content area."""
        try:
            body = self.query_one("#page-body", _PageBody)
            body.update(f"[bold red]{message}[/bold red]")
            body.add_class("placeholder-text")
        except Exception:
            pass
        self._set_status("Error")

    def action_go_back(self) -> None:
        """Navigate back in history."""
        if not self._history:
            return

        previous_path = self._history.pop()
        self.run_worker(self._load_page(previous_path), exclusive=True)

    def action_reload(self) -> None:
        """Reload the current page."""
        self.run_worker(self._load_page(self.current_path), exclusive=True)

    def action_focus_url(self) -> None:
        """Focus URL bar for manual navigation (placeholder)."""
        self.notify("Manual URL entry coming soon", severity="information")

    def on__link_clicked(self, message: _LinkClicked) -> None:
        """Handle link click from page body.

        NomadNet link URL formats:
        - ``/page/path``              — same-node absolute path
        - ``path.mu``                 — same-node relative path
        - ``:/page/path``             — same-node absolute (colon = self)
        - ``:path.mu``                — same-node relative (colon = self)
        - ``dest_hash:/page/path``    — cross-node reference
        """
        url = message.url.strip()
        if not url:
            return
        if url.startswith(":"):
            # Same-node link (NomadNet convention: leading colon = self)
            path = url[1:]
            if path:
                self.navigate(path)
            return
        if ":" in url and not url.startswith("/"):
            # Cross-node reference (dest_hash:/page/path) — not yet supported
            self.notify("Cross-node links not yet supported", severity="warning")
            return
        self.navigate(url)

    def set_destination(self, destination_hash: str) -> None:
        """Change target node and reload index page.

        Args:
            destination_hash: Hex-encoded destination hash of the new NomadNet node.
        """
        self.destination_hash = destination_hash
        self._history.clear()
        self.current_path = "/page/index.mu"
        self.run_worker(self._load_page("/page/index.mu"), exclusive=True)

    def navigate(self, path: str) -> None:
        """Navigate to a new page path.

        Pushes current path to history and loads the new path.

        Args:
            path: Page path to navigate to.
        """
        if self.current_path:
            self._history.append(self.current_path)
        self.run_worker(self._load_page(path), exclusive=True)
