"""Fleet device models.

Data models for fleet device tracking and management.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

DeviceStatus = Literal["online", "offline", "pending", "error"]


@dataclass
class Device:
    """Represents a fleet device.

    Attributes:
        name: Unique device name/hostname.
        profile: Profile ID used for provisioning (e.g., "node", "edge-router").
        hardware: Hardware ID (e.g., "rpi-zero2w", "t100ta").
        status: Current device status.
        last_seen: Timestamp of last check-in or None if never seen.
        reticulum_identity: Reticulum identity hex string, if known.
        ip_address: IP address if available.
        notes: Optional notes about the device.
    """

    name: str
    profile: str
    hardware: str
    status: DeviceStatus
    last_seen: datetime | None = None
    reticulum_identity: str | None = None
    ip_address: str | None = None
    notes: str | None = None

    @property
    def is_online(self) -> bool:
        """Return True if device is online."""
        return self.status == "online"

    @property
    def is_offline(self) -> bool:
        """Return True if device is offline."""
        return self.status == "offline"

    @property
    def is_pending(self) -> bool:
        """Return True if device is pending provisioning."""
        return self.status == "pending"

    @property
    def has_error(self) -> bool:
        """Return True if device has an error."""
        return self.status == "error"

    @property
    def last_seen_display(self) -> str:
        """Return human-readable last seen time."""
        if self.last_seen is None:
            return "-"

        now = datetime.now()
        delta = now - self.last_seen

        if delta.total_seconds() < 60:
            return "just now"
        elif delta.total_seconds() < 3600:
            minutes = int(delta.total_seconds() / 60)
            return f"{minutes}m ago"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"{hours}h ago"
        else:
            days = int(delta.total_seconds() / 86400)
            return f"{days}d ago"
