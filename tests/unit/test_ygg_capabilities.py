"""Unit tests for yggdrasil capability bit and MeshDevice.ygg_address persistence."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from styrened.models.capabilities import (
    CAPABILITY_YGGDRASIL,
    add_capability,
    has_capability,
)
from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.services.node_store import NodeStore


# ---------------------------------------------------------------------------
# CAPABILITY_YGGDRASIL token
# ---------------------------------------------------------------------------


class TestCapabilityYggdrasil:
    """Tests for the CAPABILITY_YGGDRASIL constant and helpers."""

    def test_capability_yggdrasil_is_string(self):
        assert isinstance(CAPABILITY_YGGDRASIL, str)
        assert CAPABILITY_YGGDRASIL  # non-empty

    def test_capability_yggdrasil_token_value(self):
        """Token value must be stable — it is part of the wire format."""
        assert CAPABILITY_YGGDRASIL == "yggdrasil"

    def test_has_capability_returns_true_when_present(self):
        caps = ["autoreply", CAPABILITY_YGGDRASIL]
        assert has_capability(caps, CAPABILITY_YGGDRASIL) is True

    def test_has_capability_returns_false_when_absent(self):
        caps = ["autoreply"]
        assert has_capability(caps, CAPABILITY_YGGDRASIL) is False

    def test_has_capability_handles_none_list(self):
        assert has_capability(None, CAPABILITY_YGGDRASIL) is False

    def test_has_capability_handles_empty_list(self):
        assert has_capability([], CAPABILITY_YGGDRASIL) is False

    def test_add_capability_adds_to_none(self):
        result = add_capability(None, CAPABILITY_YGGDRASIL)
        assert result == [CAPABILITY_YGGDRASIL]

    def test_add_capability_adds_to_existing(self):
        result = add_capability(["autoreply"], CAPABILITY_YGGDRASIL)
        assert CAPABILITY_YGGDRASIL in result
        assert "autoreply" in result

    def test_add_capability_is_idempotent(self):
        caps = [CAPABILITY_YGGDRASIL]
        result = add_capability(caps, CAPABILITY_YGGDRASIL)
        assert result.count(CAPABILITY_YGGDRASIL) == 1

    def test_add_capability_does_not_mutate_original(self):
        original = ["autoreply"]
        add_capability(original, CAPABILITY_YGGDRASIL)
        assert original == ["autoreply"]

    def test_round_trip_via_csv(self):
        """Capability survives comma-separated wire serialisation."""
        caps = ["autoreply", CAPABILITY_YGGDRASIL, "somethingelse"]
        serialised = ",".join(caps)
        restored = serialised.split(",")
        assert has_capability(restored, CAPABILITY_YGGDRASIL) is True


# ---------------------------------------------------------------------------
# MeshDevice.ygg_address field
# ---------------------------------------------------------------------------


class TestMeshDeviceYggAddress:
    """Tests for the ygg_address field on MeshDevice."""

    def _make_device(self, **kwargs) -> MeshDevice:
        defaults = dict(
            destination_hash="aabbccdd11223344",
            identity_hash="11223344aabbccdd",
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1700000000,
            announce_count=1,
        )
        defaults.update(kwargs)
        return MeshDevice(**defaults)

    def test_ygg_address_defaults_to_none(self):
        device = self._make_device()
        assert device.ygg_address is None

    def test_ygg_address_can_be_set(self):
        addr = "200:1234:5678:abcd::1"
        device = self._make_device(ygg_address=addr)
        assert device.ygg_address == addr

    def test_ygg_address_accepts_none(self):
        device = self._make_device(ygg_address=None)
        assert device.ygg_address is None


# ---------------------------------------------------------------------------
# NodeStore persistence of ygg_address
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> NodeStore:
    """Fresh NodeStore backed by a temp SQLite database."""
    db_file = tmp_path / "nodes.db"
    return NodeStore(db_path=str(db_file))


_DEST_HASH = "aabbccdd11223344aabbccdd11223344"  # 32 hex chars (16 bytes)
_ID_HASH = "11223344aabbccdd11223344aabbccdd"


def _device(destination_hash: str = _DEST_HASH, **kwargs) -> MeshDevice:
    defaults = dict(
        destination_hash=destination_hash,
        identity_hash=_ID_HASH,
        name="test-node",
        device_type=DeviceType.STYRENE_NODE,
        last_announce=1700000000,
        announce_count=1,
    )
    defaults.update(kwargs)
    return MeshDevice(**defaults)


class TestNodeStoreYggAddress:
    """Tests for ygg_address round-trip through NodeStore."""

    def test_save_and_retrieve_ygg_address(self, store: NodeStore):
        addr = "200:abcd:1234:5678::1"
        dev = _device(ygg_address=addr)
        store.save_node(dev)
        retrieved = store.get_node_by_destination(_DEST_HASH)
        assert retrieved is not None
        assert retrieved.ygg_address == addr

    def test_save_node_without_ygg_address(self, store: NodeStore):
        dev = _device()
        store.save_node(dev)
        retrieved = store.get_node_by_destination(_DEST_HASH)
        assert retrieved is not None
        assert retrieved.ygg_address is None

    def test_ygg_address_preserved_on_update(self, store: NodeStore):
        """ygg_address set on first save is preserved when second save omits it."""
        addr = "200:beef::1"
        dev1 = _device(ygg_address=addr, announce_count=1)
        store.save_node(dev1)

        # Second announce without ygg_address — COALESCE keeps existing value
        dev2 = _device(ygg_address=None, announce_count=2)
        store.save_node(dev2)

        retrieved = store.get_node_by_destination(_DEST_HASH)
        assert retrieved is not None
        assert retrieved.ygg_address == addr

    def test_ygg_address_updated_when_provided(self, store: NodeStore):
        """Later save with a new ygg_address overwrites the stored one."""
        dev1 = _device(ygg_address="200:aaaa::1")
        store.save_node(dev1)

        dev2 = _device(ygg_address="200:bbbb::1")
        store.save_node(dev2)

        retrieved = store.get_node_by_destination(_DEST_HASH)
        assert retrieved is not None
        assert retrieved.ygg_address == "200:bbbb::1"

    def test_schema_migration_adds_ygg_address_column(self, tmp_path: Path):
        """Opening a DB created without ygg_address column should migrate cleanly."""
        db_path = tmp_path / "old.db"

        # Create a DB without the ygg_address column
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
        _OLD_DEST = "deadbeef11223344deadbeef11223344"
        _OLD_ID = "aabb1122deadbeefaabb1122deadbeef"
        conn.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (_OLD_DEST, _OLD_ID, "old-node", "styrene",
             1700000000, 1, None, None, None, 0, 0),
        )
        conn.commit()
        conn.close()

        # NodeStore should open without error and migrate the schema
        store = NodeStore(db_path=str(db_path))
        retrieved = store.get_node_by_destination(_OLD_DEST)
        assert retrieved is not None
        assert retrieved.ygg_address is None

        # New save with ygg_address should also work
        retrieved.ygg_address = "200:feed::1"
        store.save_node(retrieved)
        updated = store.get_node_by_destination(_OLD_DEST)
        assert updated is not None
        assert updated.ygg_address == "200:feed::1"
