---
id: screen-lifecycle-lane-aware-ipc-ownership
title: Lane-aware IPC ownership for long-running UI work
status: exploring
parent: screen-lifecycle
related: [tui-pages-browser-ipc-head-of-line-blocking, screen-lifecycle-widget-resource-primitives]
tags: [tui, lifecycle, ipc, workers, pages]
open_questions:
  - How should StyreneScreen and screen-owned widgets expose a standard ownership pattern for auxiliary IPC lanes and the workers that depend on them?
issue_type: task
priority: 1
---

# Lane-aware IPC ownership for long-running UI work

## Overview

Define the lifecycle rules for screen/widget-owned auxiliary IPC lanes: when a surface may spawn a sibling bridge, how lane ownership composes with StyreneScreen worker cleanup, how lane-specific degradation stays local, and how long-running operator-driven work avoids monopolizing the shared control lane.

## Research

### Pages browser execution lane is the first concrete lifecycle-owned lane pattern

The `tui-pages-browser-ipc-head-of-line-blocking` fix established the first concrete lane-aware lifecycle pattern in the TUI. `PageBrowserWidget` keeps the shared bridge as the control lane, lazily spawns an `execution` sibling bridge only for long-running page work, and disconnects that lane on teardown. This proves lane isolation can solve operator-visible head-of-line blocking without broad server-side concurrency changes or extra startup demand.

### Resource-scope helpers now define the practical ownership boundary for auxiliary lanes

The combination of `WidgetResourceScope` and `ScreenContentHost` now makes the ownership seam clearer than when this node was created. Widgets and embedded panes can keep auxiliary lanes local as long as the shared control bridge remains parent-owned, lane creation stays lazy, and the same surface that starts long-running worker activity also owns lane teardown.

## Decisions

### Decision: Auxiliary IPC lanes should be owned by the same surface that starts the dependent long-running work

**Status:** decided
**Rationale:** Page-browser isolation and the new lifecycle helpers show that lane ownership only stays understandable when worker kickoff, degradation reporting, and disconnect cleanup live at one surface boundary. The shared app bridge remains the ambient control lane, while spawned execution/bulk lanes stay local to the widget, pane, or screen that actually uses them.

## Open Questions

- How should StyreneScreen and screen-owned widgets expose a standard ownership pattern for auxiliary IPC lanes and the workers that depend on them?

## Implementation Notes

### File Scope

- `src/styrened/ipc/bridge.py` (modified) — Traffic-class metadata and `spawn_lane()` define the transport-level sibling-lane primitive.
- `src/styrened/tui/lifecycle/widget_resources.py` (modified) — Current ownership helper for widget-local auxiliary lane adoption and teardown.
- `src/styrened/tui/lifecycle/screen_content.py` (modified) — Parent-to-pane lifecycle translation that any future lane-aware pane contract must compose with.
- `src/styrened/tui/widgets/page_browser.py` (modified) — Reference implementation of a lazy execution lane owned by the surface that starts long-running page work.
- `src/styrened/tui/screens/base.py` (modified) — Potential home for any future screen-level helper or ownership convention that mirrors widget-local lane/resource semantics.

### Constraints

- Keep the shared app bridge as the control lane; auxiliary lanes must remain lazy and workload-specific.
- Lane-specific degradation must stay local to the owning surface instead of reading as daemon-wide disconnect.
- The same surface boundary should own worker kickoff, lane teardown, and operator feedback for long-running work.
