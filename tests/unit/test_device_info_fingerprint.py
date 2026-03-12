"""Unit tests for DeviceInfo system_fingerprint field in IPC messages.

Verifies to_dict(), from_dict(), and from_mesh_device() pass through
the system_fingerprint field correctly.
"""
from __future__ import annotations


from styrened.ipc.messages import DeviceInfo
from styrened.models.mesh_device import DeviceType, MeshDevice


class TestDeviceInfoFingerprint:
    """Tests for system_fingerprint in IPC DeviceInfo."""

    def test_to_dict_includes_fingerprint(self):
        """to_dict() includes system_fingerprint."""
        info = DeviceInfo(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type="styrene",
            status="active",
            is_styrene_node=True,
            lxmf_destination_hash=None,
            last_announce=1000.0,
            announce_count=1,
            system_fingerprint="nixos|24.11|x86_64|zah57xw",
        )
        d = info.to_dict()
        assert d["system_fingerprint"] == "nixos|24.11|x86_64|zah57xw"

    def test_to_dict_fingerprint_none(self):
        """to_dict() includes None fingerprint."""
        info = DeviceInfo(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type="styrene",
            status="active",
            is_styrene_node=True,
            lxmf_destination_hash=None,
            last_announce=1000.0,
            announce_count=1,
        )
        d = info.to_dict()
        assert d["system_fingerprint"] is None

    def test_from_dict_reads_fingerprint(self):
        """from_dict() reads system_fingerprint."""
        data = {
            "destination_hash": "a" * 32,
            "identity_hash": "b" * 32,
            "name": "test",
            "system_fingerprint": "debian|13|x86_64|",
        }
        info = DeviceInfo.from_dict(data)
        assert info.system_fingerprint == "debian|13|x86_64|"

    def test_from_dict_missing_fingerprint(self):
        """from_dict() returns None when fingerprint absent (backwards compat)."""
        data = {
            "destination_hash": "a" * 32,
            "identity_hash": "b" * 32,
            "name": "test",
        }
        info = DeviceInfo.from_dict(data)
        assert info.system_fingerprint is None

    def test_from_mesh_device_copies_fingerprint(self):
        """from_mesh_device() copies system_fingerprint from MeshDevice."""
        device = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1000,
            system_fingerprint="darwin|15.3|aarch64|",
        )
        info = DeviceInfo.from_mesh_device(device)
        assert info.system_fingerprint == "darwin|15.3|aarch64|"

    def test_from_mesh_device_none_fingerprint(self):
        """from_mesh_device() handles None fingerprint."""
        device = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=1000,
        )
        info = DeviceInfo.from_mesh_device(device)
        assert info.system_fingerprint is None
