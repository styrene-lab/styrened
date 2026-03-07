"""Tests for TUI utility functions — device_info_to_mesh."""

from dataclasses import dataclass

from styrened.models.mesh_device import DeviceType, MeshDevice
from styrened.tui.utils import device_info_to_mesh


@dataclass
class FakeDeviceInfo:
    """Mimics DeviceInfo dataclass from ipc.messages."""
    destination_hash: str = "aabbccdd" * 4
    identity_hash: str = "11223344" * 4
    name: str = "TestNode"
    device_type: str = "styrene"  # DeviceType.STYRENE_NODE.value
    status: str = "active"
    is_styrene_node: bool = True
    lxmf_destination_hash: str | None = None
    last_announce: float = 1234567890.0
    announce_count: int = 5
    short_name: str | None = "testnode"
    system_fingerprint: str | None = "abc123"


class TestDeviceInfoToMesh:
    """device_info_to_mesh converts DeviceInfo dataclass → MeshDevice."""

    def test_basic_conversion(self) -> None:
        info = FakeDeviceInfo()
        result = device_info_to_mesh(info)
        assert isinstance(result, MeshDevice)
        assert result.destination_hash == "aabbccdd" * 4
        assert result.identity_hash == "11223344" * 4
        assert result.name == "TestNode"
        assert result.device_type == DeviceType.STYRENE_NODE
        assert result.last_announce == 1234567890.0
        assert result.announce_count == 5
        assert result.short_name == "testnode"
        assert result.system_fingerprint == "abc123"

    def test_missing_optional_fields(self) -> None:
        info = FakeDeviceInfo(lxmf_destination_hash=None, short_name=None, system_fingerprint=None)
        result = device_info_to_mesh(info)
        assert result.lxmf_destination_hash is None
        assert result.short_name is None
        assert result.system_fingerprint is None

    def test_does_not_call_get(self) -> None:
        """Ensure we use getattr, not .get() — DeviceInfo is a dataclass, not a dict."""
        info = FakeDeviceInfo()
        assert not hasattr(info, "get")
        result = device_info_to_mesh(info)
        assert result.name == "TestNode"

    def test_unknown_device_type(self) -> None:
        info = FakeDeviceInfo(device_type="unknown")
        result = device_info_to_mesh(info)
        assert result.device_type == DeviceType.UNKNOWN
