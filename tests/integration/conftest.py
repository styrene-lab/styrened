"""Pytest configuration and fixtures for local integration tests.

These fixtures provide isolated RNS/LXMF environments for testing
client/server interactions without Kubernetes.
"""
from __future__ import annotations


import asyncio
import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def rns_available() -> bool:
    """Check if RNS is available for import.

    Returns:
        True if RNS can be imported, False otherwise.
    """
    try:
        import RNS  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture(scope="function")
def temp_rns_dir() -> Generator[Path, None, None]:
    """Create temporary directory for RNS configuration.

    Provides isolated RNS config directory per test to prevent
    state leakage between tests.

    Yields:
        Path to temporary RNS config directory.
    """
    temp_dir = tempfile.mkdtemp(prefix="styrene_test_rns_")
    temp_path = Path(temp_dir)

    # Set RNS config path environment variable
    old_rns_path = os.environ.get("RNS_CONFIG_DIR")
    os.environ["RNS_CONFIG_DIR"] = str(temp_path)

    yield temp_path

    # Cleanup
    if old_rns_path:
        os.environ["RNS_CONFIG_DIR"] = old_rns_path
    else:
        os.environ.pop("RNS_CONFIG_DIR", None)

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture(scope="function")
def local_rns_config(temp_rns_dir: Path) -> Path:
    """Create minimal RNS configuration for local testing.

    Sets up RNS with AutoInterface only (no network interfaces),
    suitable for local multi-process testing.

    Args:
        temp_rns_dir: Temporary directory for RNS config.

    Returns:
        Path to RNS config file.
    """
    config_path = temp_rns_dir / "config"

    # Minimal config for local testing - AutoInterface only
    config_content = """
[reticulum]
  enable_transport = False
  share_instance = True
  shared_instance_port = 0
  instance_control_port = 0

  panic_on_interface_error = False

[logging]
  loglevel = 4

[interfaces]
  [[AutoInterface]]
    type = AutoInterface
    enabled = True
    discovery_scope = link
    discovery_port = 0
    data_port = 0
"""
    config_path.write_text(config_content)

    return config_path


@pytest.fixture
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "requires_rns: marks tests that require RNS to be installed",
    )
    config.addinivalue_line(
        "markers",
        "slow_integration: marks tests that take longer than 30s",
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests that require RNS if it's not available."""
    try:
        import RNS  # noqa: F401

        rns_available = True
    except ImportError:
        rns_available = False

    if not rns_available:
        skip_rns = pytest.mark.skip(reason="RNS not installed")
        for item in items:
            if "requires_rns" in item.keywords:
                item.add_marker(skip_rns)
