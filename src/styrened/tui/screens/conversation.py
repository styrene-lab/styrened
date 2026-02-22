"""ConversationScreen - Message thread for chat conversations.

This screen displays a message thread with a specific conversation partner
and allows sending new messages. Uses IPCBridge for daemon communication
and theme variables for styling.
"""

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input, Static

from styrened.tui.widgets.highlighted_panel import get_color_cascade

logger = logging.getLogger(__name__)

# Delivery status indicators
STATUS_ICONS = {
    "pending": "\u23f3",   # hourglass
    "sent": "\u2713",      # check
    "delivered": "\u2713\u2713",  # double check
    "failed": "\u2717",    # cross
    "read": "\u2713\u2713",
}


class ConversationScreen(Screen[None]):
    """Conversation screen showing message thread.

    Displays message history with a conversation partner and
    provides input field for sending new messages.

    All data is loaded via IPCBridge from the daemon.
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

    ConversationScreen Input {
        background: $background;
        color: $primary;
        border: solid $border;
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

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        """Compose conversation UI."""
        title = self.display_name or f"{self.peer_hash[:16]}..."
        yield Header()
        yield Container(
            Static(f"CONVERSATION - {title}", id="conv-title"),
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
        self.run_worker(self._initialize())

    async def _initialize(self) -> None:
        """Load messages and mark as read."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            await bridge.mark_read(self.peer_hash)
        except Exception as e:
            logger.warning(f"Failed to mark messages as read: {e}")

        await self._refresh_messages()

    async def _refresh_messages(self) -> None:
        """Refresh message display from IPCBridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            messages = await bridge.get_messages(self.peer_hash)
        except Exception as e:
            logger.warning(f"Failed to load messages: {e}")
            messages = []

        container = self.query_one("#message-container", Vertical)
        container.remove_children()

        cascade = get_color_cascade()

        for msg in messages:
            is_outgoing = msg.get("is_outgoing", False)
            content = msg.get("content") or "[dim]No content[/]"
            status = msg.get("status", "")
            status_icon = STATUS_ICONS.get(status, "")

            if is_outgoing:
                msg_text = f"[{cascade.medium} bold]ME[/]: {content} {status_icon}"
            else:
                sender = self.display_name or self.peer_hash[:8]
                msg_text = f"[{cascade.dim}]{sender}[/]: {content}"

            container.mount(Static(msg_text))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle message input submission."""
        if event.input.id == "message-input":
            message = event.value.strip()
            if message:
                self.run_worker(self._send_message(message), exclusive=True)
                event.input.value = ""

    async def _send_message(self, content: str) -> None:
        """Send message via IPCBridge.

        Args:
            content: Message content to send
        """
        bridge = self._ipc_bridge
        if bridge is None:
            self.notify("Chat requires daemon mode", severity="warning")
            return

        try:
            await bridge.send_chat(self.peer_hash, content)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            self.notify(f"Send failed: {e}", severity="error")
            return

        if self.is_mounted:
            await self._refresh_messages()
