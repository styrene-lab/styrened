"""Unit tests for path table storage and hub node persistence."""
from __future__ import annotations


import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.services.node_store import NodeStore


class TestPathStore:
    """Tests for path table CRUD operations."""

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

    def test_save_path_persists(self, store):
        """save_path should persist a path entry."""
        store.save_path(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            next_hop="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            hops=2,
            interface_type="RNodeInterface",
            interface_name="RNode LoRa",
            bitrate=1200,
            expires=int(time.time()) + 3600,
        )

        path = store.get_path("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert path is not None
        assert path["destination_hash"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        assert path["next_hop"] == "f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6"
        assert path["hops"] == 2
        assert path["interface_type"] == "RNodeInterface"
        assert path["interface_name"] == "RNode LoRa"
        assert path["bitrate"] == 1200

    def test_save_path_upserts_on_conflict(self, store):
        """save_path should update existing entry on conflict."""
        store.save_path(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            next_hop="f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6",
            hops=3,
        )
        store.save_path(
            destination_hash="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            next_hop=None,
            hops=1,
            interface_type="TCPClientInterface",
        )

        path = store.get_path("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert path is not None
        assert path["next_hop"] is None
        assert path["hops"] == 1
        assert path["interface_type"] == "TCPClientInterface"

    def test_get_all_paths(self, store):
        """get_all_paths should return all entries ordered by hops."""
        store.save_path("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", None, hops=1)
        store.save_path("b1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", hops=3)
        store.save_path("c1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", hops=2)

        paths = store.get_all_paths()
        assert len(paths) == 3
        assert paths[0]["hops"] == 1
        assert paths[1]["hops"] == 2
        assert paths[2]["hops"] == 3

    def test_prune_expired_paths(self, store):
        """prune_expired_paths should remove entries past expiry."""
        now = int(time.time())
        store.save_path("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", None, hops=1, expires=now - 100)
        store.save_path("b1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", None, hops=1, expires=now + 3600)
        store.save_path("c1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", None, hops=1)  # No expiry

        pruned = store.prune_expired_paths()
        assert pruned == 1

        paths = store.get_all_paths()
        assert len(paths) == 2

    def test_clear_all_paths(self, store):
        """clear_all_paths should remove all entries."""
        store.save_path("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", None, hops=1)
        store.save_path("b1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", None, hops=2)

        deleted = store.clear_all_paths()
        assert deleted == 2
        assert len(store.get_all_paths()) == 0

    def test_rejects_invalid_destination_hash(self, store):
        """save_path should reject invalid destination hashes."""
        store.save_path("invalid", None, hops=1)
        assert len(store.get_all_paths()) == 0

    def test_rejects_invalid_next_hop(self, store):
        """save_path should reject invalid next_hop hashes."""
        store.save_path(
            "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            "bad-hash",
            hops=1,
        )
        assert len(store.get_all_paths()) == 0

    def test_accepts_null_next_hop(self, store):
        """save_path should accept None next_hop (direct link)."""
        store.save_path("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", None, hops=0)

        path = store.get_path("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")
        assert path is not None
        assert path["next_hop"] is None
        assert path["hops"] == 0

    def test_get_path_not_found(self, store):
        """get_path should return None for unknown destination."""
        assert store.get_path("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6") is None


class TestHubAsNode:
    """Tests for storing hub as a node in the node store."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_nodes.db"
            yield db_path

    @pytest.fixture
    def store(self, temp_db):
        return NodeStore(db_path=temp_db)

    def test_hub_stored_with_correct_device_type(self, store):
        """Hub should be stored as DeviceType.HUB."""
        hub_device = MeshDevice(
            destination_hash="6fc8bf22aa293588c9bf8d7488102e95",
            identity_hash="6fc8bf22aa293588c9bf8d7488102e95",
            name="Styrene Hub",
            device_type=DeviceType.HUB,
            last_announce=int(time.time()),
            announce_count=1,
        )
        store.save_node(hub_device)

        retrieved = store.get_node_by_destination("6fc8bf22aa293588c9bf8d7488102e95")
        assert retrieved is not None
        assert retrieved.device_type == DeviceType.HUB
        assert retrieved.name == "Styrene Hub"

    def test_hub_destination_hash_matches(self, store):
        """Hub destination_hash should match the hub address."""
        hub_addr = "6fc8bf22aa293588c9bf8d7488102e95"
        hub_device = MeshDevice(
            destination_hash=hub_addr,
            identity_hash=hub_addr,
            name="Styrene Hub",
            device_type=DeviceType.HUB,
            last_announce=int(time.time()),
        )
        store.save_node(hub_device)

        retrieved = store.get_node_by_destination(hub_addr)
        assert retrieved is not None
        assert retrieved.destination_hash == hub_addr


class TestPathSnapshotService:
    """Tests for PathSnapshotService with mocked RNS."""

    @pytest.fixture
    def temp_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_nodes.db"
            yield db_path

    @pytest.fixture
    def store(self, temp_db):
        return NodeStore(db_path=temp_db)

    def test_snapshot_saves_entries(self, store):
        """Mocked path table entries should be saved to store."""
        from styrened.services.path_snapshot import PathSnapshotService

        service = PathSnapshotService(store, interval=1)

        mock_reticulum = MagicMock()
        mock_reticulum.get_path_table.return_value = [
            {
                "hash": bytes.fromhex("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"),
                "hops": 2,
                "expires": int(time.time()) + 3600,
            },
        ]

        mock_next_hop = bytes.fromhex("f1e2d3c4b5a6f7e8d9c0b1a2f3e4d5c6")
        mock_iface = MagicMock()
        mock_iface.__class__.__name__ = "RNodeInterface"
        mock_iface.name = "RNode LoRa"
        mock_iface.bitrate = 1200

        with patch("RNS.Reticulum.Reticulum.get_instance", return_value=mock_reticulum), \
             patch("RNS.Transport.Transport.next_hop", return_value=mock_next_hop), \
             patch("RNS.Transport.Transport.next_hop_interface", return_value=mock_iface):
            service._take_snapshot()

        paths = store.get_all_paths()
        assert len(paths) == 1
        assert paths[0]["destination_hash"] == "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
        assert paths[0]["hops"] == 2
        assert paths[0]["interface_type"] == "RNodeInterface"

    def test_start_stop(self, store):
        """Service should start and stop cleanly."""
        from styrened.services.path_snapshot import PathSnapshotService

        service = PathSnapshotService(store, interval=60)

        # Mock RNS to avoid import errors
        with patch.dict("sys.modules", {"RNS": MagicMock()}):
            service.start()
            assert service.is_running
            service.stop()
            assert not service.is_running
