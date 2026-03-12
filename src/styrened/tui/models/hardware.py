"""Hardware detection models — re-export from shared location.

This module re-exports from styrened.models.hardware for backward compatibility.
New code should import directly from styrened.models.hardware.
"""
from __future__ import annotations


from styrened.models.hardware import (  # noqa: F401
    DiskInfo,
    DiskType,
    InterfaceCategory,
    NetworkInterface,
    NetworkInterfaceType,
    SystemInfo,
    infer_interface_category,
)

__all__ = [
    "DiskInfo",
    "DiskType",
    "InterfaceCategory",
    "NetworkInterface",
    "NetworkInterfaceType",
    "SystemInfo",
    "infer_interface_category",
]
