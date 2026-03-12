"""Unit tests for BinaryProvisioner — binary acquisition and verification."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import struct
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from styrened.services.binary_errors import BinaryIntegrityError, UnsupportedPlatformError
from styrened.services.binary_provisioner import BinaryProvisioner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manifest_path():
    """Path to the real manifest."""
    return Path(__file__).parent.parent.parent / "src" / "styrened" / "data" / "binary_manifest.json"


@pytest.fixture
def provisioner(tmp_path):
    """BinaryProvisioner with install_dir overridden to tmp_path."""
    return BinaryProvisioner(install_dir=tmp_path)


@pytest.fixture
def manifest_data(manifest_path):
    """Load manifest as dict."""
    with open(manifest_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 1. Manifest schema validation
# ---------------------------------------------------------------------------

class TestManifestSchema:
    def test_schema_version(self, manifest_data):
        assert manifest_data["schema_version"] == 1

    def test_has_both_adapters(self, manifest_data):
        assert "yggdrasil" in manifest_data["adapters"]
        assert "i2pd" in manifest_data["adapters"]

    def test_adapter_entry_fields(self, manifest_data):
        for name, entry in manifest_data["adapters"].items():
            assert "version" in entry, f"{name} missing version"
            assert "upstream_repo" in entry, f"{name} missing upstream_repo"
            assert "platforms" in entry, f"{name} missing platforms"
            assert "binary_name" in entry, f"{name} missing binary_name"

    def test_platform_entry_fields(self, manifest_data):
        required = {"asset", "sha256", "binary_path_in_archive", "binary_sha256", "archive_format"}
        for adapter_name, adapter in manifest_data["adapters"].items():
            for platform_key, plat in adapter["platforms"].items():
                missing = required - set(plat.keys())
                assert not missing, f"{adapter_name}/{platform_key} missing {missing}"

    def test_all_target_architectures_yggdrasil(self, manifest_data):
        platforms = set(manifest_data["adapters"]["yggdrasil"]["platforms"].keys())
        assert {"linux-amd64", "linux-arm64", "linux-armhf", "darwin-arm64"} <= platforms

    def test_all_target_architectures_i2pd(self, manifest_data):
        platforms = set(manifest_data["adapters"]["i2pd"]["platforms"].keys())
        assert {"linux-amd64", "linux-arm64", "linux-armhf", "darwin-arm64"} <= platforms

    def test_sha256_hashes_are_64_hex_chars(self, manifest_data):
        for adapter_name, adapter in manifest_data["adapters"].items():
            for plat_key, plat in adapter["platforms"].items():
                for field in ("sha256", "binary_sha256"):
                    val = plat[field]
                    assert len(val) == 64 and all(c in "0123456789abcdef" for c in val), \
                        f"{adapter_name}/{plat_key}/{field} invalid: {val}"

    def test_archive_formats_are_known(self, manifest_data):
        known = {"deb", "tar.gz", "pkg"}
        for adapter_name, adapter in manifest_data["adapters"].items():
            for plat_key, plat in adapter["platforms"].items():
                assert plat["archive_format"] in known, \
                    f"{adapter_name}/{plat_key} unknown format: {plat['archive_format']}"


# ---------------------------------------------------------------------------
# 2. Platform detection
# ---------------------------------------------------------------------------

class TestPlatformDetection:
    @patch("platform.machine", return_value="x86_64")
    @patch("sys.platform", "linux")
    def test_linux_amd64(self, _mock):
        p = BinaryProvisioner()
        assert p.detect_platform() == "linux-amd64"

    @patch("platform.machine", return_value="aarch64")
    @patch("sys.platform", "linux")
    def test_linux_arm64(self, _mock):
        p = BinaryProvisioner()
        assert p.detect_platform() == "linux-arm64"

    @patch("platform.machine", return_value="armv7l")
    @patch("sys.platform", "linux")
    def test_linux_armhf(self, _mock):
        p = BinaryProvisioner()
        assert p.detect_platform() == "linux-armhf"

    @patch("platform.machine", return_value="arm64")
    @patch("sys.platform", "darwin")
    def test_darwin_arm64(self, _mock):
        p = BinaryProvisioner()
        assert p.detect_platform() == "darwin-arm64"

    @patch("platform.machine", return_value="riscv64")
    @patch("sys.platform", "linux")
    def test_unsupported_returns_raw(self, _mock):
        p = BinaryProvisioner()
        assert p.detect_platform() == "linux-riscv64"


# ---------------------------------------------------------------------------
# 3. SHA-256 verification
# ---------------------------------------------------------------------------

class TestVerifyBinary:
    def test_valid_hash_passes(self, provisioner, tmp_path):
        binary = tmp_path / "test_binary"
        binary.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        # Should not raise
        provisioner.verify_hash(binary, expected)

    def test_invalid_hash_raises(self, provisioner, tmp_path):
        binary = tmp_path / "test_binary"
        binary.write_bytes(b"hello world")
        with pytest.raises(BinaryIntegrityError, match="integrity check failed"):
            provisioner.verify_hash(binary, "0" * 64, adapter_name="test")


# ---------------------------------------------------------------------------
# 4. Unsupported platform error
# ---------------------------------------------------------------------------

class TestUnsupportedPlatform:
    @pytest.mark.asyncio
    async def test_provision_unsupported_platform(self, provisioner):
        with patch.object(provisioner, "detect_platform", return_value="linux-riscv64"):
            with pytest.raises(UnsupportedPlatformError, match="linux-riscv64"):
                await provisioner.provision("yggdrasil")


# ---------------------------------------------------------------------------
# 5. Progress callback
# ---------------------------------------------------------------------------

class TestProgressCallback:
    @pytest.mark.asyncio
    async def test_progress_called_during_download(self, provisioner, tmp_path):
        """Verify on_progress receives (downloaded, total) tuples."""
        # Create a fake binary and archive
        binary_content = b"fake yggdrasil binary " * 100
        binary_hash = hashlib.sha256(binary_content).hexdigest()

        # Build a minimal tar.gz with the binary
        archive_buf = BytesIO()
        with tarfile.open(fileobj=archive_buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="usr/bin/yggdrasil")
            info.size = len(binary_content)
            info.mode = 0o755
            tf.addfile(info, BytesIO(binary_content))
        archive_bytes = archive_buf.getvalue()
        archive_hash = hashlib.sha256(archive_bytes).hexdigest()

        # Patch manifest to use tar.gz format with our hashes
        fake_manifest = {
            "schema_version": 1,
            "adapters": {
                "yggdrasil": {
                    "version": "0.5.13",
                    "upstream_repo": "yggdrasil-network/yggdrasil-go",
                    "binary_name": "yggdrasil",
                    "platforms": {
                        "linux-amd64": {
                            "asset": "test.tar.gz",
                            "sha256": archive_hash,
                            "binary_path_in_archive": "usr/bin/yggdrasil",
                            "binary_sha256": binary_hash,
                            "archive_format": "tar.gz",
                        }
                    },
                }
            },
        }

        progress_calls = []

        def on_progress(downloaded: int, total: int) -> None:
            progress_calls.append((downloaded, total))

        # Mock the download to return our archive bytes
        async def mock_download(url, dest, on_progress=None):
            dest.write_bytes(archive_bytes)
            if on_progress:
                on_progress(len(archive_bytes), len(archive_bytes))

        with patch.object(provisioner, "_load_manifest", return_value=fake_manifest), \
             patch.object(provisioner, "detect_platform", return_value="linux-amd64"), \
             patch.object(provisioner, "_download_asset", side_effect=mock_download):
            result = await provisioner.provision("yggdrasil", on_progress=on_progress)

        assert len(progress_calls) > 0
        assert progress_calls[-1][0] == progress_calls[-1][1]  # final: downloaded == total
        assert result.exists()
        assert os.access(result, os.X_OK)


# ---------------------------------------------------------------------------
# 6. Archive extraction
# ---------------------------------------------------------------------------

class TestArchiveExtraction:
    def test_extract_tar_gz(self, provisioner, tmp_path):
        """Extract binary from a tar.gz archive."""
        binary_content = b"test binary content"
        archive_path = tmp_path / "test.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tf:
            info = tarfile.TarInfo(name="usr/bin/yggdrasil")
            info.size = len(binary_content)
            info.mode = 0o755
            tf.addfile(info, BytesIO(binary_content))

        result = provisioner._extract_binary(
            archive_path, "usr/bin/yggdrasil", "tar.gz", tmp_path / "work"
        )
        assert result.read_bytes() == binary_content

    def test_extract_tar_gz_path_traversal_blocked(self, provisioner, tmp_path):
        """Ensure path traversal in tar entries is blocked."""
        binary_content = b"evil"
        archive_path = tmp_path / "evil.tar.gz"
        with tarfile.open(archive_path, "w:gz") as tf:
            info = tarfile.TarInfo(name="../../../etc/evil")
            info.size = len(binary_content)
            tf.addfile(info, BytesIO(binary_content))

        with pytest.raises((ValueError, Exception)):
            provisioner._extract_binary(
                archive_path, "../../../etc/evil", "tar.gz", tmp_path / "work"
            )

    def test_extract_deb(self, provisioner, tmp_path):
        """Extract binary from a .deb archive."""
        binary_content = b"i2pd binary content"

        # Build a minimal .deb: ar archive with data.tar.gz member
        data_tar_buf = BytesIO()
        with tarfile.open(fileobj=data_tar_buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="usr/sbin/i2pd")
            info.size = len(binary_content)
            info.mode = 0o755
            tf.addfile(info, BytesIO(binary_content))
        data_tar_bytes = data_tar_buf.getvalue()

        # Build ar archive
        archive_path = tmp_path / "test.deb"
        with open(archive_path, "wb") as f:
            f.write(b"!<arch>\n")
            # ar header: name(16) mtime(12) uid(6) gid(6) mode(8) size(10) fmag(2)
            name = b"data.tar.gz"
            header = (
                name.ljust(16) +
                b"0           " +  # mtime
                b"0     " +  # uid
                b"0     " +  # gid
                b"100644  " +  # mode
                str(len(data_tar_bytes)).encode().ljust(10) +
                b"`\n"
            )
            f.write(header)
            f.write(data_tar_bytes)
            if len(data_tar_bytes) % 2:
                f.write(b"\n")

        result = provisioner._extract_binary(
            archive_path, "usr/sbin/i2pd", "deb", tmp_path / "work"
        )
        assert result.read_bytes() == binary_content


# ---------------------------------------------------------------------------
# 7. Full provision flow (mocked download)
# ---------------------------------------------------------------------------

class TestProvisionFlow:
    @pytest.mark.asyncio
    async def test_successful_provision(self, provisioner, tmp_path):
        binary_content = b"yggdrasil binary " * 50
        binary_hash = hashlib.sha256(binary_content).hexdigest()

        archive_buf = BytesIO()
        with tarfile.open(fileobj=archive_buf, mode="w:gz") as tf:
            info = tarfile.TarInfo(name="usr/bin/yggdrasil")
            info.size = len(binary_content)
            info.mode = 0o755
            tf.addfile(info, BytesIO(binary_content))
        archive_bytes = archive_buf.getvalue()
        archive_hash = hashlib.sha256(archive_bytes).hexdigest()

        fake_manifest = {
            "schema_version": 1,
            "adapters": {
                "yggdrasil": {
                    "version": "0.5.13",
                    "upstream_repo": "yggdrasil-network/yggdrasil-go",
                    "binary_name": "yggdrasil",
                    "platforms": {
                        "linux-amd64": {
                            "asset": "test.tar.gz",
                            "sha256": archive_hash,
                            "binary_path_in_archive": "usr/bin/yggdrasil",
                            "binary_sha256": binary_hash,
                            "archive_format": "tar.gz",
                        }
                    },
                }
            },
        }

        async def mock_download(url, dest, on_progress=None):
            dest.write_bytes(archive_bytes)
            if on_progress:
                on_progress(len(archive_bytes), len(archive_bytes))

        with patch.object(provisioner, "_load_manifest", return_value=fake_manifest), \
             patch.object(provisioner, "detect_platform", return_value="linux-amd64"), \
             patch.object(provisioner, "_download_asset", side_effect=mock_download):
            result = await provisioner.provision("yggdrasil")

        assert result == provisioner.install_dir / "yggdrasil"
        assert result.read_bytes() == binary_content
        assert os.access(result, os.X_OK)

    @pytest.mark.asyncio
    async def test_archive_hash_mismatch_aborts(self, provisioner, tmp_path):
        """If archive SHA-256 doesn't match, no file should be installed."""
        fake_manifest = {
            "schema_version": 1,
            "adapters": {
                "yggdrasil": {
                    "version": "0.5.13",
                    "upstream_repo": "yggdrasil-network/yggdrasil-go",
                    "binary_name": "yggdrasil",
                    "platforms": {
                        "linux-amd64": {
                            "asset": "test.tar.gz",
                            "sha256": "a" * 64,  # won't match
                            "binary_path_in_archive": "usr/bin/yggdrasil",
                            "binary_sha256": "b" * 64,
                            "archive_format": "tar.gz",
                        }
                    },
                }
            },
        }

        async def mock_download(url, dest, on_progress=None):
            dest.write_bytes(b"not the right content")

        with patch.object(provisioner, "_load_manifest", return_value=fake_manifest), \
             patch.object(provisioner, "detect_platform", return_value="linux-amd64"), \
             patch.object(provisioner, "_download_asset", side_effect=mock_download):
            with pytest.raises(BinaryIntegrityError):
                await provisioner.provision("yggdrasil")

        # Ensure nothing was installed
        assert not (provisioner.install_dir / "yggdrasil").exists()

    @pytest.mark.asyncio
    async def test_unknown_adapter_raises(self, provisioner):
        with pytest.raises(ValueError, match="Unknown adapter"):
            await provisioner.provision("wireguard")
