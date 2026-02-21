"""Shared fixtures for chat integration tests.

These fixtures reduce duplication across chat-related test files and provide
consistent mock setups for LXMF, ChatProtocol, and message database operations.
"""

from datetime import datetime
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.orm import Session
from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.models.messages import Message, init_db

# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture
def message_db(tmp_path):
    """Create test message database.

    Returns a SQLAlchemy engine connected to a temporary SQLite database.
    Database is automatically cleaned up after the test.
    """
    db_path = tmp_path / "messages.db"
    engine = init_db(str(db_path))
    return engine


@pytest.fixture
def mock_local_identity():
    """Mock local identity hash.

    This represents the TUI user's own Reticulum identity.
    Used as destination_hash for incoming messages and source_hash for outgoing.
    """
    return "local_identity_hash_1234"


@pytest.fixture
def peer_identity():
    """Identity hash for a conversation peer.

    Used in tests that need a single peer device for messaging.
    """
    return "peer_node_identity_hash"


# =============================================================================
# Device Fixtures
# =============================================================================


@pytest.fixture
def sample_styrene_devices():
    """Create sample Styrene mesh devices for testing.

    Returns a list of MeshDevice objects representing nodes on the mesh network.
    Includes devices with varying announce times to test status display.

    Returns:
        list[MeshDevice]: Three devices (2 Styrene nodes, 1 RNode)
    """
    now = int(datetime.now().timestamp())
    return [
        MeshDevice(
            destination_hash="node01_identity_hash",
            identity_hash="node01_identity_hash",
            name="node-01",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now,  # Just announced - ACTIVE
            announce_count=5,
        ),
        MeshDevice(
            destination_hash="node02_identity_hash",
            identity_hash="node02_identity_hash",
            name="node-02",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 60,  # 1 min ago - ACTIVE
            announce_count=3,
        ),
        MeshDevice(
            destination_hash="rnode01_identity_hash",
            identity_hash="rnode01_identity_hash",
            name="rnode-01",
            device_type=DeviceType.RNODE,
            last_announce=now - 120,  # 2 min ago - ACTIVE
            announce_count=2,
        ),
    ]


@pytest.fixture
def stale_device():
    """Create a stale/offline device for testing edge cases.

    Device has an old announce time (> 1 hour) and should show as LOST.
    """
    now = int(datetime.now().timestamp())
    return MeshDevice(
        destination_hash="stale_node_identity_hash",
        identity_hash="stale_node_identity_hash",
        name="stale-node",
        device_type=DeviceType.STYRENE_NODE,
        last_announce=now - 7200,  # 2 hours ago - LOST
        announce_count=1,
    )


# =============================================================================
# ChatProtocol Fixtures
# =============================================================================


@pytest.fixture
def mock_chat_protocol(message_db, mock_local_identity):
    """Create a reusable mock ChatProtocol for conversation tests.

    This fixture provides a fully configured ChatProtocol instance that:
    - Uses the test message database
    - Has a mocked LXMF router (doesn't send real messages)
    - Has the local identity set correctly

    Returns:
        ChatProtocol: Configured protocol instance for testing
    """
    mock_router = Mock()
    mock_router.handle_outbound = Mock()
    mock_identity = Mock()
    mock_identity.hexhash = mock_local_identity

    from styrened.protocols.chat import ChatProtocol

    return ChatProtocol(
        router=mock_router,
        identity=mock_identity,
        db_engine=message_db,
    )


@pytest.fixture
def patch_chat_protocol(mock_chat_protocol):
    """Fixture that patches get_chat_protocol globally across all screens.

    Use this fixture when you need ChatProtocol mocked in multiple screens
    during a single test (e.g., dashboard → conversation navigation).

    Yields:
        ChatProtocol: The mocked protocol instance
    """
    with (
        patch(
            "styrened.tui.screens.conversation.get_chat_protocol",
            return_value=mock_chat_protocol,
        ),
        patch(
            "styrened.tui.screens.dashboard.get_chat_protocol",
            return_value=mock_chat_protocol,
        ),
        patch(
            "styrened.tui.screens.inbox.get_chat_protocol",
            return_value=mock_chat_protocol,
        ),
    ):
        yield mock_chat_protocol


# =============================================================================
# Reticulum Mock Fixtures
# =============================================================================


@pytest.fixture
def mock_reticulum(tmp_path):
    """Mock Reticulum initialization for TUI tests.

    Creates a fake Reticulum config directory and patches the services
    that would normally initialize real Reticulum/LXMF instances.

    Use this fixture (via autouse or explicit) when testing TUI screens
    that would otherwise try to start Reticulum.
    """
    fake_config = tmp_path / "reticulum_config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    with (
        patch(
            "styrened.tui.services.reticulum.find_reticulum_config",
            return_value=fake_config,
        ),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
    ):
        yield fake_config


# =============================================================================
# Message Database Helpers
# =============================================================================


def add_messages_to_db(engine, messages_data: list[dict]) -> list[int]:
    """Add test messages to database and return their IDs.

    Each message dict should contain:
    - source_hash: Peer identity who sent the message
    - destination_hash: Local identity (recipient)
    - status: One of 'pending', 'sent', 'delivered', 'read', 'failed'
    - content (optional): Message text, defaults to "Test message"
    - timestamp (optional): Unix timestamp, defaults to now

    Args:
        engine: SQLAlchemy engine for the test database
        messages_data: List of message dictionaries

    Returns:
        list[int]: IDs of created messages (for later verification)

    Example:
        msg_ids = add_messages_to_db(db, [
            {
                "source_hash": peer_hash,
                "destination_hash": local_hash,
                "status": "pending",
                "content": "Hello!",
            }
        ])
    """
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


def get_message_status(engine, message_id: int) -> str | None:
    """Get status of a message by ID.

    Args:
        engine: SQLAlchemy engine for the test database
        message_id: ID of the message to check

    Returns:
        str | None: Message status or None if not found
    """
    with Session(engine) as session:
        msg = session.query(Message).filter(Message.id == message_id).first()
        return msg.status if msg else None


def count_unread_messages(engine, source_hash: str, local_hash: str) -> int:
    """Count unread (pending) messages from a source.

    Args:
        engine: SQLAlchemy engine for the test database
        source_hash: Identity hash of the message sender
        local_hash: Local user's identity hash

    Returns:
        int: Number of pending messages from source to local
    """
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
    """Count total messages in conversation with peer (both directions).

    Args:
        engine: SQLAlchemy engine for the test database
        peer_hash: Peer's identity hash
        local_hash: Local user's identity hash

    Returns:
        int: Total messages in either direction
    """
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


def add_conversation(
    engine,
    local_hash: str,
    peer_hash: str,
    message_count: int = 3,
    unread_count: int = 1,
) -> list[int]:
    """Add a complete conversation with a peer for testing.

    Creates a set of messages between local user and peer, with specified
    number of unread messages at the end.

    Args:
        engine: SQLAlchemy engine for the test database
        local_hash: Local user's identity hash
        peer_hash: Peer's identity hash
        message_count: Total messages to create
        unread_count: How many of the last messages should be 'pending'

    Returns:
        list[int]: IDs of created messages
    """
    messages = []
    base_time = datetime.now().timestamp()

    for i in range(message_count):
        is_unread = i >= (message_count - unread_count)
        messages.append(
            {
                "source_hash": peer_hash,
                "destination_hash": local_hash,
                "content": f"Message {i + 1} from {peer_hash[:8]}",
                "timestamp": base_time + i,
                "status": "pending" if is_unread else "read",
            }
        )

    return add_messages_to_db(engine, messages)


# =============================================================================
# Table Navigation Helpers
# =============================================================================


async def select_device_by_identity(pilot, table, device_identity: str) -> bool:
    """Navigate to and select a device by identity hash in a DataTable.

    Args:
        pilot: Textual test pilot
        table: DataTable widget to navigate
        device_identity: Identity hash of the device to select

    Returns:
        bool: True if device was found and selected, False otherwise
    """
    from textual.widgets import DataTable

    if not isinstance(table, DataTable):
        return False

    for row_idx in range(table.row_count):
        try:
            coord = table.coordinate_to_cell_key((row_idx, 0))
            if coord and str(coord.row_key.value) == device_identity:
                # Navigate down to this row
                for _ in range(row_idx):
                    await pilot.press("down")
                return True
        except Exception:
            continue
    return False


async def select_device_by_name(pilot, table, device_name: str) -> bool:
    """Navigate to and select a device by name in a DataTable.

    Args:
        pilot: Textual test pilot
        table: DataTable widget to navigate
        device_name: Name of the device to select (partial match)

    Returns:
        bool: True if device was found and selected, False otherwise
    """
    from textual.widgets import DataTable

    if not isinstance(table, DataTable):
        return False

    for row_idx in range(table.row_count):
        try:
            cell_value = table.get_cell_at((row_idx, 0))
            if device_name in str(cell_value):
                for _ in range(row_idx):
                    await pilot.press("down")
                return True
        except Exception:
            continue
    return False
