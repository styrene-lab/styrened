"""Tests for forge service files: catalog, storage, provisioner."""

from pathlib import Path

import pytest

from styrened.tui.services.catalog import Catalog, load_catalog, validate_profile_hardware
from styrened.tui.services.provisioner import ProvisionResult
from styrened.tui.services.storage import StorageDevice


class TestLoadCatalog:
    def test_returns_catalog(self) -> None:
        catalog = load_catalog()
        assert isinstance(catalog, Catalog)

    def test_hardware_populated(self) -> None:
        catalog = load_catalog()
        assert len(catalog.hardware) >= 3
        assert "rpi4" in catalog.hardware
        assert "x86-generic" in catalog.hardware

    def test_roles_populated(self) -> None:
        catalog = load_catalog()
        assert len(catalog.roles) >= 2
        assert "styrene-node" in catalog.roles

    def test_profiles_populated(self) -> None:
        catalog = load_catalog()
        assert len(catalog.profiles) >= 2
        assert "node" in catalog.profiles

    def test_hardware_fields(self) -> None:
        catalog = load_catalog()
        hw = catalog.hardware["rpi4"]
        assert hw.arch == "aarch64"
        assert hw.boot == "uboot"
        assert "low_power" in hw.traits

    def test_role_fields(self) -> None:
        catalog = load_catalog()
        role = catalog.roles["styrene-node"]
        assert "mesh" in role.provides
        assert role.activity == "nixos-direct"

    def test_profile_fields(self) -> None:
        catalog = load_catalog()
        profile = catalog.profiles["node"]
        assert "styrene-node" in profile.roles
        assert profile.verified  # non-empty

    def test_custom_data_dir(self, tmp_path: Path) -> None:
        from styrened.tui.services.catalog import CatalogLoadError
        with pytest.raises(CatalogLoadError):
            load_catalog(tmp_path)  # missing YAML files → CatalogLoadError


class TestStorageDeviceDisplay:
    def test_display_name_with_label(self) -> None:
        dev = StorageDevice(device="/dev/sdb", size_gb=32, type="sd", mounted=False, label="SDCARD")
        assert "SDCARD" in dev.display_name
        assert "/dev/sdb" in dev.display_name

    def test_display_name_without_label(self) -> None:
        dev = StorageDevice(device="/dev/sdb", size_gb=32, type="sd", mounted=False)
        assert dev.display_name == "/dev/sdb"

    def test_display_size_gb(self) -> None:
        dev = StorageDevice(device="/dev/sdb", size_gb=64, type="usb", mounted=False)
        assert "GB" in dev.display_size

    def test_display_size_sub_gb(self) -> None:
        dev = StorageDevice(device="/dev/sdb", size_gb=0, type="sd", mounted=False)
        assert "MB" in dev.display_size


class TestValidateProfileHardware:
    def test_valid_single_hardware(self) -> None:
        catalog = load_catalog()
        profile = catalog.profiles["node"]
        assert validate_profile_hardware(catalog, profile, ["rpi4"]) is True

    def test_invalid_hardware_id(self) -> None:
        catalog = load_catalog()
        profile = catalog.profiles["node"]
        assert validate_profile_hardware(catalog, profile, ["nonexistent"]) is False

    def test_unverified_combination(self) -> None:
        catalog = load_catalog()
        profile = catalog.profiles["node"]
        # rpi4+rpi-zero2w is not a verified combo for the 'node' profile
        assert validate_profile_hardware(catalog, profile, ["rpi4", "rpi-zero2w"]) is False

    def test_router_profile_with_low_power_hardware(self) -> None:
        catalog = load_catalog()
        profile = catalog.profiles["router"]
        # rpi4 has low_power trait and is in verified list
        assert validate_profile_hardware(catalog, profile, ["rpi4"]) is True

    def test_router_profile_fails_without_required_trait(self) -> None:
        catalog = load_catalog()
        profile = catalog.profiles["router"]
        # x86-generic has no low_power trait
        assert validate_profile_hardware(catalog, profile, ["x86-generic"]) is False


class TestProvisionResult:
    def test_success_instantiation(self) -> None:
        result = ProvisionResult(
            success=True,
            device="/dev/sdb",
            profile="node",
            hardware="rpi4",
            errors=[],
            log="Done",
        )
        assert result.success is True
        assert result.errors == []

    def test_failure_instantiation(self) -> None:
        result = ProvisionResult(
            success=False,
            device="/dev/sdb",
            profile="node",
            hardware="rpi4",
            errors=["Device is mounted"],
            log="ERROR: Device is mounted",
        )
        assert result.success is False
        assert len(result.errors) == 1
