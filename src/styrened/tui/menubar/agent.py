"""macOS menu bar agent for styrened.

Shows unread count, recent conversations, and daemon status in the
macOS menu bar. Subscribes to IPC events for real-time updates.

Architecture:
- rumps NSApplication event loop runs on main thread
- asyncio event loop runs in a background thread for IPC
- Thread-safe communication via rumps.Timer polling + shared state
"""
from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Poll interval for refreshing state from daemon (seconds)
_POLL_INTERVAL = 15.0

# Maximum conversations shown in dropdown
_MAX_CONVERSATIONS = 8


@dataclass
class MenuBarState:
    """Thread-safe shared state between IPC and menu bar."""

    unread_total: int = 0
    daemon_connected: bool = False
    conversations: list[dict[str, Any]] = field(default_factory=list)
    last_update: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def update(
        self,
        *,
        unread: int | None = None,
        connected: bool | None = None,
        conversations: list[dict[str, Any]] | None = None,
    ) -> None:
        with self.lock:
            if unread is not None:
                self.unread_total = unread
            if connected is not None:
                self.daemon_connected = connected
            if conversations is not None:
                self.conversations = conversations
            self.last_update = time.time()

    def snapshot(self) -> tuple[int, bool, list[dict[str, Any]]]:
        with self.lock:
            return self.unread_total, self.daemon_connected, list(self.conversations)


def _relative_time(ts: float) -> str:
    """Format unix timestamp as relative time."""
    if not ts:
        return ""
    elapsed = int(time.time() - ts)
    if elapsed < 60:
        return "now"
    if elapsed < 3600:
        return f"{elapsed // 60}m"
    if elapsed < 86400:
        return f"{elapsed // 3600}h"
    return f"{elapsed // 86400}d"


async def _ipc_loop(state: MenuBarState) -> None:
    """Background asyncio loop polling daemon for state updates."""
    from styrened.ipc.bridge import IPCBridge

    bridge = IPCBridge()

    while True:
        try:
            await bridge.connect()
            state.update(connected=True)
            logger.info("Menu bar agent connected to daemon")

            while True:
                try:
                    convs = await bridge.get_conversations()
                    unread = sum(c.get("unread_count", 0) for c in convs)
                    state.update(unread=unread, connected=True, conversations=convs)
                except Exception as e:
                    logger.warning(f"Failed to poll conversations: {e}")
                    state.update(connected=False)
                    break

                await asyncio.sleep(_POLL_INTERVAL)

        except Exception as e:
            logger.debug(f"IPC connection failed: {e}")
            state.update(connected=False, unread=0, conversations=[])

        # Retry after disconnect
        await asyncio.sleep(5.0)
        try:
            await bridge.disconnect()
        except Exception:
            pass


def _start_ipc_thread(state: MenuBarState) -> None:
    """Start the IPC polling loop in a daemon thread."""

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_ipc_loop(state))
        except Exception:
            logger.exception("IPC thread crashed")

    t = threading.Thread(target=_run, daemon=True, name="menubar-ipc")
    t.start()


def _send_notification(title: str, message: str, sound: bool = True) -> None:
    """Send a macOS notification via osascript."""
    try:
        script = f'display notification "{message}" with title "{title}"'
        if sound:
            script += ' sound name "default"'
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def run() -> None:
    """Launch the menu bar agent. Blocks on the rumps event loop."""
    if platform.system() != "Darwin":
        print("Menu bar agent is macOS-only", file=sys.stderr)
        sys.exit(1)

    try:
        import rumps
    except ImportError:
        print(
            "rumps is required for the menu bar agent.\n"
            "Install with: pip install rumps",
            file=sys.stderr,
        )
        sys.exit(1)

    state = MenuBarState()
    _prev_unread = 0

    class StyreneMenuBar(rumps.App):
        def __init__(self) -> None:
            super().__init__(
                "Styrene",
                title="○",
                quit_button=None,
            )
            self._separator_key = "---"

        @rumps.timer(_POLL_INTERVAL)
        def refresh(self, _: Any) -> None:
            """Periodic refresh of menu bar state."""
            nonlocal _prev_unread
            unread, connected, convs = state.snapshot()

            # Update title
            if not connected:
                self.title = "○"
            elif unread > 0:
                self.title = f"● {unread}"
            else:
                self.title = "●"

            # Notify on new unread
            if unread > _prev_unread and _prev_unread >= 0:
                delta = unread - _prev_unread
                _send_notification(
                    "Styrene",
                    f"{delta} new message{'s' if delta != 1 else ''}",
                )
            _prev_unread = unread

            # Rebuild menu
            menu_items = []

            if not connected:
                menu_items.append(rumps.MenuItem("Daemon offline", callback=None))
                menu_items.append(None)  # separator
            else:
                status_text = f"{unread} unread" if unread else "No new messages"
                menu_items.append(rumps.MenuItem(status_text, callback=None))
                menu_items.append(None)

                for conv in convs[:_MAX_CONVERSATIONS]:
                    name = conv.get("display_name") or conv.get("peer_hash", "")[:12] + "…"
                    conv_unread = conv.get("unread_count", 0)
                    preview = conv.get("last_message_preview", "")
                    last_time = conv.get("last_message_time", 0)

                    if preview and len(preview) > 30:
                        preview = preview[:30] + "…"

                    label_parts = [name]
                    if conv_unread:
                        label_parts.append(f"({conv_unread})")
                    if preview:
                        label_parts.append(f"— {preview}")
                    if last_time:
                        label_parts.append(f"[{_relative_time(last_time)}]")

                    item = rumps.MenuItem(
                        " ".join(label_parts),
                        callback=self._open_conversation,
                    )
                    item._peer_hash = conv.get("peer_hash", "")
                    menu_items.append(item)

                if convs:
                    menu_items.append(None)

            menu_items.append(rumps.MenuItem("Open Styrene", callback=self._open_tui))
            menu_items.append(None)
            menu_items.append(rumps.MenuItem("Quit", callback=self._quit))

            self.menu.clear()
            for item in menu_items:
                self.menu.add(item)

        def _open_tui(self, _: Any) -> None:
            """Launch the TUI."""
            try:
                subprocess.Popen(
                    ["styrene"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass

        def _open_conversation(self, sender: Any) -> None:
            """Open TUI to a specific conversation."""
            # For now, just open the TUI
            # TODO: pass peer_hash to open directly to conversation
            self._open_tui(sender)

        def _quit(self, _: Any) -> None:
            rumps.quit_application()

    _start_ipc_thread(state)
    StyreneMenuBar().run()
