"""Tests for NodeInfoPanel widget.

Tests IPC-aware daemon section, uptime formatting, nuanced RNS labels,
and gating of local queries behind ipc_managed flag.
"""

from unittest.mock import MagicMock, patch

from styrened.models.rns_error import RNSErrorCategory, RNSErrorState
from styrened.tui.widgets.node_info_panel import NodeInfoPanel


class TestFormatUptime:
    """Test _format_uptime static helper."""

    def test_format_uptime_seconds(self) -> None:
        """Sub-minute uptime shows seconds."""
        assert NodeInfoPanel._format_uptime(0) == "0s"
        assert NodeInfoPanel._format_uptime(45) == "45s"
        assert NodeInfoPanel._format_uptime(59) == "59s"

    def test_format_uptime_minutes(self) -> None:
        """Sub-hour uptime shows minutes."""
        assert NodeInfoPanel._format_uptime(60) == "1m"
        assert NodeInfoPanel._format_uptime(720) == "12m"
        assert NodeInfoPanel._format_uptime(3599) == "59m"

    def test_format_uptime_hours(self) -> None:
        """Sub-day uptime shows hours and minutes."""
        assert NodeInfoPanel._format_uptime(3600) == "1h"
        assert NodeInfoPanel._format_uptime(8100) == "2h 15m"
        assert NodeInfoPanel._format_uptime(86399) == "23h 59m"

    def test_format_uptime_days(self) -> None:
        """Multi-day uptime shows days and hours."""
        assert NodeInfoPanel._format_uptime(86400) == "1d"
        assert NodeInfoPanel._format_uptime(100800) == "1d 4h"
        assert NodeInfoPanel._format_uptime(259200) == "3d"

    def test_format_uptime_fractional_seconds(self) -> None:
        """Fractional seconds are truncated to int."""
        assert NodeInfoPanel._format_uptime(45.7) == "45s"
        assert NodeInfoPanel._format_uptime(3661.9) == "1h 1m"


class TestDaemonSection:
    """Test DAEMON section rendering in IPC mode."""

    def test_render_legacy_mode_no_daemon_section(self) -> None:
        """daemon_connected=None means legacy mode - no DAEMON section."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            # daemon_connected defaults to None (legacy mode)
            rendered = panel.render()
            assert "DAEMON" not in rendered

    def test_render_ipc_connected(self) -> None:
        """daemon_connected=True renders DAEMON section with version and uptime."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.daemon_connected = True
            panel.daemon_version = "0.9.1"
            panel.daemon_uptime = 8100.0  # 2h 15m
            rendered = panel.render()

            assert "DAEMON" in rendered
            assert "connected" in rendered
            assert "0.9.1" in rendered
            assert "2h 15m" in rendered

    def test_render_ipc_disconnected(self) -> None:
        """daemon_connected=False renders DAEMON section with disconnected."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.daemon_connected = False
            rendered = panel.render()

            assert "DAEMON" in rendered
            assert "disconnected" in rendered
            # Should NOT show version or uptime when disconnected
            assert "VER:" not in rendered
            assert "UP:" not in rendered


class TestRNSLabels:
    """Test nuanced RNS status labels."""

    def test_rns_online_with_interfaces(self) -> None:
        """rns_online=True with interfaces shows 'online (N if)'."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.rns_online = True
            panel.interface_count = 3
            rendered = panel.render()

            assert "online" in rendered
            assert "3 if" in rendered

    def test_rns_online_no_interfaces_shows_no_peers(self) -> None:
        """rns_online=True with 0 interfaces shows 'no peers'."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.rns_online = True
            panel.interface_count = 0
            rendered = panel.render()

            assert "no peers" in rendered
            # Should NOT say "offline"
            assert "offline" not in rendered.split("RETICULUM")[1].split("STYRENE")[0]

    def test_rns_offline_shows_offline(self) -> None:
        """rns_online=False without error shows 'offline'."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.rns_online = False
            panel.error_state = None
            rendered = panel.render()

            # Find the RNS line in RETICULUM section
            reticulum_section = rendered.split("RETICULUM")[1].split("STYRENE")[0]
            assert "offline" in reticulum_section

    def test_rns_error_shows_error_title(self) -> None:
        """rns_online=False with error state shows error title."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.rns_online = False
            panel.error_state = RNSErrorState(
                category=RNSErrorCategory.PORT_CONFLICT,
                message="Port 4242 in use",
            )
            rendered = panel.render()

            assert "Port Conflict" in rendered


class TestIPCManagedGating:
    """Test that ipc_managed flag gates local queries."""

    def test_ipc_managed_skips_local_reticulum(self) -> None:
        """ipc_managed=True causes _load_reticulum_data to return early."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_reticulum_status"
        ) as mock_status:
            panel = NodeInfoPanel()
            panel.ipc_managed = True
            panel._load_reticulum_data()

            # get_reticulum_status should NOT be called
            mock_status.assert_not_called()

    def test_ipc_managed_skips_local_discovery(self) -> None:
        """ipc_managed=True causes _load_styrene_data to skip discover_devices."""
        with (
            patch("styrened.tui.widgets.node_info_panel.load_config") as mock_config,
            patch(
                "styrened.tui.widgets.node_info_panel.discover_devices"
            ) as mock_discover,
            patch("styrened.tui.widgets.node_info_panel.get_hub_connection"),
        ):
            mock_cfg = MagicMock()
            mock_cfg.reticulum.mode.value = "standalone"
            mock_config.return_value = mock_cfg

            panel = NodeInfoPanel()
            panel.ipc_managed = True
            panel._load_styrene_data()

            # discover_devices should NOT be called
            mock_discover.assert_not_called()

    def test_ipc_managed_still_loads_mode(self) -> None:
        """ipc_managed=True still loads config mode (always relevant)."""
        with (
            patch("styrened.tui.widgets.node_info_panel.load_config") as mock_config,
            patch("styrened.tui.widgets.node_info_panel.discover_devices"),
            patch("styrened.tui.widgets.node_info_panel.get_hub_connection"),
        ):
            mock_cfg = MagicMock()
            mock_cfg.reticulum.mode.value = "peer"
            mock_config.return_value = mock_cfg

            panel = NodeInfoPanel()
            panel.ipc_managed = True
            panel._load_styrene_data()

            assert panel.mode == "peer"

    def test_non_ipc_managed_loads_reticulum(self) -> None:
        """ipc_managed=False (default) loads Reticulum data normally."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_reticulum_status",
            return_value={"running": False},
        ) as mock_status:
            panel = NodeInfoPanel()
            # ipc_managed defaults to False
            panel._load_reticulum_data()

            mock_status.assert_called_once()
