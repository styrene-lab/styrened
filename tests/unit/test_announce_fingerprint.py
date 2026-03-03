"""Unit tests for system fingerprint in announce data.

Tests parse_announce_data() handling of the 7th field (system_fingerprint)
and MeshDevice.system_fingerprint field.
"""

from styrened.models.mesh_device import (
    DeviceType,
    MeshDevice,
    create_mesh_device,
    parse_announce_data,
)


class TestParseAnnounceDataFingerprint:
    """Tests for parse_announce_data() with system fingerprint field."""

    def test_parse_with_fingerprint(self):
        """7-field announce should parse fingerprint correctly."""
        data = b"styrene:my-node:0.9.1:hub,api:abcd1234:SN:nixos|24.11|x86_64|zah57xw"
        name, dtype, caps, version, lxmf, short, fingerprint, _nn = parse_announce_data(data)
        assert name == "my-node"
        assert dtype == DeviceType.STYRENE_NODE
        assert caps == ["hub", "api"]
        assert version == "0.9.1"
        assert lxmf == "abcd1234"
        assert short == "SN"
        assert fingerprint == "nixos|24.11|x86_64|zah57xw"

    def test_parse_without_fingerprint_legacy(self):
        """6-field (legacy) announce should return None fingerprint."""
        data = b"styrene:my-node:0.9.1:hub,api:abcd1234:SN"
        name, dtype, caps, version, lxmf, short, fingerprint, _nn = parse_announce_data(data)
        assert name == "my-node"
        assert version == "0.9.1"
        assert short == "SN"
        assert fingerprint is None

    def test_parse_minimal_styrene_announce(self):
        """Minimal 'styrene' announce (no fields) returns None fingerprint."""
        data = b"styrene"
        _, _, _, _, _, _, fingerprint, _ = parse_announce_data(data)
        assert fingerprint is None

    def test_parse_4_field_legacy(self):
        """4-field legacy announce: styrene:name:version:caps."""
        data = b"styrene:old-node:0.1.0:node"
        name, dtype, caps, version, lxmf, short, fingerprint, _nn = parse_announce_data(data)
        assert name == "old-node"
        assert version == "0.1.0"
        assert lxmf is None
        assert short is None
        assert fingerprint is None

    def test_parse_fingerprint_no_nixos_gen(self):
        """Fingerprint with empty NixOS generation (non-NixOS)."""
        data = b"styrene:deb-node:0.9.1:node::SN:debian|13|x86_64|"
        _, _, _, _, _, _, fingerprint, _ = parse_announce_data(data)
        assert fingerprint == "debian|13|x86_64|"

    def test_parse_rnode_no_fingerprint(self):
        """RNode announces don't have fingerprint field."""
        data = b"rnode:my-rnode"
        _, dtype, _, _, _, _, fingerprint, _ = parse_announce_data(data)
        assert dtype == DeviceType.RNODE
        assert fingerprint is None

    def test_parse_none_appdata(self):
        """None app_data returns None fingerprint."""
        _, _, _, _, _, _, fingerprint, _ = parse_announce_data(None)
        assert fingerprint is None

    def test_parse_empty_fingerprint_field(self):
        """Empty 7th field returns None (not empty string)."""
        data = b"styrene:node:0.9.1:node:lxmf:SN:"
        _, _, _, _, _, _, fingerprint, _ = parse_announce_data(data)
        assert fingerprint is None

    def test_parse_overlong_fingerprint_rejected(self):
        """Fingerprint exceeding 64 chars is rejected."""
        long_fp = "a" * 65
        data = f"styrene:node:0.9.1:node:lxmf:SN:{long_fp}".encode()
        _, _, _, _, _, _, fingerprint, _ = parse_announce_data(data)
        assert fingerprint is None

    def test_parse_fingerprint_with_bad_chars_rejected(self):
        """Fingerprint with HTML/injection chars is rejected."""
        data = b"styrene:node:0.9.1:node:lxmf:SN:<script>alert(1)</script>"
        _, _, _, _, _, _, fingerprint, _ = parse_announce_data(data)
        assert fingerprint is None

    def test_parse_fingerprint_max_length_accepted(self):
        """Fingerprint at exactly 64 chars is accepted."""
        fp = "nixos|24.11|x86_64|" + "a" * (64 - len("nixos|24.11|x86_64|"))
        data = f"styrene:node:0.9.1:node:lxmf:SN:{fp}".encode()
        _, _, _, _, _, _, fingerprint, _ = parse_announce_data(data)
        assert fingerprint == fp

    def test_parse_valid_fingerprint_chars(self):
        """Fingerprint with dots, dashes, pipes, alphanumeric passes."""
        data = b"styrene:node:0.9.1:node:lxmf:SN:nixos|24.11-pre|x86_64|zah57xw"
        _, _, _, _, _, _, fingerprint, _ = parse_announce_data(data)
        assert fingerprint == "nixos|24.11-pre|x86_64|zah57xw"


class TestMeshDeviceFingerprint:
    """Tests for MeshDevice.system_fingerprint field."""

    def test_field_default_none(self):
        """system_fingerprint defaults to None."""
        device = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=0,
        )
        assert device.system_fingerprint is None

    def test_field_set_explicitly(self):
        """system_fingerprint can be set explicitly."""
        device = MeshDevice(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            name="test",
            device_type=DeviceType.STYRENE_NODE,
            last_announce=0,
            system_fingerprint="nixos|24.11|x86_64|zah57xw",
        )
        assert device.system_fingerprint == "nixos|24.11|x86_64|zah57xw"


class TestCreateMeshDeviceFingerprint:
    """Tests for create_mesh_device() with fingerprint in app_data."""

    def test_create_with_fingerprint(self):
        """create_mesh_device populates system_fingerprint from 7-field announce."""
        app_data = b"styrene:test-node:0.9.1:hub:abcd:SN:nixos|24.11|x86_64|zah57xw"
        device = create_mesh_device(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            app_data=app_data,
        )
        assert device.system_fingerprint == "nixos|24.11|x86_64|zah57xw"

    def test_create_without_fingerprint(self):
        """create_mesh_device returns None fingerprint for 6-field announce."""
        app_data = b"styrene:test-node:0.9.1:hub:abcd:SN"
        device = create_mesh_device(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            app_data=app_data,
        )
        assert device.system_fingerprint is None


class TestAnnounceRoundtrip:
    """Integration-style test: build announce -> parse -> verify fingerprint."""

    def test_roundtrip_with_fingerprint(self):
        """Announce data with fingerprint survives encode/parse roundtrip."""
        # Simulate what daemon._build_announce_data() will produce
        fingerprint = "nixos|24.11|x86_64|zah57xw"
        announce = f"styrene:my-host:0.9.1:hub,api:lxmfdest:SN:{fingerprint}".encode()

        device = create_mesh_device(
            destination_hash="a" * 32,
            identity_hash="b" * 32,
            app_data=announce,
        )
        assert device.name == "my-host"
        assert device.version == "0.9.1"
        assert device.capabilities == ["hub", "api"]
        assert device.system_fingerprint == fingerprint
