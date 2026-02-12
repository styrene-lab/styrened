"""Cross-architecture validation tests.

Validates that x86_64 and aarch64 devices interoperate correctly.
"""

from __future__ import annotations

import pytest
from tests.harness.ssh import SSHHarness


def _get_arch_groups(harness: SSHHarness) -> tuple[list[str], list[str]]:
    """Split devices into x86_64 and aarch64 groups."""
    x86 = []
    arm = []
    for name, config in harness.registry.items():
        if not config.identity_hash:
            continue
        if config.arch == "aarch64":
            arm.append(name)
        else:
            x86.append(name)
    return x86, arm


@pytest.mark.mesh
class TestCrossArchitecture:
    """Validate x86_64 <-> aarch64 interoperability."""

    def test_cross_arch_discovery(self, harness: SSHHarness) -> None:
        """x86_64 and aarch64 devices can discover each other."""
        x86_devices, arm_devices = _get_arch_groups(harness)
        if not x86_devices or not arm_devices:
            pytest.skip("Need both x86_64 and aarch64 devices with identity")

        x86_device = x86_devices[0]
        arm_device = arm_devices[0]

        # Ensure both running
        for d in [x86_device, arm_device]:
            if not harness.is_daemon_running(d):
                result = harness.start_daemon(d)
                if not result.success:
                    pytest.skip(f"Could not start daemon on {d}")
                harness.wait_for_daemon(d, timeout=30)

        # x86 discovers ARM
        arm_hash = harness.registry[arm_device].identity_hash
        discovered = harness.discover_devices(x86_device, wait_seconds=20)
        x86_sees_arm = any(
            d.get("identity_hash", d.get("destination", "")).startswith(arm_hash[:16])
            for d in discovered
        )

        # ARM discovers x86
        x86_hash = harness.registry[x86_device].identity_hash
        discovered = harness.discover_devices(arm_device, wait_seconds=20)
        arm_sees_x86 = any(
            d.get("identity_hash", d.get("destination", "")).startswith(x86_hash[:16])
            for d in discovered
        )

        assert x86_sees_arm, f"{x86_device} (x86) did not discover {arm_device} (arm)"
        assert arm_sees_x86, f"{arm_device} (arm) did not discover {x86_device} (x86)"

    def test_cross_arch_rpc(self, harness: SSHHarness) -> None:
        """RPC status queries work across architectures."""
        x86_devices, arm_devices = _get_arch_groups(harness)
        if not x86_devices or not arm_devices:
            pytest.skip("Need both x86_64 and aarch64 devices with identity")

        x86_device = x86_devices[0]
        arm_device = arm_devices[0]

        # Ensure both running
        for d in [x86_device, arm_device]:
            if not harness.is_daemon_running(d):
                result = harness.start_daemon(d)
                if not result.success:
                    pytest.skip(f"Could not start daemon on {d}")
                harness.wait_for_daemon(d, timeout=30)

        # x86 -> ARM RPC
        arm_hash = harness.registry[arm_device].identity_hash
        result = harness.query_status(x86_device, arm_hash, timeout=60)
        assert result.success, f"x86->ARM RPC failed: {result.stderr}"

        # ARM -> x86 RPC
        x86_hash = harness.registry[x86_device].identity_hash
        result = harness.query_status(arm_device, x86_hash, timeout=60)
        assert result.success, f"ARM->x86 RPC failed: {result.stderr}"

    def test_cross_arch_chat(self, harness: SSHHarness) -> None:
        """Chat messages work across architectures."""
        x86_devices, arm_devices = _get_arch_groups(harness)
        if not x86_devices or not arm_devices:
            pytest.skip("Need both x86_64 and aarch64 devices with identity")

        x86_device = x86_devices[0]
        arm_device = arm_devices[0]

        # Ensure both running
        for d in [x86_device, arm_device]:
            if not harness.is_daemon_running(d):
                result = harness.start_daemon(d)
                if not result.success:
                    pytest.skip(f"Could not start daemon on {d}")
                harness.wait_for_daemon(d, timeout=30)

        # x86 -> ARM message
        arm_hash = harness.registry[arm_device].identity_hash
        result = harness.send_message(x86_device, arm_hash, "Cross-arch test x86->arm")
        assert result.return_code == 0 or "queued" in result.stdout.lower(), (
            f"x86->ARM send failed: {result.stderr}"
        )

        # ARM -> x86 message
        x86_hash = harness.registry[x86_device].identity_hash
        result = harness.send_message(arm_device, x86_hash, "Cross-arch test arm->x86")
        assert result.return_code == 0 or "queued" in result.stdout.lower(), (
            f"ARM->x86 send failed: {result.stderr}"
        )

    def test_version_parity(self, harness: SSHHarness) -> None:
        """All devices run the same styrened version."""
        versions: dict[str, str | None] = {}
        for device in harness.registry:
            versions[device] = harness.get_version(device)

        non_none = {k: v for k, v in versions.items() if v is not None}
        if len(non_none) < 2:
            pytest.skip("Need at least 2 devices with styrened installed")

        unique_versions = set(non_none.values())
        assert len(unique_versions) == 1, (
            f"Version mismatch across fleet: {non_none}"
        )
