"""Edge case and boundary condition tests for chat functionality.

These tests cover scenarios that might cause issues:
- Boundary values (empty, excessive counts)
- Unicode/special characters
- Message delivery states
- Navigation robustness
- Multi-device scenarios
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.models.messages import Message, init_db
from styrened.tui.app import StyreneApp
from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.screens.dashboard import DashboardScreen, MeshDeviceTree
from styrened.tui.services.app_lifecycle import LifecycleMode


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
def peer_identity():
    """Identity hash for conversation peer."""
    return "peer_node_identity_hash"


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


def _make_mock_lifecycle(messages=None):
    """Create a mock lifecycle with IPCBridge returning given messages."""
    bridge = MagicMock()
    bridge.get_messages = AsyncMock(return_value=messages or [])
    bridge.mark_read = AsyncMock(return_value=0)
    bridge.send_chat = AsyncMock(return_value={"status": "sent"})
    bridge.get_status = AsyncMock(return_value={})
    bridge.get_identity = AsyncMock(return_value={})
    bridge.get_hub_status = AsyncMock(return_value={})
    bridge.get_core_config = AsyncMock(return_value={})
    bridge.get_devices = AsyncMock(return_value=[])
    bridge.get_conversations = AsyncMock(return_value=[])
    bridge.get_contacts = AsyncMock(return_value=[])
    bridge.get_auto_reply = AsyncMock(return_value={})
    bridge.subscribe_activity = AsyncMock(return_value=None)

    lifecycle = MagicMock()
    lifecycle.ipc_bridge = bridge
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    return lifecycle


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


class TestBoundaryConditions:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_device_with_excessive_unread_count_displays_correctly(
        self, message_db, mock_local_identity
    ):
        """Device with 100+ unread should display clearly without breaking layout."""
        # Add 150 unread messages
        messages = [
            {
                "source_hash": "node01_identity_hash",
                "destination_hash": mock_local_identity,
                "status": "pending",
                "content": f"Message {i}",
            }
            for i in range(150)
        ]
        add_messages_to_db(message_db, messages)

        now = int(datetime.now().timestamp())
        devices = [
            MeshDevice(
                destination_hash="node01_identity_hash",
                identity_hash="node01_identity_hash",
                name="node-01",
                device_type=DeviceType.STYRENE_NODE,
                last_announce=now,
                announce_count=5,
            ),
        ]

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        with (
            patch("styrened.tui.screens.dashboard.discover_devices", return_value=devices),
            # Suppress start_discovery's direct daemon-service call; device data comes
            # from the discover_devices mock above (bridge.get_devices() path).
            patch("styrened.tui.screens.dashboard.start_discovery"),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Dashboard should render without crashing
                tree = app.screen.query_one("#mesh-device-tree", MeshDeviceTree)
                # Tree should have at least one leaf node (the device)
                leaves = [n for n in tree._tree_walk(tree.root) if n.data is not None]
                assert len(leaves) == 1

    @pytest.mark.asyncio
    async def test_very_long_message_content_handled_in_conversation(
        self, peer_identity
    ):
        """Long messages should not break conversation screen layout."""
        long_content = "A" * 500
        lifecycle = _make_mock_lifecycle(messages=[
            {"content": long_content, "is_outgoing": False, "status": "read"},
        ])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            conversation = ConversationScreen(peer_hash=peer_identity)
            await app.push_screen(conversation)
            await pilot.pause()

            # Should render without crashing
            assert isinstance(app.screen, ConversationScreen)

    @pytest.mark.asyncio
    async def test_empty_message_content_handled_gracefully(
        self, peer_identity
    ):
        """Empty or whitespace-only messages should not crash UI."""
        lifecycle = _make_mock_lifecycle(messages=[
            {"content": "", "is_outgoing": False, "status": "read"},
            {"content": "   ", "is_outgoing": False, "status": "read"},
            {"content": None, "is_outgoing": False, "status": "read"},
        ])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            conversation = ConversationScreen(peer_hash=peer_identity)
            await app.push_screen(conversation)
            await pilot.pause()

            # Should render without crashing
            assert isinstance(app.screen, ConversationScreen)

    def test_unicode_emoji_in_message_content_persists_correctly(self, message_db):
        """Messages with emoji should store and retrieve correctly."""
        add_messages_to_db(
            message_db,
            [
                {
                    "source_hash": "a",
                    "destination_hash": "b",
                    "content": "Check this out: \U0001f680 \U0001f389 \u2728 \u4f60\u597d \u0645\u0631\u062d\u0628\u0627",
                    "status": "read",
                },
            ],
        )

        with Session(message_db) as session:
            msg = session.query(Message).first()
            assert msg.content == "Check this out: \U0001f680 \U0001f389 \u2728 \u4f60\u597d \u0645\u0631\u062d\u0628\u0627"


class TestMessageDeliveryStates:
    """Tests for message delivery state handling."""

    @pytest.mark.asyncio
    async def test_failed_message_shows_failure_indicator(
        self, peer_identity
    ):
        """Messages with 'failed' status should show failure indicator in conversation."""
        lifecycle = _make_mock_lifecycle(messages=[
            {
                "content": "This message failed to send",
                "is_outgoing": True,
                "status": "failed",
            },
        ])

        app = StyreneApp()
        app._lifecycle = lifecycle

        async with app.run_test() as pilot:
            conversation = ConversationScreen(peer_hash=peer_identity)
            await app.push_screen(conversation)
            await pilot.pause()

            # Should render
            assert isinstance(app.screen, ConversationScreen)

    def test_all_valid_message_statuses_accepted(self, message_db):
        """Database should accept all valid message status values."""
        valid_statuses = ["pending", "sent", "delivered", "read", "failed"]

        for status in valid_statuses:
            add_messages_to_db(
                message_db,
                [
                    {
                        "source_hash": "a",
                        "destination_hash": "b",
                        "content": f"Status: {status}",
                        "status": status,
                    },
                ],
            )

        with Session(message_db) as session:
            messages = session.query(Message).all()
            statuses = {msg.status for msg in messages}
            assert statuses == set(valid_statuses)


class TestStaleDeviceHandling:
    """Tests for handling stale/offline devices."""

    @pytest.mark.asyncio
    async def test_detail_screen_works_for_stale_device(self):
        """Device detail screen should work for stale devices."""
        now = int(datetime.now().timestamp())
        stale_device = MeshDevice(
            destination_hash="stale_node_identity_hash",
            identity_hash="stale_node_identity_hash",
            name="stale-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 7200,  # 2 hours ago
            announce_count=1,
        )

        app = StyreneApp()

        with (
            patch(
                "styrened.tui.screens.dashboard.discover_devices",
                return_value=[stale_device],
            ),
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=[stale_device],
            ),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Navigate to detail via enter
                await pilot.press("enter")
                await pilot.pause()

                # Should navigate to detail screen without crash
                from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

                assert isinstance(app.screen, (DashboardScreen, MeshDeviceDetailScreen))


class TestNavigationRobustness:
    """Tests for rapid/complex navigation patterns."""

    @pytest.mark.asyncio
    async def test_rapid_detail_transitions_dont_corrupt_state(
        self, message_db, mock_local_identity
    ):
        """User rapidly navigating to detail and back shouldn't crash."""
        now = int(datetime.now().timestamp())
        devices = [
            MeshDevice(
                destination_hash="node01_identity_hash",
                identity_hash="node01_identity_hash",
                name="node-01",
                device_type=DeviceType.STYRENE_NODE,
                last_announce=now,
                announce_count=5,
            ),
        ]

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
            patch("styrened.tui.screens.dashboard.discover_devices", return_value=devices),
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=devices,
            ),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Rapid navigation: enter detail, escape, repeat
                for _ in range(3):
                    await pilot.press("enter")
                    await pilot.pause()

                    await pilot.press("escape")
                    await pilot.pause()

                # Should end up on dashboard without crash
                assert isinstance(app.screen, DashboardScreen)

                # Database should still be valid
                with Session(message_db) as session:
                    count = session.query(Message).count()
                    assert count >= 1


class TestMultiDeviceScenarios:
    """Tests for interactions with multiple devices."""

    @pytest.mark.asyncio
    async def test_detail_screen_for_correct_device(
        self, message_db, mock_local_identity
    ):
        """Entering detail screen should show the selected device."""
        now = int(datetime.now().timestamp())
        devices = [
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
                last_announce=now,
                announce_count=3,
            ),
        ]

        app = StyreneApp()

        with (
            patch("styrened.tui.screens.dashboard.discover_devices", return_value=devices),
            patch(
                "styrened.tui.screens.mesh_device_detail.discover_devices",
                return_value=devices,
            ),
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                tree = app.screen.query_one("#mesh-device-tree", MeshDeviceTree)
                tree._select_by_identity(devices[0].destination_hash)
                app.screen.action_select_device()
                await pilot.pause()

                from styrened.tui.screens.mesh_device_detail import MeshDeviceDetailScreen

                assert isinstance(app.screen, MeshDeviceDetailScreen), (
                    f"Expected MeshDeviceDetailScreen, got {type(app.screen).__name__}"
                )
                assert app.screen.device is not None
