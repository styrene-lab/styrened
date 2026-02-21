"""InboxScreen - Conversation list for chat messages.

This screen displays a list of conversations with unread counts and message previews.
Follows the Imperial CRT theme (green phosphor #39ff14 on #0a0a0a).
"""

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from styrened.models.messages import Message

if TYPE_CHECKING:
    from styrened.protocols.chat import ChatProtocol


class InboxScreen(Screen[None]):
    """Inbox screen showing conversation list.

    Displays all chat conversations with:
    - Destination identity (short hash)
    - Last message preview
    - Unread message count
    - Timestamp of last message

    Conversations are ordered by most recent message first.

    Attributes:
        db_engine: SQLAlchemy engine for message persistence
        local_identity_hash: Local node's identity hash
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("enter", "open_conversation", "Open"),
    ]

    CSS = """
    InboxScreen {
        background: #0a0a0a;
    }

    InboxScreen Static {
        color: #39ff14;
        background: #0a0a0a;
    }

    InboxScreen DataTable {
        background: #0a0a0a;
        color: #39ff14;
    }

    InboxScreen DataTable > .datatable--header {
        background: #0a0a0a;
        color: #39ff14;
        text-style: bold;
    }

    InboxScreen DataTable > .datatable--cursor {
        background: #1a3a1a;
        color: #39ff14;
    }
    """

    def __init__(
        self,
        db_engine: Engine | None,
        local_identity_hash: str,
        chat_protocol: "ChatProtocol | None" = None,
    ) -> None:
        """Initialize InboxScreen.

        Args:
            db_engine: SQLAlchemy engine for message persistence
            local_identity_hash: Local node's identity hash
            chat_protocol: Optional ChatProtocol for opening conversations
        """
        super().__init__()
        self.db_engine = db_engine
        self.local_identity_hash = local_identity_hash
        self.chat_protocol = chat_protocol

    def compose(self) -> ComposeResult:
        """Compose inbox UI."""
        yield Header()
        yield Container(
            Static("INBOX - LXMF Conversations", id="inbox-title"),
            Vertical(
                DataTable(id="conversation-table"),
                id="inbox-container",
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load conversations on mount."""
        table = self.query_one("#conversation-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("DESTINATION", "LAST MESSAGE", "UNREAD", "TIMESTAMP")

        # Load conversation data
        conversations = self.get_conversations()

        if not conversations:
            table.add_row("-", "[dim]No conversations yet[/]", "-", "-")
        else:
            for conv in conversations:
                # Format destination (short hash)
                dest_short = conv["destination_hash"][:8] + "..."

                # Format last message (truncate to 40 chars)
                last_msg = conv["last_message"] or "[dim]No content[/]"
                if len(last_msg) > 40:
                    last_msg = last_msg[:37] + "..."

                # Format unread count
                unread = conv["unread_count"]
                unread_text = f"[bold green]{unread}[/]" if unread > 0 else "-"

                # Format timestamp
                timestamp_text = f"{int(conv['last_timestamp'])}"

                table.add_row(
                    dest_short,
                    last_msg,
                    unread_text,
                    timestamp_text,
                    key=conv["destination_hash"],  # Row key for selection
                )

    def get_conversations(self) -> list[dict[str, Any]]:
        """Retrieve conversation list from database.

        Returns:
            List of conversation dicts with:
            - destination_hash: Conversation partner's identity
            - last_message: Most recent message content
            - last_timestamp: Timestamp of most recent message
            - unread_count: Number of unread messages
        """
        if self.db_engine is None:
            return []

        with Session(self.db_engine) as session:
            # Query for all chat messages involving this identity
            messages = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    or_(
                        Message.source_hash == self.local_identity_hash,
                        Message.destination_hash == self.local_identity_hash,
                    ),
                )
                .order_by(Message.timestamp.desc())
                .all()
            )

            if not messages:
                return []

            # Group messages by conversation partner
            conversations: dict[str, dict[str, Any]] = {}

            for msg in messages:
                # Determine conversation partner (the other party)
                if msg.source_hash == self.local_identity_hash:
                    partner_hash = msg.destination_hash
                else:
                    partner_hash = msg.source_hash

                # Initialize conversation entry if not exists
                if partner_hash not in conversations:
                    conversations[partner_hash] = {
                        "destination_hash": partner_hash,
                        "last_message": None,
                        "last_timestamp": 0.0,
                        "unread_count": 0,
                    }

                conv = conversations[partner_hash]

                # Update last message (most recent)
                if msg.timestamp > conv["last_timestamp"]:
                    conv["last_message"] = msg.content
                    conv["last_timestamp"] = msg.timestamp

                # Count unread messages (pending status + not from me)
                if msg.status == "pending" and msg.destination_hash == self.local_identity_hash:
                    conv["unread_count"] += 1

            # Convert to list and sort by most recent first
            conversation_list = list(conversations.values())
            conversation_list.sort(key=lambda c: c["last_timestamp"], reverse=True)

            return conversation_list

    def action_open_conversation(self) -> None:
        """Open conversation screen for selected row."""
        table = self.query_one("#conversation-table", DataTable)

        # Ensure we have a valid cursor position
        cursor_row = table.cursor_row
        if cursor_row is None:
            # Try to select first row if none selected
            if table.row_count > 0:
                table.move_cursor(row=0)
                cursor_row = 0
            else:
                return

        # Get destination hash from row key
        cell_key = table.coordinate_to_cell_key(Coordinate(cursor_row, 0))
        if not cell_key or not cell_key.row_key or cell_key.row_key.value == "-":
            return

        destination_hash = str(cell_key.row_key.value)

        # Require chat protocol to open conversation
        if self.chat_protocol is None:
            self.notify("Chat not available", severity="warning")
            return

        # Push conversation screen
        from styrened.tui.screens.conversation import ConversationScreen

        self.app.push_screen(
            ConversationScreen(
                destination_hash=destination_hash,
                local_identity_hash=self.local_identity_hash,
                chat_protocol=self.chat_protocol,
            )
        )
