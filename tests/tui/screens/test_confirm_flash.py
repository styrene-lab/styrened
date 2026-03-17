"""Tests for ConfirmFlash modal."""
from __future__ import annotations

from styrened.tui.screens.confirm_flash import ConfirmFlash


def test_confirm_flash_instantiation():
    """ConfirmFlash can be instantiated with required parameters."""
    modal = ConfirmFlash(
        device_label="RPi 4B",
        device_model="Raspberry Pi 4 Model B",
        disk_path="/dev/disk3",
        disk_name="SanDisk Ultra",
        disk_size="32.0 GB",
    )
    assert modal is not None


def test_confirm_flash_stores_parameters():
    """ConfirmFlash stores all display parameters."""
    modal = ConfirmFlash(
        device_label="T100TA",
        device_model="ASUS Transformer",
        disk_path="/dev/disk5",
        disk_name="Kingston",
        disk_size="16.0 GB",
    )
    assert modal._device_label == "T100TA"
    assert modal._device_model == "ASUS Transformer"
    assert modal._disk_path == "/dev/disk5"
    assert modal._disk_name == "Kingston"
    assert modal._disk_size == "16.0 GB"
