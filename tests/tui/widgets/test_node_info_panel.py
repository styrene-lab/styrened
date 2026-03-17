"""Tests for NodeInfoPanel widget.

Tests IPC-aware daemon section, uptime formatting, nuanced RNS labels,
and gating of local queries behind ipc_managed flag.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, Mock, PropertyMock, patch

from rich.console import Console

from styrened.models.rns_error import RNSErrorCategory, RNSErrorState
from styrened.tui.widgets.node_info_panel import NodeInfoPanel
from styrened.ui_state.daemon import HomeNodeInfoState, HomeNodeLocalState


def _render_panel(panel: NodeInfoPanel) -> str:
    """Render a NodeInfoPanel to plain text for assertion.

    panel.render() returns a Rich Table (RenderableType). We capture it
    through a Rich Console so string assertions work regardless of the
    underlying renderable type.
    """
    renderable = panel.render()
    if isinstance(renderable, str):
        return renderable
    buf = io.StringIO()
    console = Console(file=buf, highlight=False, markup=False, width=140)
    console.print(renderable)
    return buf.getvalue()


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


class TestNodeInfoPanelLifecycle:
    """Test bridge worker lifecycle ownership."""

    def test_on_unmount_cancels_inflight_workers(self) -> None:
        panel = NodeInfoPanel()
        identity_worker = Mock()
        mesh_worker = Mock()
        panel._identity_worker = identity_worker
        panel._mesh_count_worker = mesh_worker

        panel.on_unmount()

        identity_worker.cancel.assert_called_once_with()
        mesh_worker.cancel.assert_called_once_with()
        assert panel._identity_worker is None
        assert panel._mesh_count_worker is None

    def test_refresh_identity_via_bridge_uses_identity_worker_helper(self) -> None:
        panel = NodeInfoPanel()
        panel._start_identity_load = Mock()
        panel.identity_hash = ""

        with patch.object(NodeInfoPanel, "_bridge", new_callable=PropertyMock, return_value=Mock()):
            panel._refresh_identity_via_bridge()

        panel._start_identity_load.assert_called_once_with()

    def test_refresh_mesh_count_via_bridge_uses_mesh_count_worker_helper(self) -> None:
        panel = NodeInfoPanel()
        panel._start_mesh_count_load = Mock()
        panel.identity_hash = "already-loaded"
        panel.ipc_managed = False

        with patch.object(NodeInfoPanel, "_bridge", new_callable=PropertyMock, return_value=Mock()):
            panel._refresh_mesh_count_via_bridge()

        panel._start_mesh_count_load.assert_called_once_with()


class TestNodeInfoPanelIntegrationSeams:
    """Test local/bridge separation and future integration hooks."""

    def test_load_all_data_uses_local_fallback_mode_when_not_ipc_managed(self) -> None:
        panel = NodeInfoPanel()
        panel._refresh_local_fallback_mode = Mock()

        panel._load_all_data()

        panel._refresh_local_fallback_mode.assert_called_once_with()

    def test_load_all_data_uses_presentation_mode_when_ipc_managed(self) -> None:
        panel = NodeInfoPanel()
        panel.ipc_managed = True
        panel._refresh_ipc_managed_presentation = Mock()

        panel._load_all_data()

        panel._refresh_ipc_managed_presentation.assert_called_once_with()

    def test_refresh_bridge_backed_fallback_state_only_requests_identity_when_missing(self) -> None:
        panel = NodeInfoPanel()
        panel.identity_hash = ""
        panel._start_identity_load = Mock()
        panel._start_mesh_count_load = Mock()

        with patch.object(NodeInfoPanel, "_bridge", new_callable=PropertyMock, return_value=Mock()):
            panel._refresh_bridge_backed_fallback_state()

        panel._start_identity_load.assert_called_once_with()
        panel._start_mesh_count_load.assert_called_once_with()

    def test_apply_identity_snapshot_sets_security_tier(self) -> None:
        panel = NodeInfoPanel()
        config = MagicMock()
        config.identity.provider = "yubikey"

        with patch("styrened.tui.widgets.node_info_panel.load_config", return_value=config):
            panel._apply_identity_snapshot("abc123")

        assert panel.identity_hash == "abc123"
        assert panel.security_tier == "YubiKey/FIDO2"

    def test_apply_identity_snapshot_defaults_when_config_load_fails(self) -> None:
        panel = NodeInfoPanel()

        with patch(
            "styrened.tui.widgets.node_info_panel.load_config",
            side_effect=RuntimeError("boom"),
        ):
            panel._apply_identity_snapshot("abc123")

        assert panel.identity_hash == "abc123"
        assert panel.security_tier == "X25519"

    def test_apply_mesh_catalog_count_normalizes_via_node_catalog(self) -> None:
        panel = NodeInfoPanel()
        fake_catalog = MagicMock()
        fake_catalog.nodes = [object(), object(), object()]

        with patch(
            "styrened.ui_state.nodes.build_node_catalog",
            return_value=fake_catalog,
        ):
            count = panel._apply_mesh_catalog_count((MagicMock(),))

        assert count == 3
        assert panel.styrene_mesh_count == 3

    def test_apply_home_local_snapshot_updates_panel_from_coherent_state(self) -> None:
        panel = NodeInfoPanel()
        local_snapshot = HomeNodeLocalState(
            hardware_error="unsupported platform",
            mode="peer",
            identity_display_name="Alice",
            identity_icon="🖥️",
            identity_short_name="alice",
            security_tier="YubiKey/FIDO2",
        )

        panel.apply_home_local_snapshot(local_snapshot)

        assert panel.hardware_error == "unsupported platform"
        assert panel.mode == "peer"
        assert panel.identity_display_name == "Alice"
        assert panel.identity_icon == "🖥️"
        assert panel.identity_short_name == "alice"
        assert panel.security_tier == "YubiKey/FIDO2"

    def test_load_local_fallback_state_applies_builder_snapshot(self) -> None:
        panel = NodeInfoPanel()
        panel._fallback_state_builder = Mock()
        panel._fallback_state_builder.build_local_snapshot.return_value = HomeNodeLocalState(mode="peer")
        panel._load_reticulum_data = Mock()

        panel._load_local_fallback_state()

        panel._fallback_state_builder.build_local_snapshot.assert_called_once_with()
        panel._load_reticulum_data.assert_called_once_with()
        assert panel.mode == "peer"

    def test_apply_home_snapshot_updates_panel_from_coherent_state(self) -> None:
        panel = NodeInfoPanel()
        snapshot = HomeNodeInfoState(
            daemon_connected=True,
            daemon_version="1.2.3",
            daemon_uptime=90.0,
            local_identity_hash="abc123",
            styrene_mesh_count=4,
            rns_online=True,
            interface_count=2,
            propagation_enabled=True,
            transport_enabled=False,
            active_links=3,
            unread_count=2,
            conversation_count=5,
            contact_count=7,
            messages_received=11,
            auto_reply_enabled=True,
        )
        panel._apply_identity_snapshot = Mock()

        panel.apply_home_snapshot(snapshot)

        assert panel.daemon_connected is True
        assert panel.daemon_version == "1.2.3"
        assert panel.daemon_uptime == 90.0
        assert panel.styrene_mesh_count == 4
        assert panel.rns_online is True
        assert panel.interface_count == 2
        assert panel.propagation_enabled is True
        assert panel.transport_enabled is False
        assert panel.active_links == 3
        assert panel.unread_count == 2
        assert panel.conversation_count == 5
        assert panel.contact_count == 7
        assert panel.messages_received == 11
        assert panel.auto_reply_enabled is True
        panel._apply_identity_snapshot.assert_called_once_with("abc123", security_tier="")


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
            rendered = _render_panel(panel)
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
            rendered = _render_panel(panel)

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
            rendered = _render_panel(panel)

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
            rendered = _render_panel(panel)

            assert "online" in rendered
            assert "3 if" in rendered

    def test_rns_online_no_interfaces_shows_no_peers(self) -> None:
        """rns_online=True with 0 interfaces shows 'no interfaces'."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.rns_online = True
            panel.interface_count = 0
            rendered = _render_panel(panel)

            assert "no interfaces" in rendered
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
            rendered = _render_panel(panel)

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
            rendered = _render_panel(panel)

            assert "Port Conflict" in rendered


class TestIdentitySection:
    """Test IDENTITY section rendering in NodeInfoPanel."""

    def test_render_identity_section_with_name_and_icon(self) -> None:
        """Identity section renders display name, icon, alias, and hash."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.identity_display_name = "Alice"
            panel.identity_icon = "🖥️"
            panel.identity_short_name = "alice"
            panel.identity_hash = "abc123def456abc123def456abc12345"
            rendered = _render_panel(panel)

            assert "IDENTITY" in rendered
            assert "Alice" in rendered
            assert "🖥️" in rendered
            assert "alice" in rendered
            assert "abc123def456abc1" in rendered  # First 16 chars

    def test_render_identity_section_without_short_name(self) -> None:
        """Identity section shows 'not set' when short_name is None."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.identity_display_name = "Bob"
            panel.identity_icon = "📱"
            panel.identity_short_name = None
            rendered = _render_panel(panel)

            assert "IDENTITY" in rendered
            assert "not set" in rendered

    def test_render_no_identity_when_empty(self) -> None:
        """No IDENTITY section when display_name and icon are empty."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.identity_display_name = ""
            panel.identity_icon = ""
            rendered = _render_panel(panel)

            assert "IDENTITY" not in rendered


class TestSecurityTierDisplay:
    """Test SEC display in IDENTITY section."""

    def test_security_tier_pqc_displayed(self) -> None:
        """Non-empty security_tier containing 'PQC' renders in IDENTITY section."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.identity_display_name = "Alice"
            panel.identity_icon = ""
            panel.security_tier = "PQC_HYBRID"
            rendered = _render_panel(panel)

            assert "SEC:" in rendered
            assert "PQC_HYBRID" in rendered

    def test_security_tier_rns_displayed(self) -> None:
        """security_tier without 'PQC' renders with medium color."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.identity_display_name = "Bob"
            panel.identity_icon = ""
            panel.security_tier = "RNS_ONLY"
            rendered = _render_panel(panel)

            assert "SEC:" in rendered
            assert "RNS_ONLY" in rendered

    def test_security_tier_empty_hidden(self) -> None:
        """Empty security_tier renders no SEC line."""
        with patch(
            "styrened.tui.widgets.node_info_panel.get_system_info",
            side_effect=Exception("skip"),
        ):
            panel = NodeInfoPanel()
            panel.hardware_error = "skip"
            panel.identity_display_name = "Carol"
            panel.identity_icon = ""
            panel.security_tier = ""
            rendered = _render_panel(panel)

            assert "SEC:" not in rendered


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

    def test_ipc_managed_presentation_refresh_is_a_noop(self) -> None:
        """ipc_managed=True leaves all refresh ownership with the parent screen."""
        panel = NodeInfoPanel()
        panel.ipc_managed = True
        panel._load_hardware_data = Mock()
        panel._load_styrene_local_data = Mock()
        panel._load_reticulum_data = Mock()
        panel._start_identity_load = Mock()
        panel._start_mesh_count_load = Mock()

        panel._refresh_ipc_managed_presentation()

        panel._load_hardware_data.assert_not_called()
        panel._load_styrene_local_data.assert_not_called()
        panel._load_reticulum_data.assert_not_called()
        panel._start_identity_load.assert_not_called()
        panel._start_mesh_count_load.assert_not_called()

    def test_ipc_managed_still_loads_mode(self) -> None:
        """ipc_managed=True still loads local config-derived mode."""
        with patch("styrened.tui.widgets.node_info_panel.load_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.reticulum.mode.value = "peer"
            mock_cfg.identity.display_name = "Alice"
            mock_cfg.identity.icon = "🖥️"
            mock_cfg.identity.short_name = "alice"
            mock_cfg.identity.provider = "yubikey"
            mock_config.return_value = mock_cfg

            panel = NodeInfoPanel()
            panel.ipc_managed = True
            panel._load_styrene_local_data()

            assert panel.mode == "peer"
            assert panel.identity_display_name == "Alice"
            assert panel.security_tier == "YubiKey/FIDO2"

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
