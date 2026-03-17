"""Terminal widget — pyte-based remote terminal emulator for the TUI.

Renders a remote terminal session within a Textual widget using pyte
for VT100/xterm escape sequence processing. Connects to the daemon
via IPC, which proxies terminal I/O over RNS Links.

Usage:
    yield TerminalWidget(
        device_identity="abc123...",
        id="terminal-widget",
    )
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, ClassVar

import pyte
from rich.style import Style
from rich.text import Text
from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Static

from styrened.ipc.protocol import IPCMessageType
from styrened.tui.widgets.highlighted_panel import get_color_cascade

logger = logging.getLogger(__name__)


# =============================================================================
# KeyEncoder — Textual Key → VT100 bytes
# =============================================================================


class KeyEncoder:
    """Maps Textual Key events to VT100/xterm escape sequences.

    Handles printable characters, control sequences, arrow keys,
    function keys, and modifier combinations.
    """

    # Named key → escape sequence mapping
    _KEY_MAP: dict[str, bytes] = {
        "enter": b"\r",
        "tab": b"\t",
        "backspace": b"\x7f",
        "delete": b"\x1b[3~",
        "escape": b"\x1b",
        "up": b"\x1b[A",
        "down": b"\x1b[B",
        "right": b"\x1b[C",
        "left": b"\x1b[D",
        "home": b"\x1b[H",
        "end": b"\x1b[F",
        "pageup": b"\x1b[5~",
        "pagedown": b"\x1b[6~",
        "insert": b"\x1b[2~",
        "f1": b"\x1bOP",
        "f2": b"\x1bOQ",
        "f3": b"\x1bOR",
        "f4": b"\x1bOS",
        "f5": b"\x1b[15~",
        "f6": b"\x1b[17~",
        "f7": b"\x1b[18~",
        "f8": b"\x1b[19~",
        "f9": b"\x1b[20~",
        "f10": b"\x1b[21~",
        "f11": b"\x1b[23~",
        "f12": b"\x1b[24~",
        "space": b" ",
    }

    @classmethod
    def encode(cls, key: events.Key) -> bytes | None:
        """Encode a Textual Key event to VT100 bytes.

        Args:
            key: Textual Key event.

        Returns:
            Encoded bytes, or None if the key cannot be encoded.
        """
        name = key.key

        # Ctrl+letter → control code (0x01-0x1A)
        if name.startswith("ctrl+") and len(name) == 6:
            letter = name[5]
            if "a" <= letter <= "z":
                return bytes([ord(letter) - ord("a") + 1])

        # ctrl+@ → NUL
        if name == "ctrl+at":
            return b"\x00"

        # Named keys
        if name in cls._KEY_MAP:
            return cls._KEY_MAP[name]

        # Printable character from key.character
        if key.character and len(key.character) == 1:
            return key.character.encode("utf-8")

        # Multi-byte characters (e.g., emoji, CJK)
        if key.character and len(key.character) > 1:
            return key.character.encode("utf-8")

        return None


# =============================================================================
# Pyte color → Rich style conversion
# =============================================================================

# pyte "default" sentinel
_PYTE_DEFAULT = "default"

# Standard 8 color names used by pyte
_PYTE_COLOR_MAP: dict[str, str] = {
    "black": "black",
    "red": "red",
    "green": "green",
    "brown": "yellow",
    "blue": "blue",
    "magenta": "magenta",
    "cyan": "cyan",
    "white": "white",
    "default": "default",
}


def _pyte_color_to_rich(color: str, is_bg: bool = False) -> str | None:
    """Convert a pyte color string to a Rich color string.

    Args:
        color: Pyte color value (name, hex, or "default").
        is_bg: Whether this is a background color.

    Returns:
        Rich color string or None for default.
    """
    if color == _PYTE_DEFAULT or not color:
        return None

    # Named colors
    if color in _PYTE_COLOR_MAP:
        mapped = _PYTE_COLOR_MAP[color]
        if mapped == "default":
            return None
        return mapped

    # 256-color or RGB (pyte provides as hex string like "00ff00")
    if len(color) == 6:
        try:
            int(color, 16)
            return f"#{color}"
        except ValueError:
            pass

    return None


def _char_style_to_rich(char: pyte.screens.Char) -> Style:
    """Convert a pyte Char's attributes to a Rich Style.

    Args:
        char: pyte Char with fg, bg, bold, italics, underscore, etc.

    Returns:
        Rich Style object.
    """
    fg = _pyte_color_to_rich(char.fg) if char.fg else None
    bg = _pyte_color_to_rich(char.bg, is_bg=True) if char.bg else None

    return Style(
        color=fg,
        bgcolor=bg,
        bold=char.bold or None,
        italic=char.italics or None,
        underline=char.underscore or None,
        reverse=char.reverse or None,
        strike=char.strikethrough or None,
    )


# =============================================================================
# TerminalWidget
# =============================================================================


class TerminalWidget(Widget, can_focus=True):
    """Remote terminal emulator widget using pyte.

    Connects to a remote node via the daemon's IPC terminal proxy,
    renders output using pyte + Rich, and forwards keystrokes as
    VT100 escape sequences.

    Attributes:
        device_identity: Reticulum identity hash of the target device.
        session_id: Active session ID (hex) or None.
        status: Human-readable connection status.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+backslash", "disconnect", "Disconnect", show=True),
    ]

    session_id: reactive[str | None] = reactive(None)
    status: reactive[str] = reactive("Disconnected")

    class Connected(Message):
        """Posted when terminal session is established."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    class Disconnected(Message):
        """Posted when terminal session ends."""

        def __init__(self, exit_code: int | None = None) -> None:
            super().__init__()
            self.exit_code = exit_code

    def __init__(
        self,
        device_identity: str,
        rows: int = 24,
        cols: int = 80,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.device_identity = device_identity
        self._rows = rows
        self._cols = cols

        # pyte virtual terminal
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.Stream(self._screen)

        # State
        self._connected = False
        self._event_handlers_registered = False

    def compose(self) -> ComposeResult:
        """Compose widget layout."""
        with Vertical(id="terminal-chrome"):
            yield Static(self._status_line(), id="terminal-status")
            yield Static(self._render_screen(), id="terminal-display")
            yield Button("Connect", id="terminal-connect-btn", variant="default")

    def _status_line(self) -> str:
        """Build status line markup."""
        if self._connected:
            return (
                f"[bold]Terminal[/] [{self.device_identity[:16]}...] "
                f"[{get_color_cascade().bright}]CONNECTED[/] {self._cols}x{self._rows}"
            )
        return f"[bold]Terminal[/] [{self.device_identity[:16]}...] [{get_color_cascade().dim}]{self.status}[/]"

    def _render_screen(self) -> Text:
        """Render pyte screen buffer to Rich Text."""
        result = Text()
        buffer = self._screen.buffer

        for row_idx in range(self._rows):
            if row_idx > 0:
                result.append("\n")

            line = buffer.get(row_idx, {})
            for col_idx in range(self._cols):
                char = line.get(col_idx, self._screen.default_char)
                style = _char_style_to_rich(char)
                result.append(char.data or " ", style=style)

        return result

    def _update_display(self) -> None:
        """Re-render the terminal display from pyte buffer."""
        try:
            display = self.query_one("#terminal-display", Static)
            display.update(self._render_screen())
        except Exception:
            pass

        try:
            status = self.query_one("#terminal-status", Static)
            status.update(self._status_line())
        except Exception:
            pass

    def watch_status(self, value: str) -> None:
        """React to status changes."""
        try:
            status = self.query_one("#terminal-status", Static)
            status.update(self._status_line())
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Connection lifecycle
    # -------------------------------------------------------------------------

    def _get_bridge(self) -> Any:
        """Get the IPCBridge from the app lifecycle."""
        try:
            return self.app.services.bridge
        except Exception:
            return None

    @on(Button.Pressed, "#terminal-connect-btn")
    def _on_connect_pressed(self, event: Button.Pressed) -> None:
        """Handle Connect button press."""
        if self._connected:
            self.run_worker(self._do_disconnect())
        else:
            self._do_connect()

    @work(exclusive=True)
    async def _do_connect(self) -> None:
        """Connect to remote terminal via IPC."""
        bridge = self._get_bridge()
        if bridge is None:
            self.status = "No daemon connection"
            return

        self.status = "Connecting..."
        self._update_connect_button("Connecting...", disabled=True)

        try:
            # Register event handlers before opening
            self._register_event_handlers(bridge)

            result = await bridge.terminal_open(
                destination=self.device_identity,
                rows=self._rows,
                cols=self._cols,
            )

            self.session_id = result.get("session_id")
            self._connected = True
            self.status = "Connected"
            self._update_connect_button("Disconnect", disabled=False)
            self.focus()

            self.post_message(self.Connected(self.session_id or ""))

        except Exception as e:
            self.status = f"Failed: {e}"
            self._update_connect_button("Connect", disabled=False)
            self._unregister_event_handlers(bridge)
            logger.warning(f"Terminal connect failed: {e}")

    async def _do_disconnect(self) -> None:
        """Disconnect from remote terminal."""
        bridge = self._get_bridge()
        if bridge is not None and self.session_id:
            try:
                await bridge.terminal_close(self.session_id)
            except Exception as e:
                logger.warning(f"Error closing terminal: {e}")

        self._cleanup()

    def _cleanup(self) -> None:
        """Clean up terminal state."""
        bridge = self._get_bridge()
        if bridge is not None:
            self._unregister_event_handlers(bridge)

        self._connected = False
        self.session_id = None
        self.status = "Disconnected"
        self._update_connect_button("Connect", disabled=False)
        self._screen.reset()
        self._update_display()

    def _update_connect_button(self, label: str, disabled: bool = False) -> None:
        """Update the connect button state."""
        try:
            btn = self.query_one("#terminal-connect-btn", Button)
            btn.label = label
            btn.disabled = disabled
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Event handlers (IPC events from daemon)
    # -------------------------------------------------------------------------

    def _register_event_handlers(self, bridge: Any) -> None:
        """Register callbacks for terminal IPC events."""
        if self._event_handlers_registered:
            return
        bridge.on_event(IPCMessageType.EVENT_TERMINAL_OUTPUT, self._on_terminal_output)
        bridge.on_event(IPCMessageType.EVENT_TERMINAL_EXITED, self._on_terminal_exited)
        bridge.on_event(IPCMessageType.EVENT_TERMINAL_ERROR, self._on_terminal_error)
        bridge.on_event(IPCMessageType.EVENT_TERMINAL_READY, self._on_terminal_ready)
        self._event_handlers_registered = True

    def _unregister_event_handlers(self, bridge: Any) -> None:
        """Unregister terminal event callbacks."""
        if not self._event_handlers_registered:
            return
        bridge.remove_event_handler(IPCMessageType.EVENT_TERMINAL_OUTPUT, self._on_terminal_output)
        bridge.remove_event_handler(IPCMessageType.EVENT_TERMINAL_EXITED, self._on_terminal_exited)
        bridge.remove_event_handler(IPCMessageType.EVENT_TERMINAL_ERROR, self._on_terminal_error)
        bridge.remove_event_handler(IPCMessageType.EVENT_TERMINAL_READY, self._on_terminal_ready)
        self._event_handlers_registered = False

    def _on_terminal_output(
        self, event_type: IPCMessageType, payload: dict[str, Any]
    ) -> None:
        """Handle terminal output event from daemon."""
        if payload.get("session_id") != self.session_id:
            return

        data_b64 = payload.get("data_b64", "")
        try:
            data = base64.b64decode(data_b64)
            # Feed to pyte stream
            self._stream.feed(data.decode("utf-8", errors="replace"))
            # Schedule display update on the main thread
            self.call_from_thread(self._update_display)
        except Exception as e:
            logger.warning(f"Error processing terminal output: {e}")

    def _on_terminal_exited(
        self, event_type: IPCMessageType, payload: dict[str, Any]
    ) -> None:
        """Handle terminal exited event from daemon."""
        if payload.get("session_id") != self.session_id:
            return

        exit_code = payload.get("exit_code", -1)
        self.status = f"Exited (code {exit_code})"
        self._connected = False

        def _post_cleanup() -> None:
            self._cleanup()
            self.post_message(self.Disconnected(exit_code))

        self.call_from_thread(_post_cleanup)

    def _on_terminal_error(
        self, event_type: IPCMessageType, payload: dict[str, Any]
    ) -> None:
        """Handle terminal error event from daemon."""
        if payload.get("session_id") != self.session_id:
            return

        error = payload.get("error", "Unknown error")
        self.status = f"Error: {error}"
        logger.warning(f"Terminal error: {error}")

    def _on_terminal_ready(
        self, event_type: IPCMessageType, payload: dict[str, Any]
    ) -> None:
        """Handle terminal ready event from daemon."""
        if payload.get("session_id") != self.session_id:
            return

        self.status = "Ready"

    # -------------------------------------------------------------------------
    # Keyboard input
    # -------------------------------------------------------------------------

    async def on_key(self, event: events.Key) -> None:
        """Handle keyboard input — encode and send to remote terminal."""
        if not self._connected or not self.session_id:
            return

        encoded = KeyEncoder.encode(event)
        if encoded is None:
            return

        event.prevent_default()
        event.stop()

        bridge = self._get_bridge()
        if bridge is None:
            return

        try:
            await bridge.terminal_input(self.session_id, encoded)
        except Exception as e:
            logger.warning(f"Error sending terminal input: {e}")

    # -------------------------------------------------------------------------
    # Resize handling
    # -------------------------------------------------------------------------

    def on_resize(self, event: events.Resize) -> None:
        """Handle widget resize — update pyte screen and notify remote."""
        # Map widget size to terminal dimensions
        # Subtract chrome (status line + button = ~4 lines)
        new_cols = max(event.size.width, 20)
        new_rows = max(event.size.height - 4, 5)

        if new_cols == self._cols and new_rows == self._rows:
            return

        self._cols = new_cols
        self._rows = new_rows

        # Resize pyte screen
        self._screen.resize(new_rows, new_cols)
        self._update_display()

        # Notify remote if connected
        if self._connected and self.session_id:
            bridge = self._get_bridge()
            if bridge is not None:
                self.run_worker(
                    bridge.terminal_resize(self.session_id, new_rows, new_cols)
                )

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def on_unmount(self) -> None:
        """Clean up on widget removal."""
        if self._connected and self.session_id:
            bridge = self._get_bridge()
            if bridge is not None:
                try:
                    task = asyncio.create_task(bridge.terminal_close(self.session_id))

                    def _consume_close_result(t: asyncio.Task[object]) -> None:
                        try:
                            _ = t.exception()
                        except Exception:
                            pass

                    task.add_done_callback(_consume_close_result)
                except Exception:
                    pass
        self._cleanup()

    def action_disconnect(self) -> None:
        """Disconnect terminal session (ctrl+backslash binding)."""
        if self._connected:
            self.run_worker(self._do_disconnect())
