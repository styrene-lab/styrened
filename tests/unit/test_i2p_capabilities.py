"""Unit tests for I2P capability token and MeshDevice.b32_address persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from styrened.models.capabilities import CAPABILITY_I2P, add_capability, has_capability
from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.services.node_store import NodeStore


class TestCapabilityI2P:
    def test_capability_i2p_token_value(self):
        assert CAPABILITY_I2P == "i2p"

    def test_has_capability_returns_true_when_present(self):
        assert has_capability(["api", CAPABILITY_I2P], CAPABILITY_I2P) is True

    def test_add_capability_is_idempotent(self):
        caps = [CAPABILITY_I2P]
        result = add_capability(caps, CAPABILITY_I2P)
        assert result.count(CAPABILITY_I2P) == 1


class TestMeshDeviceB32Address:
    def _make_device(self, **kwargs) -> MeshDevice:
        defaults = {
            "destination_hash": "aabbccdd11223344",
            "identity_hash": "11223344aabbccdd",
            "name": "test-node",
            "device_type": DeviceType.STYRENE_NODE,
            "last_announce": 1700000000,
            "announce_count": 1,
        }
        defaults.update(kwargs)
        return MeshDevice(**defaults)

    def test_b32_address_defaults_to_none(self):
        device = self._make_device()
        assert device.b32_address is None

    def test_b32_address_can_be_set(self):
        device = self._make_device(b32_address="deadbeef.b32.i2p")
        assert device.b32_address == "deadbeef.b32.i2p"


@pytest.fixture
def store(tmp_path: Path) -> NodeStore:
    return NodeStore(db_path=str(tmp_path / "nodes.db"))


_DEST_HASH = "aabbccdd11223344aabbccdd11223344"
_ID_HASH = "11223344aabbccdd11223344aabbccdd"


def _device(destination_hash: str = _DEST_HASH, **kwargs) -> MeshDevice:
    defaults = {
        "destination_hash": destination_hash,
        "identity_hash": _ID_HASH,
        "name": "test-node",
        "device_type": DeviceType.STYRENE_NODE,
        "last_announce": 1700000000,
        "announce_count": 1,
    }
    defaults.update(kwargs)
    return MeshDevice(**defaults)


class TestNodeStoreB32Address:
    def test_save_and_retrieve_b32_address(self, store: NodeStore):
        dev = _device(b32_address="deadbeef.b32.i2p")
        store.save_node(dev)
        retrieved = store.get_node_by_destination(_DEST_HASH)
        assert retrieved is not None
        assert retrieved.b32_address == "deadbeef.b32.i2p"

    def test_b32_address_preserved_on_update(self, store: NodeStore):
        store.save_node(_device(b32_address="first.b32.i2p"))
        store.save_node(_device(b32_address=None, announce_count=2))
        retrieved = store.get_node_by_destination(_DEST_HASH)
        assert retrieved is not None
        assert retrieved.b32_address == "first.b32.i2p"

    def test_schema_migration_adds_b32_address_column(self, tmp_path: Path):
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """
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
                created_at INTEGER,
                updated_at INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_DEST_HASH, _ID_HASH, "old-node", "styrene", 1700000000, 1, None, None, None, 0, 0),
        )
        conn.commit()
        conn.close()

        migrated = NodeStore(db_path=str(db_path))
        retrieved = migrated.get_node_by_destination(_DEST_HASH)
        assert retrieved is not None
        assert retrieved.b32_address is None
