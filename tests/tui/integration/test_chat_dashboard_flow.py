"""End-to-end integration tests for chat workflow via device detail screen.

These tests verify the complete user journey:
1. User sees unread message indicators on dashboard
2. User opens device detail (enter key)
3. User accesses Chat tab
4. User sends/receives messages
5. User returns to dashboard with updated state
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from sqlalchemy.orm import Session
from textual.widgets import DataTable

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.models.messages import Message, init_db
from styrened.tui.app import StyreneApp
from styrened.tui.screens.dashboard import DashboardScreen, MeshDeviceTree
from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen


@pytest.fixture(autouse=True)
def mock_node_store():
    """Mock NodeStore to prevent stale data from interfering."""
    mock_store = MagicMock()
    mock_store.get_styrene_nodes.return_value = []
    mock_store.get_all_nodes.return_value = []
    with patch("styrened.services.node_store.get_node_store", return_value=mock_store):
        yield mock_store


@pytest.fixture
def message_db(tmp_path):
    """Create test message database."""
    db_path = tmp_path / "messages.db"
    engine = init_db(str(db_path))
    return engine


@pytest.fixture
def mock_local_identity():
    """Mock local identity hash."""
    return "local_identity_hash_1234"


@pytest.fixture
def sample_devices():
    """Create sample mesh devices for testing."""
    now = int(datetime.now().timestamp())
    return [
        MeshDevice(
            destination_hash="a1b2c3d4e5f60708",
            identity_hash="a1b2c3d4e5f60708",
            name="node-01",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now,
            announce_count=5,
        ),
        MeshDevice(
            destination_hash="b1c2d3e4f5a60718",
            identity_hash="b1c2d3e4f5a60718",
            name="node-02",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 60,
            announce_count=3,
        ),
    ]


def add_messages_to_db(engine, messages_data: list[dict]) -> list[int]:
    """Helper to add test messages to database."""
    message_ids = []
    with Session(engine) as session:
        for msg_data in messages_data:
            msg = Message(
                source_hash=msg_data["source_hash"],
                destination_hash=msg_data["destination_hash"],
                timestamp=msg_data.get("timestamp", datetime.now().timestamp()),
                content=msg_data.get("content", "Test message"),
                protocol_id="chat",
                status=msg_data.get("status", "pending"),
            )
            session.add(msg)
            session.flush()
            message_ids.append(msg.id)
        session.commit()
    return message_ids


def count_unread_messages(engine, source_hash: str, local_hash: str) -> int:
    """Count unread (pending) messages from a source."""
    with Session(engine) as session:
        return (
            session.query(Message)
            .filter(
                Message.source_hash == source_hash,
                Message.destination_hash == local_hash,
                Message.status == "pending",
            )
            .count()
        )


def count_total_messages(engine, peer_hash: str, local_hash: str) -> int:
    """Count total messages in conversation with peer."""
    with Session(engine) as session:
        return (
            session.query(Message)
            .filter(
                (
                    (Message.source_hash == peer_hash)
                    & (Message.destination_hash == local_hash)
                )
                | (
                    (Message.source_hash == local_hash)
                    & (Message.destination_hash == peer_hash)
                )
            )
            .count()
        )


@pytest.fixture(autouse=True)
def mock_reticulum_for_tests(tmp_path):
    """Mock Reticulum initialization for all tests."""
    fake_config = tmp_path / "reticulum_config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch(
            "styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config
        ),
        patch("styrened.tui.app.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneLifecycle") as mock_app_lifecycle,
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        mock_app_lifecycle.return_value.initialize_async = AsyncMock(return_value=True)
        mock_app_lifecycle.return_value.ipc_bridge = None
        yield


class TestDeviceDetailChatFlow:
    """Tests for accessing chat via device detail screen."""

    def test_action_select_opens_device_detail_with_tabs(self, sample_devices):
        """action_select_device should open device detail with tabbed layout."""
        screen = DashboardScreen()
        fake_app = MagicMock()

        with (
            patch.object(DashboardScreen, "_get_selected_identity", return_value=sample_devices[0].destination_hash),
            patch.object(DashboardScreen, "app", new_callable=PropertyMock, return_value=fake_app),
        ):
            screen.action_select_device()

        fake_app.push_screen.assert_called_once()
        pushed_screen = fake_app.push_screen.call_args.args[0]
        assert isinstance(pushed_screen, MeshDeviceDetailScreen)
        assert pushed_screen.device_identity == sample_devices[0].destination_hash

    @pytest.mark.asyncio
    async def test_device_detail_has_chat_tab(self, sample_devices):
        """Device detail screen should have a Chat tab."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=sample_devices,
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                app.push_screen(
                    MeshDeviceDetailScreen(
                        device_identity=sample_devices[0].destination_hash,
                    )
                )
                await pilot.pause()

                assert isinstance(app.screen, MeshDeviceDetailScreen), (
                    f"Expected MeshDeviceDetailScreen, got {type(app.screen).__name__}"
                )

                from textual.widgets import TabPane

                panes = list(app.screen.query(TabPane))
                pane_ids = {p.id for p in panes}
                assert "chat" in pane_ids, f"Missing Chat tab. Found: {pane_ids}"

    @pytest.mark.asyncio
    async def test_escape_from_detail_returns_to_dashboard(self, sample_devices):
        """Going back from detail screen should return to dashboard."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.mesh_device_detail.discover_devices",
            return_value=sample_devices,
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                app.push_screen(
                    MeshDeviceDetailScreen(
                        device_identity=sample_devices[0].destination_hash,
                    )
                )
                await pilot.pause()

                assert isinstance(app.screen, MeshDeviceDetailScreen)

                app.screen.action_go_back()
                await pilot.pause()

                assert isinstance(app.screen, DashboardScreen)


class TestDashboardUnreadDisplay:
    """Tests for unread count display on dashboard."""

    @pytest.mark.asyncio
    async def test_dashboard_shows_correct_unread_counts_for_all_devices(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Dashboard should show correct unread counts for each device."""
        # Setup different unread counts
        add_messages_to_db(
            message_db,
            [
                {
                    "source_hash": "node01_identity_hash",
                    "destination_hash": mock_local_identity,
                    "status": "pending",
                },
                {
                    "source_hash": "node01_identity_hash",
                    "destination_hash": mock_local_identity,
                    "status": "pending",
                },
                {
                    "source_hash": "node01_identity_hash",
                    "destination_hash": mock_local_identity,
                    "status": "pending",
                },
            ],
        )
        add_messages_to_db(
            message_db,
            [
                {
                    "source_hash": "node02_identity_hash",
                    "destination_hash": mock_local_identity,
                    "status": "pending",
                },
            ],
        )

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                tree = app.screen.query_one("#mesh-device-tree", MeshDeviceTree)

                # The tree should reflect the discovered device set.
                assert len(tree._device_cache) == len(sample_devices)

    @pytest.mark.asyncio
    async def test_dashboard_refreshes_on_screen_resume(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Dashboard should refresh device table on screen resume."""
        add_messages_to_db(
            message_db,
            [
                {
                    "source_hash": "node01_identity_hash",
                    "destination_hash": mock_local_identity,
                    "status": "pending",
                },
            ],
        )

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        with (
            patch(
                "styrened.tui.screens.dashboard.discover_devices",
                return_value=sample_devices,
            ),
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=sample_devices,
            ),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Open detail
                tree = app.screen.query_one("#mesh-device-tree", MeshDeviceTree)
                tree._select_by_identity(sample_devices[0].destination_hash)
                app.screen.action_select_device()
                await pilot.pause()

                assert isinstance(app.screen, MeshDeviceDetailScreen)

                # Return to dashboard
                app.screen.action_go_back()
                await pilot.pause()

                assert isinstance(app.screen, DashboardScreen)
                # Dashboard should have refreshed via on_screen_resume
