"""ConversationScreen - Message thread for chat conversations.

This screen displays a message thread with a specific conversation partner
and allows sending new messages. Follows the Imperial CRT theme.
"""

from typing import Any, ClassVar

from sqlalchemy.orm import Session
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from styrened.models.messages import Message
from styrened.protocols.chat import ChatProtocol


class ConversationScreen(Screen[None]):
    """Conversation screen showing message thread.

    Displays message history with a conversation partner and
    provides input field for sending new messages.

    Attributes:
        destination_hash: Conversation partner's identity hash
        local_identity_hash: Local node's identity hash
        chat_protocol: ChatProtocol instance for sending/receiving
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    CSS = """
    ConversationScreen {
        background: #0a0a0a;
    }

    ConversationScreen Static {
        color: #39ff14;
        background: #0a0a0a;
    }

    ConversationScreen Input {
        background: #0a0a0a;
        color: #39ff14;
        border: solid #39ff14;
    }

    ConversationScreen #message-container {
        height: 1fr;
        overflow-y: scroll;
    }

    ConversationScreen #input-container {
        height: 3;
        dock: bottom;
    }
    """

    def __init__(
        self,
        destination_hash: str,
        local_identity_hash: str,
        chat_protocol: ChatProtocol,
    ) -> None:
        """Initialize ConversationScreen.

        Args:
            destination_hash: Conversation partner's identity hash
            local_identity_hash: Local node's identity hash
            chat_protocol: ChatProtocol instance
        """
        super().__init__()
        self.destination_hash = destination_hash
        self.local_identity_hash = local_identity_hash
        self.chat_protocol = chat_protocol

    def compose(self) -> ComposeResult:
        """Compose conversation UI."""
        yield Header()
        yield Container(
            Static(f"CONVERSATION - {self.destination_hash[:16]}...", id="conv-title"),
            Vertical(
                id="message-container",
            ),
            Horizontal(
                Input(placeholder="Type message...", id="message-input"),
                id="input-container",
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        """Load message history on mount and mark messages as read."""
        self._mark_messages_as_read()
        self.refresh_messages()

    def _mark_messages_as_read(self) -> None:
        """Mark all pending incoming messages from this conversation as read.

        Updates database status from 'pending' to 'read' for messages where:
        - source is the conversation partner (destination_hash)
        - destination is the local identity (local_identity_hash)
        - status is 'pending'
        """
        # Get database engine from ChatProtocol
        if not hasattr(self.chat_protocol, "_db_engine"):
            return

        db_engine = self.chat_protocol._db_engine
        if db_engine is None:
            return

        with Session(db_engine) as session:
            # Find pending messages from this conversation partner to me
            messages_to_update = (
                session.query(Message)
                .filter(
                    Message.protocol_id == "chat",
                    Message.source_hash == self.destination_hash,
                    Message.destination_hash == self.local_identity_hash,
                    Message.status == "pending",
                )
                .all()
            )

            # Update status to 'read'
            for msg in messages_to_update:
                msg.status = "read"

            session.commit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle message input submission."""
        if event.input.id == "message-input":
            message = event.value.strip()
            if message:
                # Send message asynchronously
                self.run_worker(self.send_message(message), exclusive=True)
                # Clear input
                event.input.value = ""

    def refresh_messages(self) -> None:
        """Refresh message display."""
        container = self.query_one("#message-container", Vertical)
        container.remove_children()

        formatted = self.format_messages()

        for msg in formatted:
            # Determine if message is from me or them
            is_me = msg["source"] == self.local_identity_hash

            if is_me:
                msg_text = f"[bold green]ME[/]: {msg['content']}"
            else:
                msg_text = f"[cyan]{msg['source'][:8]}[/]: {msg['content']}"

            container.mount(Static(msg_text))

    def get_messages(self) -> list[Message]:
        """Retrieve message history from ChatProtocol.

        Returns:
            List of Message objects ordered by timestamp
        """
        return self.chat_protocol.get_conversation_history(
            self.local_identity_hash, self.destination_hash
        )

    def format_messages(self) -> list[dict[str, Any]]:
        """Format messages for display.

        Returns:
            List of dicts with source, content, timestamp
        """
        messages = self.get_messages()

        formatted = []
        for msg in messages:
            formatted.append(
                {
                    "source": msg.source_hash,
                    "content": msg.content or "[dim]No content[/]",
                    "timestamp": msg.timestamp,
                }
            )

        return formatted

    async def send_message(self, content: str) -> None:
        """Send message via ChatProtocol.

        Args:
            content: Message content to send
        """
        await self.chat_protocol.send_message(self.destination_hash, content)

        # Refresh message display if mounted
        if self.is_mounted:
            self.refresh_messages()
