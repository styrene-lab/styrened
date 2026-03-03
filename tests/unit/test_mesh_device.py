"""Unit tests for MeshDevice model and parse_announce_data.

Tests the DeviceType enum extensions, LXMF msgpack parsing,
aspect_hint parameter, and regression for existing formats.
"""

from unittest.mock import MagicMock, patch

from styrened.models.mesh_device import (
    DeviceType,
    MeshDevice,
    create_mesh_device,
    parse_announce_data,
)


class TestDeviceTypeEnum:
    """Verify new DeviceType enum values exist."""

    def test_lxmf_peer_value(self):
        assert DeviceType.LXMF_PEER.value == "lxmf_peer"

    def test_propagation_node_value(self):
        assert DeviceType.PROPAGATION_NODE.value == "propagation_node"

    def test_nomadnet_node_value(self):
        assert DeviceType.NOMADNET_NODE.value == "nomadnet_node"


class TestMeshDeviceProperties:
    """Verify convenience properties on MeshDevice."""

    def _make_device(self, device_type: DeviceType) -> MeshDevice:
        return MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type=device_type,
            last_announce=0,
        )

    def test_is_lxmf_peer(self):
        d = self._make_device(DeviceType.LXMF_PEER)
        assert d.is_lxmf_peer is True
        assert d.is_propagation_node is False

    def test_is_propagation_node(self):
        d = self._make_device(DeviceType.PROPAGATION_NODE)
        assert d.is_propagation_node is True
        assert d.is_lxmf_peer is False

    def test_is_nomadnet_node(self):
        d = self._make_device(DeviceType.NOMADNET_NODE)
        assert d.is_nomadnet_node is True
        assert d.is_styrene_node is False


class TestParseAnnounceDataExistingFormats:
    """Regression tests: existing formats must still work."""

    def test_styrene_node_format(self):
        """Styrene node announce format is unchanged."""
        data = b"styrene:myhost:0.10.0:hub,api:deadbeef:mynode:fp1"
        name, dtype, caps, version, lxmf_dest, short, fp, _nn = parse_announce_data(data)
        assert dtype == DeviceType.STYRENE_NODE
        assert name == "myhost"
        assert version == "0.10.0"
        assert caps == ["hub", "api"]
        assert lxmf_dest == "deadbeef"
        assert short == "mynode"
        assert fp == "fp1"

    def test_rnode_format(self):
        """RNode announce format is unchanged."""
        data = b"rnode:my-rnode"
        name, dtype, *_ = parse_announce_data(data)
        assert dtype == DeviceType.RNODE
        assert name == "my-rnode"

    def test_json_format(self):
        """JSON announce format is unchanged."""
        data = b'{"display_name": "SidebandUser"}'
        name, dtype, *_ = parse_announce_data(data)
        assert dtype == DeviceType.GENERIC
        assert name == "SidebandUser"

    def test_plain_text_format(self):
        """Plain text announce names are unchanged."""
        data = b"My Cool Node"
        name, dtype, *_ = parse_announce_data(data)
        assert dtype == DeviceType.GENERIC
        assert name == "My Cool Node"

    def test_empty_app_data(self):
        """Empty app_data returns UNKNOWN."""
        name, dtype, *_ = parse_announce_data(None)
        assert dtype == DeviceType.UNKNOWN
        assert name == "unknown"

    def test_minimal_styrene(self):
        """Minimal 'styrene' string is unchanged."""
        data = b"styrene"
        name, dtype, *_ = parse_announce_data(data)
        assert dtype == DeviceType.STYRENE_NODE
        assert name == "styrene-node"


class TestParseAnnounceDataLxmfMsgpack:
    """Tests for LXMF msgpack parsing of announce data."""

    def test_lxmf_delivery_msgpack_with_display_name(self):
        """LXMF 0.5.0+ delivery announce with msgpack display name."""
        # Simulate msgpack [b"TestUser", 0] - 2-element fixarray
        import msgpack

        data = msgpack.packb([b"TestUser", 0])

        # Mock LXMF module
        mock_lxmf = MagicMock()
        mock_lxmf.pn_announce_data_is_valid.return_value = False
        mock_lxmf.display_name_from_app_data.return_value = "TestUser"

        with patch.dict("sys.modules", {"LXMF": mock_lxmf}):
            name, dtype, *_ = parse_announce_data(data, aspect_hint=DeviceType.LXMF_PEER)

        assert name == "TestUser"
        assert dtype == DeviceType.LXMF_PEER

    def test_lxmf_propagation_node_msgpack(self):
        """LXMF propagation node announce with msgpack format."""
        import msgpack

        # Simulate propagation node announce data
        data = msgpack.packb([b"MyPropNode", 1000, True, 0, 0, [10, 5, 8], {1: b"MyPropNode"}])

        mock_lxmf = MagicMock()
        mock_lxmf.pn_announce_data_is_valid.return_value = True
        mock_lxmf.pn_name_from_app_data.return_value = "MyPropNode"

        with patch.dict("sys.modules", {"LXMF": mock_lxmf}):
            name, dtype, *_ = parse_announce_data(data, aspect_hint=DeviceType.PROPAGATION_NODE)

        assert name == "MyPropNode"
        assert dtype == DeviceType.PROPAGATION_NODE

    def test_msgpack_without_aspect_hint_infers_lxmf_peer(self):
        """Msgpack data without aspect_hint infers LXMF_PEER from LXMF parser."""
        import msgpack

        data = msgpack.packb([b"SomePeer", 0])

        mock_lxmf = MagicMock()
        mock_lxmf.pn_announce_data_is_valid.return_value = False
        mock_lxmf.display_name_from_app_data.return_value = "SomePeer"

        with patch.dict("sys.modules", {"LXMF": mock_lxmf}):
            name, dtype, *_ = parse_announce_data(data)

        assert name == "SomePeer"
        assert dtype == DeviceType.LXMF_PEER

    def test_msgpack_propagation_detected_without_aspect_hint(self):
        """Propagation node detected from app_data even without aspect_hint."""
        import msgpack

        data = msgpack.packb([b"PropNode", 1000, True, 0, 0, [10, 5, 8], {1: b"PropNode"}])

        mock_lxmf = MagicMock()
        mock_lxmf.pn_announce_data_is_valid.return_value = True
        mock_lxmf.pn_name_from_app_data.return_value = "PropNode"

        with patch.dict("sys.modules", {"LXMF": mock_lxmf}):
            name, dtype, *_ = parse_announce_data(data)

        assert name == "PropNode"
        assert dtype == DeviceType.PROPAGATION_NODE


class TestParseAnnounceDataAspectHint:
    """Tests for aspect_hint parameter behavior."""

    def test_aspect_hint_overrides_generic_for_plain_text(self):
        """NomadNet nodes announce plain UTF-8 name; aspect_hint classifies correctly."""
        data = b"My NomadNet Node"
        name, dtype, *_ = parse_announce_data(data, aspect_hint=DeviceType.NOMADNET_NODE)
        assert dtype == DeviceType.NOMADNET_NODE
        assert name == "My NomadNet Node"

    def test_aspect_hint_overrides_json_generic(self):
        """JSON app_data with aspect_hint uses the hint type."""
        data = b'{"display_name": "TestPeer"}'
        name, dtype, *_ = parse_announce_data(data, aspect_hint=DeviceType.LXMF_PEER)
        assert dtype == DeviceType.LXMF_PEER
        assert name == "TestPeer"

    def test_aspect_hint_with_empty_data(self):
        """Empty data with aspect_hint uses the hint."""
        name, dtype, *_ = parse_announce_data(None, aspect_hint=DeviceType.LXMF_PEER)
        assert dtype == DeviceType.LXMF_PEER

    def test_aspect_hint_does_not_override_styrene(self):
        """Styrene format is always STYRENE_NODE regardless of hint."""
        data = b"styrene:myhost:0.10.0:hub"
        _, dtype, *_ = parse_announce_data(data, aspect_hint=DeviceType.LXMF_PEER)
        assert dtype == DeviceType.STYRENE_NODE

    def test_aspect_hint_does_not_override_rnode(self):
        """RNode format is always RNODE regardless of hint."""
        data = b"rnode:my-rnode"
        _, dtype, *_ = parse_announce_data(data, aspect_hint=DeviceType.LXMF_PEER)
        assert dtype == DeviceType.RNODE

    def test_binary_data_with_no_lxmf_and_hint(self):
        """Binary data that LXMF can't parse uses aspect_hint fallback."""
        data = bytes([0xFF, 0xFE, 0xFD])  # Not valid msgpack or UTF-8

        mock_lxmf = MagicMock()
        mock_lxmf.pn_announce_data_is_valid.return_value = False
        mock_lxmf.display_name_from_app_data.return_value = None

        with patch.dict("sys.modules", {"LXMF": mock_lxmf}):
            name, dtype, *_ = parse_announce_data(data, aspect_hint=DeviceType.LXMF_PEER)

        assert dtype == DeviceType.LXMF_PEER
        assert name == "binary-data"


class TestCreateMeshDeviceWithAspectHint:
    """Tests for create_mesh_device with aspect_hint parameter."""

    def test_aspect_hint_passed_through(self):
        """aspect_hint is forwarded to parse_announce_data."""
        data = b"My NomadNet Node"
        device = create_mesh_device(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            app_data=data,
            aspect_hint=DeviceType.NOMADNET_NODE,
        )
        assert device.device_type == DeviceType.NOMADNET_NODE
        assert device.name == "My NomadNet Node"

    def test_no_aspect_hint_defaults(self):
        """Without aspect_hint, behavior is unchanged."""
        data = b"My Generic Node"
        device = create_mesh_device(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            app_data=data,
        )
        assert device.device_type == DeviceType.GENERIC
