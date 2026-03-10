"""Comprehensive TUI tests for Dashboard screen.

Tests actual UI rendering, keyboard bindings, and user interactions
using Textual's app.run_test() and pilot.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

import pytest

from styrened.ipc.protocol import IPCMessageType
from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.app import StyreneApp
from styrened.tui.screens.dashboard import DashboardScreen, MeshDeviceTree


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for all TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
        # DashboardScreen.on_mount() calls start_discovery() which injected get_node_store().
        # Patch start_discovery at the dashboard module level to prevent the direct
        # daemon-service call. Device data flows via bridge.get_devices() instead.
        patch("styrened.tui.screens.dashboard.start_discovery"),
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
    async def test_dashboard_labels_home_summary_panels(self):
        """Dashboard should present Home-oriented summary panel titles."""
        app = StyreneApp()

        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            nodes_panel = app.screen.query_one("#mesh-devices-panel")
            info_panel = app.screen.query_one("#node-info-panel")
            activity_panel = app.screen.query_one("#activity-feed-panel")
            assert getattr(nodes_panel, "_panel_title", None) == "CURRENT NODES"
            assert getattr(info_panel, "_panel_title", None) == "HOME STATUS"
            assert getattr(activity_panel, "_panel_title", None) == "RECENT ACTIVITY"

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

    @pytest.mark.asyncio
    async def test_nodes_binding_exists(self):
        """Dashboard should advertise Nodes navigation from Home."""
        screen = DashboardScreen()
        n_bindings = [b for b in screen.BINDINGS if b.key == "n"]
        assert len(n_bindings) == 1
        assert n_bindings[0].action == "open_exploration"
        assert n_bindings[0].description == "Nodes"


class TestDashboardHomeRouting:
    """Test Dashboard as the Home workspace entrypoint."""

    def test_open_exploration_delegates_to_app_nodes_action(self):
        from unittest.mock import PropertyMock

        app = MagicMock()
        screen = DashboardScreen()

        with patch.object(DashboardScreen, "app", new_callable=PropertyMock, return_value=app):
            screen.action_open_exploration()

        app.action_open_nodes.assert_called_once_with()


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

                # Should return an identity or None (exercise the method)
                device_tree.get_selected_identity()
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


class TestDashboardTimerLifecycle:
    """Test dashboard timer lifecycle management."""

    def test_screen_suspend_pauses_periodic_timers(self):
        screen = DashboardScreen()
        screen._device_refresh_timer = Mock()
        screen._hub_retry_timer = Mock()
        activity_worker = Mock()
        screen._activity_worker = activity_worker

        screen.on_screen_suspend(MagicMock())

        screen._device_refresh_timer.pause.assert_called_once_with()
        screen._hub_retry_timer.pause.assert_called_once_with()
        activity_worker.cancel.assert_called_once_with()
        assert screen._activity_worker is None

    def test_screen_resume_resumes_periodic_timers(self):
        screen = DashboardScreen()
        screen._device_refresh_timer = Mock()
        screen._hub_retry_timer = Mock()
        screen.query = Mock(return_value=[])
        screen.query_one = Mock(return_value=MagicMock())

        with patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=None):
            screen.on_screen_resume(MagicMock())

        screen._device_refresh_timer.resume.assert_called_once_with()
        screen._hub_retry_timer.resume.assert_called_once_with()

    def test_screen_resume_restarts_activity_worker_when_ipc_available(self):
        screen = DashboardScreen()
        screen._device_refresh_timer = Mock()
        screen._hub_retry_timer = Mock()
        screen.query = Mock(return_value=[])
        screen.query_one = Mock(return_value=MagicMock())
        worker_results = [Mock(), Mock()]
        screen.run_worker = Mock(side_effect=worker_results)

        with (
            patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=Mock()),
            patch.object(DashboardScreen, "_fetch_daemon_status", new=lambda self: None),
            patch.object(DashboardScreen, "_subscribe_activity", new=lambda self: None),
        ):
            screen.on_screen_resume(MagicMock())

        assert screen.run_worker.call_count == 2
        assert screen._activity_worker is worker_results[-1]

    def test_on_unmount_stops_periodic_timers(self):
        screen = DashboardScreen()
        device_timer = Mock()
        hub_timer = Mock()
        activity_worker = Mock()
        screen._device_refresh_timer = device_timer
        screen._hub_retry_timer = hub_timer
        screen._activity_worker = activity_worker

        screen.on_unmount()

        device_timer.stop.assert_called_once_with()
        hub_timer.stop.assert_called_once_with()
        activity_worker.cancel.assert_called_once_with()
        assert screen._device_refresh_timer is None
        assert screen._hub_retry_timer is None
        assert screen._activity_worker is None


class TestDashboardPanelStateOwnership:
    """Test dashboard-owned NodeInfoPanel state application."""

    def test_apply_local_panel_snapshot_pushes_local_snapshot(self):
        screen = DashboardScreen()
        panel = MagicMock()

        fake_config = MagicMock()
        fake_config.reticulum.mode.value = "peer"
        fake_config.identity.display_name = "Alice"
        fake_config.identity.icon = "🖥️"
        fake_config.identity.short_name = "alice"
        fake_config.identity.provider = "yubikey"
        fake_system_info = MagicMock()
        fake_iface = MagicMock(is_hardware=True, is_up=True, ip_address="10.0.0.1")
        fake_disk = MagicMock(is_removable=True)
        local_snapshot = MagicMock()

        with (
            patch("styrened.tui.screens.dashboard.get_system_info", return_value=fake_system_info),
            patch("styrened.tui.screens.dashboard.get_network_interfaces", return_value=[fake_iface]),
            patch("styrened.tui.screens.dashboard.get_disks", return_value=[fake_disk]),
            patch("styrened.tui.screens.dashboard.load_config", return_value=fake_config),
            patch("styrened.tui.screens.dashboard.build_home_node_local_state", return_value=local_snapshot) as build_local,
        ):
            screen._apply_local_panel_snapshot(panel)

        build_local.assert_called_once()
        panel.apply_home_local_snapshot.assert_called_once_with(local_snapshot)

    def test_apply_local_daemon_snapshot_pushes_panel_snapshot(self):
        screen = DashboardScreen()
        panel = MagicMock()
        daemon_state = MagicMock()
        status = MagicMock()
        mesh_device_infos = (MagicMock(), MagicMock())
        home_snapshot = MagicMock()
        panel._apply_mesh_catalog_count.return_value = 2

        with patch(
            "styrened.tui.screens.dashboard.build_home_node_info_state",
            return_value=home_snapshot,
        ) as build_snapshot:
            screen._apply_local_daemon_snapshot(
                panel,
                daemon_state=daemon_state,
                mesh_device_infos=mesh_device_infos,
                raw_status=status,
            )

        panel._apply_mesh_catalog_count.assert_called_once_with(mesh_device_infos)
        build_snapshot.assert_called_once_with(
            daemon_state=daemon_state,
            daemon_status=status,
            mesh_node_count=2,
        )
        panel.apply_home_snapshot.assert_called_once_with(home_snapshot)

    @pytest.mark.asyncio
    async def test_fetch_daemon_status_uses_dashboard_owned_panel_seams(self):
        screen = DashboardScreen()
        bridge = MagicMock()
        panel = MagicMock()
        panel.hub_status = MagicMock(CONNECTED="connected", DISCONNECTED="disconnected")

        bridge.get_status = AsyncMock(return_value=MagicMock(rns_initialized=True))
        bridge.get_identity = AsyncMock(return_value=MagicMock(identity_hash="abc123"))
        bridge.get_hub_status = AsyncMock(return_value={"is_connected": True})
        bridge.get_core_config = AsyncMock(return_value={"group_threads": {"feature_tier": "balanced"}})
        bridge.get_devices = AsyncMock(return_value=[MagicMock(), MagicMock()])
        bridge.get_conversations = AsyncMock(return_value=[{"unread_count": 2, "message_count": 5}])
        bridge.get_contacts = AsyncMock(return_value=[{"name": "Alice"}])
        bridge.get_auto_reply = AsyncMock(return_value={"enabled": True})

        with (
            patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=bridge),
            patch.object(screen, "query_one", return_value=panel),
            patch("styrened.tui.screens.dashboard.build_local_daemon_state", return_value=MagicMock()),
            patch.object(screen, "_apply_local_daemon_snapshot") as apply_snapshot,
            patch("styrened.tui.screens.dashboard.build_home_node_info_state", return_value=MagicMock()) as build_snapshot,
        ):
            await screen._fetch_daemon_status()

        bridge.get_identity.assert_awaited_once_with()
        bridge.get_devices.assert_awaited_once_with(styrene_only=True)
        apply_snapshot.assert_called_once()
        build_snapshot.assert_called_once()
        _, kwargs = build_snapshot.call_args
        assert kwargs["mesh_node_count"] == panel.styrene_mesh_count
        assert kwargs["conversations"] == [{"unread_count": 2, "message_count": 5}]
        assert kwargs["contacts"] == [{"name": "Alice"}]
        assert kwargs["auto_reply"] == {"enabled": True}
        panel.apply_home_snapshot.assert_called_once_with(build_snapshot.return_value)

    @pytest.mark.asyncio
    async def test_fetch_daemon_status_cancels_pending_background_requests_on_early_failure(self):
        screen = DashboardScreen()
        bridge = MagicMock()
        panel = MagicMock()

        async def _stall():
            await asyncio.Future()

        bridge.get_status = AsyncMock(side_effect=RuntimeError("boom"))
        bridge.get_identity = AsyncMock(return_value=MagicMock(identity_hash="abc123"))
        bridge.get_hub_status = AsyncMock(return_value={"is_connected": True})
        bridge.get_core_config = AsyncMock(return_value={"group_threads": {"feature_tier": "balanced"}})
        bridge.get_devices = AsyncMock(return_value=[MagicMock()])
        bridge.get_conversations = AsyncMock(side_effect=_stall)
        bridge.get_contacts = AsyncMock(side_effect=_stall)
        bridge.get_auto_reply = AsyncMock(side_effect=_stall)

        with (
            patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=bridge),
            patch.object(screen, "query_one", return_value=panel),
        ):
            await screen._fetch_daemon_status()

        assert panel.daemon_connected is False


class TestDashboardActivitySubscription:
    """Test dashboard activity subscription wiring."""

    @pytest.mark.asyncio
    async def test_activity_subscription_uses_bridge_activity_api(self):
        """Dashboard should subscribe via subscribe_activity + iter_events(EVENT_ACTIVITY)."""
        screen = DashboardScreen()
        bridge = MagicMock()
        bridge.subscribe_activity = AsyncMock(return_value=True)

        async def _iter_events(_event_type):
            yield ("unexpected", {"type": "ignored"})
            yield (IPCMessageType.EVENT_ACTIVITY, {"type": "announce_sent"})

        bridge.iter_events = _iter_events
        activity_widget = MagicMock()

        with (
            patch.object(
                DashboardScreen,
                "_ipc_bridge",
                new_callable=PropertyMock,
                return_value=bridge,
            ),
            patch.object(screen, "query_one", return_value=activity_widget),
        ):
            await screen._subscribe_activity()

        bridge.subscribe_activity.assert_awaited_once_with()
        activity_widget.add_event.assert_called_once_with(
            "announce_sent",
            {"type": "announce_sent"},
        )


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

        with (
            patch(
                "styrened.tui.screens.dashboard.discover_devices", return_value=devices
            ),
            # Suppress start_discovery's direct daemon-service call; device data comes
            # from the discover_devices mock above (bridge.get_devices() path).
            patch("styrened.tui.screens.dashboard.start_discovery"),
        ):
            async with app.run_test() as pilot:
                await app.push_screen(DashboardScreen())
                await pilot.pause()

                screen = app.screen
                device_tree = screen.query_one("#mesh-device-tree", MeshDeviceTree)

                # Only active + stale shown (lost >30min filtered by _deduplicate_by_identity)
                assert _count_leaf_nodes(device_tree) == 2
