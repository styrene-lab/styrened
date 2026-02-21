"""Tests for catalog service."""

import tempfile
from pathlib import Path

import pytest
import yaml

from styrened.tui.services.catalog import (
    Catalog,
    CatalogLoadError,
    load_catalog,
    query_hardware,
    query_profiles,
    query_roles,
    validate_profile_hardware,
)


@pytest.fixture
def temp_catalog_dir():
    """Create a temporary directory with test catalog files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        catalog_path = Path(tmpdir)

        # Create test hardware catalog
        hardware_data = {
            "hardware": {
                "rpi4": {
                    "label": "Raspberry Pi 4",
                    "arch": "aarch64",
                    "boot": "uboot",
                    "activity": "nixos-direct",
                    "traits": ["low_power", "gpio", "wifi"],
                },
                "t100ta": {
                    "label": "ASUS T100TA",
                    "arch": "x86_64",
                    "boot": "uefi32",
                    "activity": "nixos-installer",
                    "traits": ["has_display", "has_input", "wifi"],
                },
                "gl-opal": {
                    "label": "GL.iNet Opal",
                    "type": "router",
                    "arch": "",
                    "boot": "",
                    "activity": "openwrt-flash",
                    "traits": ["wifi", "ethernet"],
                },
            }
        }
        with open(catalog_path / "hardware.yaml", "w") as f:
            yaml.safe_dump(hardware_data, f)

        # Create test roles catalog
        roles_data = {
            "roles": {
                "styrene-node": {
                    "label": "Styrene Node",
                    "description": "NixOS + Reticulum mesh participant",
                    "activity": ["nixos-direct", "nixos-installer"],
                    "provides": ["reticulum", "lxmf"],
                },
                "mesh-router": {
                    "label": "Mesh Router",
                    "description": "802.11s mesh + IP routing",
                    "activity": "openwrt-flash",
                    "provides": ["802.11s", "ip-routing"],
                },
            }
        }
        with open(catalog_path / "roles.yaml", "w") as f:
            yaml.safe_dump(roles_data, f)

        # Create test profiles catalog
        profiles_data = {
            "profiles": {
                "node": {
                    "label": "Node",
                    "description": "Basic mesh participant",
                    "roles": ["styrene-node"],
                    "verified": [["rpi4"], ["t100ta"]],
                },
                "workstation": {
                    "label": "Workstation",
                    "description": "Node with display",
                    "roles": ["styrene-node"],
                    "requires_traits": ["has_display", "has_input"],
                    "verified": [["t100ta"]],
                },
                "edge-router": {
                    "label": "Edge Router",
                    "description": "Multi-device profile",
                    "roles": ["styrene-node", "mesh-router"],
                    "verified": [["rpi4", "gl-opal"]],
                },
            }
        }
        with open(catalog_path / "profiles.yaml", "w") as f:
            yaml.safe_dump(profiles_data, f)

        yield catalog_path


class TestLoadCatalog:
    """Tests for catalog loading."""

    def test_load_catalog_success(self, temp_catalog_dir):
        """Test successfully loading catalog from directory."""
        catalog = load_catalog(temp_catalog_dir)
        assert isinstance(catalog, Catalog)
        assert len(catalog.hardware) == 3
        assert len(catalog.roles) == 2
        assert len(catalog.profiles) == 3

    def test_load_catalog_hardware(self, temp_catalog_dir):
        """Test hardware entries are loaded correctly."""
        catalog = load_catalog(temp_catalog_dir)
        assert "rpi4" in catalog.hardware
        hw = catalog.hardware["rpi4"]
        assert hw.label == "Raspberry Pi 4"
        assert hw.arch == "aarch64"
        assert hw.boot == "uboot"
        assert hw.activity == "nixos-direct"
        assert "wifi" in hw.traits

    def test_load_catalog_roles(self, temp_catalog_dir):
        """Test role entries are loaded correctly."""
        catalog = load_catalog(temp_catalog_dir)
        assert "styrene-node" in catalog.roles
        role = catalog.roles["styrene-node"]
        assert role.label == "Styrene Node"
        assert isinstance(role.activity, list)
        assert "nixos-direct" in role.activity
        assert "reticulum" in role.provides

    def test_load_catalog_profiles(self, temp_catalog_dir):
        """Test profile entries are loaded correctly."""
        catalog = load_catalog(temp_catalog_dir)
        assert "node" in catalog.profiles
        profile = catalog.profiles["node"]
        assert profile.label == "Node"
        assert "styrene-node" in profile.roles
        assert ["rpi4"] in profile.verified

    def test_load_catalog_missing_hardware(self, temp_catalog_dir):
        """Test loading fails gracefully with missing hardware file."""
        (temp_catalog_dir / "hardware.yaml").unlink()
        with pytest.raises(CatalogLoadError, match=r"hardware\.yaml"):
            load_catalog(temp_catalog_dir)

    def test_load_catalog_missing_roles(self, temp_catalog_dir):
        """Test loading fails gracefully with missing roles file."""
        (temp_catalog_dir / "roles.yaml").unlink()
        with pytest.raises(CatalogLoadError, match=r"roles\.yaml"):
            load_catalog(temp_catalog_dir)

    def test_load_catalog_missing_profiles(self, temp_catalog_dir):
        """Test loading fails gracefully with missing profiles file."""
        (temp_catalog_dir / "profiles.yaml").unlink()
        with pytest.raises(CatalogLoadError, match=r"profiles\.yaml"):
            load_catalog(temp_catalog_dir)

    def test_load_catalog_invalid_yaml(self, temp_catalog_dir):
        """Test loading fails with invalid YAML syntax."""
        with open(temp_catalog_dir / "hardware.yaml", "w") as f:
            f.write("invalid: yaml: syntax: [")
        with pytest.raises(CatalogLoadError):
            load_catalog(temp_catalog_dir)


class TestQueryHardware:
    """Tests for hardware queries."""

    def test_query_hardware_all(self, temp_catalog_dir):
        """Test querying all hardware."""
        catalog = load_catalog(temp_catalog_dir)
        hardware = query_hardware(catalog)
        assert len(hardware) == 3
        assert any(hw.id == "rpi4" for hw in hardware)

    def test_query_hardware_by_arch(self, temp_catalog_dir):
        """Test querying hardware by architecture."""
        catalog = load_catalog(temp_catalog_dir)
        hardware = query_hardware(catalog, filters={"arch": "aarch64"})
        assert len(hardware) == 1
        assert hardware[0].id == "rpi4"

    def test_query_hardware_by_activity(self, temp_catalog_dir):
        """Test querying hardware by activity."""
        catalog = load_catalog(temp_catalog_dir)
        hardware = query_hardware(catalog, filters={"activity": "nixos-installer"})
        assert len(hardware) == 1
        assert hardware[0].id == "t100ta"

    def test_query_hardware_by_trait(self, temp_catalog_dir):
        """Test querying hardware by trait."""
        catalog = load_catalog(temp_catalog_dir)
        hardware = query_hardware(catalog, filters={"trait": "has_display"})
        assert len(hardware) == 1
        assert hardware[0].id == "t100ta"

    def test_query_hardware_by_traits(self, temp_catalog_dir):
        """Test querying hardware by multiple traits."""
        catalog = load_catalog(temp_catalog_dir)
        hardware = query_hardware(catalog, filters={"traits": ["has_display", "has_input"]})
        assert len(hardware) == 1
        assert hardware[0].id == "t100ta"

    def test_query_hardware_no_matches(self, temp_catalog_dir):
        """Test querying with no matches."""
        catalog = load_catalog(temp_catalog_dir)
        hardware = query_hardware(catalog, filters={"trait": "nonexistent"})
        assert len(hardware) == 0


class TestQueryRoles:
    """Tests for role queries."""

    def test_query_roles_all(self, temp_catalog_dir):
        """Test querying all roles."""
        catalog = load_catalog(temp_catalog_dir)
        roles = query_roles(catalog)
        assert len(roles) == 2

    def test_query_roles_by_activity(self, temp_catalog_dir):
        """Test querying roles by activity."""
        catalog = load_catalog(temp_catalog_dir)
        roles = query_roles(catalog, filters={"activity": "openwrt-flash"})
        assert len(roles) == 1
        assert roles[0].id == "mesh-router"

    def test_query_roles_by_provides(self, temp_catalog_dir):
        """Test querying roles by provided service."""
        catalog = load_catalog(temp_catalog_dir)
        roles = query_roles(catalog, filters={"provides": "reticulum"})
        assert len(roles) == 1
        assert roles[0].id == "styrene-node"


class TestQueryProfiles:
    """Tests for profile queries."""

    def test_query_profiles_all(self, temp_catalog_dir):
        """Test querying all profiles."""
        catalog = load_catalog(temp_catalog_dir)
        profiles = query_profiles(catalog)
        assert len(profiles) == 3

    def test_query_profiles_by_role(self, temp_catalog_dir):
        """Test querying profiles by role."""
        catalog = load_catalog(temp_catalog_dir)
        profiles = query_profiles(catalog, filters={"role": "mesh-router"})
        assert len(profiles) == 1
        assert profiles[0].id == "edge-router"

    def test_query_profiles_multi_device(self, temp_catalog_dir):
        """Test querying multi-device profiles."""
        catalog = load_catalog(temp_catalog_dir)
        profiles = query_profiles(catalog, filters={"multi_device": True})
        assert len(profiles) == 1
        assert profiles[0].id == "edge-router"


class TestValidateProfileHardware:
    """Tests for profile-hardware validation."""

    def test_validate_profile_hardware_valid_single(self, temp_catalog_dir):
        """Test validating single-device profile with valid hardware."""
        catalog = load_catalog(temp_catalog_dir)
        profile = catalog.profiles["node"]
        result = validate_profile_hardware(catalog, profile, ["rpi4"])
        assert result is True

    def test_validate_profile_hardware_valid_multi(self, temp_catalog_dir):
        """Test validating multi-device profile with valid hardware."""
        catalog = load_catalog(temp_catalog_dir)
        profile = catalog.profiles["edge-router"]
        result = validate_profile_hardware(catalog, profile, ["rpi4", "gl-opal"])
        assert result is True

    def test_validate_profile_hardware_unverified(self, temp_catalog_dir):
        """Test validating with unverified hardware combination."""
        catalog = load_catalog(temp_catalog_dir)
        profile = catalog.profiles["node"]
        result = validate_profile_hardware(catalog, profile, ["gl-opal"])
        assert result is False

    def test_validate_profile_hardware_missing_traits(self, temp_catalog_dir):
        """Test validating with hardware missing required traits."""
        catalog = load_catalog(temp_catalog_dir)
        profile = catalog.profiles["workstation"]
        result = validate_profile_hardware(catalog, profile, ["rpi4"])
        assert result is False

    def test_validate_profile_hardware_valid_traits(self, temp_catalog_dir):
        """Test validating with hardware having required traits."""
        catalog = load_catalog(temp_catalog_dir)
        profile = catalog.profiles["workstation"]
        result = validate_profile_hardware(catalog, profile, ["t100ta"])
        assert result is True

    def test_validate_profile_hardware_wrong_count(self, temp_catalog_dir):
        """Test validating with wrong number of devices."""
        catalog = load_catalog(temp_catalog_dir)
        profile = catalog.profiles["edge-router"]
        result = validate_profile_hardware(catalog, profile, ["rpi4"])
        assert result is False

    def test_validate_profile_hardware_invalid_id(self, temp_catalog_dir):
        """Test validating with non-existent hardware ID."""
        catalog = load_catalog(temp_catalog_dir)
        profile = catalog.profiles["node"]
        result = validate_profile_hardware(catalog, profile, ["nonexistent"])
        assert result is False
