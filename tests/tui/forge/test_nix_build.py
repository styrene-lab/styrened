"""Tests for forge nix_build — mocked nix build subprocess.

Ported from styrene-edge with updated imports.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from styrened.tui.forge.nix_build import resolve_nix_image, _diagnose_nix_error
from tests.forge.conftest import collect_nix, has_error


class TestResolveNixImage:
    """Test resolve_nix_image with mocked subprocess."""

    @pytest.mark.asyncio
    async def test_success(self, tmp_path):
        """Successful nix build returns .img.zst path."""
        store_path = tmp_path / "nix" / "store" / "abc123-nixos-sd-image"
        sd_dir = store_path / "sd-image"
        sd_dir.mkdir(parents=True)
        img = sd_dir / "nixos-sd-image-24.11-aarch64-linux.img.zst"
        img.write_bytes(b"\x28\xb5\x2f\xfd" + b"\x00" * 100)  # zstd magic + padding

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            f"{store_path}\n".encode(),
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            events, path = await collect_nix(
                resolve_nix_image("packages.aarch64-linux.rpi4-sd", tmp_path)
            )

        assert not has_error(events)
        assert path == img
        assert any("Store path" in e.message for e in events)

    @pytest.mark.asyncio
    async def test_nix_build_failure(self, tmp_path):
        """nix build failure yields error event."""
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"error: flake not found\n")
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            events, path = await collect_nix(
                resolve_nix_image("packages.aarch64-linux.rpi4-sd", tmp_path)
            )

        assert has_error(events)
        assert path is None
        assert any("nix build failed" in e.message for e in events)

    @pytest.mark.asyncio
    async def test_missing_sd_image_dir(self, tmp_path):
        """Error when store path has no sd-image/ directory."""
        store_path = tmp_path / "nix" / "store" / "abc123-empty"
        store_path.mkdir(parents=True)

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            f"{store_path}\n".encode(),
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            events, path = await collect_nix(
                resolve_nix_image("packages.aarch64-linux.rpi4-sd", tmp_path)
            )

        assert has_error(events)
        assert path is None
        assert any("sd-image/" in e.message for e in events)

    @pytest.mark.asyncio
    async def test_no_img_zst_in_sd_image(self, tmp_path):
        """Error when sd-image/ directory contains no .img.zst files."""
        store_path = tmp_path / "nix" / "store" / "abc123-no-zst"
        sd_dir = store_path / "sd-image"
        sd_dir.mkdir(parents=True)
        (sd_dir / "README").write_text("no image here")

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            f"{store_path}\n".encode(),
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            events, path = await collect_nix(
                resolve_nix_image("packages.aarch64-linux.rpi4-sd", tmp_path)
            )

        assert has_error(events)
        assert path is None
        assert any(".img.zst" in e.message for e in events)

    @pytest.mark.asyncio
    async def test_flake_ref_construction(self, tmp_path):
        """Verify the flake ref passed to nix build is correct."""
        store_path = tmp_path / "nix" / "store" / "xyz"
        sd_dir = store_path / "sd-image"
        sd_dir.mkdir(parents=True)
        (sd_dir / "test.img.zst").write_bytes(b"fake")

        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (
            f"{store_path}\n".encode(),
            b"",
        )
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            await collect_nix(
                resolve_nix_image("packages.aarch64-linux.rpi4-sd", tmp_path)
            )

        call_args = mock_exec.call_args[0]
        assert "nix" in call_args
        assert "build" in call_args
        expected_ref = f"{tmp_path / 'sbc'}#packages.aarch64-linux.rpi4-sd"
        assert expected_ref in call_args
        assert "--no-link" in call_args
        assert "--print-out-paths" in call_args


class TestDiagnoseNixError:
    """Test _diagnose_nix_error parses common failure modes."""

    def test_cross_arch_error(self):
        """'Cannot build' + 'required system' → Cachix guidance."""
        stderr = (
            "error: a]aarch64-linux' with "
            "features {} is required to build '/nix/store/abc-drv', "
            "but I am a 'x86_64-linux' with features {}\n"
            "Cannot build derivation: required system is aarch64-linux"
        )
        msg = _diagnose_nix_error(stderr, 1)
        assert "not in Cachix" in msg
        assert "cachix push" in msg

    def test_git_tree_warning_only(self):
        """Pure Git tree warnings produce 'no actionable output'."""
        stderr = "warning: Git tree '/src' is dirty\n"
        msg = _diagnose_nix_error(stderr, 1)
        assert "no actionable output" in msg

    def test_git_tree_warning_filtered(self):
        """Git tree warnings are stripped; real error lines survive."""
        stderr = (
            "warning: Git tree '/src' is dirty\n"
            "error: attribute 'bogus' not found\n"
        )
        msg = _diagnose_nix_error(stderr, 1)
        assert "bogus" in msg
        assert "Git tree" not in msg

    def test_generic_error_tail(self):
        """Generic errors show last 5 lines."""
        lines = [f"line {i}" for i in range(10)]
        stderr = "\n".join(lines)
        msg = _diagnose_nix_error(stderr, 1)
        assert "line 5" in msg
        assert "line 9" in msg
        assert "line 4" not in msg

    def test_empty_stderr(self):
        """Empty stderr produces 'no actionable output'."""
        msg = _diagnose_nix_error("", 1)
        assert "no actionable output" in msg
