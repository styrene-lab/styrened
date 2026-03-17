"""Unit tests for the platform-aware service installer."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import pytest

from styrened.tui.services.service_installer import (
    LAUNCHD_LABEL,
    LAUNCHD_LOG_DIR,
    SYSTEMD_UNIT_PATH,
    ServiceInfo,
    ServicePlatform,
    ServiceStatus,
    detect_platform,
    generate_launchd_plist,
    generate_systemd_unit,
    get_service_status,
    get_styrened_executable,
    install_service,
    uninstall_service,
)


class TestDetectPlatform:
    """Test platform detection logic."""

    def test_darwin_returns_launchd(self):
        """macOS should be detected as launchd."""
        with patch.object(sys, "platform", "darwin"):
            assert detect_platform() == ServicePlatform.LAUNCHD

    def test_linux_with_systemctl_returns_systemd(self):
        """Linux with systemctl available should be detected as systemd."""
        with (
            patch.object(sys, "platform", "linux"),
            patch("styrened.tui.services.service_installer.shutil.which", return_value="/usr/bin/systemctl"),
        ):
            assert detect_platform() == ServicePlatform.SYSTEMD

    def test_linux_without_systemctl_returns_unsupported(self):
        """Linux without systemctl should be unsupported."""
        with (
            patch.object(sys, "platform", "linux"),
            patch("styrened.tui.services.service_installer.shutil.which", return_value=None),
        ):
            assert detect_platform() == ServicePlatform.UNSUPPORTED

    def test_windows_returns_unsupported(self):
        """Windows should be unsupported."""
        with patch.object(sys, "platform", "win32"):
            assert detect_platform() == ServicePlatform.UNSUPPORTED

    def test_freebsd_returns_unsupported(self):
        """FreeBSD should be unsupported."""
        with patch.object(sys, "platform", "freebsd"):
            assert detect_platform() == ServicePlatform.UNSUPPORTED


class TestGetStyreneExecutable:
    """Test executable resolution."""

    def test_finds_on_path(self):
        """Should find styrened via shutil.which."""
        with patch(
            "styrened.tui.services.service_installer.shutil.which",
            return_value="/usr/local/bin/styrened",
        ):
            result = get_styrened_executable()
            assert result == Path("/usr/local/bin/styrened")

    def test_finds_sibling_of_python(self, tmp_path):
        """Should find styrened next to sys.executable."""
        fake_bin = tmp_path / "bin"
        fake_bin.mkdir()
        fake_python = fake_bin / "python"
        fake_python.touch()
        fake_styrened = fake_bin / "styrened"
        fake_styrened.touch()

        with (
            patch("styrened.tui.services.service_installer.shutil.which", return_value=None),
            patch.object(sys, "executable", str(fake_python)),
        ):
            result = get_styrened_executable()
            assert result == fake_styrened

    def test_returns_none_when_not_found(self, tmp_path):
        """Should return None when styrened cannot be found."""
        fake_python = tmp_path / "python"
        fake_python.touch()

        with (
            patch("styrened.tui.services.service_installer.shutil.which", return_value=None),
            patch.object(sys, "executable", str(fake_python)),
        ):
            result = get_styrened_executable()
            assert result is None


class TestGenerateLaunchdPlist:
    """Test launchd plist generation."""

    def test_valid_xml(self):
        """Generated plist should be valid XML."""
        plist = generate_launchd_plist(Path("/usr/local/bin/styrened"))
        # Should parse without error
        ET.fromstring(plist)

    def test_contains_label(self):
        """Plist should contain the correct label."""
        plist = generate_launchd_plist(Path("/usr/local/bin/styrened"))
        assert LAUNCHD_LABEL in plist

    def test_contains_executable_path(self):
        """Plist should contain the styrened executable path."""
        path = Path("/opt/styrene/bin/styrened")
        plist = generate_launchd_plist(path)
        assert str(path) in plist

    def test_contains_daemon_argument(self):
        """Plist should include 'daemon' as argument."""
        plist = generate_launchd_plist(Path("/usr/local/bin/styrened"))
        assert "<string>daemon</string>" in plist

    def test_keep_alive_enabled(self):
        """Plist should have KeepAlive set to true."""
        plist = generate_launchd_plist(Path("/usr/local/bin/styrened"))
        assert "<key>KeepAlive</key>" in plist
        # KeepAlive should be followed by true
        lines = plist.splitlines()
        for i, line in enumerate(lines):
            if "KeepAlive" in line and "<key>" in line:
                assert "<true/>" in lines[i + 1]
                break

    def test_run_at_load_enabled(self):
        """Plist should have RunAtLoad set to true."""
        plist = generate_launchd_plist(Path("/usr/local/bin/styrened"))
        assert "<key>RunAtLoad</key>" in plist

    def test_log_paths_set(self):
        """Plist should set stdout and stderr log paths."""
        plist = generate_launchd_plist(Path("/usr/local/bin/styrened"))
        assert "StandardOutPath" in plist
        assert "StandardErrorPath" in plist
        assert str(LAUNCHD_LOG_DIR) in plist


class TestGenerateSystemdUnit:
    """Test systemd unit file generation."""

    def test_contains_exec_start(self):
        """Unit should contain ExecStart with correct path."""
        path = Path("/usr/local/bin/styrened")
        unit = generate_systemd_unit(path)
        assert f"ExecStart={path} daemon" in unit

    def test_restart_on_failure(self):
        """Unit should restart on failure."""
        unit = generate_systemd_unit(Path("/usr/local/bin/styrened"))
        assert "Restart=on-failure" in unit

    def test_wanted_by_default_target(self):
        """Unit should be wanted by default.target for user session."""
        unit = generate_systemd_unit(Path("/usr/local/bin/styrened"))
        assert "WantedBy=default.target" in unit

    def test_network_dependency(self):
        """Unit should depend on network-online.target."""
        unit = generate_systemd_unit(Path("/usr/local/bin/styrened"))
        assert "After=network-online.target" in unit

    def test_has_description(self):
        """Unit should have a Description."""
        unit = generate_systemd_unit(Path("/usr/local/bin/styrened"))
        assert "Description=Styrene Daemon" in unit

    def test_all_sections_present(self):
        """Unit should have [Unit], [Service], and [Install] sections."""
        unit = generate_systemd_unit(Path("/usr/local/bin/styrened"))
        assert "[Unit]" in unit
        assert "[Service]" in unit
        assert "[Install]" in unit


class TestServiceInfo:
    """Test ServiceInfo dataclass."""

    def test_default_fields(self):
        """ServiceInfo should have sensible defaults."""
        info = ServiceInfo(
            platform=ServicePlatform.LAUNCHD,
            status=ServiceStatus.NOT_INSTALLED,
        )
        assert info.unit_path is None
        assert info.error is None
        assert info.pid is None
        assert info.extra == {}

    def test_all_fields(self):
        """ServiceInfo should accept all fields."""
        info = ServiceInfo(
            platform=ServicePlatform.SYSTEMD,
            status=ServiceStatus.RUNNING,
            unit_path=SYSTEMD_UNIT_PATH,
            pid=1234,
        )
        assert info.platform == ServicePlatform.SYSTEMD
        assert info.status == ServiceStatus.RUNNING
        assert info.pid == 1234


class TestGetServiceStatus:
    """Test service status checking."""

    @pytest.mark.asyncio
    async def test_unsupported_platform_returns_not_installed(self):
        """Unsupported platform should return NOT_INSTALLED."""
        with patch(
            "styrened.tui.services.service_installer.detect_platform",
            return_value=ServicePlatform.UNSUPPORTED,
        ):
            info = await get_service_status()
            assert info.status == ServiceStatus.NOT_INSTALLED
            assert info.platform == ServicePlatform.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_launchd_not_installed(self):
        """Should detect missing launchd plist."""
        with (
            patch(
                "styrened.tui.services.service_installer.detect_platform",
                return_value=ServicePlatform.LAUNCHD,
            ),
            patch.object(Path, "exists", return_value=False),
        ):
            info = await get_service_status()
            assert info.status == ServiceStatus.NOT_INSTALLED
            assert info.platform == ServicePlatform.LAUNCHD

    @pytest.mark.asyncio
    async def test_systemd_not_installed(self):
        """Should detect missing systemd unit."""
        with (
            patch(
                "styrened.tui.services.service_installer.detect_platform",
                return_value=ServicePlatform.SYSTEMD,
            ),
            patch.object(Path, "exists", return_value=False),
        ):
            info = await get_service_status()
            assert info.status == ServiceStatus.NOT_INSTALLED
            assert info.platform == ServicePlatform.SYSTEMD


class TestInstallService:
    """Test service installation."""

    @pytest.mark.asyncio
    async def test_install_fails_without_executable(self):
        """Installation should fail if styrened is not found."""
        with (
            patch(
                "styrened.tui.services.service_installer.detect_platform",
                return_value=ServicePlatform.LAUNCHD,
            ),
            patch(
                "styrened.tui.services.service_installer.get_styrened_executable",
                return_value=None,
            ),
        ):
            info = await install_service()
            assert info.status == ServiceStatus.ERROR
            assert "not found" in info.error

    @pytest.mark.asyncio
    async def test_install_unsupported_platform(self):
        """Installation should fail on unsupported platforms."""
        with (
            patch(
                "styrened.tui.services.service_installer.detect_platform",
                return_value=ServicePlatform.UNSUPPORTED,
            ),
            patch(
                "styrened.tui.services.service_installer.get_styrened_executable",
                return_value=Path("/usr/local/bin/styrened"),
            ),
        ):
            info = await install_service()
            assert info.status == ServiceStatus.ERROR
            assert "Unsupported" in info.error


class TestUninstallService:
    """Test service uninstallation."""

    @pytest.mark.asyncio
    async def test_uninstall_unsupported_platform(self):
        """Uninstall should fail on unsupported platforms."""
        with patch(
            "styrened.tui.services.service_installer.detect_platform",
            return_value=ServicePlatform.UNSUPPORTED,
        ):
            info = await uninstall_service()
            assert info.status == ServiceStatus.ERROR
