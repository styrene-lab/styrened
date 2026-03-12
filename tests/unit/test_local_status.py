"""Tests for DaemonStatus new fields and local status CLI output.

Tests backwards-compatible serialization of new DaemonStatus fields
(hub_status, hub_address, interfaces, propagation_enabled, transport_enabled,
active_links) and the local status display formatting.
"""
from __future__ import annotations


from unittest.mock import AsyncMock, patch

import pytest

from styrened.ipc.messages import DaemonStatus

# -----------------------------------------------------------------------------
# DaemonStatus serialization tests
# -----------------------------------------------------------------------------


class TestDaemonStatusNewFields:
    """Test new fields on DaemonStatus dataclass."""

    def test_default_values(self):
        """New fields should have sensible defaults for backwards compatibility."""
        status = DaemonStatus(
            uptime=100.0,
            daemon_version="0.10.4",
            rns_initialized=True,
            lxmf_initialized=True,
            device_count=5,
            styrene_node_count=3,
            pending_rpc_count=0,
        )
        assert status.hub_status == "disabled"
        assert status.hub_address is None
        assert status.interfaces == []
        assert status.propagation_enabled is False
        assert status.transport_enabled is False
        assert status.active_links == 0

    def test_to_dict_includes_new_fields(self):
        """to_dict should include all new fields."""
        status = DaemonStatus(
            uptime=3600.0,
            daemon_version="0.10.4",
            rns_initialized=True,
            lxmf_initialized=True,
            device_count=12,
            styrene_node_count=8,
            pending_rpc_count=0,
            interface_count=3,
            hub_status="connected",
            hub_address="6fc8bf22aa293588",
            interfaces=[
                {"name": "TCP Server", "type": "TCPServerInterface", "online": True},
                {"name": "UDP", "type": "UDPInterface", "online": True},
                {"name": "LoRa 915", "type": "RNodeInterface", "online": False},
            ],
            propagation_enabled=False,
            transport_enabled=True,
            active_links=3,
        )
        d = status.to_dict()
        assert d["hub_status"] == "connected"
        assert d["hub_address"] == "6fc8bf22aa293588"
        assert len(d["interfaces"]) == 3
        assert d["interfaces"][2]["online"] is False
        assert d["propagation_enabled"] is False
        assert d["transport_enabled"] is True
        assert d["active_links"] == 3

    def test_from_dict_with_new_fields(self):
        """from_dict should parse all new fields."""
        data = {
            "uptime": 7200.0,
            "daemon_version": "0.10.4",
            "rns_initialized": True,
            "lxmf_initialized": True,
            "device_count": 5,
            "styrene_node_count": 2,
            "pending_rpc_count": 1,
            "interface_count": 2,
            "hub_status": "waiting",
            "hub_address": None,
            "interfaces": [
                {"name": "AutoInterface", "type": "AutoInterface", "online": True},
            ],
            "propagation_enabled": True,
            "transport_enabled": False,
            "active_links": 0,
        }
        status = DaemonStatus.from_dict(data)
        assert status.hub_status == "waiting"
        assert status.hub_address is None
        assert len(status.interfaces) == 1
        assert status.propagation_enabled is True
        assert status.transport_enabled is False
        assert status.active_links == 0

    def test_from_dict_backwards_compatible(self):
        """from_dict should handle old payloads missing new fields."""
        data = {
            "uptime": 100.0,
            "daemon_version": "0.9.0",
            "rns_initialized": True,
            "lxmf_initialized": False,
            "device_count": 0,
            "styrene_node_count": 0,
            "pending_rpc_count": 0,
        }
        status = DaemonStatus.from_dict(data)
        assert status.hub_status == "disabled"
        assert status.hub_address is None
        assert status.interfaces == []
        assert status.propagation_enabled is False
        assert status.transport_enabled is False
        assert status.active_links == 0
        assert status.interface_count == 0

    def test_roundtrip_serialization(self):
        """to_dict -> from_dict should preserve all fields."""
        original = DaemonStatus(
            uptime=999.0,
            daemon_version="0.10.4",
            rns_initialized=True,
            lxmf_initialized=True,
            device_count=10,
            styrene_node_count=7,
            pending_rpc_count=2,
            interface_count=2,
            hub_status="connected",
            hub_address="abcdef1234567890",
            interfaces=[
                {"name": "test", "type": "TestInterface", "online": True},
            ],
            propagation_enabled=True,
            transport_enabled=True,
            active_links=5,
        )
        restored = DaemonStatus.from_dict(original.to_dict())
        assert restored.uptime == original.uptime
        assert restored.hub_status == original.hub_status
        assert restored.hub_address == original.hub_address
        assert restored.interfaces == original.interfaces
        assert restored.propagation_enabled == original.propagation_enabled
        assert restored.transport_enabled == original.transport_enabled
        assert restored.active_links == original.active_links


# -----------------------------------------------------------------------------
# Local status CLI output tests
# -----------------------------------------------------------------------------


class TestLocalStatusOutput:
    """Test the _cmd_local_status output formatting."""

    def _make_status(self, **overrides) -> DaemonStatus:
        """Create a DaemonStatus with sensible defaults."""
        defaults = {
            "uptime": 8072.0,
            "daemon_version": "0.10.4",
            "rns_initialized": True,
            "lxmf_initialized": True,
            "device_count": 12,
            "styrene_node_count": 8,
            "pending_rpc_count": 0,
            "interface_count": 3,
            "hub_status": "connected",
            "hub_address": "6fc8bf22aa293588",
            "interfaces": [
                {"name": "TCP Server", "type": "TCPServerInterface", "online": True},
                {"name": "UDP", "type": "UDPInterface", "online": True},
                {"name": "LoRa 915", "type": "RNodeInterface", "online": False},
            ],
            "transport_enabled": True,
            "active_links": 3,
        }
        defaults.update(overrides)
        return DaemonStatus(**defaults)

    @pytest.mark.asyncio
    @patch("styrened.cli._try_ipc_client")
    async def test_local_status_text_output(self, mock_ipc, capsys):
        """Local status should display daemon, hub, interface, and mesh sections."""
        import argparse

        from styrened.cli import _cmd_local_status

        status = self._make_status()
        mock_client = AsyncMock()
        mock_client.query_status.return_value = status
        mock_ipc.return_value = mock_client

        args = argparse.Namespace(json=False)
        exit_code = await _cmd_local_status(args)
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "0.10.4" in output
        assert "2h 14m 32s" in output
        assert "initialized" in output
        assert "connected" in output
        assert "6fc8bf22aa293588" in output
        assert "[UP]" in output
        assert "[DOWN]" in output
        assert "LoRa 915" in output
        assert "12 total" in output
        assert "8 styrene" in output
        assert "3 active" in output

    @pytest.mark.asyncio
    @patch("styrened.cli._try_ipc_client")
    async def test_local_status_json_output(self, mock_ipc, capsys):
        """JSON mode should output the full DaemonStatus dict."""
        import argparse
        import json

        from styrened.cli import _cmd_local_status

        status = self._make_status()
        mock_client = AsyncMock()
        mock_client.query_status.return_value = status
        mock_ipc.return_value = mock_client

        args = argparse.Namespace(json=True)
        exit_code = await _cmd_local_status(args)
        assert exit_code == 0

        output = capsys.readouterr().out
        data = json.loads(output)
        assert data["hub_status"] == "connected"
        assert data["transport_enabled"] is True
        assert len(data["interfaces"]) == 3

    @pytest.mark.asyncio
    @patch("styrened.cli._try_ipc_client", return_value=None)
    async def test_local_status_no_daemon(self, mock_ipc, capsys):
        """Should report error when daemon is not running."""
        import argparse

        from styrened.cli import _cmd_local_status

        args = argparse.Namespace(json=False)
        exit_code = await _cmd_local_status(args)
        assert exit_code == 1

        output = capsys.readouterr().err
        assert "not running" in output.lower()

    @pytest.mark.asyncio
    @patch("styrened.cli._try_ipc_client")
    async def test_local_status_hub_disabled_hidden(self, mock_ipc, capsys):
        """Hub section should be hidden when hub is disabled."""
        import argparse

        from styrened.cli import _cmd_local_status

        status = self._make_status(hub_status="disabled", hub_address=None)
        mock_client = AsyncMock()
        mock_client.query_status.return_value = status
        mock_ipc.return_value = mock_client

        args = argparse.Namespace(json=False)
        exit_code = await _cmd_local_status(args)
        assert exit_code == 0

        output = capsys.readouterr().out
        assert "Hub" not in output
