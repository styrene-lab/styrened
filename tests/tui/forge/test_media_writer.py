"""Tests for forge media_writer — mocked hardware scenarios.

Ported from styrene-edge with updated imports. All tests run without
root, network, or real disks. Subprocess calls are patched.
"""
from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.tui.forge import media_writer as mw
from styrened.tui.forge.media_writer import (
    _copy_styrene_files,
    _generate_grub_cfg,
    _get_init_path,
    _sbc_dir,
    run_media_writer,
)
from styrened.tui.forge.models import (
    STAGE_NAMES,
    STAGE_ORDER,
    DeviceProfile,
    FlashTarget,
    MediaEvent,
    StageKey,
)
from tests.tui.forge.conftest import (
    _specs,
    collect,
    has_complete,
    has_error,
    stages,
)


# Helper for mocking async generators that should be no-ops
async def _noop_async_gen(*args, **kwargs):
    return
    yield  # makes this an async generator


# ===================================================================
# Unit tests: pure functions (no mocking needed)
# ===================================================================


class TestStageConstants:
    """Verify stage metadata stays consistent."""

    def test_stage_order_matches_enum(self):
        assert STAGE_ORDER == list(StageKey)

    def test_stage_names_count_matches(self):
        assert len(STAGE_NAMES) == len(StageKey)

    def test_stage_names_count_is_seven(self):
        assert len(STAGE_NAMES) == 7


class TestSbcDir:
    """Verify _sbc_dir derivation from DeviceProfile."""

    def test_x86_generic(self, x86_uefi64_profile):
        edge = Path("/edge")
        assert _sbc_dir(x86_uefi64_profile, edge) == edge / "sbc" / "x86-generic"

    def test_rpi4(self, aarch64_direct_profile):
        edge = Path("/edge")
        assert _sbc_dir(aarch64_direct_profile, edge) == edge / "sbc" / "rpi4"

    def test_t100ta(self, x86_uefi32_profile):
        edge = Path("/edge")
        assert _sbc_dir(x86_uefi32_profile, edge) == edge / "sbc" / "t100ta"

    def test_zero2w(self, aarch64_zero2w_profile):
        edge = Path("/edge")
        assert _sbc_dir(aarch64_zero2w_profile, edge) == edge / "sbc" / "rpi-zero2w"

    def test_rg35xx_h(self, aarch64_rg35xx_h_profile):
        edge = Path("/edge")
        assert _sbc_dir(aarch64_rg35xx_h_profile, edge) == edge / "sbc" / "rg35xx-h"

    def test_r36s(self, aarch64_r36s_profile):
        edge = Path("/edge")
        assert _sbc_dir(aarch64_r36s_profile, edge) == edge / "sbc" / "r36s"


class TestGetInitPath:
    """Test init= path extraction from grub.cfg."""

    def test_extracts_nix_store_path(self, tmp_path):
        grub_dir = tmp_path / "EFI" / "BOOT"
        grub_dir.mkdir(parents=True)
        (grub_dir / "grub.cfg").write_text(
            "linux /boot/bzImage init=/nix/store/abc123-nixos-system/init "
            "root=LABEL=iso\n"
        )
        assert _get_init_path(tmp_path) == "/nix/store/abc123-nixos-system/init"

    def test_raises_on_missing_init(self, tmp_path):
        grub_dir = tmp_path / "EFI" / "BOOT"
        grub_dir.mkdir(parents=True)
        (grub_dir / "grub.cfg").write_text("menuentry 'NixOS' { }\n")
        with pytest.raises(RuntimeError, match="Could not find init path"):
            _get_init_path(tmp_path)

    def test_multiple_init_lines_picks_first(self, tmp_path):
        grub_dir = tmp_path / "EFI" / "BOOT"
        grub_dir.mkdir(parents=True)
        (grub_dir / "grub.cfg").write_text(
            "linux /boot/bzImage init=/nix/store/first/init root=LABEL=iso\n"
            "linux /boot/bzImage init=/nix/store/second/init nomodeset\n"
        )
        assert _get_init_path(tmp_path) == "/nix/store/first/init"


class TestGenerateGrubCfg:
    """Test grub.cfg generation."""

    def test_contains_init_path(self):
        cfg = _generate_grub_cfg("/nix/store/abc123/init")
        assert "init=/nix/store/abc123/init" in cfg

    def test_has_both_menuentries(self):
        cfg = _generate_grub_cfg("/nix/store/abc/init")
        assert "menuentry 'NixOS Installer'" in cfg
        assert "menuentry 'NixOS Installer (nomodeset)'" in cfg

    def test_nomodeset_entry_has_flag(self):
        cfg = _generate_grub_cfg("/nix/store/abc/init")
        lines = cfg.splitlines()
        nomodeset_lines = [ln for ln in lines if "nomodeset" in ln]
        assert len(nomodeset_lines) >= 1


# ===================================================================
# WiFi config generation
# ===================================================================


class TestWifiConf:
    """Test wifi.conf writing with various SSID/password edge cases."""

    @pytest.mark.asyncio
    async def test_simple_ssid_password(
        self, tmp_path, x86_uefi64_profile, fake_edge_dir,
    ):
        target = FlashTarget(
            device=x86_uefi64_profile,
            disk_path="/dev/disk4",
            wifi_ssid="MyNetwork",
            wifi_password="MyPassword",
        )
        await collect(
            _copy_styrene_files(tmp_path, x86_uefi64_profile, target, fake_edge_dir)
        )
        wifi = (tmp_path / "styrene" / "wifi.conf").read_text()
        assert 'ssid="MyNetwork"' in wifi
        assert 'psk="MyPassword"' in wifi

    @pytest.mark.asyncio
    async def test_ssid_with_double_quotes(
        self, tmp_path, x86_uefi64_profile, fake_edge_dir,
    ):
        target = FlashTarget(
            device=x86_uefi64_profile,
            disk_path="/dev/disk4",
            wifi_ssid='My "Smart" WiFi',
            wifi_password="pass",
        )
        await collect(
            _copy_styrene_files(tmp_path, x86_uefi64_profile, target, fake_edge_dir)
        )
        wifi = (tmp_path / "styrene" / "wifi.conf").read_text()
        assert r'ssid="My \"Smart\" WiFi"' in wifi

    @pytest.mark.asyncio
    async def test_password_with_backslash(
        self, tmp_path, x86_uefi64_profile, fake_edge_dir,
    ):
        target = FlashTarget(
            device=x86_uefi64_profile,
            disk_path="/dev/disk4",
            wifi_ssid="Net",
            wifi_password=r"pass\word",
        )
        await collect(
            _copy_styrene_files(tmp_path, x86_uefi64_profile, target, fake_edge_dir)
        )
        wifi = (tmp_path / "styrene" / "wifi.conf").read_text()
        assert r'psk="pass\\word"' in wifi

    @pytest.mark.asyncio
    async def test_no_wifi_skips_conf(
        self, tmp_path, x86_uefi64_profile, fake_edge_dir,
    ):
        target = FlashTarget(
            device=x86_uefi64_profile,
            disk_path="/dev/disk4",
        )
        events = await collect(
            _copy_styrene_files(tmp_path, x86_uefi64_profile, target, fake_edge_dir)
        )
        assert not (tmp_path / "styrene" / "wifi.conf").exists()
        assert any("No WiFi" in e.message for e in events)


# ===================================================================
# Styrene file copy tests
# ===================================================================


class TestCopyStyreneFiles:
    """Test _copy_styrene_files with various device profiles."""

    @pytest.mark.asyncio
    async def test_x86_copies_bond_and_config(
        self, tmp_path, x86_uefi64_profile, fake_edge_dir,
    ):
        target = FlashTarget(
            device=x86_uefi64_profile, disk_path="/dev/disk4",
        )
        await collect(
            _copy_styrene_files(tmp_path, x86_uefi64_profile, target, fake_edge_dir)
        )
        styrene_dir = tmp_path / "styrene"
        assert (styrene_dir / "polymerize.sh").exists()
        assert (styrene_dir / "configuration.nix").exists()
        assert (styrene_dir / "wifi.conf.example").exists()

    @pytest.mark.asyncio
    async def test_bond_script_is_executable(
        self, tmp_path, x86_uefi64_profile, fake_edge_dir,
    ):
        target = FlashTarget(
            device=x86_uefi64_profile, disk_path="/dev/disk4",
        )
        await collect(
            _copy_styrene_files(tmp_path, x86_uefi64_profile, target, fake_edge_dir)
        )
        bond = tmp_path / "styrene" / "polymerize.sh"
        assert bond.stat().st_mode & stat.S_IXUSR

    @pytest.mark.asyncio
    async def test_rpi4_no_bond_script(
        self, tmp_path, aarch64_direct_profile, fake_edge_dir,
    ):
        """RPi4 has no bond_script — should not copy polymerize.sh."""
        target = FlashTarget(
            device=aarch64_direct_profile, disk_path="/dev/disk3",
        )
        await collect(
            _copy_styrene_files(
                tmp_path, aarch64_direct_profile, target, fake_edge_dir,
            )
        )
        assert not (tmp_path / "styrene" / "polymerize.sh").exists()
        assert (tmp_path / "styrene" / "configuration.nix").exists()

    @pytest.mark.asyncio
    async def test_emits_stage_event(
        self, tmp_path, x86_uefi64_profile, fake_edge_dir,
    ):
        target = FlashTarget(
            device=x86_uefi64_profile, disk_path="/dev/disk4",
        )
        events = await collect(
            _copy_styrene_files(tmp_path, x86_uefi64_profile, target, fake_edge_dir)
        )
        assert events[0].kind == "stage"
        assert events[0].stage == StageKey.STYRENE_FILES


# ===================================================================
# Dependency check tests
# ===================================================================


class TestCheckDependencies:
    """Mock shutil.which and subprocess to test dependency checking."""

    @pytest.mark.asyncio
    async def test_x86_uefi64_needs_bsdtar(self, x86_uefi64_profile):
        with patch("styrened.tui.forge.media_writer.shutil.which") as mock_which:
            mock_which.return_value = None
            events = await collect(mw._check_dependencies(x86_uefi64_profile))
        assert has_error(events)
        assert "bsdtar" in events[-1].message

    @pytest.mark.asyncio
    async def test_x86_uefi64_all_present(self, x86_uefi64_profile):
        with patch("styrened.tui.forge.media_writer.shutil.which") as mock_which:
            mock_which.return_value = "/usr/bin/bsdtar"
            events = await collect(mw._check_dependencies(x86_uefi64_profile))
        assert not has_error(events)
        assert "All dependencies satisfied" in events[-1].message

    @pytest.mark.asyncio
    async def test_uefi32_needs_podman(self, x86_uefi32_profile):
        def which_side_effect(cmd):
            return "/usr/bin/bsdtar" if cmd == "bsdtar" else None

        with patch("styrened.tui.forge.media_writer.shutil.which", side_effect=which_side_effect):
            events = await collect(mw._check_dependencies(x86_uefi32_profile))
        assert has_error(events)
        assert "podman" in events[-1].message

    @pytest.mark.asyncio
    async def test_nix_device_needs_nix_and_zstd(self, aarch64_direct_profile):
        """Nix device (rpi4) requires nix + zstd."""
        with patch("styrened.tui.forge.media_writer.shutil.which") as mock_which:
            mock_which.return_value = None
            events = await collect(mw._check_dependencies(aarch64_direct_profile))
        assert has_error(events)
        assert "nix" in events[-1].message

    @pytest.mark.asyncio
    async def test_nix_device_accepts_nix_and_zstd(self, aarch64_direct_profile):
        """Nix device passes when both nix and zstd are available."""
        def which_side_effect(cmd):
            if cmd in ("bsdtar", "nix", "zstd"):
                return f"/usr/bin/{cmd}"
            return None

        with patch("styrened.tui.forge.media_writer.shutil.which", side_effect=which_side_effect):
            events = await collect(mw._check_dependencies(aarch64_direct_profile))
        assert not has_error(events)

    @pytest.mark.asyncio
    async def test_nix_device_missing_zstd(self, aarch64_direct_profile):
        """Nix device fails when zstd is missing (even if nix is present)."""
        def which_side_effect(cmd):
            if cmd in ("bsdtar", "nix"):
                return f"/usr/bin/{cmd}"
            return None

        with patch("styrened.tui.forge.media_writer.shutil.which", side_effect=which_side_effect):
            events = await collect(mw._check_dependencies(aarch64_direct_profile))
        assert has_error(events)
        assert "zstd" in events[-1].message

    @pytest.mark.asyncio
    async def test_nix_device_does_not_need_podman(self, aarch64_direct_profile):
        """Nix device does NOT require podman."""
        def which_side_effect(cmd):
            if cmd in ("bsdtar", "nix", "zstd"):
                return f"/usr/bin/{cmd}"
            return None

        with patch("styrened.tui.forge.media_writer.shutil.which", side_effect=which_side_effect):
            events = await collect(mw._check_dependencies(aarch64_direct_profile))
        assert not has_error(events)


# ===================================================================
# Download tests
# ===================================================================


class TestDownloadFile:
    """Test download with mocked urllib."""

    @pytest.mark.asyncio
    async def test_skips_when_cached(self, tmp_path):
        dest = tmp_path / "test.iso"
        dest.write_bytes(b"cached")
        events = await collect(mw._download_file("http://x", dest, "test"))
        assert "already downloaded" in events[0].message

    @pytest.mark.asyncio
    async def test_cleans_orphaned_partial(self, tmp_path):
        dest = tmp_path / "test.iso"
        partial = tmp_path / "test.iso.partial"
        partial.write_bytes(b"orphaned garbage")

        with patch("styrened.tui.forge.media_writer.urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.headers.get.return_value = "4"
            mock_resp.read.side_effect = [b"data", b""]
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            await collect(mw._download_file("http://x", dest, "test"))

        assert dest.exists()
        assert not partial.exists()

    @pytest.mark.asyncio
    async def test_incomplete_download_raises(self, tmp_path):
        dest = tmp_path / "test.iso"

        with patch("styrened.tui.forge.media_writer.urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.headers.get.return_value = "1000"  # expect 1000 bytes
            mock_resp.read.side_effect = [b"short", b""]  # only 5 bytes
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            with pytest.raises(RuntimeError, match="Incomplete download"):
                await collect(mw._download_file("http://x", dest, "test"))


# ===================================================================
# Extract / decompress tests
# ===================================================================


class TestExtractIso:
    """Test ISO extraction with mocked bsdtar."""

    @pytest.mark.asyncio
    async def test_skips_when_already_extracted(self, tmp_path):
        extract_dir = tmp_path / "extracted"
        (extract_dir / "boot").mkdir(parents=True)
        (extract_dir / "boot" / "bzImage").write_bytes(b"kernel")

        events = await collect(mw._extract_iso(tmp_path / "x.iso", extract_dir))
        assert "already extracted" in events[0].message

    @pytest.mark.asyncio
    async def test_calls_bsdtar(self, tmp_path):
        iso = tmp_path / "test.iso"
        iso.write_bytes(b"iso")
        extract = tmp_path / "out"

        with patch.object(mw, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "", "")
            events = await collect(mw._extract_iso(iso, extract))

        mock_cmd.assert_called_once_with(
            "bsdtar", "-xf", str(iso), "-C", str(extract),
        )
        assert any("ISO extracted" in e.message for e in events)


class TestDecompressZstd:
    """Test zstd decompression with mocked subprocess."""

    @pytest.mark.asyncio
    async def test_skips_when_decompressed(self, tmp_path):
        output = tmp_path / "image.img"
        output.write_bytes(b"img")
        compressed = tmp_path / "image.img.zst"

        events = await collect(mw._decompress_zstd(compressed, output))
        assert "already decompressed" in events[0].message

    @pytest.mark.asyncio
    async def test_uses_zstd_when_available(self, tmp_path):
        compressed = tmp_path / "image.img.zst"
        compressed.write_bytes(b"compressed")
        output = tmp_path / "image.img"

        with patch("styrened.tui.forge.media_writer.shutil.which", return_value="/usr/bin/zstd"):
            with patch.object(mw, "_run_cmd") as mock_cmd:
                mock_cmd.return_value = (0, "", "")
                await collect(mw._decompress_zstd(compressed, output))

        mock_cmd.assert_called_once_with(
            "zstd", "-d", str(compressed), "-o", str(output),
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_podman(self, tmp_path):
        compressed = tmp_path / "image.img.zst"
        compressed.write_bytes(b"compressed")
        output = tmp_path / "image.img"

        with patch("styrened.tui.forge.media_writer.shutil.which", return_value=None):
            with patch.object(mw, "_run_cmd") as mock_cmd:
                mock_cmd.return_value = (0, "", "")
                await collect(mw._decompress_zstd(compressed, output))

        cmd_args = mock_cmd.call_args[0]
        assert "podman" in cmd_args


# ===================================================================
# Media event stream / orchestrator tests
# ===================================================================


class TestRunMediaWriter:
    """Integration tests for the full orchestrator with all I/O mocked."""

    @pytest.mark.asyncio
    async def test_missing_deps_aborts_early(self, x86_usb_target):
        with patch("styrened.tui.forge.media_writer.shutil.which", return_value=None):
            events = await collect(
                run_media_writer(x86_usb_target, edge_dir=Path("/fake"))
            )
        assert has_error(events)
        assert not has_complete(events)
        s = stages(events)
        assert StageKey.DEPS in s
        assert StageKey.DOWNLOAD not in s

    @pytest.mark.asyncio
    async def test_unsupported_arch_errors(self, tmp_path):
        """Device with unsupported arch emits error event."""
        bad_profile = DeviceProfile(
            id="bad", label="Bad", model="Bad",
            arch="mips",  # type: ignore[arg-type]
            boot_type="uefi64", media_type="installer",
            media_target="usb",
            nixos_config="sbc/bad/configuration.nix",
            bond_script=None, default_hostname="bad-01",
            specs=_specs(),
        )
        target = FlashTarget(device=bad_profile, disk_path="/dev/disk9")

        with patch("styrened.tui.forge.media_writer.shutil.which", return_value="/usr/bin/bsdtar"):
            events = await collect(run_media_writer(target, edge_dir=tmp_path))

        assert has_error(events)
        assert any("Unsupported architecture" in e.message for e in events)

    @pytest.mark.asyncio
    async def test_exception_becomes_error_event(self, x86_usb_target, tmp_path):
        """RuntimeError from a stage is caught and yielded as error event."""
        with patch("styrened.tui.forge.media_writer.shutil.which", return_value="/usr/bin/x"):
            with patch.object(mw, "_download_file") as mock_dl:
                async def _boom(*a, **kw):
                    raise RuntimeError("network exploded")
                    yield  # noqa: F841 — unreachable, makes it an async generator
                mock_dl.return_value = _boom()
                events = await collect(
                    run_media_writer(x86_usb_target, edge_dir=tmp_path)
                )

        assert has_error(events)
        assert any("network exploded" in e.message for e in events)

    @pytest.mark.asyncio
    async def test_x86_full_pipeline_stages(self, x86_usb_target, fake_edge_dir):
        """Verify all 7 stages fire for a complete x86 USB pipeline."""
        efi_mount = fake_edge_dir / "efi"
        data_mount = fake_edge_dir / "data"

        async def _stub_partition(*args, **kwargs):
            yield mw._log("  Partitioning (stubbed)...")
            yield mw._log(f"MOUNTS:{efi_mount}|{data_mount}")

        async def _stub_styrene_files(*args, **kwargs):
            yield mw._stage(StageKey.STYRENE_FILES, "Adding Styrene automation...")
            yield mw._log("Styrene files copied (stubbed)")

        async def _stub_finish(*args, **kwargs):
            yield mw._stage(StageKey.FINISH, "Syncing and ejecting...")
            yield MediaEvent(kind="complete", message="Media creation complete")

        with (
            patch("styrened.tui.forge.media_writer.shutil.which", return_value="/usr/bin/x"),
            patch.object(mw, "_download_file", side_effect=_noop_async_gen),
            patch.object(mw, "_extract_iso", side_effect=_noop_async_gen),
            patch.object(mw, "_unmount_disk", new_callable=AsyncMock),
            patch.object(mw, "_partition_x86", side_effect=_stub_partition),
            patch.object(mw, "_get_init_path", return_value="/nix/store/abc/init"),
            patch("styrened.tui.forge.media_writer.shutil.copy2"),
            patch("styrened.tui.forge.media_writer.shutil.copytree"),
            patch.object(mw, "_copy_styrene_files", side_effect=_stub_styrene_files),
            patch.object(mw, "_finish_media", side_effect=_stub_finish),
        ):
            (efi_mount / "EFI" / "BOOT").mkdir(parents=True)
            (efi_mount / "boot").mkdir(parents=True)
            (data_mount / "boot").mkdir(parents=True)

            events = await collect(
                run_media_writer(x86_usb_target, edge_dir=fake_edge_dir)
            )

        s = stages(events)
        assert StageKey.DEPS in s
        assert StageKey.DOWNLOAD in s
        assert StageKey.EXTRACT in s
        assert StageKey.PARTITION in s
        assert StageKey.COPY in s
        assert StageKey.STYRENE_FILES in s
        assert StageKey.FINISH in s
        assert has_complete(events)


# ===================================================================
# Platform-specific behavior tests
# ===================================================================


class TestDdCommand:
    """Verify dd argument construction differs by platform."""

    @pytest.mark.asyncio
    async def test_macos_omits_status_progress(self):
        """On macOS, dd should NOT include status=progress."""
        with patch.object(mw, "_IS_MACOS", True):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc

                with patch.object(mw, "_run_cmd", return_value=(0, "", "")):
                    with patch.object(mw, "_unmount_disk"):
                        with patch.object(mw, "_remount_nixos_partition", return_value=None):
                            profile = DeviceProfile(
                                id="rpi4", label="RPi4", model="test",
                                arch="aarch64", boot_type="uboot",
                                media_type="direct", media_target="sd",
                                nixos_config="sbc/rpi4/configuration.nix",
                                bond_script=None, default_hostname="rpi4-01",
                                specs=_specs(),
                            )
                            target = FlashTarget(device=profile, disk_path="/dev/disk3")
                            await collect(
                                mw._prepare_aarch64_direct(
                                    "/dev/disk3", profile, target, Path("/fake"),
                                )
                            )

                dd_call_args = mock_exec.call_args[0]
                assert "status=progress" not in dd_call_args

    @pytest.mark.asyncio
    async def test_linux_includes_status_progress(self):
        """On Linux, dd SHOULD include status=progress."""
        with patch.object(mw, "_IS_MACOS", False):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc

                with patch.object(mw, "_run_cmd", return_value=(0, "", "")):
                    with patch.object(mw, "_unmount_disk"):
                        with patch.object(mw, "_remount_nixos_partition", return_value=None):
                            profile = DeviceProfile(
                                id="rpi4", label="RPi4", model="test",
                                arch="aarch64", boot_type="uboot",
                                media_type="direct", media_target="sd",
                                nixos_config="sbc/rpi4/configuration.nix",
                                bond_script=None, default_hostname="rpi4-01",
                                specs=_specs(),
                            )
                            target = FlashTarget(device=profile, disk_path="/dev/sda")
                            await collect(
                                mw._prepare_aarch64_direct(
                                    "/dev/sda", profile, target, Path("/fake"),
                                )
                            )

                dd_call_args = mock_exec.call_args[0]
                assert "status=progress" in dd_call_args


class TestUnmountDisk:
    """Verify unmount uses correct strategy per platform."""

    @pytest.mark.asyncio
    async def test_macos_uses_diskutil(self):
        with patch.object(mw, "_IS_MACOS", True):
            with patch.object(mw, "_run_cmd") as mock_cmd:
                mock_cmd.return_value = (0, "", "")
                await mw._unmount_disk("/dev/disk4")
        mock_cmd.assert_called_once_with(
            "diskutil", "unmountDisk", "/dev/disk4",
            sudo=True, check=False,
        )

    @pytest.mark.asyncio
    async def test_linux_uses_shell_glob(self):
        with patch.object(mw, "_IS_MACOS", False):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = AsyncMock()
                mock_proc.communicate.return_value = (b"", b"")
                mock_exec.return_value = mock_proc
                await mw._unmount_disk("/dev/sda")

        call_args = mock_exec.call_args[0]
        assert "sudo" in call_args
        assert "sh" in call_args
        assert "-c" in call_args
        shell_cmd = call_args[3]
        assert "umount /dev/sda*" in shell_cmd


# ===================================================================
# Media type coverage (USB vs SD, installer vs direct)
# ===================================================================


class TestMediaTypeBranching:
    """Verify correct code path taken for each device type."""

    @pytest.mark.asyncio
    async def test_installer_calls_x86_prepare(self, x86_usb_target, fake_edge_dir):
        with (
            patch("styrened.tui.forge.media_writer.shutil.which", return_value="/usr/bin/x"),
            patch.object(mw, "_download_file", side_effect=_noop_async_gen),
            patch.object(mw, "_extract_iso", side_effect=_noop_async_gen),
            patch.object(mw, "_prepare_x86_installer", side_effect=_noop_async_gen) as mock_x86,
            patch.object(mw, "_prepare_aarch64_direct", side_effect=_noop_async_gen) as mock_arm,
            patch.object(mw, "_finish_media", side_effect=_noop_async_gen),
        ):
            await collect(run_media_writer(x86_usb_target, edge_dir=fake_edge_dir))

        mock_x86.assert_called_once()
        mock_arm.assert_not_called()

    @pytest.mark.asyncio
    async def test_nix_device_calls_nix_pipeline(self, aarch64_sd_target, fake_edge_dir):
        """Nix device (rpi4) routes through _run_nix_media_pipeline."""
        with (
            patch("styrened.tui.forge.media_writer.shutil.which", return_value="/usr/bin/x"),
            patch.object(mw, "_run_nix_media_pipeline", side_effect=_noop_async_gen) as mock_nix,
            patch.object(mw, "_run_stock_media_pipeline", side_effect=_noop_async_gen) as mock_stock,
        ):
            await collect(run_media_writer(aarch64_sd_target, edge_dir=fake_edge_dir))

        mock_nix.assert_called_once()
        mock_stock.assert_not_called()
