"""Tests for catalog data models."""

from styrened.tui.models.catalog import Hardware, Profile, Role


class TestHardware:
    """Tests for Hardware model."""

    def test_hardware_creation(self):
        """Test creating a hardware instance."""
        hw = Hardware(
            id="rpi4",
            label="Raspberry Pi 4",
            arch="aarch64",
            boot="uboot",
            activity="nixos-direct",
            traits=["low_power", "gpio", "wifi"],
        )
        assert hw.id == "rpi4"
        assert hw.label == "Raspberry Pi 4"
        assert hw.arch == "aarch64"
        assert hw.boot == "uboot"
        assert hw.activity == "nixos-direct"
        assert hw.traits == ["low_power", "gpio", "wifi"]
        assert hw.type is None

    def test_hardware_with_type(self):
        """Test creating a hardware instance with optional type."""
        hw = Hardware(
            id="gl-opal",
            label="GL.iNet Opal",
            arch="",
            boot="",
            activity="openwrt-flash",
            traits=["wifi", "ethernet", "usb_powered"],
            type="router",
        )
        assert hw.type == "router"

    def test_has_trait(self):
        """Test checking for specific trait."""
        hw = Hardware(
            id="rpi4",
            label="Raspberry Pi 4",
            arch="aarch64",
            boot="uboot",
            activity="nixos-direct",
            traits=["low_power", "gpio", "wifi"],
        )
        assert hw.has_trait("wifi")
        assert hw.has_trait("gpio")
        assert not hw.has_trait("has_display")

    def test_has_all_traits(self):
        """Test checking for multiple traits."""
        hw = Hardware(
            id="t100ta",
            label="ASUS T100TA",
            arch="x86_64",
            boot="uefi32",
            activity="nixos-installer",
            traits=["has_display", "has_input", "low_memory", "wifi"],
        )
        assert hw.has_all_traits(["has_display", "has_input"])
        assert hw.has_all_traits(["wifi"])
        assert not hw.has_all_traits(["has_display", "gpio"])
        assert not hw.has_all_traits(["ethernet"])


class TestRole:
    """Tests for Role model."""

    def test_role_creation(self):
        """Test creating a role instance."""
        role = Role(
            id="styrene-node",
            label="Styrene Node",
            description="NixOS + Reticulum mesh participant",
            activity="nixos-direct",
            provides=["reticulum", "lxmf", "mesh-participation"],
        )
        assert role.id == "styrene-node"
        assert role.label == "Styrene Node"
        assert role.description == "NixOS + Reticulum mesh participant"
        assert role.activity == "nixos-direct"
        assert role.provides == ["reticulum", "lxmf", "mesh-participation"]

    def test_role_with_multiple_activities(self):
        """Test role supporting multiple activities."""
        role = Role(
            id="styrene-node",
            label="Styrene Node",
            description="NixOS + Reticulum mesh participant",
            activity=["nixos-direct", "nixos-installer"],
            provides=["reticulum", "lxmf"],
        )
        assert isinstance(role.activity, list)
        assert "nixos-direct" in role.activity
        assert "nixos-installer" in role.activity

    def test_supports_activity_single(self):
        """Test checking activity support with single activity."""
        role = Role(
            id="mesh-router",
            label="Mesh Router",
            description="802.11s mesh + IP routing",
            activity="openwrt-flash",
            provides=["802.11s", "ip-routing", "dhcp"],
        )
        assert role.supports_activity("openwrt-flash")
        assert not role.supports_activity("nixos-direct")

    def test_supports_activity_multiple(self):
        """Test checking activity support with multiple activities."""
        role = Role(
            id="styrene-node",
            label="Styrene Node",
            description="NixOS + Reticulum mesh participant",
            activity=["nixos-direct", "nixos-installer"],
            provides=["reticulum", "lxmf"],
        )
        assert role.supports_activity("nixos-direct")
        assert role.supports_activity("nixos-installer")
        assert not role.supports_activity("openwrt-flash")


class TestProfile:
    """Tests for Profile model."""

    def test_profile_creation(self):
        """Test creating a profile instance."""
        profile = Profile(
            id="node",
            label="Node",
            description="Basic mesh participant",
            roles=["styrene-node"],
            verified=[["rpi4"], ["rpi-zero2w"], ["t100ta"]],
        )
        assert profile.id == "node"
        assert profile.label == "Node"
        assert profile.description == "Basic mesh participant"
        assert profile.roles == ["styrene-node"]
        assert len(profile.verified) == 3
        assert profile.requires_traits is None

    def test_profile_with_traits(self):
        """Test profile with trait requirements."""
        profile = Profile(
            id="workstation",
            label="Workstation",
            description="Node with local display and input",
            roles=["styrene-node"],
            verified=[["t100ta"], ["q502l"]],
            requires_traits=["has_display", "has_input"],
        )
        assert profile.requires_traits == ["has_display", "has_input"]

    def test_profile_multi_device(self):
        """Test multi-device profile."""
        profile = Profile(
            id="edge-router",
            label="Edge Router",
            description="Mesh node + routing (multi-device)",
            roles=["styrene-node", "mesh-router"],
            verified=[["rpi4", "gl-opal"]],
        )
        assert len(profile.roles) == 2
        assert profile.verified == [["rpi4", "gl-opal"]]

    def test_requires_hardware_count_single(self):
        """Test hardware count for single-device profile."""
        profile = Profile(
            id="node",
            label="Node",
            description="Basic mesh participant",
            roles=["styrene-node"],
            verified=[["rpi4"], ["t100ta"]],
        )
        assert profile.requires_hardware_count() == 1

    def test_requires_hardware_count_multi(self):
        """Test hardware count for multi-device profile."""
        profile = Profile(
            id="edge-router",
            label="Edge Router",
            description="Mesh node + routing",
            roles=["styrene-node", "mesh-router"],
            verified=[["rpi4", "gl-opal"]],
        )
        assert profile.requires_hardware_count() == 2

    def test_is_multi_device(self):
        """Test multi-device detection."""
        single = Profile(
            id="node",
            label="Node",
            description="Basic mesh participant",
            roles=["styrene-node"],
            verified=[["rpi4"]],
        )
        assert not single.is_multi_device()

        multi = Profile(
            id="edge-router",
            label="Edge Router",
            description="Mesh node + routing",
            roles=["styrene-node", "mesh-router"],
            verified=[["rpi4", "gl-opal"]],
        )
        assert multi.is_multi_device()

    def test_is_verified_combination(self):
        """Test checking verified hardware combinations."""
        profile = Profile(
            id="node",
            label="Node",
            description="Basic mesh participant",
            roles=["styrene-node"],
            verified=[["rpi4"], ["t100ta"], ["q502l"]],
        )
        assert profile.is_verified_combination(["rpi4"])
        assert profile.is_verified_combination(["t100ta"])
        assert not profile.is_verified_combination(["gl-opal"])
        assert not profile.is_verified_combination(["rpi4", "gl-opal"])

    def test_is_verified_combination_multi_device(self):
        """Test verified combinations for multi-device profile."""
        profile = Profile(
            id="edge-router",
            label="Edge Router",
            description="Mesh node + routing",
            roles=["styrene-node", "mesh-router"],
            verified=[["rpi4", "gl-opal"]],
        )
        assert profile.is_verified_combination(["rpi4", "gl-opal"])
        # Order shouldn't matter
        assert profile.is_verified_combination(["gl-opal", "rpi4"])
        assert not profile.is_verified_combination(["rpi4"])
        assert not profile.is_verified_combination(["t100ta", "gl-opal"])
