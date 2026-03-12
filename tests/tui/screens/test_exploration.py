"""TUI tests for ExplorationScreen — categorized tabs, search, sort, and type display.

Tests the tabbed exploration interface with LXMF, Pages, Infrastructure, and Other tabs.
"""
from __future__ import annotations


from datetime import datetime
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest
from textual.widgets import Input, Static, TabbedContent

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.app import StyreneApp
from styrened.tui.screens.exploration import ExplorationScreen, ReticumAnnounceTable
from styrened.ui_state import WorkspaceId


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for all TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch(
            "styrened.tui.services.reticulum.find_reticulum_config",
            return_value=fake_config,
        ),
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
) -> MeshDevice:
    """Create a test MeshDevice."""
    now = int(datetime.now().timestamp())
    if dest_hash is None:
        # Generate unique hash from name
        dest_hash = name.encode().hex().ljust(32, "0")[:32]
    return MeshDevice(
        destination_hash=dest_hash,
        identity_hash=identity_hash or dest_hash,
        name=name,
        device_type=device_type,
        last_announce=last_announce or now,
        announce_count=1,
    )


@pytest.fixture
def sample_devices():
    """Create a set of sample devices for testing."""
    now = int(datetime.now().timestamp())
    return [
        _make_device("Alice", DeviceType.LXMF_PEER, last_announce=now - 10),
        _make_device("Bob", DeviceType.GENERIC, last_announce=now - 20),
        _make_device("MyRNode", DeviceType.RNODE, last_announce=now - 5),
        _make_device("PropNode1", DeviceType.PROPAGATION_NODE, last_announce=now - 30),
        _make_device("NomadPage", DeviceType.NOMADNET_NODE, last_announce=now - 15),
        _make_device("unknown-dev", DeviceType.UNKNOWN, last_announce=now - 60),
    ]


def _patch_discovery(devices):
    """Return context managers that mock discovery and node_store."""
    return (
        patch(
            "styrened.tui.screens.exploration.discover_devices",
            return_value=devices,
        ),
        patch(
            "styrened.tui.screens.exploration.start_discovery",
        ),
        patch(
            "styrened.services.node_store.get_node_store",
            return_value=type("FakeStore", (), {"get_all_nodes": lambda self: []})(),
        ),
    )


class TestExplorationWorkspaceSemantics:
    """Exploration now serves as the canonical Nodes workspace."""

    def test_nodes_binding_exists_for_returning_home(self):
        screen = ExplorationScreen()
        n_bindings = [b for b in screen.BINDINGS if b.key == "n"]
        assert len(n_bindings) == 1
        assert n_bindings[0].action == "app.pop_screen"
        assert n_bindings[0].description == "Home"


class TestExplorationTabStructure:
    """The screen has 4 categorized tabs."""

    @pytest.mark.asyncio
    async def test_four_tabs_present(self, sample_devices):
        """TabbedContent should have 5 tab panes including Styrene."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                tabs = app.screen.query_one("#explore-tabs", TabbedContent)
                panes = list(tabs.query("TabPane"))
                assert len(panes) == 5

    @pytest.mark.asyncio
    async def test_each_tab_has_table(self, sample_devices):
        """Each tab pane should contain a ReticumAnnounceTable."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                for tid in ["#table-lxmf", "#table-pages", "#table-infra", "#table-other"]:
                    table = app.screen.query_one(tid, ReticumAnnounceTable)
                    assert table is not None


class TestExplorationTimerLifecycle:
    """Nodes workspace should manage its periodic refresh timer across lifecycle events."""

    def test_screen_suspend_pauses_refresh_timer_and_cancels_workers(self):
        screen = ExplorationScreen()
        screen._refresh_timer = Mock()
        node_worker = Mock()
        stored_worker = Mock()
        screen._node_refresh_worker = node_worker
        screen._stored_nodes_worker = stored_worker

        screen.on_screen_suspend(Mock())

        screen._refresh_timer.pause.assert_called_once_with()
        node_worker.cancel.assert_called_once_with()
        stored_worker.cancel.assert_called_once_with()
        assert screen._node_refresh_worker is None
        assert screen._stored_nodes_worker is None

    def test_screen_resume_resumes_refresh_timer_and_refreshes_nodes(self):
        screen = ExplorationScreen()
        screen._refresh_timer = Mock()
        screen._start_node_refresh = Mock()

        screen.on_screen_resume(Mock())

        screen._refresh_timer.resume.assert_called_once_with()
        screen._start_node_refresh.assert_called_once_with()

    def test_on_unmount_stops_refresh_timer_and_cancels_workers(self):
        screen = ExplorationScreen()
        timer = Mock()
        node_worker = Mock()
        stored_worker = Mock()
        screen._refresh_timer = timer
        screen._node_refresh_worker = node_worker
        screen._stored_nodes_worker = stored_worker

        screen.on_unmount()

        timer.stop.assert_called_once_with()
        node_worker.cancel.assert_called_once_with()
        stored_worker.cancel.assert_called_once_with()
        assert screen._refresh_timer is None
        assert screen._node_refresh_worker is None
        assert screen._stored_nodes_worker is None


class TestExplorationWorkerOwnership:
    """Nodes workspace should route refresh starts through explicit worker helpers."""

    def test_refresh_via_bridge_uses_refresh_helper(self):
        screen = ExplorationScreen()
        screen._start_node_refresh = Mock()

        screen._refresh_via_bridge()

        screen._start_node_refresh.assert_called_once_with()


class TestExplorationRouting:
    """Nodes workspace should preserve explicit NODES origin when drilling down."""

    def test_enter_from_nodes_workspace_sets_nodes_origin(self, sample_devices):
        screen = ExplorationScreen()
        fake_app = Mock()

        with (
            patch.object(
                ExplorationScreen,
                "_get_selected_identity",
                return_value=sample_devices[0].identity_hash,
            ),
            patch.object(
                ExplorationScreen,
                "_find_device_by_identity",
                return_value=sample_devices[0],
            ),
            patch.object(
                ExplorationScreen,
                "app",
                new_callable=PropertyMock,
                return_value=fake_app,
            ),
        ):
            screen.action_select_device()

        from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

        fake_app.push_screen.assert_called_once()
        pushed_screen = fake_app.push_screen.call_args.args[0]
        assert isinstance(pushed_screen, MeshDeviceDetailScreen)
        assert pushed_screen.origin_workspace == WorkspaceId.NODES


class TestDevicesInCorrectTab:
    """Devices appear in the correct tab based on their type."""

    @pytest.mark.asyncio
    async def test_lxmf_peer_in_lxmf_tab(self, sample_devices):
        """LXMF_PEER should appear in LXMF tab."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one("#table-lxmf", ReticumAnnounceTable)
                assert table.device_count == 1  # Only Alice

    @pytest.mark.asyncio
    async def test_nomadnet_in_pages_tab(self, sample_devices):
        """NOMADNET_NODE should appear in Pages tab."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one("#table-pages", ReticumAnnounceTable)
                assert table.device_count == 1  # Only NomadPage

    @pytest.mark.asyncio
    async def test_infra_devices_in_infra_tab(self, sample_devices):
        """PROPAGATION_NODE and RNODE should appear in Infra tab."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one("#table-infra", ReticumAnnounceTable)
                assert table.device_count == 2  # MyRNode + PropNode1

    @pytest.mark.asyncio
    async def test_other_devices_in_other_tab(self, sample_devices):
        """GENERIC and UNKNOWN should appear in Other tab."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one("#table-other", ReticumAnnounceTable)
                assert table.device_count == 2  # Bob (generic) + unknown-dev


class TestTabCountLabels:
    """Tab labels show device counts."""

    @pytest.mark.asyncio
    async def test_tab_labels_show_counts(self, sample_devices):
        """Populated tabs should show count in label."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                tabs = app.screen.query_one("#explore-tabs", TabbedContent)
                lxmf_tab = tabs.get_tab("tab-lxmf")
                assert "(1)" in str(lxmf_tab.label)

                infra_tab = tabs.get_tab("tab-infra")
                assert "(2)" in str(infra_tab.label)

    @pytest.mark.asyncio
    async def test_empty_tab_no_count(self):
        """Tab with zero devices should not show a count."""
        # Only LXMF devices — other tabs should be empty
        devices = [
            _make_device("Alice", DeviceType.LXMF_PEER),
        ]
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                tabs = app.screen.query_one("#explore-tabs", TabbedContent)
                other_tab = tabs.get_tab("tab-other")
                label_text = str(other_tab.label)
                assert "(" not in label_text


class TestExplorationSearchHidden:
    """Search input is hidden by default."""

    @pytest.mark.asyncio
    async def test_search_hidden_on_mount(self, sample_devices):
        """Search input should have the 'hidden' class initially."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                search = app.screen.query_one("#explore-search-bar", Input)
                assert search.has_class("hidden")


class TestExplorationSearchActivation:
    """Pressing / shows and focuses the search input."""

    @pytest.mark.asyncio
    async def test_slash_shows_search(self, sample_devices):
        """Pressing / should reveal and focus the search input."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                await pilot.press("slash")
                await pilot.pause()

                search = app.screen.query_one("#explore-search-bar", Input)
                assert not search.has_class("hidden")


class TestExplorationSearchFilters:
    """Search input filters the active tab's table rows."""

    @pytest.mark.asyncio
    async def test_search_filters_active_tab(self, sample_devices):
        """Typing in search should filter the active tab's table."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                # Switch to Infra tab which has 2 devices (better for filter test)
                tabs = app.screen.query_one("#explore-tabs", TabbedContent)
                tabs.active = "tab-infra"
                await pilot.pause()

                table = app.screen.query_one("#table-infra", ReticumAnnounceTable)
                assert table.device_count == 2
                initial_row_count = table.row_count

                # Activate search and type partial match
                await pilot.press("slash")
                await pilot.pause()
                await pilot.press("r", "n", "o", "d", "e")
                await pilot.pause()

                # Should filter to only MyRNode (1 row vs 2)
                assert table.row_count < initial_row_count
                assert table.row_count == 1


class TestExplorationSearchDismiss:
    """Escape clears filter and hides search."""

    @pytest.mark.asyncio
    async def test_escape_clears_and_hides_search(self, sample_devices):
        """Pressing escape should clear filter and hide search input."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                # Open search and type
                await pilot.press("slash")
                await pilot.pause()
                await pilot.press("z", "z", "z")
                await pilot.pause()

                table = app.screen.query_one("#table-lxmf", ReticumAnnounceTable)
                filtered_count = table.row_count

                # Press escape to dismiss
                await pilot.press("escape")
                await pilot.pause()

                search = app.screen.query_one("#explore-search-bar", Input)
                assert search.has_class("hidden")
                assert search.value == ""
                # All rows should be back
                assert table.row_count >= filtered_count


class TestExplorationTabSwitchClearsSearch:
    """Tab switch clears the search bar."""

    @pytest.mark.asyncio
    async def test_tab_switch_clears_search(self, sample_devices):
        """Switching tabs should clear any active search filter."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                # Open search and type
                await pilot.press("slash")
                await pilot.pause()
                await pilot.press("a", "l", "i")
                await pilot.pause()

                search = app.screen.query_one("#explore-search-bar", Input)
                assert search.value == "ali"

                # Switch to Infra tab
                tabs = app.screen.query_one("#explore-tabs", TabbedContent)
                tabs.active = "tab-infra"
                await pilot.pause()

                # Search input should be cleared
                assert search.value == ""


class TestExplorationSorting:
    """Column header clicks sort the table."""

    @pytest.mark.asyncio
    async def test_sort_by_name(self, sample_devices):
        """Clicking NAME header should sort alphabetically."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                # Use infra tab which has 2 items (good for sort testing)
                table = app.screen.query_one("#table-infra", ReticumAnnounceTable)

                table.sort_by("name")
                assert table._sort_column == "name"
                assert table._sort_reverse is False

    @pytest.mark.asyncio
    async def test_sort_toggle_direction(self, sample_devices):
        """Clicking same header again toggles sort direction."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one("#table-infra", ReticumAnnounceTable)

                table.sort_by("name")
                assert table._sort_reverse is False

                table.sort_by("name")
                assert table._sort_reverse is True


class TestExplorationLxmfShadowFiltering:
    """LXMF shadow entries for Styrene nodes are filtered out across all tabs."""

    @pytest.mark.asyncio
    async def test_lxmf_shadow_filtered_out(self):
        """An LXMF_PEER sharing identity_hash with a STYRENE_NODE should not appear."""
        now = int(datetime.now().timestamp())
        shared_identity = "aabb" * 8

        styrene_node = _make_device(
            "Testbed Node",
            DeviceType.STYRENE_NODE,
            dest_hash="1111" * 8,
            identity_hash=shared_identity,
            last_announce=now - 5,
        )
        lxmf_shadow = _make_device(
            "Testbed Node",
            DeviceType.LXMF_PEER,
            dest_hash="2222" * 8,
            identity_hash=shared_identity,
            last_announce=now - 5,
        )
        real_lxmf = _make_device(
            "Alice",
            DeviceType.LXMF_PEER,
            dest_hash="3333" * 8,
            identity_hash="ccdd" * 8,
            last_announce=now - 10,
        )

        devices = [styrene_node, lxmf_shadow, real_lxmf]
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                # Only the real LXMF peer should appear in the LXMF tab
                table = app.screen.query_one("#table-lxmf", ReticumAnnounceTable)
                assert table.device_count == 1

    @pytest.mark.asyncio
    async def test_unrelated_lxmf_peer_not_filtered(self):
        """An LXMF_PEER with unique identity_hash should still appear."""
        now = int(datetime.now().timestamp())
        devices = [
            _make_device(
                "Alice",
                DeviceType.LXMF_PEER,
                dest_hash="aaaa" * 8,
                identity_hash="aaaa" * 8,
                last_announce=now - 10,
            ),
            _make_device(
                "Bob",
                DeviceType.LXMF_PEER,
                dest_hash="bbbb" * 8,
                identity_hash="bbbb" * 8,
                last_announce=now - 20,
            ),
        ]
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one("#table-lxmf", ReticumAnnounceTable)
                assert table.device_count == 2


class TestExplorationScrollPreservation:
    """Cursor position is preserved across table rebuilds."""

    @pytest.mark.asyncio
    async def test_cursor_preserved_after_rebuild(self, sample_devices):
        """Cursor should stay on the same row key after _rebuild_table()."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                # Switch to infra tab (has 2 rows — good for cursor test)
                tabs = app.screen.query_one("#explore-tabs", TabbedContent)
                tabs.active = "tab-infra"
                await pilot.pause()

                table = app.screen.query_one("#table-infra", ReticumAnnounceTable)

                # Move cursor down
                await pilot.press("down")
                await pilot.pause()

                from textual.coordinate import Coordinate

                cursor_row = table.cursor_row
                cell_key = table.coordinate_to_cell_key(Coordinate(cursor_row, 0))
                selected_key = str(cell_key.row_key.value)

                # Rebuild table (simulates periodic refresh)
                table._rebuild_table()
                await pilot.pause()

                new_cursor_row = table.cursor_row
                new_cell_key = table.coordinate_to_cell_key(
                    Coordinate(new_cursor_row, 0)
                )
                assert str(new_cell_key.row_key.value) == selected_key


class TestExplorationCountIndicator:
    """Count indicator shows total announces for active tab."""

    @pytest.mark.asyncio
    async def test_count_indicator_shows(self, sample_devices):
        """Count indicator should show announces text."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                count = app.screen.query_one("#explore-count", Static)
                assert "announces" in str(count.render())


class TestPagesTabPreview:
    """Pages tab v key triggers inline page browser."""

    @pytest.mark.asyncio
    async def test_placeholder_visible_initially(self, sample_devices):
        """Pages tab should show placeholder before any preview."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                # Switch to Pages tab
                tabs = app.screen.query_one("#explore-tabs", TabbedContent)
                tabs.active = "tab-pages"
                await pilot.pause()

                placeholder = app.screen.query_one(
                    "#pages-browser-placeholder", Static
                )
                assert not placeholder.has_class("hidden")

    @pytest.mark.asyncio
    async def test_v_key_outside_pages_tab_does_nothing(self, sample_devices):
        """Pressing v on non-Pages tab should not trigger preview."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                # Stay on LXMF tab (default), press v
                await pilot.press("v")
                await pilot.pause()

                # Browser section should remain hidden
                from textual.containers import Vertical

                browser_section = app.screen.query_one(
                    "#pages-browser-section", Vertical
                )
                assert browser_section.has_class("hidden")


class TestEmptyTabPlaceholder:
    """Empty tabs show 'No announces discovered' message."""

    @pytest.mark.asyncio
    async def test_empty_tab_shows_placeholder_row(self):
        """Tab with no matching devices should show a placeholder row."""
        # Only LXMF devices — Pages tab will be empty
        devices = [
            _make_device("Alice", DeviceType.LXMF_PEER),
        ]
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one("#table-pages", ReticumAnnounceTable)
                assert table.device_count == 0
                # Table should have a placeholder row
                assert table.row_count == 1
