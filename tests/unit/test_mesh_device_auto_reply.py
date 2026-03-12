"""Unit tests for MeshDevice.has_auto_reply property."""
from __future__ import annotations


from styrened.models.mesh_device import DeviceType, MeshDevice


class TestHasAutoReply:
    """Verify has_auto_reply property checks capabilities list."""

    def test_has_auto_reply_true_when_present(self):
        """Should return True when 'autoreply' is in capabilities."""
        device = MeshDevice(
            destination_hash="abcd1234",
            identity_hash="efgh5678",
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=0,
            capabilities=["hub", "api", "autoreply"],
        )
        assert device.has_auto_reply is True

    def test_has_auto_reply_false_when_absent(self):
        """Should return False when 'autoreply' is not in capabilities."""
        device = MeshDevice(
            destination_hash="abcd1234",
            identity_hash="efgh5678",
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=0,
            capabilities=["hub", "api"],
        )
        assert device.has_auto_reply is False

    def test_has_auto_reply_false_when_none(self):
        """Should return False when capabilities is None."""
        device = MeshDevice(
            destination_hash="abcd1234",
            identity_hash="efgh5678",
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=0,
            capabilities=None,
        )
        assert device.has_auto_reply is False

    def test_has_auto_reply_false_when_empty(self):
        """Should return False when capabilities is empty list."""
        device = MeshDevice(
            destination_hash="abcd1234",
            identity_hash="efgh5678",
            name="test-node",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=0,
            capabilities=[],
        )
        assert device.has_auto_reply is False
