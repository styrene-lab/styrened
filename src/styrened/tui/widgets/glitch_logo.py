"""Glitch-convergence animated logo widget for the Styrene splash screen.

Renders the styrene molecule (benzene ring + vinyl group) as braille Unicode
art, then plays a character-by-character noise-to-clean convergence animation
over ~1.5 s.  Each character position has a randomised unlock frame weighted
toward centre-outward reveal; before unlock it shows a CRT-noise glyph, after
unlock it shows the final logo character.
"""

from __future__ import annotations

import random
from typing import ClassVar

from rich.text import Text
from textual.app import RenderResult
from textual.reactive import reactive
from textual.message import Message
from textual.widget import Widget

# ---------------------------------------------------------------------------
# Imperial CRT palette
# ---------------------------------------------------------------------------
_TEAL   = "#5af0ce"   # primary phosphor teal
_DIM    = "#1e6e5a"   # dimmed teal — glitch noise / secondary elements
_ACCENT = "#a0fbe8"   # bright highlight — wordmark

# ---------------------------------------------------------------------------
# Styrene molecule logo art (braille Unicode + block-letter wordmark)
#
# Molecule mark: generated from the styrene monomer PNG (benzene ring +
# vinyl group, CH=CH₂) via alpha-channel rasterisation → braille encoding
# at 72 chars × 10 rows.  Followed by 2 blank lines and the 5-row
# block-letter wordmark.
#
# The blank braille cell (U+2800 ⠀) is treated as background — it is never
# glitched and renders as transparent space.
# ---------------------------------------------------------------------------

_BRAILLE_BLANK = "\u2800"  # ⠀ — background cell

LOGO_LINES: list[str] = [
    # ── molecule mark (10 rows) ───────────────────────────────────────────
    '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⡤⠴⠖⠲⠤⢤⣀⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⣤⠤⠶⠒⠦⢤⣄⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠀⢀⣀⣠⠤⠶⠒⠛⠉⠁⠀⠀⠀⠀⠙⠒⠶⠤⣭⣉⡛⠒⠦⢤⣄⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣠⡤⠴⠖⠚⠉⠉⠀⠀⠀⠀⠉⠓⠲⠦⢬⣍⣙⠒⠲⠤⣤⣀⣀⠀⠀⠀⠀⠀⠀',
    '⠀⢠⠤⠖⠚⠋⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠉⠓⠲⠦⢬⣍⣙⠒⠲⢤⡤⠶⠒⠋⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠉⠛⠒⠶⠤⣍⣉⡓⠲⠦⠄⠀',
    '⠀⢸⠀⠀⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠁⠀⢸⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠙⠀⠀⠀',
    '⠀⢸⠀⠀⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⢸⠀⠀⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢸⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⢸⠀⠀⣿⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⡀⠀⢸⡇⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠘⠲⠦⢤⣄⣀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣀⡤⠴⠖⢚⣋⣩⡤⠴⠚⠃⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠀⠈⠉⠙⠒⠶⠤⣄⣀⡀⠀⠀⠀⠀⣠⠤⠴⠒⣛⣉⣭⠤⠖⠒⠋⠉⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠙⠓⠲⠦⠴⠒⠚⠉⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    # ── spacer (2 blank lines) ────────────────────────────────────────────
    '                                                                        ',
    '                                                                        ',
    # ── wordmark (9 rows) ─────────────────────────────────────────────────
    '            ...#@@@=                                                                      ',
    '...      . ...@@@@@=....   . . .    ...   .. ......   . .. ....   ..  .   ..  .......  ...',
    '@@@@@@@@@@@..=@@@@@@@..@@@@@@.#@@@@@..@@@@@@@@@..@@@@@@@@@@@+..@@@@@@@@@@@@+..=@@@@@@@@@@@',
    '@@@@@#   ...  @@@@@= . @@@@@@.#@@@@@. @@@@@@@@@. @@@@@,.@@@@@ .@@@@@# =@@@@@  @@@@@#.@@@@@',
    '#@@@@@@@@@@#  @@@@@= . @@@@@@.#@@@@@. @@@@@@...  @@@@@@@@@@@@ .@@@@@# =@@@@@  @@@@@@@@@@@@',
    ',,,,,,#@@@@#  @@@@@= ..@@@@@@.#@@@@@. @@@@@@.    @@@@@-,,,,,,. @@@@@# =@@@@@  @@@@@@,,,,,,',
    '#@@@@@@@@@@....@@@@@@,..@@@@@@@@@@@@..@@@@@@.   .X@@@@@@@@@@@..@@@@@#.=@@@@@..=@@@@@@@@@@@',
    '...      ...... ..   ...++++++@@@@@@...   ...   ...         ...   ... ..   . ....         ',
    '                       ,@@@@@@@@@@+.                                                      ',
]

_MARK_ROWS  = 10   # number of molecule mark rows
_LINE_WIDTH = max(len(ln) for ln in LOGO_LINES)
LOGO_LINES  = [ln.ljust(_LINE_WIDTH) for ln in LOGO_LINES]

# ---------------------------------------------------------------------------
# Noise palette — CRT phosphor aesthetic
# ---------------------------------------------------------------------------
_NOISE_CHARS: str = "▓▒░█▄▀▌▐▊▋▍▎▏◆■□▪◇┼╬╪╫┤├┬┴╱╲│─"

# ---------------------------------------------------------------------------
# Animation parameters
# ---------------------------------------------------------------------------
FRAME_INTERVAL_S: float = 0.045   # ~22 fps
TOTAL_FRAMES: int       = 36      # ~1.6 s to full resolution
HOLD_FRAMES: int        = 8       # frames to hold clean logo before dismiss


def _assign_unlock_frames(lines: list[str], total: int) -> list[list[int]]:
    """Assign a random unlock frame to each character position.

    Outer characters resolve first; centre characters resolve last — matching
    how a CRT phosphor would converge from the edges inward to reveal the logo.

    Blank cells (braille ⠀ or ASCII space) are always unlocked (frame 0).
    """
    height = len(lines)
    width  = _LINE_WIDTH
    cx, cy = width / 2, height / 2

    frame_map: list[list[int]] = []
    for y, line in enumerate(lines):
        row_frames: list[int] = []
        for x, ch in enumerate(line):
            if ch in (" ", _BRAILLE_BLANK):
                row_frames.append(0)
            else:
                # Normalised distance from centre: ~0 at edge, ~1 at centre
                dist = (
                    (x - cx) ** 2 / cx ** 2
                    + (y - cy) ** 2 / cy ** 2
                ) ** 0.5
                # Edge chars unlock early, centre chars unlock late
                max_frame = int(total * 0.25 + dist * total * 0.55)
                max_frame = min(max_frame, total - 4)
                row_frames.append(random.randint(0, max(1, max_frame)))
        frame_map.append(row_frames)
    return frame_map


class GlitchLogoWidget(Widget):
    """Animated Styrene logo with glitch-convergence reveal.

    Drives itself via a Textual timer — call :meth:`start` to begin the
    animation.  When the animation completes, the widget emits a
    :class:`GlitchLogoWidget.AnimationComplete` message.
    """

    DEFAULT_CSS = """
    GlitchLogoWidget {
        width: auto;
        height: auto;
        content-align: center middle;
    }
    """

    _frame: reactive[int] = reactive(0, layout=False)

    class AnimationComplete(Message):
        """Posted when the logo has finished resolving and the hold has ended."""

    _rng_seed: ClassVar[int] = 42

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        GlitchLogoWidget._rng_seed = random.randint(0, 2**31)
        random.seed(GlitchLogoWidget._rng_seed)
        self._unlock_map = _assign_unlock_frames(LOGO_LINES, TOTAL_FRAMES)
        self._timer      = None
        self._noise_seed = random.randint(0, 2**31)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin the glitch animation."""
        self._frame = 0
        self._timer = self.set_interval(FRAME_INTERVAL_S, self._tick)

    def skip_to_clean(self) -> None:
        """Jump immediately to the fully resolved clean logo."""
        if self._timer:
            self._timer.stop()
            self._timer = None
        self._frame = TOTAL_FRAMES + HOLD_FRAMES + 1
        self.refresh()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        self._frame += 1
        self.refresh()
        if self._frame >= TOTAL_FRAMES + HOLD_FRAMES:
            if self._timer:
                self._timer.stop()
                self._timer = None
            self.post_message(self.AnimationComplete())

    def render(self) -> RenderResult:
        frame = self._frame
        rng   = random.Random(self._noise_seed + frame * 997)

        text = Text(no_wrap=True, overflow="fold")

        for y, (line, row_frames) in enumerate(
            zip(LOGO_LINES, self._unlock_map)
        ):
            for x, (ch, unlock) in enumerate(zip(line, row_frames)):
                if ch in (" ", _BRAILLE_BLANK):
                    text.append(ch)
                elif frame >= unlock:
                    colour = self._char_colour(y, x, ch)
                    text.append(ch, style=colour)
                else:
                    # Glitching — CRT noise character
                    noise = rng.choice(_NOISE_CHARS)
                    progress = frame / max(1, unlock)
                    noise_colour = _DIM if progress > 0.7 else "#2a3a32"
                    text.append(noise, style=noise_colour)
            text.append("\n")

        return text

    def _char_colour(self, y: int, x: int, ch: str) -> str:  # noqa: ARG002
        """Map a resolved character to its display colour."""
        # Wordmark rows (after mark rows + 2 blank lines)
        if y >= _MARK_ROWS + 2:
            return f"bold {_ACCENT}"
        # Molecule mark — uniform phosphor teal
        return _TEAL
