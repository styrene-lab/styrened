---
id: tui-panel-tier-system
title: TUI Panel Tier System
status: decided
tags: [tui, design-system, theme]
open_questions: []
branches: ["feature/tui-panel-tier-system"]
openspec_change: tui-panel-tier-system
---

# TUI Panel Tier System

## Overview

Define a semantic panel hierarchy using border style + color to differentiate panel importance without backgrounds (half-char border constraint). Three usable border types: round, double, heavy. Colors from theme palette provide semantic meaning.

## Research

### Operator TUI visual scanning patterns

Operators scan dashboards in an F-pattern — top-left anchor, then sweep right, then down the left edge. They need to instantly distinguish "can I act on this?" from "is this just showing me something?" from "is something wrong?". Border weight and color must answer these questions at a glance without reading labels.

Key insight: **color encodes interactivity**, **weight encodes urgency**. These are orthogonal axes that compose naturally:

- Color axis: $primary = interactive/actionable, $border = informational/passive, $secondary = ambient/chrome
- Weight axis: round = normal, double = structural grouping, heavy = urgent/alert

This means `round $primary` (thin + bright) is the workhorse — clean, inviting, "you work here." Double is NOT primary — it's too visually heavy for the 80% case. Double says "I'm a boundary/container" which is structural, not interactive. Heavy says "pay attention NOW."

tweakcn theme compatibility: swapping $primary from teal→purple→orange changes the mood but the weight hierarchy stays readable. The system must degrade gracefully to any palette.

### tweakcn color inventory vs TUI semantic needs

**What tweakcn gives us (per theme):**

| Token | Role in web UI | Typical hue |
|---|---|---|
| `primary` + fg | CTA buttons, links | Theme's hero color |
| `secondary` + fg | Muted buttons, badges | Desaturated hero |
| `accent` + fg | Highlights, hover states | Complementary or analogous |
| `destructive` + fg | Delete/danger actions | Red or orange (ONE color) |
| `muted` + fg | Disabled states, placeholder | Grey |
| `border` | Dividers, input borders | Grey |
| `input` | Input field borders | Grey (variant of border) |
| `ring` | Focus rings | Usually = primary |
| `card` + fg | Card backgrounds | Slightly lighter bg |
| `popover` + fg | Dropdown backgrounds | Slightly lighter bg |
| `sidebar-*` | Sidebar variant of above | Tinted variants |
| `chart-1..5` | Data visualization | 5 distinct, visually separated hues |

**What our TUI needs:**

| Semantic role | Used for | Current mapping |
|---|---|---|
| Interactive | Forms, buttons, active panels | ← primary ✓ |
| Info/passive | Status readouts, read-only | ← border ✓ |
| Ambient/chrome | Logs, feeds, faint structure | ← secondary ✓ |
| Focus/ring | Keyboard focus indicator | ← ring ✓ |
| Error | Broken, failed, critical | ← destructive (shared!) |
| Warning | Caution, needs attention | ← destructive (SAME!) |
| Success/positive | Connected, completed, healthy | ← primary (WRONG — same as interactive) |

**The problem:** tweakcn has exactly ONE negative semantic color (`destructive`). The current `to_textual_theme()` maps BOTH `warning` and `error` to `destructive`, and maps `success` to `primary`. So we have 3 semantic states collapsed into 2 colors.

**The solution: mine the chart colors.** Every tweakcn theme provides 5 chart colors designed to be mutually distinct AND distinct from primary/destructive. These are free palette slots we can reassign:

- `chart-1..5` are ordered by visual prominence in the theme
- We can analyze their OKLCH hue angles to find the best candidate for warning vs success
- Or we establish a fixed mapping convention: e.g. chart with hue nearest amber → warning, chart with hue nearest green → success

**Current to_textual_theme() mapping that needs to change:**
```python
success=primary,          # WRONG: same as interactive
warning=destructive,      # WRONG: same as error  
error=destructive,        # OK but only color
```

### Monochromatic theme problem — chart colors are not diverse

The styrene theme's chart-1..5 are ALL teal/cyan (hue 180-212°) — just lightness ramps of the primary. Many tweakcn themes are monochromatic or analogous, so chart colors can't be relied on for hue diversity.

This means neither fixed-position nor hue-analysis of chart colors will reliably produce distinct warning/success colors across arbitrary themes. We need a different strategy:

**Option A: Derive from destructive by hue rotation.** Take the theme's `destructive` hue and rotate it in OKLCH space:
- error = destructive (as-is, ~60° orange/red)
- warning = destructive hue + 40° (→ ~100° yellow/amber)  
- success = destructive hue + 180° or primary hue shifted toward green (~140°)

Pro: Always produces 3 distinct semantic colors that are harmonious with the theme's destructive. Works for any palette.
Con: Derived colors might clash with primary on some themes.

**Option B: Fixed semantic colors independent of theme.** Define warning=#f59e0b (amber), error=#ef4444 (red), success=#22c55e (green) as constants that never change regardless of theme.

Pro: Universal recognition, zero ambiguity.
Con: Might clash badly with some theme palettes. Breaks the "everything from the theme" promise.

**Option C: Hybrid — derive with hue targets.** Use OKLCH to generate semantic colors that MATCH the theme's lightness/saturation profile but target specific hue angles:
- error → hue 30° (red) at destructive's L and C  
- warning → hue 80° (amber) at destructive's L and slightly reduced C
- success → hue 145° (green) at primary's L and slightly reduced C

Pro: Colors "feel like they belong" to the theme because L/C match. Hue distinction is guaranteed.
Con: More complex derivation code.

## Decisions

### Decision: Panel tier definitions: color = interactivity, weight = urgency

**Status:** exploring
**Rationale:** Two orthogonal axes compose into a coherent visual language that survives theme swaps.

### Decision: Option C — derive semantic colors via OKLCH hue targeting

**Status:** decided
**Rationale:** Keep destructive's L/C (proven visible against theme bg), rotate hue to fixed semantic targets: error=30°, warning=75°, success=145°. Colors feel native to any theme while guaranteeing distinct hues.

### Decision: Panel tier definitions: color = interactivity, weight = urgency

**Status:** decided
**Rationale:** Finalized. interactive (round $primary), info (round $border), ambient (round $secondary), container (double $border), alert (heavy $warning/$error/$primary). Buttons: recessed default (round $primary-background) → heavy on hover. Primary: round $primary → double on hover.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/widgets/highlighted_panel.py` (modified) — DEFAULT_CSS baseline to panel-info (round $border)
- `src/styrened/tui/screens/settings.py` (modified) — All settings panels → panel-interactive
- `src/styrened/tui/screens/dashboard.py` (modified) — STATUS/NODES → panel-info, ACTIVITY → panel-ambient
- `src/styrened/tui/screens/dashboard_local.py` (modified) — NODE STATUS → panel-info, LOAD → panel-ambient
- `src/styrened/tui/screens/contacts.py` (modified) — CONTACTS → panel-info, EDIT/RESOLVE → panel-interactive
- `src/styrened/tui/screens/exchange_tabs.py` (modified) — Same as contacts
- `src/styrened/tui/screens/mesh_device_detail.py` (modified) — MESH INFO → panel-info, Error → panel-alert-error
- `src/styrened/tui/screens/provision.py` (modified) — SELECT DEVICE/CONFIGURE → panel-interactive, FORGE → panel-interactive
- `src/styrened/tui/screens/confirm_flash.py` (modified) — CONFIRM FLASH → panel-alert
