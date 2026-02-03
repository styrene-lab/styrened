"""Unified test harness for styrened across SSH and Kubernetes backends."""

from .base import (
    CommandResult,
    ExecutionBackend,
    NodeInfo,
    TestHarness,
)
from .logging import (
    LogCapture,
    configure_harness_logging,
    get_logger,
)

__all__ = [
    # Base types
    "CommandResult",
    "ExecutionBackend",
    "NodeInfo",
    "TestHarness",
    # Logging
    "configure_harness_logging",
    "get_logger",
    "LogCapture",
]
