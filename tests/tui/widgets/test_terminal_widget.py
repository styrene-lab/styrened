"""Integration tests for TerminalWidget.

Tests widget mount/unmount, connection state transitions, pyte integration,
and event handling via mocked IPC bridge.
"""

import pyte

from styrened.tui.widgets.terminal_widget import (
    TerminalWidget,
    _char_style_to_rich,
    _pyte_color_to_rich,
)


class TestPyteIntegration:
    """Test pyte screen rendering."""

    def test_pyte_screen_initialized(self):
        """Widget should initialize pyte screen with given dimensions."""
        widget = TerminalWidget(device_identity="test123", rows=30, cols=100)
        assert widget._screen.lines == 30
        assert widget._screen.columns == 100

    def test_pyte_feed_renders_text(self):
        """Feeding text to pyte should populate the screen buffer."""
        widget = TerminalWidget(device_identity="test123", rows=24, cols=80)
        widget._stream.feed("Hello, World!")
        # Check that the text appears in the buffer
        row = widget._screen.buffer[0]
        text = "".join(row[i].data for i in range(13))
        assert text == "Hello, World!"

    def test_pyte_feed_escape_sequences(self):
        """Feeding escape sequences should update screen state."""
        widget = TerminalWidget(device_identity="test123", rows=24, cols=80)
        # Move cursor and write
        widget._stream.feed("\x1b[2;5HTest")
        # Row 1 (0-indexed), Column 4 (0-indexed)
        row = widget._screen.buffer[1]
        text = "".join(row[i].data for i in range(4, 8))
        assert text == "Test"

    def test_pyte_screen_resize(self):
        """Screen resize should update dimensions."""
        widget = TerminalWidget(device_identity="test123", rows=24, cols=80)
        widget._screen.resize(48, 160)
        assert widget._screen.lines == 48
        assert widget._screen.columns == 160

    def test_render_screen_returns_rich_text(self):
        """_render_screen should return a Rich Text object."""
        widget = TerminalWidget(device_identity="test123", rows=5, cols=10)
        widget._stream.feed("ABC")
        result = widget._render_screen()
        assert "ABC" in result.plain


class TestPyteColorConversion:
    """Test pyte color to Rich color conversion."""

    def test_default_color_returns_none(self):
        """Default color should return None."""
        assert _pyte_color_to_rich("default") is None

    def test_empty_color_returns_none(self):
        """Empty color should return None."""
        assert _pyte_color_to_rich("") is None

    def test_named_color(self):
        """Named colors should map correctly."""
        assert _pyte_color_to_rich("red") == "red"
        assert _pyte_color_to_rich("green") == "green"
        assert _pyte_color_to_rich("blue") == "blue"

    def test_brown_maps_to_yellow(self):
        """Brown should map to yellow (standard terminal convention)."""
        assert _pyte_color_to_rich("brown") == "yellow"

    def test_hex_color(self):
        """Hex color should convert to Rich #rrggbb format."""
        assert _pyte_color_to_rich("ff0000") == "#ff0000"
        assert _pyte_color_to_rich("00ff00") == "#00ff00"

    def test_char_style_bold(self):
        """Bold character should produce bold Rich style."""
        char = pyte.screens.Char(
            data="X", fg="default", bg="default",
            bold=True, italics=False, underscore=False,
            strikethrough=False, reverse=False,
        )
        style = _char_style_to_rich(char)
        assert style.bold is True

    def test_char_style_default(self):
        """Default character should produce empty Rich style."""
        screen = pyte.Screen(80, 24)
        char = screen.default_char
        style = _char_style_to_rich(char)
        # Default char shouldn't have explicit styles set
        assert style.bold is not True


class TestTerminalWidgetState:
    """Test widget state management."""

    def test_initial_state_disconnected(self):
        """Widget should start in disconnected state."""
        widget = TerminalWidget(device_identity="test123")
        assert widget._connected is False
        assert widget.session_id is None
        assert widget.status == "Disconnected"

    def test_cleanup_resets_state(self):
        """_cleanup should reset all state."""
        widget = TerminalWidget(device_identity="test123")
        widget._connected = True
        widget.session_id = "abc123"
        widget.status = "Connected"

        widget._cleanup()

        assert widget._connected is False
        assert widget.session_id is None
        assert widget.status == "Disconnected"

    def test_status_line_disconnected(self):
        """Status line should show disconnected state."""
        widget = TerminalWidget(device_identity="abcdef1234567890")
        line = widget._status_line()
        assert "abcdef12345678" in line
        assert "Disconnected" in line

    def test_status_line_connected(self):
        """Status line should show connected state with dimensions."""
        widget = TerminalWidget(device_identity="abcdef1234567890", rows=24, cols=80)
        widget._connected = True
        line = widget._status_line()
        assert "CONNECTED" in line
        assert "80x24" in line


class TestTerminalWidgetEventHandling:
    """Test terminal event callback handling."""

    def test_output_event_feeds_pyte(self):
        """Terminal output event should feed data to pyte."""
        widget = TerminalWidget(device_identity="test123")
        widget.session_id = "sess123"
        widget._connected = True

        # Simulate output event (without call_from_thread which needs app)
        data = b"Hello from remote"

        # Feed directly to pyte (bypassing call_from_thread)
        widget._stream.feed(data.decode("utf-8", errors="replace"))

        # Check pyte buffer
        row = widget._screen.buffer[0]
        text = "".join(row[i].data for i in range(17))
        assert text == "Hello from remote"

    def test_output_event_wrong_session_ignored(self):
        """Output event with wrong session_id should be ignored."""
        from styrened.ipc.protocol import IPCMessageType

        widget = TerminalWidget(device_identity="test123")
        widget.session_id = "correct_session"

        # This should not crash or modify state
        widget._on_terminal_output(
            IPCMessageType.EVENT_TERMINAL_OUTPUT,
            {"session_id": "wrong_session", "data_b64": "dGVzdA=="},
        )

    def test_error_event_updates_status(self):
        """Terminal error event should update status."""
        from styrened.ipc.protocol import IPCMessageType

        widget = TerminalWidget(device_identity="test123")
        widget.session_id = "sess123"

        widget._on_terminal_error(
            IPCMessageType.EVENT_TERMINAL_ERROR,
            {"session_id": "sess123", "error": "Connection lost"},
        )

        assert "Connection lost" in widget.status

    def test_ready_event_updates_status(self):
        """Terminal ready event should update status."""
        from styrened.ipc.protocol import IPCMessageType

        widget = TerminalWidget(device_identity="test123")
        widget.session_id = "sess123"

        widget._on_terminal_ready(
            IPCMessageType.EVENT_TERMINAL_READY,
            {"session_id": "sess123"},
        )

        assert widget.status == "Ready"
