"""Device profile, flash target, bundle, and forge config models.

Extracted from styrene-edge forge/models/ with path parameterization
for portability outside the edge repo.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml

# ---------------------------------------------------------------------------
# Device types
# ---------------------------------------------------------------------------

BootType = Literal["uefi64", "uefi32", "uboot"]
MediaType = Literal["installer", "direct"]
MediaTarget = Literal["usb", "sd"]


@dataclass(frozen=True)
class DeviceSpecs:
    """Hardware specifications for a device."""

    cpu: str
    cores: int
    ram_mb: int
    storage: str
    network: str


@dataclass(frozen=True)
class DeviceProfile:
    """Declarative device profile loaded from YAML."""

    id: str
    label: str
    model: str
    arch: Literal["x86_64", "aarch64"]
    boot_type: BootType
    media_type: MediaType
    media_target: MediaTarget
    nixos_config: str
    bond_script: str | None
    default_hostname: str
    specs: DeviceSpecs
    nix_flake_output: str | None = None


@dataclass
class FlashTarget:
    """Mutable runtime state accumulating through the pipeline."""

    device: DeviceProfile
    disk_path: str = ""
    disk_name: str = ""
    disk_size: str = ""
    hostname: str = ""
    wifi_ssid: str = ""
    wifi_password: str = ""
    ssh_key_path: str = ""
    ip_address: str = ""
    stages_completed: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.hostname:
            self.hostname = self.device.default_hostname

    @property
    def needs_bond(self) -> bool:
        """Whether this device requires a bond (on-device install) phase."""
        return self.device.media_type == "installer" and self.device.bond_script is not None


# ---------------------------------------------------------------------------
# Bundle
# ---------------------------------------------------------------------------


@dataclass
class Bundle:
    """A self-contained, flashable bundle for a device."""

    path: Path
    device_id: str
    device_label: str
    arch: str
    boot_type: str
    media_type: str
    nixos_version: str
    created: str
    hostname: str
    wifi_configured: bool
    wheels_count: int
    nix_image: bool = False

    @property
    def manifest_path(self) -> Path:
        return self.path / "bundle.yaml"

    @property
    def styrene_dir(self) -> Path:
        return self.path / "styrene"

    def write_manifest(self) -> None:
        """Write bundle.yaml manifest."""
        data = {
            "version": 1,
            "device_id": self.device_id,
            "device_label": self.device_label,
            "arch": self.arch,
            "boot_type": self.boot_type,
            "media_type": self.media_type,
            "nixos_version": self.nixos_version,
            "created": self.created,
            "hostname": self.hostname,
            "wifi_configured": self.wifi_configured,
            "wheels_count": self.wheels_count,
            "nix_image": self.nix_image,
        }
        with open(self.manifest_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    @classmethod
    def load(cls, bundle_path: Path) -> "Bundle":
        """Load a bundle from its manifest."""
        manifest = bundle_path / "bundle.yaml"
        with open(manifest) as f:
            data = yaml.safe_load(f)
        return cls(
            path=bundle_path,
            device_id=data["device_id"],
            device_label=data["device_label"],
            arch=data["arch"],
            boot_type=data["boot_type"],
            media_type=data["media_type"],
            nixos_version=data["nixos_version"],
            created=data["created"],
            hostname=data["hostname"],
            wifi_configured=data.get("wifi_configured", False),
            wheels_count=data.get("wheels_count", 0),
            nix_image=data.get("nix_image", False),
        )

    @classmethod
    def create(
        cls,
        bundles_dir: Path,
        target: "FlashTarget",
        wheels_dir: Path | None = None,
    ) -> "Bundle":
        """Create a new empty bundle directory for a target.

        Args:
            bundles_dir: Parent directory for bundles.
            target: Flash target to create bundle for.
            wheels_dir: Directory containing .whl files. If None, wheels_count=0.
        """
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M")
        bundle_name = f"{target.device.id}-{ts}"
        bundle_path = bundles_dir / bundle_name
        bundle_path.mkdir(parents=True, exist_ok=True)

        wheels_count = 0
        if wheels_dir is not None and wheels_dir.is_dir():
            wheels_count = len(list(wheels_dir.glob("*.whl")))

        return cls(
            path=bundle_path,
            device_id=target.device.id,
            device_label=target.device.label,
            arch=target.device.arch,
            boot_type=target.device.boot_type,
            media_type=target.device.media_type,
            nixos_version="24.11",
            created=datetime.now(UTC).isoformat(),
            hostname=target.hostname,
            wifi_configured=bool(target.wifi_ssid),
            wheels_count=wheels_count,
            nix_image=target.device.nix_flake_output is not None,
        )


# ---------------------------------------------------------------------------
# Stage / event types (shared by media_writer and bundle_builder)
# ---------------------------------------------------------------------------


class StageKey(Enum):
    DEPS = "deps"
    DOWNLOAD = "download"
    EXTRACT = "extract"
    PARTITION = "partition"
    COPY = "copy"
    STYRENE_FILES = "styrene_files"
    FINISH = "finish"


STAGE_ORDER: list[StageKey] = list(StageKey)

STAGE_NAMES: list[str] = [
    "Check dependencies",
    "Download NixOS image",
    "Extract / decompress",
    "Partition disk",
    "Copy system files",
    "Add Styrene automation",
    "Finalize and eject",
]


@dataclass(frozen=True)
class MediaEvent:
    """Structured progress event emitted by the media writer."""

    kind: str  # "log" | "stage" | "error" | "complete"
    message: str
    stage: StageKey | None = None


# ---------------------------------------------------------------------------
# Disk info
# ---------------------------------------------------------------------------


@dataclass
class DiskInfo:
    """Detected external disk."""

    device: str  # /dev/disk4
    name: str  # "SanDisk Ultra"
    size: str  # "32.0 GB"
    media_type: str  # "USB" or "SD"


# ---------------------------------------------------------------------------
# Forge config
# ---------------------------------------------------------------------------


@dataclass
class ForgeConfig:
    """User defaults loaded from forge.yaml."""

    wifi_ssid: str = ""
    wifi_password: str = ""
    ssh_key: str = ""
    hostnames: dict[str, str] = field(default_factory=dict)


def load_forge_config(path: Path | None = None) -> ForgeConfig:
    """Load forge.yaml. Returns empty config if missing.

    Args:
        path: Explicit path to forge.yaml. If None, returns empty config.
    """
    if path is None or not path.exists():
        return ForgeConfig()

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        return ForgeConfig()

    wifi = raw.get("wifi") or {}
    ssh_key = raw.get("ssh_key", "")
    if ssh_key:
        ssh_key = str(Path(ssh_key).expanduser())

    hostnames = raw.get("hostnames") or {}

    return ForgeConfig(
        wifi_ssid=wifi.get("ssid", ""),
        wifi_password=wifi.get("password", ""),
        ssh_key=ssh_key,
        hostnames={str(k): str(v) for k, v in hostnames.items()},
    )


# ---------------------------------------------------------------------------
# Device catalog
# ---------------------------------------------------------------------------


def _parse_device(dev_id: str, data: dict) -> DeviceProfile:
    """Parse a single device entry from YAML."""
    specs_data = data.get("specs", {})
    specs = DeviceSpecs(
        cpu=specs_data.get("cpu", "Unknown"),
        cores=specs_data.get("cores", 0),
        ram_mb=specs_data.get("ram_mb", 0),
        storage=specs_data.get("storage", "Unknown"),
        network=specs_data.get("network", "Unknown"),
    )
    return DeviceProfile(
        id=dev_id,
        label=data["label"],
        model=data["model"],
        arch=data["arch"],
        boot_type=data["boot_type"],
        media_type=data["media_type"],
        media_target=data["media_target"],
        nixos_config=data["nixos_config"],
        bond_script=data.get("bond_script"),
        default_hostname=data["default_hostname"],
        specs=specs,
        nix_flake_output=data.get("nix_flake_output"),
    )


def load_device_catalog(catalog_path: Path) -> dict[str, DeviceProfile]:
    """Load device profiles from YAML catalog.

    Args:
        catalog_path: Path to devices.yaml file.
    """
    with open(catalog_path) as f:
        raw = yaml.safe_load(f)

    devices: dict[str, DeviceProfile] = {}
    for dev_id, dev_data in raw.get("devices", {}).items():
        devices[dev_id] = _parse_device(dev_id, dev_data)

    return devices
