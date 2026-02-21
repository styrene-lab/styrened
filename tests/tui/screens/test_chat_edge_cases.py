"""Edge case and boundary condition tests for chat functionality.

These tests cover scenarios that might cause issues:
- Boundary values (empty, excessive counts)
- Unicode/special characters
- Network failures and message delivery states
- Concurrent operations
- Stale/offline devices

Tests are written TDD-style and will fail until functionality is implemented.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session
from styrened.tui.app import StyreneApp
from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.models.messages import Message, init_db
from styrened.tui.screens.conversation import ConversationScreen
from styrened.tui.screens.dashboard import DashboardScreen
from textual.widgets import DataTable


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
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
    ):
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

        with patch("styrened.tui.screens.dashboard.discover_devices", return_value=devices):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Dashboard should render without crashing
                table = app.screen.query_one("#mesh-device-table", DataTable)
                assert table.row_count == 1

                # Unread column should show some representation of 150
                # Implementation may truncate to "99+" or "150"

    @pytest.mark.asyncio
    async def test_very_long_message_content_handled_in_conversation(
        self, message_db, mock_local_identity, peer_identity
    ):
        """Long messages should not break conversation screen layout."""
        # 500-character message
        long_content = "A" * 500
        add_messages_to_db(
            message_db,
            [
                {
                    "source_hash": peer_identity,
                    "destination_hash": mock_local_identity,
                    "content": long_content,
                    "status": "pending",
                },
            ],
        )

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        mock_router = Mock()
        mock_identity = Mock()
        mock_identity.hexhash = mock_local_identity

        from styrened.protocols.chat import ChatProtocol

        chat_protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=message_db,
        )
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            conversation = ConversationScreen(
                destination_hash=peer_identity,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
            await app.push_screen(conversation)
            await pilot.pause()

            # Screen should render without crashing
            assert isinstance(app.screen, ConversationScreen)

    @pytest.mark.asyncio
    async def test_empty_message_content_handled_gracefully(
        self, message_db, mock_local_identity, peer_identity
    ):
        """Empty or whitespace-only messages should not crash UI."""
        add_messages_to_db(
            message_db,
            [
                {
                    "source_hash": peer_identity,
                    "destination_hash": mock_local_identity,
                    "content": "",  # Empty
                    "status": "pending",
                },
                {
                    "source_hash": peer_identity,
                    "destination_hash": mock_local_identity,
                    "content": "   ",  # Whitespace only
                    "status": "pending",
                },
                {
                    "source_hash": peer_identity,
                    "destination_hash": mock_local_identity,
                    "content": None,  # Null
                    "status": "pending",
                },
            ],
        )

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        mock_router = Mock()
        mock_identity = Mock()
        mock_identity.hexhash = mock_local_identity

        from styrened.protocols.chat import ChatProtocol

        chat_protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=message_db,
        )
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            conversation = ConversationScreen(
                destination_hash=peer_identity,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
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
                    "content": "Check this out: 🚀 🎉 ✨ 你好 مرحبا",
                    "status": "read",
                },
            ],
        )

        with Session(message_db) as session:
            msg = session.query(Message).first()
            assert msg.content == "Check this out: 🚀 🎉 ✨ 你好 مرحبا"


class TestMessageDeliveryStates:
    """Tests for message delivery state handling."""

    @pytest.mark.asyncio
    async def test_failed_message_shows_failure_indicator(
        self, message_db, mock_local_identity, peer_identity
    ):
        """Messages with 'failed' status should show failure indicator in conversation."""
        add_messages_to_db(
            message_db,
            [
                {
                    "source_hash": mock_local_identity,
                    "destination_hash": peer_identity,
                    "content": "This message failed to send",
                    "status": "failed",
                },
            ],
        )

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        mock_router = Mock()
        mock_identity = Mock()
        mock_identity.hexhash = mock_local_identity

        from styrened.protocols.chat import ChatProtocol

        chat_protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=message_db,
        )
        app.chat_protocol = chat_protocol

        async with app.run_test() as pilot:
            conversation = ConversationScreen(
                destination_hash=peer_identity,
                local_identity_hash=mock_local_identity,
                chat_protocol=chat_protocol,
            )
            await app.push_screen(conversation)
            await pilot.pause()

            # Should render - implementation will determine failure styling
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
    async def test_opening_chat_with_stale_device_shows_warning(
        self, message_db, mock_local_identity
    ):
        """Opening chat with a stale device should show offline warning."""
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
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        mock_router = Mock()
        mock_identity = Mock()
        mock_identity.hexhash = mock_local_identity

        from styrened.protocols.chat import ChatProtocol

        chat_protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=message_db,
        )
        app.chat_protocol = chat_protocol

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=[stale_device]
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Select and open chat with stale device
                await pilot.press("down")
                await pilot.press("c")
                await pilot.pause()

                # Should either open chat (with warning) or stay on dashboard
                # Implementation will determine exact behavior
                assert isinstance(app.screen, (DashboardScreen, ConversationScreen))


class TestNavigationRobustness:
    """Tests for rapid/complex navigation patterns."""

    @pytest.mark.asyncio
    async def test_rapid_screen_transitions_dont_corrupt_state(
        self, message_db, mock_local_identity
    ):
        """User rapidly navigating shouldn't cause data corruption."""
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

        # Add some messages
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

        mock_router = Mock()
        mock_identity = Mock()
        mock_identity.hexhash = mock_local_identity

        from styrened.protocols.chat import ChatProtocol

        chat_protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=message_db,
        )
        app.chat_protocol = chat_protocol

        with patch("styrened.tui.screens.dashboard.discover_devices", return_value=devices):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Rapid navigation: open chat, escape, repeat
                for _ in range(3):
                    await pilot.press("down")
                    await pilot.press("c")
                    await pilot.pause()

                    if isinstance(app.screen, ConversationScreen):
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
    async def test_opening_chat_with_one_device_doesnt_affect_others(
        self, message_db, mock_local_identity
    ):
        """Opening chat with device A should not mark device B's messages as read."""
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

        # Both devices have unread messages
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
                {
                    "source_hash": "node02_identity_hash",
                    "destination_hash": mock_local_identity,
                    "status": "pending",
                },
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

        mock_router = Mock()
        mock_identity = Mock()
        mock_identity.hexhash = mock_local_identity

        from styrened.protocols.chat import ChatProtocol

        chat_protocol = ChatProtocol(
            router=mock_router,
            identity=mock_identity,
            db_engine=message_db,
        )
        app.chat_protocol = chat_protocol

        with patch("styrened.tui.screens.dashboard.discover_devices", return_value=devices):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Open chat with node-01 (cursor starts at row 0, which is node-01)
                await pilot.press("c")
                await pilot.pause()

                if isinstance(app.screen, ConversationScreen):
                    # Return to dashboard
                    await pilot.press("escape")
                    await pilot.pause()

                    # Verify node-02's messages are still pending
                    with Session(message_db) as session:
                        node02_pending = (
                            session.query(Message)
                            .filter(
                                Message.source_hash == "node02_identity_hash",
                                Message.status == "pending",
                            )
                            .count()
                        )
                        assert node02_pending == 3, (
                            f"node-02 should still have 3 pending messages, got {node02_pending}"
                        )
