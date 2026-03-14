"""Styrene TUI intro splash screen.

Shown immediately on mount while the daemon IPC connection is being
established.  Runs the glitch-convergence logo animation concurrently with
the daemon-check polling so the user sees a polished boot sequence rather
than a blank hang.

Flow:
    1. SplashScreen pushed as the very first screen.
    2. ``_daemon_task`` worker runs the same logic as ``_check_daemon()``.
    3. As daemon polling progresses the status label is updated.
    4. When daemon responds (or times out) SplashScreen dismisses itself
       with a bool result — True = daemon ok, False = setup needed.
    5. If the animation hasn't finished yet we let it complete (or the user
       can press any key to skip straight to the result).
"""

from __future__ import annotations

import asyncio
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, Static

from styrened.tui.widgets.glitch_logo import GlitchLogoWidget

# Status messages shown while polling
_STATUS_INIT       = "initialising…"
_STATUS_STARTING   = "starting daemon…"
_STATUS_CONNECTING = "connecting…"
_STATUS_LOADING    = "loading mesh state…"
_STATUS_DONE       = "ready"
_STATUS_FAILED     = "daemon unavailable — launching setup"


class SplashScreen(Screen[bool]):
    """Full-screen intro animation with concurrent daemon polling.

    Dismisses with ``True`` when the daemon is reachable, ``False`` when
    the poll times out (caller should show DaemonSetupScreen).
    """

    DEFAULT_CSS = """
    SplashScreen {
        align: center middle;
        background: $background;
    }

    #splash-container {
        align: center middle;
        width: auto;
        height: auto;
    }

    #logo {
        width: auto;
        height: auto;
        margin-bottom: 2;
    }

    #tagline {
        width: auto;
        text-align: center;
        color: $primary-darken-2;
        margin-bottom: 1;
    }

    #status {
        width: auto;
        text-align: center;
        color: $primary;
    }

    #hint {
        width: auto;
        text-align: center;
        color: $primary-darken-3;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "skip", "Skip animation"),
        ("space",  "skip", "Skip animation"),
        ("enter",  "skip", "Skip animation"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._daemon_ok:      bool | None = None
        self._anim_done:      bool        = False
        self._daemon_done:    bool        = False

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Static(id="splash-container"):
            yield GlitchLogoWidget(id="logo")
            yield Label("mesh communications · reticulum network", id="tagline")
            yield Label(_STATUS_INIT, id="status")
            yield Label("press any key to skip", id="hint")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        logo = self.query_one(GlitchLogoWidget)
        logo.start()
        self._poll_daemon()

    # ------------------------------------------------------------------
    # Animation complete
    # ------------------------------------------------------------------

    @on(GlitchLogoWidget.AnimationComplete)
    def _on_anim_done(self) -> None:
        self._anim_done = True
        self._maybe_dismiss()

    # ------------------------------------------------------------------
    # Daemon polling worker
    # ------------------------------------------------------------------

    @work(exclusive=True)
    async def _poll_daemon(self) -> None:
        """Mirror of app._check_daemon() with status label updates."""
        status = self.query_one("#status", Label)

        # Fast path — already running?
        if await self._ping_daemon():
            self._daemon_ok = True
            status.update(_STATUS_LOADING)
            self._finish_daemon()
            return

        # Try auto-start
        status.update(_STATUS_STARTING)
        await self._auto_start_daemon()

        status.update(_STATUS_CONNECTING)
        for i in range(16):
            await asyncio.sleep(0.5)
            if await self._ping_daemon():
                self._daemon_ok = True
                status.update(_STATUS_LOADING)
                # Small extra delay so the label reads naturally
                await asyncio.sleep(0.4)
                status.update(_STATUS_DONE)
                self._finish_daemon()
                return
            # Intermediate feedback
            if i == 6:
                status.update("still connecting…")
            if i == 12:
                status.update("taking longer than usual…")

        # Timed out
        self._daemon_ok = False
        status.update(_STATUS_FAILED)
        await asyncio.sleep(0.8)
        self._finish_daemon()

    def _finish_daemon(self) -> None:
        self._daemon_done = True
        self._maybe_dismiss()

    # ------------------------------------------------------------------
    # Shared dismiss logic
    # ------------------------------------------------------------------

    def _maybe_dismiss(self) -> None:
        """Dismiss only when both animation and daemon poll are done."""
        if self._anim_done and self._daemon_done:
            self.dismiss(bool(self._daemon_ok))

    # ------------------------------------------------------------------
    # Skip action
    # ------------------------------------------------------------------

    def action_skip(self) -> None:
        """Skip the animation — if daemon result is known, dismiss immediately."""
        logo = self.query_one(GlitchLogoWidget)
        logo.skip_to_clean()
        self._anim_done = True
        self._maybe_dismiss()

    # ------------------------------------------------------------------
    # IPC helpers (duplicated from app so the screen is self-contained)
    # ------------------------------------------------------------------

    async def _ping_daemon(self) -> bool:
        try:
            from styrened.ipc import ControlClient, get_default_socket_path

            socket_path = get_default_socket_path()
            if not socket_path.exists():
                return False
            client = ControlClient(socket_path=socket_path, timeout=3.0)
            try:
                await client.connect()
                return await client.ping(timeout=2.0)
            finally:
                await client.disconnect()
        except Exception:
            return False

    async def _auto_start_daemon(self) -> None:
        try:
            import subprocess
            import sys

            subprocess.Popen(
                [sys.executable, "-m", "styrened.daemon"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            await asyncio.sleep(1.5)
        except Exception:
            pass
