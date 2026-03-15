---
id: screen-lifecycle-widget-resource-primitives
title: Composable widget lifecycle resource primitives
status: decided
parent: screen-lifecycle-widget-refresh-tail
related: [screen-lifecycle-lane-aware-ipc-ownership, screen-lifecycle-screen-content-primitive]
open_questions: []
issue_type: task
priority: 1
---

# Composable widget lifecycle resource primitives

## Overview

> Parent: [Widget-owned refresh and lane-ownership tail](screen-lifecycle-widget-refresh-tail.md)
> Spawned from: "What composable widget lifecycle helper set should standardize timer, subscription, worker, and auxiliary-lane ownership without forcing a heavyweight shared base?"

Define the reusable helper layer that widget-owned live resources should use before further widget-by-widget cleanup proceeds. The goal is to normalize ownership semantics once, keep widget-local degradation visible, and avoid solving timers, subscriptions, worker launch, and auxiliary IPC-lane teardown in four different ad hoc ways.

## Research

### The helper should be a composable resource toolkit, not a universal widget base class

The four target widgets share a resource-ownership problem, not a common widget shape. `ChatWidget` owns daemon event subscriptions, callback registration, polling fallback, and worker launches; `PageBrowserWidget` owns async worker kickoff plus a lazily spawned auxiliary IPC lane; `ForgeLog` owns timer lifecycle; `CommsSummaryWidget` owns periodic polling and refresh fan-out. A heavyweight shared base would overfit these differences and make ownership harder to see. A better fit is a composable toolkit that lets widgets opt into the exact resource helpers they need while exposing one clear cleanup boundary.

### A small resource scope plus focused registries captures the common denominator without hiding local degradation

The common denominator is not UI behavior; it is owned runtime resources that must be registered and released. The reusable layer should therefore center on a widget-attached resource scope that can track and dispose of timers, event-subscription removers, async teardown callbacks, worker-launch callables, and spawned auxiliary IPC lanes. That keeps local degradation visible at the widget boundary — for example, a failed execution lane still belongs to `PageBrowserWidget` — while removing repeated stop/unsubscribe/disconnect bookkeeping from every widget.

## Decisions

### Decision: Define widget lifecycle helpers as a composed resource scope with focused ownership primitives

**Status:** decided
**Rationale:** The right reusable layer is a narrow resource scope attached to a widget, plus focused helpers for timers, subscription cleanup, worker launch, and auxiliary IPC lanes. This standardizes the lifecycle contract once without forcing unrelated widgets into inheritance-heavy structure or hiding which surface owns which resource.

### Decision: Keep the first helper set explicit: owned timers, owned subscriptions, owned workers, and owned auxiliary lanes

**Status:** decided
**Rationale:** These four primitives cover the current repeated failure modes and cleanup needs in `ChatWidget`, `PageBrowserWidget`, `CommsSummaryWidget`, and `ForgeLog`. Starting with this small set captures today's real overlap while leaving room to add narrower utilities later instead of growing a monolithic lifecycle framework up front.

## Open Questions

*No open questions.*

## Acceptance Criteria

### Scenarios

#### Scenario 1: Widgets compose reusable resource primitives instead of inheriting a heavyweight base

Given the first-pass widget lifecycle targets own different kinds of persistent resources  
When the reusable lifecycle layer is defined  
Then it must be expressed as composable resource helpers rather than a universal widget superclass that every live widget must inherit

#### Scenario 2: The first helper set covers the current repeated ownership problems

Given `ChatWidget`, `PageBrowserWidget`, `CommsSummaryWidget`, and `ForgeLog` are the current migration targets  
When the initial helper set is chosen  
Then it must explicitly cover owned timers, owned subscriptions, owned worker launch, and owned auxiliary IPC lanes

#### Scenario 3: Local degradation remains visible at the widget boundary

Given some widget-owned resources may fail independently of daemon liveness  
When the helpers are used to manage cleanup and teardown  
Then lane, timer, or subscription failures must remain local to the owning widget instead of being flattened into daemon-wide disconnect semantics

### Falsifiability

- This design is wrong if the helper layer requires a heavyweight shared widget base to become useful.
- This design is wrong if the initial helper set does not clearly cover the current repeated resource-ownership patterns in ChatWidget, PageBrowserWidget, CommsSummaryWidget, and ForgeLog.
- This design is wrong if helper-driven cleanup obscures widget ownership so thoroughly that local failures appear as daemon-wide failures.

### Constraints

- Do not introduce a heavyweight universal widget base class just to share cleanup code.
- Keep widget-local degradation visible; helper usage must not turn lane or subscription failure into daemon-wide disconnect state.
- Worker helper APIs must preserve the async-callable/partial scheduling convention so mock-heavy tests do not leak unawaited coroutine warnings.
- The helper layer must compose with parent-screen ownership of the shared control bridge rather than replacing it.

## Implementation Notes

### File Scope

- `src/styrened/tui/lifecycle/widget_resources.py` (new) — New composable resource-scope helper for owned timers, subscriptions, worker launching, and auxiliary IPC lane teardown.
- `src/styrened/tui/widgets/chat_widget.py` (modified) — Primary migration target for owned subscriptions, polling timers, and worker launch helpers.
- `src/styrened/tui/widgets/page_browser.py` (modified) — Primary migration target for owned worker launch and auxiliary execution-lane ownership.
- `src/styrened/tui/widgets/comms_summary.py` (modified) — Migration target for owned polling timer and refresh-worker helper usage.
- `src/styrened/tui/widgets/forge_log.py` (modified) — Migration target for owned mesh-watch timer helper usage.
- `tests/tui/widgets/` (modified) — Regression coverage for helper-backed cleanup, including timer stop, unsubscribe, and auxiliary-lane disconnect behavior.

### Constraints

- Do not introduce a heavyweight universal widget base class just to share cleanup code.
- Keep widget-local degradation visible; helper usage must not turn lane or subscription failure into daemon-wide disconnect state.
- Worker helper APIs must preserve the async-callable/partial scheduling convention so mock-heavy tests do not leak unawaited coroutine warnings.
- The helper layer must compose with parent-screen ownership of the shared control bridge rather than replacing it.
