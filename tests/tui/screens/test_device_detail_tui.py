"""Focused tests for MeshDeviceDetailScreen."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, PropertyMock, patch

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.rpc.messages import StatusResponse
from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen
from styrened.ui_state import PeerWorkspaceFocus, WorkspaceId


@pytest.fixture
def test_device():
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
    def test_device_detail_accepts_initial_tab_and_origin(self, test_device):
        screen = MeshDeviceDetailScreen(
            device_identity=test_device.identity_hash,
            initial_tab="chat",
            device=test_device,
            origin_workspace=WorkspaceId.NODES,
        )
        assert screen.initial_tab == "chat"
        assert screen.origin_workspace == WorkspaceId.NODES

    def test_mail_focus_maps_to_peer_workspace_focus_mail(self, test_device):
        screen = MeshDeviceDetailScreen(
            device_identity=test_device.identity_hash,
            initial_tab="mail",
            device=test_device,
            origin_workspace=WorkspaceId.MAIL,
        )
        assert screen.requested_focus == PeerWorkspaceFocus.MAIL
        assert screen.origin_workspace == WorkspaceId.MAIL

    def test_chat_focus_maps_to_peer_workspace_focus_comms(self, test_device):
        screen = MeshDeviceDetailScreen(
            device_identity=test_device.identity_hash,
            initial_tab="chat",
            device=test_device,
            origin_workspace=WorkspaceId.NODES,
        )
        assert screen.requested_focus == PeerWorkspaceFocus.COMMS


class TestDeviceDetailRPCActions:
    @pytest.mark.asyncio
    async def test_auto_fetch_status_uses_bridge_status_query(self, test_device):
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
        status_widget = Mock(link_info=None, status=None, loading=False, error=None)
        app = Mock()
        app.services.bridge = mock_bridge

        with (
            patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "query_one", return_value=status_widget),
        ):
            await screen._auto_fetch_status()

        mock_bridge.query_device_status.assert_awaited_once()
        assert status_widget.status == mock_response


class TestDeviceDetailLoadingState:
    def test_init_does_not_try_sync_device_lookup(self):
        with patch("styrened.tui.screens.mesh_device_detail.discover_devices") as discover:
            screen = MeshDeviceDetailScreen(device_identity="peer-1", device=None)

        discover.assert_not_called()
        assert screen.device is None
        assert screen._device_lookup_complete is False


class TestDeviceDetailLifecycle:
    def test_on_mount_starts_device_load_when_device_missing(self):
        screen = MeshDeviceDetailScreen(device_identity="peer-1", device=None)
        screen._start_device_load = Mock()

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
        for attr in ("_device_load_worker", "_status_worker", "_link_worker", "_speedtest_worker", "_contact_worker"):
            setattr(screen, attr, Mock())

        screen.on_screen_suspend(Mock())

        for attr in ("_device_load_worker", "_status_worker", "_link_worker", "_speedtest_worker", "_contact_worker"):
            assert getattr(screen, attr) is None

    def test_screen_resume_refreshes_loaded_device_status(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        screen._start_status_refresh = Mock()

        screen.on_screen_resume(Mock())

        screen._start_status_refresh.assert_called_once_with()

    def test_screen_resume_retries_device_load_when_missing(self):
        screen = MeshDeviceDetailScreen(device_identity="peer-1", device=None)
        screen._start_device_load = Mock()

        screen.on_screen_resume(Mock())

        screen._start_device_load.assert_called_once_with()

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

    def test_go_back_pops_current_peer_workspace(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash, device=test_device)
        fake_app = Mock()
        with patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=fake_app):
            screen.action_go_back()
        fake_app.pop_screen.assert_called_once_with()


class TestDeviceDetailNodeStoreFallback:
    @pytest.mark.asyncio
    async def test_device_loaded_from_ipc_nodes_when_live_cache_empty(self, test_device):
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
        app.device_cache.get.return_value = []
        screen.call_after_refresh = Mock()

        with (
            patch("styrened.tui.utils.device_info_to_mesh", return_value=test_device),
            patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "refresh"),
        ):
            await screen._async_load_device()

        assert screen.device is not None
        assert screen.device.identity_hash == test_device.identity_hash
        screen.call_after_refresh.assert_called_once_with(screen._start_status_refresh)

    @pytest.mark.asyncio
    async def test_live_cache_takes_precedence_over_ipc_nodes(self, test_device):
        screen = MeshDeviceDetailScreen(device_identity=test_device.identity_hash)
        live_device = test_device
        stale_device = {
            "destination_hash": test_device.destination_hash,
            "identity_hash": test_device.identity_hash,
            "name": "Stale Name",
            "device_type": test_device.device_type.value,
            "last_announce": test_device.last_announce - 1000,
            "announce_count": 1,
        }
        bridge = MagicMock()
        bridge.get_nodes = AsyncMock(return_value=[stale_device])
        app = MagicMock()
        app.services.bridge = bridge
        app.device_cache.get.return_value = [live_device]
        screen.call_after_refresh = Mock()

        with (
            patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "refresh"),
        ):
            await screen._async_load_device()

        assert screen.device is not None
        assert screen.device.name == "Test Device"
        bridge.get_nodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_device_not_found_in_either_source_sets_error_state(self):
        screen = MeshDeviceDetailScreen(device_identity="nonexistent")
        bridge = MagicMock()
        bridge.get_nodes = AsyncMock(return_value=[])
        app = MagicMock()
        app.services.bridge = bridge
        app.device_cache.get.return_value = []
        screen.notify = MagicMock()

        with (
            patch.object(MeshDeviceDetailScreen, "app", new_callable=PropertyMock, return_value=app),
            patch.object(screen, "refresh"),
        ):
            await screen._async_load_device()

        assert screen.device is None
        assert screen._device_lookup_complete is True
        screen.notify.assert_called_once()
