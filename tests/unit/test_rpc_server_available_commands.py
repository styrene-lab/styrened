"""Unit tests for RPCServer._get_available_commands()."""
from __future__ import annotations

from unittest.mock import patch


class TestGetAvailableCommands:
    """Tests for RPCServer._get_available_commands() method."""

    def _make_server(self, allowed_commands: set[str] | None = None):
        """Create an RPCServer with mocked StyreneProtocol."""
        from unittest.mock import MagicMock

        from styrened.rpc.server import RPCServer

        protocol = MagicMock()
        protocol.register_handler = MagicMock()
        server = RPCServer(protocol, allowed_commands=allowed_commands)
        return server

    def test_filters_to_installed_commands(self):
        """_get_available_commands returns only commands found by shutil.which."""
        server = self._make_server(allowed_commands={"ls", "fake_nonexistent_xyz", "echo"})

        with patch("styrened.rpc.server.shutil.which") as mock_which:
            mock_which.side_effect = lambda cmd: f"/usr/bin/{cmd}" if cmd != "fake_nonexistent_xyz" else None
            result = server._get_available_commands()

        assert result == ["echo", "ls"]  # sorted

    def test_returns_sorted_list(self):
        """Result is sorted alphabetically."""
        server = self._make_server(allowed_commands={"zzz", "aaa", "mmm"})

        with patch("styrened.rpc.server.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/cmd"
            result = server._get_available_commands()

        assert result == ["aaa", "mmm", "zzz"]

    def test_empty_when_nothing_found(self):
        """Returns empty list when no commands are found."""
        server = self._make_server(allowed_commands={"nope1", "nope2"})

        with patch("styrened.rpc.server.shutil.which") as mock_which:
            mock_which.return_value = None
            result = server._get_available_commands()

        assert result == []

    def test_gather_status_includes_available_commands(self):
        """_gather_status() includes available_commands key."""
        server = self._make_server(allowed_commands={"uptime"})

        with (
            patch("styrened.rpc.server.shutil.which", return_value="/usr/bin/uptime"),
            patch.object(server, "_get_uptime", return_value=100),
            patch.object(server, "_get_ip_address", return_value="1.2.3.4"),
            patch.object(server, "_get_services", return_value=[]),
            patch.object(server, "_get_disk_usage", return_value=(0, 0)),
            patch("styrened.rpc.server.get_os_info", return_value={
                "arch": "x86_64",
                "os_id": "test",
                "os_version": "1.0",
                "nixos_generation": "",
            }),
        ):
            status = server._gather_status()

        assert "available_commands" in status
        assert status["available_commands"] == ["uptime"]
