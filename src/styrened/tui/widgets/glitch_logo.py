"""Glitch-convergence animated logo widget for the Styrene splash screen.

Renders the styrene molecule (benzene ring + vinyl group) as braille Unicode
art, then plays a character-by-character noise-to-clean convergence animation
over ~1.5 s.  Each character position has a randomised unlock frame weighted
toward centre-outward reveal; before unlock it shows a CRT-noise glyph, after
unlock it shows the final logo character.
"""

from __future__ import annotations

import random
import shutil
from typing import ClassVar

from rich.text import Text
from textual.app import RenderResult
from textual.message import Message
from textual.reactive import reactive
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

_LARGE_LINES: list[str] = [
    # ── styrene logo mark (26 rows) ─────────────────────────────────────────────
    '                    :@@@*                                       .+@@@:.                   ',
    '              ...@@@@@@@@@@@...                             ..@@@@@@@@@@@..               ',
    '           ..=@@@@@@@:.-@@@@@@@..                        . @@@@@@@-.-@@@@@@@=.            ',
    '          @@@@@@@@....:@.. @@@@@@@@                   .@@@@@@@@..  #@...@@@@@@@@.         ',
    '    ..-@@@@@@@..      :@@@@:..:@@@@@@@:.          .:@@@@@@@-.      .@@@@...*@@@@@@@-.     ',
    '  .@@@@@@@@..        ...@@@@@@%...@@@@@@@@.    .@@@@@@@@..         ..@@@@@@#...@@@@@@@@.  ',
    '@@@@@@@:          ...@@..  @@@@@@@...#@@@@@@@@@@@@@@:.    ...@@@:..    .%@@@@@@...-@@@@@@@',
    '@@@@..          .-@%   ..@@  ..@@@@@@@.. @@@@@@@@..    ..+@@..  .%@@..    ..@@@@@@%...%.  ',
    '@@@@.=@..  ...@@.          .@@....@@@@.  @@@@+..   .. @@+...     . . @@=..    .@@@@@.     ',
    '@@@@ =@@@ +@@.                .:@%       @@@@   ..#@@.             @@ ..@@@..       .     ',
    '@@@@ =@@@ @                      @       @@@@  .@*...              @@@@..@..@.      @     ',
    '@@@@ =@@@ @                      @       @@@@   @                  @@@@  @  @.      @.@.  ',
    '@@@@ =@@@ @                      @       @@@@   @                  @@@@  @  @.      @.@.  ',
    '@@@@ =@@@ @                      @       @@@@   @                  @@@@  @  @.      @.@.  ',
    '@@@@ =@@@ @                      @       @@@@   @                  @@@@  @  @.       .@.  ',
    '@@@@ =@@@ @                      @       @@@@   @                  @@@@  @  @.       .@.  ',
    '@@@@ =@@@ .@%...              .%@%  .    @@@@   @                  @@@@..@  @.      .@@.  ',
    '@@@@ =#..  ...@@.          .@@...=@@@@@  @@@@   @                  @@@@  @  @.       @@.  ',
    '@@@@+..          .@%....=@#...@@@@@@@...%@@@@  .@@...              @@@@ .@.@@. ...   @@.  ',
    '@@@@@@@@.           .@@...+@@@@@@-...@@@@@@@@     .@@%.            @@@@:@@.  .+@@@  .-.   ',
    ' ..:@@@@@@@#..        .@@@@@@@...@@@@@@@@#.           .@@...     . @@@@....@@@@@@@        ',
    '      .@@@@@@@@..     :@@@*...@@@@@@@@..                 .@@%...-@@.  .=@@@@@@*           ',
    '        ..-@@@@@@@-. .:...+@@@@@@@=..                       ..@%.  .@@@@@@@..             ',
    '             .@@@@@@@@.@@@@@@@@                                 .@@@@@@#.                 ',
    '                .#@@@@@@@@@+..                                     ..                     ',
    '                   ..@@@...                                                               ',
    # ── spacer (3 blank lines) ───────────────────────────────────────────────
    '                                                                                          ',
    '                                                                                          ',
    '                                                                                          ',
    # ── wordmark (7 rows) ─────────────────────────────────────────────────────
    '              ..    .  .+@....     .. ...... .  ..   .    ....  .      ..                 ',
    '             ..@@@@@@  %@@@@..@=.  .@@.. @.@@@...@@@@@:   @@.@@@@#    #@@@@@.             ',
    '              @@.       @@    -@.  .@-   @@. . .@.. ..@   @@-.. .@  .@@.. .%@.            ',
    '              .@@@@@@   @@     @@..@@    @      @@@@@@@   @@    .@   @@@@@@@@.            ',
    '                  .+@   @@.    .@@@@.    @      @@.       @@    .@   @@:.                 ',
    '              ++++++     .++     @@     .+.     .++++++   ++.   .+.    ++++++.            ',
    '                               .*@..                                                      ',
]

_LARGE_MARK_ROWS: int = 26
_LARGE_WIDTH: int = max(len(ln) for ln in _LARGE_LINES)
_LARGE_LINES = [ln.ljust(_LARGE_WIDTH) for ln in _LARGE_LINES]

# ── medium variant (16-row mark + 5-row wordmark, 55 cols) ─────────────────
_MEDIUM_MARK_ROWS: int = 16
_MEDIUM_LINES: list[str] = [
    '          ..****.                     .****.           ',
    '       .,****.*****.               .***** ****,.       ',
    '    .*****.   **..****.         .****.   **..*****     ',
    '..****..     ..****..*****  .*****..  .  .*****..****.. ',
    '***.     ..*, **..****`.,*****`   ..*. ,* .  .**** .*` ',
    '**.**. .*.      ..*. .,  ***   .**.      ..*.   .*.    ',
    '**.** *             *    *** *..         ****.*.   *   ',
    '**.** *             *    *** *           **** *.   * . ',
    '**.** *             *    *** *           **** *.   . . ',
    '**.** *             *    *** *           **** *.     . ',
    '**.**..**.        **. `  *** *           **,* *.   .*. ',
    '***.      .*...* .****,..*** **.         **,*.*. .  *. ',
    ' *****..      .****..*****.     .*..     ***...***     ',
    '   ..*****    **..*****.           .*,.*`..****..      ',
    '      ..***** *****.                  . ****           ',
    '           .****.                                      ',
    '                                                       ',
    '                                                       ',
    '               |                                       ',
    '        <**** *+* *.  *  r** .***.  r***. .***.        ',
    '        ^---.  |   \\v/*  *   *****  *   * *****.       ',
    '        -.__>  |   .v.   *   ^._.   *   * ^._.         ',
    '                  .**                                  ',
]
_MEDIUM_WIDTH: int = max(len(ln) for ln in _MEDIUM_LINES)
_MEDIUM_LINES = [ln.ljust(_MEDIUM_WIDTH) for ln in _MEDIUM_LINES]

# Back-compat alias used by module-level _assign_unlock_frames call
LOGO_LINES = _LARGE_LINES
_MARK_ROWS = _LARGE_MARK_ROWS
_LINE_WIDTH = _LARGE_WIDTH

# ---------------------------------------------------------------------------
# Noise palette — CRT phosphor aesthetic
# ---------------------------------------------------------------------------
_NOISE_CHARS: str = "▓▒░█▄▀▌▐▊▋▍▎▏◆■□▪◇┼╬╪╫┤├┬┴╱╲│─"

# ---------------------------------------------------------------------------
# Animation parameters
# ---------------------------------------------------------------------------
FRAME_INTERVAL_S: float = 0.045   # ~22 fps
TOTAL_FRAMES: int       = 42      # ~1.9 s to full resolution
HOLD_FRAMES: int        = 8       # frames to hold clean logo before dismiss


def _assign_unlock_frames(
    lines: list[str], total: int
) -> list[list[tuple[int, int]]]:
    """Assign (appear_frame, unlock_frame) to every character position.

    Two-phase cascade + glitch animation:
      - appear_frame : row sweeps in top-to-bottom over the first 55 % of
                       total frames, with ±2-frame per-character jitter.
      - unlock_frame : how many frames after appearing the character spends
                       as CRT noise before resolving to its final glyph.
                       Centre columns glitch longest; edges resolve faster.

    Blank / space cells always get (0, 0) — rendered as spaces throughout.
    """
    height      = len(lines)
    cascade_end = int(total * 0.55)          # cascade finishes here
    max_glitch  = int(total * 0.40)          # max noise window after appear

    frame_map: list[list[tuple[int, int]]] = []
    for y, line in enumerate(lines):
        row: list[tuple[int, int]] = []
        base_appear = int((y / max(height - 1, 1)) * cascade_end)
        cx = len(line) / 2.0
        for x, ch in enumerate(line):
            if ch in (" ", _BRAILLE_BLANK):
                row.append((0, 0))
            else:
                appear = base_appear + random.randint(0, 2)
                # Centre columns linger in glitch longer — more dramatic
                dist_from_cx = abs(x - cx) / max(cx, 1.0)
                hi = max(4, int(max_glitch * (0.35 + 0.65 * (1.0 - dist_from_cx))))
                lo = max(3, int(hi * 0.25))
                unlock = min(appear + random.randint(lo, hi), total - 2)
                row.append((appear, unlock))
        frame_map.append(row)
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
        # Variant auto-selected: large requires ≥160 cols (reliable proxy for
        # 4K / wide-format terminals); medium is the default everywhere else.
        w = self._detect_cols()
        if w >= 220:
            self._lines: list[str] = _LARGE_LINES
            self._mark_rows: int   = _LARGE_MARK_ROWS
            self._line_width: int  = _LARGE_WIDTH
        else:
            self._lines: list[str] = _MEDIUM_LINES
            self._mark_rows: int   = _MEDIUM_MARK_ROWS
            self._line_width: int  = _MEDIUM_WIDTH
        self._unlock_map = _assign_unlock_frames(self._lines, TOTAL_FRAMES)
        self._timer      = None
        self._noise_seed = random.randint(0, 2**31)



    @staticmethod
    def _detect_cols() -> int:
        """Return terminal width in columns via OS query (pre-Textual layout)."""
        try:
            return shutil.get_terminal_size(fallback=(80, 24)).columns
        except Exception:
            return 80

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
            zip(self._lines, self._unlock_map, strict=False)
        ):
            for x, (ch, (appear, unlock)) in enumerate(
                zip(line, row_frames, strict=False)
            ):
                if ch in (" ", _BRAILLE_BLANK):
                    text.append(ch)
                elif frame < appear:
                    # Not yet reached by the cascade — invisible
                    text.append(" ")
                elif frame >= unlock:
                    # Fully resolved — clean glyph
                    colour = self._char_colour(y, x, ch)
                    text.append(ch, style=colour)
                else:
                    # Glitching — CRT noise
                    noise    = rng.choice(_NOISE_CHARS)
                    progress = (frame - appear) / max(1, unlock - appear)
                    if frame == appear:
                        # Bright arrival flash
                        noise_colour = _ACCENT
                    elif progress > 0.65:
                        # Dimming as it converges
                        noise_colour = _DIM
                    else:
                        noise_colour = _TEAL
                    text.append(noise, style=noise_colour)
            text.append("\n")

        return text

    def _char_colour(self, y: int, x: int, ch: str) -> str:  # noqa: ARG002
        """Map a resolved character to its display colour."""
        # Wordmark rows (after logo mark rows + 2 blank spacer lines)
        if y >= self._mark_rows + 2:
            return f"bold {_ACCENT}"
        # Logo mark — flat phosphor teal (art is dense; gradient adds noise)
        return _TEAL
