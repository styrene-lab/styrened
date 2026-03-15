"""ExchangeScreen — tabbed workspace consolidating Mail, Direct, Pages, Contacts.

Provides a single tabbed entry point for all communication workspaces.
Tabs:
  mail     — Async conversations (lifted from InboxScreen)
  direct   — Direct/live comms  (lifted from CommsScreen)
  pages    — NomadNet page browser (lifted from ExplorationScreen pages pane)
  contacts — Contact directory   (lifted from ContactsScreen)
"""

from __future__ import annotations

import datetime
import logging
from functools import partial
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static, Switch, TabbedContent, TabPane
from textual.worker import Worker, WorkerState

from styrened.models.mesh_device import DeviceType
from styrened.tui.lifecycle import ScreenContentHooks, ScreenContentHost
from styrened.tui.screens.exchange_tabs import ExchangeContactsTab, ExchangeDirectTab
from styrened.tui.screens.exploration import ReticumAnnounceTable
from styrened.tui.widgets.highlighted_panel import get_color_cascade
from styrened.ui_state import (
    ConversationScopeKind,
    MailIndexInputs,
    MailIndexState,
    MailThreadRecord,
    build_mail_index,
)

# Pages tab shows NomadNet nodes AND Styrene nodes that carry a NomadNet
# destination (e.g. the Styrene Community Hub).  The table accepts both
# device types; _refresh_pages_table pre-filters to the exact browsable set.
_PAGES_BROWSABLE_TYPES = frozenset({DeviceType.NOMADNET_NODE, DeviceType.STYRENE_NODE})
_PAGES_TYPES = _PAGES_BROWSABLE_TYPES  # backward-compat alias used in compose

logger = logging.getLogger(__name__)

_DELETE_CONFIRM_TIMEOUT = 3.0

TAB_MAIL = "mail"
TAB_DIRECT = "direct"
TAB_PAGES = "pages"
TAB_CONTACTS = "contacts"


def _format_timestamp(ts: float | int | None) -> str:
    """Format a Unix timestamp as a human-readable string."""
    if ts is None:
        return "-"

    dt = datetime.datetime.fromtimestamp(float(ts))
    now = datetime.datetime.now()
    delta = now - dt

    if delta.days == 0:
        return dt.strftime("%H:%M")
    elif delta.days < 7:
        return dt.strftime("%a %H:%M")
    elif dt.year == now.year:
        return dt.strftime("%b %d %H:%M")
    else:
        return dt.strftime("%Y-%m-%d")


class ExchangeScreen(Screen[None]):
    """Tabbed Exchange workspace — Mail / Direct / Pages / Contacts.

    Inherits from Screen[None] and accesses all services through
    ``self.app.services`` (TUIServices protocol), matching the pattern
    used by InboxScreen and other migrated screens.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "go_back", "Back"),
        # Mail-tab bindings (active when Mail tab is focused)
        Binding("ctrl+n", "compose_new", "New", show=True),
        Binding("d", "delete_conversation", "Delete", show=True),
        Binding("slash", "search_messages", "Search", show=True),
        Binding("s", "sync_messages", "Sync", show=True),
        Binding("t", "cycle_sort", "Sort", show=True),
        # Pages-tab bindings
        Binding("v", "preview_page", "View Page", show=True),
    ]

    SORT_MODES = ["time", "unread", "name"]

    CSS = """
    ExchangeScreen {
        background: $background;
    }

    ExchangeScreen Static {
        color: $primary;
        background: $background;
    }

    ExchangeScreen DataTable {
        background: $background;
        color: $primary;
    }

    ExchangeScreen DataTable > .datatable--header {
        background: $surface;
        color: $primary;
        text-style: bold;
    }

    ExchangeScreen DataTable > .datatable--cursor {
        background: $surface;
        color: $primary;
    }

    ExchangeScreen #inbox-header-bar {
        height: auto;
        padding: 0 1;
    }

    ExchangeScreen #inbox-title {
        width: 1fr;
    }

    ExchangeScreen #ooo-label {
        width: auto;
    }

    ExchangeScreen #inbox-header-bar Switch {
        width: auto;
    }

    ExchangeScreen #compose-bar {
        height: auto;
        padding: 0 1;
        display: none;
    }

    ExchangeScreen #compose-bar.visible {
        display: block;
    }

    ExchangeScreen #compose-bar Input {
        width: 1fr;
    }

    ExchangeScreen #compose-bar Static {
        width: auto;
    }

    ExchangeScreen .placeholder-pane {
        align: center middle;
        color: $primary;
        background: $background;
    }

    ExchangeScreen #mail-content {
        border: round $border;
        border-title-color: $primary;
        border-title-style: bold;
        border-title-align: left;
        background: $background;
        padding: 0 1;
    }

    ExchangeScreen #pages-pane-content {
        width: 100%;
        height: 100%;
        border: round $border;
        border-title-color: $primary;
        border-title-style: bold;
        border-title-align: left;
        background: $background;
        padding: 0 1;
    }

    ExchangeScreen #pages-table-section {
        height: 1fr;
        min-height: 5;
    }

    ExchangeScreen #pages-browser-section {
        height: 2fr;
    }

    ExchangeScreen #pages-browser-section.hidden {
        display: none;
    }

    ExchangeScreen #pages-browser-placeholder {
        height: 1;
        padding: 0 1;
        color: $primary-darken-2;
    }

    ExchangeScreen #pages-browser-placeholder.hidden {
        display: none;
    }
    """

    def focus_tab(self, tab_id: str) -> None:
        """Switch to the given tab, even if screen is already mounted."""
        self._initial_tab = tab_id
        try:
            tabs = self.query_one("#exchange-tabs", TabbedContent)
            tabs.active = tab_id
        except Exception:
            pass  # Screen not yet mounted — _initial_tab will be used at compose

    def __init__(self, initial_tab: str = TAB_MAIL) -> None:
        super().__init__()
        self._initial_tab = initial_tab

        # --- Mail-tab state (lifted from InboxScreen) ---
        self._delete_pending: str | None = None
        self._delete_timer: Timer | None = None
        self._search_active: bool = False
        self._compose_active: bool = False
        self._sort_mode: str = "time"
        self._conversations: list[dict[str, Any]] = []
        self._mail_index = MailIndexState(threads=(), by_thread_id={})
        self._mail_load_worker: Worker | None = None
        self._auto_reply_worker: Worker | None = None
        self._pages_refresh_worker: Worker | None = None
        self._content_host = ScreenContentHost(self, owner_logger=logger)
        self._content_host_registered = False

    # -------------------------------------------------------------------------
    # Services accessor (TUIServices protocol)
    # -------------------------------------------------------------------------

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app services."""
        try:
            return self.app.services.bridge  # type: ignore[attr-defined]
        except Exception:
            return None

    def _run_async_worker(self, fn: Any, *args: Any, **worker_kwargs: Any) -> Worker:
        """Schedule async work with callable-based worker semantics."""
        work = partial(fn, *args) if args else fn
        return self.run_worker(work, **worker_kwargs)

    def _cancel_worker(self, worker: Worker | None) -> None:
        """Cancel an in-flight worker if it is still pending or running."""
        if worker is not None and worker.state in (WorkerState.PENDING, WorkerState.RUNNING):
            worker.cancel()

    def _start_mail_load(self) -> None:
        """Start or replace the Mail conversations refresh worker."""
        if self._ipc_bridge is None:
            return
        self._cancel_worker(self._mail_load_worker)
        self._mail_load_worker = self._run_async_worker(
            self._load_conversations,
            group="exchange-mail-load",
            exclusive=True,
        )

    def _start_auto_reply_load(self) -> None:
        """Start or replace the auto-reply state refresh worker."""
        if self._ipc_bridge is None:
            return
        self._cancel_worker(self._auto_reply_worker)
        self._auto_reply_worker = self._run_async_worker(
            self._load_auto_reply_state,
            group="exchange-auto-reply-load",
            exclusive=True,
        )

    def _start_pages_refresh(self) -> None:
        """Start or replace the Pages refresh worker."""
        self._cancel_worker(self._pages_refresh_worker)
        self._pages_refresh_worker = self._run_async_worker(
            self._refresh_pages_table,
            group="pages-refresh",
            exclusive=True,
        )

    def _cancel_mail_content_workers(self) -> None:
        """Cancel Mail-pane background work."""
        self._cancel_worker(self._mail_load_worker)
        self._cancel_worker(self._auto_reply_worker)
        self._mail_load_worker = None
        self._auto_reply_worker = None

    def _cancel_pages_refresh(self) -> None:
        """Cancel Pages-pane background work."""
        self._cancel_worker(self._pages_refresh_worker)
        self._pages_refresh_worker = None

    def _register_content_slots(self) -> None:
        """Register tab content lifecycle hooks once the DOM exists."""
        if self._content_host_registered:
            return

        self._content_host.register(
            TAB_MAIL,
            hooks=ScreenContentHooks(
                activate=self._activate_mail_content,
                resume=self._resume_mail_content,
                deactivate=self._deactivate_mail_content,
                suspend=self._suspend_mail_content,
                cleanup=self._cleanup_mail_content,
            ),
        )
        self._content_host.register(
            TAB_PAGES,
            hooks=ScreenContentHooks(
                activate=self._activate_pages_content,
                resume=self._resume_pages_content,
                deactivate=self._deactivate_pages_content,
                suspend=self._suspend_pages_content,
                cleanup=self._cleanup_pages_content,
            ),
        )
        self._content_host.register(TAB_DIRECT, self.query_one(ExchangeDirectTab))
        self._content_host.register(TAB_CONTACTS, self.query_one(ExchangeContactsTab))
        self._content_host_registered = True

    def _activate_mail_content(self, initial: bool) -> None:
        """Activate the Mail pane and lazily refresh its data."""
        self._start_mail_load()
        self._start_auto_reply_load()
        if initial:
            try:
                self.query_one("#conversation-table", DataTable).focus()
            except Exception:
                pass

    def _resume_mail_content(self) -> None:
        """Refresh Mail data after re-entry."""
        self._start_mail_load()
        self._start_auto_reply_load()

    def _deactivate_mail_content(self) -> None:
        """Deactivate the Mail pane without hiding parent ownership."""
        self._cancel_delete_timer()
        self._cancel_mail_content_workers()

    def _suspend_mail_content(self) -> None:
        """Suspend Mail-pane background work while the screen is inactive."""
        self._deactivate_mail_content()

    def _cleanup_mail_content(self) -> None:
        """Release Mail-pane background work on final teardown."""
        self._deactivate_mail_content()

    def _activate_pages_content(self, initial: bool) -> None:
        """Activate the Pages pane and lazily refresh its browsable nodes."""
        _ = initial
        self._start_pages_refresh()

    def _resume_pages_content(self) -> None:
        """Refresh Pages data after re-entry."""
        self._start_pages_refresh()

    def _deactivate_pages_content(self) -> None:
        """Deactivate the Pages pane and cancel in-flight refresh work."""
        self._cancel_pages_refresh()

    def _suspend_pages_content(self) -> None:
        """Suspend Pages-pane background work while the screen is inactive."""
        self._deactivate_pages_content()

    def _cleanup_pages_content(self) -> None:
        """Release Pages-pane background work on final teardown."""
        self._deactivate_pages_content()

    # -------------------------------------------------------------------------
    # Compose
    # -------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial=self._initial_tab, id="exchange-tabs"):
            with TabPane("Mail", id=TAB_MAIL):
                yield Container(
                    Horizontal(
                        Static("", id="inbox-title"),
                        Static("Auto-Reply (OOO): ", id="ooo-label"),
                        Switch(value=False, id="ooo-switch"),
                        id="inbox-header-bar",
                    ),
                    Horizontal(
                        Input(
                            placeholder="Destination hash or contact name...",
                            id="compose-input",
                        ),
                        Static(f"[{get_color_cascade().dim}]Enter hash or name, then press Enter[/]", id="compose-hint"),
                        id="compose-bar",
                    ),
                    Horizontal(
                        Input(placeholder="Search all messages...", id="inbox-search-input"),
                        Static("", id="inbox-search-count"),
                        id="inbox-search-bar",
                        classes="hidden",
                    ),
                    Vertical(
                        DataTable(id="conversation-table"),
                        id="inbox-container",
                    ),
                    id="mail-content",
                )
            with TabPane("Direct", id=TAB_DIRECT):
                yield ExchangeDirectTab()
            with TabPane("Pages", id=TAB_PAGES):
                with Vertical(id="pages-pane-content"):
                    with Vertical(id="pages-table-section"):
                        yield ReticumAnnounceTable(
                            id="table-pages",
                            device_types=_PAGES_TYPES,
                            classes="explore-tab-table",
                        )
                    yield Static(
                        "Press [bold]v[/bold] on a node to preview pages",
                        id="pages-browser-placeholder",
                    )
                    with Vertical(id="pages-browser-section", classes="hidden"):
                        pass  # PageBrowserWidget mounted dynamically
            with TabPane("Contacts", id=TAB_CONTACTS):
                yield ExchangeContactsTab()
        yield Footer()

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def on_mount(self) -> None:
        """Initialise structure, then activate only the visible tab content."""
        # Set border titles on content containers
        try:
            self.query_one("#mail-content", Container).border_title = "CONVERSATIONS"
        except Exception:
            pass
        try:
            self.query_one("#pages-pane-content", Vertical).border_title = "PAGES"
        except Exception:
            pass

        table = self.query_one("#conversation-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("DESTINATION", "LAST MESSAGE", "UNREAD", "ATTACH", "TIMESTAMP")

        if self._ipc_bridge is None:
            table.add_row("-", f"[{get_color_cascade().dim}]Chat requires daemon mode[/]", "-", "-", "-")
        else:
            # Show loading placeholder immediately so the screen feels responsive
            table.add_row("…", f"[{get_color_cascade().dim}]loading…[/]", "-", "-", "-")

        self._register_content_slots()
        self._content_host.activate(self._initial_tab)

    def on_screen_resume(self) -> None:
        """Resume only the currently active tab content."""
        self._content_host.resume_active()

    def on_screen_suspend(self) -> None:
        """Suspend only the currently active tab content."""
        self._content_host.suspend_active()

    def on_unmount(self) -> None:
        """Fan out final cleanup to all registered tab content."""
        self._content_host.cleanup_all()

    def on_tabbed_content_tab_activated(
        self, event: TabbedContent.TabActivated
    ) -> None:
        """Activate the newly selected tab's content slot."""
        tab_id = getattr(event.tab, "id", None)
        if not isinstance(tab_id, str) or not tab_id.startswith("tab-"):
            return
        self._content_host.activate(tab_id.removeprefix("tab-"))

    async def _refresh_pages_table(self) -> None:
        """Populate #table-pages with NomadNet-browsable nodes from the device cache."""
        try:
            from styrened.tui.services.reticulum import discover_devices

            cache = getattr(self.app, "device_cache", None)
            if cache is not None:
                all_devices = cache.get()
                if not all_devices:
                    # Cache exists but hasn't been primed yet — fall back to
                    # live discovery so the Pages tab isn't permanently empty
                    # just because the cache hasn't populated on this mount.
                    all_devices = discover_devices()
            else:
                all_devices = discover_devices()
        except Exception as exc:
            logger.debug("_refresh_pages_table: device fetch failed: %s", exc)
            return

        pages_devices = [
            d for d in all_devices
            if d.device_type == DeviceType.NOMADNET_NODE
            or (
                d.device_type == DeviceType.STYRENE_NODE
                and d.nomadnet_destination_hash
            )
        ]

        try:
            table = self.query_one("#table-pages", ReticumAnnounceTable)
            table.load_from_devices(pages_devices)
        except Exception as exc:
            logger.debug("_refresh_pages_table: table update failed: %s", exc)

    # -------------------------------------------------------------------------
    # Mail-tab: data loading (preserved 1-to-1 from InboxScreen)
    # -------------------------------------------------------------------------

    async def _load_conversations(self) -> None:
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            self._conversations = await bridge.get_conversations()
        except Exception as e:
            logger.warning(f"Failed to load conversations: {e}")
            self._conversations = []

        self._mail_index = build_mail_index(
            MailIndexInputs(
                threads=tuple(self._conversation_to_mail_thread(c) for c in self._conversations),
            )
        )
        self._render_conversations()

    def _conversation_to_mail_thread(self, conversation: dict[str, Any]) -> dict[str, Any]:
        return {
            "thread_id": conversation.get("peer_hash") or "",
            "scope_kind": ConversationScopeKind.DIRECT.value,
            "peer_identity": conversation.get("peer_hash"),
            "peer_hash": conversation.get("peer_hash"),
            "display_name": conversation.get("display_name"),
            "unread_count": conversation.get("unread_count", 0),
            "last_message_time": conversation.get("last_message_time"),
            "last_message_preview": conversation.get("last_message_preview"),
            "is_outgoing": conversation.get("last_message_outgoing", False),
            "transport": "lxmf",
            "attachment_count": conversation.get("attachment_count", 0),
            "message_count": conversation.get("message_count", 0),
        }

    def _render_conversations(self) -> None:


        table = self.query_one("#conversation-table", DataTable)
        table.clear()

        conversations = self._sorted_conversations()

        if not conversations:
            table.add_row("-", f"[{get_color_cascade().dim}]No conversations yet[/]", "-", "-", "-")
            return

        cascade = get_color_cascade()

        for thread in conversations:
            peer_hash = thread.participant_identity or thread.thread_id
            unread = thread.unread_count
            is_unread = unread > 0

            if thread.display_name:
                dest_display = thread.display_name
            else:
                dest_display = peer_hash[:8] + "..." if peer_hash else "unknown"

            last_msg = (thread.latest_message.preview if thread.latest_message else None) or "No content"
            if len(last_msg) > 40:
                last_msg = last_msg[:37] + "..."

            if is_unread:
                unread_text = f"[{cascade.bright} bold]{unread}[/]"
            else:
                unread_text = f"[{cascade.dim}]-[/]"

            legacy = self._mail_conversation_meta(thread.thread_id)
            attach_count = int(legacy.get("attachment_count", 0) or 0)
            attach_text = f"\U0001f4ce {attach_count}" if attach_count > 0 else f"[{cascade.dim}]-[/]"

            last_time = thread.latest_message.timestamp if thread.latest_message else None
            timestamp_text = _format_timestamp(last_time) if last_time else "-"

            if is_unread:
                dest_display = f"[{cascade.bright} bold]{dest_display}[/]"
                last_msg = f"[{cascade.medium}]{last_msg}[/]"
                timestamp_text = f"[{cascade.medium}]{timestamp_text}[/]"
            else:
                dest_display = f"[{cascade.dim}]{dest_display}[/]"
                last_msg = f"[{cascade.dim}]{last_msg}[/]"
                timestamp_text = f"[{cascade.dim}]{timestamp_text}[/]"

            table.add_row(
                dest_display,
                last_msg,
                unread_text,
                attach_text if is_unread else f"[{cascade.dim}]{attach_text}[/]",
                timestamp_text,
                key=thread.thread_id,
            )

    def _mail_conversation_meta(self, thread_id: str) -> dict[str, Any]:
        for conversation in self._conversations:
            if conversation.get("peer_hash") == thread_id:
                return conversation
        return {}

    def _sorted_conversations(self) -> list[MailThreadRecord]:
        threads = list(self._mail_index.threads)
        if self._sort_mode == "unread":
            threads.sort(
                key=lambda t: (
                    t.unread_count == 0,
                    -(t.latest_message.timestamp if t.latest_message and t.latest_message.timestamp is not None else 0),
                )
            )
        elif self._sort_mode == "name":
            threads.sort(key=lambda t: (t.display_name or t.participant_identity or t.thread_id).lower())
        else:
            threads.sort(
                key=lambda t: t.latest_message.timestamp if t.latest_message and t.latest_message.timestamp is not None else 0,
                reverse=True,
            )
        return threads

    # -------------------------------------------------------------------------
    # Auto-reply
    # -------------------------------------------------------------------------

    async def _load_auto_reply_state(self) -> None:
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            data = await bridge.get_auto_reply()
            switch = self.query_one("#ooo-switch", Switch)
            mode = data.get("mode", "disabled")
            switch.value = mode != "disabled"
        except Exception as e:
            logger.warning(f"Failed to load auto-reply state: {e}")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if str(event.switch.id) == "ooo-switch":
            self._run_async_worker(self._toggle_auto_reply, event.value)

    async def _toggle_auto_reply(self, enabled: bool) -> None:
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Auto-reply requires daemon mode", severity="warning")
            return
        try:
            mode = "template" if enabled else "disabled"
            await bridge.set_auto_reply(mode=mode)
            self.notify(f"Auto-reply {mode}", severity="information")
        except Exception as e:
            logger.warning(f"Failed to toggle auto-reply: {e}")
            self.notify(f"Failed to toggle auto-reply: {e}", severity="error")

    # -------------------------------------------------------------------------
    # Selection helpers
    # -------------------------------------------------------------------------

    def _get_selected_thread_id(self) -> str | None:
        table = self.query_one("#conversation-table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row is None:
            if table.row_count > 0:
                table.move_cursor(row=0)
                cursor_row = 0
            else:
                return None
        cell_key = table.coordinate_to_cell_key(Coordinate(cursor_row, 0))
        if not cell_key or not cell_key.row_key or cell_key.row_key.value == "-":
            return None
        return str(cell_key.row_key.value)

    def _get_selected_mail_thread(self) -> MailThreadRecord | None:
        thread_id = self._get_selected_thread_id()
        if thread_id is None:
            return None
        return self._mail_index.by_thread_id.get(thread_id)

    def _get_selected_peer_hash(self) -> str | None:
        thread = self._get_selected_mail_thread()
        if thread is None:
            return None
        return thread.participant_identity or thread.thread_id

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_go_back(self) -> None:
        if self._compose_active:
            self._close_compose()
            return
        if self._search_active:
            self._close_search()
            return
        self.app.switch_screen("dashboard")

    def action_preview_page(self) -> None:
        """Load selected NomadNet node's index page in the inline browser (Pages tab only)."""
        try:
            tabs = self.query_one("#exchange-tabs", TabbedContent)
            if tabs.active != TAB_PAGES:
                return
        except Exception:
            return

        # Find selected row in pages table
        try:
            table = self.query_one("#table-pages", ReticumAnnounceTable)
            if table.cursor_row < 0 or table.row_count == 0:
                return
            row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
            dest_hash = str(row_key.value) if row_key.value is not None else None
        except Exception:
            dest_hash = None

        if not dest_hash:
            self.notify("Select a NomadNet node first", severity="warning")
            return

        from styrened.tui.widgets.page_browser import PageBrowserWidget

        # Look up full device for transport selector
        device = None
        try:
            table = self.query_one("#table-pages", ReticumAnnounceTable)
            if hasattr(table, "_all_devices"):
                for d in table._all_devices:
                    if d.identity_hash == dest_hash or d.destination_hash == dest_hash:
                        device = d
                        break
                    if getattr(d, "nomadnet_destination_hash", None) == dest_hash:
                        device = d
                        break
        except Exception:
            pass

        # Resolve NomadNet destination hash for browsing
        nomadnet_dest = dest_hash
        if device is not None:
            if getattr(device, "nomadnet_destination_hash", None):
                nomadnet_dest = device.nomadnet_destination_hash or nomadnet_dest
            elif device.device_type == DeviceType.NOMADNET_NODE:
                nomadnet_dest = device.destination_hash

        try:
            placeholder = self.query_one("#pages-browser-placeholder", Static)
            placeholder.add_class("hidden")

            browser_section = self.query_one("#pages-browser-section", Vertical)
            browser_section.remove_class("hidden")

            existing = browser_section.query(PageBrowserWidget)
            if existing:
                browser_widget = existing.first()
                if device is not None:
                    browser_widget.set_mesh_device(device)
                browser_widget.set_destination(nomadnet_dest)
            else:
                browser = PageBrowserWidget(
                    destination_hash=nomadnet_dest,
                    classes="explore-inline-browser",
                )
                if device is not None:
                    browser.set_mesh_device(device)
                browser_section.mount(browser)
        except Exception as exc:
            logger.warning("action_preview_page failed: %s", exc)

    def action_cycle_sort(self) -> None:
        idx = self.SORT_MODES.index(self._sort_mode)
        self._sort_mode = self.SORT_MODES[(idx + 1) % len(self.SORT_MODES)]
        self.notify(f"Sort: {self._sort_mode}", severity="information")
        self._render_conversations()

    # --- Compose ---

    def action_compose_new(self) -> None:
        if self._ipc_bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return
        if self._compose_active:
            self._close_compose()
            return
        self._compose_active = True
        try:
            self.query_one("#compose-bar").add_class("visible")
            self.query_one("#compose-input", Input).focus()
        except Exception:
            pass

    def _close_compose(self) -> None:
        self._compose_active = False
        try:
            self.query_one("#compose-bar").remove_class("visible")
            self.query_one("#compose-input", Input).value = ""
        except Exception:
            pass

    # --- Open mail thread ---

    def _open_mail_thread(self, thread: MailThreadRecord) -> None:
        if thread.scope_kind == ConversationScopeKind.DIRECT:
            peer_hash = thread.participant_identity or thread.thread_id
            from styrened.tui.screens.conversation import ConversationScreen

            self.app.push_screen(
                ConversationScreen(
                    peer_hash=peer_hash,
                    display_name=thread.display_name,
                    origin_workspace="mail",
                )
            )
            return

        if thread.scope_kind == ConversationScopeKind.GROUP:
            from styrened.tui.screens.mail_group_thread import MailGroupThreadScreen

            self.app.push_screen(
                MailGroupThreadScreen(
                    thread_id=thread.thread_id,
                    display_name=thread.display_name,
                    group=thread.group,
                )
            )
            return

        if thread.scope_kind == ConversationScopeKind.FORUM:
            from styrened.tui.screens.forum_thread import ForumThreadScreen

            self.app.push_screen(
                ForumThreadScreen(
                    thread_id=thread.thread_id,
                    display_name=thread.display_name,
                    forum=thread.forum,
                )
            )
            return

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if not event.row_key or not event.row_key.value or event.row_key.value == "-":
            return
        if self._ipc_bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return
        thread = self._mail_index.by_thread_id.get(str(event.row_key.value))
        if thread is None:
            return
        self._open_mail_thread(thread)

    def action_open_conversation(self) -> None:
        thread = self._get_selected_mail_thread()
        if thread is None:
            return
        if self._ipc_bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return
        self._open_mail_thread(thread)

    # --- Delete ---

    def action_delete_conversation(self) -> None:
        peer_hash = self._get_selected_peer_hash()
        if peer_hash is None:
            return
        if self._delete_pending == peer_hash:
            self._cancel_delete_timer()
            self._run_async_worker(self._execute_delete_conversation, peer_hash, group="exchange-delete")
        else:
            self._delete_pending = peer_hash
            self.notify("Press d again to delete conversation", severity="warning")
            self._cancel_delete_timer()
            self._delete_timer = self.set_timer(_DELETE_CONFIRM_TIMEOUT, self._cancel_delete_pending)

    def _cancel_delete_timer(self) -> None:
        if self._delete_timer is not None:
            self._delete_timer.stop()
            self._delete_timer = None

    def _cancel_delete_pending(self) -> None:
        self._delete_pending = None
        self._cancel_delete_timer()

    async def _execute_delete_conversation(self, peer_hash: str) -> None:
        self._delete_pending = None
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            count = await bridge.delete_conversation(peer_hash)
            self.notify(f"Deleted {count} messages", severity="information")
            await self._load_conversations()
        except Exception as e:
            logger.error(f"Failed to delete conversation: {e}")
            self.notify(f"Delete failed: {e}", severity="error")

    # --- Search ---

    def action_search_messages(self) -> None:
        if self._search_active:
            self._close_search()
        else:
            self._open_search()

    def _open_search(self) -> None:
        self._search_active = True
        try:
            self.query_one("#inbox-search-bar").remove_class("hidden")
            self.query_one("#inbox-search-input", Input).focus()
        except Exception:
            pass

    def _close_search(self) -> None:
        self._search_active = False
        try:
            self.query_one("#inbox-search-bar").add_class("hidden")
            self.query_one("#inbox-search-input", Input).value = ""
            self.query_one("#inbox-search-count", Static).update("")
        except Exception:
            pass
        self._run_async_worker(self._load_conversations)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "compose-input":
            value = event.value.strip()
            if not value:
                return
            self._run_async_worker(self._resolve_and_open, value, group="exchange-compose")
            return

        if event.input.id != "inbox-search-input":
            return

        query = event.value.strip()
        if len(query) < 2:
            return
        self._run_async_worker(self._execute_search, query, group="exchange-search")

    async def _resolve_and_open(self, value: str) -> None:
        import re

        bridge = self._ipc_bridge
        if bridge is None:
            return

        peer_hash: str | None = None
        display_name: str | None = None

        if re.match(r"^[0-9a-fA-F]{16,64}$", value):
            peer_hash = value
        else:
            try:
                resolved = await bridge.resolve_name(value)
                if resolved:
                    peer_hash = resolved
                    display_name = value
                else:
                    self.notify(f"No contact found for '{value}'", severity="warning")
                    return
            except Exception as e:
                self.notify(f"Resolve failed: {e}", severity="error")
                return

        self._close_compose()

        from styrened.tui.screens.conversation import ConversationScreen

        self.app.push_screen(
            ConversationScreen(
                peer_hash=peer_hash,
                display_name=display_name,
                origin_workspace="mail",
            )
        )

    async def _execute_search(self, query: str) -> None:
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            results = await bridge.search_messages(query=query)
        except Exception as e:
            logger.warning(f"Search failed: {e}")
            self.notify(f"Search failed: {e}", severity="error")
            return

        try:
            self.query_one("#inbox-search-count", Static).update(f"{len(results)} results")
        except Exception:
            pass

        table = self.query_one("#conversation-table", DataTable)
        table.clear()

        if not results:
            table.add_row("-", f"[{get_color_cascade().dim}]No results for '{query}'[/]", "-", "-", "-")
            return

        for msg in results:
            peer_hash = msg.get("source_hash", "") or msg.get("destination_hash", "")
            content = msg.get("content", "") or f"[{get_color_cascade().dim}]No content[/]"
            if len(content) > 40:
                content = content[:37] + "..."
            is_outgoing = msg.get("is_outgoing", False)
            direction = "\u2192" if is_outgoing else "\u2190"
            timestamp = msg.get("timestamp")
            ts_text = _format_timestamp(timestamp) if timestamp else "-"
            has_attach = msg.get("has_attachment", False)
            attach_text = "\U0001f4ce" if has_attach else "-"
            table.add_row(
                f"{direction} {peer_hash[:8]}...",
                content,
                "-",
                attach_text,
                ts_text,
                key=peer_hash,
            )

    # --- Sync ---

    def action_sync_messages(self) -> None:
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Sync requires daemon mode", severity="warning")
            return
        self.notify("Syncing with propagation node...", severity="information")
        self._run_async_worker(self._execute_sync, group="exchange-sync")

    async def _execute_sync(self) -> None:
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            result = await bridge.sync_messages()
            if result.get("synced"):
                self.notify("Sync requested", severity="information")
                import asyncio
                await asyncio.sleep(2.0)
                await self._load_conversations()
            else:
                self.notify("Sync failed — no propagation node configured?", severity="warning")
        except Exception as e:
            logger.warning(f"Sync failed: {e}")
            self.notify(f"Sync failed: {e}", severity="error")
