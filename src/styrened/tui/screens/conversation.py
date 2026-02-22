"""ConversationScreen - Message thread for chat conversations.

This screen displays a message thread with a specific conversation partner
and allows sending new messages. Delegates to ChatWidget for all messaging
logic.
"""

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from styrened.tui.widgets.chat_widget import ChatWidget


class ConversationScreen(Screen[None]):
    """Conversation screen showing message thread.

    Displays message history with a conversation partner and
    provides input field for sending new messages.

    All messaging logic is handled by the embedded ChatWidget.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    CSS = """
    ConversationScreen {
        background: $background;
    }

    ConversationScreen Static {
        color: $primary;
        background: $background;
    }

    ConversationScreen #conv-content {
        height: 1fr;
    }
    """

    def __init__(
        self,
        peer_hash: str,
        display_name: str | None = None,
    ) -> None:
        """Initialize ConversationScreen.

        Args:
            peer_hash: Conversation partner's identity hash
            display_name: Optional display name for the peer
        """
        super().__init__()
        self.peer_hash = peer_hash
        self.display_name = display_name

    def compose(self) -> ComposeResult:
        """Compose conversation UI."""
        title = self.display_name or f"{self.peer_hash[:16]}..."
        yield Header()
        with Container(id="conv-content"):
            yield Static(f"CONVERSATION - {title}", id="conv-title")
            yield ChatWidget(
                peer_hash=self.peer_hash,
                display_name=self.display_name,
                id="chat-widget",
            )
        yield Footer()
