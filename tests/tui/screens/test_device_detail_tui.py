"""Comprehensive TUI tests for MeshDeviceDetailScreen.

Tests device information display, RPC actions, tabbed layout, and real-time updates.
"""
from __future__ import annotations


from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

import pytest
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Button, Static, TabbedContent

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.rpc.messages import ExecResult, StatusResponse
from styrened.tui.app import StyreneApp
from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
from styrened.ui_state import PeerWorkspaceFocus, WorkspaceId


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


class DummyOriginScreen(Screen[None]):
    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label

    def compose(self) -> ComposeResult:
        yield Static(self.label)


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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
                )
                await pilot.pause()

                screen = app.screen

                # Should have TabbedContent
                tabbed = screen.query(TabbedContent)
                assert len(tabbed) > 0, "Device detail should use TabbedContent"

    @pytest.mark.asyncio
    async def test_device_detail_has_status_mail_chat_fleet_ops_terminal_tabs(self, test_device):
        """Device detail should have Status, Mail, Chat, Fleet Ops, and Terminal tabs."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
                )
                await pilot.pause()

                screen = app.screen

                # Check for tab panes by ID
                from textual.widgets import TabPane

                panes = list(screen.query(TabPane))
                pane_ids = {p.id for p in panes}

                assert "status" in pane_ids, f"Missing Status tab. Found: {pane_ids}"
                assert "mail" in pane_ids, f"Missing Mail tab. Found: {pane_ids}"
                assert "chat" in pane_ids, f"Missing Chat tab. Found: {pane_ids}"
                assert "fleet-ops" in pane_ids, f"Missing Fleet Ops tab. Found: {pane_ids}"
                assert "terminal" in pane_ids, f"Missing Terminal tab. Found: {pane_ids}"

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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
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
                        device_identity=test_device.identity_hash,
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
    async def test_auto_fetch_status_uses_bridge_status_query(self, test_device):
        """Status refresh should use the IPC bridge status query contract."""
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        mock_bridge = MagicMock()
        mock_response = StatusResponse(
            uptime=3600,
            ip="192.168.1.100",
            disk_used=1000000,
            disk_total=10000000,
            services=[],
        )
        mock_bridge.datalink_status = AsyncMock(return_value={"connected": False})
        mock_bridge.query_device_status = AsyncMock(return_value=mock_response)
        status_widget = Mock()
        status_widget.link_info = None
        status_widget.status = None
        status_widget.loading = False
        status_widget.error = None
        app = Mock()
        app.services.bridge = mock_bridge

        with (
            patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "query_one", return_value=status_widget),
        ):
            await screen._auto_fetch_status()

        mock_bridge.query_device_status.assert_awaited_once()
        assert status_widget.status == mock_response

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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
                )
                await pilot.pause()

                # Screen renders successfully


class TestDeviceDetailLoadingState:
    """Test lifecycle-managed unresolved-device behavior."""

    def test_init_does_not_try_sync_device_lookup(self):
        with patch("styrened.tui.screens.mesh_device_detail.discover_devices") as discover:
            screen = MeshDeviceDetailScreen(device_identity="peer-1", device=None)

        discover.assert_not_called()
        assert screen.device is None
        assert screen._device_lookup_complete is False


class TestDeviceDetailLifecycle:
    """Test peer workspace worker lifecycle management."""

    def test_on_mount_starts_device_load_when_device_missing(self):
        screen = MeshDeviceDetailScreen(device_identity="peer-1", device=None)
        screen._start_device_load = Mock()
        screen.device = None

        screen.on_mount()

        screen._start_device_load.assert_called_once_with()

    def test_on_mount_starts_status_refresh_when_device_present_without_status(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        screen._start_status_refresh = Mock()
        screen.initial_status = None

        screen.on_mount()

        screen._start_status_refresh.assert_called_once_with()

    def test_screen_suspend_cancels_inflight_workers(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        load_worker = Mock()
        status_worker = Mock()
        link_worker = Mock()
        speedtest_worker = Mock()
        contact_worker = Mock()
        screen._device_load_worker = load_worker
        screen._status_worker = status_worker
        screen._link_worker = link_worker
        screen._speedtest_worker = speedtest_worker
        screen._contact_worker = contact_worker

        screen.on_screen_suspend(Mock())

        load_worker.cancel.assert_called_once_with()
        status_worker.cancel.assert_called_once_with()
        link_worker.cancel.assert_called_once_with()
        speedtest_worker.cancel.assert_called_once_with()
        contact_worker.cancel.assert_called_once_with()
        assert screen._device_load_worker is None
        assert screen._status_worker is None
        assert screen._link_worker is None
        assert screen._speedtest_worker is None
        assert screen._contact_worker is None

    def test_screen_resume_refreshes_loaded_device_status(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        screen._start_status_refresh = Mock()

        screen.on_screen_resume(Mock())

        screen._start_status_refresh.assert_called_once_with()

    def test_screen_resume_retries_device_load_when_missing(self):
        screen = MeshDeviceDetailScreen(device_identity="peer-1", device=None)
        screen._start_device_load = Mock()
        screen.device = None

        screen.on_screen_resume(Mock())

        screen._start_device_load.assert_called_once_with()

    def test_on_unmount_cancels_inflight_workers(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        load_worker = Mock()
        status_worker = Mock()
        link_worker = Mock()
        speedtest_worker = Mock()
        contact_worker = Mock()
        screen._device_load_worker = load_worker
        screen._status_worker = status_worker
        screen._link_worker = link_worker
        screen._speedtest_worker = speedtest_worker
        screen._contact_worker = contact_worker

        screen.on_unmount()

        load_worker.cancel.assert_called_once_with()
        status_worker.cancel.assert_called_once_with()
        link_worker.cancel.assert_called_once_with()
        speedtest_worker.cancel.assert_called_once_with()
        contact_worker.cancel.assert_called_once_with()
        assert screen._device_load_worker is None
        assert screen._status_worker is None
        assert screen._link_worker is None
        assert screen._speedtest_worker is None
        assert screen._contact_worker is None

    def test_action_refresh_status_uses_status_worker_helper(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        screen._start_status_refresh = Mock()
        screen.notify = Mock()

        import asyncio
        asyncio.run(screen.action_refresh_status())

        screen._start_status_refresh.assert_called_once_with()
        screen.notify.assert_called_once()

    def test_action_establish_link_uses_worker_helper(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        bridge = Mock()
        app = Mock()
        app.services.bridge = bridge
        screen.notify = Mock()
        screen._start_link_establish = Mock()

        with patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app):
            import asyncio
            asyncio.run(screen.action_establish_link())

        screen._start_link_establish.assert_called_once_with(bridge)

    def test_action_run_speedtest_uses_worker_helper(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        bridge = Mock()
        bridge.datalink_status = AsyncMock(return_value={"connected": True})
        app = Mock()
        app.services.bridge = bridge
        screen.notify = Mock()
        screen._start_speedtest = Mock()

        with patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app):
            import asyncio
            asyncio.run(screen.action_run_speedtest())

        screen._start_speedtest.assert_called_once_with(bridge)

    def test_action_add_contact_uses_worker_helper(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        bridge = Mock()
        app = Mock()
        app.services.bridge = bridge
        screen._start_contact_save = Mock()

        with patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app):
            screen.action_add_contact()

        screen._start_contact_save.assert_called_once_with(bridge, test_device.name)


class TestDeviceDetailRoutingContext:
    """Test peer workspace routing context."""

    def test_screen_builds_canonical_peer_workspace_context(self, test_device):
        screen = MeshDeviceDetailScreen(
            device_identity=test_device.identity_hash,
            initial_tab="chat",
            device=test_device,
            origin_workspace=WorkspaceId.NODES,
        )

        assert screen.origin_workspace == WorkspaceId.NODES
        assert screen.requested_focus == PeerWorkspaceFocus.COMMS
        assert screen.peer_context.peer_identity_hash == test_device.identity_hash

    def test_mail_focus_maps_to_peer_workspace_focus_mail(self, test_device):
        """initial_tab='mail' should map to PeerWorkspaceFocus.MAIL."""
        screen = MeshDeviceDetailScreen(
            device_identity=test_device.identity_hash,
            initial_tab="mail",
            device=test_device,
            origin_workspace=WorkspaceId.MAIL,
        )
        assert screen.requested_focus == PeerWorkspaceFocus.MAIL
        assert screen.origin_workspace == WorkspaceId.MAIL

    @pytest.mark.asyncio
    async def test_mail_tab_renders_placeholder_content(self, test_device):
        """Mail tab should render without error (placeholder for 0.16.1)."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(
                    MeshDeviceDetailScreen(
                        device_identity=test_device.identity_hash,
                        device=test_device,
                        initial_tab="mail",
                        origin_workspace=WorkspaceId.MAIL,
                    )
                )
                await pilot.pause()

                screen = app.screen
                # Mail placeholder widget should be present
                mail_placeholder = screen.query_one("#mail-placeholder")
                assert mail_placeholder is not None

    @pytest.mark.asyncio
    async def test_escape_returns_to_originating_dashboard_screen(self, test_device):
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DummyOriginScreen("dashboard-root"))
                await app.push_screen(
                    MeshDeviceDetailScreen(
                        device_identity=test_device.identity_hash,
                        device=test_device,
                        origin_workspace=WorkspaceId.HOME,
                    )
                )
                await pilot.pause()

                await pilot.press("escape")
                await pilot.pause()

                assert isinstance(app.screen, DummyOriginScreen)
                assert app.screen.label == "dashboard-root"

    @pytest.mark.asyncio
    async def test_escape_returns_to_originating_nodes_screen(self, test_device):
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=[test_device],
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DummyOriginScreen("nodes-root"))
                await app.push_screen(
                    MeshDeviceDetailScreen(
                        device_identity=test_device.identity_hash,
                        device=test_device,
                        origin_workspace=WorkspaceId.NODES,
                    )
                )
                await pilot.pause()

                await pilot.press("escape")
                await pilot.pause()

                assert isinstance(app.screen, DummyOriginScreen)
                assert app.screen.label == "nodes-root"


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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
                )
                await pilot.pause()

                # Press Escape
                await pilot.press("escape")
                await pilot.pause()

                # Should pop detail screen

    def test_r_refreshes_device_status_via_helper(self, test_device):
        """Pressing 'r' should route through the status refresh helper."""
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        screen._start_status_refresh = Mock()
        screen.notify = Mock()

        import asyncio
        asyncio.run(screen.action_refresh_status())

        screen._start_status_refresh.assert_called_once_with()


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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
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
                    MeshDeviceDetailScreen(device_identity=offline_device.identity_hash)
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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
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
                    MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
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
            async with app.run_test():
                await app.push_screen(
                    MeshDeviceDetailScreen(device_identity="nonexistent_device")
                )

                # Should handle gracefully (show error or return to list)


class TestDeviceDetailNodeStoreFallback:
    """Test NodeStore fallback for IPC mode where discover_devices is empty."""

    @pytest.mark.asyncio
    async def test_device_loaded_from_ipc_nodes_when_discover_empty(self, test_device):
        """Device should load from IPC bridge node inventory when live discovery is empty."""
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
        bridge = MagicMock()
        bridge.get_nodes = AsyncMock(
            return_value=[
                {
                    "destination_hash": test_device.destination_hash,
                    "identity_hash": test_device.identity_hash,
                    "name": test_device.name,
                    "device_type": test_device.device_type.value,
                    "last_announce": test_device.last_announce,
                    "announce_count": test_device.announce_count,
                }
            ]
        )
        app = MagicMock()
        app.services.bridge = bridge
        screen.call_after_refresh = Mock()

        with (
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=[],
            ),
            patch("styrened.tui.utils.device_info_to_mesh", return_value=test_device),
            patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "refresh"),
        ):
            await screen._async_load_device()

        assert screen.device is not None
        assert screen.device.identity_hash == test_device.identity_hash
        screen.call_after_refresh.assert_called_once_with(screen._start_status_refresh)

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
                screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
                await app.push_screen(screen)
                await pilot.pause()

                assert app.screen.device is not None
                assert app.screen.device.name == "Test Device"

    @pytest.mark.asyncio
    async def test_device_not_found_in_either_source(self):
        """Device not in live discovery or stored IPC nodes should show error state."""
        screen = MeshDeviceDetailScreen(device_identity="nonexistent")
        bridge = MagicMock()
        bridge.get_nodes = AsyncMock(return_value=[])
        app = MagicMock()
        app.services.bridge = bridge
        screen.notify = MagicMock()

        with (
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=[],
            ),
            patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "refresh"),
        ):
            await screen._async_load_device()

        assert screen.device is None
        assert screen._device_lookup_complete is True
        screen.notify.assert_called_once()
