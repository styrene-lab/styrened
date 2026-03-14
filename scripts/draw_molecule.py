#!/usr/bin/env python3
"""
Programmatic styrene molecule renderer.

Draws the benzene ring + vinyl group by:
  1. Computing 2D atom coordinates (flat-top hexagon, vinyl extending right)
  2. Rasterising each bond onto a character grid
  3. Selecting Unicode characters based on the slope of each bond segment

Outputs several styles for review.

Usage:
    python scripts/draw_molecule.py
"""

import math
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class Vec2:
    x: float
    y: float

    def __add__(self, o): return Vec2(self.x + o.x, self.y + o.y)
    def __sub__(self, o): return Vec2(self.x - o.x, self.y - o.y)
    def __mul__(self, s): return Vec2(self.x * s, self.y * s)
    def lerp(self, o, t): return Vec2(self.x + (o.x - self.x)*t, self.y + (o.y - self.y)*t)


@dataclass
class Bond:
    a: Vec2       # start atom position (world space)
    b: Vec2       # end atom position (world space)
    order: int = 1   # 1 = single, 2 = aromatic/double
    label: str = ""


# ---------------------------------------------------------------------------
# Character selection by slope
# ---------------------------------------------------------------------------

# Slope bands → (char, offset_char)
# offset_char used for double bonds (parallel displaced)
SLOPE_CHARS = {
    # slope abs value, angle from horizontal
    "h":  ("─", "─"),   # horizontal
    "v":  ("│", "│"),   # vertical
    "d1": ("╱", "╱"),   # ~45°, going up-right / down-left
    "d2": ("╲", "╲"),   # ~45°, going up-left / down-right
    "s1": ("⟋", "⟋"),   # shallow up-right (alt: ╱ )
    "s2": ("⟍", "⟍"),   # shallow up-left
    "st1": ("╱", "╱"),  # steep up-right
    "st2": ("╲", "╲"),  # steep up-left
}

# Thick/block style
BLOCK_CHARS = {
    "h":  "▄",
    "v":  "█",
    "d1": "▓",
    "d2": "▓",
}


def slope_char(dx: float, dy: float, style: str = "thin") -> str:
    """Return the best Unicode char for a line segment of slope dy/dx."""
    eps = 1e-9
    if abs(dx) < eps:
        return "│"
    slope = dy / dx
    angle = math.degrees(math.atan2(abs(dy), abs(dx)))

    # Terminal cells are 2:1 (height:width) so a "true 45°" in screen space
    # is actually slope=2 in character coords (2 rows per col).
    # A hexagon edge at 60° from horizontal → slope = tan(60°)*2 ≈ 3.46 (steep)
    # A hexagon edge at 30° → slope = tan(30°)*2 ≈ 1.15

    if angle < 20:      return "─"
    if angle > 70:      return "│"
    if slope > 0:       return "╲"   # going down as x increases
    else:               return "╱"


# ---------------------------------------------------------------------------
# Grid renderer
# ---------------------------------------------------------------------------

class Grid:
    def __init__(self, cols: int, rows: int, bg: str = " "):
        self.cols = cols
        self.rows = rows
        self.cells: list[list[str]] = [[bg] * cols for _ in range(rows)]

    def put(self, col: int, row: int, ch: str):
        if 0 <= row < self.rows and 0 <= col < self.cols:
            self.cells[row][col] = ch

    def get(self, col: int, row: int) -> str:
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self.cells[row][col]
        return " "

    def draw_line(self, x0: float, y0: float, x1: float, y1: float,
                  ch: str | None = None, style: str = "thin"):
        """Bresenham-ish: walk t from 0→1, place chars at each grid cell hit."""
        dx = x1 - x0
        dy = y1 - y0
        dist = max(abs(dx), abs(dy))
        if dist < 0.01:
            return
        steps = int(dist * 2) + 1
        auto_ch = slope_char(dx, dy, style)
        c = ch or auto_ch
        seen: set[tuple[int, int]] = set()
        for i in range(steps + 1):
            t = i / steps
            cx = int(round(x0 + dx * t))
            cy = int(round(y0 + dy * t))
            if (cx, cy) not in seen:
                seen.add((cx, cy))
                self.put(cx, cy, c)

    def draw_line_double(self, x0: float, y0: float, x1: float, y1: float,
                         style: str = "thin", offset: float = 1.2):
        """Draw a double bond as two parallel lines, offset perpendicular."""
        dx = x1 - x0
        dy = y1 - y0
        length = math.hypot(dx, dy)
        if length < 0.01:
            return
        # Perpendicular unit vector (in cell space, accounting for 2:1 ratio)
        nx = -dy / length
        ny =  dx / length
        # Draw two offset lines
        scale = offset * 0.5
        self.draw_line(x0 + nx*scale, y0 + ny*scale,
                       x1 + nx*scale, y1 + ny*scale, style=style)
        self.draw_line(x0 - nx*scale, y0 - ny*scale,
                       x1 - nx*scale, y1 - ny*scale, style=style)

    def rows_as_strings(self) -> list[str]:
        return ["".join(row) for row in self.cells]

    def trimmed(self) -> list[str]:
        lines = self.rows_as_strings()
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return lines


# ---------------------------------------------------------------------------
# Styrene molecule geometry
# ---------------------------------------------------------------------------

def hex_vertices(cx: float, cy: float, rx: float, ry: float,
                 flat_top: bool = True) -> list[Vec2]:
    """6 hexagon vertices. rx=x-radius (cols), ry=y-radius (rows)."""
    offset = 0 if flat_top else math.pi / 6
    return [
        Vec2(cx + rx * math.cos(math.pi/3 * i + offset),
             cy + ry * math.sin(math.pi/3 * i + offset))
        for i in range(6)
    ]


def styrene_bonds(cx: float, cy: float, rx: float, ry: float,
                  vinyl_len: float = 6.0, flat_top: bool = True) -> list[Bond]:
    """Return all bonds for styrene: ring + vinyl, attachment at right vertex."""
    verts = hex_vertices(cx, cy, rx, ry, flat_top)

    bonds = []
    for i in range(6):
        j = (i + 1) % 6
        order = 2 if i % 2 == 0 else 1   # alternating Kekulé
        bonds.append(Bond(verts[i], verts[j], order))

    # Vinyl group: attach to vertex 0 (rightmost for flat-top)
    attach = verts[0]
    # vinyl C1: extend right, then angle up
    c1 = Vec2(attach.x + vinyl_len, attach.y - ry * 0.2)
    c2 = Vec2(c1.x + vinyl_len * 0.7, c1.y - ry * 0.9)

    bonds.append(Bond(attach, c1, 1, "C-C"))
    bonds.append(Bond(c1, c2, 2, "C=C"))  # double bond

    return bonds, verts


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_thin(label: str, cols=72, rows=30, flat_top=True,
                rx=12, ry=7, aromatic=True) -> list[str]:
    """Thin line rendering using ╱ ╲ │ ─ characters."""
    g = Grid(cols, rows)
    cx, cy = cols // 2 - 8, rows // 2
    bonds, verts = styrene_bonds(cx, cy, rx, ry, flat_top=flat_top)

    for b in bonds:
        if b.order == 2:
            g.draw_line_double(b.a.x, b.a.y, b.b.x, b.b.y, offset=0.7)
        else:
            g.draw_line(b.a.x, b.a.y, b.b.x, b.b.y)

    if aromatic:
        # Draw aromatic circle (○) at center
        g.put(int(round(cx)), int(round(cy)), "◯")

    return [label] + ["  " + l for l in g.trimmed()]


def render_dots(label: str, cols=72, rows=30, flat_top=True,
                rx=13, ry=8) -> list[str]:
    """Thin lines with · at each carbon atom."""
    g = Grid(cols, rows)
    cx, cy = cols // 2 - 8, rows // 2
    bonds, verts = styrene_bonds(cx, cy, rx, ry, vinyl_len=7, flat_top=flat_top)

    # Draw bonds first
    for b in bonds:
        if b.order == 2:
            g.draw_line_double(b.a.x, b.a.y, b.b.x, b.b.y, offset=0.6)
        else:
            g.draw_line(b.a.x, b.a.y, b.b.x, b.b.y)

    # Place aromatic circle
    g.put(int(round(cx)), int(round(cy)), "◯")

    # Place atom dots on top (so they overwrite bond chars at vertices)
    attach = verts[0]
    c1 = Vec2(attach.x + 7, attach.y - ry * 0.2)
    c2 = Vec2(c1.x + 4.9, c1.y - ry * 0.9)
    for v in verts + [c1, c2]:
        g.put(int(round(v.x)), int(round(v.y)), "·")

    return [label] + ["  " + l for l in g.trimmed()]


def render_bold(label: str, cols=72, rows=32, flat_top=True,
                rx=13, ry=8) -> list[str]:
    """Block-shade hexagon outline using ░▒▓█."""
    g = Grid(cols, rows)
    cx, cy = cols // 2 - 8, rows // 2
    bonds, verts = styrene_bonds(cx, cy, rx, ry, flat_top=flat_top)

    # Draw outer ring only (skip vinyl for the thick hexagon shape)
    ring_bonds = bonds[:6]

    def shade_char(dist_from_center: float) -> str:
        if dist_from_center < 0.3: return "█"
        if dist_from_center < 0.6: return "▓"
        if dist_from_center < 0.9: return "▒"
        return "░"

    for b in ring_bonds:
        # Draw 3 parallel lines per edge for thickness
        for off in [-0.4, 0.0, 0.4]:
            dx = b.b.x - b.a.x
            dy = b.b.y - b.a.y
            ln = math.hypot(dx, dy) or 1
            nx, ny = -dy / ln, dx / ln
            ch = shade_char(abs(off))
            g.draw_line(b.a.x + nx*off, b.a.y + ny*off,
                        b.b.x + nx*off, b.b.y + ny*off, ch=ch)

    # Aromatic circle
    g.put(int(round(cx)), int(round(cy)), "◯")

    # Vinyl (thin)
    for b in bonds[6:]:
        if b.order == 2:
            g.draw_line_double(b.a.x, b.a.y, b.b.x, b.b.y, offset=0.5)
        else:
            g.draw_line(b.a.x, b.a.y, b.b.x, b.b.y)

    return [label] + ["  " + l for l in g.trimmed()]


def render_kekulé(label: str, cols=76, rows=30, flat_top=True,
                  rx=14, ry=9) -> list[str]:
    """Full Kekulé structure: alternating single/double bonds, large."""
    g = Grid(cols, rows)
    cx, cy = cols // 2 - 10, rows // 2
    bonds, verts = styrene_bonds(cx, cy, rx, ry, vinyl_len=8, flat_top=flat_top)

    for b in bonds:
        if b.order == 2:
            g.draw_line_double(b.a.x, b.a.y, b.b.x, b.b.y, offset=0.8)
        else:
            g.draw_line(b.a.x, b.a.y, b.b.x, b.b.y)

    return [label] + ["  " + l for l in g.trimmed()]


def render_pointy(label: str, cols=72, rows=28) -> list[str]:
    """Pointy-top hexagon (rotated 30°), vinyl extending upper-right."""
    g = Grid(cols, rows)
    cx, cy = cols // 2 - 8, rows // 2
    rx, ry = 12, 7
    bonds, verts = styrene_bonds(cx, cy, rx, ry, vinyl_len=7, flat_top=False)

    for b in bonds:
        if b.order == 2:
            g.draw_line_double(b.a.x, b.a.y, b.b.x, b.b.y, offset=0.7)
        else:
            g.draw_line(b.a.x, b.a.y, b.b.x, b.b.y)

    g.put(int(round(cx)), int(round(cy)), "◯")

    return [label] + ["  " + l for l in g.trimmed()]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SEP = "─" * 72

def main():
    versions = [
        render_thin("VERSION 1 — flat-top, thin Unicode lines, aromatic ◯, double bonds"),
        render_dots("VERSION 2 — flat-top, dots at each carbon (·), aromatic ◯"),
        render_bold("VERSION 3 — flat-top, thick block-shade ring outline, thin vinyl"),
        render_kekulé("VERSION 4 — flat-top, full Kekulé alternating double bonds, large"),
        render_pointy("VERSION 5 — pointy-top, aromatic ◯, double bonds"),
    ]
    for v in versions:
        print(SEP)
        for line in v:
            print(line)
        print()


if __name__ == "__main__":
    main()
