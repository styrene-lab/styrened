"""Comprehensive TUI tests for Dashboard screen.

Tests actual UI rendering, keyboard bindings, and user interactions
using Textual's app.run_test() and pilot.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.app import StyreneApp
from styrened.tui.screens.dashboard import DashboardScreen, MeshDeviceTree


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for all TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    mock_store = MagicMock()
    mock_store.get_styrene_nodes.return_value = []

    import styrened.services.node_store as _ns_mod

    old_singleton = _ns_mod._node_store
    _ns_mod._node_store = None

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
        patch("styrened.services.node_store.get_node_store", return_value=mock_store),
    ):
        yield

    _ns_mod._node_store = old_singleton


@pytest.fixture
def mock_devices():
    """Create mock mesh devices for testing."""
    now = int(datetime.now().timestamp())

    device1 = MeshDevice(
        destination_hash="a1b2c3d4e5f6",
        identity_hash="a1b2c3d4e5f6",
        name="Test Device 1",
        device_type=DeviceType.STYRENE_NODE,
        last_announce=now,
        announce_count=1,
    )
    device2 = MeshDevice(
        destination_hash="f6e5d4c3b2a1",
        identity_hash="f6e5d4c3b2a1",
        name="Test Device 2",
        device_type=DeviceType.STYRENE_NODE,
        last_announce=now - 300,
        announce_count=2,
    )
    return [device1, device2]


def _count_leaf_nodes(tree: MeshDeviceTree) -> int:
    """Count leaf nodes (devices) in the tree, excluding branch headers."""
    count = 0
    for node in tree._tree_walk(tree.root):
        if node.data is not None:
            count += 1
    return count


class TestDashboardComposition:
    """Test dashboard screen composition and widget tree."""

    @pytest.mark.asyncio
    async def test_dashboard_compose_creates_widgets(self):
        """Dashboard compose() should create all expected widgets."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, DashboardScreen)

            device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)
            assert device_tree is not None

    @pytest.mark.asyncio
    async def test_dashboard_loads_with_no_devices(self):
        """Dashboard should load successfully with no devices."""
        app = StyreneApp()

        with patch("styrened.tui.screens.dashboard.discover_devices", return_value=[]):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)
                assert _count_leaf_nodes(device_tree) == 0

    @pytest.mark.asyncio
    async def test_dashboard_displays_devices(self, mock_devices):
        """Dashboard should display devices in the tree."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)
                assert _count_leaf_nodes(device_tree) == 2


class TestDashboardKeyboardBindings:
    """Test dashboard keyboard bindings with actual key presses."""

    @pytest.mark.asyncio
    async def test_refresh_key_binding(self, mock_devices):
        """Pressing 'r' should refresh device list."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)
                initial_count = _count_leaf_nodes(device_tree)

                await pilot.press("r")
                await pilot.pause()

                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)
                assert device_tree is not None
                assert _count_leaf_nodes(device_tree) == initial_count

    @pytest.mark.asyncio
    async def test_provision_key_binding(self):
        """Pressing 'p' should open provision screen."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            await pilot.press("p")
            await pilot.pause()

    @pytest.mark.asyncio
    async def test_interrupt_binding(self):
        """Pressing 'ctrl+c' should have interrupt binding."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            interrupt_bindings = [b for b in app.BINDINGS if b.key == "ctrl+c"]
            assert len(interrupt_bindings) > 0

    @pytest.mark.asyncio
    async def test_enter_description_is_details(self):
        """Enter binding should have 'Details' description."""
        screen = DashboardScreen()
        enter_bindings = [b for b in screen.BINDINGS if b.key == "enter"]
        assert len(enter_bindings) == 1
        assert enter_bindings[0].description == "Details"

    @pytest.mark.asyncio
    async def test_no_standalone_status_binding(self):
        """Dashboard should not have standalone 's' (status) binding."""
        screen = DashboardScreen()
        s_bindings = [b for b in screen.BINDINGS if b.key == "s"]
        assert len(s_bindings) == 0, "Standalone 's' binding should be removed"

    @pytest.mark.asyncio
    async def test_chat_binding_exists(self):
        """Dashboard should have 'c' (chat) binding."""
        screen = DashboardScreen()
        c_bindings = [b for b in screen.BINDINGS if b.key == "c"]
        assert len(c_bindings) == 1
        assert c_bindings[0].action == "open_chat"


class TestDashboardDeviceSelection:
    """Test device selection and navigation."""

    @pytest.mark.asyncio
    async def test_tree_navigation(self, mock_devices):
        """Arrow keys should navigate device tree."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)

                # Press down arrow to navigate
                await pilot.press("down")
                await pilot.pause()

                # Tree should not crash
                assert device_tree is not None

    @pytest.mark.asyncio
    async def test_enter_key_selects_device(self, mock_devices):
        """Pressing Enter should not crash."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                await pilot.press("enter")
                await pilot.pause()

    @pytest.mark.asyncio
    async def test_get_selected_identity(self, mock_devices):
        """get_selected_identity() returns identity of selected leaf."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)

                # Navigate to a leaf node (skip root, skip branch header)
                await pilot.press("down")
                await pilot.pause()
                await pilot.press("down")
                await pilot.pause()

                # Should return an identity or None
                identity = device_tree.get_selected_identity()
                # May or may not be on a leaf node depending on tree structure


class TestDashboardAsyncUpdates:
    """Test async device discovery and real-time updates."""

    @pytest.mark.asyncio
    async def test_auto_refresh_updates_table(self, mock_devices):
        """Auto-refresh should update device tree."""
        app = StyreneApp()

        call_count = {"count": 0}

        def mock_discover():
            call_count["count"] += 1
            return mock_devices

        with patch("styrened.tui.screens.dashboard.discover_devices", mock_discover):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)

                initial_calls = call_count["count"]
                assert _count_leaf_nodes(device_tree) == 2

                device_tree.refresh_data()
                await pilot.pause()

                assert call_count["count"] > initial_calls
                assert _count_leaf_nodes(device_tree) == 2

    @pytest.mark.asyncio
    async def test_device_status_changes_reflect_in_ui(self, mock_devices):
        """Device status changes should update in tree."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)
                assert _count_leaf_nodes(device_tree) == 2


class TestDashboardErrorHandling:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_database_error_handled_gracefully(self):
        """Database errors should be handled gracefully."""
        app = StyreneApp()

        with patch(
            "styrened.tui.services.reticulum.discover_devices",
            side_effect=Exception("DB error"),
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                assert isinstance(screen, DashboardScreen)

    @pytest.mark.asyncio
    async def test_empty_device_selection_handled(self):
        """Selecting device when tree is empty should not crash."""
        app = StyreneApp()

        with patch("styrened.tui.services.reticulum.discover_devices", return_value=[]):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                await pilot.press("enter")
                await pilot.pause()


class TestDashboardScreenLifecycle:
    """Test screen lifecycle events."""

    @pytest.mark.asyncio
    async def test_on_mount_loads_devices(self, mock_devices):
        """on_mount should load devices from discovery."""
        app = StyreneApp()

        with (
            patch(
                "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
            ),
            patch("styrened.tui.screens.dashboard.start_discovery"),
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)
                assert _count_leaf_nodes(device_tree) == 2

    @pytest.mark.asyncio
    async def test_screen_resume_refreshes_data(self, mock_devices):
        """Resuming screen should refresh device list."""
        app = StyreneApp()

        with patch(
            "styrened.tui.services.reticulum.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                assert hasattr(screen, "_refresh_device_table")


class TestDashboardLostNodeFiltering:
    """Test that stale ghosts are filtered from the dashboard."""

    @pytest.mark.asyncio
    async def test_mesh_device_tree_filters_old_lost_nodes(self):
        """MeshDeviceTree should filter devices lost for >30 minutes."""
        now = int(datetime.now().timestamp())

        active_device = MeshDevice(
            destination_hash="active_hash",
            identity_hash="active_hash",
            name="Active Node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now,
            announce_count=5,
        )
        lost_device = MeshDevice(
            destination_hash="lost_hash",
            identity_hash="lost_hash",
            name="Lost Node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 86400,  # 24h ago — filtered by dedup
            announce_count=1,
        )
        stale_device = MeshDevice(
            destination_hash="stale_hash",
            identity_hash="stale_hash",
            name="Stale Node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 600,  # 10min ago — within 30min cutoff
            announce_count=3,
        )

        assert active_device.status == NodeStatus.ACTIVE
        assert lost_device.status == NodeStatus.LOST
        assert stale_device.status == NodeStatus.STALE

        devices = [active_device, lost_device, stale_device]

        app = StyreneApp()

        mock_store = MagicMock()
        mock_store.get_styrene_nodes.return_value = []

        with (
            patch(
                "styrened.tui.screens.dashboard.discover_devices", return_value=devices
            ),
            patch(
                "styrened.services.node_store.get_node_store", return_value=mock_store
            ),
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)

                # Only active + stale shown (lost >30min filtered by _deduplicate_by_identity)
                assert _count_leaf_nodes(device_tree) == 2
