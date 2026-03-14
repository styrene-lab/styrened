#!/usr/bin/env python3
"""Quick preview of the Styrene splash screen animation.

Run from the repo root:
    .venv/bin/python scripts/preview_splash.py
"""

from textual.app import App, ComposeResult
from textual import on
from styrened.tui.widgets.glitch_logo import GlitchLogoWidget


class PreviewApp(App):
    CSS = """
    Screen {
        align: center middle;
        background: #0a0f0d;
    }
    #logo { width: auto; height: auto; }
    """

    BINDINGS = [("q", "quit", "Quit"), ("r", "restart", "Restart")]

    def compose(self) -> ComposeResult:
        yield GlitchLogoWidget(id="logo")

    def on_mount(self) -> None:
        self.query_one(GlitchLogoWidget).start()

    @on(GlitchLogoWidget.AnimationComplete)
    def _done(self) -> None:
        self.bell()  # audible cue that animation finished

    def action_restart(self) -> None:
        w = self.query_one(GlitchLogoWidget)
        import random, styrened.tui.widgets.glitch_logo as gl
        gl._assign_unlock_frames  # force re-import of the function
        import importlib
        importlib.reload(gl)
        # Simpler: just recreate unlock map with new seed
        import random as rnd
        w._unlock_map = gl._assign_unlock_frames(gl.LOGO_LINES, gl.TOTAL_FRAMES)
        w._noise_seed = rnd.randint(0, 2**31)
        w._frame = 0
        w.start()


if __name__ == "__main__":
    PreviewApp().run()
