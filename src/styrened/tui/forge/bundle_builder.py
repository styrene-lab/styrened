"""Bundle builder — assembles a self-contained, flashable bundle.

Extracted from styrene-edge. Downloads the NixOS image, extracts boot
files, and collects all Styrene automation artifacts (bond script,
configuration, wheels, WiFi config) into a bundle directory that can
be flashed to USB/SD later.

The ``edge_dir`` parameter must be provided explicitly — there is
no default path since this code is no longer inside styrene-edge.
"""

import shutil
import stat
from collections.abc import AsyncIterator
from pathlib import Path

from styrened.tui.forge.media_writer import (
    _AARCH64_IMG_NAME,
    _AARCH64_IMG_URL,
    _X86_EXTRACT_DIR_NAME,
    _X86_ISO_NAME,
    _X86_ISO_URL,
    WORK_DIR,
    _build_bootia32,
    _check_dependencies,
    _decompress_zstd,
    _download_file,
    _error,
    _extract_iso,
    _generate_grub_cfg,
    _get_init_path,
    _log,
    _sbc_dir,
    _stage,
)
from styrened.tui.forge.models import Bundle, FlashTarget, MediaEvent, StageKey
from styrened.tui.forge.nix_build import resolve_nix_image

# Stage definitions for the bundle builder (no partition/flash stages)
BUNDLE_STAGE_NAMES: list[str] = [
    "Check dependencies",
    "Download NixOS image",
    "Extract / decompress",
    "Assemble Styrene files",
    "Write manifest",
]

BUNDLE_STAGE_KEYS: list[StageKey] = [
    StageKey.DEPS,
    StageKey.DOWNLOAD,
    StageKey.EXTRACT,
    StageKey.STYRENE_FILES,
    StageKey.FINISH,
]


async def build_bundle(
    target: FlashTarget,
    bundle: Bundle,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Build a complete bundle for the given target.

    Yields ``MediaEvent`` objects for progress tracking.

    Args:
        target: Flash target with device profile and configuration.
        bundle: Bundle object to populate.
        edge_dir: Path to styrene-edge repository root.
    """
    profile = target.device

    yield _log(
        f"Building bundle: {bundle.path.name}\n"
        f"  Device: {profile.label} | Arch: {profile.arch} | Boot: {profile.boot_type}"
    )

    try:
        async for event in _build_bundle_pipeline(target, bundle, edge_dir):
            yield event
    except Exception as exc:
        yield _error(f"Bundle build failed: {exc}")


async def _build_bundle_pipeline(
    target: FlashTarget,
    bundle: Bundle,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Inner bundle build pipeline."""
    profile = target.device

    if profile.nix_flake_output:
        async for event in _build_nix_bundle(target, bundle, edge_dir):
            yield event
    else:
        async for event in _build_stock_bundle(target, bundle, edge_dir):
            yield event


async def _build_nix_bundle(
    target: FlashTarget,
    bundle: Bundle,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Build a bundle from a Nix flake SD image (rpi4, rpi-zero2w)."""
    profile = target.device

    # ---- 1. Dependency check ----
    failed = False
    async for event in _check_dependencies(profile):
        if event.kind == "error":
            failed = True
        yield event
    if failed:
        return

    # ---- 2. Resolve Nix image ----
    yield _stage(StageKey.DOWNLOAD, "Resolving Nix image...")

    nix_img_path = None
    async for event, path in resolve_nix_image(profile.nix_flake_output, edge_dir):
        yield event
        if path is not None:
            nix_img_path = path

    if nix_img_path is None:
        yield _error("Failed to resolve Nix image")
        return

    # ---- 3. Copy .img.zst to bundle ----
    yield _stage(StageKey.EXTRACT, "Copying image to bundle...")
    bundle_img = bundle.path / "nixos.img.zst"
    if not bundle_img.exists():
        shutil.copy2(nix_img_path, bundle_img)
    size_mb = bundle_img.stat().st_size / (1024 * 1024)
    yield _log(f"Image: {size_mb:.0f} MB (compressed)")

    # ---- 4. Skip Styrene files (baked into Nix closure) ----
    yield _stage(StageKey.STYRENE_FILES, "Styrene files baked into Nix image")
    yield _log("Skipping styrene-files assembly (configuration in Nix closure)")

    # ---- 5. Write manifest ----
    yield _stage(StageKey.FINISH, "Writing bundle manifest...")
    bundle.write_manifest()
    yield _log(f"Bundle manifest written: {bundle.manifest_path}")
    yield _log(f"Bundle ready: {bundle.path}")
    yield MediaEvent(kind="complete", message="Bundle build complete")


async def _build_stock_bundle(
    target: FlashTarget,
    bundle: Bundle,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Build a bundle from a stock NixOS image (x86 devices)."""
    profile = target.device
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 1. Dependency check ----
    failed = False
    async for event in _check_dependencies(profile):
        if event.kind == "error":
            failed = True
        yield event
    if failed:
        return

    # ---- 2. Download NixOS image ----
    yield _stage(StageKey.DOWNLOAD, "Downloading NixOS image...")

    if profile.arch == "x86_64":
        iso_path = WORK_DIR / _X86_ISO_NAME
        async for event in _download_file(_X86_ISO_URL, iso_path, "NixOS x86_64 ISO"):
            yield event
    elif profile.arch == "aarch64":
        compressed = WORK_DIR / f"{_AARCH64_IMG_NAME}.zst"
        final = WORK_DIR / _AARCH64_IMG_NAME
        async for event in _download_file(_AARCH64_IMG_URL, compressed, "NixOS aarch64 SD image"):
            yield event
    else:
        yield _error(f"Unsupported architecture: {profile.arch}")
        return

    # ---- 3. Extract / decompress ----
    yield _stage(StageKey.EXTRACT, "Extracting / decompressing...")

    if profile.arch == "x86_64":
        extract_dir = WORK_DIR / _X86_EXTRACT_DIR_NAME
        async for event in _extract_iso(iso_path, extract_dir):
            yield event

        if profile.boot_type == "uefi32":
            async for event in _build_bootia32(WORK_DIR):
                yield event

        # Copy NixOS image and EFI files into bundle
        yield _log("Copying NixOS ISO to bundle...")
        bundle_iso = bundle.path / "nixos.iso"
        if not bundle_iso.exists():
            shutil.copy2(iso_path, bundle_iso)
        yield _log(f"ISO: {bundle_iso.stat().st_size / (1024 * 1024):.0f} MB")

        # Pre-extract EFI boot files into bundle
        efi_dir = bundle.path / "efi" / "EFI" / "BOOT"
        efi_dir.mkdir(parents=True, exist_ok=True)
        (bundle.path / "efi" / "boot").mkdir(parents=True, exist_ok=True)

        if profile.boot_type == "uefi32":
            shutil.copy2(WORK_DIR / "bootia32.efi", efi_dir / "BOOTIA32.EFI")
        shutil.copy2(extract_dir / "EFI" / "BOOT" / "BOOTX64.EFI", efi_dir / "BOOTX64.EFI")
        shutil.copy2(extract_dir / "boot" / "bzImage", bundle.path / "efi" / "boot" / "bzImage")
        shutil.copy2(extract_dir / "boot" / "initrd", bundle.path / "efi" / "boot" / "initrd")

        # grub.cfg
        init_path = _get_init_path(extract_dir)
        (efi_dir / "grub.cfg").write_text(_generate_grub_cfg(init_path))
        yield _log("EFI boot files extracted into bundle")

        # Data files (squashfs, kernel, initrd for DATA partition)
        data_dir = bundle.path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "boot").mkdir(parents=True, exist_ok=True)

        shutil.copy2(extract_dir / "nix-store.squashfs", data_dir / "nix-store.squashfs")
        shutil.copy2(extract_dir / "boot" / "bzImage", data_dir / "boot" / "bzImage")
        shutil.copy2(extract_dir / "boot" / "initrd", data_dir / "boot" / "initrd")

        isolinux_src = extract_dir / "isolinux"
        if isolinux_src.is_dir():
            isolinux_dest = data_dir / "isolinux"
            shutil.copytree(isolinux_src, isolinux_dest, dirs_exist_ok=True)
            for p in isolinux_dest.rglob("*"):
                p.chmod(p.stat().st_mode | 0o200)
            isolinux_dest.chmod(isolinux_dest.stat().st_mode | 0o200)

        yield _log("NixOS system files staged in bundle")

    elif profile.arch == "aarch64":
        async for event in _decompress_zstd(compressed, final):
            yield event

        # Copy raw image into bundle
        yield _log("Copying NixOS image to bundle...")
        bundle_img = bundle.path / "nixos.img"
        if not bundle_img.exists():
            shutil.copy2(final, bundle_img)
        yield _log(f"Image: {bundle_img.stat().st_size / (1024 * 1024):.0f} MB")

    # ---- 4. Assemble Styrene files ----
    yield _stage(StageKey.STYRENE_FILES, "Assembling Styrene files...")
    async for event in _assemble_styrene_files(bundle, target, edge_dir):
        yield event

    # ---- 5. Write manifest ----
    yield _stage(StageKey.FINISH, "Writing bundle manifest...")
    bundle.write_manifest()
    yield _log(f"Bundle manifest written: {bundle.manifest_path}")
    yield _log(f"Bundle ready: {bundle.path}")
    yield MediaEvent(kind="complete", message="Bundle build complete")


async def _assemble_styrene_files(
    bundle: Bundle,
    target: FlashTarget,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Assemble all Styrene automation files into the bundle."""
    profile = target.device
    styrene_dir = bundle.styrene_dir
    styrene_dir.mkdir(parents=True, exist_ok=True)

    sbc = _sbc_dir(profile, edge_dir)

    # Bond script
    if profile.bond_script:
        bond_src = sbc / "polymerize.sh"
        if bond_src.exists():
            dest = styrene_dir / "polymerize.sh"
            shutil.copy2(bond_src, dest)
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            yield _log("Copied polymerize.sh")

    # NixOS configuration — copy then bake in hostname + SSH keys
    config_src = sbc / "configuration.nix"
    if config_src.exists():
        config_dest = styrene_dir / "configuration.nix"
        shutil.copy2(config_src, config_dest)

        config_text = config_dest.read_text()

        # Bake hostname into configuration.nix
        if target.hostname:
            config_text = config_text.replace("HOSTNAME_PLACEHOLDER", target.hostname)
            (styrene_dir / "hostname").write_text(target.hostname + "\n")
            yield _log(f"Set hostname: {target.hostname}")

        # Bake SSH authorized keys into configuration.nix
        if target.ssh_key_path:
            ssh_key_file = Path(target.ssh_key_path).expanduser()
            if ssh_key_file.exists():
                keys = [
                    line.strip()
                    for line in ssh_key_file.read_text().splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
                if keys:
                    nix_keys = "\n".join(f'      "{k}"' for k in keys)
                    auth_nix = f"openssh.authorizedKeys.keys = [\n{nix_keys}\n    ];"
                    config_text = config_text.replace("AUTHORIZED_KEYS_PLACEHOLDER", auth_nix)
                    auth_dest = styrene_dir / "authorized_keys"
                    auth_dest.write_text("\n".join(keys) + "\n")
                    yield _log(f"Set SSH keys from {ssh_key_file} ({len(keys)} key(s))")
                else:
                    config_text = config_text.replace(
                        "AUTHORIZED_KEYS_PLACEHOLDER",
                        "# No SSH keys provided",
                    )
                    yield _log("Warning: SSH key file was empty")
            else:
                config_text = config_text.replace(
                    "AUTHORIZED_KEYS_PLACEHOLDER",
                    "# No SSH keys provided",
                )
                yield _log(f"Warning: SSH key not found at {ssh_key_file}")
        else:
            config_text = config_text.replace(
                "AUTHORIZED_KEYS_PLACEHOLDER",
                "# No SSH keys provided",
            )

        config_dest.write_text(config_text)
        yield _log("Copied configuration.nix")

    # Common NixOS modules
    common_src = sbc.parent / "common"
    if common_src.is_dir():
        common_dest = styrene_dir / "common"
        common_dest.mkdir(parents=True, exist_ok=True)
        nix_files = sorted(common_src.glob("*.nix"))
        for nix_file in nix_files:
            shutil.copy2(nix_file, common_dest / nix_file.name)
        yield _log(f"Copied common modules ({', '.join(f.name for f in nix_files)})")

    # Python wheels for airgapped install
    wheels_src = edge_dir / "forge" / "wheels"
    if wheels_src.is_dir() and any(wheels_src.glob("*.whl")):
        wheels_dest = styrene_dir / "wheels"
        wheels_dest.mkdir(parents=True, exist_ok=True)
        whl_files = sorted(wheels_src.glob("*.whl"))
        for whl in whl_files:
            shutil.copy2(whl, wheels_dest / whl.name)
        yield _log(f"Copied {len(whl_files)} wheels for airgapped install")

    # WiFi config
    if target.wifi_ssid:
        wifi_conf = styrene_dir / "wifi.conf"
        ssid = target.wifi_ssid.replace("\\", "\\\\").replace('"', '\\"')
        psk = target.wifi_password.replace("\\", "\\\\").replace('"', '\\"')
        wifi_conf.write_text(f'network={{\n  ssid="{ssid}"\n  psk="{psk}"\n}}\n')
        yield _log(f"Wrote wifi.conf (SSID: {target.wifi_ssid})")
    else:
        yield _log("No WiFi configured — installer will prompt manually")

    # WiFi config example
    example_src = sbc / "wifi.conf.example"
    if example_src.exists():
        shutil.copy2(example_src, styrene_dir / "wifi.conf.example")
