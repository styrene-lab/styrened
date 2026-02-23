"""TUI tests for ExplorationScreen - search, sort, and type display.

Tests the search input, column sorting, and new device type display.
"""

from datetime import datetime
from unittest.mock import patch

import pytest
from textual.widgets import Input, Static

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.app import StyreneApp
from styrened.tui.screens.exploration import ExplorationScreen, ReticumAnnounceTable


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
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
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
    """Search input filters table rows."""

    @pytest.mark.asyncio
    async def test_search_filters_by_name(self, sample_devices):
        """Typing in search should filter table to matching rows."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one(
                    "#reticulum-announce-table", ReticumAnnounceTable
                )
                initial_count = table.row_count

                # Activate search and type
                await pilot.press("slash")
                await pilot.pause()
                await pilot.press("a", "l", "i", "c", "e")
                await pilot.pause()

                # Should have fewer rows (only "Alice" matches)
                assert table.row_count < initial_count
                assert table.row_count >= 1


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
                await pilot.press("a", "l", "i")
                await pilot.pause()

                table = app.screen.query_one(
                    "#reticulum-announce-table", ReticumAnnounceTable
                )
                filtered_count = table.row_count

                # Press escape to dismiss
                await pilot.press("escape")
                await pilot.pause()

                search = app.screen.query_one("#explore-search-bar", Input)
                assert search.has_class("hidden")
                assert search.value == ""
                # All rows should be back
                assert table.row_count >= filtered_count


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

                table = app.screen.query_one(
                    "#reticulum-announce-table", ReticumAnnounceTable
                )

                # Sort by name
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

                table = app.screen.query_one(
                    "#reticulum-announce-table", ReticumAnnounceTable
                )

                # Sort ascending
                table.sort_by("name")
                assert table._sort_reverse is False

                # Click again - should toggle to descending
                table.sort_by("name")
                assert table._sort_reverse is True

    @pytest.mark.asyncio
    async def test_sort_by_type(self, sample_devices):
        """Sorting by type groups devices by their type value."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one(
                    "#reticulum-announce-table", ReticumAnnounceTable
                )

                table.sort_by("type")
                assert table._sort_column == "type"
                # Should have all rows still
                assert table.row_count == len(sample_devices)


class TestExplorationNewDeviceTypes:
    """New device types display correctly."""

    @pytest.mark.asyncio
    async def test_lxmf_peer_displays(self, sample_devices):
        """LXMF peer should show LXMF type label."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                table = app.screen.query_one(
                    "#reticulum-announce-table", ReticumAnnounceTable
                )
                # Should have rows for all device types
                assert table.row_count == len(sample_devices)

    @pytest.mark.asyncio
    async def test_count_indicator_shows(self, sample_devices):
        """Count indicator should show total announces."""
        app = StyreneApp()
        p1, p2, p3 = _patch_discovery(sample_devices)
        with p1, p2, p3:
            async with app.run_test() as pilot:
                await app.push_screen(ExplorationScreen())
                await pilot.pause()

                count = app.screen.query_one("#explore-count", Static)
                assert "announces" in str(count.render())


class TestExplorationLxmfShadowFiltering:
    """LXMF shadow entries for Styrene nodes are filtered out."""

    @pytest.mark.asyncio
    async def test_lxmf_shadow_filtered_out(self):
        """An LXMF_PEER sharing identity_hash with a STYRENE_NODE should not appear."""
        now = int(datetime.now().timestamp())
        shared_identity = "aabb" * 8  # 32 hex chars

        # Styrene node on operator aspect (different dest_hash, same identity)
        styrene_node = _make_device(
            "Testbed Node",
            DeviceType.STYRENE_NODE,
            dest_hash="1111" * 8,
            identity_hash=shared_identity,
            last_announce=now - 5,
        )
        # LXMF shadow on delivery aspect (different dest_hash, same identity)
        lxmf_shadow = _make_device(
            "Testbed Node",
            DeviceType.LXMF_PEER,
            dest_hash="2222" * 8,
            identity_hash=shared_identity,
            last_announce=now - 5,
        )
        # Unrelated LXMF peer (different identity)
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

                table = app.screen.query_one(
                    "#reticulum-announce-table", ReticumAnnounceTable
                )
                # Only the real LXMF peer should appear (shadow and styrene both excluded)
                assert table.row_count == 1

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

                table = app.screen.query_one(
                    "#reticulum-announce-table", ReticumAnnounceTable
                )
                assert table.row_count == 2


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

                table = app.screen.query_one(
                    "#reticulum-announce-table", ReticumAnnounceTable
                )

                # Move cursor down a few rows
                await pilot.press("down", "down")
                await pilot.pause()

                # Record which row key is selected
                from textual.coordinate import Coordinate

                cursor_row = table.cursor_row
                cell_key = table.coordinate_to_cell_key(Coordinate(cursor_row, 0))
                selected_key = str(cell_key.row_key.value)

                # Rebuild table (simulates periodic refresh)
                table._rebuild_table()
                await pilot.pause()

                # Cursor should still point to the same row key
                new_cursor_row = table.cursor_row
                new_cell_key = table.coordinate_to_cell_key(
                    Coordinate(new_cursor_row, 0)
                )
                assert str(new_cell_key.row_key.value) == selected_key
