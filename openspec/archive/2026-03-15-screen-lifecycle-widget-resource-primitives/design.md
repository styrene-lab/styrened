# Composable widget lifecycle resource primitives — Design

## Architecture Decisions

### Decision: Define widget lifecycle helpers as a composed resource scope with focused ownership primitives

**Status:** decided
**Rationale:** The right reusable layer is a narrow resource scope attached to a widget, plus focused helpers for timers, subscription cleanup, worker launch, and auxiliary IPC lanes. This standardizes the lifecycle contract once without forcing unrelated widgets into inheritance-heavy structure or hiding which surface owns which resource.

### Decision: Keep the first helper set explicit: owned timers, owned subscriptions, owned workers, and owned auxiliary lanes

**Status:** decided
**Rationale:** These four primitives cover the current repeated failure modes and cleanup needs in `ChatWidget`, `PageBrowserWidget`, `CommsSummaryWidget`, and `ForgeLog`. Starting with this small set captures today's real overlap while leaving room to add narrower utilities later instead of growing a monolithic lifecycle framework up front.

## Research Context

### The helper should be a composable resource toolkit, not a universal widget base class

The four target widgets share a resource-ownership problem, not a common widget shape. `ChatWidget` owns daemon event subscriptions, callback registration, polling fallback, and worker launches; `PageBrowserWidget` owns async worker kickoff plus a lazily spawned auxiliary IPC lane; `ForgeLog` owns timer lifecycle; `CommsSummaryWidget` owns periodic polling and refresh fan-out. A heavyweight shared base would overfit these differences and make ownership harder to see. A better fit is a composable toolkit that lets widgets opt into the exact resource helpers they need while exposing one clear cleanup boundary.

### A small resource scope plus focused registries captures the common denominator without hiding local degradation

The common denominator is not UI behavior; it is owned runtime resources that must be registered and released. The reusable layer should therefore center on a widget-attached resource scope that can track and dispose of timers, event-subscription removers, async teardown callbacks, worker-launch callables, and spawned auxiliary IPC lanes. That keeps local degradation visible at the widget boundary — for example, a failed execution lane still belongs to `PageBrowserWidget` — while removing repeated stop/unsubscribe/disconnect bookkeeping from every widget.

## File Changes

- `src/styrened/tui/lifecycle/widget_resources.py` (new) — New composable resource-scope helper for owned timers, subscriptions, worker launching, and auxiliary IPC lane teardown.
- `src/styrened/tui/widgets/chat_widget.py` (modified) — Primary migration target for owned subscriptions, polling timers, and worker launch helpers.
- `src/styrened/tui/widgets/page_browser.py` (modified) — Primary migration target for owned worker launch and auxiliary execution-lane ownership.
- `src/styrened/tui/widgets/comms_summary.py` (modified) — Migration target for owned polling timer and refresh-worker helper usage.
- `src/styrened/tui/widgets/forge_log.py` (modified) — Migration target for owned mesh-watch timer helper usage.
- `tests/tui/widgets/` (modified) — Regression coverage for helper-backed cleanup, including timer stop, unsubscribe, and auxiliary-lane disconnect behavior.

## Constraints

- Do not introduce a heavyweight universal widget base class just to share cleanup code.
- Keep widget-local degradation visible; helper usage must not turn lane or subscription failure into daemon-wide disconnect state.
- Worker helper APIs must preserve the async-callable/partial scheduling convention so mock-heavy tests do not leak unawaited coroutine warnings.
- The helper layer must compose with parent-screen ownership of the shared control bridge rather than replacing it.
