"""Tests for the rewritten ProvisionScreen."""



from styrened.tui.forge.models import (
    DeviceProfile,
    DeviceSpecs,
    FlashTarget,
    ForgeConfig,
    MediaEvent,
    StageKey,
    load_device_catalog,
)
from styrened.tui.screens.provision import ProvisionScreen

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_specs(**overrides) -> DeviceSpecs:
    defaults = {"cpu": "Test", "cores": 4, "ram_mb": 4096, "storage": "test", "network": "test"}
    defaults.update(overrides)
    return DeviceSpecs(**defaults)


def _make_device(dev_id: str = "test-dev", **overrides) -> DeviceProfile:
    defaults = {
        "id": dev_id,
        "label": "Test Device",
        "model": "Test Model",
        "arch": "x86_64",
        "boot_type": "uefi64",
        "media_type": "installer",
        "media_target": "usb",
        "nixos_config": "sbc/x86-generic/configuration.nix",
        "bond_script": "sbc/x86-generic/polymerize.sh",
        "default_hostname": "test-01",
        "specs": _make_specs(),
    }
    defaults.update(overrides)
    return DeviceProfile(**defaults)


# ---------------------------------------------------------------------------
# ProvisionScreen instantiation
# ---------------------------------------------------------------------------


class TestProvisionScreenInstantiation:
    """Test ProvisionScreen can be created and has correct initial state."""

    def test_instantiation(self):
        """Screen can be instantiated."""
        screen = ProvisionScreen()
        assert screen is not None

    def test_initial_state_no_selections(self):
        """Screen starts with no selections."""
        screen = ProvisionScreen()
        assert screen._selected_device is None
        assert screen._selected_disk is None
        assert screen._config == {}
        assert screen._flash_worker is None

    def test_initial_state_empty_devices(self):
        """Screen starts with empty device catalog."""
        screen = ProvisionScreen()
        assert screen._devices == {}

    def test_initial_forge_config_empty(self):
        """Screen starts with default (empty) forge config."""
        screen = ProvisionScreen()
        assert screen._forge_config.wifi_ssid == ""
        assert screen._forge_config.wifi_password == ""
        assert screen._forge_config.ssh_key == ""

    def test_initial_edge_dir_none(self):
        """Screen starts with no edge_dir."""
        screen = ProvisionScreen()
        assert screen._edge_dir is None


# ---------------------------------------------------------------------------
# Device catalog loading
# ---------------------------------------------------------------------------


class TestDeviceCatalogLoading:
    """Test loading device catalog from bundled YAML."""

    def test_load_bundled_catalog(self):
        """Bundled devices.yaml can be loaded."""
        from styrened.tui.forge.models import get_device_catalog_path

        path = get_device_catalog_path()
        devices = load_device_catalog(path)
        assert len(devices) > 0

    def test_bundled_catalog_has_expected_devices(self):
        """Bundled catalog contains known device IDs."""
        from styrened.tui.forge.models import get_device_catalog_path

        path = get_device_catalog_path()
        devices = load_device_catalog(path)
        # These should be present from the styrene-edge catalog
        assert "rpi4" in devices
        assert "minigmk" in devices

    def test_device_profile_fields(self):
        """Device profiles have required fields populated."""
        from styrened.tui.forge.models import get_device_catalog_path

        path = get_device_catalog_path()
        devices = load_device_catalog(path)
        rpi4 = devices["rpi4"]
        assert rpi4.label == "RPi 4B"
        assert rpi4.arch == "aarch64"
        assert rpi4.media_target == "sd"
        assert rpi4.specs.cores > 0


# ---------------------------------------------------------------------------
# FlashTarget construction
# ---------------------------------------------------------------------------


class TestFlashTargetConstruction:
    """Test building FlashTarget from selections."""

    def test_flash_target_from_selections(self):
        """FlashTarget correctly combines device, disk, and config."""
        device = _make_device()
        target = FlashTarget(
            device=device,
            disk_path="/dev/disk4",
            disk_name="Test USB",
            disk_size="32 GB",
            hostname="my-node",
            wifi_ssid="TestNet",
            wifi_password="secret",
            ssh_key_path="~/.ssh/id_ed25519.pub",
        )
        assert target.device.id == "test-dev"
        assert target.disk_path == "/dev/disk4"
        assert target.hostname == "my-node"
        assert target.wifi_ssid == "TestNet"

    def test_flash_target_default_hostname(self):
        """FlashTarget uses device default_hostname when not specified."""
        device = _make_device(default_hostname="auto-host")
        target = FlashTarget(device=device)
        assert target.hostname == "auto-host"

    def test_flash_target_needs_bond(self):
        """needs_bond is True for installer devices with bond_script."""
        device = _make_device(media_type="installer", bond_script="sbc/x86-generic/polymerize.sh")
        target = FlashTarget(device=device)
        assert target.needs_bond is True

    def test_flash_target_no_bond_for_direct(self):
        """needs_bond is False for direct-flash devices."""
        device = _make_device(media_type="direct", bond_script=None)
        target = FlashTarget(device=device)
        assert target.needs_bond is False


# ---------------------------------------------------------------------------
# MediaEvent stream consumption
# ---------------------------------------------------------------------------


class TestMediaEventConsumption:
    """Test that ForgeLog correctly processes MediaEvent streams."""

    def test_stage_events_update_tracker(self):
        """Stage events are tracked by ForgeLog."""
        from styrened.tui.widgets.forge_log import ForgeLog

        log = ForgeLog()
        log.handle_event(MediaEvent(kind="stage", message="Deps", stage=StageKey.DEPS))
        assert log._current_stage == StageKey.DEPS

    def test_log_events_accumulate(self):
        """Log events accumulate in ForgeLog."""
        from styrened.tui.widgets.forge_log import ForgeLog

        log = ForgeLog()
        log.handle_event(MediaEvent(kind="log", message="Line 1"))
        log.handle_event(MediaEvent(kind="log", message="Line 2"))
        assert len(log._log_lines) == 2

    def test_error_event_sets_state(self):
        """Error events set error state."""
        from styrened.tui.widgets.forge_log import ForgeLog

        log = ForgeLog()
        log.handle_event(MediaEvent(kind="error", message="Fail"))
        assert log.is_error

    def test_complete_event_sets_state(self):
        """Complete events set complete state."""
        from styrened.tui.widgets.forge_log import ForgeLog

        log = ForgeLog()
        log.handle_event(MediaEvent(kind="complete", message="Done"))
        assert log.is_complete


# ---------------------------------------------------------------------------
# ForgeConfig resolution
# ---------------------------------------------------------------------------


class TestForgeConfigResolution:
    """Test forge.yaml loading and defaults."""

    def test_missing_forge_yaml_returns_defaults(self):
        """Missing forge.yaml returns empty ForgeConfig."""
        config = ForgeConfig()
        assert config.wifi_ssid == ""
        assert config.wifi_password == ""
        assert config.ssh_key == ""
        assert config.hostnames == {}

    def test_forge_config_from_yaml(self, tmp_path):
        """forge.yaml populates ForgeConfig correctly."""
        forge_yaml = tmp_path / "forge.yaml"
        forge_yaml.write_text(
            "wifi:\n"
            "  ssid: TestNet\n"
            "  password: secret\n"
            "ssh_key: ~/.ssh/id_ed25519.pub\n"
            "hostnames:\n"
            "  rpi4: my-rpi4\n"
        )
        from styrened.tui.forge.models import load_forge_config

        config = load_forge_config(forge_yaml)
        assert config.wifi_ssid == "TestNet"
        assert config.wifi_password == "secret"
        assert "rpi4" in config.hostnames
        assert config.hostnames["rpi4"] == "my-rpi4"
