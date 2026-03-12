"""Unit tests for NodeStore hash validation and persistence.

Tests the security-critical validation of destination_hash and identity_hash
from potentially untrusted mesh peers, plus core persistence operations.
"""
from __future__ import annotations


import tempfile
import threading
import time
from pathlib import Path

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.services.node_store import (
    MIN_PREFIX_LENGTH,
    NodeStore,
    _is_valid_hash,
    _is_valid_hash_prefix,
    get_node_store,
)


class TestIsValidHash:
    """Tests for _is_valid_hash() validation function."""

    def test_accepts_valid_lowercase_hash(self):
        """32-char lowercase hex should be valid."""
        assert _is_valid_hash("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6") is True

    def test_accepts_valid_uppercase_hash(self):
        """32-char uppercase hex should be valid."""
        assert _is_valid_hash("A1B2C3D4E5F6A7B8C9D0E1F2A3B4C5D6") is True

    def test_accepts_valid_mixed_case_hash(self):
        """32-char mixed case hex should be valid."""
        assert _is_valid_hash("a1B2c3D4e5F6a7B8c9D0e1F2a3B4c5D6") is True

    def test_accepts_all_zeros(self):
        """32 zeros should be valid (edge case)."""
        assert _is_valid_hash("00000000000000000000000000000000") is True

    def test_accepts_all_f(self):
        """32 'f' characters should be valid (max value)."""
        assert _is_valid_hash("ffffffffffffffffffffffffffffffff") is True

    def test_rejects_short_hash(self):
        """31-char hash should be rejected."""
        assert _is_valid_hash("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d") is False

    def test_rejects_long_hash(self):
        """33-char hash should be rejected."""
        assert _is_valid_hash("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e") is False

    def test_rejects_empty_string(self):
        """Empty string should be rejected."""
        assert _is_valid_hash("") is False

    def test_rejects_none(self):
        """None should be rejected."""
        assert _is_valid_hash(None) is False

    def test_rejects_non_hex_characters(self):
        """Non-hex characters (g-z) should be rejected."""
        assert _is_valid_hash("g1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6") is False
        assert _is_valid_hash("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5dz") is False

    def test_rejects_special_characters(self):
        """Special characters should be rejected."""
        assert _is_valid_hash("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d!") is False
        assert _is_valid_hash("a1b2c3d4-5f6a-7b8c-9d0e-1f2a3b4c5d6") is False

    def test_rejects_whitespace(self):
        """Whitespace should be rejected."""
        assert _is_valid_hash(" 1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6") is False
        assert _is_valid_hash("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d ") is False
        assert _is_valid_hash("a1b2c3d4e5f6a7b8 c9d0e1f2a3b4c5d6") is False


class TestIsValidHashPrefix:
    """Tests for _is_valid_hash_prefix() validation function."""

    def test_accepts_valid_prefix_at_minimum_length(self):
        """Prefix at exactly MIN_PREFIX_LENGTH should be valid."""
        prefix = "a" * MIN_PREFIX_LENGTH
        assert _is_valid_hash_prefix(prefix) is True

    def test_accepts_valid_prefix_longer_than_minimum(self):
        """Prefix longer than MIN_PREFIX_LENGTH should be valid."""
        prefix = "a1b2c3d4e5f6"  # 12 chars
        assert _is_valid_hash_prefix(prefix) is True

    def test_accepts_full_32_char_hash_as_prefix(self):
        """Full 32-char hash should be valid as prefix."""
        assert _is_valid_hash_prefix("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6") is True

    def test_rejects_prefix_too_short(self):
        """Prefix shorter than MIN_PREFIX_LENGTH should be rejected."""
        short_prefix = "a" * (MIN_PREFIX_LENGTH - 1)
        assert _is_valid_hash_prefix(short_prefix) is False

    def test_rejects_single_char(self):
        """Single character should be rejected."""
        assert _is_valid_hash_prefix("a") is False

    def test_rejects_empty_string(self):
        """Empty string should be rejected."""
        assert _is_valid_hash_prefix("") is False

    def test_rejects_none(self):
        """None should be rejected."""
        assert _is_valid_hash_prefix(None) is False

    def test_rejects_non_hex_characters(self):
        """Non-hex characters should be rejected."""
        assert _is_valid_hash_prefix("a1b2c3g4") is False  # 'g' is not hex
        assert _is_valid_hash_prefix("a1b2c3z4") is False  # 'z' is not hex

    def test_accepts_mixed_case_hex(self):
        """Mixed case hex should be valid."""
        assert _is_valid_hash_prefix("A1b2C3d4") is True

    def test_minimum_prefix_length_is_reasonable(self):
        """MIN_PREFIX_LENGTH should be at least 8 for collision resistance."""
        assert MIN_PREFIX_LENGTH >= 8


class TestNodeStoreSaveValidation:
    """Tests for save_node() hash validation."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_nodes.db"
            yield db_path

    @pytest.fixture
    def store(self, temp_db):
        """Create a NodeStore with temporary database."""
        return NodeStore(db_path=temp_db)

    def _make_device(
        self,
        destination_hash: str = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        identity_hash: str = "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
    ) -> MeshDevice:
        """Create a MeshDevice with specified hashes."""
        return MeshDevice(
            destination_hash=destination_hash,
            identity_hash=identity_hash,
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(time.time()),
        )

    def test_save_node_accepts_valid_hashes(self, store):
        """Valid hashes should be accepted and persisted."""
        device = self._make_device()
        store.save_node(device)

        # Verify node was saved
        retrieved = store.get_node_by_destination(device.destination_hash)
        assert retrieved is not None
        assert retrieved.name == "test-node"

    def test_save_node_rejects_invalid_destination_hash(self, store):
        """Invalid destination_hash should be rejected."""
        device = self._make_device(destination_hash="invalid")
        store.save_node(device)

        # Verify node was NOT saved
        assert store.get_all_nodes() == []

    def test_save_node_rejects_short_destination_hash(self, store):
        """Short destination_hash should be rejected."""
        device = self._make_device(destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d")
        store.save_node(device)
        assert store.get_all_nodes() == []

    def test_save_node_rejects_invalid_identity_hash(self, store):
        """Invalid identity_hash should be rejected."""
        device = self._make_device(identity_hash="not-a-valid-hash")
        store.save_node(device)
        assert store.get_all_nodes() == []

    def test_save_node_rejects_none_destination_hash(self, store):
        """None destination_hash should be rejected."""
        device = self._make_device()
        device.destination_hash = None  # type: ignore
        store.save_node(device)
        assert store.get_all_nodes() == []

    def test_save_node_rejects_none_identity_hash(self, store):
        """None identity_hash should be rejected."""
        device = self._make_device()
        device.identity_hash = None  # type: ignore
        store.save_node(device)
        assert store.get_all_nodes() == []

    def test_save_node_logs_warning_on_invalid_hash(self, store, caplog):
        """Invalid hashes should log warnings."""
        import logging

        with caplog.at_level(logging.WARNING):
            device = self._make_device(destination_hash="bad")
            store.save_node(device)

        assert "Invalid destination_hash rejected" in caplog.text
        assert "'bad'" in caplog.text


class TestNodeStoreGetOperations:
    """Tests for NodeStore get/query operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_nodes.db"
            yield db_path

    @pytest.fixture
    def store(self, temp_db):
        """Create a NodeStore with temporary database."""
        return NodeStore(db_path=temp_db)

    def test_get_node_by_destination_not_found(self, store):
        """Querying non-existent node returns None."""
        result = store.get_node_by_destination("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert result is None

    def test_get_node_by_identity_not_found(self, store):
        """Querying non-existent identity returns None."""
        result = store.get_node_by_identity("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert result is None

    def test_get_identity_for_destination_returns_hash(self, store):
        """Should return identity hash for known destination."""
        device = MeshDevice(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            identity_hash="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(time.time()),
        )
        store.save_node(device)

        result = store.get_identity_for_destination("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert result == "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6"

    def test_get_identity_for_lxmf_destination_returns_hash(self, store):
        """Should return identity hash for LXMF destination."""
        device = MeshDevice(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            identity_hash="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(time.time()),
            lxmf_destination_hash="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7",
        )
        store.save_node(device)

        result = store.get_identity_for_lxmf_destination("b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7")
        assert result == "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6"


class TestNodeStoreConcurrency:
    """Tests for thread-safe operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_nodes.db"
            yield db_path

    @pytest.fixture
    def store(self, temp_db):
        """Create a NodeStore with temporary database."""
        return NodeStore(db_path=temp_db)

    def test_concurrent_save_operations(self, store):
        """Multiple threads saving nodes should not corrupt database."""
        errors = []
        saved_count = [0]

        def save_node(thread_id: int):
            try:
                for i in range(10):
                    # Generate unique valid hashes for each save
                    dest_hash = f"{thread_id:08x}{i:08x}{'0' * 16}"
                    identity_hash = f"{i:08x}{thread_id:08x}{'f' * 16}"

                    device = MeshDevice(
                        destination_hash=dest_hash,
                        identity_hash=identity_hash,
                        name=f"thread-{thread_id}-node-{i}",
                        device_type=DeviceType.STYRENE_NODE,
                        last_announce=int(time.time()),
                    )
                    store.save_node(device)
                    saved_count[0] += 1
            except Exception as e:
                errors.append(e)

        # Launch 5 threads, each saving 10 nodes
        threads = [threading.Thread(target=save_node, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors should have occurred
        assert errors == []

        # All 50 nodes should be saved
        all_nodes = store.get_all_nodes()
        assert len(all_nodes) == 50

    def test_concurrent_read_write_no_deadlock(self, store):
        """Concurrent reads and writes should not deadlock."""
        # Pre-populate with some nodes
        for i in range(5):
            dest_hash = f"{i:08x}{'a' * 24}"
            identity_hash = f"{i:08x}{'b' * 24}"
            device = MeshDevice(
                destination_hash=dest_hash,
                identity_hash=identity_hash,
                name=f"initial-{i}",
                device_type=DeviceType.STYRENE_NODE,
                last_announce=int(time.time()),
            )
            store.save_node(device)

        errors = []
        read_count = [0]
        write_count = [0]

        def reader():
            try:
                for _ in range(20):
                    _ = store.get_all_nodes()
                    read_count[0] += 1
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def writer():
            try:
                for i in range(20):
                    dest_hash = f"99{i:06x}{'c' * 24}"
                    identity_hash = f"99{i:06x}{'d' * 24}"
                    device = MeshDevice(
                        destination_hash=dest_hash,
                        identity_hash=identity_hash,
                        name=f"writer-{i}",
                        device_type=DeviceType.STYRENE_NODE,
                        last_announce=int(time.time()),
                    )
                    store.save_node(device)
                    write_count[0] += 1
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        # Run readers and writers concurrently
        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]
        for t in threads:
            t.start()

        # Set a timeout to detect deadlock
        for t in threads:
            t.join(timeout=10)
            if t.is_alive():
                errors.append(Exception("Thread deadlocked"))

        assert errors == []
        assert read_count[0] == 40  # 2 readers * 20 reads
        assert write_count[0] == 20


class TestNodeStoreDeleteOperations:
    """Tests for delete/prune operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_nodes.db"
            yield db_path

    @pytest.fixture
    def store(self, temp_db):
        """Create a NodeStore with temporary database."""
        return NodeStore(db_path=temp_db)

    def test_delete_node_removes_from_store(self, store):
        """Deleting a node should remove it."""
        device = MeshDevice(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            identity_hash="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            name="delete-me",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=int(time.time()),
        )
        store.save_node(device)
        assert len(store.get_all_nodes()) == 1

        result = store.delete_node("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert result is True
        assert len(store.get_all_nodes()) == 0

    def test_delete_node_returns_false_for_nonexistent(self, store):
        """Deleting non-existent node should return False."""
        result = store.delete_node("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert result is False

    def test_clear_all_nodes(self, store):
        """clear_all_nodes should remove all entries."""
        # Add several nodes
        for i in range(5):
            dest_hash = f"{i:08x}{'0' * 24}"
            identity_hash = f"{i:08x}{'f' * 24}"
            device = MeshDevice(
                destination_hash=dest_hash,
                identity_hash=identity_hash,
                name=f"node-{i}",
                device_type=DeviceType.STYRENE_NODE,
                last_announce=int(time.time()),
            )
            store.save_node(device)

        assert len(store.get_all_nodes()) == 5

        deleted = store.clear_all_nodes()
        assert deleted == 5
        assert len(store.get_all_nodes()) == 0


class TestGetNodeStoreSingleton:
    """Tests for get_node_store() singleton."""

    def test_get_node_store_returns_singleton(self):
        """get_node_store() should return same instance."""
        # Reset singleton for test isolation
        import styrened.services.node_store as ns

        ns._node_store = None

        store1 = get_node_store()
        store2 = get_node_store()
        assert store1 is store2

        # Cleanup
        ns._node_store = None


class TestDiscoveredVia:
    """Tests for the discovered_via field on MeshDevice + NodeStore."""

    def test_mesh_device_discovered_via_default_none(self):
        """MeshDevice.discovered_via defaults to None."""
        from styrened.models.mesh_device import DeviceType, MeshDevice
        d = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1000,
        )
        assert d.discovered_via is None

    def test_mesh_device_discovered_via_set(self):
        """MeshDevice.discovered_via can be set."""
        from styrened.models.mesh_device import DeviceType, MeshDevice
        d = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1000,
            discovered_via="Styrene Community Hub",
        )
        assert d.discovered_via == "Styrene Community Hub"

    def test_node_store_persists_discovered_via(self, tmp_path):
        """NodeStore round-trips discovered_via through SQLite."""
        from styrened.models.mesh_device import DeviceType, MeshDevice
        from styrened.services.node_store import NodeStore
        store = NodeStore(db_path=tmp_path / "test.db")
        d = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1000,
            discovered_via="TCPInterface: rns.styrene.io",
        )
        store.save_node(d)
        loaded = store.get_node_by_destination("a" * 32)
        assert loaded is not None
        assert loaded.discovered_via == "TCPInterface: rns.styrene.io"

    def test_node_store_discovered_via_not_overwritten_with_none(self, tmp_path):
        """COALESCE keeps existing discovered_via when update has None."""
        from styrened.models.mesh_device import DeviceType, MeshDevice
        from styrened.services.node_store import NodeStore
        store = NodeStore(db_path=tmp_path / "test.db")
        d1 = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1000,
            discovered_via="Styrene Community Hub",
        )
        store.save_node(d1)
        # Second save with no discovered_via should preserve the first
        d2 = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=2000,
            discovered_via=None,
        )
        store.save_node(d2)
        loaded = store.get_node_by_destination("a" * 32)
        assert loaded is not None
        assert loaded.discovered_via == "Styrene Community Hub"

    def test_node_store_index_exists(self, tmp_path):
        """idx_discovered_via index is created."""
        from styrened.services.node_store import init_db
        conn = init_db(tmp_path / "test.db")
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_discovered_via'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
