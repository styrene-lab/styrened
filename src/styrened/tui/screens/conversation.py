"""ConversationScreen - Message thread for chat conversations.

This screen displays a message thread with a specific conversation partner
and allows sending new messages. Delegates to ChatWidget for all messaging
logic.
"""

import logging
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Static

from styrened.tui.widgets.chat_widget import ChatWidget
from styrened.ui_state import (
    PeerWorkspaceContext,
    PeerWorkspaceFocus,
    WorkspaceId,
    build_peer_workspace_context,
)

logger = logging.getLogger(__name__)

# Delete confirmation timeout (seconds)
_DELETE_CONFIRM_TIMEOUT = 3.0


class ConversationScreen(Screen[None]):
    """Conversation screen showing message thread.

    Displays message history with a conversation partner and
    provides input field for sending new messages.

    All messaging logic is handled by the embedded ChatWidget.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "go_back", "Back"),
        Binding("ctrl+d", "delete_conversation", "Delete All", show=True),
        Binding("B", "block_peer", "Block", show=True),
    ]

    CSS = """
    ConversationScreen {
        background: $background;
    }

    ConversationScreen #conv-content {
        height: 1fr;
    }

    ConversationScreen #conv-title {
        height: 1;
        padding: 0 1;
        color: $primary;
        text-style: bold;
        background: $surface;
    }

    ConversationScreen #conv-path-info {
        height: 1;
        padding: 0 1;
        color: $panel;
        background: $surface;
    }
    """

    def __init__(
        self,
        peer_hash: str,
        display_name: str | None = None,
        origin_workspace: WorkspaceId | str | None = None,
        peer_context: PeerWorkspaceContext | None = None,
    ) -> None:
        """Initialize ConversationScreen.

        Args:
            peer_hash: Conversation partner's identity hash
            display_name: Optional display name for the peer
            origin_workspace: Aggregate workspace that launched this mail-thread view.
            peer_context: Optional pre-built canonical peer workspace context.
        """
        super().__init__()
        self.peer_hash = peer_hash
        self.display_name = display_name
        self.peer_context = peer_context or build_peer_workspace_context(
            peer_hash,
            origin_workspace,
            focus=PeerWorkspaceFocus.MAIL,
        )
        self._delete_conv_pending: bool = False
        self._delete_conv_timer: Timer | None = None

    @property
    def origin_workspace(self) -> WorkspaceId:
        """Aggregate workspace that launched this mail-thread view."""
        return self.peer_context.origin_workspace

    @property
    def requested_focus(self) -> PeerWorkspaceFocus:
        """Requested focus for this compatibility mail-thread context."""
        return self.peer_context.focus

    @property
    def _ipc_bridge(self) -> Any:
        """Get IPCBridge from app lifecycle."""
        try:
            return self.app.services.bridge
        except Exception:
            return None

    def compose(self) -> ComposeResult:
        """Compose conversation UI."""
        title = self.display_name or self.peer_hash[:12]
        yield Header()
        with Container(id="conv-content"):
            yield Static(f"[bold]{title}[/]", id="conv-title")
            yield Static("", id="conv-path-info")
            yield ChatWidget(
                peer_hash=self.peer_hash,
                display_name=self.display_name,
                id="chat-widget",
            )
        yield Footer()

    def action_go_back(self) -> None:
        """Leave the mail-thread compatibility screen."""
        self.app.pop_screen()

    def on_mount(self) -> None:
        """Load path info on mount."""
        if self._ipc_bridge is not None:
            self.run_worker(self._load_path_info(), group="conv-path")

    async def _load_path_info(self) -> None:
        """Load path info for the peer and display in header."""
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            info = await bridge.get_path_info(self.peer_hash)
        except Exception:
            return

        if not info.get("found"):
            try:
                path_widget = self.query_one("#conv-path-info", Static)
                path_widget.update("[dim]No path info available[/]")
            except Exception:
                pass
            return

        hops = info.get("hops", 0)
        iface = info.get("interface_name") or info.get("interface_type") or "unknown"
        bitrate = info.get("bitrate")

        parts = [f"{hops} hop{'s' if hops != 1 else ''}"]
        parts.append(f"via {iface}")
        if bitrate:
            if bitrate >= 1_000_000:
                parts.append(f"{bitrate / 1_000_000:.1f} Mbps")
            elif bitrate >= 1_000:
                parts.append(f"{bitrate / 1_000:.0f} kbps")
            else:
                parts.append(f"{bitrate} bps")

        try:
            path_widget = self.query_one("#conv-path-info", Static)
            path_widget.update(f"[dim]{' | '.join(parts)}[/]")
        except Exception:
            pass

    def action_delete_conversation(self) -> None:
        """Delete entire conversation with double-tap confirmation."""
        if self._delete_conv_pending:
            # Second press — execute
            self._cancel_delete_conv_timer()
            self.run_worker(self._execute_delete_conversation(), group="conv-delete")
        else:
            # First press — set pending
            self._delete_conv_pending = True
            self.notify(
                "Press Ctrl+D again to delete entire conversation",
                severity="warning",
            )
            self._cancel_delete_conv_timer()
            self._delete_conv_timer = self.set_timer(
                _DELETE_CONFIRM_TIMEOUT, self._cancel_delete_conv_pending
            )

    def _cancel_delete_conv_timer(self) -> None:
        """Cancel delete conversation timer."""
        if self._delete_conv_timer is not None:
            self._delete_conv_timer.stop()
            self._delete_conv_timer = None

    def _cancel_delete_conv_pending(self) -> None:
        """Cancel delete conversation pending state."""
        self._delete_conv_pending = False
        self._cancel_delete_conv_timer()

    def action_block_peer(self) -> None:
        """Block this peer — double-press B within 5s to confirm."""
        import time as _time

        now = _time.time()
        if (
            hasattr(self, "_block_confirm_time")
            and self._block_confirm_time
            and now - self._block_confirm_time < 5.0
        ):
            self._block_confirm_time = None
            self.run_worker(self._execute_block_peer(), group="conv-block")
        else:
            self._block_confirm_time = now
            self.notify(
                f"Press B again to block {self.peer_hash[:8]}...\n"
                "All future messages will be silently dropped.",
                title="⚠ Confirm Block",
                severity="warning",
            )

    async def _execute_block_peer(self) -> None:
        """Execute peer block and pop screen."""
        bridge = self._ipc_bridge
        if bridge is None:
            return
        try:
            await bridge.block_peer(identity_hash=self.peer_hash)
            self.notify(
                f"Blocked {self.peer_hash[:8]}... — messages will be dropped",
                title="Peer Blocked",
            )
            self.app.pop_screen()
        except Exception as e:
            logger.error(f"Failed to block peer: {e}")
            self.notify(f"Block failed: {e}", severity="error")

    async def _execute_delete_conversation(self) -> None:
        """Execute conversation deletion and pop screen."""
        self._delete_conv_pending = False
        bridge = self._ipc_bridge
        if bridge is None:
            return

        try:
            count = await bridge.delete_conversation(self.peer_hash)
            self.notify(f"Deleted {count} messages", severity="information")
            self.app.pop_screen()
        except Exception as e:
            logger.error(f"Failed to delete conversation: {e}")
            self.notify(f"Delete failed: {e}", severity="error")
