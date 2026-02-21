"""Hardware detection services — re-export from shared location.

This module re-exports from styrened.services.hardware for backward compatibility.
New code should import directly from styrened.services.hardware.
"""

from styrened.services.hardware import (  # noqa: F401
    PlatformNotSupportedError,
    get_disks,
    get_network_interfaces,
    get_system_info,
)

__all__ = [
    "PlatformNotSupportedError",
    "get_disks",
    "get_network_interfaces",
    "get_system_info",
]
