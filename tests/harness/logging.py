"""Logging configuration for test harness.

Provides consistent logging setup for installation, provisioning, and test operations.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Default format for test harness logs
DEFAULT_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%H:%M:%S"

# Verbose format includes more context
VERBOSE_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s (%(filename)s:%(lineno)d): %(message)s"


def configure_harness_logging(
    level: int | str = logging.INFO,
    format_string: str | None = None,
    log_file: Path | None = None,
    verbose: bool = False,
) -> logging.Logger:
    """Configure logging for the test harness.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        format_string: Custom format string (uses default if None)
        log_file: Optional file path to write logs
        verbose: Use verbose format with file/line info

    Returns:
        Root logger for the harness package
    """
    # Convert string level to int
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # Select format
    if format_string is None:
        format_string = VERBOSE_FORMAT if verbose else DEFAULT_FORMAT

    # Configure harness logger
    harness_logger = logging.getLogger("tests.harness")
    harness_logger.setLevel(level)

    # Remove existing handlers
    harness_logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(format_string, datefmt=DEFAULT_DATE_FORMAT)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    harness_logger.addHandler(console_handler)

    # File handler if requested
    if log_file:
        file_handler = logging.FileHandler(log_file, mode="a")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        harness_logger.addHandler(file_handler)

    # Don't propagate to root logger
    harness_logger.propagate = False

    return harness_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a test harness module.

    Args:
        name: Module name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class LogCapture:
    """Context manager to capture log output for inspection.

    Useful for verifying expected log messages in tests.

    Example:
        with LogCapture("tests.harness.primitives.installation") as capture:
            result = install_via_pip_git(harness, node)
        assert "SUCCEEDED" in capture.output
    """

    def __init__(self, logger_name: str, level: int = logging.DEBUG):
        self.logger_name = logger_name
        self.level = level
        self.handler: logging.Handler | None = None
        self.records: list[logging.LogRecord] = []

    def __enter__(self) -> LogCapture:
        self.handler = CaptureHandler(self.records)
        self.handler.setLevel(self.level)

        logger = logging.getLogger(self.logger_name)
        logger.addHandler(self.handler)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.handler:
            logger = logging.getLogger(self.logger_name)
            logger.removeHandler(self.handler)

    @property
    def output(self) -> str:
        """Get captured output as a single string."""
        return "\n".join(record.getMessage() for record in self.records)

    @property
    def messages(self) -> list[str]:
        """Get captured messages as a list."""
        return [record.getMessage() for record in self.records]

    def has_level(self, level: int) -> bool:
        """Check if any record has the given level."""
        return any(record.levelno == level for record in self.records)

    def has_error(self) -> bool:
        """Check if any error was logged."""
        return self.has_level(logging.ERROR)

    def has_warning(self) -> bool:
        """Check if any warning was logged."""
        return self.has_level(logging.WARNING)


class CaptureHandler(logging.Handler):
    """Handler that captures log records for inspection."""

    def __init__(self, records: list[logging.LogRecord]):
        super().__init__()
        self.records = records

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
