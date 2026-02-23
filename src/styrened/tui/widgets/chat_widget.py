"""Chat widget for peer-to-peer messaging via IPCBridge.

Embeddable widget that provides message history display and send capability.
Used by both ConversationScreen (standalone) and MeshDeviceDetailScreen (tabbed).

Features:
- Real-time message events via IPC subscription (Phase 1)
- MessageBubble selection with arrow keys (Phase 2)
- Message retry for failed messages (Phase 3)
- Message delete with double-tap confirm (Phase 4)
- Full-text search within conversation (Phase 5)
- Reply threading with quote context (Phase 6)
"""

import asyncio
import logging
import time
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from styrened.ipc import IPCMessageType
from styrened.tui.widgets.highlighted_panel import get_color_cascade
from styrened.tui.widgets.message_bubble import STATUS_ICONS, MessageBubble

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ["ChatWidget", "STATUS_ICONS"]

# Timeout for IPC send_chat call (seconds)
_SEND_TIMEOUT = 15.0

# Polling fallback interval (seconds)
_POLL_INTERVAL = 10.0

# Delete confirmation timeout (seconds)
_DELETE_CONFIRM_TIMEOUT = 3.0

# Search debounce delay (seconds)
_SEARCH_DEBOUNCE = 0.3


class ChatWidget(Widget):
    """Widget for peer-to-peer chat messaging.

    Displays message history and provides input for sending messages.
    Uses reactive properties and IPCBridge for daemon communication.

    Attributes:
        peer_hash: Identity hash of the conversation partner.
        display_name: Optional display name for the peer.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "select_prev", "Prev Msg", show=False),
        Binding("down", "select_next", "Next Msg", show=False),
        Binding("escape", "escape_handler", "Back", show=False),
        Binding("tab", "toggle_focus", "Toggle Focus", show=False),
        Binding("R", "retry_message", "Retry", show=True),
        Binding("ctrl+r", "retry_all_failed", "Retry All", show=False),
        Binding("d", "delete_message", "Delete", show=True),
        Binding("slash", "open_search", "Search", show=True),
        Binding("r", "reply_to_message", "Reply", show=True),
    ]

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

    ChatWidget #chat-reply-bar {
        height: 1;
        dock: bottom;
        color: $primary;
        padding: 0 1;
        background: $surface;
    }

    ChatWidget #chat-search-bar {
        height: auto;
        dock: top;
        max-height: 3;
        padding: 0 1;
    }

    ChatWidget #search-input {
        width: 1fr;
    }

    ChatWidget #search-count {
        width: auto;
        min-width: 12;
        color: $panel;
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

    ChatWidget .message-bubble.--selected {
        background: $surface;
        text-style: bold;
    }

    ChatWidget .message-bubble.--failed {
        text-style: italic;
    }

    ChatWidget .hidden {
        display: none;
    }
    """

    def __init__(
        self,
        peer_hash: str,
        display_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.peer_hash = peer_hash
        self.display_name = display_name
        self._pending_messages: list[str] = []

        # Phase 1: Event tracking
        self._message_ids: list[int] = []
        self._last_event_time: float = 0.0
        self._poll_timer: Timer | None = None
        self._event_callback: Any = None

        # Phase 2: Selection
        self._selected_message_id: int | None = None

        # Phase 4: Delete confirmation
        self._delete_pending: int | None = None
        self._delete_timer: Timer | None = None

        # Phase 5: Search state
        self._search_active: bool = False
        self._search_timer: Timer | None = None

        # Phase 6: Reply state
        self._reply_to: dict[str, Any] | None = None

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
                "Daemon not connected \u2014 chat unavailable",
                classes="chat-no-bridge",
                id="chat-no-bridge",
            )
            return

        # Search bar (hidden by default)
        with Horizontal(id="chat-search-bar", classes="hidden"):
            yield Input(placeholder="Search messages...", id="search-input")
            yield Static("", id="search-count")

        yield Vertical(id="chat-message-container")

        # Reply context bar (hidden by default)
        yield Static("", id="chat-reply-bar", classes="hidden")

        yield Static("", id="chat-status")
        with Horizontal(id="chat-input-container"):
            yield Input(placeholder="Type message...", id="chat-input")

    def on_mount(self) -> None:
        """Load message history on mount, subscribe to events, and mark as read."""
        if self._ipc_bridge is not None:
            self.run_worker(self._initialize(), group="chat-init")

    async def _initialize(self) -> None:
        """Load messages, mark as read, and subscribe to events."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            await bridge.mark_read(self.peer_hash)
        except Exception as e:
            logger.warning(f"Failed to mark messages as read: {e}")

        await self._refresh_messages()

        # Phase 1: Subscribe to message events
        try:
            await bridge.subscribe_messages(peer_hashes=[self.peer_hash])
            self._event_callback = self._on_message_event
            bridge.on_event(IPCMessageType.EVENT_MESSAGE, self._event_callback)
            self._last_event_time = time.monotonic()
        except Exception as e:
            logger.warning(f"Failed to subscribe to message events: {e}")

        # Phase 1: Set up polling fallback
        self._poll_timer = self.set_interval(_POLL_INTERVAL, self._poll_fallback)

    def on_unmount(self) -> None:
        """Clean up event subscriptions on unmount."""
        bridge = self._ipc_bridge
        if bridge is not None:
            try:
                if self._event_callback is not None:
                    bridge.remove_event_handler(IPCMessageType.EVENT_MESSAGE, self._event_callback)
                    self._event_callback = None
            except Exception:
                pass

            try:
                self.run_worker(bridge.unsubscribe("messages"), group="chat-unsub")
            except Exception:
                pass

        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None

    def _on_message_event(self, event_data: dict[str, Any]) -> None:
        """Handle incoming message event from IPC subscription."""
        self._last_event_time = time.monotonic()
        event_type = event_data.get("event_type", "")
        peer_hash = event_data.get("peer_hash", "")

        # Only process events for our conversation
        if peer_hash != self.peer_hash:
            return

        if event_type == "new_message":
            try:
                self.app.call_from_thread(self._append_event_message, event_data)
            except RuntimeError:
                self._append_event_message(event_data)

        elif event_type == "delivery_status":
            msg_id = event_data.get("message_id", 0)
            new_status = event_data.get("status", "")
            try:
                self.app.call_from_thread(self._update_bubble_status, msg_id, new_status)
            except RuntimeError:
                self._update_bubble_status(msg_id, new_status)

    def _append_event_message(self, event_data: dict[str, Any]) -> None:
        """Append a new message from an event to the display."""
        self.run_worker(self._refresh_messages(), group="chat-refresh")

    def _update_bubble_status(self, message_id: int, new_status: str) -> None:
        """Update a specific message bubble's status icon."""
        try:
            container = self.query_one("#chat-message-container", Vertical)
        except Exception:
            return

        cascade = get_color_cascade()

        for child in container.query(MessageBubble):
            if child.message_id == message_id:
                child.update_status(new_status)
                icon = STATUS_ICONS.get(new_status, "")
                if child.is_outgoing:
                    if new_status == "delivered" and child.read_by_recipient:
                        icon = f"[{cascade.bright}]{STATUS_ICONS['read']}[/]"
                    elif new_status == "delivered":
                        icon = f"[{cascade.dim}]{STATUS_ICONS['delivered']}[/]"
                    msg_text = f"[{cascade.medium} bold]ME[/]: {child.content} {icon}"
                    child.update(msg_text)
                return

    def _poll_fallback(self) -> None:
        """Polling fallback when no events received recently."""
        elapsed = time.monotonic() - self._last_event_time
        if elapsed >= _POLL_INTERVAL and self.is_mounted:
            self.run_worker(self._refresh_messages(), group="chat-poll")

    def _set_status(self, text: str) -> None:
        """Update the status line below messages."""
        try:
            status = self.query_one("#chat-status", Static)
            status.update(text)
        except Exception:
            pass

    async def _refresh_messages(self) -> None:
        """Refresh message display from IPCBridge (incremental)."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            messages = await bridge.get_messages(self.peer_hash)
        except Exception as e:
            logger.warning(f"Failed to load messages: {e}")
            self._set_status(f"[red]Failed to load messages: {e}[/]")
            messages = []

        if not messages and self._pending_messages:
            return

        try:
            container = self.query_one("#chat-message-container", Vertical)
        except Exception:
            return

        new_ids = [msg.get("id", 0) for msg in messages]

        if new_ids != self._message_ids:
            await container.remove_children()
            self._message_ids = new_ids
            self._pending_messages.clear()

            cascade = get_color_cascade()

            if not messages:
                await container.mount(Static("[dim]No messages yet[/]", classes="chat-no-messages"))
                return

            for msg in messages:
                bubble = self._create_bubble(msg, cascade)
                await container.mount(bubble)

                if msg.get("id") == self._selected_message_id:
                    bubble.select()

            container.scroll_end(animate=False)
        else:
            cascade = get_color_cascade()
            for msg in messages:
                msg_id = msg.get("id", 0)
                new_status = msg.get("status", "")
                for child in container.query(MessageBubble):
                    if child.message_id == msg_id and child.status != new_status:
                        self._update_bubble_status(msg_id, new_status)
                        break

    def _create_bubble(
        self,
        msg: dict[str, Any],
        cascade: Any,
    ) -> MessageBubble:
        """Create a MessageBubble from message data."""
        is_outgoing = msg.get("is_outgoing", False)
        content = msg.get("content") or "[dim]No content[/]"
        status = msg.get("status", "")
        lxmf_hash = msg.get("lxmf_hash")
        reply_to_hash = msg.get("reply_to_hash")
        read_by_recipient = msg.get("read_by_recipient", False)
        msg_id = msg.get("id", 0)
        timestamp = msg.get("timestamp", 0.0)

        parts: list[str] = []

        # Phase 6: Reply context
        if reply_to_hash:
            replied_preview = self._find_reply_preview(reply_to_hash)
            parts.append(f'[{cascade.dim}]\u25b8 replying to: "{replied_preview}"[/]')

        if is_outgoing:
            status_icon = STATUS_ICONS.get(status, "")
            if read_by_recipient and status in ("delivered", "read"):
                status_icon = f"[{cascade.bright}]{STATUS_ICONS['read']}[/]"
            elif status == "delivered":
                status_icon = f"[{cascade.dim}]{STATUS_ICONS['delivered']}[/]"

            parts.append(f"[{cascade.medium} bold]ME[/]: {content} {status_icon}")
            css_class = "chat-msg-outgoing"
        else:
            sender = self.display_name or self.peer_hash[:8]
            parts.append(f"[{cascade.dim}]{sender}[/]: {content}")
            css_class = "chat-msg-incoming"

        msg_text = "\n".join(parts)

        return MessageBubble(
            msg_text,
            message_id=msg_id,
            is_outgoing=is_outgoing,
            status=status,
            lxmf_hash=lxmf_hash,
            reply_to_hash=reply_to_hash,
            content=content,
            timestamp=timestamp,
            read_by_recipient=read_by_recipient,
            classes=css_class,
        )

    def _find_reply_preview(self, lxmf_hash: str) -> str:
        """Find a message preview by LXMF hash for reply context."""
        try:
            container = self.query_one("#chat-message-container", Vertical)
            for child in container.query(MessageBubble):
                if child.lxmf_hash == lxmf_hash:
                    preview = child.content[:40]
                    if len(child.content) > 40:
                        preview += "..."
                    return preview
        except Exception:
            pass
        return f"#{lxmf_hash[:8]}..."

    # -------------------------------------------------------------------------
    # Input handling
    # -------------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle message input submission."""
        if event.input.id == "search-input":
            return

        if event.input.id != "chat-input":
            return

        message = event.value.strip()
        if not message:
            return

        event.input.value = ""

        self._pending_messages.append(message)
        self._show_optimistic_message(message)

        kwargs: dict[str, Any] = {}
        if self._reply_to is not None:
            kwargs["reply_to_hash"] = self._reply_to.get("lxmf_hash")
            self._clear_reply()

        self.run_worker(
            self._send_message(message, **kwargs),
            group="chat-send",
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes with debounce."""
        if event.input.id != "search-input":
            return

        if self._search_timer is not None:
            self._search_timer.stop()
            self._search_timer = None

        query = event.value.strip()
        if len(query) < 2:
            return

        self._search_timer = self.set_timer(
            _SEARCH_DEBOUNCE,
            lambda: self.run_worker(self._execute_search(query), group="chat-search"),
        )

    def _show_optimistic_message(self, content: str) -> None:
        """Show sent message immediately in the UI before IPC confirms."""
        try:
            container = self.query_one("#chat-message-container", Vertical)
        except Exception:
            return

        cascade = get_color_cascade()

        for child in list(container.query(".chat-no-messages")):
            child.remove()

        msg_text = f"[{cascade.medium} bold]ME[/]: {content} \u23f3"
        bubble = MessageBubble(
            msg_text,
            message_id=0,
            is_outgoing=True,
            status="pending",
            content=content,
            classes="chat-msg-outgoing",
        )
        container.mount(bubble)
        container.scroll_end(animate=False)

        self._set_status("[dim]Sending...[/]")

    async def _send_message(self, content: str, **kwargs: Any) -> None:
        """Send message via IPCBridge."""
        bridge = self._ipc_bridge
        if bridge is None:
            self._set_status("[red]Chat requires daemon connection[/]")
            self.notify("Chat requires daemon connection", severity="error")
            return

        try:
            result = await asyncio.wait_for(
                bridge.send_chat(self.peer_hash, content, **kwargs),
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

        await asyncio.sleep(0.5)

        if self.is_mounted:
            await self._refresh_messages()
            self._set_status("")

    def _update_optimistic_status(self, content: str, status: str) -> None:
        """Update the status icon on a pending optimistic message."""
        try:
            container = self.query_one("#chat-message-container", Vertical)
        except Exception:
            return

        cascade = get_color_cascade()
        icon = STATUS_ICONS.get(status, "")

        for child in reversed(list(container.query(".chat-msg-outgoing"))):
            if isinstance(child, (Static, MessageBubble)):
                msg_text = f"[{cascade.medium} bold]ME[/]: {content} {icon}"
                child.update(msg_text)
                if isinstance(child, MessageBubble):
                    child.update_status(status)
                return

    # -------------------------------------------------------------------------
    # Phase 2: Message selection
    # -------------------------------------------------------------------------

    def _get_bubbles(self) -> list[MessageBubble]:
        """Get all message bubbles in order."""
        try:
            container = self.query_one("#chat-message-container", Vertical)
            return list(container.query(MessageBubble))
        except Exception:
            return []

    def _get_selected_bubble(self) -> MessageBubble | None:
        """Get the currently selected bubble."""
        if self._selected_message_id is None:
            return None
        for bubble in self._get_bubbles():
            if bubble.message_id == self._selected_message_id:
                return bubble
        return None

    def _select_bubble(self, bubble: MessageBubble | None) -> None:
        """Select a specific bubble, deselecting any current selection."""
        current = self._get_selected_bubble()
        if current is not None:
            current.deselect()

        if bubble is not None:
            bubble.select()
            self._selected_message_id = bubble.message_id
            import datetime

            ts = datetime.datetime.fromtimestamp(bubble.timestamp).strftime("%H:%M:%S")
            method = f" [{bubble.status}]" if bubble.status else ""
            self._set_status(f"[dim]#{bubble.message_id} {ts}{method}[/]")
        else:
            self._selected_message_id = None
            self._set_status("")

    def action_select_prev(self) -> None:
        """Move selection to previous message."""
        try:
            chat_input = self.query_one("#chat-input", Input)
            if chat_input.has_focus:
                return
        except Exception:
            pass

        bubbles = self._get_bubbles()
        if not bubbles:
            return

        if self._selected_message_id is None:
            self._select_bubble(bubbles[-1])
            return

        for i, b in enumerate(bubbles):
            if b.message_id == self._selected_message_id:
                if i > 0:
                    self._select_bubble(bubbles[i - 1])
                return

    def action_select_next(self) -> None:
        """Move selection to next message."""
        try:
            chat_input = self.query_one("#chat-input", Input)
            if chat_input.has_focus:
                return
        except Exception:
            pass

        bubbles = self._get_bubbles()
        if not bubbles:
            return

        if self._selected_message_id is None:
            self._select_bubble(bubbles[0])
            return

        for i, b in enumerate(bubbles):
            if b.message_id == self._selected_message_id:
                if i < len(bubbles) - 1:
                    self._select_bubble(bubbles[i + 1])
                return

    def action_toggle_focus(self) -> None:
        """Toggle focus between message list and input."""
        try:
            chat_input = self.query_one("#chat-input", Input)
            if chat_input.has_focus:
                chat_input.blur()
            else:
                chat_input.focus()
        except Exception:
            pass

    def action_escape_handler(self) -> None:
        """Layered escape: cancel reply -> close search -> deselect -> pop screen."""
        if self._reply_to is not None:
            self._clear_reply()
            return

        if self._search_active:
            self._close_search()
            return

        if self._selected_message_id is not None:
            self._select_bubble(None)
            return

        self.app.pop_screen()

    # -------------------------------------------------------------------------
    # Phase 3: Message retry
    # -------------------------------------------------------------------------

    def action_retry_message(self) -> None:
        """Retry sending a failed message (R key)."""
        bubble = self._get_selected_bubble()
        if bubble is None or not bubble.is_failed:
            return

        self.run_worker(self._retry_single(bubble.message_id), group="chat-retry")

    async def _retry_single(self, message_id: int) -> None:
        """Retry a single failed message via IPC."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        self._update_bubble_status(message_id, "pending")

        try:
            await bridge.retry_message(message_id)
            self._set_status("[green]Retry sent[/]")
        except Exception as e:
            logger.error(f"Retry failed: {e}")
            self._update_bubble_status(message_id, "failed")
            self._set_status(f"[red]Retry failed: {e}[/]")

    def action_retry_all_failed(self) -> None:
        """Retry all failed messages (ctrl+r)."""
        failed = [b for b in self._get_bubbles() if b.is_failed]
        if not failed:
            return

        for bubble in failed:
            self.run_worker(self._retry_single(bubble.message_id), group="chat-retry")

    # -------------------------------------------------------------------------
    # Phase 4: Message delete (double-tap)
    # -------------------------------------------------------------------------

    def action_delete_message(self) -> None:
        """Delete selected message with double-tap confirmation."""
        bubble = self._get_selected_bubble()
        if bubble is None:
            return

        if self._delete_pending == bubble.message_id:
            self._cancel_delete_timer()
            self.run_worker(self._execute_delete(bubble.message_id), group="chat-delete")
        else:
            self._delete_pending = bubble.message_id
            self._set_status("[yellow]Press d again to delete[/]")
            self._cancel_delete_timer()
            self._delete_timer = self.set_timer(
                _DELETE_CONFIRM_TIMEOUT, self._cancel_delete_pending
            )

    def _cancel_delete_timer(self) -> None:
        """Cancel any active delete confirmation timer."""
        if self._delete_timer is not None:
            self._delete_timer.stop()
            self._delete_timer = None

    def _cancel_delete_pending(self) -> None:
        """Cancel delete pending state (timeout or other action)."""
        self._delete_pending = None
        self._cancel_delete_timer()
        self._set_status("")

    async def _execute_delete(self, message_id: int) -> None:
        """Execute message deletion via IPC."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        self._delete_pending = None

        try:
            await bridge.delete_message(message_id)
            for bubble in self._get_bubbles():
                if bubble.message_id == message_id:
                    await bubble.remove()
                    break

            if message_id in self._message_ids:
                self._message_ids.remove(message_id)

            self._selected_message_id = None
            self._set_status("[dim]Message deleted[/]")
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            self._set_status(f"[red]Delete failed: {e}[/]")

    # -------------------------------------------------------------------------
    # Phase 5: Full-text search
    # -------------------------------------------------------------------------

    def action_open_search(self) -> None:
        """Toggle search bar visibility."""
        if self._search_active:
            self._close_search()
        else:
            self._open_search()

    def _open_search(self) -> None:
        """Show search bar and focus it."""
        self._search_active = True
        try:
            bar = self.query_one("#chat-search-bar")
            bar.remove_class("hidden")
            search_input = self.query_one("#search-input", Input)
            search_input.focus()
        except Exception:
            pass

    def _close_search(self) -> None:
        """Hide search bar and restore normal view."""
        self._search_active = False
        try:
            bar = self.query_one("#chat-search-bar")
            bar.add_class("hidden")
            search_input = self.query_one("#search-input", Input)
            search_input.value = ""
            count = self.query_one("#search-count", Static)
            count.update("")
        except Exception:
            pass

        self.run_worker(self._refresh_messages(), group="chat-refresh")

    async def _execute_search(self, query: str) -> None:
        """Execute search via IPC and display results."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            results = await bridge.search_messages(query=query, peer_hash=self.peer_hash)
        except Exception as e:
            logger.warning(f"Search failed: {e}")
            self._set_status(f"[red]Search failed: {e}[/]")
            return

        try:
            count_widget = self.query_one("#search-count", Static)
            count_widget.update(f"{len(results)} results")
        except Exception:
            pass

        try:
            container = self.query_one("#chat-message-container", Vertical)
            await container.remove_children()

            cascade = get_color_cascade()

            if not results:
                await container.mount(
                    Static(f"[dim]No results for '{query}'[/]", classes="chat-no-messages")
                )
                return

            for msg in results:
                bubble = self._create_bubble(msg, cascade)
                await container.mount(bubble)

        except Exception:
            pass

        self._set_status(f"[dim]{len(results)} results for '{query}'[/]")

    # -------------------------------------------------------------------------
    # Phase 6: Reply threading
    # -------------------------------------------------------------------------

    def action_reply_to_message(self) -> None:
        """Set reply context from selected message (r key)."""
        bubble = self._get_selected_bubble()
        if bubble is None or not bubble.lxmf_hash:
            return

        self._reply_to = {
            "lxmf_hash": bubble.lxmf_hash,
            "content": bubble.content,
            "message_id": bubble.message_id,
        }

        preview = bubble.content[:40]
        if len(bubble.content) > 40:
            preview += "..."

        try:
            reply_bar = self.query_one("#chat-reply-bar", Static)
            reply_bar.update(f"\u21a9 Replying to: {preview}  [dim]\u00d7 esc to cancel[/]")
            reply_bar.remove_class("hidden")
        except Exception:
            pass

        try:
            self.query_one("#chat-input", Input).focus()
        except Exception:
            pass

    def _clear_reply(self) -> None:
        """Clear reply context."""
        self._reply_to = None
        try:
            reply_bar = self.query_one("#chat-reply-bar", Static)
            reply_bar.update("")
            reply_bar.add_class("hidden")
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Worker error handling
    # -------------------------------------------------------------------------

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
