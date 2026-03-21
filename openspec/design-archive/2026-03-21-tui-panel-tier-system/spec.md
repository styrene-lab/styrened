# TUI Panel Tier System — Design Spec (extracted)

> Auto-extracted from docs/tui-panel-tier-system.md at decide-time.

## Decisions

### Panel tier definitions: color = interactivity, weight = urgency (exploring)

Two orthogonal axes compose into a coherent visual language that survives theme swaps.

### Option C — derive semantic colors via OKLCH hue targeting (decided)

Keep destructive's L/C (proven visible against theme bg), rotate hue to fixed semantic targets: error=30°, warning=75°, success=145°. Colors feel native to any theme while guaranteeing distinct hues.

### Panel tier definitions: color = interactivity, weight = urgency (decided)

Finalized. interactive (round $primary), info (round $border), ambient (round $secondary), container (double $border), alert (heavy $warning/$error/$primary). Buttons: recessed default (round $primary-background) → heavy on hover. Primary: round $primary → double on hover.

## Research Summary

### Operator TUI visual scanning patterns

Operators scan dashboards in an F-pattern — top-left anchor, then sweep right, then down the left edge. They need to instantly distinguish "can I act on this?" from "is this just showing me something?" from "is something wrong?". Border weight and color must answer these questions at a glance without reading labels.

Key insight: **color encodes interactivity**, **weight encodes urgency**. These are orthogonal axes that compose naturally:

- Color axis: $primary = interactive/actionable, $border…

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
| `input` | Input field border…

### Monochromatic theme problem — chart colors are not diverse

The styrene theme's chart-1..5 are ALL teal/cyan (hue 180-212°) — just lightness ramps of the primary. Many tweakcn themes are monochromatic or analogous, so chart colors can't be relied on for hue diversity.

This means neither fixed-position nor hue-analysis of chart colors will reliably produce distinct warning/success colors across arbitrary themes. We need a different strategy:

**Option A: Derive from destructive by hue rotation.** Take the theme's `destructive` hue and rotate it in OKLCH …
