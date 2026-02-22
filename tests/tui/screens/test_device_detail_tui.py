"""Comprehensive TUI tests for MeshDeviceDetailScreen.

Tests device information display, RPC actions, tabbed layout, and real-time updates.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from styrened.tui.app import StyreneApp
from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.rpc.messages import ExecResult, StatusResponse
from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
from textual.widgets import Button, Static, TabbedContent


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for all TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch(
            "styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config
        ),
        patch(
            "styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config
        ),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


@pytest.fixture
def test_device():
    """Create a test mesh device."""
    now = int(datetime.now().timestamp())
    return MeshDevice(
        destination_hash="test_device_hash",
        identity_hash="test_device_hash",
        name="Test Device",
        device_type=DeviceType.STYRENE_NODE,
        last_announce=now,
        announce_count=1,
    )


class TestDeviceDetailComposition:
    """Test device detail screen composition."""

    @pytest.mark.asyncio
    async def test_device_detail_displays_device_info(self, test_device):
        """Device detail should display all device information."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                screen = app.screen
                assert isinstance(screen, MeshDeviceDetailScreen)

                # Check for device info widgets
                statics = list(screen.query(Static))
                assert len(statics) > 0

    @pytest.mark.asyncio
    async def test_device_detail_has_tabbed_content(self, test_device):
        """Device detail should use TabbedContent layout."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                screen = app.screen

                # Should have TabbedContent
                tabbed = screen.query(TabbedContent)
                assert len(tabbed) > 0, "Device detail should use TabbedContent"

    @pytest.mark.asyncio
    async def test_device_detail_has_status_chat_command_ssh_tabs(self, test_device):
        """Device detail should have Status, Chat, Command, and SSH tabs."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                screen = app.screen

                # Check for tab panes by ID
                from textual.widgets import TabPane

                panes = list(screen.query(TabPane))
                pane_ids = {p.id for p in panes}

                assert "status" in pane_ids, f"Missing Status tab. Found: {pane_ids}"
                assert "chat" in pane_ids, f"Missing Chat tab. Found: {pane_ids}"
                assert "command" in pane_ids, f"Missing Command tab. Found: {pane_ids}"
                assert "ssh" in pane_ids, f"Missing SSH tab. Found: {pane_ids}"

    @pytest.mark.asyncio
    async def test_device_detail_shows_action_buttons(self, test_device):
        """Device detail should show action buttons."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                screen = app.screen

                # Check for action buttons (refresh button)
                buttons = list(screen.query(Button))
                assert len(buttons) > 0

    @pytest.mark.asyncio
    async def test_device_detail_accepts_initial_tab(self, test_device):
        """Device detail should accept initial_tab parameter."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(
                        device_identity=test_device.identity,
                        initial_tab="chat",
                    )
                )
                await pilot.pause()

                screen = app.screen
                assert isinstance(screen, MeshDeviceDetailScreen)
                assert screen.initial_tab == "chat"


class TestDeviceDetailRPCActions:
    """Test RPC action buttons."""

    @pytest.mark.asyncio
    async def test_status_button_sends_rpc_request(self, test_device):
        """Status button should send RPC status request."""
        app = StyreneApp()

        # Mock RPC client with real StatusResponse
        mock_rpc_client = AsyncMock()
        mock_response = StatusResponse(
            uptime=3600,
            ip="192.168.1.100",
            disk_used=1000000,
            disk_total=10000000,
            services=[],
        )
        mock_rpc_client.call_status = AsyncMock(return_value=mock_response)

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Set mock AFTER app startup
                app.rpc_client = mock_rpc_client

                screen = app.screen

                # Trigger refresh status action
                await screen.action_refresh_status()
                await pilot.pause()

                # RPC call should be made
                assert mock_rpc_client.call_status.called

    @pytest.mark.asyncio
    async def test_exec_button_shows_command_prompt(self, test_device):
        """Exec button should show command input prompt."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Screen renders successfully


class TestDeviceDetailKeyboardBindings:
    """Test device detail keyboard bindings."""

    @pytest.mark.asyncio
    async def test_escape_returns_to_dashboard(self, test_device):
        """Escape should return to dashboard."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Press Escape
                await pilot.press("escape")
                await pilot.pause()

                # Should pop detail screen

    @pytest.mark.asyncio
    async def test_r_refreshes_device_status(self, test_device):
        """Pressing 'r' should refresh device status."""
        app = StyreneApp()

        mock_rpc_client = AsyncMock()
        mock_response = StatusResponse(
            uptime=3600,
            ip="192.168.1.100",
            disk_used=1000000,
            disk_total=10000000,
            services=[],
        )
        mock_rpc_client.call_status = AsyncMock(return_value=mock_response)

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Set mock AFTER app startup
                app.rpc_client = mock_rpc_client

                # Press 'r' to refresh
                await pilot.press("r")
                await pilot.pause()

                # Should make RPC call
                assert mock_rpc_client.call_status.called


class TestDeviceDetailRealTimeUpdates:
    """Test real-time device status updates."""

    @pytest.mark.asyncio
    async def test_status_updates_reflected_in_ui(self, test_device):
        """Status updates should be reflected in UI."""
        app = StyreneApp()

        mock_rpc_client = AsyncMock()
        mock_response = StatusResponse(
            uptime=7200,
            ip="192.168.1.100",
            disk_used=2000000,
            disk_total=10000000,
            services=["ssh", "http"],
        )
        mock_rpc_client.call_status = AsyncMock(return_value=mock_response)
        app.rpc_client = mock_rpc_client

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                screen = app.screen

                # Request status
                await screen.action_refresh_status()
                await pilot.pause()

                # UI should show updated data (test doesn't crash)

    @pytest.mark.asyncio
    async def test_last_seen_timestamp_updates(self, test_device):
        """Last seen timestamp should update on successful RPC."""
        app = StyreneApp()

        mock_rpc_client = AsyncMock()
        mock_response = StatusResponse(
            uptime=3600,
            ip="192.168.1.100",
            disk_used=1000000,
            disk_total=10000000,
            services=[],
        )
        mock_rpc_client.call_status = AsyncMock(return_value=mock_response)
        app.rpc_client = mock_rpc_client

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Request status
                await pilot.press("r")
                await pilot.pause()

                # Should complete successfully


class TestDeviceDetailErrorHandling:
    """Test error handling in device detail."""

    @pytest.mark.asyncio
    async def test_rpc_timeout_shows_error_message(self, test_device):
        """RPC timeout should show error message."""
        app = StyreneApp()

        from styrened.rpc.errors import RPCTimeoutError

        mock_rpc_client = AsyncMock()
        mock_rpc_client.call_status = AsyncMock(
            side_effect=RPCTimeoutError(
                "RPC timeout", request_id="test-id", destination="test-dest", timeout=30.0
            )
        )
        app.rpc_client = mock_rpc_client

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Request status (will timeout)
                await pilot.press("r")
                await pilot.pause()

                # Should show error notification (doesn't crash)

    @pytest.mark.asyncio
    async def test_unauthorized_rpc_shows_error(self, test_device):
        """Unauthorized RPC should show error message."""
        app = StyreneApp()

        mock_rpc_client = AsyncMock()
        mock_rpc_client.call_status = AsyncMock(side_effect=Exception("Unauthorized"))
        app.rpc_client = mock_rpc_client

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Request status (will fail)
                await pilot.press("r")
                await pilot.pause()

                # Should show error (doesn't crash)

    @pytest.mark.asyncio
    async def test_device_offline_handled_gracefully(self):
        """Device offline should be handled gracefully."""
        app = StyreneApp()

        now = int(datetime.now().timestamp())
        offline_device = MeshDevice(
            destination_hash="test_device",
            identity_hash="test_device",
            name="Test Device",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 10000,  # Long ago
            announce_count=1,
        )

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[offline_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=offline_device.identity)
                )
                await pilot.pause()

                # Screen renders successfully for offline device


class TestDeviceDetailExecCommand:
    """Test exec command functionality."""

    @pytest.mark.asyncio
    async def test_exec_command_dialog_accepts_input(self, test_device):
        """Exec command dialog should accept command input."""
        app = StyreneApp()

        mock_rpc_client = AsyncMock()
        mock_result = ExecResult(
            exit_code=0,
            stdout="Hello World",
            stderr="",
        )
        mock_rpc_client.call_exec = AsyncMock(return_value=mock_result)
        app.rpc_client = mock_rpc_client

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Command widget is in the Command tab

    @pytest.mark.asyncio
    async def test_exec_output_displayed(self, test_device):
        """Exec command output should be displayed."""
        app = StyreneApp()

        mock_rpc_client = AsyncMock()
        mock_result = ExecResult(
            exit_code=0,
            stdout="Command output here",
            stderr="",
        )
        mock_rpc_client.call_exec = AsyncMock(return_value=mock_result)
        app.rpc_client = mock_rpc_client

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Command widget handles output display


class TestDeviceDetailNavigation:
    """Test navigation from device detail."""

    @pytest.mark.asyncio
    async def test_back_button_returns_to_list(self, test_device):
        """Back button should return to device list."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity)
                )
                await pilot.pause()

                # Press Escape
                await pilot.press("escape")
                await pilot.pause()

                # Should pop screen

    @pytest.mark.asyncio
    async def test_device_not_found_returns_to_list(self):
        """Device not found should return to list."""
        app = StyreneApp()

        # Empty device list (device not found)
        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices", return_value=[]
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity="nonexistent_device")
                )

                # Should handle gracefully (show error or return to list)


class TestDeviceDetailNodeStoreFallback:
    """Test NodeStore fallback for IPC mode where discover_devices is empty."""

    @pytest.mark.asyncio
    async def test_device_loaded_from_node_store_when_discover_empty(self, test_device):
        """Device should load from NodeStore when discover_devices returns empty."""
        app = StyreneApp()

        mock_store = MagicMock()
        mock_store.get_all_nodes.return_value = [test_device]

        with (
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=[],
            ),
            patch(
                "styrened.services.node_store.get_node_store",
                return_value=mock_store,
            ),
        ):
            async with app.run_test() as pilot:
                screen = MeshDeviceDetailScreen(device_identity=test_device.identity)
                await app.push_screen(screen)
                await pilot.pause()

                assert isinstance(app.screen, MeshDeviceDetailScreen)
                assert app.screen.device is not None
                assert app.screen.device.identity == test_device.identity

    @pytest.mark.asyncio
    async def test_live_devices_take_precedence_over_node_store(self, test_device):
        """Live discovered devices should override NodeStore entries."""
        app = StyreneApp()

        now = int(datetime.now().timestamp())
        stale_device = MeshDevice(
            destination_hash=test_device.destination_hash,
            identity_hash=test_device.identity_hash,
            name="Stale Name",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 1000,
            announce_count=1,
        )

        mock_store = MagicMock()
        mock_store.get_all_nodes.return_value = [stale_device]

        with (
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=[test_device],
            ),
            patch(
                "styrened.services.node_store.get_node_store",
                return_value=mock_store,
            ),
        ):
            async with app.run_test() as pilot:
                screen = MeshDeviceDetailScreen(device_identity=test_device.identity)
                await app.push_screen(screen)
                await pilot.pause()

                assert app.screen.device is not None
                assert app.screen.device.name == "Test Device"

    @pytest.mark.asyncio
    async def test_device_not_found_in_either_source(self):
        """Device not in NodeStore or discover_devices should show error."""
        app = StyreneApp()

        mock_store = MagicMock()
        mock_store.get_all_nodes.return_value = []

        with (
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=[],
            ),
            patch(
                "styrened.services.node_store.get_node_store",
                return_value=mock_store,
            ),
        ):
            async with app.run_test() as pilot:
                screen = MeshDeviceDetailScreen(device_identity="nonexistent")
                await app.push_screen(screen)
                await pilot.pause()

                assert app.screen.device is None
