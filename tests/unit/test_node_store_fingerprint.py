"""Unit tests for NodeStore system_fingerprint persistence.

Tests the system_fingerprint column migration, save/retrieve, and
schema backwards compatibility.
"""

import sqlite3

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.services.node_store import NodeStore


@pytest.fixture
def node_store(tmp_path):
    """Create a fresh NodeStore for testing."""
    return NodeStore(db_path=tmp_path / "nodes.db")


def _make_device(
    dest_hash: str = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
    identity_hash: str = "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
    fingerprint: str | None = "nixos|24.11|x86_64|zah57xw",
) -> MeshDevice:
    return MeshDevice(
        destination_hash=dest_hash,
        identity_hash=identity_hash,
        name="test-node",
        device_type=DeviceType.STYRENE_NODE,
        last_announce=1000000,
        system_fingerprint=fingerprint,
    )


class TestNodeStoreFingerprint:
    """Tests for system_fingerprint persistence."""

    def test_save_and_retrieve_fingerprint(self, node_store):
        """Saved system_fingerprint is retrievable."""
        device = _make_device(fingerprint="nixos|24.11|x86_64|zah57xw")
        node_store.save_node(device)
        result = node_store.get_node_by_destination(device.destination_hash)
        assert result is not None
        assert result.system_fingerprint == "nixos|24.11|x86_64|zah57xw"

    def test_save_null_fingerprint(self, node_store):
        """Null system_fingerprint is stored and retrieved as None."""
        device = _make_device(fingerprint=None)
        node_store.save_node(device)
        result = node_store.get_node_by_destination(device.destination_hash)
        assert result is not None
        assert result.system_fingerprint is None

    def test_fingerprint_updated_on_re_announce(self, node_store):
        """Re-announcing with new fingerprint updates the stored value."""
        device = _make_device(fingerprint="nixos|24.11|x86_64|zah57xw")
        node_store.save_node(device)

        updated = _make_device(fingerprint="nixos|24.11|x86_64|abc1234")
        node_store.save_node(updated)

        result = node_store.get_node_by_destination(device.destination_hash)
        assert result is not None
        assert result.system_fingerprint == "nixos|24.11|x86_64|abc1234"

    def test_get_all_nodes_includes_fingerprint(self, node_store):
        """get_all_nodes returns devices with system_fingerprint."""
        node_store.save_node(_make_device(fingerprint="debian|13|x86_64|"))
        nodes = node_store.get_all_nodes()
        assert len(nodes) == 1
        assert nodes[0].system_fingerprint == "debian|13|x86_64|"

    def test_get_styrene_nodes_includes_fingerprint(self, node_store):
        """get_styrene_nodes returns devices with system_fingerprint."""
        node_store.save_node(_make_device(fingerprint="darwin|15.3|aarch64|"))
        nodes = node_store.get_styrene_nodes()
        assert len(nodes) == 1
        assert nodes[0].system_fingerprint == "darwin|15.3|aarch64|"


class TestNodeStoreFingerprintMigration:
    """Tests for schema migration adding system_fingerprint column."""

    def test_migration_adds_column(self, tmp_path):
        """Opening an old DB without system_fingerprint column still works."""
        db_path = tmp_path / "legacy.db"
        # Create a legacy schema without system_fingerprint
        conn = sqlite3.Connection(str(db_path))
        conn.execute("""
            CREATE TABLE nodes (
                destination_hash TEXT PRIMARY KEY,
                identity_hash TEXT NOT NULL,
                name TEXT,
                device_type TEXT,
                last_announce INTEGER,
                announce_count INTEGER DEFAULT 1,
                capabilities TEXT,
                version TEXT,
                lxmf_destination_hash TEXT,
                short_name TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        """)
        conn.execute(
            "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
                "OldNode",
                "styrene_node",
                1000000,
                1,
                None,
                "0.4.0",
                None,
                None,
                1000000,
                1000000,
            ),
        )
        conn.commit()
        conn.close()

        # NodeStore should migrate and still read existing rows
        store = NodeStore(db_path=db_path)
        result = store.get_node_by_destination("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert result is not None
        assert result.name == "OldNode"
        assert result.system_fingerprint is None

    def test_migration_allows_saving_fingerprint(self, tmp_path):
        """After migration, fingerprint can be saved to previously-empty DB."""
        db_path = tmp_path / "legacy.db"
        conn = sqlite3.Connection(str(db_path))
        conn.execute("""
            CREATE TABLE nodes (
                destination_hash TEXT PRIMARY KEY,
                identity_hash TEXT NOT NULL,
                name TEXT,
                device_type TEXT,
                last_announce INTEGER,
                announce_count INTEGER DEFAULT 1,
                capabilities TEXT,
                version TEXT,
                lxmf_destination_hash TEXT,
                short_name TEXT,
                created_at INTEGER,
                updated_at INTEGER
            )
        """)
        conn.commit()
        conn.close()

        store = NodeStore(db_path=db_path)
        device = _make_device(fingerprint="nixos|24.11|x86_64|zah57xw")
        store.save_node(device)

        result = store.get_node_by_destination(device.destination_hash)
        assert result is not None
        assert result.system_fingerprint == "nixos|24.11|x86_64|zah57xw"
