"""Navigation and workflow tests aligned to splash-first startup and current workspace ownership."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.app import StyreneApp
from styrened.tui.screens.exploration import ExplorationScreen
from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
from styrened.tui.screens.splash import SplashScreen
from styrened.ui_state import WorkspaceId


@pytest.fixture
def sample_device() -> MeshDevice:
    return MeshDevice(
        destination_hash="test_device",
        identity_hash="test_device",
        name="Test Device",
        device_type=DeviceType.STYRENE_NODE,
        last_announce=int(datetime.now().timestamp()),
        announce_count=1,
    )


@pytest.fixture
def app_with_cache(sample_device: MeshDevice) -> StyreneApp:
    app = StyreneApp()
    app.device_cache.get = Mock(return_value=[sample_device])  # type: ignore[method-assign]
    app.device_cache.refresh = AsyncMock()  # type: ignore[method-assign]
    return app


class TestAppInitialization:
    @pytest.mark.asyncio
    async def test_app_starts_with_splash(self):
        app = StyreneApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, SplashScreen)

    @pytest.mark.asyncio
    async def test_app_loads_without_crash(self):
        app = StyreneApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.is_running


class TestScreenNavigation:
    @pytest.mark.asyncio
    async def test_global_nodes_action_opens_exploration_workspace(self):
        app = StyreneApp()
        async with app.run_test() as pilot:
            app.action_open_nodes()
            await pilot.pause()
            assert isinstance(app.screen, ExplorationScreen)

    @pytest.mark.asyncio
    async def test_exploration_to_device_detail_sets_nodes_origin(self, app_with_cache: StyreneApp, sample_device: MeshDevice):
        async with app_with_cache.run_test() as pilot:
            await app_with_cache.push_screen(ExplorationScreen())
            await pilot.pause()

            screen = app_with_cache.screen
            with patch.object(screen, "_get_selected_row_key", return_value=sample_device.identity_hash):
                screen.action_select_device()
            await pilot.pause()

            assert isinstance(app_with_cache.screen, MeshDeviceDetailScreen)
            assert app_with_cache.screen.origin_workspace == WorkspaceId.NODES

    def test_home_overflow_routes_to_nodes_workspace(self):
        from styrened.tui.screens.dashboard import DashboardScreen
        from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable

        screen = DashboardScreen()
        screen.action_open_exploration = Mock()
        screen.on_home_node_summary_table_overflow_selected(HomeNodeSummaryTable.OverflowSelected())
        screen.action_open_exploration.assert_called_once_with()


class TestKeyboardWorkflows:
    def test_mesh_device_detail_back_pops_screen(self, sample_device: MeshDevice):
        screen = MeshDeviceDetailScreen(
            device_identity=sample_device.identity_hash,
            device=sample_device,
            origin_workspace=WorkspaceId.NODES,
        )
        fake_app = Mock()

        with patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=fake_app):
            screen.action_go_back()

        fake_app.pop_screen.assert_called_once_with()

    def test_mesh_device_detail_chat_focus_preserves_origin(self, sample_device: MeshDevice):
        screen = MeshDeviceDetailScreen(
            device_identity=sample_device.identity_hash,
            device=sample_device,
            initial_tab="chat",
            origin_workspace=WorkspaceId.NODES,
        )
        assert screen.origin_workspace == WorkspaceId.NODES
        assert screen.initial_tab == "chat"
