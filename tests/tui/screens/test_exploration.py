"""TUI tests for ExplorationScreen — current Nodes workspace behavior."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest
from textual.containers import Vertical
from textual.widgets import Input, TabbedContent, TabPane

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.app import StyreneApp
from styrened.tui.screens.exploration import (
    ExplorationScreen,
    ReticumAnnounceTable,
    StyreneFleetTable,
)
from styrened.ui_state import WorkspaceId


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for all TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.app.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneLifecycle") as mock_app_lifecycle,
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        mock_app_lifecycle.return_value.initialize_async = AsyncMock(return_value=True)
        mock_app_lifecycle.return_value.ipc_bridge = None
        yield


def _make_device(
    name: str,
    device_type: DeviceType = DeviceType.GENERIC,
    dest_hash: str | None = None,
    identity_hash: str | None = None,
    last_announce: int | None = None,
    nomadnet_destination_hash: str | None = None,
) -> MeshDevice:
    now = int(datetime.now().timestamp())
    if dest_hash is None:
        dest_hash = name.encode().hex().ljust(32, "0")[:32]
    return MeshDevice(
        destination_hash=dest_hash,
        identity_hash=identity_hash or dest_hash,
        name=name,
        device_type=device_type,
        last_announce=last_announce or now,
        announce_count=1,
        nomadnet_destination_hash=nomadnet_destination_hash,
    )


@pytest.fixture
def sample_devices():
    now = int(datetime.now().timestamp())
    return [
        _make_device("Styrene-1", DeviceType.STYRENE_NODE, last_announce=now - 1),
        _make_device("Alice", DeviceType.LXMF_PEER, last_announce=now - 10),
        _make_device("MyRNode", DeviceType.RNODE, last_announce=now - 5),
        _make_device("PropNode1", DeviceType.PROPAGATION_NODE, last_announce=now - 30),
        _make_device("NomadPage", DeviceType.NOMADNET_NODE, last_announce=now - 15),
        _make_device("Bob", DeviceType.GENERIC, last_announce=now - 20),
        _make_device("unknown-dev", DeviceType.UNKNOWN, last_announce=now - 60),
    ]


@pytest.fixture
def app_with_cache(sample_devices):
    app = StyreneApp()
    app.device_cache.get = Mock(return_value=sample_devices)  # type: ignore[method-assign]
    app.device_cache.refresh = AsyncMock()  # type: ignore[method-assign]
    return app


class TestExplorationWorkspaceSemantics:
    def test_home_binding_exists_for_returning_home(self):
        screen = ExplorationScreen()
        bindings = [b for b in screen.BINDINGS if b.key == "n"]
        assert len(bindings) == 1
        assert bindings[0].action == "go_home"
        assert bindings[0].description == "Home"


class TestExplorationTabStructure:
    @pytest.mark.asyncio
    async def test_tabbed_nodes_workspace_contains_current_tabs(self, app_with_cache):
        async with app_with_cache.run_test() as pilot:
            await app_with_cache.push_screen(ExplorationScreen())
            await pilot.pause()

            tabs = app_with_cache.screen.query_one("#explore-tabs", TabbedContent)
            panes = {pane.id for pane in tabs.query(TabPane)}
            assert panes == {
                "tab-styrene",
                "tab-lxmf",
                "tab-infra",
                "tab-other",
                "tab-pages",
                "tab-diagnostics",
            }

    @pytest.mark.asyncio
    async def test_each_primary_tab_has_table(self, app_with_cache):
        async with app_with_cache.run_test() as pilot:
            await app_with_cache.push_screen(ExplorationScreen())
            await pilot.pause()

            assert isinstance(app_with_cache.screen.query_one("#table-styrene"), StyreneFleetTable)
            for tid in ["#table-lxmf", "#table-pages", "#table-infra", "#table-other"]:
                assert isinstance(app_with_cache.screen.query_one(tid), ReticumAnnounceTable)


class TestExplorationTimerLifecycle:
    def test_screen_suspend_pauses_refresh_timer_and_cancels_workers(self):
        screen = ExplorationScreen()
        screen._refresh_timer = Mock()
        screen._countdown_timer = Mock()
        node_worker = Mock()
        stored_worker = Mock()
        screen._node_refresh_worker = node_worker
        screen._stored_nodes_worker = stored_worker

        screen.on_screen_suspend(Mock())

        screen._refresh_timer.pause.assert_called_once_with()
        screen._countdown_timer.pause.assert_called_once_with()
        node_worker.cancel.assert_called_once_with()
        stored_worker.cancel.assert_called_once_with()

    def test_screen_resume_resumes_timers_refreshes_tables_and_refreshes_nodes(self):
        screen = ExplorationScreen()
        screen._refresh_timer = Mock()
        screen._countdown_timer = Mock()
        screen._refresh_announce_tables = Mock()
        screen._start_node_refresh = Mock()

        screen.on_screen_resume(Mock())

        screen._refresh_timer.resume.assert_called_once_with()
        screen._countdown_timer.resume.assert_called_once_with()
        screen._refresh_announce_tables.assert_called_once_with()
        screen._start_node_refresh.assert_called_once_with()


class TestExplorationRouting:
    def test_enter_from_nodes_workspace_sets_nodes_origin(self, sample_devices):
        screen = ExplorationScreen()
        screen._get_selected_row_key = Mock(return_value=sample_devices[0].identity_hash)
        screen._find_device_by_selection_key = Mock(return_value=sample_devices[0])
        fake_app = Mock()

        with patch.object(ExplorationScreen, "app", new_callable=PropertyMock, return_value=fake_app):
            screen.action_select_device()

        pushed_screen = fake_app.push_screen.call_args.args[0]
        assert pushed_screen.origin_workspace == WorkspaceId.NODES

    def test_enter_routes_detail_by_identity_when_row_key_is_destination_hash(self, sample_devices):
        screen = ExplorationScreen()
        screen._get_selected_row_key = Mock(return_value=sample_devices[0].destination_hash)
        screen._find_device_by_selection_key = Mock(return_value=sample_devices[0])
        fake_app = Mock()

        with patch.object(ExplorationScreen, "app", new_callable=PropertyMock, return_value=fake_app):
            screen.action_select_device()

        pushed_screen = fake_app.push_screen.call_args.args[0]
        assert pushed_screen.device_identity == sample_devices[0].identity_hash
        assert pushed_screen.device == sample_devices[0]


class TestDevicesInCorrectTab:
    @pytest.mark.asyncio
    async def test_devices_are_distributed_to_current_tabs(self, app_with_cache):
        async with app_with_cache.run_test() as pilot:
            await app_with_cache.push_screen(ExplorationScreen())
            await pilot.pause()

            assert app_with_cache.screen.query_one("#table-styrene", StyreneFleetTable).device_count == 1
            assert app_with_cache.screen.query_one("#table-lxmf", ReticumAnnounceTable).device_count == 1
            assert app_with_cache.screen.query_one("#table-pages", ReticumAnnounceTable).device_count == 1
            assert app_with_cache.screen.query_one("#table-infra", ReticumAnnounceTable).device_count == 2
            assert app_with_cache.screen.query_one("#table-other", ReticumAnnounceTable).device_count == 2


class TestTabCountLabels:
    @pytest.mark.asyncio
    async def test_tab_labels_show_counts(self, app_with_cache):
        async with app_with_cache.run_test() as pilot:
            await app_with_cache.push_screen(ExplorationScreen())
            await pilot.pause()

            tabs = app_with_cache.screen.query_one("#explore-tabs", TabbedContent)
            assert "(1)" in str(tabs.get_tab("tab-styrene").label)
            assert "(2)" in str(tabs.get_tab("tab-infra").label)


class TestExplorationSearch:
    @pytest.mark.asyncio
    async def test_search_hidden_on_mount(self, app_with_cache):
        async with app_with_cache.run_test() as pilot:
            await app_with_cache.push_screen(ExplorationScreen())
            await pilot.pause()

            search = app_with_cache.screen.query_one("#explore-search-bar", Input)
            assert search.has_class("hidden")

    @pytest.mark.asyncio
    async def test_search_filters_active_tab(self, app_with_cache):
        async with app_with_cache.run_test() as pilot:
            await app_with_cache.push_screen(ExplorationScreen())
            await pilot.pause()

            tabs = app_with_cache.screen.query_one("#explore-tabs", TabbedContent)
            tabs.active = "tab-infra"
            await pilot.pause()

            table = app_with_cache.screen.query_one("#table-infra", ReticumAnnounceTable)
            assert table.device_count == 2

            await pilot.press("slash")
            await pilot.pause()
            await pilot.press("r", "n", "o", "d", "e")
            await pilot.pause()

            assert table.row_count == 1


class TestExplorationLxmfShadowFiltering:
    @pytest.mark.asyncio
    async def test_lxmf_shadow_filtered_out(self):
        now = int(datetime.now().timestamp())
        shared_identity = "aabb" * 8
        devices = [
            _make_device("Testbed Node", DeviceType.STYRENE_NODE, dest_hash="1111" * 8, identity_hash=shared_identity, last_announce=now - 5),
            _make_device("Testbed Node", DeviceType.LXMF_PEER, dest_hash="2222" * 8, identity_hash=shared_identity, last_announce=now - 5),
            _make_device("Alice", DeviceType.LXMF_PEER, dest_hash="3333" * 8, identity_hash="ccdd" * 8, last_announce=now - 10),
        ]
        app = StyreneApp()
        app.device_cache.get = Mock(return_value=devices)  # type: ignore[method-assign]
        app.device_cache.refresh = AsyncMock()  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            await app.push_screen(ExplorationScreen())
            await pilot.pause()

            table = app.screen.query_one("#table-lxmf", ReticumAnnounceTable)
            assert table.device_count == 1


class TestDuplicateIdentityRows:
    @pytest.mark.asyncio
    async def test_other_tab_allows_multiple_rows_with_same_identity(self):
        now = int(datetime.now().timestamp())
        shared_identity = "feed" * 8
        devices = [
            _make_device("Node A", DeviceType.UNKNOWN, dest_hash="1111" * 8, identity_hash=shared_identity, last_announce=now - 5),
            _make_device("Node B", DeviceType.UNKNOWN, dest_hash="2222" * 8, identity_hash=shared_identity, last_announce=now - 10),
        ]
        app = StyreneApp()
        app.device_cache.get = Mock(return_value=devices)  # type: ignore[method-assign]
        app.device_cache.refresh = AsyncMock()  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            await app.push_screen(ExplorationScreen())
            await pilot.pause()

            table = app.screen.query_one("#table-other", ReticumAnnounceTable)
            assert table.device_count == 2
            assert table.row_count == 2

    @pytest.mark.asyncio
    async def test_pages_tab_allows_nomadnet_and_styrene_rows_sharing_identity(self):
        now = int(datetime.now().timestamp())
        shared_identity = "cafe" * 8
        devices = [
            _make_device(
                "Community Hub",
                DeviceType.STYRENE_NODE,
                dest_hash="3333" * 8,
                identity_hash=shared_identity,
                last_announce=now - 5,
                nomadnet_destination_hash="4444" * 8,
            ),
            _make_device(
                "Community Hub Pages",
                DeviceType.NOMADNET_NODE,
                dest_hash="5555" * 8,
                identity_hash=shared_identity,
                last_announce=now - 10,
            ),
        ]
        app = StyreneApp()
        app.device_cache.get = Mock(return_value=devices)  # type: ignore[method-assign]
        app.device_cache.refresh = AsyncMock()  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            await app.push_screen(ExplorationScreen())
            await pilot.pause()

            table = app.screen.query_one("#table-pages", ReticumAnnounceTable)
            assert table.device_count == 2
            assert table.row_count == 2


class TestPagesTabPreview:
    @pytest.mark.asyncio
    async def test_placeholder_visible_initially(self, app_with_cache):
        async with app_with_cache.run_test() as pilot:
            await app_with_cache.push_screen(ExplorationScreen())
            await pilot.pause()

            tabs = app_with_cache.screen.query_one("#explore-tabs", TabbedContent)
            tabs.active = "tab-pages"
            await pilot.pause()

            placeholder = app_with_cache.screen.query_one("#pages-browser-placeholder", Vertical)
            assert not placeholder.has_class("hidden")


class TestEmptyTabPlaceholder:
    @pytest.mark.asyncio
    async def test_empty_tab_shows_placeholder_row(self):
        app = StyreneApp()
        app.device_cache.get = Mock(return_value=[_make_device("Alice", DeviceType.LXMF_PEER)])  # type: ignore[method-assign]
        app.device_cache.refresh = AsyncMock()  # type: ignore[method-assign]

        async with app.run_test() as pilot:
            await app.push_screen(ExplorationScreen())
            await pilot.pause()

            table = app.screen.query_one("#table-pages", ReticumAnnounceTable)
            assert table.device_count == 0
            assert table.row_count == 1
