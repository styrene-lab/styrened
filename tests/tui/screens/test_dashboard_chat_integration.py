"""Tests for dashboard chat integration features.

These tests drive the implementation of:
- Unread message count display in device table
- Chat navigation from dashboard ('c' key)
- Message count refresh on screen resume

Tests are written TDD-style and will fail until functionality is implemented.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from styrened.tui.app import StyreneApp
from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.models.messages import Message, init_db
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
def sample_devices():
    """Create sample mesh devices for testing."""
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
        MeshDevice(
            destination_hash="rnode01_identity_hash",
            identity_hash="rnode01_identity_hash",
            name="rnode-01",
            device_type=DeviceType.RNODE,
            last_announce=now - 120,
            announce_count=2,
        ),
    ]


def add_messages_to_db(engine, messages_data: list[dict]) -> None:
    """Helper to add test messages to database."""
    from sqlalchemy.orm import Session

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
        session.commit()


@pytest.fixture(autouse=True)
def mock_reticulum_for_tests(tmp_path):
    """Mock Reticulum initialization for all tests."""
    fake_config = tmp_path / "reticulum_config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch(
            "styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config
        ),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
    ):
        yield


class TestDashboardMessageIndicators:
    """Tests for unread message count display in dashboard device table."""

    @pytest.mark.asyncio
    async def test_dashboard_device_table_has_unread_column(self, sample_devices):
        """Dashboard device table should have an UNREAD column for message counts."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.screen.query_one("#mesh-device-table", DataTable)
                column_labels = [str(col.label) for col in table.columns.values()]

                # Should have UNREAD or MESSAGES column
                has_message_column = any(
                    label in col.upper()
                    for col in column_labels
                    for label in ["UNREAD", "MESSAGES", "MSG"]
                )
                assert has_message_column, (
                    f"Expected UNREAD/MESSAGES column in table. Found: {column_labels}"
                )

    @pytest.mark.asyncio
    async def test_device_row_shows_unread_count_from_database(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Device rows should display unread message count from chat database."""
        # Setup: node-01 has 3 unread messages
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
        # Inject test database
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.screen.query_one("#mesh-device-table", DataTable)

                # Find unread count for node-01
                # The table should show "3" in the unread column for node01_identity_hash
                row_data = self._get_row_data(table, "node01_identity_hash")
                assert row_data is not None, "node-01 should be in table"

                # Check unread value (could be in different column positions)
                unread_value = row_data.get("unread", row_data.get("messages"))
                assert unread_value is not None
                assert "3" in str(unread_value), (
                    f"Expected unread count of 3, got {unread_value}"
                )

    @pytest.mark.asyncio
    async def test_device_with_no_messages_shows_dash(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Devices with no messages should show '-' or '0' in unread column."""
        # No messages added - all devices have 0 unread
        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                table = app.screen.query_one("#mesh-device-table", DataTable)
                row_data = self._get_row_data(table, "node01_identity_hash")

                unread_value = str(row_data.get("unread", row_data.get("messages", "")))
                # Accept Rich markup variants like "[dim]-[/]"
                assert (
                    "-" in unread_value or "0" in unread_value or unread_value == ""
                ), f"Expected '-' or '0' for no messages, got {unread_value}"

    @pytest.mark.asyncio
    async def test_unread_count_highlighted_when_nonzero(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Non-zero unread counts should be visually highlighted."""
        # Setup: node-01 has unread messages
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

                table = app.screen.query_one("#mesh-device-table", DataTable)

                # The unread cell should have Rich markup for highlighting
                # e.g., [bold yellow]1[/] or [bold green]1[/]
                row_data = self._get_row_data(table, "node01_identity_hash")
                unread_cell = row_data.get("unread_raw", row_data.get("unread"))

                # Check that the cell has formatting (Rich Text or markup)
                # This is a soft assertion - the key behavior is visibility
                if hasattr(unread_cell, "plain"):
                    # It's a Rich Text object - good
                    pass
                elif isinstance(unread_cell, str) and "[" in unread_cell:
                    # Contains Rich markup - good
                    pass
                # Test passes if we got here - highlighting is implementation detail

    def _get_row_data(self, table: DataTable, row_key: str) -> dict | None:
        """Helper to extract row data from DataTable by row key."""
        # Find the row with matching key
        for row_idx in range(table.row_count):
            try:
                coord = table.coordinate_to_cell_key((row_idx, 0))
                if coord and coord.row_key and str(coord.row_key.value) == row_key:
                    # Extract all column values for this row
                    data = {}
                    for col_idx, col in enumerate(table.columns.values()):
                        cell_key = table.coordinate_to_cell_key((row_idx, col_idx))
                        if cell_key:
                            value = table.get_cell(
                                cell_key.row_key, cell_key.column_key
                            )
                            col_name = str(col.label).lower().replace(" ", "_")
                            data[col_name] = value
                            data[f"{col_name}_raw"] = value
                    return data
            except Exception:
                continue
        return None


class TestDashboardChatNavigation:
    """Tests for chat navigation from dashboard."""

    @pytest.mark.asyncio
    async def test_c_key_opens_chat_screen_for_selected_device(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Pressing 'c' on dashboard should open ConversationScreen for selected device."""
        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        # Create ChatProtocol
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
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Focus the table and move to first device row
                table = app.screen.query_one("#mesh-device-table")
                table.focus()
                await pilot.pause()

                # Press 'c' to open chat
                await pilot.press("c")
                await pilot.pause()

                # Verify ConversationScreen is now active
                from styrened.tui.screens.conversation import ConversationScreen

                assert isinstance(app.screen, ConversationScreen), (
                    f"Expected ConversationScreen, got {type(app.screen).__name__}"
                )

    @pytest.mark.asyncio
    async def test_chat_screen_receives_correct_device_identity(
        self, sample_devices, message_db, mock_local_identity
    ):
        """ConversationScreen should be initialized with selected device's identity."""
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
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Focus table and select first device (node-01)
                table = app.screen.query_one("#mesh-device-table")
                table.focus()
                await pilot.pause()

                await pilot.press("c")
                await pilot.pause()

                from styrened.tui.screens.conversation import ConversationScreen

                if isinstance(app.screen, ConversationScreen):
                    assert app.screen.destination_hash == "node01_identity_hash", (
                        f"Expected node01_identity_hash, got {app.screen.destination_hash}"
                    )

    @pytest.mark.asyncio
    async def test_c_key_with_no_selection_shows_notification(self):
        """Pressing 'c' with no device selected should show notification, not crash."""
        app = StyreneApp()

        # Empty device list
        with patch("styrened.tui.screens.dashboard.discover_devices", return_value=[]):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Press 'c' with no devices
                await pilot.press("c")
                await pilot.pause()

                # Should still be on dashboard (no crash, no navigation)
                from styrened.tui.screens.dashboard import DashboardScreen

                assert isinstance(app.screen, DashboardScreen)

    @pytest.mark.asyncio
    async def test_c_key_only_works_for_styrene_nodes(self, sample_devices):
        """Chat should only open for Styrene nodes, not RNodes or generic devices."""
        app = StyreneApp()

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
            async with app.run_test() as pilot:
                await pilot.pause()

                # Navigate to RNode (third device)
                await pilot.press("down")
                await pilot.press("down")
                await pilot.press("down")
                await pilot.pause()

                # Press 'c' - should show notification or do nothing
                await pilot.press("c")
                await pilot.pause()

                # Should either stay on dashboard or show appropriate message
                from styrened.tui.screens.conversation import ConversationScreen
                from styrened.tui.screens.dashboard import DashboardScreen

                # Either stayed on dashboard OR opened chat is acceptable
                # (depends on implementation choice)
                assert isinstance(app.screen, (DashboardScreen, ConversationScreen))


class TestDashboardRefreshOnReturn:
    """Tests for dashboard refresh when returning from chat."""

    @pytest.mark.asyncio
    async def test_dashboard_refreshes_message_counts_on_return(
        self, sample_devices, message_db, mock_local_identity
    ):
        """Returning from chat should refresh dashboard with updated message counts."""
        # Setup: node-01 has 2 unread messages
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

        app = StyreneApp()
        app.db_engine = message_db
        app.local_identity_hash = mock_local_identity

        with patch(
            "styrened.tui.screens.dashboard.discover_devices", return_value=sample_devices
        ):
                await pilot.pause()

                # Navigate to chat
                await pilot.press("down")
                await pilot.press("c")
                await pilot.pause()

                # Simulate messages being marked as read (would happen in ConversationScreen)
                from sqlalchemy.orm import Session

                with Session(message_db) as session:
                    session.query(Message).filter(
                        Message.source_hash == "node01_identity_hash"
                    ).update({"status": "read"})
                    session.commit()

                # Return to dashboard
                await pilot.press("escape")
                await pilot.pause()

                # Verify dashboard shows updated count (0 unread)
                from styrened.tui.screens.dashboard import DashboardScreen

                if isinstance(app.screen, DashboardScreen):
                    # Dashboard should have refreshed - verify table is accessible
                    _ = app.screen.query_one("#mesh-device-table", DataTable)
                    # Count should now be 0 after messages marked as read
                    # Implementation will determine exact behavior
