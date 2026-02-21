"""Tests for forge bundle_builder — bundle assembly service.

All subprocess and filesystem operations are mocked where necessary.
"""

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from styrened.tui.forge.bundle_builder import (
    _assemble_styrene_files,
    _build_nix_bundle,
    _build_stock_bundle,
    build_bundle,
)
from styrened.tui.forge.models import (
    Bundle,
    FlashTarget,
    MediaEvent,
    StageKey,
)
from tests.forge.conftest import collect, has_complete, has_error, stages


# Helper for mocking async generators
async def _noop_async_gen(*args, **kwargs):
    return
    yield


# ===================================================================
# Nix bundle pipeline
# ===================================================================


class TestBuildBundleNix:
    """Test Nix bundle build pipeline (rpi4, zero2w, etc.)."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self, tmp_path, aarch64_sd_target, fake_edge_dir):
        """Full nix pipeline writes manifest and emits all stages."""
        bundle = Bundle.create(tmp_path / "bundles", aarch64_sd_target)

        # Mock resolve_nix_image to return a fake image
        nix_img = tmp_path / "fake-image.img.zst"
        nix_img.write_bytes(b"\x28\xb5\x2f\xfd" + b"\x00" * 100)

        async def _mock_resolve(flake_output, edge_dir):
            from styrened.tui.forge.nix_build import _log
            yield _log("Resolving..."), None
            yield _log("Done"), nix_img

        with (
            patch("styrened.tui.forge.bundle_builder._check_dependencies", side_effect=_noop_async_gen),
            patch("styrened.tui.forge.bundle_builder.resolve_nix_image", side_effect=_mock_resolve),
        ):
            events = await collect(
                build_bundle(aarch64_sd_target, bundle, fake_edge_dir)
            )

        assert has_complete(events)
        assert not has_error(events)
        assert bundle.manifest_path.exists()

        # Check stages
        s = stages(events)
        assert StageKey.DOWNLOAD in s
        assert StageKey.EXTRACT in s
        assert StageKey.STYRENE_FILES in s
        assert StageKey.FINISH in s

    @pytest.mark.asyncio
    async def test_errors_on_failed_nix_image(self, tmp_path, aarch64_sd_target, fake_edge_dir):
        """Error event when nix image resolution fails."""
        bundle = Bundle.create(tmp_path / "bundles", aarch64_sd_target)

        async def _mock_resolve_fail(flake_output, edge_dir):
            from styrened.tui.forge.nix_build import _error
            yield _error("nix build failed"), None

        with (
            patch("styrened.tui.forge.bundle_builder._check_dependencies", side_effect=_noop_async_gen),
            patch("styrened.tui.forge.bundle_builder.resolve_nix_image", side_effect=_mock_resolve_fail),
        ):
            events = await collect(
                build_bundle(aarch64_sd_target, bundle, fake_edge_dir)
            )

        assert has_error(events)
        assert not has_complete(events)


# ===================================================================
# Stock bundle pipeline (x86, stock aarch64)
# ===================================================================


class TestBuildBundleStock:
    """Test stock (non-Nix) bundle build pipeline."""

    @pytest.mark.asyncio
    async def test_x86_pipeline(self, tmp_path, x86_usb_target, fake_edge_dir):
        """x86 stock pipeline creates bundle with EFI and data files."""
        bundle = Bundle.create(tmp_path / "bundles", x86_usb_target)

        async def _stub_download(*args, **kwargs):
            return
            yield

        async def _stub_extract(*args, **kwargs):
            return
            yield

        async def _stub_assemble(*args, **kwargs):
            from styrened.tui.forge.media_writer import _stage, _log
            yield _stage(StageKey.STYRENE_FILES, "Assembling...")
            yield _log("Done")

        def _fake_copy2(src, dst):
            """Create the destination file so stat() succeeds."""
            dst = Path(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"\x00" * 1024)

        work = tmp_path / "work"
        work.mkdir(parents=True)

        # Create fake extract dir structure under the mocked WORK_DIR
        ext = work / "nixos-x86_64-extracted"
        (ext / "EFI" / "BOOT").mkdir(parents=True)
        (ext / "boot").mkdir(parents=True)
        (ext / "EFI" / "BOOT" / "BOOTX64.EFI").write_bytes(b"efi")
        (ext / "EFI" / "BOOT" / "grub.cfg").write_text("init=/nix/store/abc/init")
        (ext / "boot" / "bzImage").write_bytes(b"kernel")
        (ext / "boot" / "initrd").write_bytes(b"initrd")
        (ext / "nix-store.squashfs").write_bytes(b"squashfs")

        # Create fake ISO so the code can find it
        iso_path = work / "nixos-minimal-24.11-x86_64.iso"
        iso_path.write_bytes(b"\x00" * 2048)

        with (
            patch("styrened.tui.forge.bundle_builder._check_dependencies", side_effect=_noop_async_gen),
            patch("styrened.tui.forge.bundle_builder._download_file", side_effect=_stub_download),
            patch("styrened.tui.forge.bundle_builder._extract_iso", side_effect=_stub_extract),
            patch("styrened.tui.forge.bundle_builder._get_init_path", return_value="/nix/store/abc/init"),
            patch("styrened.tui.forge.bundle_builder.shutil.copy2", side_effect=_fake_copy2),
            patch("styrened.tui.forge.bundle_builder.shutil.copytree"),
            patch("styrened.tui.forge.bundle_builder._assemble_styrene_files", side_effect=_stub_assemble),
            patch("styrened.tui.forge.bundle_builder._generate_grub_cfg", return_value="grub cfg content"),
            patch("styrened.tui.forge.bundle_builder.WORK_DIR", work),
        ):
            events = await collect(
                build_bundle(x86_usb_target, bundle, fake_edge_dir)
            )

        s = stages(events)
        assert not has_error(events)
        assert StageKey.FINISH in s
        assert has_complete(events)

    @pytest.mark.asyncio
    async def test_dep_failure_aborts(self, tmp_path, x86_usb_target, fake_edge_dir):
        """Dependency check failure stops the pipeline."""
        bundle = Bundle.create(tmp_path / "bundles", x86_usb_target)

        async def _fail_deps(profile):
            from styrened.tui.forge.media_writer import _stage, _error
            yield _stage(StageKey.DEPS, "Checking...")
            yield _error("Missing: bsdtar")

        with patch("styrened.tui.forge.bundle_builder._check_dependencies", side_effect=_fail_deps):
            events = await collect(
                build_bundle(x86_usb_target, bundle, fake_edge_dir)
            )

        assert has_error(events)
        assert not has_complete(events)


# ===================================================================
# Styrene files assembly
# ===================================================================


class TestAssembleStyreneFiles:
    """Test _assemble_styrene_files detail behavior."""

    @pytest.mark.asyncio
    async def test_copies_bond_script(self, tmp_path, x86_usb_target, fake_edge_dir):
        """x86 profile copies polymerize.sh."""
        bundle = Bundle.create(tmp_path / "bundles", x86_usb_target)

        events = await collect(
            _assemble_styrene_files(bundle, x86_usb_target, fake_edge_dir)
        )

        bond = bundle.styrene_dir / "polymerize.sh"
        assert bond.exists()
        assert any("polymerize" in e.message for e in events)

    @pytest.mark.asyncio
    async def test_skips_bond_when_absent(self, tmp_path, aarch64_sd_target, fake_edge_dir):
        """RPi4 profile (no bond_script) skips polymerize.sh."""
        bundle = Bundle.create(tmp_path / "bundles", aarch64_sd_target)

        events = await collect(
            _assemble_styrene_files(bundle, aarch64_sd_target, fake_edge_dir)
        )

        assert not (bundle.styrene_dir / "polymerize.sh").exists()

    @pytest.mark.asyncio
    async def test_bakes_hostname(self, tmp_path, x86_usb_target, fake_edge_dir):
        """Hostname is baked into configuration.nix."""
        # Update the config template to have the placeholder
        x86_config = fake_edge_dir / "sbc" / "x86-generic" / "configuration.nix"
        x86_config.write_text("hostName = \"HOSTNAME_PLACEHOLDER\";")

        bundle = Bundle.create(tmp_path / "bundles", x86_usb_target)
        x86_usb_target.hostname = "test-node"

        events = await collect(
            _assemble_styrene_files(bundle, x86_usb_target, fake_edge_dir)
        )

        config_text = (bundle.styrene_dir / "configuration.nix").read_text()
        assert "test-node" in config_text
        assert "HOSTNAME_PLACEHOLDER" not in config_text
        assert (bundle.styrene_dir / "hostname").read_text().strip() == "test-node"

    @pytest.mark.asyncio
    async def test_bakes_ssh_keys(self, tmp_path, x86_usb_target, fake_edge_dir):
        """SSH authorized keys are baked into configuration.nix."""
        x86_config = fake_edge_dir / "sbc" / "x86-generic" / "configuration.nix"
        x86_config.write_text("AUTHORIZED_KEYS_PLACEHOLDER")

        ssh_key_file = tmp_path / "id_ed25519.pub"
        ssh_key_file.write_text("ssh-ed25519 AAAA test@host\n")

        x86_usb_target.ssh_key_path = str(ssh_key_file)
        bundle = Bundle.create(tmp_path / "bundles", x86_usb_target)

        events = await collect(
            _assemble_styrene_files(bundle, x86_usb_target, fake_edge_dir)
        )

        config_text = (bundle.styrene_dir / "configuration.nix").read_text()
        assert "ssh-ed25519 AAAA test@host" in config_text
        assert "AUTHORIZED_KEYS_PLACEHOLDER" not in config_text
        assert (bundle.styrene_dir / "authorized_keys").exists()

    @pytest.mark.asyncio
    async def test_copies_wheels(self, tmp_path, x86_usb_target, fake_edge_dir):
        """Copies Python wheels for airgapped install."""
        wheels_dir = fake_edge_dir / "forge" / "wheels"
        wheels_dir.mkdir(parents=True)
        (wheels_dir / "pkg-1.0.whl").write_text("fake wheel")

        bundle = Bundle.create(tmp_path / "bundles", x86_usb_target)

        events = await collect(
            _assemble_styrene_files(bundle, x86_usb_target, fake_edge_dir)
        )

        assert (bundle.styrene_dir / "wheels" / "pkg-1.0.whl").exists()
        assert any("wheel" in e.message for e in events)

    @pytest.mark.asyncio
    async def test_writes_wifi_conf(self, tmp_path, x86_usb_target, fake_edge_dir):
        """WiFi config is written when SSID is set."""
        bundle = Bundle.create(tmp_path / "bundles", x86_usb_target)

        events = await collect(
            _assemble_styrene_files(bundle, x86_usb_target, fake_edge_dir)
        )

        wifi = bundle.styrene_dir / "wifi.conf"
        assert wifi.exists()
        content = wifi.read_text()
        assert "TestNet" in content

    @pytest.mark.asyncio
    async def test_copies_common_modules(self, tmp_path, x86_usb_target, fake_edge_dir):
        """Common NixOS modules are copied."""
        bundle = Bundle.create(tmp_path / "bundles", x86_usb_target)

        events = await collect(
            _assemble_styrene_files(bundle, x86_usb_target, fake_edge_dir)
        )

        common = bundle.styrene_dir / "common"
        assert common.is_dir()
        assert (common / "base.nix").exists()
        assert (common / "network.nix").exists()


# ===================================================================
# Error handling
# ===================================================================


class TestBuildBundleErrorHandling:
    """Test error handling in build_bundle."""

    @pytest.mark.asyncio
    async def test_exception_becomes_error_event(self, tmp_path, x86_usb_target, fake_edge_dir):
        """Exception in pipeline becomes error event."""
        bundle = Bundle.create(tmp_path / "bundles", x86_usb_target)

        async def _explode(target, bundle, edge_dir):
            raise RuntimeError("disk full")
            yield  # make it an async generator

        with patch("styrened.tui.forge.bundle_builder._build_bundle_pipeline", side_effect=_explode):
            events = await collect(
                build_bundle(x86_usb_target, bundle, fake_edge_dir)
            )

        assert has_error(events)
        assert any("disk full" in e.message for e in events)
