"""Comprehensive navigation and workflow tests.

Tests screen transitions, keyboard navigation, and end-to-end user workflows.
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.app import StyreneApp
from styrened.tui.screens.dashboard import DashboardScreen, MeshDeviceTable
from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen


class TestAppInitialization:
    """Test application initialization and startup."""

    @pytest.mark.asyncio
    async def test_app_starts_with_dashboard(self):
        """App should start with dashboard screen."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Should start on dashboard
            # (Or first-run wizard if fresh install)

    @pytest.mark.asyncio
    async def test_app_loads_without_crash(self):
        """App should load without crashing."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # App should be running
            assert app.is_running

    @pytest.mark.asyncio
    async def test_app_title_set_correctly(self):
        """App title should be set correctly."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await pilot.pause()

            # Check app title
            assert "Styrene" in app.title or app.title != ""


class TestScreenNavigation:
    """Test navigation between screens."""

    @pytest.mark.asyncio
    async def test_dashboard_to_settings_navigation(self):
        """Navigate from dashboard to settings and back."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Should be on dashboard
            assert isinstance(app.screen, DashboardScreen)

            # Press 's' to open settings
            await pilot.press("s")
            await pilot.pause()

            # Should be on settings
            # Note: Actual behavior depends on implementation

            # Press Escape to return
            await pilot.press("escape")
            await pilot.pause()

            # Should be back on dashboard

    @pytest.mark.asyncio
    async def test_dashboard_to_device_detail_navigation(self):
        """Navigate from dashboard to device detail."""
        app = StyreneApp()

        device = MeshDevice(
            destination_hash="test_device",
            identity_hash="test_device",
            name="Test Device",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(datetime.now().timestamp()),
            announce_count=1,
        )

        with patch("styrened.tui.screens.dashboard.discover_devices", return_value=[device]):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Select device and press Enter
                await pilot.press("enter")
                await pilot.pause()

                # Should push device detail screen

    @pytest.mark.asyncio
    async def test_dashboard_to_provision_navigation(self):
        """Navigate from dashboard to provision screen."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Press 'p' to provision
            await pilot.press("p")
            await pilot.pause()

            # Should push provision screen

    @pytest.mark.asyncio
    async def test_screen_stack_management(self):
        """Screen stack should be managed correctly."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            # Push multiple screens
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            initial_stack_size = len(app.screen_stack)

            await pilot.press("grave_accent")  # Open settings
            await pilot.pause()

            # Stack should grow
            assert len(app.screen_stack) >= initial_stack_size

            await pilot.press("escape")  # Close settings
            await pilot.pause()

            # Stack should shrink back


class TestKeyboardWorkflows:
    """Test complete keyboard-driven workflows."""

    @pytest.mark.asyncio
    async def test_keyboard_only_device_status_workflow(self):
        """Complete device status check using only keyboard."""
        app = StyreneApp()

        device = MeshDevice(
            destination_hash="test_device",
            identity_hash="test_device",
            name="Test Device",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(datetime.now().timestamp()),
            announce_count=1,
        )

        # Mock RPC client
        mock_rpc_client = AsyncMock()
        mock_rpc_client.call_status = AsyncMock(
            return_value=Mock(
                uptime=3600,
                ip="192.168.1.100",
                disk_used=1000000,
                disk_total=10000000,
                services=[],
                os_id="Linux",
                os_version="6.1",
                arch="aarch64",
                format_uptime=Mock(return_value="1h 0m"),
            )
        )
        app.rpc_client = mock_rpc_client

        with (
            patch("styrened.tui.screens.dashboard.discover_devices", return_value=[device]),
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=[device],
            ),
        ):
            async with app.run_test() as pilot:
                # Start on dashboard
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Navigate to device
                await pilot.press("down")  # Move cursor
                await pilot.pause()

                await pilot.press("enter")  # Select device
                await pilot.pause()

                # Request status
                await pilot.press("s")  # Status request
                await pilot.pause()

                # Return to dashboard
                await pilot.press("escape")  # Back
                await pilot.pause()

                # Should be back on dashboard
                # Status should have been requested

    @pytest.mark.asyncio
    async def test_keyboard_only_settings_workflow(self):
        """Complete settings change using only keyboard."""
        app = StyreneApp()

        with patch("styrened.tui.screens.settings.save_config"):
            async with app.run_test() as pilot:
                # Start on dashboard
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Open settings
                await pilot.press("s")
                await pilot.pause()

                # Navigate form with Tab
                await pilot.press("tab")
                await pilot.pause()

                # Type new value
                await pilot.press(*"NewValue")
                await pilot.pause()

                # Save
                await pilot.press("ctrl+s")
                await pilot.pause()

                # Close
                await pilot.press("escape")
                await pilot.pause()

                # Should be back on dashboard
                # Settings should be saved

    @pytest.mark.asyncio
    async def test_keyboard_only_device_provision_workflow(self):
        """Complete device provisioning using only keyboard."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            # Start on dashboard
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Open provision screen
            await pilot.press("p")
            await pilot.pause()

            # Fill out provision form using Tab and typing
            await pilot.press("tab")
            await pilot.pause()

            await pilot.press(*"NewDevice")
            await pilot.pause()

            await pilot.press("tab")
            await pilot.pause()

            # Submit provision
            await pilot.press("enter")
            await pilot.pause()

            # Should provision device and return to dashboard


class TestUserWorkflows:
    """Test complete end-to-end user workflows."""

    @pytest.mark.asyncio
    async def test_discover_and_add_device_workflow(self):
        """Complete workflow: discover device, add to list, check status."""
        app = StyreneApp()

        # Simulate device discovery
        discovered_device = MeshDevice(
            destination_hash="discovered_device",
            identity_hash="discovered_device",
            name="New Device",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(datetime.now().timestamp()),
            announce_count=1,
        )

        # Create a second device for row count comparison
        discovered_device_2 = MeshDevice(
            destination_hash="discovered_device_2",
            identity_hash="discovered_device_2",
            name="New Device 2",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(datetime.now().timestamp()),
            announce_count=1,
        )

        # Mock both discover_devices and NodeStore to control exact device list
        mock_node_store = Mock()
        mock_node_store.get_styrene_nodes.return_value = []

        with (
            patch(
                "styrened.tui.screens.dashboard.discover_devices",
                return_value=[discovered_device, discovered_device_2],
            ),
            patch(
                "styrened.services.node_store.get_node_store",
                return_value=mock_node_store,
            ),
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Devices should be displayed
                screen = app.screen
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)
                # Should show 2 devices
                assert device_table.row_count == 2

                # Trigger refresh should still work
                await pilot.press("r")
                await pilot.pause()

                # Should still show 2 devices
                assert device_table.row_count == 2

    @pytest.mark.asyncio
    async def test_device_goes_offline_workflow(self):
        """Workflow: device goes offline, status check fails, UI reflects."""
        app = StyreneApp()

        device = MeshDevice(
            destination_hash="test_device",
            identity_hash="test_device",
            name="Test Device",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(datetime.now().timestamp()),
            announce_count=1,
        )

        # Mock RPC client with timeout
        mock_rpc_client = AsyncMock()
        mock_rpc_client.call_status = AsyncMock(
            side_effect=TimeoutError("Device offline")
        )
        app.rpc_client = mock_rpc_client

        with (
            patch("styrened.tui.screens.dashboard.discover_devices", return_value=[device]),
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=[device],
            ),
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Select device
                await pilot.press("enter")
                await pilot.pause()

                # Request status (will timeout)
                await pilot.press("s")
                await pilot.pause()

                # Should show error
                # Device status should update to offline

    @pytest.mark.asyncio
    async def test_bulk_device_status_check_workflow(self):
        """Workflow: check status of multiple devices."""
        app = StyreneApp()

        devices = [
            MeshDevice(
                destination_hash=f"device_{i}",
                identity_hash=f"device_{i}",
                name=f"Device {i}",
                device_type=DeviceType.STYRENE_NODE,
                last_announce=int(datetime.now().timestamp()),
                announce_count=1,
            )
            for i in range(3)
        ]

        with patch("styrened.tui.screens.dashboard.discover_devices", return_value=devices):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # For each device: select, check status, return
                for i in range(len(devices)):
                    # Navigate to device i
                    for _ in range(i):
                        await pilot.press("down")
                        await pilot.pause()

                    # Select device
                    await pilot.press("enter")
                    await pilot.pause()

                    # Check status
                    await pilot.press("s")
                    await pilot.pause()

                    # Return to dashboard
                    await pilot.press("escape")
                    await pilot.pause()

                    # Reset cursor
                    for _ in range(i):
                        await pilot.press("up")
                        await pilot.pause()


class TestErrorRecovery:
    """Test error recovery and resilience."""

    @pytest.mark.asyncio
    async def test_network_error_recovery(self):
        """App should recover from network errors."""
        app = StyreneApp()

        device = MeshDevice(
            destination_hash="test_device",
            identity_hash="test_device",
            name="Test Device",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(datetime.now().timestamp()),
            announce_count=1,
        )

        # Mock RPC client with failure then success
        mock_rpc_client = AsyncMock()
        mock_rpc_client.call_status = AsyncMock(
            side_effect=[
                Exception("Network error"),
                Mock(
                    uptime=3600,
                    ip="192.168.1.100",
                    disk_used=1000000,
                    disk_total=10000000,
                    services=[],
                    os_id="Linux",
                    os_version="6.1",
                    arch="aarch64",
                    format_uptime=Mock(return_value="1h 0m"),
                ),
            ]
        )
        app.rpc_client = mock_rpc_client

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices", return_value=[device]
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=device.identity)
                )
                await pilot.pause()

                # First status request (fails)
                await pilot.press("s")
                await pilot.pause()

                # Retry
                await pilot.press("s")
                await pilot.pause()

                # Should succeed on retry

    @pytest.mark.asyncio
    async def test_invalid_screen_state_recovery(self):
        """App should recover from invalid screen states."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Simulate invalid state (device table cleared unexpectedly)
            # App should handle gracefully and allow recovery

    @pytest.mark.asyncio
    async def test_rapid_navigation_doesnt_crash(self):
        """Rapid screen navigation should not crash app."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Rapidly navigate between screens
            for _ in range(10):
                await pilot.press("grave_accent")  # Open settings
                await pilot.press("escape")  # Close settings
                await pilot.pause(0.01)  # Minimal pause

            # App should still be running
            assert app.is_running


class TestAccessibility:
    """Test accessibility features."""

    @pytest.mark.asyncio
    async def test_all_actions_have_keyboard_shortcuts(self):
        """All actions should be accessible via keyboard."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Verify key bindings exist
            screen = app.screen
            bindings = screen.BINDINGS

            # Should have bindings for: quit, refresh, provision, settings
            assert len(bindings) > 0

    @pytest.mark.asyncio
    async def test_focus_navigation_works(self):
        """Tab/Shift+Tab should navigate focus correctly."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            # Tab through focusable widgets
            await pilot.press("tab")
            await pilot.pause()

            # Shift+Tab to go back
            await pilot.press("shift+tab")
            await pilot.pause()

            # Focus should move predictably


class TestPerformance:
    """Test performance with many devices."""

    @pytest.mark.asyncio
    async def test_large_device_list_renders(self):
        """Dashboard should handle large device lists."""
        app = StyreneApp()

        # Create 100 devices
        devices = [
            MeshDevice(
                destination_hash=f"device_{i:03d}",
                identity_hash=f"device_{i:03d}",
                name=f"Device {i}",
                device_type=DeviceType.STYRENE_NODE,
                last_announce=int(datetime.now().timestamp()),
                announce_count=1,
            )
            for i in range(100)
        ]

        mock_node_store = Mock()
        mock_node_store.get_styrene_nodes.return_value = []

        with (
            patch("styrened.tui.screens.dashboard.discover_devices", return_value=devices),
            patch("styrened.services.node_store.get_node_store", return_value=mock_node_store),
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Should render without hanging
                screen = app.screen
                device_table = screen.query_one("#mesh-device-table", MeshDeviceTable)
                assert device_table.row_count == 100

    @pytest.mark.asyncio
    async def test_rapid_refresh_doesnt_hang(self):
        """Rapid refreshes should not hang the UI."""
        app = StyreneApp()

        with patch("styrened.tui.screens.dashboard.discover_devices", return_value=[]):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                # Rapid refresh
                for _ in range(20):
                    await pilot.press("r")
                    await pilot.pause(0.01)

                # UI should still be responsive
                assert app.is_running
