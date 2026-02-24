"""Shared fixtures for Forge tests.

Ported from styrene-edge tests/conftest.py with updated imports
for the styrene-tui module layout.
"""

from pathlib import Path

import pytest

from styrened.tui.forge.models import (
    DeviceProfile,
    DeviceSpecs,
    FlashTarget,
    MediaEvent,
    StageKey,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _specs(**overrides: object) -> DeviceSpecs:
    defaults = {"cpu": "Test", "cores": 4, "ram_mb": 4096, "storage": "test", "network": "test"}
    defaults.update(overrides)
    return DeviceSpecs(**defaults)


async def collect(aiter) -> list[MediaEvent]:
    """Drain an async iterator into a list."""
    events = []
    async for e in aiter:
        events.append(e)
    return events


async def collect_nix(aiter):
    """Drain resolve_nix_image, returning (events, final_path)."""
    events = []
    final_path = None
    async for event, path in aiter:
        events.append(event)
        if path is not None:
            final_path = path
    return events, final_path


def stages(events: list[MediaEvent]) -> list[StageKey]:
    """Extract stage transitions from event list."""
    return [e.stage for e in events if e.kind == "stage" and e.stage]


def kinds(events: list[MediaEvent]) -> list[str]:
    """Extract event kinds from event list."""
    return [e.kind for e in events]


def has_error(events) -> bool:
    return any(e.kind == "error" for e in events)


def has_complete(events: list[MediaEvent]) -> bool:
    return any(e.kind == "complete" for e in events)


# ---------------------------------------------------------------------------
# Device profiles covering the hardware matrix
# ---------------------------------------------------------------------------


@pytest.fixture
def x86_uefi64_profile() -> DeviceProfile:
    """MiniGMK-style: x86_64, standard UEFI, USB installer."""
    return DeviceProfile(
        id="minigmk",
        label="MiniGMK",
        model="GMKtec NucBox G3 Plus",
        arch="x86_64",
        boot_type="uefi64",
        media_type="installer",
        media_target="usb",
        nixos_config="sbc/x86-generic/configuration.nix",
        bond_script="sbc/x86-generic/polymerize.sh",
        default_hostname="minigmk-01",
        specs=_specs(),
    )


@pytest.fixture
def x86_uefi32_profile() -> DeviceProfile:
    """T100TA-style: x86_64, 32-bit UEFI, USB installer, needs BOOTIA32."""
    return DeviceProfile(
        id="t100ta",
        label="T100TA",
        model="ASUS T100TA",
        arch="x86_64",
        boot_type="uefi32",
        media_type="installer",
        media_target="usb",
        nixos_config="sbc/t100ta/configuration.nix",
        bond_script="sbc/t100ta/polymerize.sh",
        default_hostname="t100ta-01",
        specs=_specs(),
    )


@pytest.fixture
def aarch64_direct_profile() -> DeviceProfile:
    """RPi4-style: aarch64, u-boot, direct SD card, no bond, Nix image."""
    return DeviceProfile(
        id="rpi4",
        label="RPi 4B",
        model="Raspberry Pi 4 Model B Rev 1.5",
        arch="aarch64",
        boot_type="uboot",
        media_type="direct",
        media_target="sd",
        nixos_config="sbc/rpi4/configuration.nix",
        bond_script=None,
        default_hostname="rpi4-01",
        specs=_specs(),
        nix_flake_output="packages.aarch64-linux.rpi4-sd",
    )


@pytest.fixture
def aarch64_zero2w_profile() -> DeviceProfile:
    """RPi Zero 2W: aarch64, u-boot, direct SD, no bond, Nix image."""
    return DeviceProfile(
        id="rpi-zero2w",
        label="RPi Zero 2W",
        model="Raspberry Pi Zero 2 W",
        arch="aarch64",
        boot_type="uboot",
        media_type="direct",
        media_target="sd",
        nixos_config="sbc/rpi-zero2w/configuration.nix",
        bond_script=None,
        default_hostname="zero2w-01",
        specs=_specs(),
        nix_flake_output="packages.aarch64-linux.rpi-zero2w-sd",
    )


@pytest.fixture
def aarch64_rg35xx_h_profile() -> DeviceProfile:
    """RG35XX H: aarch64, u-boot, direct SD, WiFi, Nix image."""
    return DeviceProfile(
        id="rg35xx-h",
        label="RG35XX H",
        model="Anbernic RG35XX H",
        arch="aarch64",
        boot_type="uboot",
        media_type="direct",
        media_target="sd",
        nixos_config="sbc/rg35xx-h/configuration.nix",
        bond_script=None,
        default_hostname="rg35xx-h-01",
        specs=_specs(
            cpu="Allwinner H700 (Cortex-A53)",
            ram_mb=1024,
            storage="microSD",
            network="WiFi 5, BT 4.2",
        ),
        nix_flake_output="packages.aarch64-linux.rg35xx-h-sd",
    )


@pytest.fixture
def aarch64_r36s_profile() -> DeviceProfile:
    """R36S: aarch64, u-boot, direct SD, no WiFi, Nix image."""
    return DeviceProfile(
        id="r36s",
        label="R36S",
        model="PowKiddy R36S",
        arch="aarch64",
        boot_type="uboot",
        media_type="direct",
        media_target="sd",
        nixos_config="sbc/r36s/configuration.nix",
        bond_script=None,
        default_hostname="r36s-01",
        specs=_specs(
            cpu="Rockchip RK3326 (Cortex-A35)",
            ram_mb=1024,
            storage="2x microSD",
            network="None (USB OTG)",
        ),
        nix_flake_output="packages.aarch64-linux.r36s-sd",
    )


# ---------------------------------------------------------------------------
# FlashTarget fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def x86_usb_target(x86_uefi64_profile: DeviceProfile) -> FlashTarget:
    """x86 USB target with WiFi configured."""
    return FlashTarget(
        device=x86_uefi64_profile,
        disk_path="/dev/disk4",
        disk_name="SanDisk Ultra USB 3.0",
        disk_size="32.0 GB",
        wifi_ssid="TestNet",
        wifi_password="hunter2",
    )


@pytest.fixture
def x86_uefi32_target(x86_uefi32_profile: DeviceProfile) -> FlashTarget:
    """T100TA USB target for 32-bit UEFI testing."""
    return FlashTarget(
        device=x86_uefi32_profile,
        disk_path="/dev/disk5",
        disk_name="Kingston DataTraveler",
        disk_size="16.0 GB",
        wifi_ssid="TestNet",
        wifi_password="hunter2",
    )


@pytest.fixture
def aarch64_sd_target(aarch64_direct_profile: DeviceProfile) -> FlashTarget:
    """RPi4 SD card target with WiFi configured."""
    return FlashTarget(
        device=aarch64_direct_profile,
        disk_path="/dev/disk3",
        disk_name="Samsung EVO 32GB",
        disk_size="32.0 GB",
        wifi_ssid="TestNet",
        wifi_password="hunter2",
    )


@pytest.fixture
def aarch64_handheld_target(aarch64_rg35xx_h_profile: DeviceProfile) -> FlashTarget:
    """RG35XX H SD card target with WiFi configured."""
    return FlashTarget(
        device=aarch64_rg35xx_h_profile,
        disk_path="/dev/disk3",
        disk_name="Samsung EVO 32GB",
        disk_size="32.0 GB",
        wifi_ssid="TestNet",
        wifi_password="hunter2",
    )


@pytest.fixture
def no_wifi_target(x86_uefi64_profile: DeviceProfile) -> FlashTarget:
    """x86 USB target without WiFi (wired deployment)."""
    return FlashTarget(
        device=x86_uefi64_profile,
        disk_path="/dev/disk4",
        disk_name="SanDisk Ultra USB 3.0",
        disk_size="32.0 GB",
    )


# ---------------------------------------------------------------------------
# Filesystem fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_edge_dir(tmp_path: Path, x86_uefi64_profile: DeviceProfile) -> Path:
    """Create a minimal edge-fleet directory tree for file-copy tests."""
    # x86-generic
    x86 = tmp_path / "sbc" / "x86-generic"
    x86.mkdir(parents=True)
    (x86 / "polymerize.sh").write_text("#!/bin/bash\necho bond")
    (x86 / "polymerize.sh").chmod(0o755)
    (x86 / "configuration.nix").write_text("{ ... }")
    (x86 / "wifi.conf.example").write_text('network={\n  ssid=""\n  psk=""\n}\n')

    # t100ta
    t100 = tmp_path / "sbc" / "t100ta"
    t100.mkdir(parents=True)
    (t100 / "polymerize.sh").write_text("#!/bin/bash\necho t100ta")
    (t100 / "polymerize.sh").chmod(0o755)
    (t100 / "configuration.nix").write_text("{ ... t100ta }")
    (t100 / "wifi.conf.example").write_text('network={\n  ssid=""\n  psk=""\n}\n')

    # rpi4
    rpi4 = tmp_path / "sbc" / "rpi4"
    rpi4.mkdir(parents=True)
    (rpi4 / "configuration.nix").write_text("{ ... rpi4 }")
    (rpi4 / "wifi.conf.example").write_text('network={\n  ssid=""\n  psk=""\n}\n')

    # rpi-zero2w
    z2w = tmp_path / "sbc" / "rpi-zero2w"
    z2w.mkdir(parents=True)
    (z2w / "configuration.nix").write_text("{ ... zero2w }")
    (z2w / "wifi.conf.example").write_text('network={\n  ssid=""\n  psk=""\n}\n')

    # rg35xx-h
    rg35xx = tmp_path / "sbc" / "rg35xx-h"
    rg35xx.mkdir(parents=True)
    (rg35xx / "configuration.nix").write_text("{ ... rg35xx-h }")
    (rg35xx / "wifi.conf.example").write_text('network={\n  ssid=""\n  psk=""\n}\n')

    # r36s
    r36s = tmp_path / "sbc" / "r36s"
    r36s.mkdir(parents=True)
    (r36s / "configuration.nix").write_text("{ ... r36s }")
    (r36s / "wifi.conf.example").write_text('network={\n  ssid=""\n  psk=""\n}\n')

    # common modules directory
    common = tmp_path / "sbc" / "common"
    common.mkdir(parents=True)
    (common / "base.nix").write_text("{ ... common base }")
    (common / "network.nix").write_text("{ ... common network }")

    return tmp_path
