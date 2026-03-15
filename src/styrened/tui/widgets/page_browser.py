"""Page browser widget for NomadNet, HTTPS, and I2P page viewing.

Embeddable widget that fetches and displays pages via IPCBridge.
Supports multiple transports per node (NomadNet/I2P/HTTPS) with
content-type-aware rendering (micron native, html2text, plaintext).

Features:
- URL bar showing current destination:path or explicit URL
- Scrollable content area with rendered micron or HTML content
- Content-type-aware renderer dispatch (micron → native, HTML → html2text)
- Transport selector (T key) to cycle NomadNet/I2P/HTTPS for multi-transport nodes
- Browser delegation (O key) to open current page in system browser
- Back navigation with history stack
- Reload current page
- Link click navigation (works for both micron and html2text links)
- Status bar with transfer time, content size, and content type indicator
"""
from __future__ import annotations

import logging
import os
import urllib.parse
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from rich.console import RenderableType

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from styrened.tui.lifecycle import WidgetResourceScope
from styrened.tui.widgets.highlighted_panel import get_color_cascade
from styrened.tui.widgets.html_renderer import ContentKind, detect_content_type, render_html_to_rich
from styrened.tui.widgets.micron_parser import parse_micron, render_to_rich
from styrened.tui.widgets.page_renderers import render_structured_page

logger = logging.getLogger(__name__)


class Transport(Enum):
    """Available page transport types for a node."""

    NOMADNET = auto()
    I2P = auto()
    HTTPS = auto()


# Content-type indicator for URL bar
_CONTENT_INDICATORS: dict[ContentKind, str] = {
    ContentKind.MICRON: "📄 micron",
    ContentKind.HTML: "🌐 HTML",
    ContentKind.PLAIN: "📝 text",
}

# Transport labels for status display
_TRANSPORT_LABELS: dict[Transport, str] = {
    Transport.NOMADNET: "NomadNet",
    Transport.I2P: "I2P",
    Transport.HTTPS: "HTTPS",
}


def _is_headless() -> bool:
    """Detect if running in a headless environment (no browser available).

    Checks for SSH session without display server — common on edge devices.
    """
    has_display = bool(
        os.environ.get("DISPLAY")
        or os.environ.get("WAYLAND_DISPLAY")
        or os.environ.get("BROWSER")
    )
    is_ssh = bool(os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_CLIENT"))
    # macOS always has a browser available (even in SSH, `open` works)
    is_macos = os.uname().sysname == "Darwin"
    if is_macos:
        return False
    return is_ssh and not has_display


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
        Binding("o", "open_in_browser", "Browser", show=True),
        Binding("t", "cycle_transport", "Transport", show=True),
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
        destination_hash: str = "",
        initial_path: str = "/page/index.mu",
        external_url: str = "",
        **kwargs: Any,
    ) -> None:
        """Initialize page browser widget.

        Args:
            destination_hash: Hex-encoded destination hash of the NomadNet node.
            initial_path: Initial page path to load.
            external_url: Optional explicit HTTP(S)/I2P URL.
            **kwargs: Additional widget arguments.
        """
        super().__init__(**kwargs)
        self.destination_hash = destination_hash
        self._initial_path = initial_path
        self._external_url = external_url
        self._history: list[str] = []
        self._page_content: str = ""
        self._form_fields: dict[str, str] = {}  # field_name -> current_value
        self._mesh_device: Any | None = None  # MeshDevice for transport selector
        self._active_transport: Transport | None = None
        self._last_content_kind: ContentKind = ContentKind.MICRON
        self._page_bridge: Any | None = None
        self._resources = WidgetResourceScope(self, owner_logger=logger)

    @property
    def _ipc_bridge(self) -> Any | None:
        """Get the app's shared control-plane IPC bridge."""
        try:
            return self.app.services.bridge
        except Exception:
            return None

    async def _get_page_bridge(self) -> Any | None:
        """Get or lazily create the long-running page-browsing IPC lane."""
        if self._page_bridge is not None:
            return self._page_bridge

        shared_bridge = self._ipc_bridge
        if shared_bridge is None:
            return None

        page_bridge = shared_bridge
        spawn_lane = getattr(shared_bridge, "spawn_lane", None)
        if callable(spawn_lane):
            page_bridge = spawn_lane("execution")

        if page_bridge is not shared_bridge:
            connected = getattr(page_bridge, "connected", False)
            if not connected:
                ok = await page_bridge.connect()
                if not ok:
                    return None

        self._page_bridge = self._resources.adopt_auxiliary_lane(
            "_page_bridge",
            page_bridge,
            shared_lane=shared_bridge,
        )
        return self._page_bridge

    def _run_async_worker(
        self,
        fn: Any,
        *args: Any,
        **worker_kwargs: Any,
    ) -> None:
        """Schedule async work via the shared widget resource scope.

        Workers are tracked so they are cancelled before the auxiliary IPC
        lane is disconnected on teardown.
        """
        self._resources.own_worker(self._resources.run_worker(fn, *args, **worker_kwargs))

    @property
    def _is_external_mode(self) -> bool:
        return bool(self._external_url)

    def set_mesh_device(self, device: Any) -> None:
        """Set the MeshDevice for transport selector.

        Called by ExplorationScreen/ExchangeScreen when a node is selected.
        Determines available transports from the device's declared endpoints.

        Args:
            device: MeshDevice instance with endpoint fields.
        """
        self._mesh_device = device
        transports = self._get_available_transports()
        if transports and self._active_transport not in transports:
            self._active_transport = transports[0]

    def _get_available_transports(self) -> list[Transport]:
        """Get transports declared by the current node."""
        if self._mesh_device is None:
            return []
        transports: list[Transport] = []
        if getattr(self._mesh_device, "nomadnet_destination_hash", None):
            transports.append(Transport.NOMADNET)
        if getattr(self._mesh_device, "b32_address", None):
            transports.append(Transport.I2P)
        if getattr(self._mesh_device, "web_url", None):
            transports.append(Transport.HTTPS)
        return transports

    def _display_location(self, path_or_url: str | None = None) -> str:
        target = path_or_url or self._external_url or self._initial_path
        indicator = _CONTENT_INDICATORS.get(self._last_content_kind, "")
        transport_label = ""
        if self._active_transport:
            transports = self._get_available_transports()
            if len(transports) > 1:
                transport_label = f"  T: {_TRANSPORT_LABELS[self._active_transport]}"
        suffix = f"  {indicator}{transport_label}" if indicator else ""
        if self._is_external_mode:
            return f"  {target}{suffix}"
        return f"  {self.destination_hash[:16]}...:{target}{suffix}"

    def compose(self) -> ComposeResult:
        """Compose widget layout."""
        with Vertical():
            yield Static(
                self._display_location(),
                id="page-url-bar",
            )
            with VerticalScroll(id="page-content"):
                yield _PageBody("Loading...", id="page-body", classes="placeholder-text")
            yield Static("", id="page-status")

    def on_mount(self) -> None:
        """Load initial page on mount.

        Skipped when both ``destination_hash`` and ``_external_url`` are empty
        so that an inline browser widget constructed without a target (e.g. the
        Pages tab placeholder in ExplorationScreen) doesn't fire a spurious IPC
        call on every screen mount.  The caller is expected to invoke
        :meth:`set_destination` or :meth:`set_external_url` to trigger the
        first load.
        """
        if not self.destination_hash and not self._external_url:
            return  # deferred — waiting for set_destination() / set_external_url()
        target = self._external_url or self._initial_path
        self._run_async_worker(self._load_page, target, exclusive=True)

    def on_unmount(self) -> None:
        """Cancel in-flight workers and tear down the dedicated page-browsing IPC lane.

        Worker cancellation happens before lane disconnect via
        ``WidgetResourceScope.release()``, which drains tracked workers first.
        If the lane was never created (``_page_bridge is None``) the call is a
        no-op — both the workers list and the auxiliary-lane registry will be
        empty.
        """
        self._resources.release()

    async def _load_page(self, path: str) -> None:
        """Fetch and render a page.

        Args:
            path: Page path to fetch.
        """
        bridge = await self._get_page_bridge()
        if bridge is None:
            self._set_error("Page browsing requires daemon mode")
            return

        self.loading = True
        self._update_url_bar(path)
        self._set_status("Loading...")

        try:
            if self._is_external_mode:
                result = await bridge.fetch_page_url(
                    url=path,
                    timeout=30.0,
                )
            else:
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
                content_type = result.get("content_type")

                # Detect content type unconditionally so _last_content_kind
                # is always set (even when the structured renderer is used).
                kind = detect_content_type(content, content_type)
                self._last_content_kind = kind

                # Try structured data rendering first
                structured_data = result.get("structured_data")
                page_metadata = result.get("page_metadata")
                rendered: RenderableType | None = None

                if structured_data and page_metadata:
                    page_type = page_metadata.get("page_type", "")
                    rendered = render_structured_page(page_type, structured_data)

                # Content-type-aware rendering dispatch (fallback when no structured render)
                if rendered is None:
                    if kind == ContentKind.HTML:
                        rendered = render_html_to_rich(content)
                    else:
                        # Micron or plain text — use existing parser
                        elements = parse_micron(content)
                        # Reset form fields on new page load
                        self._form_fields = {}
                        rendered = render_to_rich(elements, form_state=self._form_fields)

                self._page_content = content
                self.current_path = path

                # Update display
                try:
                    body = self.query_one("#page-body", _PageBody)
                    if rendered is not None:
                        body.update(rendered)
                    body.remove_class("placeholder-text")
                except Exception:
                    pass

                # Format size
                if content_length > 1024:
                    size_str = f"{content_length / 1024:.1f}KB"
                else:
                    size_str = f"{content_length}B"

                kind_label = _CONTENT_INDICATORS.get(self._last_content_kind, "")
                self._set_status(f"{size_str} in {transfer_time:.1f}s  {kind_label}")
                self._update_url_bar(path)

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
            # Try cache fallback on IPC-level failures too (NomadNet cache only)
            if bridge is not None and not self._is_external_mode:
                try:
                    cached = await bridge.page_get_cached(
                        destination_hash=self.destination_hash,
                        path=path,
                    )
                    if cached and cached.get("found"):
                        self._show_cached_page(
                            path, cached["content"], cached["fetched_at"],
                            f"Connection failed: {e}"
                        )
                    else:
                        self._set_error(f"Failed to load page: {e}")
                except Exception:
                    self._set_error(f"Failed to load page: {e}")
            else:
                self._set_error(f"Failed to load page: {e}")

        finally:
            self.loading = False

    def _update_url_bar(self, path: str) -> None:
        """Update the URL bar display."""
        try:
            url_bar = self.query_one("#page-url-bar", Static)
            url_bar.update(self._display_location(path))
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
            body.update(f"[{get_color_cascade().color_danger} bold]{message}[/]")
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
            f"[{get_color_cascade().color_warning} bold]⚠ Cached page[/] [{get_color_cascade().dim}]({age_str})[/]\n"
            f"[{get_color_cascade().dim}]{error_reason} — showing last cached version[/]\n"
            f"[{get_color_cascade().dim}]Press F5 to retry live fetch[/]\n\n"
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
        self._run_async_worker(self._load_page, previous_path, exclusive=True)

    def action_reload(self) -> None:
        """Reload the current page."""
        self._run_async_worker(self._load_page, self.current_path, exclusive=True)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Hide the open_in_browser action in headless environments."""
        if action == "open_in_browser":
            return False if _is_headless() else True
        return None

    def action_open_in_browser(self) -> None:
        """Open the current page in the system browser.

        For .i2p URLs, constructs a proxy URL through localhost:4444.
        Hidden/no-op when in a headless environment.
        """
        if _is_headless():
            self.notify("No browser available (headless environment)", severity="warning")
            return

        url = self._external_url or self.current_path
        if not url:
            return

        # NomadNet paths have no browser-accessible equivalent
        if url.startswith("/"):
            self.notify("NomadNet pages are only viewable in the TUI", severity="information")
            return

        # .i2p URLs must be proxied through the local I2P HTTP proxy
        if ".i2p" in url:
            proxy_url = f"http://localhost:4444/{url}"
            try:
                self.app.open_url(proxy_url)
            except Exception as e:
                self.notify(f"Failed to open browser: {e}", severity="error")
            return

        # HTTPS and other clear URLs pass through directly
        try:
            self.app.open_url(url)
        except Exception as e:
            self.notify(f"Failed to open browser: {e}", severity="error")

    def action_cycle_transport(self) -> None:
        """Cycle through available transports for the current node.

        Only available when the selected node has multiple declared endpoints.
        Clears history and re-fetches from the root path of the new transport.
        """
        transports = self._get_available_transports()
        if len(transports) <= 1:
            if not transports:
                self.notify("No transport information available", severity="information")
            else:
                self.notify(
                    f"Only {_TRANSPORT_LABELS[transports[0]]} transport available",
                    severity="information",
                )
            return

        # Cycle to next transport
        current_idx = (
            transports.index(self._active_transport)
            if self._active_transport in transports
            else -1
        )
        next_idx = (current_idx + 1) % len(transports)
        self._active_transport = transports[next_idx]

        # Clear history and load root of new transport
        self._history.clear()
        label = _TRANSPORT_LABELS[self._active_transport]

        if self._active_transport == Transport.NOMADNET:
            # Switch to NomadNet mode — set fields directly, one worker
            nomadnet_dest = getattr(self._mesh_device, "nomadnet_destination_hash", "")
            self._external_url = ""
            self.destination_hash = nomadnet_dest
            self.notify(f"Switched to {label} transport")
            self._run_async_worker(self._load_page, "/page/index.mu", exclusive=True)

        elif self._active_transport == Transport.I2P:
            # Switch to I2P mode — set fields directly, one worker
            b32 = getattr(self._mesh_device, "b32_address", "")
            url = f"http://{b32}/"
            self._external_url = url
            self.destination_hash = ""
            self.notify(f"Switched to {label} transport")
            self._run_async_worker(self._load_page, url, exclusive=True)

        elif self._active_transport == Transport.HTTPS:
            # Switch to HTTPS mode — set fields directly, one worker
            web_url = getattr(self._mesh_device, "web_url", "")
            self._external_url = web_url
            self.destination_hash = ""
            self.notify(f"Switched to {label} transport")
            self._run_async_worker(self._load_page, web_url, exclusive=True)

    def action_focus_url(self) -> None:
        """Open a URL entry modal for manual navigation.

        Accepts NomadNet destination hashes, .i2p hostnames, and http(s):// URLs.
        Routes to the appropriate transport based on the entered value.
        """
        from textual.screen import ModalScreen
        from textual.widgets import Input

        current = self.current_path or ""

        class _UrlInputScreen(ModalScreen[str | None]):
            """Modal for entering a URL or NomadNet destination."""

            DEFAULT_CSS = """
            _UrlInputScreen {
                align: center middle;
            }
            #url-input-container {
                width: 72;
                height: auto;
                border: thick $accent;
                background: $surface;
                padding: 1 2;
            }
            #url-label {
                margin-bottom: 1;
            }
            #url-hint {
                margin-top: 1;
                color: $text-muted;
            }
            """

            def compose(self) -> ComposeResult:
                with Vertical(id="url-input-container"):
                    yield Static("  Navigate to:", id="url-label")
                    yield Input(
                        value=current,
                        placeholder="dest_hash, hostname.i2p, or https://...",
                        id="url-input",
                    )
                    yield Static(
                        "  [dim]NomadNet: hex hash  ·  I2P: *.i2p  ·  Web: https://[/]",
                        id="url-hint",
                    )

            def on_mount(self) -> None:
                self.query_one("#url-input", Input).focus()

            def on_input_submitted(self, event: Input.Submitted) -> None:
                self.dismiss(event.value.strip() or None)

            def key_escape(self) -> None:
                self.dismiss(None)

        def _handle_url(result: str | None) -> None:
            if not result:
                return
            # Route based on URL shape
            if result.endswith(".i2p") or result.startswith("http://") or result.startswith("https://"):
                # External URL — switch to external mode and navigate
                self.set_external_url(result)
                self._run_async_worker(self._load_page, result, exclusive=True, group="page-load")
            else:
                # Treat as NomadNet destination hash or path
                if self._is_external_mode:
                    self.set_external_url("")  # exit external mode
                self._run_async_worker(self._load_page, result, exclusive=True, group="page-load")

        self.app.push_screen(_UrlInputScreen(), _handle_url)

    def action_save_site(self) -> None:
        """Save this node for periodic background crawling and caching."""
        if self._is_external_mode:
            self.notify("Save Site is only available for NomadNet nodes", severity="warning")
            return
        self._run_async_worker(self._do_save_site, exclusive=True, group="page-save")

    async def _do_save_site(self) -> None:
        """Save site via IPC."""
        bridge = await self._get_page_bridge()
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
            self.notify("Site saved — will refresh periodically", severity="information")
        except Exception as e:
            self.notify(f"Failed to save site: {e}", severity="error")

    def action_crawl_site(self) -> None:
        """Crawl and cache all reachable pages from this node."""
        if self._is_external_mode:
            self.notify("Crawl is only available for NomadNet nodes", severity="warning")
            return
        self._run_async_worker(self._do_crawl_site, exclusive=True, group="page-crawl")

    async def _do_crawl_site(self) -> None:
        """Crawl site via IPC."""
        bridge = await self._get_page_bridge()
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

        if self._is_external_mode:
            if message.link_fields:
                self.notify("Form submission is only supported for NomadNet pages", severity="warning")
                return
            self.navigate(urllib.parse.urljoin(self.current_path, url))
            return

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
            self._run_async_worker(self._load_page_with_form, path, form_data, exclusive=True)
        else:
            self.navigate(path)

    async def _load_page_with_form(self, path: str, form_data: dict[str, str]) -> None:
        """Fetch a page with form data submission."""
        if self._is_external_mode:
            self._set_error("Form submission is only supported for NomadNet pages")
            return

        bridge = await self._get_page_bridge()
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
        self._external_url = ""
        self._history.clear()
        self.current_path = "/page/index.mu"
        self._run_async_worker(self._load_page, "/page/index.mu", exclusive=True)

    def set_external_url(self, url: str) -> None:
        """Change target to an explicit external URL and reload it."""
        self.destination_hash = ""
        self._external_url = url
        self._history.clear()
        self.current_path = url
        self._run_async_worker(self._load_page, url, exclusive=True)

    def navigate(self, path: str) -> None:
        """Navigate to a new page path.

        Pushes current path to history and loads the new path.

        Args:
            path: Page path to navigate to.
        """
        if self.current_path:
            self._history.append(self.current_path)
        self._run_async_worker(self._load_page, path, exclusive=True)
