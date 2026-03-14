---
id: tui-global-cop-surface
title: TUI Global COP Surface
status: seed
parent: tui-startup-ipc-backpressure
open_questions:
  - What should the dedicated TUI Global COP surface include once Home is kept lean?
issue_type: feature
priority: 2
---

# TUI Global COP Surface

## Overview

> Parent: [TUI Startup IPC Backpressure and Demand Shaping](tui-startup-ipc-backpressure.md)
> Spawned from: "What should the dedicated TUI Global COP surface include once Home is kept lean?"

*To be explored.*

## Research

### Progressive disclosure target above Home

The Global COP surface should become the richer TUI drill-down once Home is intentionally kept lean. It can own broader fleet visibility, richer filters/sorting, multi-panel summaries, and heavier or more optional hydration that would be inappropriate for first paint on constrained systems. This supports a layered operator experience: lightweight Home COP first, richer TUI Global COP second, and potentially an even more capable web UI later on systems that can afford it.

## Open Questions

- What should the dedicated TUI Global COP surface include once Home is kept lean?

## Implementation Notes

### File Scope

- `src/styrened/tui/screens/dashboard.py` (modified) — Keep Home scoped to the lightweight summary COP and navigation affordances into richer surfaces.
- `src/styrened/tui/screens/exploration.py` (modified) — Potential reuse of existing fleet-table and filtering primitives inside a richer Global COP workspace.
- `src/styrened/tui/widgets/home_node_summary.py` (modified) — Preserve Home as a compact summary widget rather than the owner of global fleet detail.

### Constraints

- Home must remain the lowest-cost COP surface and stay usable on constrained devices.
- Global COP may be richer and heavier than Home, but should still degrade gracefully as data becomes available.
- The richer web UI, if added later, should extend the same progressive-disclosure model rather than forcing Home to absorb those concerns.
