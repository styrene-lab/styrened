"""Pytest configuration for bare-metal tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure tests package is importable
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import from unified harness package
from tests.harness.ssh import SSHHarness

# Re-export for backward compatibility
BareMetalHarness = SSHHarness


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add bare-metal test options."""
    parser.addoption(
        "--device",
        action="store",
        default=None,
        help="Run tests only on specific device (e.g., styrene-node, t100ta)",
    )
    parser.addoption(
        "--skip-deploy",
        action="store_true",
        default=False,
        help="Skip deployment tests (use existing installation)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "smoke: Quick validation tests")
    config.addinivalue_line("markers", "deployment: Wheel deployment tests")
    config.addinivalue_line("markers", "mesh: Mesh network integration tests")
    config.addinivalue_line("markers", "rpc: RPC communication tests")


@pytest.fixture(scope="session")
def harness() -> SSHHarness:
    """Session-scoped SSH harness for bare-metal testing."""
    return SSHHarness()


@pytest.fixture(scope="session")
def all_devices(harness: SSHHarness) -> list[str]:
    """List of all registered device names."""
    return [node.name for node in harness.get_nodes()]


@pytest.fixture
def device_filter(request: pytest.FixtureRequest) -> str | None:
    """Get device filter from command line."""
    return request.config.getoption("--device")
