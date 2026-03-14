#!/usr/bin/env python3
"""
Convert styrene_logo.svg → clean ASCII/braille art for the splash screen.

Usage:
    python scripts/logo_to_ascii.py [--width N] [--mode ascii|block|braille]
                                    [--threshold T] [--crop-bottom F]
                                    [--save FILE] [--no-color]

The script rasterizes the SVG at high resolution (4× the target), applies a
sharp binary threshold, then maps pixels → characters with correct terminal
aspect-ratio compensation (chars are ~2× taller than wide).
"""

import argparse
import sys
from pathlib import Path

SVG_PATH = Path(__file__).parent.parent.parent / "graphics" / "styrene_logo.svg"

TEAL  = "\033[38;2;90;240;206m"
DIM   = "\033[38;2;30;110;90m"
RESET = "\033[0m"
BG    = "\033[48;2;10;15;13m"

# ── braille encoding ──────────────────────────────────────────────────────────
BRAILLE_BASE = 0x2800
BRAILLE_BITS = [
    (0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (0, 3, 0x40),
    (1, 0, 0x08), (1, 1, 0x10), (1, 2, 0x20), (1, 3, 0x80),
]

def braille_char(block, threshold=128):
    code = BRAILLE_BASE
    for dx, dy, bit in BRAILLE_BITS:
        if block[dy][dx] < threshold:
            code |= bit
    return chr(code)


# ── rasterize ─────────────────────────────────────────────────────────────────

def rasterize(width_px: int, crop_bottom: float = 0.28) -> "Image":
    """Rasterize SVG to a high-contrast greyscale PIL Image."""
    import cairosvg
    from PIL import Image, ImageOps
    import io

    png_bytes = cairosvg.svg2png(
        url=str(SVG_PATH),
        output_width=width_px,
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

    # White background composite (SVG may have transparent bg)
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert("L")

    # Crop bottom empty space (the SVG has a lot of whitespace below wordmark)
    if crop_bottom > 0:
        w, h = img.size
        img = img.crop((0, 0, w, int(h * (1 - crop_bottom))))

    return img


def binarise(img, threshold: int = 180):
    """Sharp binary threshold: dark pixels = mark, light = background."""
    from PIL import Image
    return img.point(lambda p: 0 if p < threshold else 255)


# ── converters ────────────────────────────────────────────────────────────────

BLOCK_RAMP = " ░▒▓█"   # light → dark

def to_block(img, char_width: int) -> list[str]:
    from PIL import Image
    w, h = img.size
    char_h = max(1, int(h / w * char_width * 0.5))
    img = img.resize((char_width, char_h), Image.LANCZOS)
    px = img.load()
    lines = []
    for y in range(char_h):
        row = ""
        for x in range(char_width):
            # Invert: 0=black=mark → dense char; 255=white=bg → space
            idx = int((255 - px[x, y]) / 255 * (len(BLOCK_RAMP) - 1))
            row += BLOCK_RAMP[idx]
        lines.append(row)
    return lines


ASCII_RAMP = " .:-=+*#%@"

def to_ascii(img, char_width: int) -> list[str]:
    from PIL import Image
    w, h = img.size
    char_h = max(1, int(h / w * char_width * 0.5))
    img = img.resize((char_width, char_h), Image.LANCZOS)
    px = img.load()
    lines = []
    for y in range(char_h):
        row = ""
        for x in range(char_width):
            idx = int((255 - px[x, y]) / 255 * (len(ASCII_RAMP) - 1))
            row += ASCII_RAMP[idx]
        lines.append(row)
    return lines


def to_braille(img, char_width: int) -> list[str]:
    from PIL import Image
    w, h = img.size
    px_w = char_width * 2
    px_h = int(h / w * px_w * 0.5)
    px_h = (px_h // 4) * 4 or 4
    img = img.resize((px_w, px_h), Image.LANCZOS)
    px = img.load()
    lines = []
    for by in range(0, px_h, 4):
        row = ""
        for bx in range(0, px_w, 2):
            block = [[px[bx + dx, by + dy] for dx in range(2)] for dy in range(4)]
            row += braille_char(block)
        lines.append(row)
    return lines


# ── colorizer ─────────────────────────────────────────────────────────────────

def colorize(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        colored = BG
        for ch in line:
            if ch == " ":
                colored += " "
            elif ch in "░⠀":
                colored += DIM + ch + TEAL
            else:
                colored += TEAL + ch
        out.append(colored + RESET)
    return out


# ── trim helpers ──────────────────────────────────────────────────────────────

def trim_lines(lines: list[str]) -> list[str]:
    """Remove leading/trailing blank lines (all-space rows)."""
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--width",        type=int,   default=64)
    p.add_argument("--mode",         choices=["ascii", "block", "braille"], default="braille")
    p.add_argument("--threshold",    type=int,   default=180,
                   help="Pixel threshold for binarisation (0-255, default 180)")
    p.add_argument("--crop-bottom",  type=float, default=0.28,
                   help="Fraction of height to crop from bottom (default 0.28)")
    p.add_argument("--no-color",     action="store_true")
    p.add_argument("--save",         metavar="FILE")
    args = p.parse_args()

    # Rasterize at 4× for clean anti-aliasing
    raster_w = args.width * (2 if args.mode == "braille" else 1) * 4
    print(f"Rasterising SVG at {raster_w}px…", file=sys.stderr)
    img = rasterize(raster_w, crop_bottom=args.crop_bottom)
    img = binarise(img, args.threshold)
    print(f"Image size after crop+threshold: {img.size}", file=sys.stderr)

    if args.mode == "ascii":
        lines = to_ascii(img, args.width)
    elif args.mode == "block":
        lines = to_block(img, args.width)
    else:
        lines = to_braille(img, args.width)

    lines = trim_lines(lines)
    print(f"{len(lines)} lines × {args.width} chars", file=sys.stderr)

    if args.save:
        Path(args.save).write_text("\n".join(lines) + "\n")
        print(f"Saved to {args.save}", file=sys.stderr)

    if args.no_color:
        print("\n".join(lines))
    else:
        for ln in colorize(lines):
            print(ln)


if __name__ == "__main__":
    main()
