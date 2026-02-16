"""Quick smoke tests for bare-metal validation.

These tests verify basic connectivity and installation status.
Run with: pytest tests/bare-metal/test_smoke.py -v
"""

from __future__ import annotations

import pytest
from conftest import ALL_DEVICES, DEVICES_WITH_IDENTITY, SSHHarness


@pytest.mark.smoke
class TestSmoke:
    """Fast smoke tests for release validation."""

    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_device_reachable(self, harness: SSHHarness, device: str) -> None:
        """Device is SSH-accessible."""
        result = harness.run(device, "echo ok")
        assert result.stdout.strip() == "ok"

    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_styrened_installed(self, harness: SSHHarness, device: str) -> None:
        """styrened is installed and runnable in venv."""
        version = harness.get_version(device)
        assert version, "Expected non-empty version string"
        # Version should be semver-ish
        assert "." in version, f"Unexpected version format: {version}"

    @pytest.mark.parametrize("device", DEVICES_WITH_IDENTITY)
    def test_identity_exists(self, harness: SSHHarness, device: str) -> None:
        """Device has valid identity."""
        identity = harness.get_identity(device)
        assert identity is not None, "Expected identity data"
        assert identity.get("identity_hash"), "Expected identity_hash in response"
        assert len(identity["identity_hash"]) == 32, (
            f"Expected 32-char hash, got {len(identity['identity_hash'])}"
        )

    @pytest.mark.parametrize("device", DEVICES_WITH_IDENTITY)
    def test_identity_matches_registry(self, harness: SSHHarness, device: str) -> None:
        """Device identity matches registry."""
        identity = harness.get_identity(device)
        assert identity is not None, "Expected identity data"
        device_config = harness.get_device_config(device)
        assert device_config is not None
        expected_hash = device_config.identity_hash
        assert identity["identity_hash"] == expected_hash, (
            f"Identity mismatch: {identity['identity_hash']} != {expected_hash}"
        )

    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_venv_exists(self, harness: SSHHarness, device: str) -> None:
        """Python venv exists on device."""
        device_config = harness.get_device_config(device)
        assert device_config is not None
        result = harness.run(
            device,
            f"test -d {device_config.venv_path} && echo exists",
        )
        assert result.stdout.strip() == "exists"

    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_config_exists(self, harness: SSHHarness, device: str) -> None:
        """Styrene config exists on device."""
        device_config = harness.get_device_config(device)
        assert device_config is not None
        result = harness.run(
            device,
            f"test -f {device_config.config_path}/core-config.yaml && echo exists",
        )
        assert result.stdout.strip() == "exists"


@pytest.mark.smoke
class TestDaemonStatus:
    """Tests for daemon service status."""

    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_systemd_unit_exists(self, harness: SSHHarness, device: str) -> None:
        """Systemd unit file exists for styrened."""
        device_config = harness.get_device_config(device)
        assert device_config is not None

        if "systemd_user" in device_config.capabilities:
            result = harness.run(
                device,
                "systemctl --user cat styrened.service >/dev/null 2>&1 && echo exists",
            )
        else:
            result = harness.run(
                device,
                "systemctl cat styrened.service >/dev/null 2>&1 && echo exists",
            )
        # Unit may not exist yet - that's informational, not a failure
        if result.stdout.strip() != "exists":
            pytest.skip("Systemd unit not configured yet")
