"""Deployment and upgrade tests for bare-metal devices.

These tests deploy wheels and verify installation.
Run with: pytest tests/bare-metal/test_deployment.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ALL_DEVICES, DEVICES_WITH_IDENTITY

from tests.harness.ssh import SSHHarness


def get_wheel_path() -> Path | None:
    """Find the most recent wheel in dist/."""
    dist = Path(__file__).parents[2] / "dist"
    if not dist.exists():
        return None
    wheels = list(dist.glob("styrened-*.whl"))
    if not wheels:
        return None
    return max(wheels, key=lambda p: p.stat().st_mtime)


@pytest.fixture(scope="module")
def wheel_path() -> Path:
    """Path to wheel built from current source."""
    path = get_wheel_path()
    if path is None:
        pytest.skip("No wheel found - run 'python -m build --wheel' first")
    return path


@pytest.mark.deployment
class TestDeployment:
    """Test deployment to bare-metal devices."""

    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_deploy_wheel(
        self,
        harness: SSHHarness,
        wheel_path: Path,
        device: str,
    ) -> None:
        """Deploy wheel and verify installation."""
        result = harness.deploy_wheel(device, wheel_path)
        assert result.success, f"Failed to deploy wheel to {device}: {result.stderr}"

        # Verify version matches
        version = harness.get_version(device)
        # Extract expected version from wheel name: styrened-0.3.6-py3-none-any.whl
        expected = wheel_path.stem.split("-")[1]
        assert version == expected, f"Expected {expected}, got {version}"

    @pytest.mark.parametrize("device", DEVICES_WITH_IDENTITY)
    def test_identity_preserved_after_deploy(
        self,
        harness: SSHHarness,
        wheel_path: Path,
        device: str,
    ) -> None:
        """Verify identity is preserved after upgrade."""
        expected_hash = harness.registry[device].identity_hash

        harness.deploy_wheel(device, wheel_path)

        identity = harness.get_identity(device)
        assert identity is not None, "Identity missing after deploy"
        assert identity["identity_hash"] == expected_hash

    @pytest.mark.parametrize("device", ALL_DEVICES)
    def test_config_preserved_after_deploy(
        self,
        harness: SSHHarness,
        wheel_path: Path,
        device: str,
    ) -> None:
        """Verify config files are not overwritten by deployment."""
        info = harness.registry[device]

        hash_before = harness.run(
            device,
            f"sha256sum {info.config_path}/core-config.yaml | cut -d' ' -f1",
        ).stdout.strip()

        harness.deploy_wheel(device, wheel_path)

        hash_after = harness.run(
            device,
            f"sha256sum {info.config_path}/core-config.yaml | cut -d' ' -f1",
        ).stdout.strip()

        assert hash_before == hash_after, "Config was modified by deployment"
