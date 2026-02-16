"""Bare-metal test harness for styrened.

This module re-exports from the unified harness package for backward compatibility.
New code should import directly from tests.harness.ssh.
"""

from __future__ import annotations

# Re-export from unified harness for backward compatibility
from tests.harness.ssh import SSHDeviceConfig as DeviceInfo
from tests.harness.ssh import SSHHarness as BareMetalHarness

__all__ = ["BareMetalHarness", "DeviceInfo"]
