"""Tests for DeviceStatusWidget."""

from styrened.tui.models.rpc import StatusResponse


def test_status_response_disk_percentage():
    """StatusResponse calculates disk usage percentage correctly."""
    status = StatusResponse(
        uptime=123456,
        ip="192.168.0.101",
        services=["reticulum"],
        disk_used=4_200_000_000,
        disk_total=28_000_000_000,
    )

    percent = status.disk_usage_percent
    assert 14.0 < percent < 16.0  # ~15%


def test_status_response_formats_disk_usage():
    """StatusResponse formats disk usage as human-readable string."""
    status = StatusResponse(
        uptime=123456,
        ip="192.168.0.101",
        services=["reticulum"],
        disk_used=4_200_000_000,  # 4.2 GB
        disk_total=28_000_000_000,  # 28 GB
    )

    formatted = status.format_disk_usage()
    # Note: 4_200_000_000 bytes / 1024^3 = 3.9 GB (binary)
    assert "3.9" in formatted or "4.0" in formatted  # Should show ~3.9-4.0 GB
    assert "GB" in formatted
    assert "%" in formatted


def test_status_response_formats_uptime_days():
    """StatusResponse formats uptime with days correctly."""
    status = StatusResponse(
        uptime=293856,  # 3 days, 9 hours, 37 minutes
        ip="192.168.0.101",
        services=["reticulum"],
        disk_used=1_000_000_000,
        disk_total=10_000_000_000,
    )

    formatted = status.format_uptime()
    assert "3d" in formatted
    assert "9h" in formatted


def test_status_response_formats_uptime_hours():
    """StatusResponse formats uptime with hours correctly."""
    status = StatusResponse(
        uptime=7200,  # 2 hours
        ip="192.168.0.101",
        services=["reticulum"],
        disk_used=1_000_000_000,
        disk_total=10_000_000_000,
    )

    formatted = status.format_uptime()
    assert "2h" in formatted
    assert "d" not in formatted  # No days


def test_status_response_formats_uptime_minutes():
    """StatusResponse formats uptime with minutes only."""
    status = StatusResponse(
        uptime=900,  # 15 minutes
        ip="192.168.0.101",
        services=["reticulum"],
        disk_used=1_000_000_000,
        disk_total=10_000_000_000,
    )

    formatted = status.format_uptime()
    assert "15m" in formatted
    assert "h" not in formatted  # No hours
    assert "d" not in formatted  # No days


def test_status_response_zero_disk():
    """StatusResponse handles zero disk total gracefully."""
    status = StatusResponse(
        uptime=123456,
        ip="192.168.0.101",
        services=["reticulum"],
        disk_used=0,
        disk_total=0,
    )

    percent = status.disk_usage_percent
    assert percent == 0.0
