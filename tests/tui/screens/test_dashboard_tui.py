"""Comprehensive TUI tests for Dashboard (Home) screen.

Home owns: local node status, recent activity, and navigation to peer workspaces.
Peer browsing (MeshDeviceTree) belongs in ExplorationScreen (Nodes workspace).
"""
from __future__ import annotations


import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

import pytest

from styrened.ipc.protocol import IPCMessageType
from styrened.tui.app import StyreneApp
from styrened.tui.screens.dashboard import DashboardScreen


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
        patch("styrened.tui.screens.dashboard.start_discovery"),
    ):
        yield


class TestDashboardComposition:
    """Test Home screen widget composition — no peer tree."""

    @pytest.mark.asyncio
    async def test_home_compose_creates_status_and_activity_widgets(self):
        """Home compose() should create NodeInfoPanel and ActivityFeedWidget."""
        from styrened.tui.widgets.activity_feed import ActivityFeedWidget
        from styrened.tui.widgets.node_info_panel import NodeInfoPanel

        app = StyreneApp()
        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, DashboardScreen)
            # Status and activity panels are present
            assert screen.query_one("#node-info-panel") is not None
            assert screen.query_one("#activity-feed-panel") is not None

    @pytest.mark.asyncio
    async def test_home_has_no_peer_tree(self):
        """Home must NOT render a peer-browsing tree — that lives in Nodes."""
        from textual.css.query import NoMatches

        app = StyreneApp()
        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            screen = app.screen
            with pytest.raises(NoMatches):
                screen.query_one("#mesh-device-tree")

    @pytest.mark.asyncio
    async def test_home_panels_have_correct_titles(self):
        """Home panels should use Home-scope titles (no CURRENT NODES panel)."""
        app = StyreneApp()
        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            info_panel = app.screen.query_one("#node-info-panel")
            activity_panel = app.screen.query_one("#activity-feed-panel")
            assert getattr(info_panel, "_panel_title", None) == "HOME STATUS"
            assert getattr(activity_panel, "_panel_title", None) == "RECENT ACTIVITY"
            # CURRENT NODES panel must not be present
            from textual.css.query import NoMatches
            with pytest.raises(NoMatches):
                app.screen.query_one("#mesh-devices-panel")


class TestDashboardKeyboardBindings:
    """Test Home keyboard bindings."""

    @pytest.mark.asyncio
    async def test_refresh_key_binding_does_not_crash(self):
        """Pressing 'r' on Home should refresh without crashing."""
        app = StyreneApp()
        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            await pilot.press("r")
            await pilot.pause()
            # Still on dashboard, no crash
            assert isinstance(app.screen, DashboardScreen)

    @pytest.mark.asyncio
    async def test_provision_key_binding(self):
        """Pressing 'p' should open provision screen without crashing."""
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
    async def test_no_standalone_status_binding(self):
        """Home should not have standalone 's' (status) binding."""
        screen = DashboardScreen()
        s_bindings = [b for b in screen.BINDINGS if b.key == "s"]
        assert len(s_bindings) == 0, "Standalone 's' binding should be removed"

    @pytest.mark.asyncio
    async def test_no_enter_binding_for_tree(self):
        """Home should not have an 'enter' binding (no tree to select from)."""
        screen = DashboardScreen()
        enter_bindings = [b for b in screen.BINDINGS if b.key == "enter"]
        assert len(enter_bindings) == 0, "Enter binding belongs in Nodes, not Home"

    @pytest.mark.asyncio
    async def test_no_chat_binding_on_home(self):
        """Home should not have a 'c' (chat) binding — chat opens from Nodes."""
        screen = DashboardScreen()
        c_bindings = [b for b in screen.BINDINGS if b.key == "c"]
        assert len(c_bindings) == 0, "'c' chat binding belongs in Nodes, not Home"

    @pytest.mark.asyncio
    async def test_nodes_binding_exists(self):
        """Home should advertise 'n' to navigate to the Nodes workspace."""
        screen = DashboardScreen()
        n_bindings = [b for b in screen.BINDINGS if b.key == "n"]
        assert len(n_bindings) == 1
        assert n_bindings[0].action == "open_exploration"
        assert n_bindings[0].description == "Nodes"


class TestDashboardHomeRouting:
    """Test Home as entrypoint to other workspaces."""

    def test_open_exploration_delegates_to_app_nodes_action(self):
        """action_open_exploration() should delegate to app.action_open_nodes()."""
        app = MagicMock()
        screen = DashboardScreen()

        with patch.object(DashboardScreen, "app", new_callable=PropertyMock, return_value=app):
            screen.action_open_exploration()

        app.action_open_nodes.assert_called_once_with()


class TestDashboardTimerLifecycle:
    """Test Home timer lifecycle management."""

    def test_screen_suspend_pauses_hub_timer_and_cancels_activity(self):
        screen = DashboardScreen()
        screen._hub_retry_timer = Mock()
        activity_worker = Mock()
        screen._activity_worker = activity_worker

        screen.on_screen_suspend(MagicMock())

        screen._hub_retry_timer.pause.assert_called_once_with()
        activity_worker.cancel.assert_called_once_with()
        assert screen._activity_worker is None

    def test_screen_resume_resumes_hub_timer(self):
        screen = DashboardScreen()
        screen._hub_retry_timer = Mock()
        screen.query = Mock(return_value=[])
        screen.query_one = Mock(return_value=MagicMock())

        with patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=None):
            screen.on_screen_resume(MagicMock())

        screen._hub_retry_timer.resume.assert_called_once_with()

    def test_screen_resume_restarts_activity_worker_when_ipc_available(self):
        screen = DashboardScreen()
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

    def test_on_unmount_stops_hub_timer_and_activity_worker(self):
        screen = DashboardScreen()
        hub_timer = Mock()
        activity_worker = Mock()
        screen._hub_retry_timer = hub_timer
        screen._activity_worker = activity_worker

        screen.on_unmount()

        hub_timer.stop.assert_called_once_with()
        activity_worker.cancel.assert_called_once_with()
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
            patch(
                "styrened.tui.screens.dashboard.build_home_node_local_state",
                return_value=local_snapshot,
            ) as build_local,
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
            patch(
                "styrened.tui.screens.dashboard.build_home_node_info_state",
                return_value=MagicMock(),
            ) as build_snapshot,
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
