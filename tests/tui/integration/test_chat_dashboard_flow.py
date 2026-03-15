"""Integration-oriented TUI tests for current peer-workspace chat flow."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.app import StyreneApp
from styrened.tui.screens.dashboard import DashboardScreen
from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
from styrened.ui_state import WorkspaceId


@pytest.fixture(autouse=True)
def mock_reticulum_for_tests(tmp_path):
    fake_config = tmp_path / "reticulum_config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.app.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneLifecycle") as mock_app_lifecycle,
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
        patch("styrened.tui.screens.dashboard.start_discovery"),
    ):
        mock_app_lifecycle.return_value.initialize_async = AsyncMock(return_value=True)
        mock_app_lifecycle.return_value.ipc_bridge = None
        yield


@pytest.fixture
def sample_devices():
    now = int(datetime.now().timestamp())
    return [
        MeshDevice(
            destination_hash="a1b2c3d4e5f60708",
            identity_hash="a1b2c3d4e5f60708",
            name="node-01",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now,
            announce_count=5,
        ),
        MeshDevice(
            destination_hash="b1c2d3e4f5a60718",
            identity_hash="b1c2d3e4f5a60718",
            name="node-02",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 60,
            announce_count=3,
        ),
    ]


class TestDeviceDetailChatFlow:
    def test_dashboard_overflow_still_routes_to_nodes(self):
        from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable

        screen = DashboardScreen()
        screen.action_open_exploration = Mock()

        screen.on_home_node_summary_table_overflow_selected(HomeNodeSummaryTable.OverflowSelected())

        screen.action_open_exploration.assert_called_once_with()

    def test_select_device_opens_peer_workspace_from_nodes_context(self, sample_devices):
        from styrened.tui.screens.exploration import ExplorationScreen

        screen = ExplorationScreen()
        fake_app = MagicMock()
        with (
            patch.object(ExplorationScreen, "_get_selected_row_key", return_value=sample_devices[0].identity_hash),
            patch.object(ExplorationScreen, "_find_device_by_selection_key", return_value=sample_devices[0]),
            patch.object(ExplorationScreen, "app", new_callable=PropertyMock, return_value=fake_app),
        ):
            screen.action_select_device()

        pushed = fake_app.push_screen.call_args.args[0]
        assert isinstance(pushed, MeshDeviceDetailScreen)
        assert pushed.origin_workspace == WorkspaceId.NODES

    def test_chat_tab_can_be_requested_for_peer_workspace(self, sample_devices):
        screen = MeshDeviceDetailScreen(
            device_identity=sample_devices[0].identity_hash,
            device=sample_devices[0],
            initial_tab="chat",
            origin_workspace=WorkspaceId.NODES,
        )
        assert screen.initial_tab == "chat"
        assert screen.origin_workspace == WorkspaceId.NODES


class TestDashboardUnreadDisplay:
    @pytest.mark.asyncio
    async def test_dashboard_status_fetch_updates_total_unread_count_from_conversations(self, sample_devices):
        app = StyreneApp()
        app.device_cache.get = Mock(return_value=sample_devices)  # type: ignore[method-assign]

        screen = DashboardScreen()
        bar = MagicMock()
        table = MagicMock()
        cop = MagicMock()
        bridge = MagicMock()
        bridge.get_status = AsyncMock(return_value={"rns_initialized": True, "interfaces": [], "uptime": 10, "active_links": 0})
        bridge.get_hub_status = AsyncMock(return_value={"status": "connected"})
        bridge.get_core_config = AsyncMock(return_value={})
        bridge.get_conversations = AsyncMock(return_value=[
            {"identity_hash": sample_devices[0].identity_hash, "unread_count": 3},
            {"identity_hash": sample_devices[1].identity_hash, "unread_count": 1},
        ])

        def query_one_side_effect(widget_type):
            from styrened.tui.widgets.cop_activity_summary import CopActivitySummary
            from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable
            from styrened.tui.widgets.home_status_bar import HomeStatusBar

            if widget_type is HomeStatusBar:
                return bar
            if widget_type is HomeNodeSummaryTable:
                return table
            if widget_type is CopActivitySummary:
                return cop
            raise AssertionError(widget_type)

        with (
            patch.object(DashboardScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=bridge),
            patch.object(screen, "query_one", side_effect=query_one_side_effect),
        ):
            await screen._fetch_daemon_status()

        assert bar.unread_count == 4
        table.update_nodes.assert_called_once()
