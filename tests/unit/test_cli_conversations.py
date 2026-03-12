"""Unit tests for conversations and messages CLI subcommands.

Tests argument parsing and basic command behavior for the
conversations and messages subcommands.
"""
from __future__ import annotations


import argparse
import json
from io import StringIO
from unittest.mock import AsyncMock, patch

import pytest

from styrened.cli import create_parser


class TestConversationsSubcommandParsing:
    """Tests for conversations subcommand argument parsing."""

    def test_parser_recognizes_conversations_subcommand(self):
        """Parser should recognize the conversations subcommand."""
        parser = create_parser()
        args = parser.parse_args(["conversations"])
        assert args.command == "conversations"

    def test_conversations_default_json_false(self):
        """conversations --json default should be False."""
        parser = create_parser()
        args = parser.parse_args(["conversations"])
        assert args.json is False

    def test_conversations_with_json_flag(self):
        """conversations --json should enable JSON output."""
        parser = create_parser()
        args = parser.parse_args(["conversations", "--json"])
        assert args.json is True

    def test_conversations_has_func(self):
        """conversations should have func attribute set."""
        parser = create_parser()
        args = parser.parse_args(["conversations"])
        assert hasattr(args, "func")


class TestMessagesSubcommandParsing:
    """Tests for messages subcommand argument parsing."""

    def test_parser_recognizes_messages_subcommand(self):
        """Parser should recognize the messages subcommand."""
        parser = create_parser()
        args = parser.parse_args(["messages", "abcd1234"])
        assert args.command == "messages"

    def test_messages_requires_peer_hash(self):
        """messages command should require peer_hash positional arg."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["messages"])

    def test_messages_parses_peer_hash(self):
        """messages should parse the peer_hash positional argument."""
        parser = create_parser()
        args = parser.parse_args(["messages", "a1b2c3d4e5f6a7b8"])
        assert args.peer_hash == "a1b2c3d4e5f6a7b8"

    def test_messages_default_limit_50(self):
        """messages default limit should be 50."""
        parser = create_parser()
        args = parser.parse_args(["messages", "abcd1234"])
        assert args.limit == 50

    def test_messages_custom_limit(self):
        """messages -n should set custom limit."""
        parser = create_parser()
        args = parser.parse_args(["messages", "abcd1234", "-n", "100"])
        assert args.limit == 100

    def test_messages_limit_long_option(self):
        """messages --limit should set custom limit."""
        parser = create_parser()
        args = parser.parse_args(["messages", "abcd1234", "--limit", "25"])
        assert args.limit == 25

    def test_messages_json_flag(self):
        """messages --json should enable JSON output."""
        parser = create_parser()
        args = parser.parse_args(["messages", "abcd1234", "--json"])
        assert args.json is True

    def test_messages_status_filter(self):
        """messages --status should set status filter."""
        parser = create_parser()
        args = parser.parse_args(["messages", "abcd1234", "--status", "delivered"])
        assert args.status == "delivered"

    def test_messages_default_status_none(self):
        """messages default status filter should be None."""
        parser = create_parser()
        args = parser.parse_args(["messages", "abcd1234"])
        assert args.status is None

    def test_messages_has_func(self):
        """messages should have func attribute set."""
        parser = create_parser()
        args = parser.parse_args(["messages", "abcd1234"])
        assert hasattr(args, "func")


class TestConversationsCommand:
    """Tests for conversations command behavior."""

    @pytest.mark.asyncio
    async def test_conversations_json_output(self):
        """conversations --json should output conversation list as JSON."""
        from styrened.cli import _cmd_conversations_async

        mock_client = AsyncMock()
        mock_client.query_conversations.return_value = [
            {
                "peer_hash": "abcd1234",
                "unread_count": 2,
                "message_count": 10,
                "last_message_timestamp": 1700000000.0,
                "last_message_preview": "Hello!",
            }
        ]
        mock_client.disconnect = AsyncMock()

        args = argparse.Namespace(json=True)

        with patch("styrened.cli._try_ipc_client", return_value=mock_client):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                result = await _cmd_conversations_async(args)

        assert result == 0
        output = json.loads(mock_stdout.getvalue())
        assert len(output) == 1
        assert output[0]["peer_hash"] == "abcd1234"

    @pytest.mark.asyncio
    async def test_conversations_no_daemon(self):
        """conversations should error when daemon is not running."""
        from styrened.cli import _cmd_conversations_async

        args = argparse.Namespace(json=False)

        with patch("styrened.cli._try_ipc_client", return_value=None):
            result = await _cmd_conversations_async(args)

        assert result == 1


class TestMessagesCommand:
    """Tests for messages command behavior."""

    @pytest.mark.asyncio
    async def test_messages_json_output(self):
        """messages --json should output message list as JSON."""
        from styrened.cli import _cmd_messages_async

        mock_client = AsyncMock()
        mock_client.query_messages.return_value = [
            {
                "id": 1,
                "peer_hash": "abcd1234",
                "content": "Hello!",
                "timestamp": 1700000000.0,
                "is_outgoing": True,
                "status": "delivered",
            }
        ]
        mock_client.disconnect = AsyncMock()

        args = argparse.Namespace(
            peer_hash="abcd1234", limit=50, status=None, json=True
        )

        with patch("styrened.cli._try_ipc_client", return_value=mock_client):
            with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
                result = await _cmd_messages_async(args)

        assert result == 0
        output = json.loads(mock_stdout.getvalue())
        assert len(output) == 1
        assert output[0]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_messages_no_daemon(self):
        """messages should error when daemon is not running."""
        from styrened.cli import _cmd_messages_async

        args = argparse.Namespace(
            peer_hash="abcd1234", limit=50, status=None, json=False
        )

        with patch("styrened.cli._try_ipc_client", return_value=None):
            result = await _cmd_messages_async(args)

        assert result == 1
