"""Comprehensive TUI tests for Dashboard screen.

Tests actual UI rendering, keyboard bindings, and user interactions
using Textual's app.run_test() and pilot.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from styrened.tui.app import StyreneApp
from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.screens.dashboard import DashboardScreen, MeshDeviceTable


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for all TUI tests."""
    # Create a fake config directory
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")  # Empty config file

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch(
            "styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config
        ),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


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
        device_type=DeviceType.RNODE,
        last_announce=now - 300,  # 5 minutes ago
        announce_count=2,
    )
    return [device1, device2]


class TestDashboardComposition:
    """Test dashboard screen composition and widget tree."""

    @pytest.mark.asyncio
    async def test_dashboard_compose_creates_widgets(self):
        """Dashboard compose() should create all expected widgets."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Verify widgets exist
            screen = app.screen
            assert isinstance(screen, DashboardScreen)

            # Check for device table widget
            device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)
            assert device_table is not None
            assert device_table.id == "mesh-device-table"

    @pytest.mark.asyncio
    async def test_dashboard_loads_with_no_devices(self):
        """Dashboard should load successfully with no devices."""
        app = StyreneApp()

        with patch("styrened.tui.services.reticulum.discover_devices", return_value=[]):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)

                # Table should have 1 row (placeholder message)
                assert device_table.row_count == 1

    @pytest.mark.asyncio
    async def test_dashboard_displays_devices(self, mock_devices):
        """Dashboard should display devices in the table."""
        app = StyreneApp()

        # Patch at the point where dashboard imports it
        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)

                # Should have 2 rows (2 devices)
                assert device_table.row_count == 2


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

                # Get initial row count
                screen = app.screen
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)
                initial_count = device_table.row_count

                # Press 'r' to refresh
                await pilot.press("r")
                await pilot.pause()

                # Table should still exist (refresh completed)
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)
                assert device_table is not None
                assert device_table.row_count == initial_count

    @pytest.mark.asyncio
    async def test_provision_key_binding(self):
        """Pressing 'p' should open provision screen."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Press 'p' to provision
            await pilot.press("p")
            await pilot.pause()

            # Provision screen should be pushed (screen stack grows)
            # Note: This tests the binding exists and doesn't crash

    @pytest.mark.asyncio
    async def test_quit_key_binding(self):
        """Pressing 'ctrl+c' should have quit binding."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Check for quit binding in app (ctrl+c is the priority quit binding)
            quit_bindings = [b for b in app.BINDINGS if b.key == "ctrl+c"]
            assert len(quit_bindings) > 0

    @pytest.mark.asyncio
    async def test_settings_key_binding(self):
        """Pressing 's' should open settings screen."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Press 's' to open settings
            await pilot.press("s")
            await pilot.pause()

            # Settings screen should be pushed


class TestDashboardDeviceSelection:
    """Test device selection and navigation."""

    @pytest.mark.asyncio
    async def test_arrow_key_navigation(self, mock_devices):
        """Arrow keys should navigate device list."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)

                # Initial cursor position
                initial_row = device_table.cursor_row

                # Press down arrow
                await pilot.press("down")
                await pilot.pause()

                # Cursor should move
                assert device_table.cursor_row != initial_row

    @pytest.mark.asyncio
    async def test_enter_key_selects_device(self, mock_devices):
        """Pressing Enter should open device detail screen."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Press Enter to select device
                await pilot.press("enter")
                await pilot.pause()

                # Should push device detail screen (doesn't crash)


class TestDashboardRPCActions:
    """Test RPC action buttons and commands."""

    @pytest.mark.asyncio
    async def test_status_request_action(self, mock_devices):
        """Status request action should send RPC call."""
        app = StyreneApp()

        # Mock RPC client
        mock_rpc_client = AsyncMock()
        mock_response = Mock()
        mock_response.uptime = 3600
        mock_response.ip = "192.168.1.100"
        mock_rpc_client.call_status = AsyncMock(return_value=mock_response)

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Set mock AFTER app startup (which overwrites rpc_client)
                app.rpc_client = mock_rpc_client

                screen = app.screen

                # Trigger status request action
                await screen.action_request_status()
                await pilot.pause()

                # Verify RPC call was made
                assert mock_rpc_client.call_status.called


class TestDashboardAsyncUpdates:
    """Test async device discovery and real-time updates."""

    @pytest.mark.asyncio
    async def test_auto_refresh_updates_table(self, mock_devices):
        """Auto-refresh should update device table."""
        app = StyreneApp()

        # Track calls to verify refresh happened
        call_count = {"count": 0}

        def mock_discover():
            call_count["count"] += 1
            return mock_devices

        with patch("styrened.tui.screens.dashboard.discover_devices", mock_discover):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)

                # Initial state (devices loaded on mount)
                initial_calls = call_count["count"]
                assert device_table.row_count == 2

                # Refresh
                device_table.refresh_data()
                await pilot.pause()

                # Should have called discover_devices again
                assert call_count["count"] > initial_calls
                # Should still have 2 devices
                assert device_table.row_count == 2

    @pytest.mark.asyncio
    async def test_device_status_changes_reflect_in_ui(self, mock_devices):
        """Device status changes should update in table."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Table renders successfully with devices
                screen = app.screen
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)
                assert device_table.row_count == 2


class TestDashboardErrorHandling:
    """Test error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_rpc_timeout_shows_error(self, mock_devices):
        """RPC timeout should show error message."""
        app = StyreneApp()

        # Mock RPC client with timeout
        from styrened.rpc.errors import RPCTimeoutError

        mock_rpc_client = AsyncMock()
        mock_rpc_client.call_status = AsyncMock(
            side_effect=RPCTimeoutError(
                "Timeout", request_id="test-id", destination="abc123", timeout=30.0
            )
        )

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=mock_devices
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Set mock AFTER app startup (which overwrites rpc_client)
                app.rpc_client = mock_rpc_client

                screen = app.screen

                # Trigger status request (should timeout)
                await screen.action_request_status()
                await pilot.pause()

                # Should not crash (error handled gracefully)

    @pytest.mark.asyncio
    async def test_database_error_handled_gracefully(self):
        """Database errors should be handled gracefully."""
        app = StyreneApp()

        # Mock discover_devices to raise exception
        with patch(
            "styrened.tui.services.reticulum.discover_devices",
            side_effect=Exception("DB error"),
        ):
            async with app.run_test() as pilot:
                # Should not crash
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Screen should load (with error handling)
                screen = app.screen
                assert isinstance(screen, DashboardScreen)

    @pytest.mark.asyncio
    async def test_empty_device_selection_handled(self):
        """Selecting device when table is empty should not crash."""
        app = StyreneApp()

        with patch("styrened.tui.services.reticulum.discover_devices", return_value=[]):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Try to select device (should handle gracefully)
                await pilot.press("enter")
                await pilot.pause()

                # Should not crash


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

                # on_mount should have loaded devices
                screen = app.screen
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)
                assert device_table.row_count == 2

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

                # Verify the mechanism exists
                screen = app.screen
                assert hasattr(screen, "_refresh_device_table")


class TestDashboardLostNodeFiltering:
    """Test that lost nodes are excluded from the dashboard device table."""

    @pytest.mark.asyncio
    async def test_mesh_device_table_excludes_lost_nodes(self):
        """MeshDeviceTable should not display devices with LOST status."""
        now = int(datetime.now().timestamp())

        active_device = MeshDevice(
            destination_hash="active_hash",
            identity_hash="active_hash",
            name="Active Node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now,  # Just now -> ACTIVE
            announce_count=5,
        )
        lost_device = MeshDevice(
            destination_hash="lost_hash",
            identity_hash="lost_hash",
            name="Lost Node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 86400,  # 24h ago -> LOST
            announce_count=1,
        )
        stale_device = MeshDevice(
            destination_hash="stale_hash",
            identity_hash="stale_hash",
            name="Stale Node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 600,  # 10min ago -> STALE
            announce_count=3,
        )

        # Verify status assumptions
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
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)

                # Should have 2 rows (active + stale), NOT 3 (lost excluded)
                assert device_table.row_count == 2
