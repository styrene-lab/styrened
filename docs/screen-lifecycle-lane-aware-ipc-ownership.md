---
id: screen-lifecycle-lane-aware-ipc-ownership
title: Lane-aware IPC ownership for long-running UI work
status: implemented
parent: screen-lifecycle
related: [tui-pages-browser-ipc-head-of-line-blocking, screen-lifecycle-widget-resource-primitives, screen-lifecycle-aggregate-refresh-surfaces]
tags: [tui, lifecycle, ipc, workers, pages]
open_questions: []
branches: ["feature/screen-lifecycle-lane-aware-ipc-ownership"]
openspec_change: screen-lifecycle-lane-aware-ipc-ownership
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

### Ownership belongs in lifecycle helpers, not in IPCBridge itself

Code inspection shows `IPCBridge.spawn_lane()` is intentionally just a transport-level clone primitive: it copies socket settings and traffic-class metadata, but it does not track who owns the new lane, when worker activity begins, or how teardown should be sequenced. The actual ownership semantics already live above it in lifecycle helpers such as `WidgetResourceScope`, which suggests the standard pattern should stay at the screen/widget lifecycle boundary rather than turning `IPCBridge` into a global lane registry.

## Decisions

### Decision: Auxiliary IPC lanes should be owned by the same surface that starts the dependent long-running work

**Status:** decided
**Rationale:** Page-browser isolation and the new lifecycle helpers show that lane ownership only stays understandable when worker kickoff, degradation reporting, and disconnect cleanup live at one surface boundary. The shared app bridge remains the ambient control lane, while spawned execution/bulk lanes stay local to the widget, pane, or screen that actually uses them.

### Decision: Expose auxiliary-lane ownership through owner-local lifecycle scopes rather than IPCBridge-global state

**Status:** decided
**Rationale:** `WidgetResourceScope` already demonstrates the right abstraction boundary: the surface that owns timers, workers, and local degraded state should also adopt and release any auxiliary lane it spawns. `IPCBridge.spawn_lane()` should remain the low-level transport primitive, while `StyreneScreen` and embedded panes/widgets expose lane ownership through lifecycle-local helpers so parent-vs-child responsibility stays explicit.

### Decision: Suspend and unmount should cancel dependent workers before disconnecting auxiliary lanes, and resume should recreate lanes lazily

**Status:** decided
**Rationale:** Long-running work often holds both a worker and an auxiliary lane. To avoid orphan work, misleading errors, or reconnect churn, the owner should first stop or cancel the work that depends on the lane, then release the lane during suspend/unmount. Re-entry should not eagerly reconnect every possible lane; it should recreate the lane only when the long-running flow is actually reactivated.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/ipc/bridge.py` (modified) — Traffic-class metadata and `spawn_lane()` define the transport-level sibling-lane primitive.
- `src/styrened/tui/lifecycle/widget_resources.py` (modified) — Current ownership helper for widget-local auxiliary lane adoption and teardown.
- `src/styrened/tui/lifecycle/screen_content.py` (modified) — Parent-to-pane lifecycle translation that any future lane-aware pane contract must compose with.
- `src/styrened/tui/widgets/page_browser.py` (modified) — Reference implementation of a lazy execution lane owned by the surface that starts long-running page work.
- `src/styrened/tui/screens/base.py` (modified) — Potential home for any future screen-level helper or ownership convention that mirrors widget-local lane/resource semantics.
- `tests/tui/screens/test_screen_base.py` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `tests/tui/widgets/test_widget_resources.py` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `tests/tui/widgets/test_page_browser.py` (modified) — Post-assess reconciliation delta — touched during follow-up fixes

### Constraints

- Keep the shared app bridge as the control lane; auxiliary lanes must remain lazy and workload-specific.
- Lane-specific degradation must stay local to the owning surface instead of reading as daemon-wide disconnect.
- The same surface boundary should own worker kickoff, lane teardown, and operator feedback for long-running work.
- Keep `IPCBridge.spawn_lane()` as a low-level transport primitive; do not turn the bridge into a global lane-ownership registry.
- `ScreenContentHost` should remain a lifecycle translator only; pane-local lane ownership stays in pane/widget resource helpers or a screen-local resource scope.
- Suspend/unmount sequencing should stop dependent work before auxiliary-lane disconnect, and resume/reactivation should recreate lanes lazily rather than prewarming them.
- Keep the shared app bridge as the control lane; auxiliary lanes remain lazy and workload-specific.
- Lane-specific degradation stays local to the owning surface rather than reading as daemon-wide disconnect.
- Suspend/unmount sequencing cancels dependent workers before auxiliary-lane disconnect, and resume/reactivation recreates lanes lazily.

## Acceptance Criteria

### Falsifiability

- This decision is wrong if: This design is wrong if lane ownership only works by teaching `IPCBridge` global parent/child lifetime semantics instead of keeping ownership at the screen/widget lifecycle boundary.
- This decision is wrong if: This design is wrong if a suspended or unmounted surface can still leave long-running worker activity running against a lane it no longer owns.
- This decision is wrong if: This design is wrong if resume/reactivation eagerly reconnects auxiliary lanes even when the operator has not re-entered the long-running workflow that needs them.
