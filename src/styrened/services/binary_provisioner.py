"""BinaryProvisioner — acquire adapter binaries from upstream GitHub releases.

Tier 2 of the three-tier provisioning strategy:
  1. Nix closure (air-gap first-class)
  2. BinaryProvisioner (online download from upstream)
  3. OS package manager instructions (fallback)

Downloads release assets, verifies SHA-256 against the shipped manifest,
extracts the binary from .deb/.tar.gz/.pkg archives, and installs to
``~/.styrene/bin/`` (no root required).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from styrened.services.binary_errors import BinaryIntegrityError, UnsupportedPlatformError

log = logging.getLogger(__name__)

# Default install location for provisioned binaries
_DEFAULT_INSTALL_DIR = Path.home() / ".styrene" / "bin"

# Machine name mappings
_MACHINE_MAP: dict[str, str] = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "armhf",
    "armv6l": "armhf",
}

# Platform prefix mappings
_PLATFORM_MAP: dict[str, str] = {
    "linux": "linux",
    "darwin": "darwin",
}


class BinaryProvisioner:
    """Acquires and installs adapter binaries from upstream releases."""

    def __init__(self, install_dir: Path | None = None) -> None:
        self.install_dir = install_dir or _DEFAULT_INSTALL_DIR

    # ------------------------------------------------------------------
    # Platform detection
    # ------------------------------------------------------------------

    def detect_platform(self) -> str:
        """Map current platform to a manifest key like ``linux-amd64``."""
        machine = platform.machine().lower()
        arch = _MACHINE_MAP.get(machine, machine)

        plat = sys.platform.lower()
        os_prefix = _PLATFORM_MAP.get(plat, plat)

        return f"{os_prefix}-{arch}"

    # ------------------------------------------------------------------
    # Manifest loading
    # ------------------------------------------------------------------

    def _load_manifest(self) -> dict[str, Any]:
        """Load the binary manifest shipped with styrened."""
        manifest_path = Path(__file__).parent.parent / "data" / "binary_manifest.json"
        with open(manifest_path) as f:
            return json.load(f)

    # ------------------------------------------------------------------
    # Hash verification
    # ------------------------------------------------------------------

    @staticmethod
    def verify_hash(
        path: Path,
        expected_sha256: str,
        adapter_name: str = "unknown",
    ) -> None:
        """Verify a file's SHA-256 against an expected value.

        Raises :class:`BinaryIntegrityError` on mismatch.
        """
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        actual = h.hexdigest()
        if actual != expected_sha256:
            raise BinaryIntegrityError(adapter_name, expected_sha256, actual)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    async def _download_asset(
        self,
        url: str,
        dest: Path,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        """Download a file from *url* to *dest* with optional progress.

        Uses urllib to avoid adding an aiohttp dependency. Runs the
        blocking download in a thread via asyncio to stay non-blocking.
        """
        import asyncio

        def _do_download() -> None:
            import urllib.request

            req = urllib.request.Request(url, headers={"User-Agent": "styrened-provisioner"})
            with urllib.request.urlopen(req) as resp:  # noqa: S310 — URL from manifest, HTTPS
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with open(dest, "wb") as f:
                    while chunk := resp.read(65536):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _do_download)

    # ------------------------------------------------------------------
    # Archive extraction
    # ------------------------------------------------------------------

    def _extract_binary(
        self,
        archive_path: Path,
        binary_path_in_archive: str,
        archive_format: str,
        work_dir: Path,
    ) -> Path:
        """Extract a single binary from an archive.

        Returns the path to the extracted binary (inside *work_dir*).
        """
        work_dir.mkdir(parents=True, exist_ok=True)

        if archive_format == "tar.gz":
            return self._extract_from_tar(archive_path, binary_path_in_archive, work_dir)
        elif archive_format == "deb":
            return self._extract_from_deb(archive_path, binary_path_in_archive, work_dir)
        elif archive_format == "pkg":
            return self._extract_from_pkg(archive_path, binary_path_in_archive, work_dir)
        else:
            raise ValueError(f"Unknown archive format: {archive_format}")

    def _extract_from_tar(
        self, archive_path: Path, binary_path: str, work_dir: Path
    ) -> Path:
        """Extract from a tar.gz archive with path traversal protection."""
        with tarfile.open(archive_path, "r:gz") as tf:
            # Validate all members for path traversal
            for member in tf.getmembers():
                member_path = os.path.normpath(member.name)
                if member_path.startswith("..") or os.path.isabs(member_path):
                    raise ValueError(
                        f"Path traversal detected in archive: {member.name}"
                    )

            # Extract only the target binary
            normalized = os.path.normpath(binary_path)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise ValueError(f"Path traversal in binary_path: {binary_path}")

            member = tf.getmember(binary_path)
            tf.extract(member, work_dir, filter="data")

        return work_dir / binary_path

    def _extract_from_deb(
        self, archive_path: Path, binary_path: str, work_dir: Path
    ) -> Path:
        """Extract binary from a .deb archive (ar format wrapping data.tar.*)."""
        with open(archive_path, "rb") as f:
            magic = f.read(8)
            if magic != b"!<arch>\n":
                raise ValueError(f"Not an ar archive: {archive_path}")

            while True:
                header = f.read(60)
                if len(header) < 60:
                    break

                name = header[:16].strip().decode().rstrip("/")
                size = int(header[48:58].strip())

                if name.startswith("data.tar"):
                    # Read the data tar into a temp file and extract
                    data = f.read(size)
                    data_path = work_dir / name
                    data_path.write_bytes(data)

                    # Detect compression
                    if name.endswith(".gz"):
                        mode = "r:gz"
                    elif name.endswith(".xz"):
                        mode = "r:xz"
                    elif name.endswith(".zst"):
                        # Python's tarfile doesn't support zstd natively
                        raise ValueError("zstd-compressed .deb not supported")
                    else:
                        mode = "r"

                    return self._extract_from_tar_mode(
                        data_path, binary_path, work_dir, mode
                    )
                else:
                    f.read(size)

                # ar entries are 2-byte aligned
                if size % 2:
                    f.read(1)

        raise ValueError(f"data.tar.* not found in {archive_path}")

    def _extract_from_tar_mode(
        self, tar_path: Path, binary_path: str, work_dir: Path, mode: str
    ) -> Path:
        """Extract with explicit tar mode and path traversal protection."""
        with tarfile.open(tar_path, mode) as tf:
            for member in tf.getmembers():
                member_path = os.path.normpath(member.name)
                if member_path.startswith("..") or os.path.isabs(member_path):
                    raise ValueError(
                        f"Path traversal detected in archive: {member.name}"
                    )

            normalized = os.path.normpath(binary_path)
            if normalized.startswith("..") or os.path.isabs(normalized):
                raise ValueError(f"Path traversal in binary_path: {binary_path}")

            member = tf.getmember(binary_path)
            tf.extract(member, work_dir, filter="data")

        return work_dir / binary_path

    def _extract_from_pkg(
        self, archive_path: Path, binary_path: str, work_dir: Path
    ) -> Path:
        """Extract from a macOS .pkg (xar archive wrapping cpio payload).

        Falls back to tar extraction if xar/cpio are unavailable.
        """
        import subprocess

        # xar extract
        pkg_dir = work_dir / "pkg_extract"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["xar", "-xf", str(archive_path), "-C", str(pkg_dir)],
            check=True,
            capture_output=True,
        )

        # Find the Payload (usually in base.pkg/Payload, gzip-compressed cpio)
        payload_candidates = list(pkg_dir.rglob("Payload"))
        if not payload_candidates:
            raise ValueError(f"No Payload found in .pkg: {archive_path}")

        payload = payload_candidates[0]
        extract_dir = work_dir / "payload_extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        # gunzip | cpio
        subprocess.run(
            f"cat {payload} | gunzip | cpio -id",
            shell=True,  # noqa: S602 — controlled input
            check=True,
            capture_output=True,
            cwd=str(extract_dir),
        )

        result = extract_dir / binary_path
        if not result.exists():
            # Try without leading path
            for candidate in extract_dir.rglob(Path(binary_path).name):
                if candidate.is_file():
                    result = candidate
                    break

        if not result.exists():
            raise FileNotFoundError(
                f"Binary {binary_path} not found in .pkg payload"
            )
        return result

    # ------------------------------------------------------------------
    # Provision (main entry point)
    # ------------------------------------------------------------------

    async def provision(
        self,
        adapter_name: str,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """Download, verify, extract, and install an adapter binary.

        Returns the installed binary path on success.

        Raises:
            ValueError: Unknown adapter name.
            UnsupportedPlatformError: Platform not in manifest.
            BinaryIntegrityError: SHA-256 mismatch.
        """
        manifest = self._load_manifest()
        adapters = manifest.get("adapters", {})

        if adapter_name not in adapters:
            raise ValueError(f"Unknown adapter: {adapter_name!r}")

        adapter_info = adapters[adapter_name]
        platform_key = self.detect_platform()
        platforms = adapter_info.get("platforms", {})

        if platform_key not in platforms:
            raise UnsupportedPlatformError(platform_key)

        plat = platforms[platform_key]
        version = adapter_info["version"]
        repo = adapter_info["upstream_repo"]
        asset = plat["asset"]
        binary_name = adapter_info["binary_name"]

        # Build download URL
        url = f"https://github.com/{repo}/releases/download/v{version}/{asset}"
        # i2pd tags don't have 'v' prefix
        if repo == "PurpleI2P/i2pd":
            url = f"https://github.com/{repo}/releases/download/{version}/{asset}"

        self.install_dir.mkdir(parents=True, exist_ok=True)
        installed_path = self.install_dir / binary_name

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            archive_path = tmp / asset
            work_dir = tmp / "work"

            # Download
            log.info("Downloading %s from %s", adapter_name, url)
            await self._download_asset(url, archive_path, on_progress=on_progress)

            # Verify archive hash
            log.info("Verifying archive SHA-256 for %s", adapter_name)
            self.verify_hash(archive_path, plat["sha256"], adapter_name)

            # Extract
            log.info("Extracting %s binary", adapter_name)
            extracted = self._extract_binary(
                archive_path,
                plat["binary_path_in_archive"],
                plat["archive_format"],
                work_dir,
            )

            # Verify extracted binary hash
            log.info("Verifying binary SHA-256 for %s", adapter_name)
            self.verify_hash(extracted, plat["binary_sha256"], adapter_name)

            # Install
            shutil.copy2(extracted, installed_path)
            os.chmod(installed_path, 0o755)

        log.info("Installed %s to %s", adapter_name, installed_path)
        return installed_path
