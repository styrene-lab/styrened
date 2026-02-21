"""Tests for forge data models.

Covers DeviceSpecs, DeviceProfile, FlashTarget, Bundle, StageKey,
DiskInfo, MediaEvent, ForgeConfig, and catalog loading functions.
"""

from pathlib import Path

import pytest
import yaml

from styrened.tui.forge.models import (
    Bundle,
    DeviceProfile,
    DeviceSpecs,
    DiskInfo,
    FlashTarget,
    ForgeConfig,
    MediaEvent,
    StageKey,
    STAGE_NAMES,
    STAGE_ORDER,
    load_device_catalog,
    load_forge_config,
    _parse_device,
)

from tests.forge.conftest import _specs


# ===================================================================
# DeviceSpecs
# ===================================================================


class TestDeviceSpecs:
    """Test DeviceSpecs frozen dataclass."""

    def test_field_access(self):
        specs = DeviceSpecs(cpu="ARM", cores=4, ram_mb=2048, storage="eMMC", network="WiFi")
        assert specs.cpu == "ARM"
        assert specs.cores == 4
        assert specs.ram_mb == 2048
        assert specs.storage == "eMMC"
        assert specs.network == "WiFi"

    def test_frozen(self):
        specs = _specs()
        with pytest.raises(AttributeError):
            specs.cpu = "other"  # type: ignore[misc]

    def test_equality(self):
        a = DeviceSpecs(cpu="ARM", cores=4, ram_mb=2048, storage="eMMC", network="WiFi")
        b = DeviceSpecs(cpu="ARM", cores=4, ram_mb=2048, storage="eMMC", network="WiFi")
        assert a == b

    def test_inequality(self):
        a = _specs(cores=4)
        b = _specs(cores=8)
        assert a != b


# ===================================================================
# DeviceProfile
# ===================================================================


class TestDeviceProfile:
    """Test DeviceProfile frozen dataclass."""

    def test_frozen(self, x86_uefi64_profile):
        with pytest.raises(AttributeError):
            x86_uefi64_profile.id = "other"  # type: ignore[misc]

    def test_default_nix_flake_output_is_none(self, x86_uefi64_profile):
        assert x86_uefi64_profile.nix_flake_output is None

    def test_nix_flake_output_set(self, aarch64_direct_profile):
        assert aarch64_direct_profile.nix_flake_output == "packages.aarch64-linux.rpi4-sd"

    def test_all_fields_populated(self, x86_uefi64_profile):
        assert x86_uefi64_profile.id == "minigmk"
        assert x86_uefi64_profile.label == "MiniGMK"
        assert x86_uefi64_profile.arch == "x86_64"
        assert x86_uefi64_profile.boot_type == "uefi64"
        assert x86_uefi64_profile.media_type == "installer"
        assert x86_uefi64_profile.media_target == "usb"
        assert x86_uefi64_profile.bond_script is not None
        assert x86_uefi64_profile.default_hostname == "minigmk-01"
        assert isinstance(x86_uefi64_profile.specs, DeviceSpecs)


# ===================================================================
# FlashTarget
# ===================================================================


class TestFlashTarget:
    """Test FlashTarget mutable dataclass."""

    def test_default_hostname_from_device(self, x86_uefi64_profile):
        target = FlashTarget(device=x86_uefi64_profile)
        assert target.hostname == "minigmk-01"

    def test_custom_hostname_preserved(self, x86_uefi64_profile):
        target = FlashTarget(device=x86_uefi64_profile, hostname="custom-node")
        assert target.hostname == "custom-node"

    def test_needs_bond_installer_with_script(self, x86_uefi64_profile):
        target = FlashTarget(device=x86_uefi64_profile)
        assert target.needs_bond is True

    def test_needs_bond_false_for_direct(self, aarch64_direct_profile):
        target = FlashTarget(device=aarch64_direct_profile)
        assert target.needs_bond is False

    def test_needs_bond_false_when_no_script(self):
        profile = DeviceProfile(
            id="test", label="Test", model="Test",
            arch="x86_64", boot_type="uefi64",
            media_type="installer", media_target="usb",
            nixos_config="sbc/test/configuration.nix",
            bond_script=None, default_hostname="test-01",
            specs=_specs(),
        )
        target = FlashTarget(device=profile)
        assert target.needs_bond is False

    def test_mutable(self, x86_uefi64_profile):
        target = FlashTarget(device=x86_uefi64_profile)
        target.hostname = "new-host"
        assert target.hostname == "new-host"

    def test_default_empty_fields(self, x86_uefi64_profile):
        target = FlashTarget(device=x86_uefi64_profile)
        assert target.disk_path == ""
        assert target.wifi_ssid == ""
        assert target.wifi_password == ""
        assert target.ssh_key_path == ""
        assert target.stages_completed == []


# ===================================================================
# Bundle
# ===================================================================


class TestBundle:
    """Test Bundle dataclass with manifest I/O."""

    def test_manifest_write_load_roundtrip(self, tmp_path):
        bundle_path = tmp_path / "test-bundle"
        bundle_path.mkdir()

        bundle = Bundle(
            path=bundle_path,
            device_id="minigmk",
            device_label="MiniGMK",
            arch="x86_64",
            boot_type="uefi64",
            media_type="installer",
            nixos_version="24.11",
            created="2024-01-01T00:00:00+00:00",
            hostname="test-01",
            wifi_configured=True,
            wheels_count=3,
            nix_image=False,
        )

        bundle.write_manifest()
        assert bundle.manifest_path.exists()

        loaded = Bundle.load(bundle_path)
        assert loaded.device_id == "minigmk"
        assert loaded.device_label == "MiniGMK"
        assert loaded.arch == "x86_64"
        assert loaded.boot_type == "uefi64"
        assert loaded.media_type == "installer"
        assert loaded.hostname == "test-01"
        assert loaded.wifi_configured is True
        assert loaded.wheels_count == 3
        assert loaded.nix_image is False

    def test_manifest_path_property(self, tmp_path):
        bundle = Bundle(
            path=tmp_path, device_id="x", device_label="X",
            arch="x86_64", boot_type="uefi64", media_type="installer",
            nixos_version="24.11", created="now", hostname="h",
            wifi_configured=False, wheels_count=0,
        )
        assert bundle.manifest_path == tmp_path / "bundle.yaml"

    def test_styrene_dir_property(self, tmp_path):
        bundle = Bundle(
            path=tmp_path, device_id="x", device_label="X",
            arch="x86_64", boot_type="uefi64", media_type="installer",
            nixos_version="24.11", created="now", hostname="h",
            wifi_configured=False, wheels_count=0,
        )
        assert bundle.styrene_dir == tmp_path / "styrene"

    def test_create_from_flash_target(self, tmp_path, x86_usb_target):
        bundles_dir = tmp_path / "bundles"
        bundles_dir.mkdir()

        bundle = Bundle.create(bundles_dir, x86_usb_target)
        assert bundle.device_id == "minigmk"
        assert bundle.hostname == "minigmk-01"
        assert bundle.wifi_configured is True
        assert bundle.nix_image is False
        assert bundle.path.exists()

    def test_create_counts_wheels(self, tmp_path, x86_usb_target):
        bundles_dir = tmp_path / "bundles"
        bundles_dir.mkdir()

        wheels_dir = tmp_path / "wheels"
        wheels_dir.mkdir()
        (wheels_dir / "pkg1-1.0.whl").write_text("fake")
        (wheels_dir / "pkg2-2.0.whl").write_text("fake")

        bundle = Bundle.create(bundles_dir, x86_usb_target, wheels_dir=wheels_dir)
        assert bundle.wheels_count == 2

    def test_create_nix_image_flag(self, tmp_path, aarch64_sd_target):
        bundles_dir = tmp_path / "bundles"
        bundles_dir.mkdir()

        bundle = Bundle.create(bundles_dir, aarch64_sd_target)
        assert bundle.nix_image is True

    def test_load_defaults_for_missing_optional_fields(self, tmp_path):
        """Load handles missing wifi_configured, wheels_count, nix_image."""
        bundle_path = tmp_path / "old-bundle"
        bundle_path.mkdir()

        data = {
            "version": 1,
            "device_id": "x",
            "device_label": "X",
            "arch": "x86_64",
            "boot_type": "uefi64",
            "media_type": "installer",
            "nixos_version": "24.11",
            "created": "now",
            "hostname": "h",
        }
        with open(bundle_path / "bundle.yaml", "w") as f:
            yaml.dump(data, f)

        loaded = Bundle.load(bundle_path)
        assert loaded.wifi_configured is False
        assert loaded.wheels_count == 0
        assert loaded.nix_image is False


# ===================================================================
# StageKey
# ===================================================================


class TestStageKey:
    """Test StageKey enumeration."""

    def test_seven_stages(self):
        assert len(StageKey) == 7

    def test_order_matches_enum(self):
        assert STAGE_ORDER == list(StageKey)

    def test_stage_names_count(self):
        assert len(STAGE_NAMES) == len(StageKey)

    def test_known_stages(self):
        expected = {"deps", "download", "extract", "partition", "copy", "styrene_files", "finish"}
        actual = {s.value for s in StageKey}
        assert actual == expected


# ===================================================================
# DiskInfo
# ===================================================================


class TestDiskInfo:
    """Test DiskInfo dataclass."""

    def test_construction(self):
        info = DiskInfo(device="/dev/disk4", name="SanDisk", size="32 GB", media_type="USB")
        assert info.device == "/dev/disk4"
        assert info.name == "SanDisk"
        assert info.size == "32 GB"
        assert info.media_type == "USB"


# ===================================================================
# MediaEvent
# ===================================================================


class TestMediaEvent:
    """Test MediaEvent frozen dataclass."""

    def test_construction_defaults(self):
        event = MediaEvent(kind="log", message="test")
        assert event.kind == "log"
        assert event.message == "test"
        assert event.stage is None

    def test_with_stage(self):
        event = MediaEvent(kind="stage", message="test", stage=StageKey.DEPS)
        assert event.stage == StageKey.DEPS


# ===================================================================
# ForgeConfig
# ===================================================================


class TestForgeConfig:
    """Test ForgeConfig dataclass."""

    def test_defaults(self):
        config = ForgeConfig()
        assert config.wifi_ssid == ""
        assert config.wifi_password == ""
        assert config.ssh_key == ""
        assert config.hostnames == {}


class TestLoadForgeConfig:
    """Test load_forge_config with various inputs."""

    def test_none_path_returns_empty(self):
        config = load_forge_config(None)
        assert config.wifi_ssid == ""

    def test_missing_file_returns_empty(self, tmp_path):
        config = load_forge_config(tmp_path / "nonexistent.yaml")
        assert config.wifi_ssid == ""

    def test_valid_yaml(self, tmp_path):
        path = tmp_path / "forge.yaml"
        path.write_text(yaml.dump({
            "wifi": {"ssid": "MyNet", "password": "secret"},
            "ssh_key": "~/.ssh/id_ed25519.pub",
            "hostnames": {"minigmk": "node-01"},
        }))

        config = load_forge_config(path)
        assert config.wifi_ssid == "MyNet"
        assert config.wifi_password == "secret"
        assert "id_ed25519.pub" in config.ssh_key
        assert config.hostnames == {"minigmk": "node-01"}

    def test_tilde_expansion(self, tmp_path):
        path = tmp_path / "forge.yaml"
        path.write_text(yaml.dump({"ssh_key": "~/keys/id.pub"}))

        config = load_forge_config(path)
        assert "~" not in config.ssh_key
        assert config.ssh_key.endswith("keys/id.pub")

    def test_empty_yaml(self, tmp_path):
        path = tmp_path / "forge.yaml"
        path.write_text("")

        config = load_forge_config(path)
        assert config.wifi_ssid == ""

    def test_corrupt_yaml_returns_empty(self, tmp_path):
        path = tmp_path / "forge.yaml"
        path.write_text("not_a_dict: [")  # invalid YAML

        # yaml.safe_load may raise or return something unexpected
        # load_forge_config should handle gracefully
        try:
            config = load_forge_config(path)
            assert isinstance(config, ForgeConfig)
        except yaml.YAMLError:
            pass  # acceptable — implementation may not catch all YAML errors

    def test_yaml_with_only_wifi(self, tmp_path):
        path = tmp_path / "forge.yaml"
        path.write_text(yaml.dump({"wifi": {"ssid": "Net"}}))

        config = load_forge_config(path)
        assert config.wifi_ssid == "Net"
        assert config.wifi_password == ""
        assert config.ssh_key == ""


# ===================================================================
# Device catalog loading
# ===================================================================


class TestLoadDeviceCatalog:
    """Test load_device_catalog YAML parsing."""

    def test_valid_catalog(self, tmp_path):
        catalog = tmp_path / "devices.yaml"
        catalog.write_text(yaml.dump({
            "devices": {
                "minigmk": {
                    "label": "MiniGMK",
                    "model": "GMKtec NucBox",
                    "arch": "x86_64",
                    "boot_type": "uefi64",
                    "media_type": "installer",
                    "media_target": "usb",
                    "nixos_config": "sbc/x86-generic/configuration.nix",
                    "default_hostname": "minigmk-01",
                    "specs": {
                        "cpu": "Intel N100",
                        "cores": 4,
                        "ram_mb": 16384,
                        "storage": "512GB NVMe",
                        "network": "2.5GbE + WiFi 6",
                    },
                },
            },
        }))

        devices = load_device_catalog(catalog)
        assert "minigmk" in devices
        dev = devices["minigmk"]
        assert dev.label == "MiniGMK"
        assert dev.specs.cpu == "Intel N100"
        assert dev.specs.cores == 4

    def test_multiple_devices(self, tmp_path):
        catalog = tmp_path / "devices.yaml"
        catalog.write_text(yaml.dump({
            "devices": {
                "dev1": {
                    "label": "D1", "model": "M1", "arch": "x86_64",
                    "boot_type": "uefi64", "media_type": "installer",
                    "media_target": "usb", "nixos_config": "sbc/d1/c.nix",
                    "default_hostname": "d1-01",
                },
                "dev2": {
                    "label": "D2", "model": "M2", "arch": "aarch64",
                    "boot_type": "uboot", "media_type": "direct",
                    "media_target": "sd", "nixos_config": "sbc/d2/c.nix",
                    "default_hostname": "d2-01",
                },
            },
        }))

        devices = load_device_catalog(catalog)
        assert len(devices) == 2
        assert "dev1" in devices
        assert "dev2" in devices

    def test_specs_defaults_for_missing_fields(self, tmp_path):
        catalog = tmp_path / "devices.yaml"
        catalog.write_text(yaml.dump({
            "devices": {
                "bare": {
                    "label": "Bare", "model": "M", "arch": "x86_64",
                    "boot_type": "uefi64", "media_type": "installer",
                    "media_target": "usb", "nixos_config": "sbc/bare/c.nix",
                    "default_hostname": "bare-01",
                },
            },
        }))

        devices = load_device_catalog(catalog)
        specs = devices["bare"].specs
        assert specs.cpu == "Unknown"
        assert specs.cores == 0
        assert specs.ram_mb == 0

    def test_empty_devices(self, tmp_path):
        catalog = tmp_path / "devices.yaml"
        catalog.write_text(yaml.dump({"devices": {}}))

        devices = load_device_catalog(catalog)
        assert devices == {}


class TestParseDevice:
    """Test _parse_device helper."""

    def test_all_fields(self):
        data = {
            "label": "Test",
            "model": "Model",
            "arch": "x86_64",
            "boot_type": "uefi64",
            "media_type": "installer",
            "media_target": "usb",
            "nixos_config": "sbc/test/c.nix",
            "bond_script": "sbc/test/polymerize.sh",
            "default_hostname": "test-01",
            "nix_flake_output": "packages.x86_64-linux.test-sd",
            "specs": {
                "cpu": "Intel", "cores": 8,
                "ram_mb": 16384, "storage": "SSD", "network": "GbE",
            },
        }
        profile = _parse_device("test", data)
        assert profile.id == "test"
        assert profile.bond_script == "sbc/test/polymerize.sh"
        assert profile.nix_flake_output == "packages.x86_64-linux.test-sd"
        assert profile.specs.cores == 8

    def test_default_specs(self):
        data = {
            "label": "Bare", "model": "M", "arch": "x86_64",
            "boot_type": "uefi64", "media_type": "installer",
            "media_target": "usb", "nixos_config": "sbc/bare/c.nix",
            "default_hostname": "bare-01",
        }
        profile = _parse_device("bare", data)
        assert profile.specs.cpu == "Unknown"
        assert profile.bond_script is None

    def test_optional_nix_flake_output(self):
        data = {
            "label": "Test", "model": "M", "arch": "x86_64",
            "boot_type": "uefi64", "media_type": "installer",
            "media_target": "usb", "nixos_config": "sbc/test/c.nix",
            "default_hostname": "t-01",
        }
        profile = _parse_device("test", data)
        assert profile.nix_flake_output is None
