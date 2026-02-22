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
from textual.widgets import DataTable, Footer, Header, Static, Switch

logger = logging.getLogger(__name__)


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

    def action_open_conversation(self) -> None:
        """Open conversation screen for selected row."""
        table = self.query_one("#conversation-table", DataTable)

        cursor_row = table.cursor_row
        if cursor_row is None:
            if table.row_count > 0:
                table.move_cursor(row=0)
                cursor_row = 0
            else:
                return

        cell_key = table.coordinate_to_cell_key(Coordinate(cursor_row, 0))
        if not cell_key or not cell_key.row_key or cell_key.row_key.value == "-":
            return

        peer_hash = str(cell_key.row_key.value)

        if self._ipc_bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return

        from styrened.tui.screens.conversation import ConversationScreen

        self.app.push_screen(ConversationScreen(peer_hash=peer_hash))
