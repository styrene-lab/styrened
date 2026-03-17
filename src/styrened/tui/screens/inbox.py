"""InboxScreen - Conversation list for chat messages.

This screen displays a list of conversations with unread counts and message previews.
Uses IPCBridge for daemon communication and theme variables for styling.
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
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static, Switch

from styrened.tui.screens.base import StyreneScreen
from styrened.tui.widgets.highlighted_panel import get_color_cascade
from styrened.ui_state import (
    ConversationScopeKind,
    MailIndexInputs,
    MailIndexState,
    MailThreadRecord,
    build_mail_index,
)

logger = logging.getLogger(__name__)

# Delete confirmation timeout (seconds)
_DELETE_CONFIRM_TIMEOUT = 3.0


def _format_timestamp(ts: float | int | None) -> str:
    """Format a Unix timestamp as a human-readable string.

    - Today: "14:32"
    - This week: "Mon 14:32"
    - This year: "Feb 22 14:32"
    - Older: "2025-12-01"
    """
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


class InboxScreen(StyreneScreen[None]):
    """Mail workspace compatibility screen showing conversation list.

    Displays all chat conversations with:
    - Display name or short hash
    - Last message preview
    - Unread message count
    - Timestamp of last message

    Conversations are ordered by most recent message first.
    All data is loaded via IPCBridge from the daemon.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "go_back", "Home"),
        Binding("enter", "open_conversation", "Open"),
        Binding("ctrl+n", "compose_new", "New", show=True),
        Binding("d", "delete_conversation", "Delete", show=True),
        Binding("slash", "search_messages", "Search", show=True),
        Binding("s", "sync_messages", "Sync", show=True),
        Binding("t", "cycle_sort", "Sort", show=True),
    ]

    # Sort modes: time (default), unread first, name
    SORT_MODES = ["time", "unread", "name"]

    CSS = """
    InboxScreen {
        background: $background;
    }

    InboxScreen Static {
        color: $primary;
        background: $background;
    }

    InboxScreen DataTable {
        background: $background;
        color: $primary;
    }

    InboxScreen DataTable > .datatable--header {
        background: $surface;
        color: $primary;
        text-style: bold;
    }

    InboxScreen DataTable > .datatable--cursor {
        background: $surface;
        color: $primary;
    }

    InboxScreen #inbox-header-bar {
        height: auto;
        padding: 0 1;
    }

    InboxScreen #inbox-title {
        width: 1fr;
    }

    InboxScreen #ooo-label {
        width: auto;
    }

    InboxScreen #inbox-header-bar Switch {
        width: auto;
    }

    InboxScreen #compose-bar {
        height: auto;
        padding: 0 1;
        display: none;
    }

    InboxScreen #compose-bar.visible {
        display: block;
    }

    InboxScreen #compose-bar Input {
        width: 1fr;
    }

    InboxScreen #compose-bar Static {
        width: auto;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._delete_pending: str | None = None
        self._delete_timer: Timer | None = None
        self._search_active: bool = False
        self._compose_active: bool = False
        self._sort_mode: str = "time"
        self._conversations: list[dict[str, Any]] = []
        self._mail_index = MailIndexState(threads=(), by_thread_id={})

    def compose(self) -> ComposeResult:
        """Compose inbox UI."""
        yield Header()
        yield Container(
            Horizontal(
                Static("MAIL - Async Conversations", id="inbox-title"),
                Static("Auto-Reply (OOO): ", id="ooo-label"),
                Switch(value=False, id="ooo-switch"),
                id="inbox-header-bar",
            ),
            # Compose bar (hidden by default)
            Horizontal(
                Input(
                    placeholder="Destination hash or contact name...",
                    id="compose-input",
                ),
                Static(f"[{get_color_cascade().dim}]Enter hash or name, then press Enter[/]", id="compose-hint"),
                id="compose-bar",
            ),
            # Search bar (hidden by default)
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
        )
        yield Footer()

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle (returns None when unavailable)."""
        try:
            return self.bridge
        except Exception:
            return None

    def _loading_message(self) -> str:
        return "Loading mail…"

    def _run_async_worker(self, fn: Any, *args: Any, **worker_kwargs: Any) -> Any:
        """Schedule async work with callable-based worker semantics."""
        work = partial(fn, *args) if args else fn
        return self.run_worker(work, **worker_kwargs)

    def on_mount(self) -> None:
        """Set up the DataTable widget structure, then start the shared load cycle."""
        table = self.query_one("#conversation-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("DESTINATION", "LAST MESSAGE", "UNREAD", "ATTACH", "TIMESTAMP")
        table.focus()
        # StyreneScreen.on_mount() triggers _start_load() which calls _load_data().
        super().on_mount()

    async def _load_data(self) -> None:
        """Fetch conversations and auto-reply state via the shared StyreneScreen lifecycle."""
        if self._ipc_bridge is None:
            self._conversations = []
            self._mail_index = MailIndexState(threads=(), by_thread_id={})
            table = self.query_one("#conversation-table", DataTable)
            table.clear()
            table.add_row("-", f"[{get_color_cascade().dim}]Chat requires daemon mode[/]", "-", "-", "-")
            return

        await self._load_conversations()
        await self._load_auto_reply_state()

    async def _load_conversations(self) -> None:
        """Load conversations via IPCBridge."""
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
                threads=tuple(self._conversation_to_mail_thread(conv) for conv in self._conversations),
            )
        )
        self._render_conversations()

    def _conversation_to_mail_thread(self, conversation: dict[str, Any]) -> dict[str, Any]:
        """Normalize legacy inbox conversation payloads into canonical mail-thread inputs."""
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
        """Render conversation table with current sort and styling."""
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
            if attach_count > 0:
                attach_text = f"\U0001f4ce {attach_count}"
            else:
                attach_text = f"[{cascade.dim}]-[/]"

            last_time = thread.latest_message.timestamp if thread.latest_message else None
            timestamp_text = _format_timestamp(last_time) if last_time else "-"

            if is_unread:
                dest_display = f"[{cascade.bright} bold]● {dest_display}[/]"
                last_msg = f"[{cascade.medium}]{last_msg}[/]"
                timestamp_text = f"[{cascade.medium}]{timestamp_text}[/]"
            else:
                dest_display = f"[{cascade.dim}]  {dest_display}[/]"
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
        """Return legacy conversation metadata not yet modeled in canonical mail state."""
        for conversation in self._conversations:
            if conversation.get("peer_hash") == thread_id:
                return conversation
        return {}

    def _sorted_conversations(self):
        """Sort canonical mail threads based on current sort mode."""
        threads = list(self._mail_index.threads)
        if self._sort_mode == "unread":
            threads.sort(
                key=lambda thread: (
                    thread.unread_count == 0,
                    -(thread.latest_message.timestamp if thread.latest_message and thread.latest_message.timestamp is not None else 0),
                )
            )
        elif self._sort_mode == "name":
            threads.sort(key=lambda thread: (thread.display_name or thread.participant_identity or thread.thread_id).lower())
        else:
            threads.sort(
                key=lambda thread: thread.latest_message.timestamp if thread.latest_message and thread.latest_message.timestamp is not None else 0,
                reverse=True,
            )
        return threads

    def action_cycle_sort(self) -> None:
        """Cycle through sort modes: time -> unread -> name."""
        idx = self.SORT_MODES.index(self._sort_mode)
        self._sort_mode = self.SORT_MODES[(idx + 1) % len(self.SORT_MODES)]
        self.notify(f"Sort: {self._sort_mode}", severity="information")
        self._render_conversations()

    async def _load_auto_reply_state(self) -> None:
        """Load auto-reply state from IPCBridge."""
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
        """Handle OOO switch toggle."""
        if str(event.switch.id) == "ooo-switch":
            self._run_async_worker(self._toggle_auto_reply, event.value)

    async def _toggle_auto_reply(self, enabled: bool) -> None:
        """Toggle auto-reply via IPCBridge."""
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

    def _get_selected_thread_id(self) -> str | None:
        """Get the canonical thread id for the currently selected row."""
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
        """Return the currently selected canonical Mail thread."""
        thread_id = self._get_selected_thread_id()
        if thread_id is None:
            return None
        return self._mail_index.by_thread_id.get(thread_id)

    def _get_selected_peer_hash(self) -> str | None:
        """Return the peer hash for the currently selected conversation row.

        For DIRECT-scope threads the thread_id doubles as the peer hash.
        """
        return self._get_selected_thread_id()

    def action_go_back(self) -> None:
        """Layered escape: close compose -> close search -> pop screen."""
        if self._compose_active:
            self._close_compose()
            return
        if self._search_active:
            self._close_search()
            return
        self.app.switch_screen("dashboard")

    # -------------------------------------------------------------------------
    # Compose new conversation
    # -------------------------------------------------------------------------

    def action_compose_new(self) -> None:
        """Show compose bar for entering a destination hash or contact name."""
        if self._ipc_bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return

        if self._compose_active:
            self._close_compose()
            return

        self._compose_active = True
        try:
            bar = self.query_one("#compose-bar")
            bar.add_class("visible")
            compose_input = self.query_one("#compose-input", Input)
            compose_input.value = ""
            compose_input.focus()
        except Exception:
            pass

    def _close_compose(self) -> None:
        """Hide compose bar."""
        self._compose_active = False
        try:
            bar = self.query_one("#compose-bar")
            bar.remove_class("visible")
            compose_input = self.query_one("#compose-input", Input)
            compose_input.value = ""
        except Exception:
            pass

    def _open_mail_thread(self, thread: MailThreadRecord) -> None:
        """Open a canonical Mail thread using scope-aware routing."""
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
        """Handle DataTable enter key with scope-aware Mail thread routing.

        The DataTable consumes enter key events when cursor_type="row",
        emitting RowSelected instead of letting the screen binding fire.
        """
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
        """Open the selected canonical Mail thread.

        Fallback action for the enter binding. When DataTable is focused,
        on_data_table_row_selected handles it instead.
        """
        thread = self._get_selected_mail_thread()
        if thread is None:
            return

        if self._ipc_bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return

        self._open_mail_thread(thread)

    # -------------------------------------------------------------------------
    # Delete conversation (double-tap)
    # -------------------------------------------------------------------------

    def action_delete_conversation(self) -> None:
        """Delete selected conversation with double-tap confirmation.

        First press: highlights the row and updates the footer status — no
        intrusive toast.  Second press within the timeout window executes.
        """
        peer_hash = self._get_selected_peer_hash()
        if peer_hash is None:
            return

        if self._delete_pending == peer_hash:
            # Second press on the same row — execute.
            self._cancel_delete_timer()
            self._delete_pending = None
            self._set_footer_status("")
            # exclusive=True prevents concurrent deletes from racing.
            self._run_async_worker(
                self._execute_delete_conversation, peer_hash,
                group="inbox-delete", exclusive=True,
            )
        else:
            # First press — arm confirmation without a toast.
            self._delete_pending = peer_hash
            self._set_footer_status("⚠ Press D again to confirm delete")
            self._cancel_delete_timer()
            self._delete_timer = self._resources.set_timer(
                "_delete_timer",
                _DELETE_CONFIRM_TIMEOUT,
                self._cancel_delete_pending,
            )

    def _set_footer_status(self, text: str) -> None:
        """Push a transient message into the screen's status area."""
        try:
            from styrened.tui.widgets.highlighted_panel import get_color_cascade
            cascade = get_color_cascade()
            # Attempt to use a dedicated status label if one exists.
            status = self.query_one("#inbox-status", Static)
            status.update(f"[{cascade.dim}]{text}[/]" if text else "")
        except Exception:
            # Fallback: sub_title on the screen itself.
            try:
                self.sub_title = text
            except Exception:
                pass

    def _cancel_delete_timer(self) -> None:
        """Cancel delete confirmation timer."""
        self._resources.stop_timer("_delete_timer")

    def _cancel_delete_pending(self) -> None:
        """Cancel delete pending state and clear footer hint."""
        self._delete_pending = None
        self._set_footer_status("")
        self._cancel_delete_timer()

    async def _execute_delete_conversation(self, peer_hash: str) -> None:
        """Execute conversation deletion and refresh the list."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            count = await bridge.delete_conversation(peer_hash)
            msg = f"Conversation deleted ({count} message{'s' if count != 1 else ''})" if count else "Conversation deleted"
            self.notify(msg, severity="information", timeout=3)
            await self._load_conversations()
        except Exception as e:
            logger.error(f"Failed to delete conversation: {e}")
            self.notify(f"Delete failed: {e}", severity="error")

    # -------------------------------------------------------------------------
    # Cross-conversation search
    # -------------------------------------------------------------------------

    def action_search_messages(self) -> None:
        """Toggle cross-conversation search bar."""
        if self._search_active:
            self._close_search()
        else:
            self._open_search()

    def _open_search(self) -> None:
        """Show search bar."""
        self._search_active = True
        try:
            bar = self.query_one("#inbox-search-bar")
            bar.remove_class("hidden")
            search_input = self.query_one("#inbox-search-input", Input)
            search_input.focus()
        except Exception:
            pass

    def _close_search(self) -> None:
        """Hide search bar and restore conversation view."""
        self._search_active = False
        try:
            bar = self.query_one("#inbox-search-bar")
            bar.add_class("hidden")
            search_input = self.query_one("#inbox-search-input", Input)
            search_input.value = ""
            count = self.query_one("#inbox-search-count", Static)
            count.update("")
        except Exception:
            pass

        # Restore conversation list
        self._run_async_worker(self._load_conversations)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle compose or search input submission."""
        if event.input.id == "compose-input":
            value = event.value.strip()
            if not value:
                return
            self._run_async_worker(self._resolve_and_open, value, group="inbox-compose")
            return

        if event.input.id != "inbox-search-input":
            return

        query = event.value.strip()
        if len(query) < 2:
            return

        self._run_async_worker(self._execute_search, query, group="inbox-search")

    async def _resolve_and_open(self, value: str) -> None:
        """Resolve input to a peer hash and open conversation.

        Accepts either a hex destination hash or a contact name.
        """
        import re

        bridge = self._ipc_bridge
        if bridge is None:
            return

        peer_hash: str | None = None
        display_name: str | None = None

        # Check if it looks like a hex hash (16-64 hex chars)
        if re.match(r"^[0-9a-fA-F]{16,64}$", value):
            peer_hash = value
        else:
            # Try resolving as a contact name
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
        """Execute cross-conversation search."""
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
            count_widget = self.query_one("#inbox-search-count", Static)
            count_widget.update(f"{len(results)} results")
        except Exception:
            pass

        # Display results in the conversation table
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

    # -------------------------------------------------------------------------
    # Propagation node sync
    # -------------------------------------------------------------------------

    def action_sync_messages(self) -> None:
        """Request message sync from propagation node."""
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Sync requires daemon mode", severity="warning")
            return

        self.notify("Syncing with propagation node...", severity="information")
        self._run_async_worker(self._execute_sync, group="inbox-sync")

    async def _execute_sync(self) -> None:
        """Execute propagation node sync via IPCBridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            result = await bridge.sync_messages()
            if result.get("synced"):
                self.notify("Sync requested", severity="information")
                # Refresh conversation list after a short delay for messages to arrive
                import asyncio

                await asyncio.sleep(2.0)
                await self._load_conversations()
            else:
                self.notify(
                    "Sync failed — no propagation node configured?",
                    severity="warning",
                )
        except Exception as e:
            logger.warning(f"Sync failed: {e}")
            self.notify(f"Sync failed: {e}", severity="error")


MailScreen = InboxScreen
