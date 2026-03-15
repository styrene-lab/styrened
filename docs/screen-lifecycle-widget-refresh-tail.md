---
id: screen-lifecycle-widget-refresh-tail
title: Widget-owned refresh and lane-ownership tail
status: implemented
parent: screen-lifecycle-styrenescreen-migration-tail
open_questions: []
issue_type: task
priority: 2
---

# Widget-owned refresh and lane-ownership tail

## Overview

> Parent: [Remaining StyreneScreen migration tail](screen-lifecycle-styrenescreen-migration-tail.md)
> Spawned from: "Which widgets still own polling, event subscriptions, media fetches, or auxiliary IPC lanes that should be normalized under the lifecycle contract?"

*To be explored.*

## Research

### The material widget tail is defined by persistent resources: subscriptions, polling timers, and auxiliary IPC lanes

`ChatWidget` is still a major lifecycle owner below the screen layer: mount triggers `_initialize()`, which marks threads read, refreshes messages, subscribes to daemon events, installs an event callback, and starts a polling fallback timer, with explicit unsubscribe and timer shutdown on unmount. `PageBrowserWidget` now owns the first lane-aware pattern by lazily spawning an execution bridge via `spawn_lane('execution')` and disconnecting it on unmount. `ForgeLog` owns a mesh-watch interval timer with explicit teardown, and `CommsSummaryWidget` still starts a periodic polling interval on mount while doing its own bridge fan-out with no explicit teardown hook. In contrast, `MessageBubble` only performs a one-shot image fetch on mount and `CommandWidget` is mostly action-driven aside from initial auto-ping and short confirmation timers, so they are lower-priority lifecycle debt than the widgets that hold persistent resources across screen lifetime.

### A shared widget helper would reduce boilerplate, but the current resource shapes are still too heterogeneous to freeze one abstraction

The persistent-resource widgets do share a theme — they each own something that must be torn down — but the owned resources are not uniform. `ChatWidget` manages event subscription callbacks plus a polling timer; `PageBrowserWidget` owns a lazily spawned auxiliary IPC lane; `ForgeLog` owns a mesh-watch timer; `CommsSummaryWidget` only needs interval polling and refresh coalescing. A shared base helper could standardize worker/timer/subscription registration, but it would also need to cover very different teardown semantics and remain compatible with mocked `run_worker` callables/partials. Right now explicit per-widget cleanup keeps ownership and local degradation obvious, while leaving room to extract tiny helper utilities later once the common denominator is better proven.

### The widget resource patterns are heterogeneous, but composable helper primitives can still standardize ownership without one giant base class

Reassessing the widget tail suggests a middle path between hand-written cleanup everywhere and a heavy shared base. `ChatWidget`, `PageBrowserWidget`, `ForgeLog`, and `CommsSummaryWidget` all need explicit ownership of persistent resources, but the reusable layer can be a small composable toolkit: e.g. registries/helpers for timers, event subscriptions, worker callables, and auxiliary IPC lanes. That approach captures the shared lifecycle contract early, keeps local degradation visible, and avoids forcing unrelated widgets into an inheritance-heavy abstraction.

### Widget helper proving ground is complete; remaining widget tail is lighter and more specialized

`WidgetResourceScope` is now implemented and the initial persistent-resource widgets have migrated. The remaining widget-side lifecycle work is no longer generic cleanup boilerplate; it is narrower follow-up around specialized surfaces, lane-aware ownership patterns, or lower-priority one-shot/action-driven widgets.

## Decisions

### Decision: Prioritize widget migration only where the widget owns persistent runtime resources

**Status:** decided
**Rationale:** The widget tail should focus on helpers that hold resources across screen lifetime: daemon event subscriptions, polling intervals, spawned IPC lanes, or other teardown-sensitive state. That makes ChatWidget, PageBrowserWidget, CommsSummaryWidget, and ForgeLog the meaningful lifecycle-follow-up set, while one-shot helpers like MessageBubble or largely action-driven widgets like CommandWidget can stay lower priority unless they start accumulating longer-lived background ownership.

### Decision: Prefer explicit per-widget cleanup patterns over a new shared widget lifecycle base for the first pass

**Status:** decided
**Rationale:** The first-pass widget targets all own persistent resources, but not the same kind of resources. A shared widget lifecycle base would risk hiding ownership, overfitting to today's small sample, and complicating test ergonomics around async callables and local degradation. Explicit per-widget cleanup, guided by shared conventions from StyreneScreen ownership, keeps the contract visible and lets the team extract smaller helper utilities later only after repeated patterns actually stabilize.

### Decision: Start with composable widget lifecycle helpers before broad per-widget cleanup

**Status:** decided
**Rationale:** The right abstraction is not a single heavyweight widget base, but it is still helper-first. Introducing composable primitives for timer ownership, subscription registration, worker scheduling, and auxiliary-lane teardown lets the project normalize resource ownership once and then migrate `ChatWidget`, `PageBrowserWidget`, `CommsSummaryWidget`, and `ForgeLog` onto that shared contract.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/widgets/chat_widget.py` (modified) — Owns message subscription, event callback registration, polling fallback timer, and teardown.
- `src/styrened/tui/widgets/page_browser.py` (modified) — Reference implementation for lazy execution-lane ownership and explicit bridge disconnect.
- `src/styrened/tui/widgets/comms_summary.py` (modified) — Still owns interval polling and direct bridge fan-out without an explicit teardown contract.
- `src/styrened/tui/widgets/forge_log.py` (modified) — Owns mesh-watch interval lifecycle and explicit timer cleanup.

### Constraints

- Prioritize widgets that hold persistent resources across screen lifetime; do not spend the first pass on one-shot fetch helpers.
- Keep lane-specific degradation local to the owning widget instead of reporting daemon-wide failure.
- Any widget helper pattern must remain compatible with the async-callable/partial worker scheduling convention used in mock-heavy tests.
- Widget cleanup should complement, not fight, parent-screen ownership of shared control-lane resources.

## Acceptance Criteria

### Falsifiability

- This decision is wrong if: This design is wrong if the first widget follow-up pass spends most of its time on one-shot helpers instead of persistent-resource owners.
- This decision is wrong if: This design is wrong if spawned IPC lanes are treated as special cases outside the lifecycle contract.
- This decision is wrong if: This design is wrong if the widget plan ignores the parent-screen ownership boundary and lets local widget cleanup fight shared control-lane ownership.
