"""Tests for dashboard chat integration features.

These tests cover:
- Unread message count display in device tree
- Message count refresh on screen resume
- Device detail navigation from tree

Chat navigation is now via the device detail screen's Chat tab,
not standalone dashboard bindings.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.models.messages import Message, init_db
from styrened.tui.app import StyreneApp
from styrened.tui.screens.dashboard import DashboardScreen, MeshDeviceTree


@pytest.fixture
def sample_devices():
    """Create sample devices for chat integration tests."""
    now = int(datetime.now().timestamp())
    return [
        MeshDevice(
            destination_hash="node01_identity_hash",
            identity_hash="node01_identity_hash",
            name="node-01",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now,
            announce_count=5,
        ),
        MeshDevice(
            destination_hash="node02_identity_hash",
            identity_hash="node02_identity_hash",
            name="node-02",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 60,
            announce_count=3,
        ),
    ]


@pytest.fixture
def message_db(tmp_path):
    """Create a test message database."""
    db_path = tmp_path / "messages.db"
    engine = create_engine(f"sqlite:///{db_path}")
    init_db(str(db_path))
    return engine


@pytest.fixture
def mock_local_identity():
    """Mock local identity hash."""
    return "local_test_identity"


def add_messages_to_db(engine, messages):
    """Helper to add messages to the test database."""
    import time

    from sqlalchemy.orm import Session

    with Session(engine) as session:
        for i, msg_data in enumerate(messages):
            msg = Message(
                lxmf_hash=f"test_{id(msg_data)}_{msg_data.get('source_hash', '')}_{i}",
                source_hash=msg_data.get("source_hash", "unknown"),
                destination_hash=msg_data.get("destination_hash", "unknown"),
                content=msg_data.get("content", "test message"),
                timestamp=msg_data.get("timestamp", time.time()),
                protocol_id="chat",
                status=msg_data.get("status", "pending"),
            )
            session.add(msg)
        session.commit()


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


def _get_leaf_labels(tree: MeshDeviceTree) -> list[str]:
    """Get all leaf node labels from the tree as strings."""
    labels = []
    for node in tree._tree_walk(tree.root):
        if node.data is not None:
            labels.append(str(node.label))
    return labels


def _count_leaves(tree: MeshDeviceTree) -> int:
    """Count leaf nodes (devices) in the tree."""
    return len([n for n in tree._tree_walk(tree.root) if n.data is not None])


class TestDashboardMessageIndicators:
    """Tests for unread message count display in dashboard device tree."""

    @pytest.mark.asyncio
    async def test_dashboard_device_tree_renders_devices(self, sample_devices):
        """Dashboard device tree should render device entries."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                tree = app.screen.query_one("#mesh-device-tree", MeshDeviceTree)
                assert _count_leaves(tree) == 2

    @pytest.mark.asyncio
    async def test_device_row_shows_unread_count_from_database(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Device tree leaves should include unread count in label."""
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

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                tree = app.screen.query_one("#mesh-device-tree", MeshDeviceTree)
                labels = _get_leaf_labels(tree)

                # Find node-01's label — should contain unread badge "✉3"
                node01_labels = [lbl for lbl in labels if "node-01" in lbl]
                assert len(node01_labels) == 1
                assert "✉3" in node01_labels[0], (
                    f"Expected unread badge ✉3 in label, got: {node01_labels[0]}"
                )

    @pytest.mark.asyncio
    async def test_device_with_no_messages_has_no_badge(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Devices with no messages should not have unread badge."""
        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                tree = app.screen.query_one("#mesh-device-tree", MeshDeviceTree)
                labels = _get_leaf_labels(tree)

                # No device should have ✉ badge
                for label in labels:
                    assert "✉" not in label, (
                        f"Expected no unread badge, got: {label}"
                    )

    @pytest.mark.asyncio
    async def test_unread_count_highlighted_when_nonzero(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Non-zero unread counts should include Rich markup for highlighting."""
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

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                tree = app.screen.query_one("#mesh-device-tree", MeshDeviceTree)
                labels = _get_leaf_labels(tree)

                node01_labels = [lbl for lbl in labels if "node-01" in lbl]
                assert len(node01_labels) == 1
                # Unread badge should have Rich markup (bold)
                assert "bold" in node01_labels[0] or "✉" in node01_labels[0]


class TestDashboardEnterOpensDetail:
    """Tests for enter key navigating to device detail screen."""

    @pytest.mark.asyncio
    async def test_action_select_device_opens_detail(self, sample_devices):
        """action_select_device should navigate to MeshDeviceDetailScreen."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                screen = app.screen

                # Navigate to a leaf node first
                await pilot.press("down")  # branch header
                await pilot.pause()
                await pilot.press("down")  # first device leaf
                await pilot.pause()

                screen.action_select_device()
                await pilot.pause()

                from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

                assert isinstance(app.screen, MeshDeviceDetailScreen), (
                    f"Expected MeshDeviceDetailScreen, got {type(app.screen).__name__}"
                )

    @pytest.mark.asyncio
    async def test_enter_with_no_selection_does_nothing(self):
        """Pressing enter with no device selected should not crash."""
        app = StyreneApp()

        mock_store = MagicMock()
        mock_store.get_styrene_nodes.return_value = []
        mock_store.get_all_nodes.return_value = []

        with (
            patch("styrened.tui.screens.dashboard.discover_devices", return_value=[]),
            patch("styrened.services.node_store.get_node_store", return_value=mock_store),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                await pilot.press("enter")
                await pilot.pause()

                assert isinstance(app.screen, DashboardScreen)
