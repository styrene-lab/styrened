"""Unit tests for system_info service.

Tests OS detection, NixOS generation extraction, and system fingerprint
generation for announce data and status responses.
"""
from __future__ import annotations

from unittest.mock import mock_open, patch

from styrened.services.system_info import get_os_info, get_system_fingerprint


class TestGetOsInfo:
    """Tests for get_os_info() OS detection."""

    def test_linux_os_release_parsing(self):
        """Parse /etc/os-release for ID and VERSION_ID on Linux."""
        os_release_content = (
            'NAME="NixOS"\n'
            "ID=nixos\n"
            'VERSION_ID="24.11"\n'
            'PRETTY_NAME="NixOS 24.11 (Vicuna)"\n'
        )
        with (
            patch("builtins.open", mock_open(read_data=os_release_content)),
            patch("os.readlink", side_effect=OSError),
        ):
            info = get_os_info()
        assert info["os_id"] == "nixos"
        assert info["os_version"] == "24.11"

    def test_linux_debian(self):
        """Parse Debian /etc/os-release."""
        os_release_content = "ID=debian\nVERSION_ID=13\n"
        with (
            patch("builtins.open", mock_open(read_data=os_release_content)),
            patch("os.readlink", side_effect=OSError),
        ):
            info = get_os_info()
        assert info["os_id"] == "debian"
        assert info["os_version"] == "13"

    def test_linux_quoted_values(self):
        """Handle quoted values in os-release (common on Ubuntu)."""
        os_release_content = 'ID="ubuntu"\nVERSION_ID="22.04"\n'
        with (
            patch("builtins.open", mock_open(read_data=os_release_content)),
            patch("os.readlink", side_effect=OSError),
        ):
            info = get_os_info()
        assert info["os_id"] == "ubuntu"
        assert info["os_version"] == "22.04"

    def test_macos_fallback(self):
        """Fall back to platform module when /etc/os-release missing."""
        with (
            patch("builtins.open", side_effect=FileNotFoundError),
            patch("platform.system", return_value="Darwin"),
            patch("platform.mac_ver", return_value=("15.3", ("", "", ""), "")),
        ):
            info = get_os_info()
        assert info["os_id"] == "darwin"
        assert info["os_version"] == "15.3"

    def test_nixos_generation_from_symlink(self):
        """Extract NixOS generation hash from /run/current-system symlink."""
        with (
            patch("builtins.open", mock_open(read_data="ID=nixos\nVERSION_ID=24.11\n")),
            patch(
                "os.readlink",
                return_value="/nix/store/zah57xw1234abcdef-nixos-system-24.11",
            ),
        ):
            info = get_os_info()
        assert info["nixos_generation"] == "zah57xw"

    def test_nixos_generation_missing(self):
        """Gracefully handle missing /run/current-system (non-NixOS)."""
        with (
            patch("builtins.open", mock_open(read_data="ID=debian\nVERSION_ID=13\n")),
            patch("os.readlink", side_effect=OSError("No such file")),
        ):
            info = get_os_info()
        assert info["nixos_generation"] == ""

    def test_arch_from_platform(self):
        """Architecture comes from platform.machine()."""
        with (
            patch("builtins.open", mock_open(read_data="ID=nixos\nVERSION_ID=24.11\n")),
            patch("os.readlink", side_effect=OSError),
            patch("platform.machine", return_value="aarch64"),
        ):
            info = get_os_info()
        assert info["arch"] == "aarch64"


class TestGetSystemFingerprint:
    """Tests for get_system_fingerprint() compact announce string."""

    def test_nixos_fingerprint_format(self):
        """NixOS fingerprint: nixos|24.11|x86_64|zah57xw."""
        with (
            patch("builtins.open", mock_open(read_data="ID=nixos\nVERSION_ID=24.11\n")),
            patch(
                "os.readlink",
                return_value="/nix/store/zah57xw1234abcdef-nixos-system-24.11",
            ),
            patch("platform.machine", return_value="x86_64"),
        ):
            fp = get_system_fingerprint()
        assert fp == "nixos|24.11|x86_64|zah57xw"

    def test_debian_fingerprint_format(self):
        """Debian fingerprint: debian|13|x86_64| (no nix gen)."""
        with (
            patch("builtins.open", mock_open(read_data="ID=debian\nVERSION_ID=13\n")),
            patch("os.readlink", side_effect=OSError),
            patch("platform.machine", return_value="x86_64"),
        ):
            fp = get_system_fingerprint()
        assert fp == "debian|13|x86_64|"

    def test_macos_fingerprint_format(self):
        """macOS fingerprint: darwin|15.3|aarch64| (no nix gen)."""
        with (
            patch("builtins.open", side_effect=FileNotFoundError),
            patch("platform.system", return_value="Darwin"),
            patch("platform.mac_ver", return_value=("15.3", ("", "", ""), "")),
            patch("platform.machine", return_value="aarch64"),
        ):
            fp = get_system_fingerprint()
        assert fp == "darwin|15.3|aarch64|"

    def test_fingerprint_is_compact(self):
        """Fingerprint should stay under 40 bytes for mesh efficiency."""
        with (
            patch("builtins.open", mock_open(read_data="ID=nixos\nVERSION_ID=24.11\n")),
            patch(
                "os.readlink",
                return_value="/nix/store/zah57xw1234abcdef-nixos-system-24.11",
            ),
            patch("platform.machine", return_value="x86_64"),
        ):
            fp = get_system_fingerprint()
        assert len(fp) < 40

    def test_fingerprint_pipe_delimited_four_fields(self):
        """Fingerprint always has exactly 4 pipe-delimited fields."""
        with (
            patch("builtins.open", mock_open(read_data="ID=nixos\nVERSION_ID=24.11\n")),
            patch("os.readlink", side_effect=OSError),
            patch("platform.machine", return_value="x86_64"),
        ):
            fp = get_system_fingerprint()
        assert fp.count("|") == 3
        parts = fp.split("|")
        assert len(parts) == 4

    def test_fingerprint_no_colons(self):
        """Fingerprint must not contain colons (announce field delimiter)."""
        with (
            patch("builtins.open", mock_open(read_data="ID=nixos\nVERSION_ID=24.11\n")),
            patch("os.readlink", side_effect=OSError),
            patch("platform.machine", return_value="x86_64"),
        ):
            fp = get_system_fingerprint()
        assert ":" not in fp
