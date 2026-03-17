"""Unit tests for KeyEncoder — Textual Key → VT100 mapping.

Tests that all key types (printable, arrows, function keys, ctrl combos)
are correctly mapped to their VT100/xterm escape sequences.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from styrened.tui.widgets.terminal_widget import KeyEncoder


def _make_key(key_name: str, character: str | None = None) -> MagicMock:
    """Create a mock Textual Key event.

    Args:
        key_name: The key name (e.g., "a", "enter", "ctrl+c").
        character: The character property (printable char or None).

    Returns:
        Mock Key event.
    """
    mock = MagicMock()
    mock.key = key_name
    mock.character = character
    return mock


class TestPrintableCharacters:
    """Test encoding of printable characters."""

    def test_lowercase_letter(self):
        """Lowercase letter should encode to UTF-8."""
        result = KeyEncoder.encode(_make_key("a", "a"))
        assert result == b"a"

    def test_uppercase_letter(self):
        """Uppercase letter should encode to UTF-8."""
        result = KeyEncoder.encode(_make_key("A", "A"))
        assert result == b"A"

    def test_digit(self):
        """Digit should encode to UTF-8."""
        result = KeyEncoder.encode(_make_key("1", "1"))
        assert result == b"1"

    def test_symbol(self):
        """Symbol should encode to UTF-8."""
        result = KeyEncoder.encode(_make_key("@", "@"))
        assert result == b"@"

    def test_space(self):
        """Space should encode to space byte."""
        result = KeyEncoder.encode(_make_key("space"))
        assert result == b" "

    def test_unicode_character(self):
        """Unicode character should encode to UTF-8."""
        result = KeyEncoder.encode(_make_key("é", "é"))
        assert result == "é".encode()


class TestControlKeys:
    """Test encoding of control key combinations."""

    def test_enter(self):
        """Enter should encode to carriage return."""
        result = KeyEncoder.encode(_make_key("enter"))
        assert result == b"\r"

    def test_tab(self):
        """Tab should encode to tab character."""
        result = KeyEncoder.encode(_make_key("tab"))
        assert result == b"\t"

    def test_backspace(self):
        """Backspace should encode to DEL (0x7f)."""
        result = KeyEncoder.encode(_make_key("backspace"))
        assert result == b"\x7f"

    def test_escape(self):
        """Escape should encode to ESC (0x1b)."""
        result = KeyEncoder.encode(_make_key("escape"))
        assert result == b"\x1b"

    def test_delete(self):
        """Delete should encode to xterm delete sequence."""
        result = KeyEncoder.encode(_make_key("delete"))
        assert result == b"\x1b[3~"


class TestCtrlCombinations:
    """Test encoding of Ctrl+letter combinations."""

    def test_ctrl_a(self):
        """Ctrl+A should encode to SOH (0x01)."""
        result = KeyEncoder.encode(_make_key("ctrl+a"))
        assert result == b"\x01"

    def test_ctrl_c(self):
        """Ctrl+C should encode to ETX (0x03)."""
        result = KeyEncoder.encode(_make_key("ctrl+c"))
        assert result == b"\x03"

    def test_ctrl_d(self):
        """Ctrl+D should encode to EOT (0x04)."""
        result = KeyEncoder.encode(_make_key("ctrl+d"))
        assert result == b"\x04"

    def test_ctrl_z(self):
        """Ctrl+Z should encode to SUB (0x1A)."""
        result = KeyEncoder.encode(_make_key("ctrl+z"))
        assert result == b"\x1a"

    def test_ctrl_l(self):
        """Ctrl+L should encode to FF (0x0C) — clear screen."""
        result = KeyEncoder.encode(_make_key("ctrl+l"))
        assert result == b"\x0c"


class TestArrowKeys:
    """Test encoding of arrow keys."""

    def test_up(self):
        """Up arrow should encode to CSI A."""
        result = KeyEncoder.encode(_make_key("up"))
        assert result == b"\x1b[A"

    def test_down(self):
        """Down arrow should encode to CSI B."""
        result = KeyEncoder.encode(_make_key("down"))
        assert result == b"\x1b[B"

    def test_right(self):
        """Right arrow should encode to CSI C."""
        result = KeyEncoder.encode(_make_key("right"))
        assert result == b"\x1b[C"

    def test_left(self):
        """Left arrow should encode to CSI D."""
        result = KeyEncoder.encode(_make_key("left"))
        assert result == b"\x1b[D"


class TestNavigationKeys:
    """Test encoding of navigation keys."""

    def test_home(self):
        """Home should encode to CSI H."""
        result = KeyEncoder.encode(_make_key("home"))
        assert result == b"\x1b[H"

    def test_end(self):
        """End should encode to CSI F."""
        result = KeyEncoder.encode(_make_key("end"))
        assert result == b"\x1b[F"

    def test_pageup(self):
        """PageUp should encode to CSI 5~."""
        result = KeyEncoder.encode(_make_key("pageup"))
        assert result == b"\x1b[5~"

    def test_pagedown(self):
        """PageDown should encode to CSI 6~."""
        result = KeyEncoder.encode(_make_key("pagedown"))
        assert result == b"\x1b[6~"

    def test_insert(self):
        """Insert should encode to CSI 2~."""
        result = KeyEncoder.encode(_make_key("insert"))
        assert result == b"\x1b[2~"


class TestFunctionKeys:
    """Test encoding of function keys."""

    def test_f1(self):
        """F1 should encode to SS3 P."""
        result = KeyEncoder.encode(_make_key("f1"))
        assert result == b"\x1bOP"

    def test_f2(self):
        """F2 should encode to SS3 Q."""
        result = KeyEncoder.encode(_make_key("f2"))
        assert result == b"\x1bOQ"

    def test_f3(self):
        """F3 should encode to SS3 R."""
        result = KeyEncoder.encode(_make_key("f3"))
        assert result == b"\x1bOR"

    def test_f4(self):
        """F4 should encode to SS3 S."""
        result = KeyEncoder.encode(_make_key("f4"))
        assert result == b"\x1bOS"

    def test_f5(self):
        """F5 should encode to CSI 15~."""
        result = KeyEncoder.encode(_make_key("f5"))
        assert result == b"\x1b[15~"

    def test_f12(self):
        """F12 should encode to CSI 24~."""
        result = KeyEncoder.encode(_make_key("f12"))
        assert result == b"\x1b[24~"


class TestEdgeCases:
    """Test edge cases and unknown keys."""

    def test_unknown_key_returns_none(self):
        """Unknown key name with no character should return None."""
        result = KeyEncoder.encode(_make_key("super+x"))
        assert result is None

    def test_empty_character_returns_none(self):
        """Key with empty character should return None."""
        result = KeyEncoder.encode(_make_key("unknown", ""))
        assert result is None
