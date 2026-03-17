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

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Label, Static

from styrened.tui.widgets.glitch_logo import GlitchLogoWidget

# ---------------------------------------------------------------------------
# Imperial CRT palette (mirrors glitch_logo constants)
# ---------------------------------------------------------------------------
_TEAL   = "#5af0ce"
_DIM    = "#1e6e5a"
_ACCENT = "#a0fbe8"
_ERR    = "#ff6b6b"

# ---------------------------------------------------------------------------
# Startup checklist widget
# ---------------------------------------------------------------------------
_CHECKLIST_ITEMS = [
    "reticulum transport",
    "mesh discovery",
    "lxmf routing",
    "hub connection",
]

_HIDDEN  = "hidden"
_PENDING = "pending"
_ACTIVE  = "active"
_DONE    = "done"
_FAILED  = "failed"

# Scan sequence cycled while an item is ACTIVE — CRT noise feel
_SCAN_FRAMES = ["░  ", "▒  ", "▓  ", "▒  ", "░  ", "▸  ", "▸  ", "▸  "]
# Flash sequence played on DONE transition before settling on ✓
_DONE_FLASH  = ["▓  ", "▒  ", "✓  "]

_SCAN_INTERVAL = 0.10   # seconds per scan frame (~10 fps)


class StartupChecklist(Widget):
    """Animated startup progress list shown below the logo.

    Each item cycles through a CRT-scan sequence while ACTIVE, then plays a
    brief flash when it transitions to DONE.  Drives its own timer.
    """

    DEFAULT_CSS = """
    StartupChecklist {
        width: auto;
        height: auto;
        content-align: center middle;
    }
    """

    _states: reactive[tuple[str, ...]] = reactive(
        tuple(_HIDDEN for _ in _CHECKLIST_ITEMS)
    )
    _scan_frame: reactive[int] = reactive(0, layout=False)
    # per-item flash counter: -1 = not flashing, 0..N = flash frame index
    _flash: reactive[tuple[int, ...]] = reactive(
        tuple(-1 for _ in _CHECKLIST_ITEMS)
    )

    def on_mount(self) -> None:
        self.set_interval(_SCAN_INTERVAL, self._tick)

    def _tick(self) -> None:
        self._scan_frame = (self._scan_frame + 1) % len(_SCAN_FRAMES)
        # Advance any in-progress done flashes
        flash = list(self._flash)
        changed = False
        for i, f in enumerate(flash):
            if 0 <= f < len(_DONE_FLASH) - 1:
                flash[i] = f + 1
                changed = True
        if changed:
            self._flash = tuple(flash)
        self.refresh()

    def render(self) -> Text:
        text = Text(no_wrap=True)
        for i, (label, state) in enumerate(zip(_CHECKLIST_ITEMS, self._states, strict=False)):
            if state == _HIDDEN:
                continue
            flash_f = self._flash[i]
            if state == _PENDING:
                ind, ind_colour = "  ·  ", _DIM
            elif state == _ACTIVE:
                ind = "  " + _SCAN_FRAMES[self._scan_frame]
                ind_colour = _TEAL
            elif state == _DONE:
                if 0 <= flash_f < len(_DONE_FLASH):
                    ind = "  " + _DONE_FLASH[flash_f]
                    ind_colour = _ACCENT
                else:
                    ind, ind_colour = "  ✓  ", _ACCENT
            elif state == _FAILED:
                ind, ind_colour = "  ✗  ", _ERR
            else:
                ind, ind_colour = "  ·  ", _DIM

            text.append(ind, style=ind_colour)
            label_colour = _TEAL if state in (_ACTIVE, _DONE) else _DIM
            text.append(label, style=label_colour)
            text.append("\n")
        return text

    def set_item(self, index: int, state: str) -> None:
        """Transition one item to a new state."""
        states = list(self._states)
        states[index] = state
        self._states = tuple(states)
        # Trigger done flash
        if state == _DONE:
            flash = list(self._flash)
            flash[index] = 0
            self._flash = tuple(flash)

    def finish_all(self) -> None:
        for i in range(len(_CHECKLIST_ITEMS)):
            self.set_item(i, _DONE)

    def fail_active(self) -> None:
        self._states = tuple(
            _FAILED if s == _ACTIVE else s for s in self._states
        )


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

    StartupChecklist {
        width: auto;
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
            yield StartupChecklist(id="checklist")
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
        """Mirror of app._check_daemon() with checklist + status updates."""
        status    = self.query_one("#status", Label)
        checklist = self.query_one(StartupChecklist)

        # Reveal all items as pending, then drive them active one by one
        for i in range(len(_CHECKLIST_ITEMS)):
            checklist.set_item(i, _PENDING)

        checklist.set_item(0, _ACTIVE)   # reticulum transport
        status.update(_STATUS_INIT)

        # Fast path — already running? (generous timeout, only called once)
        if await self._ping_daemon(timeout=3.0):
            self._daemon_ok = True
            checklist.set_item(0, _DONE)
            checklist.set_item(1, _ACTIVE)
            status.update(_STATUS_LOADING)

            # Wait for device cache to prime so the dashboard has nodes on
            # first paint.  Polls the app-level cache for up to 5s.
            await self._wait_for_mesh_discovery(checklist, status)
            self._finish_daemon()
            return

        # Try auto-start
        checklist.set_item(0, _DONE)
        checklist.set_item(1, _ACTIVE)   # mesh discovery
        status.update(_STATUS_STARTING)
        await self._auto_start_daemon()

        checklist.set_item(1, _DONE)
        checklist.set_item(2, _ACTIVE)   # lxmf routing
        status.update(_STATUS_CONNECTING)

        for i in range(16):
            await asyncio.sleep(0.5)
            # Short timeout — we're polling rapidly, no need to wait long
            if await self._ping_daemon(timeout=0.8):
                self._daemon_ok = True
                checklist.set_item(2, _DONE)
                checklist.set_item(3, _ACTIVE)
                status.update(_STATUS_LOADING)
                await self._wait_for_mesh_discovery(checklist, status)
                self._finish_daemon()
                return
            # Advance checklist as polling drags on
            if i == 5:
                checklist.set_item(2, _DONE)
                checklist.set_item(3, _ACTIVE)   # hub connection
                status.update("still connecting…")
            if i == 12:
                status.update("taking longer than usual…")

        # Timed out
        self._daemon_ok = False
        checklist.fail_active()
        status.update(_STATUS_FAILED)
        await asyncio.sleep(0.8)
        self._finish_daemon()

    async def _wait_for_mesh_discovery(
        self,
        checklist: StartupChecklist,
        status: Label,
    ) -> None:
        """Hold splash until the device cache has at least one node (or 5s timeout).

        This ensures the dashboard has nodes on first paint rather than showing
        an empty "No mesh nodes discovered" table.  The app-level DeviceCache
        primes at 0.25s after the dashboard mounts — we just need to wait for
        that to land and propagate back via IPC.  The 5s cap prevents the
        splash from hanging if the mesh is truly empty.
        """
        # Initialise services and prime the device cache so the dashboard
        # has nodes on first paint.  We do NOT push screens here — the
        # splash callback handles navigation after dismiss.
        try:
            app = self.app
            init = getattr(app, "_initialize_services", None)
            if init:
                await init()
                setattr(app, "_services_initialized", True)
            # Wire bridge into cache and trigger immediate prime
            bridge = getattr(getattr(app, "_lifecycle", None), "_ipc_bridge", None)
            if bridge is None:
                bridge = getattr(app, "bridge", None)
            cache = getattr(app, "device_cache", None)
            if cache:
                if bridge:
                    cache.update_bridge(bridge)
                # Prime the cache directly — don't wait for timers
                try:
                    await cache._do_refresh()
                except Exception:
                    pass
        except Exception:
            pass

        checklist.set_item(1, _ACTIVE)  # mesh discovery
        status.update("discovering mesh nodes…")

        for tick in range(20):  # 20 × 0.25s = 5s max
            await asyncio.sleep(0.25)
            try:
                cache = getattr(self.app, "device_cache", None)
                if cache and cache.get():
                    break
                # Re-prime if first attempt returned empty
                if cache and tick in (4, 8, 12):
                    try:
                        await cache._do_refresh()
                    except Exception:
                        pass
            except Exception:
                pass
            # Update checklist progression while waiting
            if tick == 4:  # 1s
                checklist.set_item(1, _DONE)
                checklist.set_item(2, _ACTIVE)
                status.update("establishing routes…")
            if tick == 12:  # 3s
                checklist.set_item(2, _DONE)
                checklist.set_item(3, _ACTIVE)
                status.update("connecting to hub…")

        # Mark remaining items done regardless
        checklist.finish_all()
        status.update(_STATUS_DONE)
        await asyncio.sleep(0.3)

    def _finish_daemon(self) -> None:
        self._daemon_done = True
        self._maybe_dismiss()

    # ------------------------------------------------------------------
    # Shared dismiss logic
    # ------------------------------------------------------------------

    def _maybe_dismiss(self) -> None:
        """Dismiss only when both animation and daemon poll are done."""
        if self._anim_done and self._daemon_done:
            if getattr(self, "_dismissed", False):
                return
            self._dismissed = True
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

    async def _ping_daemon(self, timeout: float = 2.0) -> bool:
        """Ping the daemon socket.  ``timeout`` caps the entire attempt."""
        try:
            from styrened.ipc import ControlClient, get_default_socket_path

            socket_path = get_default_socket_path()
            if not socket_path.exists():
                return False
            # Use a short connect + ping timeout so polling loops stay snappy.
            connect_t = min(timeout * 0.6, 1.0)
            ping_t    = min(timeout * 0.4, 0.8)
            client = ControlClient(socket_path=socket_path, timeout=connect_t)
            try:
                await client.connect()
                return await client.ping(timeout=ping_t)
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
