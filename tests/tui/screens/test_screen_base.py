"""Tests for StyreneScreen base class lifecycle contract."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from textual.app import ComposeResult
from textual.widgets import Label

from styrened.tui.screens.base import (
    BridgeUnavailableError,
    StyreneLoadingIndicator,
    StyreneScreen,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _SimpleScreen(StyreneScreen[None]):
    """Minimal concrete screen for testing."""

    def __init__(self, load_side_effect=None):
        super().__init__()
        self.load_calls: list[int] = []
        self._load_side_effect = load_side_effect
        self.cleanup_calls = 0
        self.error_calls: list[tuple[Exception, int]] = []

    def compose(self) -> ComposeResult:
        yield Label("content")

    async def _load_data(self) -> None:
        attempt = len(self.load_calls) + 1
        self.load_calls.append(attempt)
        if self._load_side_effect is not None:
            result = self._load_side_effect(attempt)
            if asyncio.iscoroutine(result):
                await result

    def _cleanup(self) -> None:
        self.cleanup_calls += 1

    async def _on_error(self, error: Exception, attempt: int) -> None:
        self.error_calls.append((error, attempt))


class _FailingScreen(StyreneScreen[None]):
    """Screen whose _load_data always raises."""

    def __init__(self, error: Exception | None = None):
        super().__init__()
        self.load_calls = 0
        self.error_calls: list[tuple[Exception, int]] = []
        self._error = error or ValueError("load failed")
        self.cleanup_calls = 0

    def compose(self) -> ComposeResult:
        yield Label("content")

    async def _load_data(self) -> None:
        self.load_calls += 1
        raise self._error

    async def _on_error(self, error: Exception, attempt: int) -> None:
        self.error_calls.append((error, attempt))

    def _cleanup(self) -> None:
        self.cleanup_calls += 1


class _CustomMessageScreen(StyreneScreen[None]):
    def compose(self) -> ComposeResult:
        yield Label("x")

    async def _load_data(self) -> None:
        pass

    def _loading_message(self) -> str:
        return "Fetching mesh data…"


# ---------------------------------------------------------------------------
# Shared mock setup
# ---------------------------------------------------------------------------


def _make_mock_app(bridge=None):
    """Return a MagicMock that satisfies the StyreneApp/TUIServices contract."""
    mock_services = MagicMock()
    mock_services.bridge = bridge
    mock_app = MagicMock()
    mock_app.services = mock_services
    return mock_app


# ---------------------------------------------------------------------------
# Unit tests — no Textual pilot needed
# ---------------------------------------------------------------------------


class TestBridgeProperty:
    def test_bridge_property_raises_when_none(self):
        """BridgeUnavailableError is raised when services.bridge is None."""
        screen = _SimpleScreen()
        mock_app = _make_mock_app(bridge=None)

        with patch.object(
            type(screen), "app", new_callable=lambda: property(lambda self: mock_app)
        ):
            with pytest.raises(BridgeUnavailableError):
                _ = screen.bridge

    def test_bridge_property_returns_bridge_when_set(self):
        """bridge property forwards the real bridge when connected."""
        screen = _SimpleScreen()
        fake_bridge = MagicMock()
        mock_app = _make_mock_app(bridge=fake_bridge)

        with patch.object(
            type(screen), "app", new_callable=lambda: property(lambda self: mock_app)
        ):
            result = screen.bridge
            assert result is fake_bridge


# ---------------------------------------------------------------------------
# Integration tests — use Textual pilot
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_reticulum(tmp_path):
    """Prevent real Reticulum / daemon init during TUI tests."""
    fake_config = tmp_path / "config"
    fake_config.mkdir()
    (fake_config / "config").write_text("")

    import styrened.services.node_store as _ns_mod

    old_singleton = _ns_mod._node_store
    _ns_mod._node_store = None

    with (
        patch("styrened.tui.services.reticulum.find_reticulum_config", return_value=fake_config),
        patch("styrened.tui.services.app_lifecycle.StyreneLifecycle"),
        patch("styrened.tui.app.StyreneApp._check_daemon", return_value=True),
        patch("styrened.services.node_store.get_node_store", return_value=MagicMock()),
    ):
        yield

    _ns_mod._node_store = old_singleton


def _make_app():
    """Create a StyreneApp with a mock lifecycle suitable for testing screens."""
    from styrened.tui.app import StyreneApp
    from styrened.tui.services.app_lifecycle import LifecycleMode

    lifecycle = MagicMock()
    lifecycle.initialize_async = AsyncMock(return_value=True)
    lifecycle.active_mode = LifecycleMode.IPC
    lifecycle.shutdown_async = AsyncMock()
    lifecycle.ipc_bridge = None

    app = StyreneApp()
    app._lifecycle = lifecycle
    return app


@pytest.mark.asyncio
async def test_screen_calls_load_data_on_mount():
    """_load_data() is triggered when the screen mounts."""

    load_called = asyncio.Event()

    class _TrackingScreen(_SimpleScreen):
        async def _load_data(self) -> None:
            await super()._load_data()
            load_called.set()

    screen = _TrackingScreen()
    app = _make_app()

    async with app.run_test(size=(80, 24)) as pilot:
        await app.push_screen(screen)
        await asyncio.wait_for(load_called.wait(), timeout=5.0)

    assert len(screen.load_calls) >= 1


@pytest.mark.asyncio
async def test_loading_indicator_shown_before_first_load():
    """StyreneLoadingIndicator is mounted before _load_data completes."""

    load_started = asyncio.Event()
    load_proceed = asyncio.Event()

    class _SlowScreen(StyreneScreen[None]):
        def compose(self) -> ComposeResult:
            yield Label("x")

        async def _load_data(self) -> None:
            load_started.set()
            await load_proceed.wait()

    screen = _SlowScreen()
    app = _make_app()

    async with app.run_test(size=(80, 24)) as pilot:
        await app.push_screen(screen)
        await asyncio.wait_for(load_started.wait(), timeout=5.0)
        # Indicator should be visible while loading
        indicators = screen.query(StyreneLoadingIndicator)
        assert len(indicators) == 1
        load_proceed.set()
        await pilot.pause(0.2)


@pytest.mark.asyncio
async def test_loading_indicator_hidden_after_success():
    """StyreneLoadingIndicator is removed after _load_data() succeeds."""

    done = asyncio.Event()

    class _QuickScreen(_SimpleScreen):
        async def _load_data(self) -> None:
            await super()._load_data()
            done.set()

    screen = _QuickScreen()
    app = _make_app()

    async with app.run_test(size=(80, 24)) as pilot:
        await app.push_screen(screen)
        await asyncio.wait_for(done.wait(), timeout=5.0)
        await pilot.pause(0.1)
        indicators = screen.query(StyreneLoadingIndicator)
        assert len(indicators) == 0


@pytest.mark.asyncio
async def test_load_data_error_retries():
    """_load_data is called up to 3 times on repeated failure."""

    exhausted = asyncio.Event()

    class _FailThenDoneScreen(_FailingScreen):
        async def _on_error(self, error: Exception, attempt: int) -> None:
            await super()._on_error(error, attempt)
            exhausted.set()

    screen = _FailThenDoneScreen()
    app = _make_app()

    with patch("styrened.tui.screens.base.asyncio.sleep", new=AsyncMock()):
        async with app.run_test(size=(80, 24)) as pilot:
            await app.push_screen(screen)
            await asyncio.wait_for(exhausted.wait(), timeout=5.0)

    assert screen.load_calls == 3


@pytest.mark.asyncio
async def test_error_hook_called_after_exhaustion():
    """_on_error() is called after all retry attempts fail."""

    exhausted = asyncio.Event()
    err = RuntimeError("bridge down")

    class _FailThenDoneScreen(_FailingScreen):
        async def _on_error(self, error: Exception, attempt: int) -> None:
            await super()._on_error(error, attempt)
            exhausted.set()

    screen = _FailThenDoneScreen(error=err)
    app = _make_app()

    with patch("styrened.tui.screens.base.asyncio.sleep", new=AsyncMock()):
        async with app.run_test(size=(80, 24)) as pilot:
            await app.push_screen(screen)
            await asyncio.wait_for(exhausted.wait(), timeout=5.0)

    assert len(screen.error_calls) == 1
    exc, attempt = screen.error_calls[0]
    assert isinstance(exc, RuntimeError)
    assert attempt == 3


@pytest.mark.asyncio
async def test_screen_cleanup_on_suspend():
    """_cleanup() is called when the screen is suspended."""

    done = asyncio.Event()

    class _TrackingScreen(_SimpleScreen):
        async def _load_data(self) -> None:
            await super()._load_data()
            done.set()

    screen = _TrackingScreen()
    app = _make_app()

    async with app.run_test(size=(80, 24)) as pilot:
        await app.push_screen(screen)
        await asyncio.wait_for(done.wait(), timeout=5.0)
        # Call directly — on_screen_suspend only cancels worker + calls _cleanup(),
        # no coroutine is created so no unawaited-coroutine risk here.
        screen.on_screen_suspend()
        await pilot.pause(0.1)

    assert screen.cleanup_calls >= 1


@pytest.mark.asyncio
async def test_screen_cleanup_on_unmount():
    """_cleanup() is called when the screen unmounts."""

    done = asyncio.Event()

    class _TrackingScreen(_SimpleScreen):
        async def _load_data(self) -> None:
            await super()._load_data()
            done.set()

    screen = _TrackingScreen()
    app = _make_app()

    async with app.run_test(size=(80, 24)) as pilot:
        await app.push_screen(screen)
        await asyncio.wait_for(done.wait(), timeout=5.0)

    # on_unmount fires as context manager exits
    assert screen.cleanup_calls >= 1


@pytest.mark.asyncio
async def test_screen_refreshes_on_resume():
    """_load_data() runs again when screen_resume fires."""

    first_done = asyncio.Event()
    second_done = asyncio.Event()
    call_count = 0

    class _TrackingScreen(_SimpleScreen):
        async def _load_data(self) -> None:
            nonlocal call_count
            await super()._load_data()
            call_count += 1
            if call_count == 1:
                first_done.set()
            elif call_count == 2:
                second_done.set()

    screen = _TrackingScreen()
    app = _make_app()

    async with app.run_test(size=(80, 24)) as pilot:
        await app.push_screen(screen)
        await asyncio.wait_for(first_done.wait(), timeout=5.0)
        # Post the event through Textual's dispatcher to avoid un-awaited coroutines.
        from textual.events import ScreenResume
        screen.post_message(ScreenResume())
        await asyncio.wait_for(second_done.wait(), timeout=5.0)

    assert call_count >= 2


@pytest.mark.asyncio
async def test_loading_message_used_in_indicator():
    """_loading_message() return value is used in the StyreneLoadingIndicator."""

    load_started = asyncio.Event()
    load_proceed = asyncio.Event()

    class _MsgScreen(StyreneScreen[None]):
        def compose(self) -> ComposeResult:
            yield Label("x")

        def _loading_message(self) -> str:
            return "Fetching mesh data…"

        async def _load_data(self) -> None:
            load_started.set()
            await load_proceed.wait()

    screen = _MsgScreen()
    app = _make_app()

    async with app.run_test(size=(80, 24)) as pilot:
        await app.push_screen(screen)
        await asyncio.wait_for(load_started.wait(), timeout=5.0)
        indicators = screen.query(StyreneLoadingIndicator)
        assert len(indicators) == 1
        assert indicators.first(StyreneLoadingIndicator).message == "Fetching mesh data…"
        load_proceed.set()
        await pilot.pause(0.2)
