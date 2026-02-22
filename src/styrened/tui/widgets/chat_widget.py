"""Chat widget for peer-to-peer messaging via IPCBridge.

Embeddable widget that provides message history display and send capability.
Used by both ConversationScreen (standalone) and MeshDeviceDetailScreen (tabbed).
"""

import asyncio
import logging
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from styrened.tui.widgets.highlighted_panel import get_color_cascade

logger = logging.getLogger(__name__)

# Timeout for IPC send_chat call (seconds)
_SEND_TIMEOUT = 15.0

# Delivery status indicators
STATUS_ICONS = {
    "pending": "\u23f3",  # hourglass
    "sent": "\u2713",  # check
    "delivered": "\u2713\u2713",  # double check
    "failed": "\u2717",  # cross
    "read": "\u2713\u2713",
}


class ChatWidget(Widget):
    """Widget for peer-to-peer chat messaging.

    Displays message history and provides input for sending messages.
    Uses reactive properties and IPCBridge for daemon communication.

    Shows a visible "Daemon not connected" message when the bridge
    is unavailable instead of silently failing.

    Attributes:
        peer_hash: Identity hash of the conversation partner.
        display_name: Optional display name for the peer.
    """

    loading: reactive[bool] = reactive(False)

    DEFAULT_CSS = """
    ChatWidget {
        height: 1fr;
        layout: vertical;
    }

    ChatWidget #chat-message-container {
        height: 1fr;
        overflow-y: scroll;
    }

    ChatWidget #chat-input-container {
        height: auto;
        dock: bottom;
        max-height: 5;
    }

    ChatWidget #chat-input-container Input {
        width: 1fr;
    }

    ChatWidget #chat-status {
        height: 1;
        dock: bottom;
        color: $panel;
        padding: 0 1;
    }

    ChatWidget .chat-no-bridge {
        color: $warning;
        text-style: bold italic;
        padding: 1;
    }

    ChatWidget .chat-no-messages {
        color: $panel;
        padding: 1;
    }

    ChatWidget .chat-msg-outgoing {
        padding: 0 1;
    }

    ChatWidget .chat-msg-incoming {
        padding: 0 1;
    }
    """

    def __init__(
        self,
        peer_hash: str,
        display_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize ChatWidget.

        Args:
            peer_hash: Conversation partner's identity hash.
            display_name: Optional display name for the peer.
            **kwargs: Additional widget arguments.
        """
        super().__init__(**kwargs)
        self.peer_hash = peer_hash
        self.display_name = display_name
        self._pending_messages: list[str] = []

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app._lifecycle.ipc_bridge  # type: ignore[attr-defined]
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        """Compose chat widget layout."""
        bridge = self._ipc_bridge

        if bridge is None:
            yield Static(
                "Daemon not connected — chat unavailable",
                classes="chat-no-bridge",
                id="chat-no-bridge",
            )
            return

        yield Vertical(id="chat-message-container")
        yield Static("", id="chat-status")
        with Horizontal(id="chat-input-container"):
            yield Input(placeholder="Type message...", id="chat-input")

    def on_mount(self) -> None:
        """Load message history on mount and mark messages as read."""
        if self._ipc_bridge is not None:
            self.run_worker(self._initialize(), group="chat-init")

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

    def _set_status(self, text: str) -> None:
        """Update the status line below messages."""
        try:
            status = self.query_one("#chat-status", Static)
            status.update(text)
        except Exception:
            pass

    async def _refresh_messages(self) -> None:
        """Refresh message display from IPCBridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            messages = await bridge.get_messages(self.peer_hash)
        except Exception as e:
            logger.warning(f"Failed to load messages: {e}")
            self._set_status(f"[red]Failed to load messages: {e}[/]")
            messages = []

        # If server returned no messages but we have pending optimistic ones,
        # keep the optimistic display — don't overwrite with "No messages yet"
        if not messages and self._pending_messages:
            return

        try:
            container = self.query_one("#chat-message-container", Vertical)
        except Exception:
            return

        await container.remove_children()

        cascade = get_color_cascade()

        if not messages:
            await container.mount(
                Static("[dim]No messages yet[/]", classes="chat-no-messages")
            )
            return

        # Server returned real messages — clear pending optimistic list
        self._pending_messages.clear()

        for msg in messages:
            is_outgoing = msg.get("is_outgoing", False)
            content = msg.get("content") or "[dim]No content[/]"
            status = msg.get("status", "")
            status_icon = STATUS_ICONS.get(status, "")

            if is_outgoing:
                msg_text = f"[{cascade.medium} bold]ME[/]: {content} {status_icon}"
                css_class = "chat-msg-outgoing"
            else:
                sender = self.display_name or self.peer_hash[:8]
                msg_text = f"[{cascade.dim}]{sender}[/]: {content}"
                css_class = "chat-msg-incoming"

            await container.mount(Static(msg_text, classes=css_class))

        container.scroll_end(animate=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle message input submission."""
        if event.input.id != "chat-input":
            return

        message = event.value.strip()
        if not message:
            return

        event.input.value = ""

        # Track as pending optimistic message
        self._pending_messages.append(message)

        # Show message immediately in the UI
        self._show_optimistic_message(message)

        # Send via IPC in background
        self.run_worker(
            self._send_message(message),
            group="chat-send",
        )

    def _show_optimistic_message(self, content: str) -> None:
        """Show sent message immediately in the UI before IPC confirms."""
        try:
            container = self.query_one("#chat-message-container", Vertical)
        except Exception:
            logger.warning("Chat container not found for optimistic message")
            return

        cascade = get_color_cascade()

        # Remove "No messages yet" placeholder if present
        for child in list(container.query(".chat-no-messages")):
            child.remove()

        msg_text = f"[{cascade.medium} bold]ME[/]: {content} \u23f3"
        container.mount(Static(msg_text, classes="chat-msg-outgoing"))
        container.scroll_end(animate=False)

        self._set_status("[dim]Sending...[/]")

    async def _send_message(self, content: str) -> None:
        """Send message via IPCBridge.

        Args:
            content: Message content to send.
        """
        bridge = self._ipc_bridge
        if bridge is None:
            self._set_status("[red]Chat requires daemon connection[/]")
            self.notify("Chat requires daemon connection", severity="error")
            return

        try:
            result = await asyncio.wait_for(
                bridge.send_chat(self.peer_hash, content),
                timeout=_SEND_TIMEOUT,
            )
            logger.info(f"Message sent to {self.peer_hash[:8]}...: {result}")
            self._set_status("[green]Sent[/]")
            self._update_optimistic_status(content, "sent")
        except TimeoutError:
            logger.error(f"Send timed out after {_SEND_TIMEOUT}s to {self.peer_hash[:8]}...")
            self._set_status(f"[red]Send timed out ({_SEND_TIMEOUT:.0f}s)[/]")
            self._update_optimistic_status(content, "failed")
            self.notify(
                f"Message send timed out after {_SEND_TIMEOUT:.0f}s",
                title="Send Timeout",
                severity="warning",
            )
            return
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            self._set_status(f"[red]Send failed: {e}[/]")
            self._update_optimistic_status(content, "failed")
            self.notify(f"Send failed: {e}", title="Chat Error", severity="error")
            return

        # Delay briefly to let daemon commit, then refresh
        await asyncio.sleep(0.5)

        if self.is_mounted:
            await self._refresh_messages()
            self._set_status("")

    def _update_optimistic_status(self, content: str, status: str) -> None:
        """Update the status icon on a pending optimistic message.

        Args:
            content: Message content to match.
            status: New status ("sent", "failed").
        """
        try:
            container = self.query_one("#chat-message-container", Vertical)
        except Exception:
            return

        cascade = get_color_cascade()
        icon = STATUS_ICONS.get(status, "")

        # Find the most recent outgoing message matching content
        for child in reversed(list(container.query(".chat-msg-outgoing"))):
            if isinstance(child, Static):
                # Update the last outgoing message (assumed to be the one we sent)
                msg_text = f"[{cascade.medium} bold]ME[/]: {content} {icon}"
                child.update(msg_text)
                return

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker state changes to surface errors."""
        if event.state == WorkerState.ERROR:
            logger.error(f"Chat worker error: {event.worker.error}")
            self._set_status(f"[red]Error: {event.worker.error}[/]")
            self.notify(
                f"Chat error: {event.worker.error}",
                title="Chat Error",
                severity="error",
            )
