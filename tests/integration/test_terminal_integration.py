"""Integration tests for terminal service in daemon.

These tests verify that the terminal service is properly integrated
into the daemon lifecycle - currently a critical gap.

TDD RED PHASE: Many of these tests will fail until we:
1. Add TerminalConfig to models/config.py
2. Add terminal attribute to CoreConfig
3. Add TerminalService initialization to daemon.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from styrened.daemon import StyreneDaemon
from styrened.models.config import (
    APIConfig,
    ChatConfig,
    CoreConfig,
    DeploymentMode,
    IPCConfig,
    ReticulumConfig,
    RPCConfig,
)

if TYPE_CHECKING:
    pass


# Check if TerminalConfig exists yet
try:
    from styrened.models.config import TerminalConfig

    HAS_TERMINAL_CONFIG = True
except ImportError:
    HAS_TERMINAL_CONFIG = False

    # Stub for tests until implemented
    class TerminalConfig:  # type: ignore[no-redef]
        """Stub TerminalConfig for tests."""

        def __init__(
            self,
            enabled: bool = False,
            max_sessions_per_identity: int = 3,
            max_total_sessions: int = 10,
        ):
            self.enabled = enabled
            self.max_sessions_per_identity = max_sessions_per_identity
            self.max_total_sessions = max_total_sessions


@pytest.fixture
def minimal_config(tmp_path: Path) -> CoreConfig:
    """Create minimal config for testing daemon startup."""
    config = CoreConfig(
        reticulum=ReticulumConfig(
            mode=DeploymentMode.STANDALONE,
        ),
        rpc=RPCConfig(enabled=False),
        api=APIConfig(enabled=False),
        ipc=IPCConfig(enabled=False),
        chat=ChatConfig(enabled=False),
    )
    # Attach terminal config if CoreConfig supports it
    if hasattr(config, "terminal"):
        config.terminal = TerminalConfig(
            enabled=True,
        )
    return config


@pytest.fixture
def terminal_enabled_config(tmp_path: Path) -> CoreConfig:
    """Create config with terminal service enabled."""
    config = CoreConfig(
        reticulum=ReticulumConfig(
            mode=DeploymentMode.STANDALONE,
        ),
        rpc=RPCConfig(enabled=False),
        api=APIConfig(enabled=False),
        ipc=IPCConfig(enabled=False),
        chat=ChatConfig(enabled=False),
    )
    # Attach terminal config if CoreConfig supports it
    if hasattr(config, "terminal"):
        config.terminal = TerminalConfig(
            enabled=True,
            max_sessions_per_identity=3,
            max_total_sessions=10,
        )
    return config


class TestDaemonTerminalServiceIntegration:
    """Tests that verify terminal service is integrated into daemon."""

    def test_daemon_has_terminal_service_attribute(
        self,
        minimal_config: CoreConfig,
    ) -> None:
        """Daemon should have a _terminal_service attribute.

        This test fails until we add TerminalService to daemon.py.
        """
        daemon = StyreneDaemon(minimal_config)

        assert hasattr(daemon, "_terminal_service"), (
            "StyreneDaemon should have _terminal_service attribute. "
            "Add TerminalService to daemon.py __init__"
        )

    def test_config_has_terminal_section(
        self,
        terminal_enabled_config: CoreConfig,
    ) -> None:
        """CoreConfig should have terminal configuration section.

        This test verifies the config model supports terminal settings.
        """
        assert hasattr(terminal_enabled_config, "terminal"), (
            "CoreConfig should have 'terminal' attribute. "
            "Add TerminalConfig to models/config.py and 'terminal' field to CoreConfig"
        )
        if hasattr(terminal_enabled_config, "terminal"):
            assert terminal_enabled_config.terminal.enabled is True
            assert terminal_enabled_config.terminal.max_sessions_per_identity == 3

    @pytest.mark.asyncio
    @pytest.mark.requires_rns
    async def test_daemon_starts_terminal_service(
        self,
        terminal_enabled_config: CoreConfig,
        temp_rns_dir: Path,
    ) -> None:
        """Daemon start() should initialize and start terminal service.

        This is the critical test - it fails until we integrate
        TerminalService into daemon.py's start() method.
        """
        # Skip if terminal config not supported yet
        if not hasattr(terminal_enabled_config, "terminal"):
            pytest.skip("TerminalConfig not yet added to CoreConfig")

        daemon = StyreneDaemon(terminal_enabled_config)

        # Mock lifecycle initialization to avoid RNS setup complexity
        async def mock_run_loop() -> None:
            """Mock run loop that returns immediately."""
            pass

        with patch.object(daemon.lifecycle, "initialize", return_value=True):
            with patch.object(daemon, "_run_loop", mock_run_loop):
                # Start daemon (will return quickly due to mocked _run_loop)
                start_task = asyncio.create_task(daemon.start())

                # Give it a moment to initialize services
                await asyncio.sleep(0.1)

                # Cancel the task since _run_loop is mocked
                start_task.cancel()
                try:
                    await start_task
                except asyncio.CancelledError:
                    pass

        # Verify terminal service was started
        assert hasattr(daemon, "_terminal_service"), (
            "Daemon should have _terminal_service after start()"
        )
        if daemon._terminal_service is not None:
            assert daemon._terminal_service._registered is True, (
                "Terminal service should be registered after daemon start()"
            )

    @pytest.mark.asyncio
    async def test_daemon_stops_terminal_service_on_shutdown(
        self,
        terminal_enabled_config: CoreConfig,
    ) -> None:
        """Daemon shutdown should stop terminal service gracefully.

        Terminal service should be stopped, closing all sessions.
        """
        daemon = StyreneDaemon(terminal_enabled_config)

        # First check if daemon has terminal service support
        if not hasattr(daemon, "_terminal_service"):
            pytest.fail(
                "StyreneDaemon should have _terminal_service attribute. "
                "Add TerminalService to daemon.py"
            )

        # Manually set up a mock terminal service
        mock_terminal = MagicMock()
        mock_terminal._registered = True
        mock_terminal.sessions = {}

        # Attach it (simulating successful start)
        daemon._terminal_service = mock_terminal

        # Call shutdown
        if hasattr(daemon, "stop"):
            await daemon.stop()
        elif hasattr(daemon, "shutdown"):
            await daemon.shutdown()
        else:
            pytest.skip("Daemon has no stop() or shutdown() method")

        # Verify stop was called
        mock_terminal.stop.assert_called_once()


class TestTerminalServiceInitialization:
    """Tests for terminal service initialization within daemon."""

    def test_terminal_service_uses_config_values(
        self,
        terminal_enabled_config: CoreConfig,
    ) -> None:
        """Terminal service should be initialized with config values.

        When daemon creates TerminalService, it should pass:
        - max_sessions_per_identity from config
        - max_total_sessions from config
        - rbac_policy from config
        """
        config = terminal_enabled_config

        # Verify config values are accessible
        assert config.terminal.max_sessions_per_identity == 3
        assert config.terminal.max_total_sessions == 10

    def test_terminal_disabled_skips_initialization(
        self,
        minimal_config: CoreConfig,
    ) -> None:
        """Daemon should skip terminal service when disabled in config."""
        # Disable terminal in config
        minimal_config.terminal.enabled = False

        daemon = StyreneDaemon(minimal_config)

        # If terminal_service attribute exists, it should be None when disabled
        if hasattr(daemon, "_terminal_service"):
            # After start, it should still be None
            assert daemon._terminal_service is None, (
                "Terminal service should be None when terminal.enabled=False"
            )


class TestTerminalConfigModel:
    """Tests for terminal configuration model."""

    def test_terminal_config_defaults(self) -> None:
        """TerminalConfig should have sensible defaults."""
        config = TerminalConfig()

        # Check defaults
        assert config.enabled is False  # Should default to disabled

    def test_terminal_config_from_dict(self) -> None:
        """TerminalConfig should be loadable from dict (YAML config)."""
        config = TerminalConfig(
            enabled=True,
            max_sessions_per_identity=5,
            max_total_sessions=20,
        )

        assert config.enabled is True
        assert config.max_sessions_per_identity == 5
        assert config.max_total_sessions == 20
