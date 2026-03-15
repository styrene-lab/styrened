---
id: screen-lifecycle-widget-refresh-tail
title: Widget-owned refresh and lane-ownership tail
status: exploring
parent: screen-lifecycle-styrenescreen-migration-tail
open_questions:
  - "Do we want a shared widget-level lifecycle helper for timers/subscriptions/auxiliary lanes, or explicit per-widget cleanup patterns built around StyreneScreen ownership?"
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

## Decisions

### Decision: Prioritize widget migration only where the widget owns persistent runtime resources

**Status:** decided
**Rationale:** The widget tail should focus on helpers that hold resources across screen lifetime: daemon event subscriptions, polling intervals, spawned IPC lanes, or other teardown-sensitive state. That makes ChatWidget, PageBrowserWidget, CommsSummaryWidget, and ForgeLog the meaningful lifecycle-follow-up set, while one-shot helpers like MessageBubble or largely action-driven widgets like CommandWidget can stay lower priority unless they start accumulating longer-lived background ownership.

## Open Questions

- Do we want a shared widget-level lifecycle helper for timers/subscriptions/auxiliary lanes, or explicit per-widget cleanup patterns built around StyreneScreen ownership?

## Acceptance Criteria

### Scenarios

#### Scenario 1: Widget follow-up focuses on persistent-resource owners

Given many widgets perform some amount of async work  
When the widget lifecycle tail is prioritized  
Then the first follow-up set must focus on widgets that keep subscriptions, polling timers, spawned lanes, or other teardown-sensitive resources alive across screen lifetime

#### Scenario 2: Lane-aware page browsing remains part of the widget lifecycle contract

Given `PageBrowserWidget` now owns a lazily spawned execution lane  
When widget lifecycle patterns are normalized  
Then auxiliary-lane ownership and disconnect semantics must be treated as first-class widget lifecycle concerns alongside timers and subscriptions

#### Scenario 3: Low-risk one-shot helpers stay out of the first migration pass

Given some widgets only kick off a single fetch or short confirmation timer  
When the remaining widget debt is staged  
Then those helpers should remain lower priority than `ChatWidget`, `CommsSummaryWidget`, `PageBrowserWidget`, and `ForgeLog`

### Falsifiability

- This design is wrong if the first widget follow-up pass spends most of its time on one-shot helpers instead of persistent-resource owners.
- This design is wrong if spawned IPC lanes are treated as special cases outside the lifecycle contract.
- This design is wrong if the widget plan ignores the parent-screen ownership boundary and lets local widget cleanup fight shared control-lane ownership.

### Constraints

- Prioritize widgets that hold persistent resources across screen lifetime; do not spend the first pass on one-shot fetch helpers.
- Keep lane-specific degradation local to the owning widget instead of reporting daemon-wide failure.
- Any widget helper pattern must remain compatible with the async-callable/partial worker scheduling convention used in mock-heavy tests.
- Widget cleanup should complement, not fight, parent-screen ownership of shared control-lane resources.

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
