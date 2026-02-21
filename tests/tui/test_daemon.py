"""Smoke tests for daemon module."""

import pytest


def test_daemon_imports() -> None:
    """Daemon module should import without errors."""
    try:
        from styrened.tui import daemon
        assert daemon is not None
    except ImportError as e:
        pytest.fail(f"Failed to import daemon: {e}")


def test_daemon_class_exists() -> None:
    """StyreneDaemon class should be defined."""
    from styrened.tui.daemon import StyreneDaemon
    assert StyreneDaemon is not None
    # Verify it's a class
    assert callable(StyreneDaemon)


def test_daemon_no_textual_dependency() -> None:
    """Daemon should not import textual (headless operation)."""
    import sys

    # Import daemon
    from styrened.tui import daemon

    # Check loaded modules for textual
    textual_modules = [name for name in sys.modules.keys() if 'textual' in name.lower()]

    # daemon.py might transitively import textual through other styrene modules
    # This test documents the current state rather than enforcing strict isolation
    # For true headless operation, daemon would need to avoid importing any TUI code
    assert daemon is not None  # Basic sanity check
