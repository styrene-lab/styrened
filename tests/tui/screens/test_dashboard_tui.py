"""Comprehensive TUI tests for Dashboard (Home) screen — COP layout.

Home owns: compact status bar, node summary table, activity feed.
Peer browsing (MeshDeviceTree) belongs in ExplorationScreen (Nodes workspace).
"""
from __future__ import annotations

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
    """Test Home screen widget composition — COP layout."""

    @pytest.mark.asyncio
    async def test_home_compose_creates_cop_widgets(self):
        """Home compose() should create HomeStatusBar, HomeNodeSummaryTable, and CopActivitySummary."""
        from styrened.tui.widgets.cop_activity_summary import CopActivitySummary
        from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable
        from styrened.tui.widgets.home_status_bar import HomeStatusBar

        app = StyreneApp()
        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            screen = app.screen
            assert isinstance(screen, DashboardScreen)
            # COP panels are present
            assert screen.query_one("#status-bar-panel") is not None
            assert screen.query_one("#nodes-panel") is not None
            assert screen.query_one("#activity-panel") is not None
            # Widgets inside panels
            assert isinstance(screen.query_one(HomeStatusBar), HomeStatusBar)
            assert isinstance(screen.query_one(HomeNodeSummaryTable), HomeNodeSummaryTable)
            assert isinstance(screen.query_one(CopActivitySummary), CopActivitySummary)

    @pytest.mark.asyncio
    async def test_home_has_no_peer_tree(self):
        """Home must NOT render a peer-browsing tree or NodeInfoPanel."""
        from textual.css.query import NoMatches

        app = StyreneApp()
        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            screen = app.screen
            with pytest.raises(NoMatches):
                screen.query_one("#mesh-device-tree")
            # NodeInfoPanel should NOT be on Home (lives on LocalDashboard)
            with pytest.raises(NoMatches):
                from styrened.tui.widgets.node_info_panel import NodeInfoPanel
                screen.query_one(NodeInfoPanel)

    @pytest.mark.asyncio
    async def test_home_panels_have_correct_titles(self):
        """Home panels should use COP titles: STATUS, NODES, ACTIVITY."""
        app = StyreneApp()
        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            status_panel = app.screen.query_one("#status-bar-panel")
            nodes_panel = app.screen.query_one("#nodes-panel")
            activity_panel = app.screen.query_one("#activity-panel")
            # StyrenePanel uses Textual's border_title (not _panel_title)
            assert status_panel.border_title == "STATUS"
            assert nodes_panel.border_title == "NODES"
            assert activity_panel.border_title == "ACTIVITY"

    @pytest.mark.asyncio
    async def test_home_cop_layout_order(self):
        """Status bar before node table before activity feed."""
        app = StyreneApp()
        async with app.run_test() as pilot:
            await app.push_screen(DashboardScreen())
            await pilot.pause()

            from styrened.tui.widgets.highlighted_panel import HighlightedPanel
            panels = list(app.screen.query(HighlightedPanel))
            ids = [p.id for p in panels]
            assert ids == ["status-bar-panel", "nodes-panel", "activity-panel"]


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
        app_mock = MagicMock()
        screen = DashboardScreen()

        with patch.object(DashboardScreen, "app", new_callable=PropertyMock, return_value=app_mock):
            screen.action_open_exploration()

        app_mock.action_open_nodes.assert_called_once_with()


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

        with patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=None):
            screen.on_screen_resume(MagicMock())

        screen._hub_retry_timer.resume.assert_called_once_with()

    def test_screen_resume_restarts_activity_worker_when_ipc_available(self):
        screen = DashboardScreen()
        screen._hub_retry_timer = Mock()
        screen.query = Mock(return_value=[])
        # on_screen_resume calls run_worker 3 times: status, adapters, activity
        worker_results = [Mock(), Mock(), Mock()]
        screen.run_worker = Mock(side_effect=worker_results)

        with (
            patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=Mock()),
            patch.object(DashboardScreen, "_fetch_daemon_status", new=lambda self: None),
            patch.object(DashboardScreen, "_fetch_adapter_state", new=lambda self: None),
            patch.object(DashboardScreen, "_subscribe_activity", new=lambda self: None),
        ):
            screen.on_screen_resume(MagicMock())

        assert screen.run_worker.call_count == 3
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


class TestDashboardStatusBarWiring:
    """Test that _fetch_daemon_status feeds HomeStatusBar correctly."""

    @pytest.mark.asyncio
    async def test_fetch_daemon_status_updates_status_bar(self):
        """Status bar should be updated with daemon state."""
        screen = DashboardScreen()
        bridge = MagicMock()
        status_bar = MagicMock()
        node_table = MagicMock()

        bridge.get_status = AsyncMock(return_value={
            "rns_initialized": True,
            "interfaces": [{"name": "tcp0"}, {"name": "auto0"}],
            "uptime": 3600,
            "transport_enabled": False,
            "propagation_enabled": False,
            "active_links": 2,
        })
        bridge.get_hub_status = AsyncMock(return_value={"status": "connected"})
        bridge.get_core_config = AsyncMock(return_value={})
        bridge.get_devices = AsyncMock(return_value=[
            {"device_type": "styrene_node", "identity_hash": "abc"},
            {"device_type": "lxmf_peer", "identity_hash": "def"},
        ])
        bridge.get_conversations = AsyncMock(return_value=[
            {"identity_hash": "abc", "unread_count": 3},
        ])

        def query_one_side_effect(widget_type):
            from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable
            from styrened.tui.widgets.home_status_bar import HomeStatusBar
            if widget_type is HomeStatusBar or widget_type == HomeStatusBar:
                return status_bar
            if widget_type is HomeNodeSummaryTable or widget_type == HomeNodeSummaryTable:
                return node_table
            return MagicMock()

        app = MagicMock()
        app.device_cache.get.return_value = [
            {"device_type": "styrene_node", "identity_hash": "abc", "destination_hash": "abc", "name": "Alpha", "last_announce": 1},
            {"device_type": "lxmf_peer", "identity_hash": "def", "destination_hash": "def", "name": "Bravo", "last_announce": 1},
        ]

        with (
            patch.object(DashboardScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=bridge),
            patch.object(screen, "query_one", side_effect=query_one_side_effect),
        ):
            await screen._fetch_daemon_status()

        assert status_bar.daemon_connected is True
        assert status_bar.rns_online is True
        assert status_bar.interface_count == 2
        assert status_bar.daemon_uptime == 3600.0
        assert status_bar.active_links == 2
        assert status_bar.unread_count == 3

    @pytest.mark.asyncio
    async def test_fetch_daemon_status_marks_disconnected_on_failure(self):
        """Status bar should show disconnected when bridge fails."""
        screen = DashboardScreen()
        bridge = MagicMock()
        status_bar = MagicMock()

        bridge.get_status = AsyncMock(side_effect=RuntimeError("boom"))
        bridge.get_hub_status = AsyncMock(return_value={})
        bridge.get_core_config = AsyncMock(return_value={})
        bridge.get_devices = AsyncMock(return_value=[])
        bridge.get_conversations = AsyncMock(return_value=[])

        with (
            patch.object(DashboardScreen, "_ipc_bridge", new_callable=PropertyMock, return_value=bridge),
            patch.object(screen, "query_one", return_value=status_bar),
        ):
            await screen._fetch_daemon_status()

        assert status_bar.daemon_connected is False


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

        screen.post_message = MagicMock()

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
        # add_ephemeral no longer called — routing goes through DaemonEvent → on_daemon_event
        activity_widget.add_ephemeral.assert_not_called()
        # DaemonEvent posted to the screen message pump for the EVENT_ACTIVITY item
        screen.post_message.assert_called_once()


class TestDashboardOverflowWiring:
    """Test Home overflow affordance → Nodes workspace navigation."""

    def test_overflow_selected_calls_open_exploration(self):
        """OverflowSelected event on the node table triggers action_open_exploration."""
        from styrened.tui.widgets.home_node_summary import HomeNodeSummaryTable

        screen = DashboardScreen()
        with patch.object(screen, "action_open_exploration") as mock_open:
            screen.on_home_node_summary_table_overflow_selected(
                HomeNodeSummaryTable.OverflowSelected()
            )
        mock_open.assert_called_once_with()


class TestDashboardAdapterWiring:
    """Test adapter_changed event wiring into DashboardScreen."""

    def _make_event(self, adapter_name: str, state: str, detail: str = ""):
        from styrened.tui.models.events import DaemonEvent
        return DaemonEvent(
            event_type="adapter_changed",
            action="adapter_changed",
            data={"adapter_name": adapter_name, "state": state, "detail": detail},
        )

    def test_adapter_changed_updates_adapter_status_bar(self):
        """adapter_changed event feeds AdapterStatusTracker and pushes snapshot to AdapterStatusBar."""
        from unittest.mock import MagicMock, patch

        from styrened.tui.models.adapter_status import AdapterDisplayState
        from styrened.tui.screens.dashboard import DashboardScreen
        from styrened.tui.widgets.adapter_status_bar import AdapterStatusBar

        screen = DashboardScreen()
        mock_bar = MagicMock(spec=AdapterStatusBar)
        mock_cop = MagicMock()

        def _query_one(widget_type):
            if widget_type is AdapterStatusBar:
                return mock_bar
            return mock_cop

        with patch.object(screen, "query_one", side_effect=_query_one):
            event = self._make_event("i2p", "ready")
            screen.on_daemon_event(event)

        mock_bar.apply_snapshot.assert_called_once()
        snap = mock_bar.apply_snapshot.call_args[0][0]
        assert len(snap.adapters) == 1
        assert snap.adapters[0].name == "i2p"
        assert snap.adapters[0].state == AdapterDisplayState.READY

    def test_ready_to_degraded_injects_anomaly_situation_line(self):
        """READY→DEGRADED transition should inject an ANOMALY situation line into COP feed."""
        from unittest.mock import MagicMock, patch

        from styrened.tui.models.cop_situation import SituationPriority
        from styrened.tui.screens.dashboard import DashboardScreen
        from styrened.tui.widgets.adapter_status_bar import AdapterStatusBar
        from styrened.tui.widgets.cop_activity_summary import CopActivitySummary

        screen = DashboardScreen()
        mock_bar = MagicMock(spec=AdapterStatusBar)
        mock_cop = MagicMock(spec=CopActivitySummary)

        def _query_one(widget_type):
            if widget_type is AdapterStatusBar:
                return mock_bar
            return mock_cop

        with patch.object(screen, "query_one", side_effect=_query_one):
            # First: establish READY state
            screen.on_daemon_event(self._make_event("i2p", "ready"))
            cop_calls_before = mock_cop.apply_snapshot.call_count
            # Now: transition to DEGRADED
            screen.on_daemon_event(self._make_event("i2p", "degraded"))

        # COP apply_snapshot should have been called again after the transition
        assert mock_cop.apply_snapshot.call_count > cop_calls_before
        # Check snapshot contains an anomaly line
        snap = mock_cop.apply_snapshot.call_args[0][0]
        anomaly_lines = [
            line for line in snap.lines
            if line.priority == SituationPriority.ANOMALY
        ]
        assert any("degraded" in line.message.lower() for line in anomaly_lines), (
            f"Expected anomaly line about degraded, got: {[line.message for line in snap.lines]}"
        )

    def test_warming_to_ready_injects_informational_situation_line(self):
        """WARMING→READY transition should inject an INFO situation line into COP feed."""
        from unittest.mock import MagicMock, patch

        from styrened.tui.models.cop_situation import SituationPriority
        from styrened.tui.screens.dashboard import DashboardScreen
        from styrened.tui.widgets.adapter_status_bar import AdapterStatusBar
        from styrened.tui.widgets.cop_activity_summary import CopActivitySummary

        screen = DashboardScreen()
        mock_bar = MagicMock(spec=AdapterStatusBar)
        mock_cop = MagicMock(spec=CopActivitySummary)

        def _query_one(widget_type):
            if widget_type is AdapterStatusBar:
                return mock_bar
            return mock_cop

        with patch.object(screen, "query_one", side_effect=_query_one):
            screen.on_daemon_event(self._make_event("ygg", "warming"))
            screen.on_daemon_event(self._make_event("ygg", "ready"))

        snap = mock_cop.apply_snapshot.call_args[0][0]
        info_lines = [
            line for line in snap.lines
            if line.priority == SituationPriority.INFO
        ]
        assert any(
            "ready" in line.message.lower() or "ygg" in line.message.lower()
            for line in info_lines
        ), (
            f"Expected info line about ready, got: {[line.message for line in snap.lines]}"
        )

    def test_disabled_to_probing_generates_no_situation_line(self):
        """DISABLED→PROBING transitions generate no situation line in COP feed."""
        from unittest.mock import MagicMock, patch

        from styrened.tui.screens.dashboard import DashboardScreen
        from styrened.tui.widgets.adapter_status_bar import AdapterStatusBar
        from styrened.tui.widgets.cop_activity_summary import CopActivitySummary

        screen = DashboardScreen()
        mock_bar = MagicMock(spec=AdapterStatusBar)
        mock_cop = MagicMock(spec=CopActivitySummary)

        def _query_one(widget_type):
            if widget_type is AdapterStatusBar:
                return mock_bar
            return mock_cop

        with patch.object(screen, "query_one", side_effect=_query_one):
            screen.on_daemon_event(self._make_event("i2p", "disabled"))
            mock_cop.apply_snapshot.reset_mock()
            screen.on_daemon_event(self._make_event("i2p", "probing"))

        # COP may be called, but the snapshot should have NO anomaly or info lines
        # from the adapter transition (DISABLED origin → no situation)
        if mock_cop.apply_snapshot.called:
            snap = mock_cop.apply_snapshot.call_args[0][0]
            adapter_lines = [
                line for line in snap.lines
                if "i2p" in line.message.lower()
            ]
            assert len(adapter_lines) == 0, (
                f"Expected no i2p situation lines, got: {[line.message for line in adapter_lines]}"
            )
