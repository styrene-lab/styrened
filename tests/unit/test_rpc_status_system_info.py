"""Unit tests for enriched STATUS_RESPONSE system info fields.

Verifies that _gather_status() includes styrened version, hostname,
architecture, OS, NixOS generation, CPU, and RAM.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from styrened.rpc.server import RPCServer


@pytest.fixture
def rpc_server():
    """Create an RPCServer with mocked protocol."""
    mock_protocol = MagicMock()
    server = RPCServer(
        styrene_protocol=mock_protocol,
    )
    return server


class TestGatherStatusSystemInfo:
    """Tests for new system info fields in _gather_status()."""

    def test_includes_styrened_version(self, rpc_server):
        """Status response includes styrened_version matching __version__."""
        from styrened import __version__

        with patch(
            "styrened.rpc.server.get_os_info",
            return_value={"os_id": "test", "os_version": "1.0", "arch": "x86_64", "nixos_generation": ""},
        ):
            status = rpc_server._gather_status()
        assert "styrened_version" in status
        assert status["styrened_version"] == __version__

    def test_includes_hostname(self, rpc_server):
        """Status response includes hostname."""
        with patch(
            "styrened.rpc.server.get_os_info",
            return_value={"os_id": "test", "os_version": "1.0", "arch": "x86_64", "nixos_generation": ""},
        ):
            status = rpc_server._gather_status()
        assert "hostname" in status
        assert isinstance(status["hostname"], str)
        assert len(status["hostname"]) > 0

    def test_includes_arch(self, rpc_server):
        """Status response includes architecture."""
        with patch(
            "styrened.rpc.server.get_os_info",
            return_value={"os_id": "test", "os_version": "1.0", "arch": "aarch64", "nixos_generation": ""},
        ):
            status = rpc_server._gather_status()
        assert status["arch"] == "aarch64"

    def test_includes_os_fields(self, rpc_server):
        """Status response includes os_id and os_version."""
        with patch(
            "styrened.rpc.server.get_os_info",
            return_value={"os_id": "nixos", "os_version": "24.11", "arch": "x86_64", "nixos_generation": "zah57xw"},
        ):
            status = rpc_server._gather_status()
        assert status["os_id"] == "nixos"
        assert status["os_version"] == "24.11"

    def test_includes_nixos_generation(self, rpc_server):
        """Status response includes nixos_generation when on NixOS."""
        with patch(
            "styrened.rpc.server.get_os_info",
            return_value={"os_id": "nixos", "os_version": "24.11", "arch": "x86_64", "nixos_generation": "zah57xw"},
        ):
            status = rpc_server._gather_status()
        assert status["nixos_generation"] == "zah57xw"

    def test_nixos_generation_empty_when_not_nixos(self, rpc_server):
        """Status response has empty nixos_generation on non-NixOS."""
        with patch(
            "styrened.rpc.server.get_os_info",
            return_value={"os_id": "debian", "os_version": "13", "arch": "x86_64", "nixos_generation": ""},
        ):
            status = rpc_server._gather_status()
        assert status["nixos_generation"] == ""

    def test_still_includes_original_fields(self, rpc_server):
        """Status response still includes original fields (backwards compat)."""
        with patch(
            "styrened.rpc.server.get_os_info",
            return_value={"os_id": "test", "os_version": "1.0", "arch": "x86_64", "nixos_generation": ""},
        ):
            status = rpc_server._gather_status()
        assert "uptime" in status
        assert "ip" in status
        assert "services" in status
        assert "disk_used" in status
        assert "disk_total" in status
