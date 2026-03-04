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
import atexit
import datetime
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
from textual import work
from textual.worker import Worker, WorkerState

from styrened.ipc import IPCMessageType
from styrened.tui.widgets.highlighted_panel import get_color_cascade
from styrened.tui.widgets.message_bubble import (
    ATTACHMENT_ICONS,
    STATUS_ICONS,
    MessageBubble,
    _human_size,
)

try:
    from styrened.tui.menubar.clipboard import has_clipboard_image, read_clipboard_attachment
except ImportError:
    # Not on macOS or clipboard deps missing
    def has_clipboard_image() -> bool:  # type: ignore[misc]
        return False

    def read_clipboard_attachment():  # type: ignore[misc]
        return None

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = ["ChatWidget", "STATUS_ICONS"]

# Track temp files for cleanup on exit
_TEMP_FILES: set[str] = set()


def _cleanup_temp_files() -> None:
    """Remove temp attachment files on process exit."""
    import os

    for path in list(_TEMP_FILES):
        try:
            os.unlink(path)
        except OSError:
            pass
    _TEMP_FILES.clear()


atexit.register(_cleanup_temp_files)

# Timeout for IPC send_chat call (seconds)
_SEND_TIMEOUT = 30.0

# Polling fallback interval (seconds)
_POLL_INTERVAL = 10.0

# Delete confirmation timeout (seconds)
_DELETE_CONFIRM_TIMEOUT = 3.0

# Search debounce delay (seconds)
_SEARCH_DEBOUNCE = 0.3


class ChatWidget(Widget, can_focus=True):
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
        Binding("ctrl+r", "retry_all_failed", "Retry All", show=True, priority=True),
        Binding("d", "delete_message", "Delete", show=True),
        Binding("slash", "open_search", "Search", show=True),
        Binding("r", "reply_to_message", "Reply", show=True),
        Binding("y", "copy_message", "Copy", show=True),
        Binding("o", "open_attachment", "Open", show=True),
        Binding("a", "attach_file", "Attach", show=True),
        Binding("ctrl+y", "attach_clipboard", "📋 Attach", priority=True),
        Binding("ctrl+v", "paste_attachment", "Paste", show=False),
        Binding("B", "block_peer", "Block", show=True),
    ]

    loading: reactive[bool] = reactive(False)
    security_tier: reactive[str] = reactive("")

    DEFAULT_CSS = """
    ChatWidget {
        height: 1fr;
        layout: vertical;
    }

    ChatWidget #chat-message-container {
        height: 1fr;
        overflow-y: scroll;
        scrollbar-background: transparent;
        scrollbar-color: $border;
        padding: 0 1;
    }

    ChatWidget #chat-input-bar {
        height: 3;
        dock: bottom;
        border-top: solid $border;
    }

    ChatWidget #chat-input-bar #chat-input {
        width: 1fr;
        border: none !important;
        background: transparent;
        padding: 0 1;
        height: 1;
    }

    ChatWidget #chat-input-bar #chat-input:focus {
        border: none !important;
        background: transparent;
    }

    ChatWidget #chat-input-bar #send-hint {
        width: auto;
        min-width: 4;
        color: $panel;
        padding: 0 1;
        height: 1;
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
        border-top: solid $border;
    }

    ChatWidget #chat-search-bar {
        height: auto;
        dock: top;
        max-height: 3;
        padding: 0 1;
        border-bottom: solid $border;
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
        padding: 1 2;
    }

    ChatWidget .chat-no-messages {
        color: $panel;
        padding: 1 2;
    }

    ChatWidget .message-bubble.--outgoing {
        margin-left: 20;
        text-align: right;
        padding: 0 1;
    }

    ChatWidget .message-bubble.--incoming {
        margin-right: 20;
        padding: 0 1;
    }

    ChatWidget .message-bubble.--selected .bubble-text {
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

        # Attachment state
        self._pending_attachment: dict[str, Any] | None = None

        # Tracks whether the status bar is showing the idle tier label
        self._status_is_tier: bool = False

        # Tracks the last displayed date for date separator continuity
        self._last_displayed_date: str | None = None

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

        # Search bar (hidden and disabled by default to prevent focus stealing)
        with Horizontal(id="chat-search-bar", classes="hidden"):
            yield Input(placeholder="Search messages...", id="search-input", disabled=True)
            yield Static("", id="search-count")

        yield Vertical(id="chat-message-container")

        # Reply context bar (hidden by default)
        yield Static("", id="chat-reply-bar", classes="hidden")

        yield Static("", id="chat-status")
        with Horizontal(id="chat-input-bar"):
            yield Input(placeholder="Type a message…", id="chat-input")
            yield Static("[dim]⏎[/]", id="send-hint")

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
                    elif new_status == "failed":
                        icon = f"[red bold]{STATUS_ICONS['failed']}[/]"
                    ts_str = datetime.datetime.fromtimestamp(child.timestamp).strftime("%H:%M") if child.timestamp else ""
                    if new_status == "failed":
                        msg_text = f"[red italic]{child.raw_content}[/] {icon} [{cascade.dim}]{ts_str}[/]"
                    else:
                        msg_text = f"{child.raw_content} {icon} [{cascade.dim}]{ts_str}[/]"
                    child.update_text(msg_text)
                return

    def _poll_fallback(self) -> None:
        """Polling fallback when no events received recently."""
        elapsed = time.monotonic() - self._last_event_time
        if elapsed >= _POLL_INTERVAL and self.is_mounted:
            self.run_worker(self._refresh_messages(), group="chat-poll")

    def _set_status(self, text: str) -> None:
        """Update the status line below messages.

        When *text* is empty, the security-tier idle indicator is restored.
        """
        try:
            status = self.query_one("#chat-status", Static)
            if text:
                status.update(text)
                self._status_is_tier = False
            else:
                status.update(self._tier_label())
                self._status_is_tier = True
        except Exception:
            pass

    def _tier_label(self) -> str:
        """Build the idle security-tier Rich markup string."""
        if not self.security_tier:
            return ""
        cascade = get_color_cascade()
        color = cascade.bright if "PQC" in self.security_tier.upper() else cascade.medium
        return f"[{color}]{self.security_tier}[/]"

    def watch_security_tier(self, value: str) -> None:
        """Update the idle status bar when the security tier changes."""
        try:
            status = self.query_one("#chat-status", Static)
            # Only overwrite if status bar is empty or already showing a tier
            if not str(status.renderable) or self._status_is_tier:
                status.update(self._tier_label())
                self._status_is_tier = True
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
            old_ids_set = set(self._message_ids)
            cascade = get_color_cascade()

            if not self._message_ids:
                # First load or empty → full rebuild
                await container.remove_children()
                self._message_ids = new_ids
                self._last_displayed_date = None
                self._pending_messages.clear()

                if not messages:
                    await container.mount(Static("[dim]No messages yet[/]", classes="chat-no-messages"))
                    return

                last_date: str | None = None
                for msg in messages:
                    sep, last_date = self._date_separator_if_needed(
                        msg.get("timestamp", 0.0), last_date, cascade
                    )
                    if sep:
                        await container.mount(sep)
                    bubble = self._create_bubble(msg, cascade)
                    await container.mount(bubble)

                    if msg.get("id") == self._selected_message_id:
                        bubble.select()

                container.scroll_end(animate=False)
            else:
                new_ids_set = set(new_ids)
                deleted_ids = old_ids_set - new_ids_set

                if deleted_ids:
                    # Messages were deleted — full rebuild needed
                    self._message_ids = []
                    self._last_displayed_date = None
                    await self._refresh_messages()
                    return

                # Remove optimistic bubbles (id=0) before appending real ones
                for child in list(container.query(MessageBubble)):
                    if child.message_id == 0:
                        child.remove()

                # Incremental — only append new messages
                appended = False
                # Determine last date from existing messages for date separator continuity
                last_date = self._last_displayed_date
                for msg in messages:
                    msg_id = msg.get("id", 0)
                    if msg_id not in old_ids_set:
                        sep, last_date = self._date_separator_if_needed(
                            msg.get("timestamp", 0.0), last_date, cascade
                        )
                        if sep:
                            await container.mount(sep)
                        bubble = self._create_bubble(msg, cascade)
                        await container.mount(bubble)
                        appended = True

                self._message_ids = new_ids
                self._pending_messages.clear()

                if appended:
                    container.scroll_end(animate=False)
        else:
            # Same IDs — just update statuses in-place
            cascade = get_color_cascade()
            for msg in messages:
                msg_id = msg.get("id", 0)
                new_status = msg.get("status", "")
                for child in container.query(MessageBubble):
                    if child.message_id == msg_id and child.status != new_status:
                        self._update_bubble_status(msg_id, new_status)
                        break

    def _date_separator_if_needed(
        self,
        timestamp: float,
        last_date: str | None,
        cascade: Any,
    ) -> tuple[Static | None, str | None]:
        """Create a date separator widget if the message date differs from last_date.

        Returns (separator_widget_or_None, date_string).
        """
        if not timestamp:
            return None, last_date
        msg_date = datetime.datetime.fromtimestamp(timestamp)
        today = datetime.datetime.now().date()
        yesterday = today - datetime.timedelta(days=1)

        if msg_date.date() == today:
            date_str = "Today"
        elif msg_date.date() == yesterday:
            date_str = "Yesterday"
        else:
            date_str = msg_date.strftime("%a, %b %d")

        if date_str != last_date:
            self._last_displayed_date = date_str
            separator = Static(
                f"[{cascade.dim}]── {date_str} ──[/]",
                classes="chat-date-separator",
            )
            return separator, date_str
        return None, last_date

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
        has_attachment = msg.get("has_attachment", False)
        attachment_type = msg.get("attachment_type")
        attachment_name = msg.get("attachment_name")
        attachment_size = msg.get("attachment_size")

        parts: list[str] = []

        # Format inline timestamp
        ts_str = ""
        if timestamp:
            ts_str = datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M")

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
            elif status == "failed":
                status_icon = f"[red bold]{STATUS_ICONS['failed']}[/]"

            if status == "failed":
                parts.append(f"{content} {status_icon} [{cascade.dim}]{ts_str}[/]")
                parts.append(f"[{cascade.dim}]↻ press R to retry[/]")
            else:
                parts.append(f"{content} {status_icon} [{cascade.dim}]{ts_str}[/]")
        else:
            sender = self.display_name or self.peer_hash[:8]
            parts.append(f"[{cascade.dim} bold]{sender}[/]")
            parts.append(f"{content} [{cascade.dim}]{ts_str}[/]")

        # Attachment indicator (images rendered inline by MessageBubble)
        if has_attachment and not (attachment_type and attachment_type.startswith("image")):
            parts.append(self._format_attachment_line(msg, cascade))

        msg_text = "\n".join(parts)

        return MessageBubble(
            msg_text,
            message_id=msg_id,
            is_outgoing=is_outgoing,
            status=status,
            lxmf_hash=lxmf_hash,
            reply_to_hash=reply_to_hash,
            raw_content=content,
            timestamp=timestamp,
            read_by_recipient=read_by_recipient,
            has_attachment=has_attachment,
            attachment_type=attachment_type,
            attachment_name=attachment_name,
            attachment_size=attachment_size,
        )

    def _format_attachment_line(self, msg: dict[str, Any], cascade: Any) -> str:
        """Format the attachment indicator line for a message bubble."""
        att_type = msg.get("attachment_type", "file")
        icon = ATTACHMENT_ICONS.get(att_type, ATTACHMENT_ICONS["file"])
        name = msg.get("attachment_name") or f"{att_type} attachment"
        size = msg.get("attachment_size")
        size_str = _human_size(size) if size else ""
        if size_str:
            return f"[{cascade.dim}]{icon} {name} ({size_str})[/]"
        return f"[{cascade.dim}]{icon} {name}[/]"

    def _find_reply_preview(self, lxmf_hash: str) -> str:
        """Find a message preview by LXMF hash for reply context."""
        try:
            container = self.query_one("#chat-message-container", Vertical)
            for child in container.query(MessageBubble):
                if child.lxmf_hash == lxmf_hash:
                    preview = child.raw_content[:40]
                    if len(child.raw_content) > 40:
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

        # Allow empty message if we have a staged attachment
        if not message and not (
            self._pending_attachment
            and not self._pending_attachment.get("awaiting_path")
        ):
            return

        # Handle attach mode: user entered a file path
        if (
            self._pending_attachment is not None
            and self._pending_attachment.get("awaiting_path")
        ):
            event.input.value = ""
            self.run_worker(
                self._stage_attachment_from_path(message),
                group="chat-attach",
            )
            # Restore placeholder
            try:
                event.input.placeholder = "Type a message..."
            except Exception:
                pass
            return

        event.input.value = ""

        kwargs: dict[str, Any] = {}
        if self._reply_to is not None:
            kwargs["reply_to_hash"] = self._reply_to.get("lxmf_hash")
            self._clear_reply()

        # Include pending attachment if staged
        attachment_filename = None
        if self._pending_attachment and not self._pending_attachment.get("awaiting_path"):
            kwargs["attachment_data_b64"] = self._pending_attachment.get("data_b64")
            kwargs["attachment_filename"] = self._pending_attachment.get("filename")
            kwargs["attachment_mime"] = self._pending_attachment.get("mime")
            attachment_filename = self._pending_attachment.get("filename")
            self._pending_attachment = None
            self._set_status("")
            # Restore placeholder
            try:
                chat_input = self.query_one("#chat-input", Input)
                chat_input.placeholder = "Type a message…"
            except Exception:
                pass

        # Build display text for optimistic message
        display = message
        if not display and attachment_filename:
            display = f"📎 {attachment_filename}"

        self._pending_messages.append(display)
        self._show_optimistic_message(display)

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

        msg_text = f"{content} \u23f3"
        bubble = MessageBubble(
            msg_text,
            message_id=0,
            is_outgoing=True,
            status="pending",
            raw_content=content,
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
            # Refresh to replace optimistic bubble (id=0) with real DB record
            if self.is_mounted:
                await asyncio.sleep(0.3)
                await self._refresh_messages()
            return
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            self._set_status(f"[red]Send failed: {e}[/]")
            self._update_optimistic_status(content, "failed")
            self.notify(f"Send failed: {e}", title="Chat Error", severity="error")
            # Refresh to replace optimistic bubble (id=0) with real DB record
            if self.is_mounted:
                await asyncio.sleep(0.3)
                await self._refresh_messages()
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
        if status == "failed":
            icon = f"[red bold]{STATUS_ICONS['failed']}[/]"

        for child in reversed(list(container.query(".--outgoing"))):
            if isinstance(child, MessageBubble):
                # Match by content to avoid updating the wrong bubble
                # when multiple sends are in flight. For attachment-only
                # messages (empty content), match the most recent pending bubble.
                if content and child.raw_content and child.raw_content.rstrip() != content.rstrip():
                    continue
                if not content and child.status != "pending":
                    continue

                display = content
                if status == "failed":
                    cascade_ref = get_color_cascade()
                    msg_text = f"{display} {icon}"
                    # Retry hint added on next full refresh from DB
                else:
                    msg_text = f"{display} {icon}"
                child.update_text(msg_text)
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
                self.focus()
            else:
                chat_input.focus()
        except Exception:
            pass

    def action_escape_handler(self) -> None:
        """Layered escape: cancel attachment -> cancel reply -> close search -> deselect -> pop screen."""
        if self._pending_attachment is not None:
            self._pending_attachment = None
            self._set_status("")
            try:
                chat_input = self.query_one("#chat-input", Input)
                chat_input.placeholder = "Type a message..."
                chat_input.value = ""
            except Exception:
                pass
            return

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
        """Retry sending a failed message (R key).

        If no message is selected, auto-selects the most recent failed message.
        """
        bubble = self._get_selected_bubble()

        # If nothing selected or selected isn't failed, find the most recent failed
        if bubble is None or not bubble.is_failed:
            failed = [b for b in self._get_bubbles() if b.is_failed]
            if not failed:
                self._set_status("[dim]No failed messages to retry[/]")
                return
            bubble = failed[-1]  # Most recent
            self._selected_message_id = bubble.message_id
            bubble.select()

        if bubble.message_id == 0:
            # Optimistic bubble — refresh from DB first to get real ID
            self.run_worker(self._retry_after_refresh(bubble.raw_content), group="chat-retry")
        else:
            self.run_worker(
                self._retry_single(bubble.message_id),
                group=f"chat-retry-{bubble.message_id}",
            )

    async def _retry_after_refresh(self, content: str | None) -> None:
        """Refresh messages from DB, find the failed message by content, then retry."""
        await self._refresh_messages()
        await asyncio.sleep(0.2)

        # Find the failed message in the refreshed bubbles
        for bubble in reversed(self._get_bubbles()):
            if bubble.is_failed and bubble.message_id > 0:
                if content is None or (bubble.raw_content and bubble.raw_content.strip() == (content or "").strip()):
                    await self._retry_single(bubble.message_id)
                    return

        self._set_status("[red]Could not find message to retry[/]")

    async def _retry_single(self, message_id: int) -> None:
        """Retry a single failed message via IPC."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        self._update_bubble_status(message_id, "pending")

        try:
            await bridge.retry_message(message_id)
            self._set_status("[green]Retry queued[/]")
            # Refresh to show updated status
            if self.is_mounted:
                await asyncio.sleep(0.5)
                await self._refresh_messages()
        except Exception as e:
            logger.error(f"Retry failed: {e}")
            self._update_bubble_status(message_id, "failed")
            self._set_status(f"[red]Retry failed: {e}[/]")

    def action_retry_all_failed(self) -> None:
        """Retry all failed messages (ctrl+r)."""
        failed = [b for b in self._get_bubbles() if b.is_failed]
        if not failed:
            return

        self._set_status(f"[dim]Retrying {len(failed)} failed message(s)...[/]")
        for bubble in failed:
            self.run_worker(
                self._retry_single(bubble.message_id),
                group=f"chat-retry-{bubble.message_id}",
            )

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
            search_input.disabled = False
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
            search_input.disabled = True
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
            "content": bubble.raw_content,
            "message_id": bubble.message_id,
        }

        preview = bubble.raw_content[:40]
        if len(bubble.raw_content) > 40:
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
    # Copy to clipboard
    # -------------------------------------------------------------------------

    def action_copy_message(self) -> None:
        """Copy selected message content to system clipboard (y key)."""
        bubble = self._get_selected_bubble()
        if bubble is None:
            return

        try:
            self.app.copy_to_clipboard(bubble.raw_content)
            self._set_status("[dim]Copied to clipboard[/]")
        except Exception:
            self._set_status("[red]Copy failed[/]")

    # -------------------------------------------------------------------------
    # Block actions
    # -------------------------------------------------------------------------

    def action_block_peer(self) -> None:
        """Block this peer — silently drop all future messages (B key).

        First press shows confirmation prompt, second press within 5s executes.
        """
        if not self._ipc_bridge or not self.peer_hash:
            return

        import time as _time

        now = _time.time()
        if (
            hasattr(self, "_block_confirm_time")
            and self._block_confirm_time
            and now - self._block_confirm_time < 5.0
            and getattr(self, "_block_confirm_hash", None) == self.peer_hash
        ):
            # Second press — execute
            self._block_confirm_time = None
            self._block_peer_async()
        else:
            # First press — prompt
            self._block_confirm_time = now
            self._block_confirm_hash = self.peer_hash
            self.notify(
                f"Press B again within 5s to block {self.peer_hash[:8]}...\n"
                "All future messages will be silently dropped.",
                title="⚠ Confirm Block",
                severity="warning",
            )

    @work(exclusive=True, thread=False)
    async def _block_peer_async(self) -> None:
        """Block the peer via IPC."""
        bridge = self._ipc_bridge
        if not bridge:
            return
        try:
            result = await bridge.block_peer(self.peer_hash)
            self.notify(
                f"Blocked {self.peer_hash[:8]}... — messages will be dropped",
                title="Peer Blocked",
            )
        except Exception as e:
            self.notify(f"Block failed: {e}", severity="error")

    # -------------------------------------------------------------------------
    # Attachment actions
    # -------------------------------------------------------------------------

    def action_open_attachment(self) -> None:
        """Open the attachment of the selected message (o key)."""
        bubble = self._get_selected_bubble()
        if bubble is None:
            return

        if not bubble.has_attachment:
            self._set_status("[dim]No attachment on selected message[/]")
            return

        self.run_worker(
            self._open_attachment(bubble.message_id),
            group="chat-attachment",
        )

    @staticmethod
    def _cleanup_temp_file(path: str) -> None:
        """Remove a temp attachment file if it still exists."""
        import os

        try:
            os.unlink(path)
            _TEMP_FILES.discard(path)
        except OSError:
            pass

    async def _open_attachment(self, message_id: int) -> None:
        """Fetch attachment and open with system viewer."""
        import os
        import platform
        import subprocess
        import tempfile

        bridge = self._ipc_bridge
        if bridge is None:
            self._set_status("[red]No daemon connection[/]")
            return

        try:
            self._set_status("[dim]Fetching attachment...[/]")
            import base64

            result = await bridge.get_attachment(message_id)
            data = base64.b64decode(result.get("data_b64", ""))
            filename = result.get("filename") or "attachment"

            # Write to temp file with correct extension
            suffix = ""
            if "." in filename:
                suffix = "." + filename.rsplit(".", 1)[-1]
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix, prefix="styrene_"
            ) as f:
                f.write(data)
                tmp_path = f.name

            # Track for cleanup
            _TEMP_FILES.add(tmp_path)

            # Open with system viewer
            system = platform.system()
            if system == "Darwin":
                subprocess.Popen(["open", tmp_path])
            elif system == "Windows":
                os.startfile(tmp_path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", tmp_path])

            # Schedule delayed cleanup (5 min) to let viewer open
            self.set_timer(300, lambda: self._cleanup_temp_file(tmp_path))

            self._set_status(f"[dim]Opened {filename}[/]")
        except Exception as e:
            logger.error(f"Failed to open attachment: {e}")
            self._set_status(f"[red]Failed to open: {e}[/]")

    def action_attach_file(self) -> None:
        """Attach a file or clipboard content (a key).

        If an attachment is already staged, cancel it.
        Otherwise, try clipboard first, then fall back to path prompt.
        """
        if self._pending_attachment is not None:
            self._pending_attachment = None
            self._set_status("")
            try:
                chat_input = self.query_one("#chat-input", Input)
                chat_input.placeholder = "Type a message…"
            except Exception:
                pass
            return

        # Try clipboard first
        attachment = read_clipboard_attachment()
        if attachment is not None:
            self._pending_attachment = {
                "data_b64": attachment.data_b64,
                "filename": attachment.filename,
                "mime": attachment.mime,
            }
            icon = ATTACHMENT_ICONS.get(
                "image" if attachment.mime.startswith("image/") else
                "audio" if attachment.mime.startswith("audio/") else
                "file",
                ATTACHMENT_ICONS["file"],
            )
            size_str = _human_size(attachment.size)
            self._set_status(
                f"[dim]{icon} 📋 {attachment.filename} ({size_str}) "
                f"| Enter to send, Esc to cancel[/]"
            )
            try:
                chat_input = self.query_one("#chat-input", Input)
                chat_input.focus()
            except Exception:
                pass
            return

        # Fall back to path prompt
        try:
            chat_input = self.query_one("#chat-input", Input)
            chat_input.placeholder = "Enter file path to attach (Esc to cancel)…"
            chat_input.value = ""
            chat_input.focus()
            self._set_status("[dim]Enter path to file, then press Enter[/]")
            self._pending_attachment = {"awaiting_path": True}
        except Exception:
            self._set_status("[red]Cannot access input[/]")

    async def _stage_attachment_from_path(self, path_str: str) -> bool:
        """Read a file and stage it as a pending attachment.

        Runs file I/O in a thread executor to avoid blocking the event loop.

        Args:
            path_str: Path to the file to attach.

        Returns:
            True if file was staged successfully.
        """
        import base64
        import mimetypes
        from pathlib import Path

        from styrened.services.attachment_store import DEFAULT_MAX_FILE_SIZE

        path = Path(path_str.strip()).expanduser()
        if not path.is_file():
            self._set_status(f"[red]File not found: {path}[/]")
            self._pending_attachment = None
            return False

        # Size pre-check before reading into RAM
        try:
            file_size = path.stat().st_size
        except OSError as e:
            self._set_status(f"[red]Cannot stat file: {e}[/]")
            self._pending_attachment = None
            return False

        if file_size > DEFAULT_MAX_FILE_SIZE:
            self._set_status(
                f"[red]File too large: {_human_size(file_size)} "
                f"(max {_human_size(DEFAULT_MAX_FILE_SIZE)})[/]"
            )
            self._pending_attachment = None
            return False

        try:
            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(None, path.read_bytes)
            mime_type, _ = mimetypes.guess_type(str(path))
            data_b64 = base64.b64encode(data).decode("ascii")

            self._pending_attachment = {
                "data_b64": data_b64,
                "filename": path.name,
                "mime": mime_type,
            }

            size_str = _human_size(len(data))
            icon = ATTACHMENT_ICONS.get(
                "image" if mime_type and mime_type.startswith("image/") else
                "audio" if mime_type and mime_type.startswith("audio/") else
                "file",
                ATTACHMENT_ICONS["file"],
            )
            self._set_status(
                f"[dim]{icon} {path.name} ({size_str}) | Press Esc to cancel[/]"
            )

            # Restore normal input placeholder
            try:
                chat_input = self.query_one("#chat-input", Input)
                chat_input.placeholder = "Type a message..."
                chat_input.value = ""
            except Exception:
                pass

            return True
        except Exception as e:
            self._set_status(f"[red]Failed to read file: {e}[/]")
            self._pending_attachment = None
            return False

    # -------------------------------------------------------------------------
    # Paste & clipboard attachment support
    # -------------------------------------------------------------------------

    def on_paste(self, event: Any) -> None:
        """Handle paste events — check clipboard for image data or file paths.

        Priority order:
        1. macOS clipboard image data (screenshots, copied images)
        2. File path in clipboard text pointing to a supported file
        3. Normal text paste (don't intercept)
        """
        # First, try reading image/file data directly from macOS clipboard.
        # This catches screenshots (Cmd+Shift+4 → clipboard) and Finder copies.
        if has_clipboard_image():
            event.prevent_default()
            self._do_stage_from_clipboard()
            return

        # Fallback: check if pasted text is a file path
        text = getattr(event, "text", "")
        if not text:
            return

        stripped = text.strip()
        if stripped.startswith(("/", "~", ".")) or (len(stripped) > 2 and stripped[1] == ":"):
            from pathlib import Path as _P

            path = _P(stripped).expanduser()
            if path.suffix.lower() in (
                ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
                ".pdf", ".txt", ".md", ".zip", ".tar", ".gz",
                ".mp3", ".wav", ".ogg", ".mp4", ".mov",
            ) and path.is_file():
                event.prevent_default()
                self.run_worker(
                    self._stage_attachment_from_path(str(path)),
                    group="chat-paste",
                )

    def action_paste_attachment(self) -> None:
        """Explicitly paste clipboard content as attachment (Ctrl+V).

        When the input is focused, Textual handles Ctrl+V as text paste
        which triggers on_paste(). This action is a fallback for when
        the widget itself has focus (message browsing mode).
        """
        self._do_stage_from_clipboard()

    def action_attach_clipboard(self) -> None:
        """Attach clipboard content (Ctrl+Y).

        Works regardless of whether Input or ChatWidget has focus.
        Checks clipboard for image data or file references first.
        If nothing in clipboard, falls back to path prompt.
        """
        logger.debug("action_attach_clipboard triggered")
        # If already staged, cancel
        if self._pending_attachment is not None:
            self._pending_attachment = None
            self._set_status("")
            try:
                chat_input = self.query_one("#chat-input", Input)
                chat_input.placeholder = "Type a message…"
            except Exception:
                pass
            return

        # Read clipboard on main thread — PyObjC NSPasteboard requires it
        try:
            attachment = read_clipboard_attachment()
        except Exception as e:
            logger.error(f"Clipboard read exception: {e}")
            attachment = None

        if attachment is not None:
            self._stage_clipboard_attachment(attachment)
            return

        # Nothing in clipboard — fall back to path prompt
        logger.debug("No clipboard content, prompting for path")
        self._set_status("[dim]No image in clipboard. Enter file path:[/]")
        try:
            chat_input = self.query_one("#chat-input", Input)
            chat_input.placeholder = "Enter file path to attach (Esc to cancel)…"
            chat_input.value = ""
            chat_input.focus()
            self._pending_attachment = {"awaiting_path": True}
        except Exception:
            self._set_status("[red]Cannot access input[/]")

    def _stage_clipboard_attachment(self, attachment: "ClipboardAttachment") -> None:
        """Stage a clipboard attachment for sending."""
        self._pending_attachment = {
            "data_b64": attachment.data_b64,
            "filename": attachment.filename,
            "mime": attachment.mime,
        }
        icon = ATTACHMENT_ICONS.get(
            "image" if attachment.mime.startswith("image/") else
            "audio" if attachment.mime.startswith("audio/") else
            "file",
            ATTACHMENT_ICONS["file"],
        )
        size_str = _human_size(attachment.size)
        source_label = {
            "screenshot": "📋 screenshot",
            "image_copy": "📋 copied image",
            "file": "📎 file",
            "path": "📎 file",
        }.get(attachment.source, "📎")
        self._set_status(
            f"[dim]{icon} {source_label}: {attachment.filename} ({size_str}) "
            f"| Enter to send, Esc to cancel[/]"
        )
        try:
            chat_input = self.query_one("#chat-input", Input)
            chat_input.placeholder = f"📎 {attachment.filename} — Enter to send, Esc to cancel"
            chat_input.focus()
        except Exception:
            pass

    def _do_stage_from_clipboard(self) -> None:
        """Read clipboard and stage as attachment.

        Called directly (not via run_worker) to ensure NSPasteboard
        is accessed on the main thread, as required by macOS/PyObjC.
        """
        try:
            attachment = read_clipboard_attachment()
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Clipboard read exception: {e}")
            attachment = None

        if attachment is None:
            self._set_status("[dim]No image or file in clipboard[/]")
            return

        self._stage_clipboard_attachment(attachment)
        try:
            chat_input = self.query_one("#chat-input", Input)
            chat_input.focus()
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
