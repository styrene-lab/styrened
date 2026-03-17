"""Tests for NodeStore - SQLite persistence for discovered mesh nodes."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.services.node_store import NodeStore, get_db_path, get_node_store, init_db


class TestInitDb:
    """Tests for database initialization."""

    def test_init_db_creates_tables(self, tmp_path: Path) -> None:
        """init_db creates the nodes table with correct schema."""
        db_path = tmp_path / "test_nodes.db"
        conn = init_db(db_path)

        # Check table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='nodes'"
        )
        assert cursor.fetchone() is not None

        # Check columns
        cursor = conn.execute("PRAGMA table_info(nodes)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {
            "destination_hash",
            "identity_hash",
            "name",
            "device_type",
            "last_announce",
            "announce_count",
            "capabilities",
            "version",
            "lxmf_destination_hash",
            "short_name",
            "system_fingerprint",
            "discovered_via",
            "hops",
            "nomadnet_destination_hash",
            "ygg_address",
            "b32_address",
            "web_url",
            "created_at",
            "updated_at",
        }
        assert columns == expected

        conn.close()

    def test_init_db_creates_index(self, tmp_path: Path) -> None:
        """init_db creates index on identity_hash."""
        db_path = tmp_path / "test_nodes.db"
        conn = init_db(db_path)

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_identity_hash'"
        )
        assert cursor.fetchone() is not None

        conn.close()

    def test_init_db_idempotent(self, tmp_path: Path) -> None:
        """init_db can be called multiple times without error."""
        db_path = tmp_path / "test_nodes.db"
        conn1 = init_db(db_path)
        conn1.close()

        # Second call should not raise
        conn2 = init_db(db_path)
        conn2.close()

    def test_get_db_path_returns_valid_path(self) -> None:
        """get_db_path returns a path in the user config directory."""
        path = get_db_path()
        assert path.name == "nodes.db"
        assert "styrene" in str(path).lower()


class TestNodeStore:
    """Tests for NodeStore class."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> NodeStore:
        """Create a NodeStore with a temporary database."""
        db_path = tmp_path / "test_nodes.db"
        return NodeStore(db_path)

    @pytest.fixture
    def sample_device(self) -> MeshDevice:
        """Create a sample MeshDevice for testing."""
        return MeshDevice(
            destination_hash="abcd1234abcd1234abcd1234abcd1234",
            identity_hash="ef015678ef015678ef015678ef015678",
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(time.time()),
            announce_count=1,
            capabilities=["shell", "file_transfer"],
            version="1.0.0",
        )

    def test_save_node_inserts_new(
        self, store: NodeStore, sample_device: MeshDevice
    ) -> None:
        """save_node inserts a new node."""
        store.save_node(sample_device)

        retrieved = store.get_node_by_destination(sample_device.destination_hash)
        assert retrieved is not None
        assert retrieved.destination_hash == sample_device.destination_hash
        assert retrieved.identity_hash == sample_device.identity_hash
        assert retrieved.name == sample_device.name
        assert retrieved.device_type == sample_device.device_type

    def test_save_node_updates_existing(
        self, store: NodeStore, sample_device: MeshDevice
    ) -> None:
        """save_node updates existing node and increments announce_count."""
        store.save_node(sample_device)

        # Modify and save again
        updated = MeshDevice(
            destination_hash=sample_device.destination_hash,
            identity_hash=sample_device.identity_hash,
            name="updated-name",
            device_type=sample_device.device_type,
            last_announce=int(time.time()) + 100,
            announce_count=1,  # This should be incremented by save_node
            capabilities=["shell"],
            version="2.0.0",
        )
        store.save_node(updated)

        retrieved = store.get_node_by_destination(sample_device.destination_hash)
        assert retrieved is not None
        assert retrieved.name == "updated-name"
        assert retrieved.announce_count == 2  # Incremented
        assert retrieved.version == "2.0.0"

    def test_save_node_with_no_capabilities(self, store: NodeStore) -> None:
        """save_node handles None capabilities."""
        device = MeshDevice(
            destination_hash="aaaa1111aaaa1111aaaa1111aaaa1111",
            identity_hash="bbbb2222bbbb2222bbbb2222bbbb2222",
            name="no-caps-node",
            device_type=DeviceType.UNKNOWN,
            last_announce=int(time.time()),
            announce_count=1,
            capabilities=None,
            version=None,
        )
        store.save_node(device)

        retrieved = store.get_node_by_destination(device.destination_hash)
        assert retrieved is not None
        assert retrieved.capabilities is None
        assert retrieved.version is None

    def test_get_node_by_destination_not_found(self, store: NodeStore) -> None:
        """get_node_by_destination returns None for unknown hash."""
        result = store.get_node_by_destination("nonexistent" * 4)
        assert result is None

    def test_get_node_by_identity(
        self, store: NodeStore, sample_device: MeshDevice
    ) -> None:
        """get_node_by_identity retrieves by identity hash."""
        store.save_node(sample_device)

        retrieved = store.get_node_by_identity(sample_device.identity_hash)
        assert retrieved is not None
        assert retrieved.identity_hash == sample_device.identity_hash

    def test_get_node_by_identity_not_found(self, store: NodeStore) -> None:
        """get_node_by_identity returns None for unknown hash."""
        result = store.get_node_by_identity("nonexistent" * 4)
        assert result is None

    def test_get_identity_for_destination(
        self, store: NodeStore, sample_device: MeshDevice
    ) -> None:
        """get_identity_for_destination returns identity hash."""
        store.save_node(sample_device)

        identity = store.get_identity_for_destination(sample_device.destination_hash)
        assert identity == sample_device.identity_hash

    def test_get_identity_for_destination_not_found(self, store: NodeStore) -> None:
        """get_identity_for_destination returns None for unknown hash."""
        result = store.get_identity_for_destination("nonexistent" * 4)
        assert result is None

    def test_get_all_nodes(self, store: NodeStore) -> None:
        """get_all_nodes returns all stored nodes sorted by last_announce."""
        now = int(time.time())

        devices = [
            MeshDevice(
                destination_hash=f"a{i}de0000a{i}de0000a{i}de0000a{i}de0000",
                identity_hash=f"1de{i}0000" * 4,
                name=f"node-{i}",
                device_type=DeviceType.STYRENE_NODE,
                last_announce=now - (i * 100),  # Older as i increases
                announce_count=1,
            )
            for i in range(3)
        ]

        for device in devices:
            store.save_node(device)

        all_nodes = store.get_all_nodes()
        assert len(all_nodes) == 3
        # Should be sorted by last_announce DESC (most recent first)
        assert all_nodes[0].name == "node-0"
        assert all_nodes[2].name == "node-2"

    def test_get_all_nodes_empty(self, store: NodeStore) -> None:
        """get_all_nodes returns empty list when no nodes."""
        all_nodes = store.get_all_nodes()
        assert all_nodes == []

    def test_get_styrene_nodes(self, store: NodeStore) -> None:
        """get_styrene_nodes filters by device type."""
        now = int(time.time())

        styrene_node = MeshDevice(
            destination_hash="5001123450011234500112345001aaaa",
            identity_hash="5001567850015678500156785001bbbb",
            name="styrene-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now,
            announce_count=1,
        )
        rnode = MeshDevice(
            destination_hash="20001234200012342000123420001234",
            identity_hash="20005678200056782000567820005678",
            name="rnode-device",
            device_type=DeviceType.RNODE,
            last_announce=now,
            announce_count=1,
        )

        store.save_node(styrene_node)
        store.save_node(rnode)

        styrene_nodes = store.get_styrene_nodes()
        assert len(styrene_nodes) == 1
        assert styrene_nodes[0].device_type == DeviceType.STYRENE_NODE

    def test_delete_node(self, store: NodeStore, sample_device: MeshDevice) -> None:
        """delete_node removes a node."""
        store.save_node(sample_device)
        assert store.get_node_by_destination(sample_device.destination_hash) is not None

        result = store.delete_node(sample_device.destination_hash)
        assert result is True
        assert store.get_node_by_destination(sample_device.destination_hash) is None

    def test_delete_node_not_found(self, store: NodeStore) -> None:
        """delete_node returns False for unknown hash."""
        result = store.delete_node("nonexistent" * 4)
        assert result is False

    def test_prune_old_nodes(self, store: NodeStore) -> None:
        """prune_old_nodes deletes nodes older than max_age."""
        now = int(time.time())

        old_device = MeshDevice(
            destination_hash="01d1234501d1234501d1234501d12345",
            identity_hash="01d6789001d6789001d6789001d67890",
            name="old-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now - 100000,  # Very old
            announce_count=1,
        )
        new_device = MeshDevice(
            destination_hash="0e012345" * 4,
            identity_hash="0e067890" * 4,
            name="new-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=now,
            announce_count=1,
        )

        store.save_node(old_device)
        store.save_node(new_device)

        # Prune nodes older than 1 day
        deleted = store.prune_old_nodes(max_age_seconds=86400)
        assert deleted == 1

        all_nodes = store.get_all_nodes()
        assert len(all_nodes) == 1
        assert all_nodes[0].name == "new-node"

    def test_prune_old_nodes_none_deleted(
        self, store: NodeStore, sample_device: MeshDevice
    ) -> None:
        """prune_old_nodes returns 0 when no old nodes."""
        store.save_node(sample_device)

        deleted = store.prune_old_nodes(max_age_seconds=86400)
        assert deleted == 0

    def test_close(self, store: NodeStore, sample_device: MeshDevice) -> None:
        """close() is a no-op (connections are per-operation)."""
        store.save_node(sample_device)
        store.close()

        # close() is a no-op with per-operation connections
        # Just verify it doesn't raise
        assert True

    def test_reopen_after_close(
        self, store: NodeStore, sample_device: MeshDevice
    ) -> None:
        """Store can be used after close (reconnects automatically)."""
        store.save_node(sample_device)
        store.close()

        # Should reconnect automatically
        retrieved = store.get_node_by_destination(sample_device.destination_hash)
        assert retrieved is not None


class TestRowToDevice:
    """Tests for _row_to_device conversion."""

    @pytest.fixture
    def store(self, tmp_path: Path) -> NodeStore:
        """Create a NodeStore with a temporary database."""
        return NodeStore(tmp_path / "test_nodes.db")

    def test_handles_missing_name(self, store: NodeStore) -> None:
        """_row_to_device generates name from destination_hash if missing."""
        device = MeshDevice(
            destination_hash="abcd1234" * 4,
            identity_hash="efgh5678" * 4,
            name="device-abcd1234",  # Will be stored as NULL in DB
            device_type=DeviceType.UNKNOWN,
            last_announce=int(time.time()),
            announce_count=1,
        )

        # Insert with NULL name directly
        conn = store._get_conn()
        conn.execute(
            """
            INSERT INTO nodes (destination_hash, identity_hash, name, device_type, last_announce)
            VALUES (?, ?, NULL, ?, ?)
            """,
            (
                device.destination_hash,
                device.identity_hash,
                "unknown",
                int(time.time()),
            ),
        )
        conn.commit()

        retrieved = store.get_node_by_destination(device.destination_hash)
        assert retrieved is not None
        # Should generate name from destination_hash
        assert retrieved.name.startswith("device-")

    def test_handles_null_device_type(self, store: NodeStore) -> None:
        """_row_to_device defaults to UNKNOWN for NULL device_type."""
        conn = store._get_conn()
        conn.execute(
            """
            INSERT INTO nodes (destination_hash, identity_hash, name, device_type, last_announce)
            VALUES (?, ?, ?, NULL, ?)
            """,
            ("test1234" * 4, "iden1234" * 4, "test-node", int(time.time())),
        )
        conn.commit()

        retrieved = store.get_node_by_destination("test1234" * 4)
        assert retrieved is not None
        assert retrieved.device_type == DeviceType.UNKNOWN


class TestGlobalSingleton:
    """Tests for global singleton behavior."""

    def test_get_node_store_returns_singleton(self) -> None:
        """get_node_store returns the same instance."""
        # Reset global singleton for test
        import styrened.services.node_store as ns

        ns._node_store = None

        store1 = get_node_store()
        store2 = get_node_store()
        assert store1 is store2

        # Cleanup
        store1.close()
        ns._node_store = None


class TestThreadSafety:
    """Tests for thread safety."""

    def test_connection_allows_cross_thread_access(self, tmp_path: Path) -> None:
        """Database connection allows access from different threads."""
        import threading

        store = NodeStore(tmp_path / "test_nodes.db")
        results = []

        def worker():
            try:
                device = MeshDevice(
                    destination_hash=f"thread{threading.current_thread().name}" * 2,
                    identity_hash=f"ident{threading.current_thread().name}" * 2,
                    name=f"node-{threading.current_thread().name}",
                    device_type=DeviceType.STYRENE_NODE,
                    last_announce=int(time.time()),
                    announce_count=1,
                )
                store.save_node(device)
                results.append(("success", threading.current_thread().name))
            except Exception as e:
                results.append(("error", str(e)))

        threads = [threading.Thread(target=worker, name=f"t{i}") for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should succeed
        assert all(r[0] == "success" for r in results)
        store.close()
