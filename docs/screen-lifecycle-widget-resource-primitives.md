---
id: screen-lifecycle-widget-resource-primitives
title: Composable widget lifecycle resource primitives
status: implemented
parent: screen-lifecycle-widget-refresh-tail
related: [screen-lifecycle-lane-aware-ipc-ownership, screen-lifecycle-screen-content-primitive, screen-lifecycle-aggregate-refresh-surfaces, screen-lifecycle-provision-workflow-ownership]
open_questions: []
branches: ["feature/screen-lifecycle-widget-resource-primitives"]
openspec_change: screen-lifecycle-widget-resource-primitives
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

### Implementation landed as a composed widget resource scope with direct widget migrations

Implemented `WidgetResourceScope` under `src/styrened/tui/lifecycle/` and migrated `ChatWidget`, `PageBrowserWidget`, `CommsSummaryWidget`, and `ForgeLog` to use it for owned timers, subscription cleanup, auxiliary lane teardown, and callable-based worker scheduling. `PageBrowserWidget` keeps the shared control bridge as the parent-owned lane while the helper only tears down the lazy execution lane; `ChatWidget` now registers message-subscription teardown through the scope while preserving local degradation and existing UI behavior.

## Decisions

### Decision: Define widget lifecycle helpers as a composed resource scope with focused ownership primitives

**Status:** decided
**Rationale:** The right reusable layer is a narrow resource scope attached to a widget, plus focused helpers for timers, subscription cleanup, worker launch, and auxiliary IPC lanes. This standardizes the lifecycle contract once without forcing unrelated widgets into inheritance-heavy structure or hiding which surface owns which resource.

### Decision: Keep the first helper set explicit: owned timers, owned subscriptions, owned workers, and owned auxiliary lanes

**Status:** decided
**Rationale:** These four primitives cover the current repeated failure modes and cleanup needs in `ChatWidget`, `PageBrowserWidget`, `CommsSummaryWidget`, and `ForgeLog`. Starting with this small set captures today's real overlap while leaving room to add narrower utilities later instead of growing a monolithic lifecycle framework up front.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/tui/lifecycle/widget_resources.py` (new) — New composable resource-scope helper for owned timers, subscriptions, worker launching, and auxiliary IPC lane teardown.
- `src/styrened/tui/widgets/chat_widget.py` (modified) — Primary migration target for owned subscriptions, polling timers, and worker launch helpers.
- `src/styrened/tui/widgets/page_browser.py` (modified) — Primary migration target for owned worker launch and auxiliary execution-lane ownership.
- `src/styrened/tui/widgets/comms_summary.py` (modified) — Migration target for owned polling timer and refresh-worker helper usage.
- `src/styrened/tui/widgets/forge_log.py` (modified) — Migration target for owned mesh-watch timer helper usage.
- `tests/tui/widgets/` (modified) — Regression coverage for helper-backed cleanup, including timer stop, unsubscribe, and auxiliary-lane disconnect behavior.
- `src/styrened/tui/lifecycle/__init__.py` (new) — Exports the composable widget resource scope package entrypoint.
- `tests/tui/widgets/test_widget_resources.py` (new) — Direct regression coverage for timer cleanup, subscription teardown, auxiliary lane disconnect, and callable worker scheduling.
- `tests/tui/widgets/test_comms_summary.py` (new) — Regression coverage for CommsSummaryWidget poll-timer teardown and callable worker scheduling.
- `tests/tui/widgets/test_page_browser.py` (modified) — Post-assess reconciliation delta — touched during follow-up fixes
- `tests/tui/widgets/test_forge_log.py` (modified) — Post-assess reconciliation delta — touched during follow-up fixes

### Constraints

- Do not introduce a heavyweight universal widget base class just to share cleanup code.
- Keep widget-local degradation visible; helper usage must not turn lane or subscription failure into daemon-wide disconnect state.
- Worker helper APIs must preserve the async-callable/partial scheduling convention so mock-heavy tests do not leak unawaited coroutine warnings.
- The helper layer must compose with parent-screen ownership of the shared control bridge rather than replacing it.
- Async teardown during widget unmount must not rely solely on Textual worker execution; `WidgetResourceScope.release()` falls back to the running asyncio loop so unsubscribe/disconnect cleanup still runs during unmount.
- Widgets continue to own their degraded states locally; the shared control bridge remains screen/app-owned and only widget-spawned auxiliary lanes are eligible for helper-managed disconnect.

## Acceptance Criteria

### Falsifiability

- This decision is wrong if: This design is wrong if the helper layer requires a heavyweight shared widget base to become useful.
- This decision is wrong if: This design is wrong if the initial helper set does not clearly cover the current repeated resource-ownership patterns in ChatWidget, PageBrowserWidget, CommsSummaryWidget, and ForgeLog.
- This decision is wrong if: This design is wrong if helper-driven cleanup obscures widget ownership so thoroughly that local failures appear as daemon-wide failures.
