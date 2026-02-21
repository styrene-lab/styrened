"""Pure Python media writer for Styrene edge devices.

Extracted from styrene-edge. Replaces the subprocess wrapper around
styrene-media.sh with native Python control flow.  Subprocess calls
remain only for operations that require system privileges or
platform-specific binaries (bsdtar, zstd, diskutil, parted, dd,
podman, sync).

All I/O operations yield ``MediaEvent`` for TUI progress tracking.
The ``edge_dir`` parameter must be provided explicitly — there is
no default path since this code is no longer inside styrene-edge.
"""

import asyncio
import platform
import re
import shutil
import stat
import time
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path

from styrened.tui.forge.models import (
    DeviceProfile,
    FlashTarget,
    MediaEvent,
    StageKey,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NIXOS_VERSION = "24.11"
WORK_DIR = Path.home() / ".cache" / "styrene-forge"

_X86_ISO_NAME = f"nixos-minimal-{NIXOS_VERSION}-x86_64.iso"
_X86_ISO_URL = (
    f"https://channels.nixos.org/nixos-{NIXOS_VERSION}/latest-nixos-minimal-x86_64-linux.iso"
)
_X86_EXTRACT_DIR_NAME = "nixos-x86_64-extracted"

_AARCH64_IMG_NAME = f"nixos-sd-{NIXOS_VERSION}-aarch64.img"
_AARCH64_IMG_URL = (
    f"https://channels.nixos.org/nixos-{NIXOS_VERSION}/latest-nixos-sd-image-aarch64-linux.img.zst"
)

_IS_MACOS = platform.system() == "Darwin"

# Podman command for GRUB IA32 build
_GRUB_MODULES = (
    "part_gpt part_msdos fat iso9660 ntfs ext2 linux linuxefi chain boot "
    "configfile normal search search_fs_file search_fs_uuid search_label "
    "echo test ls cat read help gfxterm gfxmenu font png"
)

_BUILD_GRUB_SCRIPT = f"""\
#!/bin/bash
set -e
apt-get update
apt-get install -y grub-efi-ia32-bin
grub-mkimage \\
    --directory=/usr/lib/grub/i386-efi \\
    --prefix=/EFI/BOOT \\
    --output=/output/bootia32.efi \\
    --format=i386-efi \\
    --compression=auto \\
    {_GRUB_MODULES}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sbc_dir(profile: DeviceProfile, edge_dir: Path) -> Path:
    """Derive the SBC target directory from the profile's nixos_config path."""
    return edge_dir / Path(profile.nixos_config).parent


def _log(msg: str) -> MediaEvent:
    return MediaEvent(kind="log", message=msg)


def _stage(key: StageKey, msg: str) -> MediaEvent:
    return MediaEvent(kind="stage", message=msg, stage=key)


def _error(msg: str) -> MediaEvent:
    return MediaEvent(kind="error", message=msg)


async def _run_cmd(
    *args: str,
    check: bool = True,
    sudo: bool = False,
) -> tuple[int, str, str]:
    """Run a subprocess, returning (returncode, stdout, stderr)."""
    cmd = ["sudo", *args] if sudo else list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise RuntimeError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{stderr}")
    return proc.returncode, stdout, stderr


async def _with_heartbeat(
    coro,
    label: str,
    interval: float = 5.0,
) -> AsyncIterator[MediaEvent]:
    """Run *coro* in a task, yielding heartbeat log events while it runs."""
    task = asyncio.ensure_future(coro)
    start = time.monotonic()
    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=interval)
        except TimeoutError:
            elapsed = int(time.monotonic() - start)
            yield _log(f"  {label} ({elapsed}s elapsed...)")
        except Exception:
            break  # let task.result() raise below
    # Propagate any exception from the wrapped coroutine
    task.result()


# ---------------------------------------------------------------------------
# Stage: dependency checks
# ---------------------------------------------------------------------------


async def _check_dependencies(
    profile: DeviceProfile,
) -> AsyncIterator[MediaEvent]:
    yield _stage(StageKey.DEPS, "Checking dependencies...")

    missing: list[str] = []
    if not shutil.which("bsdtar"):
        missing.append("bsdtar (libarchive)")

    if profile.boot_type == "uefi32":
        if not shutil.which("podman"):
            missing.append("podman")
        else:
            rc, _, _ = await _run_cmd("podman", "info", check=False)
            if rc != 0:
                missing.append("podman (not running)")

    if profile.nix_flake_output:
        if not shutil.which("nix"):
            missing.append("nix")
        if not shutil.which("zstd"):
            missing.append("zstd (for image decompression)")
    elif profile.arch == "aarch64":
        if not shutil.which("zstd") and not shutil.which("podman"):
            missing.append("zstd or podman (for decompression)")

    if missing:
        yield _error(f"Missing dependencies: {', '.join(missing)}")
        return

    yield _log("All dependencies satisfied")


# ---------------------------------------------------------------------------
# Stage: download
# ---------------------------------------------------------------------------


async def _download_file(
    url: str,
    dest: Path,
    label: str,
) -> AsyncIterator[MediaEvent]:
    """Download *url* to *dest* with `.partial` intermediate, yielding progress."""
    if dest.exists():
        yield _log(f"{label} already downloaded")
        return

    yield _log(f"Downloading {label}...")

    partial = dest.with_suffix(dest.suffix + ".partial")
    # Clean up orphaned partial from a previous failed attempt
    partial.unlink(missing_ok=True)

    def _do_download() -> None:
        with urllib.request.urlopen(url, timeout=600) as resp, open(partial, "wb") as f:
            total = resp.headers.get("Content-Length")
            downloaded = 0
            block = 256 * 1024
            while True:
                chunk = resp.read(block)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
            # Final size check
            if total and downloaded < int(total):
                raise RuntimeError(f"Incomplete download: {downloaded}/{total} bytes")
        partial.rename(dest)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _do_download)
    size_mb = dest.stat().st_size / (1024 * 1024)
    yield _log(f"Downloaded {label} ({size_mb:.0f} MB)")


# ---------------------------------------------------------------------------
# Stage: extract / decompress
# ---------------------------------------------------------------------------


async def _extract_iso(iso_path: Path, extract_dir: Path) -> AsyncIterator[MediaEvent]:
    """Extract x86 ISO using bsdtar (Python tarfile can't read ISO9660)."""
    if extract_dir.exists() and (extract_dir / "boot" / "bzImage").exists():
        yield _log("x86_64 ISO already extracted")
        return

    yield _log("Extracting x86_64 ISO...")
    extract_dir.mkdir(parents=True, exist_ok=True)
    await _run_cmd("bsdtar", "-xf", str(iso_path), "-C", str(extract_dir))
    # ISO9660 files are read-only; make writable so we can overwrite/delete later
    for p in extract_dir.rglob("*"):
        p.chmod(p.stat().st_mode | 0o200)
    yield _log("ISO extracted")


async def _build_bootia32(work_dir: Path) -> AsyncIterator[MediaEvent]:
    """Build 32-bit GRUB EFI bootloader via Podman."""
    output = work_dir / "bootia32.efi"
    if output.exists():
        yield _log("bootia32.efi already built")
        return

    yield _log("Building 32-bit GRUB bootloader (requires Podman)...")

    build_script = work_dir / "build-grub.sh"
    build_script.write_text(_BUILD_GRUB_SCRIPT)

    await _run_cmd(
        "podman",
        "run",
        "--rm",
        "--platform",
        "linux/amd64",
        "-v",
        f"{build_script}:/build.sh:ro",
        "-v",
        f"{work_dir}:/output",
        "debian:bookworm",
        "bash",
        "/build.sh",
    )
    yield _log(f"Built: {output}")


async def _decompress_zstd(
    compressed: Path,
    output: Path,
) -> AsyncIterator[MediaEvent]:
    """Decompress a .zst file using zstd CLI or Podman fallback."""
    if output.exists():
        yield _log("Image already decompressed")
        return

    yield _log("Decompressing image...")

    if shutil.which("zstd"):
        await _run_cmd("zstd", "-d", str(compressed), "-o", str(output))
    else:
        work_dir = compressed.parent
        await _run_cmd(
            "podman",
            "run",
            "--rm",
            "-v",
            f"{work_dir}:/work",
            "debian:bookworm",
            "bash",
            "-c",
            f"apt-get update && apt-get install -y zstd && "
            f"zstd -d /work/{compressed.name} -o /work/{output.name}",
        )

    compressed.unlink(missing_ok=True)
    yield _log("Image decompressed")


def _get_init_path(extract_dir: Path) -> str:
    """Extract the init= path from the NixOS ISO grub.cfg."""
    grub_cfg = extract_dir / "EFI" / "BOOT" / "grub.cfg"
    text = grub_cfg.read_text()
    m = re.search(r"init=(/nix/store/\S+)", text)
    if not m:
        raise RuntimeError("Could not find init path in grub.cfg")
    return m.group(1)


def _generate_grub_cfg(init_path: str) -> str:
    """Generate the target grub.cfg for the USB boot media."""
    boot_args = (
        f"init={init_path} root=LABEL=NIXOS_DATA"
        " boot.shell_on_fail nohibernate loglevel=4"
        " intel_idle.max_cstate=1"
    )
    lines = [
        "set timeout=10",
        "set default=0",
        "terminal_output console",
        "terminal_input console",
        "",
        "search --set=root --file /boot/bzImage",
        "",
        "menuentry 'NixOS Installer' {",
        f"    linux /boot/bzImage {boot_args}",
        "    initrd /boot/initrd",
        "}",
        "",
        "menuentry 'NixOS Installer (nomodeset)' {",
        f"    linux /boot/bzImage {boot_args} nomodeset",
        "    initrd /boot/initrd",
        "}",
        "",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Stage: partition & mount
# ---------------------------------------------------------------------------


async def _unmount_disk(disk: str) -> None:
    """Unmount all partitions on *disk*."""
    if _IS_MACOS:
        await _run_cmd("diskutil", "unmountDisk", disk, sudo=True, check=False)
    else:
        proc = await asyncio.create_subprocess_exec(
            "sudo",
            "sh",
            "-c",
            f"umount {disk}* 2>/dev/null || true",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()


async def _wait_for_mount(path: Path, timeout: int = 10) -> None:
    """Poll until *path* exists (partition mount appeared)."""
    for _ in range(timeout):
        if path.is_dir():
            return
        await asyncio.sleep(1)
    raise RuntimeError(f"Timed out waiting for {path} to mount")


async def _partition_x86(
    disk: str,
) -> AsyncIterator[MediaEvent]:
    """Partition and format an x86 USB drive.

    Yields granular progress events. The final event is a special ``_log``
    whose message starts with ``"MOUNTS:"`` followed by two paths
    separated by ``"|"``.
    """
    if _IS_MACOS:
        yield _log("  Erasing disk and creating GPT layout...")
        yield _log("  Running diskutil partitionDisk (EFI 512MB + DATA)...")

        async def _do_partition():
            await _run_cmd(
                "diskutil",
                "partitionDisk",
                disk,
                "GPT",
                "FAT32",
                "NIXOS_EFI",
                "512MB",
                "FAT32",
                "NIXOS_DATA",
                "R",
                sudo=True,
            )

        task = asyncio.ensure_future(_do_partition())
        start = time.monotonic()
        while not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
            except TimeoutError:
                elapsed = int(time.monotonic() - start)
                yield _log(f"  diskutil partitionDisk running ({elapsed}s elapsed...)")
            except Exception:
                break
        task.result()
        elapsed = int(time.monotonic() - start)
        yield _log(f"  diskutil partitionDisk completed ({elapsed}s)")

        yield _log("  Waiting for EFI partition to mount...")
        efi_mount = Path("/Volumes/NIXOS_EFI")
        await _wait_for_mount(efi_mount)
        yield _log("  EFI partition mounted at /Volumes/NIXOS_EFI")

        yield _log("  Waiting for DATA partition to mount...")
        data_mount = Path("/Volumes/NIXOS_DATA")
        await _wait_for_mount(data_mount)
        yield _log("  DATA partition mounted at /Volumes/NIXOS_DATA")

        yield _log(f"MOUNTS:{efi_mount}|{data_mount}")
    else:
        yield _log("  Creating GPT partition table...")
        start = time.monotonic()
        await _run_cmd(
            "parted",
            "-s",
            disk,
            "mklabel",
            "gpt",
            "mkpart",
            "NIXOS_EFI",
            "fat32",
            "1MiB",
            "513MiB",
            "set",
            "1",
            "esp",
            "on",
            "mkpart",
            "NIXOS_DATA",
            "fat32",
            "513MiB",
            "100%",
            sudo=True,
        )
        elapsed = int(time.monotonic() - start)
        yield _log(f"  Partition table written ({elapsed}s)")
        await asyncio.sleep(1)

        efi_part = f"{disk}1"
        data_part = f"{disk}2"

        yield _log(f"  Formatting EFI partition ({efi_part})...")
        start = time.monotonic()
        await _run_cmd("mkfs.fat", "-F32", "-n", "NIXOS_EFI", efi_part, sudo=True)
        elapsed = int(time.monotonic() - start)
        yield _log(f"  EFI formatted ({elapsed}s)")

        yield _log(f"  Formatting DATA partition ({data_part})...")
        start = time.monotonic()
        await _run_cmd("mkfs.fat", "-F32", "-n", "NIXOS_DATA", data_part, sudo=True)
        elapsed = int(time.monotonic() - start)
        yield _log(f"  DATA formatted ({elapsed}s)")

        efi_mount = Path("/mnt/nixos_efi")
        data_mount = Path("/mnt/nixos_data")
        efi_mount.mkdir(parents=True, exist_ok=True)
        data_mount.mkdir(parents=True, exist_ok=True)

        yield _log("  Mounting partitions...")
        await _run_cmd("mount", efi_part, str(efi_mount), sudo=True)
        await _run_cmd("mount", data_part, str(data_mount), sudo=True)
        yield _log("  Partitions mounted")

        yield _log(f"MOUNTS:{efi_mount}|{data_mount}")


async def _remount_nixos_partition(disk: str) -> Path | None:
    """Re-mount the NIXOS_SD partition after dd write (aarch64 flow)."""
    if _IS_MACOS:
        await _run_cmd("diskutil", "eject", disk, sudo=True, check=False)
        await asyncio.sleep(2)

        nixos_mount = Path("/Volumes/NIXOS_SD")
        for _ in range(30):
            if nixos_mount.is_dir():
                return nixos_mount
            await asyncio.sleep(1)
        return None
    else:
        part = f"{disk}2"
        mount_point = Path("/mnt/nixos_sd")
        mount_point.mkdir(parents=True, exist_ok=True)
        await _run_cmd("mount", part, str(mount_point), sudo=True)
        return mount_point


# ---------------------------------------------------------------------------
# Stage: copy system files
# ---------------------------------------------------------------------------


async def _prepare_x86_installer(
    disk: str,
    profile: DeviceProfile,
    target: FlashTarget,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Full x86 USB installer preparation."""
    yield _stage(StageKey.PARTITION, "Partitioning disk...")
    yield _log("Unmounting existing partitions...")
    await _unmount_disk(disk)

    yield _log("Creating GPT partition table (EFI + DATA)...")
    async for event in _partition_x86(disk):
        if event.message and event.message.startswith("MOUNTS:"):
            parts = event.message[len("MOUNTS:"):].split("|")
            efi_mount = Path(parts[0])
            data_mount = Path(parts[1])
        else:
            yield event
    yield _log(f"Partitioned {disk} (EFI + DATA)")

    # ---- Copy EFI boot files ----
    yield _stage(StageKey.COPY, "Setting up EFI partition...")

    efi_boot = efi_mount / "EFI" / "BOOT"
    efi_boot.mkdir(parents=True, exist_ok=True)
    (efi_mount / "boot").mkdir(parents=True, exist_ok=True)

    extract_dir = WORK_DIR / _X86_EXTRACT_DIR_NAME

    # Bootloaders
    if profile.boot_type == "uefi32":
        shutil.copy2(
            WORK_DIR / "bootia32.efi",
            efi_boot / "BOOTIA32.EFI",
        )
    shutil.copy2(
        extract_dir / "EFI" / "BOOT" / "BOOTX64.EFI",
        efi_boot / "BOOTX64.EFI",
    )
    shutil.copy2(extract_dir / "boot" / "bzImage", efi_mount / "boot" / "bzImage")
    shutil.copy2(extract_dir / "boot" / "initrd", efi_mount / "boot" / "initrd")

    # grub.cfg
    init_path = _get_init_path(extract_dir)
    yield _log(f"Init path: {init_path}")
    (efi_boot / "grub.cfg").write_text(_generate_grub_cfg(init_path))

    # ---- Copy NixOS data ----
    yield _log("Copying NixOS system files...")
    shutil.copy2(
        extract_dir / "nix-store.squashfs",
        data_mount / "nix-store.squashfs",
    )
    (data_mount / "boot").mkdir(parents=True, exist_ok=True)
    shutil.copy2(extract_dir / "boot" / "bzImage", data_mount / "boot" / "bzImage")
    shutil.copy2(extract_dir / "boot" / "initrd", data_mount / "boot" / "initrd")

    isolinux_src = extract_dir / "isolinux"
    if isolinux_src.is_dir():
        isolinux_dest = data_mount / "isolinux"
        shutil.copytree(isolinux_src, isolinux_dest, dirs_exist_ok=True)
        if isolinux_dest.exists():
            for p in isolinux_dest.rglob("*"):
                p.chmod(p.stat().st_mode | 0o200)
            isolinux_dest.chmod(isolinux_dest.stat().st_mode | 0o200)

    yield _log("System files copied")

    # ---- Styrene files ----
    async for event in _copy_styrene_files(data_mount, profile, target, edge_dir):
        yield event


async def _prepare_aarch64_direct(
    disk: str,
    profile: DeviceProfile,
    target: FlashTarget,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Full aarch64 direct SD card preparation."""
    yield _stage(StageKey.PARTITION, "Writing NixOS image to SD card...")
    yield _log("Unmounting existing partitions...")
    await _unmount_disk(disk)

    image_path = WORK_DIR / _AARCH64_IMG_NAME

    # dd the base image — run with heartbeat since this takes minutes
    yield _log("Writing image with dd (this takes several minutes)...")

    async def _dd_write() -> None:
        dd_args = ["sudo", "dd", f"if={image_path}", f"of={disk}", "bs=4m"]
        if not _IS_MACOS:
            dd_args.append("status=progress")
        proc = await asyncio.create_subprocess_exec(
            *dd_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"dd failed: {stderr_bytes.decode(errors='replace')}")

    async for event in _with_heartbeat(_dd_write(), "Writing image"):
        yield event

    await _run_cmd("sync")
    await asyncio.sleep(3)
    yield _log("Base image written")

    # Remount to add Styrene files
    yield _stage(StageKey.COPY, "Re-mounting SD card for Styrene files...")
    nixos_mount = await _remount_nixos_partition(disk)
    if nixos_mount is None:
        yield _log(
            "Could not find NIXOS_SD partition — "
            "Styrene files not copied. Copy manually from "
            f"{_sbc_dir(profile, edge_dir)}"
        )
    else:
        async for event in _copy_styrene_files(
            nixos_mount,
            profile,
            target,
            edge_dir,
        ):
            yield event


# ---------------------------------------------------------------------------
# Stage: styrene automation files
# ---------------------------------------------------------------------------


async def _copy_styrene_files(
    mount_point: Path,
    profile: DeviceProfile,
    target: FlashTarget,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Copy Styrene automation files to the mounted media."""
    yield _stage(StageKey.STYRENE_FILES, "Adding Styrene automation...")

    styrene_dir = mount_point / "styrene"
    styrene_dir.mkdir(parents=True, exist_ok=True)

    sbc = _sbc_dir(profile, edge_dir)

    # Bond script
    bond_src = sbc / "polymerize.sh" if profile.bond_script else None
    if bond_src and bond_src.exists():
        dest = styrene_dir / "polymerize.sh"
        shutil.copy2(bond_src, dest)
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        yield _log("Copied polymerize.sh")

    # NixOS configuration
    config_src = sbc / "configuration.nix"
    if config_src.exists():
        shutil.copy2(config_src, styrene_dir / "configuration.nix")
        yield _log("Copied configuration.nix")

    # Common NixOS modules (imported by configuration.nix)
    common_src = sbc.parent / "common"
    if common_src.is_dir():
        common_dest = styrene_dir / "common"
        common_dest.mkdir(parents=True, exist_ok=True)
        for nix_file in sorted(common_src.glob("*.nix")):
            shutil.copy2(nix_file, common_dest / nix_file.name)
        yield _log(
            f"Copied common modules ({', '.join(f.name for f in sorted(common_src.glob('*.nix')))})"
        )

    # Python wheels for airgapped styrened install
    wheels_src = edge_dir / "forge" / "wheels"
    if wheels_src.is_dir() and any(wheels_src.glob("*.whl")):
        wheels_dest = styrene_dir / "wheels"
        wheels_dest.mkdir(parents=True, exist_ok=True)
        whl_files = sorted(wheels_src.glob("*.whl"))
        for whl in whl_files:
            shutil.copy2(whl, wheels_dest / whl.name)
        yield _log(f"Copied {len(whl_files)} wheels for airgapped install")

    # WiFi config example
    example_src = sbc / "wifi.conf.example"
    if example_src.exists():
        shutil.copy2(example_src, styrene_dir / "wifi.conf.example")

    # WiFi config — written directly to target media from FlashTarget
    if target.wifi_ssid:
        wifi_conf = styrene_dir / "wifi.conf"
        ssid = target.wifi_ssid.replace("\\", "\\\\").replace('"', '\\"')
        psk = target.wifi_password.replace("\\", "\\\\").replace('"', '\\"')
        wifi_conf.write_text(f'network={{\n  ssid="{ssid}"\n  psk="{psk}"\n}}\n')
        yield _log(f"Wrote wifi.conf (SSID: {target.wifi_ssid})")
    else:
        yield _log("No WiFi configured — installer will prompt manually")


# ---------------------------------------------------------------------------
# Stage: finish
# ---------------------------------------------------------------------------


async def _finish_media(
    disk: str,
    profile: DeviceProfile,
) -> AsyncIterator[MediaEvent]:
    """Sync, unmount, and report completion."""
    yield _stage(StageKey.FINISH, "Syncing and ejecting...")
    await _run_cmd("sync")

    await _unmount_disk(disk)

    yield _log(f"Styrene Media Ready — {profile.label}")
    yield MediaEvent(kind="complete", message="Media creation complete")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_media_writer(
    target: FlashTarget,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Create bootable Styrene media for *target*.

    Yields ``MediaEvent`` objects for progress tracking by the TUI.

    Args:
        target: Flash target with device profile and configuration.
        edge_dir: Path to styrene-edge repository root.
    """
    profile = target.device
    disk = target.disk_path

    yield _log(
        f"Target: {profile.label} | Arch: {profile.arch} | Boot: {profile.boot_type} | Disk: {disk}"
    )

    try:
        async for event in _run_media_pipeline(
            target,
            profile,
            disk,
            edge_dir,
        ):
            yield event
    except Exception as exc:
        yield _error(f"Unexpected error: {exc}")


async def _run_media_pipeline(
    target: FlashTarget,
    profile: DeviceProfile,
    disk: str,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Inner pipeline — exceptions caught by run_media_writer."""
    if profile.nix_flake_output:
        async for event in _run_nix_media_pipeline(profile, disk, edge_dir):
            yield event
    else:
        async for event in _run_stock_media_pipeline(target, profile, disk, edge_dir):
            yield event


async def _run_nix_media_pipeline(
    profile: DeviceProfile,
    disk: str,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Direct-to-disk pipeline for Nix-built images."""
    from styrened.tui.forge.nix_build import resolve_nix_image

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

    # ---- 3. Decompress + dd to disk ----
    yield _stage(StageKey.PARTITION, "Writing Nix image to SD card...")
    yield _log("Unmounting existing partitions...")
    await _unmount_disk(disk)

    yield _log("Decompressing and writing Nix image with zstd | dd...")

    async def _zstd_dd() -> None:
        _is_macos = platform.system() == "Darwin"
        cmd = f"zstd -d --stdout {nix_img_path} | sudo dd of={disk} bs=4m"
        if not _is_macos:
            cmd += " status=progress"
        proc = await asyncio.create_subprocess_exec(
            "sudo", "sh", "-c", cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"zstd|dd failed: {stderr_bytes.decode(errors='replace')}")

    async for event in _with_heartbeat(_zstd_dd(), "Writing image"):
        yield event

    yield _log("Image written")

    # ---- 4. Finish ----
    async for event in _finish_media(disk, profile):
        yield event


async def _run_stock_media_pipeline(
    target: FlashTarget,
    profile: DeviceProfile,
    disk: str,
    edge_dir: Path,
) -> AsyncIterator[MediaEvent]:
    """Stock pipeline for non-Nix devices."""
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 1. Dependency check ----
    failed = False
    async for event in _check_dependencies(profile):
        if event.kind == "error":
            failed = True
        yield event
    if failed:
        return

    # ---- 2. Download ----
    yield _stage(StageKey.DOWNLOAD, "Downloading NixOS image...")

    if profile.arch == "x86_64":
        iso_path = WORK_DIR / _X86_ISO_NAME
        async for event in _download_file(
            _X86_ISO_URL,
            iso_path,
            "NixOS x86_64 ISO",
        ):
            yield event
    elif profile.arch == "aarch64":
        compressed = WORK_DIR / f"{_AARCH64_IMG_NAME}.zst"
        final = WORK_DIR / _AARCH64_IMG_NAME
        async for event in _download_file(
            _AARCH64_IMG_URL,
            compressed,
            "NixOS aarch64 SD image",
        ):
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
    elif profile.arch == "aarch64":
        async for event in _decompress_zstd(compressed, final):
            yield event

    # ---- 4–6. Partition, copy, styrene files ----
    if profile.media_type == "installer":
        async for event in _prepare_x86_installer(
            disk,
            profile,
            target,
            edge_dir,
        ):
            yield event
    elif profile.media_type == "direct":
        async for event in _prepare_aarch64_direct(
            disk,
            profile,
            target,
            edge_dir,
        ):
            yield event
    else:
        yield _error(f"Unknown media type: {profile.media_type}")
        return

    # ---- 7. Finish ----
    async for event in _finish_media(disk, profile):
        yield event
