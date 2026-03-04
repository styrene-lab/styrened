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

    def __init__(self, url: str, link_fields: str = "") -> None:
        self.url = url
        self.link_fields = link_fields
        super().__init__()


class _FieldClicked(Message):
    """Posted when a form field is clicked for editing."""

    def __init__(self, field_name: str, current_value: str) -> None:
        self.field_name = field_name
        self.current_value = current_value
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

    def action_submit_form(self, url: str, fields: str) -> None:
        """Handle @click action from a form submit link."""
        self.post_message(_LinkClicked(url, link_fields=fields))

    def action_edit_field(self, field_name: str, current_value: str) -> None:
        """Handle @click action on a form field."""
        self.post_message(_FieldClicked(field_name, current_value))


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
        Binding("s", "save_site", "Save Site", show=True),
        Binding("c", "crawl_site", "Crawl", show=True),
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
        self._form_fields: dict[str, str] = {}  # field_name -> current_value

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
                    # Reset form fields on new page load
                    self._form_fields = {}
                    rendered = render_to_rich(elements, form_state=self._form_fields)

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

            elif status in ("path_not_found", "timeout", "link_failed", "not_found", "error"):
                # Check for cached fallback from daemon
                cached_content = result.get("cached_content")
                cached_at = result.get("cached_at")

                if cached_content and cached_at:
                    # Show cached content with timestamp indicator
                    self._show_cached_page(
                        path, cached_content, cached_at,
                        error_detail or f"Live fetch failed ({status})"
                    )
                else:
                    error_messages = {
                        "path_not_found": "Path not found — node may be offline or unreachable",
                        "timeout": "Request timed out",
                        "link_failed": "Failed to establish link to node",
                        "not_found": f"Page not found: {path}",
                        "error": "Page fetch failed — check daemon logs for details",
                    }
                    self._set_error(
                        error_detail or error_messages.get(status, f"Unexpected: {status}")
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

    def _show_cached_page(
        self, path: str, content: str, cached_at: float, error_reason: str
    ) -> None:
        """Display cached page content with a staleness indicator.

        Shows the last successfully fetched version of a page when
        the live fetch fails, with a banner explaining the situation.

        Args:
            path: Page path.
            content: Cached micron content.
            cached_at: Unix timestamp of when the page was cached.
            error_reason: Why the live fetch failed.
        """
        import time as _time

        # Format cache age
        age_seconds = _time.time() - cached_at
        if age_seconds < 60:
            age_str = f"{int(age_seconds)}s ago"
        elif age_seconds < 3600:
            age_str = f"{int(age_seconds / 60)}m ago"
        elif age_seconds < 86400:
            age_str = f"{int(age_seconds / 3600)}h ago"
        else:
            age_str = f"{int(age_seconds / 86400)}d ago"

        # Render cached content
        elements = parse_micron(content)
        self._form_fields = {}
        rendered = render_to_rich(elements, form_state=self._form_fields)

        # Prepend cache banner
        banner = (
            f"[bold yellow]⚠ Cached page[/bold yellow] [dim]({age_str})[/dim]\n"
            f"[dim]{error_reason} — showing last cached version[/dim]\n"
            f"[dim]Press F5 to retry live fetch[/dim]\n\n"
        )

        self._page_content = content
        self.current_path = path

        try:
            body = self.query_one("#page-body", _PageBody)
            body.update(banner + rendered)
            body.remove_class("placeholder-text")
        except Exception:
            pass

        self._set_status(f"cached {age_str}")

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

    def action_save_site(self) -> None:
        """Save this node for periodic background crawling and caching."""
        self.run_worker(self._do_save_site(), exclusive=True, group="page-save")

    async def _do_save_site(self) -> None:
        """Save site via IPC."""
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Requires daemon mode", severity="error")
            return
        try:
            # Get display name from URL bar
            display_name = self.destination_hash[:16]
            await bridge.page_save_site(
                destination_hash=self.destination_hash,
                display_name=display_name,
            )
            self.notify(f"Site saved — will refresh periodically", severity="information")
        except Exception as e:
            self.notify(f"Failed to save site: {e}", severity="error")

    def action_crawl_site(self) -> None:
        """Crawl and cache all reachable pages from this node."""
        self.run_worker(self._do_crawl_site(), exclusive=True, group="page-crawl")

    async def _do_crawl_site(self) -> None:
        """Crawl site via IPC."""
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Requires daemon mode", severity="error")
            return
        try:
            self.notify("Crawling site...", severity="information")
            self._set_status("Crawling...")
            pages = await bridge.page_crawl_site(
                destination_hash=self.destination_hash,
            )
            self.notify(f"Cached {pages} pages", severity="information")
            self._set_status(f"Crawled {pages} pages")
        except Exception as e:
            self.notify(f"Crawl failed: {e}", severity="error")

    def on__field_clicked(self, message: _FieldClicked) -> None:
        """Handle form field click — open input dialog."""
        from textual.screen import ModalScreen
        from textual.widgets import Input

        field_name = message.field_name
        current_value = message.current_value

        class _FieldInputScreen(ModalScreen[str | None]):
            """Modal for editing a form field value."""

            DEFAULT_CSS = """
            _FieldInputScreen {
                align: center middle;
            }
            #field-input-container {
                width: 60;
                height: auto;
                max-height: 10;
                border: thick $accent;
                background: $surface;
                padding: 1 2;
            }
            #field-label {
                margin-bottom: 1;
            }
            """

            def compose(self) -> ComposeResult:
                with Vertical(id="field-input-container"):
                    yield Static(f"  {field_name}:", id="field-label")
                    yield Input(
                        value=current_value,
                        placeholder=f"Enter {field_name}...",
                        id="field-input",
                        password=(field_name.lower() == "password"),
                    )

            def on_input_submitted(self, event: Input.Submitted) -> None:
                self.dismiss(event.value)

            def key_escape(self) -> None:
                self.dismiss(None)

        async def _handle_result(result: str | None) -> None:
            if result is not None:
                self._form_fields[field_name] = result
                # Re-render page with updated form state
                self._rerender_page()

        self.app.push_screen(_FieldInputScreen(), _handle_result)

    def _rerender_page(self) -> None:
        """Re-render the current page content with updated form state."""
        if not self._page_content:
            return
        elements = parse_micron(self._page_content)
        rendered = render_to_rich(elements, form_state=self._form_fields)
        try:
            body = self.query_one("#page-body", _PageBody)
            body.update(rendered)
        except Exception:
            pass

    def on__link_clicked(self, message: _LinkClicked) -> None:
        """Handle link click from page body.

        NomadNet link URL formats:
        - ``/page/path``              — same-node absolute path
        - ``path.mu``                 — same-node relative path
        - ``:/page/path``             — same-node absolute (colon = self)
        - ``:path.mu``                — same-node relative (colon = self)
        - ``dest_hash:/page/path``    — cross-node reference

        If the link has form fields, collect values and submit as form_data.
        """
        url = message.url.strip()
        if not url:
            return

        # If link has form fields, collect and submit as form data
        form_data: dict[str, str] | None = None
        if message.link_fields:
            form_data = {}
            for field_name in message.link_fields.split("|"):
                field_name = field_name.strip()
                if field_name:
                    form_data[field_name] = self._form_fields.get(field_name, "")

        if url.startswith(":"):
            path = url[1:]
            if path:
                self._navigate_with_form(path, form_data)
            return
        if ":" in url and not url.startswith("/"):
            self.notify("Cross-node links not yet supported", severity="warning")
            return
        self._navigate_with_form(url, form_data)

    def _navigate_with_form(self, path: str, form_data: dict[str, str] | None = None) -> None:
        """Navigate to a path, optionally submitting form data."""
        if form_data:
            if self.current_path:
                self._history.append(self.current_path)
            self.run_worker(self._load_page_with_form(path, form_data), exclusive=True)
        else:
            self.navigate(path)

    async def _load_page_with_form(self, path: str, form_data: dict[str, str]) -> None:
        """Fetch a page with form data submission."""
        bridge = self._ipc_bridge
        if bridge is None:
            self._set_error("Page browsing requires daemon mode")
            return

        self.loading = True
        self._update_url_bar(path)
        self._set_status("Submitting...")

        try:
            result = await bridge.fetch_page(
                destination_hash=self.destination_hash,
                path=path,
                form_data=form_data,
                timeout=30.0,
            )

            status = result.get("status", "error")
            if status == "ok":
                content = result.get("content", "")
                transfer_time = result.get("transfer_time", 0.0)
                content_length = result.get("content_length", 0)

                elements = parse_micron(content)
                self._form_fields = {}  # Reset form for new page
                rendered = render_to_rich(elements, form_state=self._form_fields)

                self._page_content = content
                self.current_path = path

                try:
                    body = self.query_one("#page-body", _PageBody)
                    body.update(rendered)
                    body.remove_class("placeholder-text")
                except Exception:
                    pass

                if content_length > 1024:
                    size_str = f"{content_length / 1024:.1f}KB"
                else:
                    size_str = f"{content_length}B"
                self._set_status(f"{size_str} in {transfer_time:.1f}s")
            else:
                error_detail = result.get("error_message", "")
                self._set_error(error_detail or f"Form submission failed: {status}")
        except Exception as e:
            logger.error(f"Form submission failed: {e}")
            self._set_error(f"Form submission failed: {e}")
        finally:
            self.loading = False

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
