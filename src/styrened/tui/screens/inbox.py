"""InboxScreen - Conversation list for chat messages.

This screen displays a list of conversations with unread counts and message previews.
Uses IPCBridge for daemon communication and theme variables for styling.
"""

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Input, Static, Switch

logger = logging.getLogger(__name__)

# Delete confirmation timeout (seconds)
_DELETE_CONFIRM_TIMEOUT = 3.0


class InboxScreen(Screen[None]):
    """Inbox screen showing conversation list.

    Displays all chat conversations with:
    - Display name or short hash
    - Last message preview
    - Unread message count
    - Timestamp of last message

    Conversations are ordered by most recent message first.
    All data is loaded via IPCBridge from the daemon.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("enter", "open_conversation", "Open"),
        Binding("d", "delete_conversation", "Delete", show=True),
        Binding("slash", "search_messages", "Search", show=True),
    ]

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

    InboxScreen #ooo-bar {
        height: 3;
        padding: 0 1;
    }

    InboxScreen #ooo-bar Static {
        width: auto;
    }

    InboxScreen #ooo-bar Switch {
        width: auto;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._delete_pending: str | None = None
        self._delete_timer: Timer | None = None
        self._search_active: bool = False

    def compose(self) -> ComposeResult:
        """Compose inbox UI."""
        yield Header()
        yield Container(
            Static("INBOX - LXMF Conversations", id="inbox-title"),
            Horizontal(
                Static("Auto-Reply (OOO): "),
                Switch(value=False, id="ooo-switch"),
                id="ooo-bar",
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
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
        except Exception:
            return None

    def on_mount(self) -> None:
        """Load conversations on mount."""
        table = self.query_one("#conversation-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("DESTINATION", "LAST MESSAGE", "UNREAD", "TIMESTAMP")

        if self._ipc_bridge is None:
            table.add_row("-", "[dim]Chat requires daemon mode[/]", "-", "-")
            return

        self.run_worker(self._load_conversations())
        self.run_worker(self._load_auto_reply_state())

    async def _load_conversations(self) -> None:
        """Load conversations via IPCBridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            conversations = await bridge.get_conversations()
        except Exception as e:
            logger.warning(f"Failed to load conversations: {e}")
            conversations = []

        table = self.query_one("#conversation-table", DataTable)
        table.clear()

        if not conversations:
            table.add_row("-", "[dim]No conversations yet[/]", "-", "-")
            return

        for conv in conversations:
            peer_hash = conv.get("peer_hash", "")
            display_name = conv.get("display_name")

            # Use display_name when present, fall back to short hash
            if display_name:
                dest_display = display_name
            else:
                dest_display = peer_hash[:8] + "..." if peer_hash else "unknown"

            # Format last message (truncate to 40 chars)
            last_msg = conv.get("last_message_preview") or "[dim]No content[/]"
            if len(last_msg) > 40:
                last_msg = last_msg[:37] + "..."

            # Format unread count
            unread = conv.get("unread_count", 0)
            unread_text = f"[bold]{unread}[/]" if unread > 0 else "-"

            # Format timestamp
            last_time = conv.get("last_message_time")
            timestamp_text = f"{int(last_time)}" if last_time else "-"

            table.add_row(
                dest_display,
                last_msg,
                unread_text,
                timestamp_text,
                key=peer_hash,
            )

    async def _load_auto_reply_state(self) -> None:
        """Load auto-reply state from IPCBridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            data = await bridge.get_auto_reply()
            switch = self.query_one("#ooo-switch", Switch)
            switch.value = data.get("enabled", False)
        except Exception as e:
            logger.warning(f"Failed to load auto-reply state: {e}")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Handle OOO switch toggle."""
        if str(event.switch.id) == "ooo-switch":
            self.run_worker(self._toggle_auto_reply(event.value))

    async def _toggle_auto_reply(self, enabled: bool) -> None:
        """Toggle auto-reply via IPCBridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Auto-reply requires daemon mode", severity="warning")
            return

        try:
            await bridge.set_auto_reply(enabled=enabled)
            state = "enabled" if enabled else "disabled"
            self.notify(f"Auto-reply {state}", severity="information")
        except Exception as e:
            logger.warning(f"Failed to toggle auto-reply: {e}")
            self.notify(f"Failed to toggle auto-reply: {e}", severity="error")

    def _get_selected_peer_hash(self) -> str | None:
        """Get the peer_hash of the currently selected conversation row."""
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

    def action_open_conversation(self) -> None:
        """Open conversation screen for selected row."""
        peer_hash = self._get_selected_peer_hash()
        if peer_hash is None:
            return

        if self._ipc_bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return

        from styrened.tui.screens.conversation import ConversationScreen

        self.app.push_screen(ConversationScreen(peer_hash=peer_hash))

    # -------------------------------------------------------------------------
    # Delete conversation (double-tap)
    # -------------------------------------------------------------------------

    def action_delete_conversation(self) -> None:
        """Delete selected conversation with double-tap confirmation."""
        peer_hash = self._get_selected_peer_hash()
        if peer_hash is None:
            return

        if self._delete_pending == peer_hash:
            # Second press — execute
            self._cancel_delete_timer()
            self.run_worker(self._execute_delete_conversation(peer_hash), group="inbox-delete")
        else:
            # First press — set pending
            self._delete_pending = peer_hash
            self.notify("Press d again to delete conversation", severity="warning")
            self._cancel_delete_timer()
            self._delete_timer = self.set_timer(
                _DELETE_CONFIRM_TIMEOUT, self._cancel_delete_pending
            )

    def _cancel_delete_timer(self) -> None:
        """Cancel delete confirmation timer."""
        if self._delete_timer is not None:
            self._delete_timer.stop()
            self._delete_timer = None

    def _cancel_delete_pending(self) -> None:
        """Cancel delete pending state."""
        self._delete_pending = None
        self._cancel_delete_timer()

    async def _execute_delete_conversation(self, peer_hash: str) -> None:
        """Execute conversation deletion and remove row."""
        self._delete_pending = None
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            count = await bridge.delete_conversation(peer_hash)
            self.notify(f"Deleted {count} messages", severity="information")
            # Refresh conversation list
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
        self.run_worker(self._load_conversations())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle search input submission."""
        if event.input.id != "inbox-search-input":
            return

        query = event.value.strip()
        if len(query) < 2:
            return

        self.run_worker(self._execute_search(query), group="inbox-search")

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
            table.add_row("-", f"[dim]No results for '{query}'[/]", "-", "-")
            return

        for msg in results:
            peer_hash = msg.get("source_hash", "") or msg.get("destination_hash", "")
            content = msg.get("content", "") or "[dim]No content[/]"
            if len(content) > 40:
                content = content[:37] + "..."

            is_outgoing = msg.get("is_outgoing", False)
            direction = "\u2192" if is_outgoing else "\u2190"

            timestamp = msg.get("timestamp")
            ts_text = f"{int(timestamp)}" if timestamp else "-"

            table.add_row(
                f"{direction} {peer_hash[:8]}...",
                content,
                "-",
                ts_text,
                key=peer_hash,
            )
