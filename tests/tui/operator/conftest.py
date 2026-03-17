"""Fixtures for operator interface testing.

Session-scoped daemon harnesses + per-test TUI pilot.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine, Generator
from typing import Any

import pytest

from tests.harness.daemon import DaemonHarness

logger = logging.getLogger(__name__)


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "operator_path: marks tests as operator interface path tests (TUI pilot + live daemon)",
    )


@pytest.fixture(scope="session")
def alpha_daemon() -> Generator[DaemonHarness, None, None]:
    """Start alpha test peer daemon for the entire test session.

    Yields a DaemonHarness with:
        - identity_hash: e426a96311c5ea0e7644317040455b39
        - TCP server on a dynamic localhost port
        - Auto-reply enabled with 1s cooldown
        - RPC enabled with exec
    """
    harness = DaemonHarness.from_fixture("alpha")
    harness.start(timeout=15.0)
    yield harness
    harness.stop()


@pytest.fixture(scope="session")
def alpha_port(alpha_daemon: DaemonHarness) -> int:
    """Get alpha daemon's TCP server port."""
    return alpha_daemon.port


@pytest.fixture(scope="session")
def alpha_identity_hash(alpha_daemon: DaemonHarness) -> str:
    """Get alpha daemon's identity hash."""
    return alpha_daemon.identity_hash


async def await_condition(
    predicate: Callable[[], bool | Coroutine[Any, Any, bool]],
    *,
    timeout: float = 10.0,
    interval: float = 0.5,
    description: str = "condition",
) -> None:
    """Poll until predicate returns True or timeout expires.

    Args:
        predicate: Callable returning bool (sync or async).
        timeout: Maximum seconds to wait.
        interval: Seconds between polls.
        description: Human-readable description for timeout error.

    Raises:
        TimeoutError: If predicate never returns True within timeout.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        await asyncio.sleep(interval)
    msg = f"Timed out after {timeout}s waiting for: {description}"
    raise TimeoutError(msg)
