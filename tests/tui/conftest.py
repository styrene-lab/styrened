"""Pytest configuration and fixtures for styrene-tui tests."""

import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from styrened.protocols.base import LXMFMessage, Protocol

# Environment variable to detect subprocess execution
_IN_SUBPROCESS = os.environ.get("_RNS_TEST_SUBPROCESS") == "1"


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "rns_singleton: marks tests requiring isolated RNS/LXMF initialization (runs in subprocess)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Reorder tests so RNS singleton tests run last (they use subprocesses)."""
    # Separate singleton tests from regular tests
    singleton_tests = []
    regular_tests = []

    for item in items:
        if "rns_singleton" in item.keywords:
            singleton_tests.append(item)
        else:
            regular_tests.append(item)

    # Put regular tests first, singleton tests last
    items[:] = regular_tests + singleton_tests


def pytest_runtest_call(item: pytest.Item) -> None:
    """Run RNS singleton tests in isolated subprocess."""
    if "rns_singleton" not in item.keywords:
        return  # Let pytest run normally

    if _IN_SUBPROCESS:
        return  # Already in subprocess, run the test normally

    # Run this test in a fresh subprocess
    node_id = item.nodeid
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            node_id,
            "-v",
            "--tb=short",
            "-x",  # Stop on first failure for clarity
        ],
        capture_output=True,
        text=True,
        cwd=str(item.config.rootdir),
        env={**os.environ, "_RNS_TEST_SUBPROCESS": "1"},
    )

    if result.returncode != 0:
        # Test failed in subprocess
        output = result.stdout + "\n" + result.stderr
        pytest.fail(f"Subprocess test failed:\n{output}")

    # Test passed - skip the actual execution in parent
    pytest.skip("PASSED in subprocess")


# =============================================================================
# Shared Fixtures
# =============================================================================


@pytest.fixture
def app():
    """Create a fresh StyreneApp instance for testing."""
    from styrened.tui.app import StyreneApp

    return StyreneApp()


@pytest.fixture
def mock_identity():
    """Create mock RNS identity for tests that don't need real RNS."""
    identity = Mock()
    identity.hexhash = "mock_identity_hash"
    return identity


@pytest.fixture
def mock_router():
    """Create mock LXMF router."""
    router = Mock()
    router.handle_outbound = Mock()
    return router


# =============================================================================
# Shared Mock Protocol Class
# =============================================================================


class MockProtocol(Protocol):
    """Mock protocol implementation for testing.

    Use this instead of defining TestProtocol in individual test files
    to avoid pytest collection warnings about classes named Test*.
    """

    def __init__(self, protocol_id: str = "test"):
        self._protocol_id = protocol_id
        self.handled_messages: list[LXMFMessage] = []

    @property
    def protocol_id(self) -> str:
        return self._protocol_id

    def can_handle(self, message: LXMFMessage) -> bool:
        return message.fields.get("protocol") == self._protocol_id

    async def handle_message(self, message: LXMFMessage) -> None:
        self.handled_messages.append(message)

    async def send_message(self, destination: str, content: str) -> None:
        pass


@pytest.fixture
def mock_protocol():
    """Create a mock protocol instance."""
    return MockProtocol()
