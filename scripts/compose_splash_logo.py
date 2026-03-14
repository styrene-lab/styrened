#!/usr/bin/env python3
"""
Compose the final splash logo: auto-converted mark + hand-tuned wordmark.

Run this once to produce the LOGO_LINES constant for glitch_logo.py.

    python scripts/compose_splash_logo.py

Outputs Python source you can paste directly.
"""
import sys
from pathlib import Path
import io

SVG_PATH = Path(__file__).parent.parent.parent / "graphics" / "styrene_logo.svg"

BLOCK_RAMP = " ░▒▓█"

BRAILLE_BASE = 0x2800
BRAILLE_BITS = [
    (0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (0, 3, 0x40),
    (1, 0, 0x08), (1, 1, 0x10), (1, 2, 0x20), (1, 3, 0x80),
]

def rasterize_crop(width_px, crop_top=0.0, crop_bottom=0.0):
    import cairosvg
    from PIL import Image, ImageOps
    png_bytes = cairosvg.svg2png(url=str(SVG_PATH), output_width=width_px)
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert("L")
    w, h = img.size
    y0 = int(h * crop_top)
    y1 = int(h * (1 - crop_bottom))
    return img.crop((0, y0, w, y1))

def binarise(img, threshold=200):
    return img.point(lambda p: 0 if p < threshold else 255)

def to_block(img, char_width):
    from PIL import Image
    w, h = img.size
    char_h = max(1, int(h / w * char_width * 0.5))
    img = img.resize((char_width, char_h), Image.LANCZOS)
    px = img.load()
    lines = []
    for y in range(char_h):
        row = ""
        for x in range(char_width):
            idx = int((255 - px[x, y]) / 255 * (len(BLOCK_RAMP) - 1))
            row += BLOCK_RAMP[idx]
        lines.append(row.rstrip())
    return lines

def trim(lines):
    while lines and not lines[0].strip(): lines.pop(0)
    while lines and not lines[-1].strip(): lines.pop()
    return lines

# ── wordmark in Tomorrow-style block caps ─────────────────────────────────────
# Hand-authored to match the geometric/condensed style of the Tomorrow typeface.
# Each letter is 5 rows × 4 cols (plus 1 col spacing).
# Using only: █ ▀ ▄ ▌ ▐ space

LETTERS = {
    's': [
        " ▄▄▄",
        "▐▄▄▄ ",
        " ▀▀▀▄",
        "▄   █",
        " ▀▀▀ ",
    ],
    't': [
        "▀█▀▀▀",
        " █   ",
        " █   ",
        " █   ",
        " ▀   ",
    ],
    'y': [
        "█   █",
        "▀▄ ▄▀",
        " ▀█▀ ",
        "  █  ",
        "  ▀  ",
    ],
    'r': [
        "▄▄▄▄ ",
        "█  █▀",
        "█▀▀  ",
        "█  ▄ ",
        "▀  ▀ ",
    ],
    'e': [
        "▄▄▄▄ ",
        "█▄▄▄ ",
        "█    ",
        "█▄▄▄ ",
        "▀▀▀▀ ",
    ],
    'n': [
        "▄  ▄",
        "██ █",
        "█▀██",
        "█  █",
        "▀  ▀",
    ],
}

def build_wordmark(word="styrene", char_width=72):
    """Build 5-row wordmark block centred to char_width."""
    cols = [LETTERS[c] for c in word]
    rows = [""] * 5
    for i, col in enumerate(cols):
        sep = "  " if i > 0 else ""
        for r in range(5):
            rows[r] += sep + col[r]
    # Centre pad
    w = max(len(r) for r in rows)
    pad = (char_width - w) // 2
    return ["" + " " * pad + r for r in rows]


def main():
    char_width = 72
    print("Rasterising mark…", file=sys.stderr)
    img = rasterize_crop(char_width * 4, crop_top=0.0, crop_bottom=0.42)
    img = binarise(img, 200)
    mark_lines = trim(to_block(img, char_width))

    # Pad ALL lines to exactly char_width
    def pad(l): return (l + " " * char_width)[:char_width]
    mark_lines = [pad(l) for l in mark_lines]

    wordmark = build_wordmark("styrene", char_width)
    wordmark = [pad(l) for l in wordmark]

    blank = " " * char_width
    all_lines = mark_lines + [blank, blank] + wordmark

    # Sanity
    widths = [len(l) for l in all_lines]
    print(f"Total: {len(all_lines)} lines, widths {min(widths)}–{max(widths)}", file=sys.stderr)

    # Emit Python
    print("LOGO_LINES = [")
    for ln in all_lines:
        print(f"    {repr(ln)},")
    print("]")
    print(f"\nLOGO_WIDTH = {char_width}", file=sys.stderr)


if __name__ == "__main__":
    main()
