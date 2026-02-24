"""Unit tests for CLI module.

Tests argument parsing, command structure, and basic command behavior
without requiring actual mesh network connectivity.
"""

import argparse
from unittest.mock import AsyncMock, patch

import pytest

from styrened.cli import create_parser


class TestArgumentParser:
    """Tests for CLI argument parser."""

    def test_create_parser_returns_parser(self):
        """create_parser should return an ArgumentParser."""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_has_version_argument(self):
        """Parser should have --version argument."""
        parser = create_parser()
        # Check that --version is registered
        actions = [a.option_strings for a in parser._actions if a.option_strings]
        assert any("--version" in opts for opts in actions)

    def test_parser_has_verbose_argument(self):
        """Parser should have --verbose argument."""
        parser = create_parser()
        args = parser.parse_args(["--verbose", "devices"])
        assert args.verbose is True

    def test_parser_default_verbose_false(self):
        """Default verbose should be False."""
        parser = create_parser()
        args = parser.parse_args(["devices"])
        assert args.verbose is False


class TestSubcommandParsing:
    """Tests for subcommand argument parsing."""

    def test_devices_command_parsing(self):
        """devices command should parse correctly."""
        parser = create_parser()
        args = parser.parse_args(["devices"])
        assert args.command == "devices"
        assert args.wait == 5  # default
        assert args.json is False  # default

    def test_devices_with_wait_option(self):
        """devices --wait should parse wait time."""
        parser = create_parser()
        args = parser.parse_args(["devices", "-w", "10"])
        assert args.wait == 10

    def test_devices_with_json_option(self):
        """devices --json should enable JSON output."""
        parser = create_parser()
        args = parser.parse_args(["devices", "--json"])
        assert args.json is True

    def test_status_command_destination_optional(self):
        """status command without destination should default to local status."""
        parser = create_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"
        assert args.destination is None

    def test_status_command_with_destination(self):
        """status command should parse destination."""
        parser = create_parser()
        args = parser.parse_args(["status", "a1b2c3d4e5f6a7b8"])
        assert args.command == "status"
        assert args.destination == "a1b2c3d4e5f6a7b8"

    def test_status_with_timeout(self):
        """status --timeout should parse timeout value."""
        parser = create_parser()
        args = parser.parse_args(["status", "a1b2c3d4", "-t", "45.0"])
        assert args.timeout == 45.0

    def test_send_command_requires_destination_and_message(self):
        """send command should require destination and message."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["send"])  # Missing required arguments
        with pytest.raises(SystemExit):
            parser.parse_args(["send", "dest"])  # Missing message

    def test_send_command_with_arguments(self):
        """send command should parse destination and message."""
        parser = create_parser()
        args = parser.parse_args(["send", "a1b2c3d4", "Hello world"])
        assert args.command == "send"
        assert args.destination == "a1b2c3d4"
        assert args.message == "Hello world"

    def test_send_with_retry_option(self):
        """send --retry should enable retry mode."""
        parser = create_parser()
        args = parser.parse_args(["send", "a1b2c3d4", "msg", "-r"])
        assert args.retry is True

    def test_exec_command_requires_destination_and_command(self):
        """exec command should require destination and command."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["exec"])  # Missing required arguments
        with pytest.raises(SystemExit):
            parser.parse_args(["exec", "dest"])  # Missing command

    def test_exec_command_with_arguments(self):
        """exec command should parse destination and command."""
        parser = create_parser()
        # Note: The exec subparser has a positional "command" argument that
        # shadows the subparser dest="command". So args.command will be the
        # remote command ("uptime"), not the subcommand name ("exec").
        args = parser.parse_args(["exec", "a1b2c3d4", "uptime"])
        assert args.destination == "a1b2c3d4"
        assert args.command == "uptime"  # Remote command to execute
        assert hasattr(args, "func")

    def test_exec_command_with_extra_args(self):
        """exec command should capture extra arguments."""
        parser = create_parser()
        # Arguments starting with - need to be after -- to be treated as positional
        # Or we need to test without dash-prefixed args
        args = parser.parse_args(["exec", "a1b2c3d4", "ls", "foo", "bar"])
        assert args.command == "ls"  # Remote command
        assert args.args == ["foo", "bar"]
        assert args.destination == "a1b2c3d4"

    def test_announce_command_parsing(self):
        """announce command should parse without arguments."""
        parser = create_parser()
        args = parser.parse_args(["announce"])
        assert args.command == "announce"

    def test_identity_command_parsing(self):
        """identity command should parse without arguments."""
        parser = create_parser()
        args = parser.parse_args(["identity"])
        assert args.command == "identity"
        assert args.create is False  # default

    def test_identity_with_create_option(self):
        """identity --create should enable identity creation."""
        parser = create_parser()
        args = parser.parse_args(["identity", "--create"])
        assert args.create is True

    def test_version_command_parsing(self):
        """version command should parse correctly."""
        parser = create_parser()
        args = parser.parse_args(["version"])
        assert args.command == "version"


class TestCommandFunctions:
    """Tests for command function behavior."""

    def test_cmd_version_returns_zero(self):
        """cmd_version should return 0."""
        from styrened.cli import cmd_version

        args = argparse.Namespace(json=False)
        result = cmd_version(args)
        assert result == 0

    def test_cmd_version_json_output(self):
        """cmd_version with --json should return JSON."""
        import json
        from io import StringIO

        from styrened.cli import cmd_version

        args = argparse.Namespace(json=True)

        # Capture stdout
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            result = cmd_version(args)

        assert result == 0
        output = mock_stdout.getvalue()
        data = json.loads(output)
        assert "version" in data
        assert "name" in data
        assert data["name"] == "styrened"


class TestSetupLogging:
    """Tests for logging setup."""

    def test_setup_logging_default_level(self):
        """Default logging level should be INFO."""
        from styrened.cli import setup_logging

        with patch("logging.basicConfig") as mock_config:
            setup_logging(verbose=False)
            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["level"] == 20  # logging.INFO

    def test_setup_logging_verbose_level(self):
        """Verbose logging level should be DEBUG."""
        from styrened.cli import setup_logging

        with patch("logging.basicConfig") as mock_config:
            setup_logging(verbose=True)
            mock_config.assert_called_once()
            call_kwargs = mock_config.call_args[1]
            assert call_kwargs["level"] == 10  # logging.DEBUG


class TestIPCClientFallback:
    """Tests for IPC client fallback behavior."""

    @pytest.mark.asyncio
    async def test_try_ipc_client_returns_none_on_failure(self):
        """_try_ipc_client should return None when connection fails."""
        from styrened.cli import _try_ipc_client

        # Patch the import inside _try_ipc_client
        with patch(
            "styrened.ipc.get_daemon_client",
            side_effect=Exception("Connection refused"),
        ):
            result = await _try_ipc_client()
            assert result is None

    @pytest.mark.asyncio
    async def test_try_ipc_client_returns_client_on_success(self):
        """_try_ipc_client should return client when connection succeeds."""
        from styrened.cli import _try_ipc_client

        mock_client = AsyncMock()
        # Patch the module function that gets imported
        with patch("styrened.ipc.get_daemon_client", return_value=mock_client):
            result = await _try_ipc_client()
            assert result is mock_client


class TestIdentityCommands:
    """Tests for identity-related commands."""

    def test_cmd_identity_shows_hash(self):
        """cmd_identity should display identity hash."""
        from io import StringIO

        from styrened.cli import cmd_identity

        args = argparse.Namespace(json=False, create=False)

        mock_hash = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

        # Patch the function where it's used (imported inside cmd_identity)
        with patch(
            "styrened.services.reticulum.get_operator_identity",
            return_value=mock_hash,
        ):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                result = cmd_identity(args)

        assert result == 0
        assert mock_hash in mock_stdout.getvalue()

    def test_cmd_identity_returns_error_when_no_identity(self):
        """cmd_identity should return 1 when no identity exists."""
        from styrened.cli import cmd_identity

        args = argparse.Namespace(json=False, create=False)

        with patch(
            "styrened.services.reticulum.get_operator_identity",
            return_value=None,
        ):
            result = cmd_identity(args)

        assert result == 1
