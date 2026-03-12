"""Tests for forge disk detection — macOS and Linux.

All subprocess calls (diskutil, lsblk) are mocked.
"""
from __future__ import annotations


import json
import subprocess
from unittest.mock import MagicMock, patch

from styrened.tui.forge.disk_detect import (
    _detect_linux,
    _detect_macos,
    detect_external_disks,
)
from styrened.tui.forge.models import DiskInfo

# ===================================================================
# macOS detection
# ===================================================================


class TestDetectMacos:
    """Test _detect_macos with mocked diskutil."""

    def test_parse_external_disks(self):
        """Parse diskutil list output with external disks."""
        list_output = (
            "/dev/disk4 (external, physical):\n"
            "   #:                       TYPE NAME                    SIZE\n"
            "   0:      GUID_partition_scheme                        *32.0 GB\n"
        )
        info_output = (
            "   Device Identifier:        disk4\n"
            "   Media Name:               SanDisk Ultra USB 3.0\n"
            "   Disk Size:                32.0 GB (32010928128 Bytes)\n"
            "   Protocol:                 USB\n"
        )

        with (
            patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run,
        ):
            mock_list = MagicMock()
            mock_list.returncode = 0
            mock_list.stdout = list_output

            mock_info = MagicMock()
            mock_info.returncode = 0
            mock_info.stdout = info_output

            mock_run.side_effect = [mock_list, mock_info]

            disks = _detect_macos()

        assert len(disks) == 1
        assert disks[0].device == "/dev/disk4"
        assert disks[0].name == "SanDisk Ultra USB 3.0"
        assert "32.0 GB" in disks[0].size
        assert disks[0].media_type == "USB"

    def test_no_external_disks(self):
        """No external disks found."""
        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            disks = _detect_macos()

        assert disks == []

    def test_diskutil_failure(self):
        """diskutil returns non-zero exit code."""
        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            disks = _detect_macos()

        assert disks == []

    def test_sd_media_type(self):
        """SD card detected via Secure Digital protocol."""
        list_output = "/dev/disk3 (external, physical):\n   ...\n"
        info_output = (
            "   Media Name:               SD Card Reader\n"
            "   Total Size:               16.0 GB (16000000000 Bytes)\n"
            "   Protocol:                 SD\n"
        )

        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_list = MagicMock()
            mock_list.returncode = 0
            mock_list.stdout = list_output

            mock_info = MagicMock()
            mock_info.returncode = 0
            mock_info.stdout = info_output

            mock_run.side_effect = [mock_list, mock_info]

            disks = _detect_macos()

        assert len(disks) == 1
        assert disks[0].media_type == "SD"

    def test_mmc_protocol_is_sd(self):
        """MMC protocol detected as SD media type."""
        list_output = "/dev/disk3 (external, physical):\n   ...\n"
        info_output = (
            "   Media Name:               MMC Storage\n"
            "   Disk Size:                8.0 GB\n"
            "   Protocol:                 MMC\n"
        )

        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_list = MagicMock()
            mock_list.returncode = 0
            mock_list.stdout = list_output

            mock_info = MagicMock()
            mock_info.returncode = 0
            mock_info.stdout = info_output

            mock_run.side_effect = [mock_list, mock_info]

            disks = _detect_macos()

        assert len(disks) == 1
        assert disks[0].media_type == "SD"

    def test_diskutil_info_timeout(self):
        """diskutil info times out for a disk — that disk is skipped."""
        list_output = "/dev/disk4 (external, physical):\n   ...\n"

        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_list = MagicMock()
            mock_list.returncode = 0
            mock_list.stdout = list_output

            mock_run.side_effect = [
                mock_list,
                subprocess.TimeoutExpired(cmd="diskutil", timeout=10),
            ]

            disks = _detect_macos()

        assert disks == []


# ===================================================================
# Linux detection
# ===================================================================


class TestDetectLinux:
    """Test _detect_linux with mocked lsblk."""

    def test_parse_lsblk_json(self):
        """Parse lsblk JSON output with USB and MMC devices."""
        lsblk_data = {
            "blockdevices": [
                {"name": "sda", "size": "32G", "model": "SanDisk Ultra", "type": "disk", "tran": "usb"},
                {"name": "sdb", "size": "500G", "model": "Samsung SSD", "type": "disk", "tran": "sata"},
                {"name": "mmcblk0", "size": "16G", "model": "SD Card", "type": "disk", "tran": "mmc"},
            ]
        }

        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(lsblk_data)
            mock_run.return_value = mock_result

            disks = _detect_linux()

        # Should only include USB and MMC, not SATA
        assert len(disks) == 2
        usb_disk = next(d for d in disks if d.media_type == "USB")
        sd_disk = next(d for d in disks if d.media_type == "SD")

        assert usb_disk.device == "/dev/sda"
        assert usb_disk.name == "SanDisk Ultra"
        assert sd_disk.device == "/dev/mmcblk0"

    def test_filter_non_removable(self):
        """Only USB and MMC transports are included."""
        lsblk_data = {
            "blockdevices": [
                {"name": "nvme0n1", "size": "1T", "model": "Samsung", "type": "disk", "tran": "nvme"},
                {"name": "sda", "size": "2T", "model": "WD", "type": "disk", "tran": "sata"},
            ]
        }

        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(lsblk_data)
            mock_run.return_value = mock_result

            disks = _detect_linux()

        assert disks == []

    def test_lsblk_failure(self):
        """lsblk returns non-zero exit code."""
        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            disks = _detect_linux()

        assert disks == []

    def test_invalid_json(self):
        """lsblk returns invalid JSON."""
        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "not json"
            mock_run.return_value = mock_result

            disks = _detect_linux()

        assert disks == []

    def test_missing_model_defaults_to_unknown(self):
        """Missing model field defaults to 'Unknown'."""
        lsblk_data = {
            "blockdevices": [
                {"name": "sda", "size": "8G", "model": "", "type": "disk", "tran": "usb"},
            ]
        }

        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(lsblk_data)
            mock_run.return_value = mock_result

            disks = _detect_linux()

        assert len(disks) == 1
        assert disks[0].name == "Unknown"

    def test_null_model_defaults_to_unknown(self):
        """Null model field defaults to 'Unknown' instead of crashing."""
        lsblk_data = {
            "blockdevices": [
                {"name": "mmcblk0", "size": "58.2G", "model": None, "type": "disk", "tran": "mmc"},
            ]
        }

        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(lsblk_data)
            mock_run.return_value = mock_result

            disks = _detect_linux()

        assert len(disks) == 1
        assert disks[0].device == "/dev/mmcblk0"
        assert disks[0].name == "Unknown"
        assert disks[0].media_type == "SD"

    def test_whitespace_model_defaults_to_unknown(self):
        """Whitespace-only model values normalize to 'Unknown'."""
        lsblk_data = {
            "blockdevices": [
                {"name": "sda", "size": "8G", "model": "   ", "type": "disk", "tran": "usb"},
            ]
        }

        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(lsblk_data)
            mock_run.return_value = mock_result

            disks = _detect_linux()

        assert len(disks) == 1
        assert disks[0].name == "Unknown"

    def test_null_tran_filtered(self):
        """Devices with null/None transport are filtered out."""
        lsblk_data = {
            "blockdevices": [
                {"name": "loop0", "size": "1G", "model": None, "type": "loop", "tran": None},
            ]
        }

        with patch("styrened.tui.forge.disk_detect.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps(lsblk_data)
            mock_run.return_value = mock_result

            disks = _detect_linux()

        assert disks == []


# ===================================================================
# Top-level detect_external_disks
# ===================================================================


class TestDetectExternalDisks:
    """Test detect_external_disks fallback behavior."""

    def test_tries_macos_first(self):
        """On macOS, uses diskutil path."""
        disk = DiskInfo(device="/dev/disk4", name="USB", size="32G", media_type="USB")

        with (
            patch("styrened.tui.forge.disk_detect._detect_macos", return_value=[disk]) as mock_mac,
            patch("styrened.tui.forge.disk_detect._detect_linux") as mock_linux,
        ):
            result = detect_external_disks()

        assert result == [disk]
        mock_mac.assert_called_once()
        mock_linux.assert_not_called()

    def test_falls_back_to_linux(self):
        """Falls back to lsblk when diskutil not found."""
        disk = DiskInfo(device="/dev/sda", name="USB", size="32G", media_type="USB")

        with (
            patch("styrened.tui.forge.disk_detect._detect_macos", side_effect=FileNotFoundError),
            patch("styrened.tui.forge.disk_detect._detect_linux", return_value=[disk]),
        ):
            result = detect_external_disks()

        assert result == [disk]

    def test_returns_empty_when_both_fail(self):
        """Returns empty list when neither platform command exists."""
        with (
            patch("styrened.tui.forge.disk_detect._detect_macos", side_effect=FileNotFoundError),
            patch("styrened.tui.forge.disk_detect._detect_linux", side_effect=FileNotFoundError),
        ):
            result = detect_external_disks()

        assert result == []
