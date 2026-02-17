"""Pytest configuration for bare-metal tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Ensure tests package is importable
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import from unified harness package
from tests.harness.ssh import SSHHarness

# Re-export for backward compatibility
BareMetalHarness = SSHHarness

# Import log capture fixture (autouse -- activates automatically)
from log_capture import capture_logs_on_failure  # noqa: F401

# ---------------------------------------------------------------------------
# Device name helpers (usable in @pytest.mark.parametrize at import time)
# ---------------------------------------------------------------------------

_DEVICES_FILE = Path(__file__).parent / "devices.yaml"


def _load_devices_yaml() -> dict:
    """Load and cache the devices.yaml registry."""
    with open(_DEVICES_FILE) as f:
        return yaml.safe_load(f)


def _load_device_names() -> list[str]:
    """Load all device names from the registry.

    Returns every device defined in devices.yaml regardless of configuration
    completeness. Suitable for smoke tests (SSH, venv, install).
    """
    data = _load_devices_yaml()
    return list(data.get("devices", {}).keys())


def _load_device_names_with_identity() -> list[str]:
    """Load device names that have identity_hash configured.

    Only devices with a non-empty identity_hash are returned.  Tests that
    require identity verification (identity checks, mesh discovery, RPC)
    should parametrize against this list.
    """
    data = _load_devices_yaml()
    return [
        name
        for name, info in data.get("devices", {}).items()
        if info.get("identity_hash")
    ]


# Module-level constants for use in @pytest.mark.parametrize decorators.
ALL_DEVICES = _load_device_names()
DEVICES_WITH_IDENTITY = _load_device_names_with_identity()


# ---------------------------------------------------------------------------
# Pytest hooks
# ---------------------------------------------------------------------------


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
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow/extended tests (overnight, load tests)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line("markers", "smoke: Quick validation tests")
    config.addinivalue_line("markers", "deployment: Wheel deployment tests")
    config.addinivalue_line("markers", "mesh: Mesh network integration tests")
    config.addinivalue_line("markers", "rpc: RPC communication tests")
    config.addinivalue_line("markers", "slow: Tests requiring --run-slow flag")
    config.addinivalue_line("markers", "slow_extended: Long-running tests (4-8+ hours)")
    config.addinivalue_line("markers", "dialogue: Dialogue conversation tests")


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Store test result on the item for the log capture fixture to access."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Filter tests based on markers and CLI options."""
    # Skip slow/slow_extended tests unless --run-slow is passed
    run_slow = config.getoption("--run-slow", default=False)
    if not run_slow:
        skip_slow = pytest.mark.skip(reason="Need --run-slow option to run")
        for item in items:
            if "slow" in item.keywords or "slow_extended" in item.keywords:
                item.add_marker(skip_slow)

    # Filter parametrized tests to a single device when --device is set
    device_filter = config.getoption("--device")
    if not device_filter:
        return

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []

    for item in items:
        # Check if this test has a "device" parameter (from parametrize)
        if hasattr(item, "callspec") and "device" in item.callspec.params:
            if item.callspec.params["device"] == device_filter:
                selected.append(item)
            else:
                deselected.append(item)
        else:
            # Non-parametrized tests always run
            selected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
