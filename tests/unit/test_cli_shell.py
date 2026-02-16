"""Unit tests for the CLI shell command.

These tests verify the `styrened shell <dest>` command:
- Argument parsing
- Destination validation
- Terminal size detection
- Integration with TerminalClient

TDD RED PHASE: Shell command doesn't exist yet. These tests document
expected behavior for Phase 3 implementation.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass


# Check if shell command exists in CLI
try:
    from styrened.cli import cmd_shell

    HAS_SHELL_COMMAND = True
except ImportError:
    HAS_SHELL_COMMAND = False
    cmd_shell = None


def skip_if_no_shell_command():
    """Skip test if shell command not implemented."""
    if not HAS_SHELL_COMMAND:
        pytest.skip("Shell command not yet implemented. Implement cmd_shell() in cli.py (Phase 3)")


class TestShellArgumentParsing:
    """Tests for shell command argument parsing."""

    def test_shell_subparser_exists(self) -> None:
        """CLI should have a 'shell' subcommand."""
        from styrened.cli import create_parser

        # Check if create_parser exists, otherwise check main
        if hasattr(sys.modules.get("styrened.cli"), "create_parser"):
            parser = create_parser()
        else:
            # Try to get subparsers from argument parsing
            pytest.skip("Need to check parser structure differently")

        # The parser should accept 'shell' as a subcommand
        # This test documents the expectation
        try:
            args = parser.parse_args(["shell", "abc123def456"])
            assert args.command == "shell" or hasattr(args, "func")
        except (SystemExit, AttributeError):
            pytest.fail(
                "CLI should have 'shell' subcommand. "
                "Add shell_parser = subparsers.add_parser('shell', ...) in cli.py"
            )

    def test_shell_requires_destination(self) -> None:
        """Shell command should require a destination argument via argparse."""
        from styrened.cli import create_parser

        parser = create_parser()

        # Parsing without destination should fail
        with pytest.raises(SystemExit):
            parser.parse_args(["shell"])  # Missing required destination

    def test_shell_accepts_destination(self) -> None:
        """Shell command should accept destination hash via argparse."""
        from styrened.cli import create_parser

        parser = create_parser()

        # Valid 32-char hex destination
        destination = "a" * 32
        args = parser.parse_args(["shell", destination])

        assert args.destination == destination
        assert args.func == cmd_shell


class TestDestinationValidation:
    """Tests for destination format validation."""

    def test_validates_hex_format(self) -> None:
        """Destination should be validated as hexadecimal in cmd_shell."""
        skip_if_no_shell_command()

        # Invalid: contains non-hex characters
        invalid_dest = "ghijklmnopqrstuv" * 2  # 32 chars but not hex

        args = argparse.Namespace(
            destination=invalid_dest,
            term_type="xterm-256color",
            rows=24,
            cols=80,
            wait=15,
        )

        # cmd_shell validates hex format and returns error code
        exit_code = cmd_shell(args)
        assert exit_code == 1, "Invalid hex should return exit code 1"

    def test_validates_length(self) -> None:
        """Destination should be 32 hex characters (16 bytes)."""
        skip_if_no_shell_command()

        # Invalid: too short
        short_dest = "abc123"

        args = argparse.Namespace(
            destination=short_dest,
            term_type="xterm-256color",
            rows=24,
            cols=80,
            wait=15,
        )

        # cmd_shell validates length and returns error code
        exit_code = cmd_shell(args)
        assert exit_code == 1, "Short destination should return exit code 1"

    def test_accepts_valid_destination(self) -> None:
        """Valid 32-char hex destination should pass validation."""
        from styrened.cli import create_parser

        parser = create_parser()

        # Valid destination
        valid_dest = "abcdef0123456789" * 2  # 32 hex chars
        args = parser.parse_args(["shell", valid_dest])

        assert args.destination == valid_dest


class TestTerminalSizeDetection:
    """Tests for automatic terminal size detection via argparse."""

    def test_rows_cols_default_to_none(self) -> None:
        """Rows and cols should default to None for auto-detection."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["shell", "a" * 32])

        assert args.rows is None, "Rows should default to None"
        assert args.cols is None, "Cols should default to None"

    def test_accepts_explicit_size(self) -> None:
        """Shell should accept explicitly specified rows/cols."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["shell", "a" * 32, "-r", "50", "-c", "200"])

        assert args.rows == 50
        assert args.cols == 200


class TestTermTypeOption:
    """Tests for terminal type option."""

    def test_term_type_default_to_none(self) -> None:
        """Terminal type should default to None (uses $TERM or xterm-256color)."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["shell", "a" * 32])

        assert args.term_type is None, "term_type should default to None"

    def test_custom_term_type(self) -> None:
        """Shell should accept custom terminal types."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["shell", "a" * 32, "-T", "vt100"])

        assert args.term_type == "vt100"


class TestWaitOption:
    """Tests for discovery wait option."""

    def test_wait_default(self) -> None:
        """Wait should default to 15 seconds."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["shell", "a" * 32])

        assert args.wait == 15

    def test_custom_wait(self) -> None:
        """Shell should accept custom wait time."""
        from styrened.cli import create_parser

        parser = create_parser()
        args = parser.parse_args(["shell", "a" * 32, "-w", "30"])

        assert args.wait == 30


class TestExitCodeHandling:
    """Tests for exit code propagation - documented expectations."""

    def test_returns_one_on_invalid_destination(self) -> None:
        """Shell should return 1 on invalid destination."""
        skip_if_no_shell_command()

        args = argparse.Namespace(
            destination="not-valid-hex!",
            term_type="xterm-256color",
            rows=24,
            cols=80,
            wait=15,
        )

        exit_code = cmd_shell(args)
        assert exit_code == 1
