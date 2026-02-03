"""Installation test scenarios.

These tests handle deployment/provisioning of styrened on bare-metal devices.
They are separate from connectivity/mesh tests which assume working installation.

Test tiers:
- smoke: Quick validation of existing installation
- installation: Full install/uninstall cycles
- provisioning: Complete setup including systemd service

Run with:
    pytest tests/scenarios/test_installation.py --backend=ssh -v
    pytest tests/scenarios/test_installation.py --backend=ssh -m installation -v
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.harness.primitives import (
    InstallMethod,
    PrimitiveResult,
    check_connectivity,
    check_installation_prerequisites,
    check_version,
    install_via_pip_git,
    install_via_pip_wheel,
    setup_systemd_service,
    uninstall_styrened,
)

if TYPE_CHECKING:
    from tests.harness.base import NodeInfo
    from tests.harness.ssh import SSHHarness


@pytest.mark.smoke
class TestInstallationSmoke:
    """Quick validation of existing installation."""

    def test_node_reachable(
        self,
        harness: SSHHarness,
        single_node: NodeInfo,
    ) -> None:
        """Verify node is SSH-accessible."""
        result = check_connectivity(harness, single_node)
        assert result.success, f"{single_node.name}: {result.error}"

    def test_styrened_installed(
        self,
        harness: SSHHarness,
        single_node: NodeInfo,
    ) -> None:
        """Verify styrened is installed."""
        result = check_version(harness, single_node)
        assert result.success, f"{single_node.name}: {result.error}"
        print(f"  Version: {result.data.get('version')}")

    def test_pip_prerequisites(
        self,
        harness: SSHHarness,
        single_node: NodeInfo,
    ) -> None:
        """Verify pip installation prerequisites are met."""
        result = check_installation_prerequisites(harness, single_node, InstallMethod.PIP_GIT)
        assert result.success, f"{single_node.name}: {result.error}"


@pytest.mark.installation
class TestPipGitInstallation:
    """Test pip git-based installation path."""

    def test_install_from_main(
        self,
        harness: SSHHarness,
        single_node: NodeInfo,
    ) -> None:
        """Install styrened from main branch."""
        # Check prerequisites
        prereq = check_installation_prerequisites(harness, single_node, InstallMethod.PIP_GIT)
        if not prereq.success:
            pytest.skip(f"Prerequisites not met: {prereq.error}")

        # Get venv path from device config
        device_config = harness.get_device_config(single_node.name)
        venv_path = device_config.venv_path if device_config else None

        # Install
        result = install_via_pip_git(
            harness,
            single_node,
            repo_url="https://github.com/styrene-lab/styrened.git",
            ref="main",
            venv_path=venv_path,
        )
        assert result.success, f"{single_node.name}: {result.error}"
        print(f"  Installed version: {result.data.get('version')}")

    def test_install_from_tag(
        self,
        harness: SSHHarness,
        single_node: NodeInfo,
        request: pytest.FixtureRequest,
    ) -> None:
        """Install styrened from a specific tag."""
        tag = request.config.getoption("--install-tag", default=None)
        if not tag:
            pytest.skip("No --install-tag specified")

        prereq = check_installation_prerequisites(harness, single_node, InstallMethod.PIP_GIT)
        if not prereq.success:
            pytest.skip(f"Prerequisites not met: {prereq.error}")

        device_config = harness.get_device_config(single_node.name)
        venv_path = device_config.venv_path if device_config else None

        result = install_via_pip_git(
            harness,
            single_node,
            ref=tag,
            venv_path=venv_path,
        )
        assert result.success, f"{single_node.name}: {result.error}"
        print(f"  Installed version: {result.data.get('version')}")

    def test_upgrade_installation(
        self,
        harness: SSHHarness,
        single_node: NodeInfo,
    ) -> None:
        """Upgrade existing installation to latest."""
        # Get current version
        before = check_version(harness, single_node)
        print(f"  Before: {before.data.get('version', 'not installed')}")

        device_config = harness.get_device_config(single_node.name)
        venv_path = device_config.venv_path if device_config else None

        # Upgrade
        result = install_via_pip_git(
            harness,
            single_node,
            ref="main",
            venv_path=venv_path,
        )
        assert result.success, f"Upgrade failed: {result.error}"

        # Check new version
        after = check_version(harness, single_node)
        print(f"  After: {after.data.get('version')}")


@pytest.mark.installation
class TestWheelInstallation:
    """Test wheel-based installation path."""

    def test_install_from_wheel(
        self,
        harness: SSHHarness,
        single_node: NodeInfo,
        request: pytest.FixtureRequest,
    ) -> None:
        """Install styrened from a wheel file."""
        wheel_path = request.config.getoption("--wheel-path", default=None)
        if not wheel_path:
            # Try to find wheel in dist/
            dist_dir = Path(__file__).parent.parent.parent / "dist"
            wheels = list(dist_dir.glob("styrened-*.whl"))
            if not wheels:
                pytest.skip("No wheel found. Build with: python -m build --wheel")
            wheel_path = wheels[0]
        else:
            wheel_path = Path(wheel_path)

        if not wheel_path.exists():
            pytest.skip(f"Wheel not found: {wheel_path}")

        result = install_via_pip_wheel(harness, single_node, wheel_path)
        assert result.success, f"{single_node.name}: {result.error}"
        print(f"  Installed: {result.data.get('version')}")


@pytest.mark.provisioning
class TestFullProvisioning:
    """Complete provisioning including systemd service setup."""

    def test_full_provisioning_workflow(
        self,
        harness: SSHHarness,
        single_node: NodeInfo,
    ) -> None:
        """Complete install + systemd setup workflow."""
        results: list[PrimitiveResult] = []

        # 1. Check prerequisites
        prereq = check_installation_prerequisites(harness, single_node, InstallMethod.PIP_GIT)
        results.append(prereq)
        if not prereq.success:
            pytest.skip(f"Prerequisites not met: {prereq.error}")

        # 2. Install styrened
        device_config = harness.get_device_config(single_node.name)
        venv_path = device_config.venv_path if device_config else None

        install_result = install_via_pip_git(
            harness,
            single_node,
            ref="main",
            venv_path=venv_path,
        )
        results.append(install_result)
        assert install_result.success, f"Install failed: {install_result.error}"

        # 3. Setup systemd service
        service_result = setup_systemd_service(
            harness,
            single_node,
            user_service=True,
            enable=True,
            start=True,
        )
        results.append(service_result)
        assert service_result.success, f"Service setup failed: {service_result.error}"

        # 4. Verify daemon is running
        is_running = harness.is_daemon_running(single_node)
        assert is_running, "Daemon not running after provisioning"

        # Print summary
        print("\n  Provisioning summary:")
        for r in results:
            status = "OK" if r.success else "FAIL"
            print(f"    [{status}] {r.name}: {r.message or r.error}")

    def test_provision_all_nodes(
        self,
        harness: SSHHarness,
        all_nodes: list[NodeInfo],
    ) -> None:
        """Provision all available nodes."""
        failed_nodes = []

        for node in all_nodes:
            print(f"\n  Provisioning {node.name}...")

            # Check prerequisites
            prereq = check_installation_prerequisites(harness, node, InstallMethod.PIP_GIT)
            if not prereq.success:
                print(f"    SKIP: {prereq.error}")
                continue

            # Install
            device_config = harness.get_device_config(node.name)
            venv_path = device_config.venv_path if device_config else None

            install_result = install_via_pip_git(harness, node, ref="main", venv_path=venv_path)
            if not install_result.success:
                print(f"    FAIL: {install_result.error}")
                failed_nodes.append(node.name)
                continue

            # Setup service
            service_result = setup_systemd_service(
                harness, node, user_service=True, enable=True, start=True
            )
            if not service_result.success:
                print(f"    FAIL: {service_result.error}")
                failed_nodes.append(node.name)
                continue

            print(f"    OK: {install_result.data.get('version')}")

        assert not failed_nodes, f"Failed to provision: {failed_nodes}"


@pytest.mark.installation
class TestUninstallation:
    """Test uninstallation paths."""

    def test_uninstall_pip(
        self,
        harness: SSHHarness,
        single_node: NodeInfo,
    ) -> None:
        """Uninstall pip-installed styrened."""
        device_config = harness.get_device_config(single_node.name)
        venv_path = device_config.venv_path if device_config else None

        result = uninstall_styrened(
            harness,
            single_node,
            method=InstallMethod.PIP_GIT,
            venv_path=venv_path,
            stop_service=True,
        )
        assert result.success, f"{single_node.name}: {result.error}"
