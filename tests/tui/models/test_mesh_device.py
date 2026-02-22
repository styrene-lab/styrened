"""Tests for mesh device models and announce parsing."""

import pytest

from styrened.models.mesh_device import (
    DeviceType,
    MeshDevice,
    NodeStatus,
    create_mesh_device,
    parse_announce_data,
)


class TestParseAnnounceData:
    """Tests for parse_announce_data function."""

    def test_none_app_data_returns_unknown(self):
        """None app_data should return unknown device."""
        name, device_type, capabilities, version, *_ = parse_announce_data(None)
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN
        assert capabilities is None
        assert version is None

    def test_empty_app_data_returns_unknown(self):
        """Empty app_data should return unknown device."""
        name, device_type, capabilities, version, *_ = parse_announce_data(b"")
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN

    def test_binary_app_data_returns_unknown(self):
        """Non-UTF8 binary data should return unknown."""
        name, device_type, capabilities, version, *_ = parse_announce_data(b"\xff\xfe\x00\x01")
        assert name == "binary-data"
        assert device_type == DeviceType.UNKNOWN

    # Styrene node tests
    def test_styrene_simple_announce(self):
        """Simple 'styrene' announce without details."""
        name, device_type, capabilities, version, *_ = parse_announce_data(b"styrene")
        assert name == "styrene-node"
        assert device_type == DeviceType.STYRENE_NODE
        assert capabilities is None
        assert version is None

    def test_styrene_with_hostname(self):
        """Styrene announce with hostname."""
        name, device_type, capabilities, version, *_ = parse_announce_data(b"styrene:mynode")
        assert name == "mynode"
        assert device_type == DeviceType.STYRENE_NODE
        assert version is None
        assert capabilities is None

    def test_styrene_with_hostname_and_version(self):
        """Styrene announce with hostname and version."""
        name, device_type, capabilities, version, *_ = parse_announce_data(b"styrene:mynode:1.0.0")
        assert name == "mynode"
        assert device_type == DeviceType.STYRENE_NODE
        assert version == "1.0.0"
        assert capabilities is None

    def test_styrene_full_format(self):
        """Styrene announce with all fields."""
        name, device_type, capabilities, version, *_ = parse_announce_data(
            b"styrene:mynode:1.0.0:rpc,lxmf"
        )
        assert name == "mynode"
        assert device_type == DeviceType.STYRENE_NODE
        assert version == "1.0.0"
        assert capabilities == ["rpc", "lxmf"]

    def test_styrene_case_insensitive(self):
        """Styrene detection should be case-insensitive."""
        name, device_type, *_ = parse_announce_data(b"STYRENE:MYNODE")
        assert device_type == DeviceType.STYRENE_NODE
        assert name == "MYNODE"

    # RNode tests
    def test_rnode_announce(self):
        """RNode announce parsing."""
        name, device_type, capabilities, version, *_ = parse_announce_data(b"rnode:my-rnode")
        assert name == "my-rnode"
        assert device_type == DeviceType.RNODE
        assert capabilities is None
        assert version is None

    def test_rnode_without_name(self):
        """RNode announce without device name returns empty string."""
        name, device_type, *_ = parse_announce_data(b"rnode:")
        assert name == ""  # Empty after the colon
        assert device_type == DeviceType.RNODE

    def test_rnode_case_insensitive(self):
        """RNode detection should be case-insensitive."""
        _, device_type, *_ = parse_announce_data(b"RNODE:test")
        assert device_type == DeviceType.RNODE

    # JSON app_data tests (LXMF clients like Sideband/NomadNet)
    def test_json_with_display_name(self):
        """JSON app_data with display_name field."""
        name, device_type, *_ = parse_announce_data(b'{"display_name": "Alice"}')
        assert name == "Alice"
        assert device_type == DeviceType.GENERIC

    def test_json_with_name_field(self):
        """JSON app_data with name field (fallback)."""
        name, device_type, *_ = parse_announce_data(b'{"name": "Bob"}')
        assert name == "Bob"
        assert device_type == DeviceType.GENERIC

    def test_json_display_name_truncated(self):
        """Long display names should be truncated to 32 chars."""
        long_name = "A" * 50
        name, device_type, *_ = parse_announce_data(f'{{"display_name": "{long_name}"}}'.encode())
        assert len(name) == 32
        assert name == "A" * 32
        assert device_type == DeviceType.GENERIC

    def test_json_without_name_returns_unknown(self):
        """JSON without display_name or name returns unknown."""
        name, device_type, *_ = parse_announce_data(b'{"foo": "bar"}')
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN

    def test_invalid_json_returns_unknown(self):
        """Invalid JSON that looks like JSON returns unknown."""
        name, device_type, *_ = parse_announce_data(b"{not valid json}")
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN

    # Generic announce tests (the case triggering SIM102)
    def test_generic_simple_string(self):
        """Simple string announce should be treated as generic name."""
        name, device_type, *_ = parse_announce_data(b"my-device")
        assert name == "my-device"
        assert device_type == DeviceType.GENERIC

    def test_generic_rejects_long_strings(self):
        """Strings over 64 chars should be rejected."""
        long_string = "a" * 65
        name, device_type, *_ = parse_announce_data(long_string.encode())
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN

    def test_generic_rejects_hex_strings(self):
        """Hex-prefixed strings should be rejected."""
        name, device_type, *_ = parse_announce_data(b"0x1234abcd")
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN

    def test_generic_rejects_serialized_data_braces(self):
        """Strings with braces (looks like serialized data) should be rejected."""
        name, device_type, *_ = parse_announce_data(b"some{data}")
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN

    def test_generic_rejects_serialized_data_brackets(self):
        """Strings with brackets should be rejected."""
        name, device_type, *_ = parse_announce_data(b"some[data]")
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN

    def test_generic_rejects_serialized_data_parens(self):
        """Strings with parentheses should be rejected."""
        name, device_type, *_ = parse_announce_data(b"some(data)")
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN

    def test_generic_rejects_serialized_data_angles(self):
        """Strings with angle brackets should be rejected."""
        name, device_type, *_ = parse_announce_data(b"some<data>")
        assert name == "unknown"
        assert device_type == DeviceType.UNKNOWN

    def test_generic_allows_hyphens_underscores(self):
        """Generic names with hyphens and underscores are allowed."""
        name, device_type, *_ = parse_announce_data(b"my_device-name")
        assert name == "my_device-name"
        assert device_type == DeviceType.GENERIC

    def test_generic_allows_spaces(self):
        """Generic names with spaces are allowed."""
        name, device_type, *_ = parse_announce_data(b"My Device Name")
        assert name == "My Device Name"
        assert device_type == DeviceType.GENERIC

    def test_generic_allows_64_char_string(self):
        """Exactly 64 char string is allowed."""
        name_64 = "a" * 64
        name, device_type, *_ = parse_announce_data(name_64.encode())
        assert name == name_64
        assert device_type == DeviceType.GENERIC


class TestCreateMeshDevice:
    """Tests for create_mesh_device factory function."""

    def test_creates_device_from_styrene_announce(self):
        """Create device from Styrene announce data."""
        device = create_mesh_device(
            destination_hash="abcd1234" * 4,
            identity_hash="efgh5678" * 4,
            app_data=b"styrene:testnode:1.0.0",
        )
        assert device.name == "testnode"
        assert device.device_type == DeviceType.STYRENE_NODE
        assert device.version == "1.0.0"
        assert device.destination_hash == "abcd1234" * 4
        assert device.identity_hash == "efgh5678" * 4
        assert device.announce_count == 1

    def test_creates_fallback_name_for_unknown(self):
        """Unknown devices get fallback name from destination hash."""
        device = create_mesh_device(
            destination_hash="abcd1234efgh5678",
            identity_hash="ijkl9012mnop3456",
            app_data=None,
        )
        assert device.name == "device-abcd1234"
        assert device.device_type == DeviceType.UNKNOWN

    def test_respects_announce_count(self):
        """Announce count is passed through."""
        device = create_mesh_device(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            app_data=b"test",
            announce_count=5,
        )
        assert device.announce_count == 5


class TestMeshDeviceProperties:
    """Tests for MeshDevice computed properties."""

    def test_identity_short(self):
        """identity_short returns first 8 chars."""
        device = MeshDevice(
            destination_hash="abcd1234efgh5678",
            identity_hash="ijkl9012mnop3456",
            name="test",
            device_type=DeviceType.GENERIC,
            last_announce=0,
        )
        assert device.identity_short == "abcd1234"

    def test_identity_legacy_alias(self):
        """identity property is alias for destination_hash."""
        device = MeshDevice(
            destination_hash="abcd1234efgh5678",
            identity_hash="ijkl9012mnop3456",
            name="test",
            device_type=DeviceType.GENERIC,
            last_announce=0,
        )
        assert device.identity == device.destination_hash

    def test_is_styrene_node(self):
        """is_styrene_node property works correctly."""
        device = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=0,
        )
        assert device.is_styrene_node is True
        assert device.is_rnode is False

    def test_is_rnode(self):
        """is_rnode property works correctly."""
        device = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type=DeviceType.RNODE,
            last_announce=0,
        )
        assert device.is_rnode is True
        assert device.is_styrene_node is False
