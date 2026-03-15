# Composable widget lifecycle resource primitives — Design Spec

> This spec defines acceptance criteria for the design phase.

## Scenarios

### Scenario 1: Widgets compose reusable resource primitives instead of inheriting a heavyweight base

Given the first-pass widget lifecycle targets own different kinds of persistent resources
When the reusable lifecycle layer is defined
Then it must be expressed as composable resource helpers rather than a universal widget superclass that every live widget must inherit

### Scenario 2: The first helper set covers the current repeated ownership problems

Given `ChatWidget`, `PageBrowserWidget`, `CommsSummaryWidget`, and `ForgeLog` are the current migration targets
When the initial helper set is chosen
Then it must explicitly cover owned timers, owned subscriptions, owned worker launch, and owned auxiliary IPC lanes

### Scenario 3: Local degradation remains visible at the widget boundary

Given some widget-owned resources may fail independently of daemon liveness
When the helpers are used to manage cleanup and teardown
Then lane, timer, or subscription failures must remain local to the owning widget instead of being flattened into daemon-wide disconnect semantics

## Falsifiability

- If the helper layer requires a heavyweight shared widget base to become useful, this design is wrong.
- If the initial helper set does not clearly cover the current repeated resource-ownership patterns in ChatWidget, PageBrowserWidget, CommsSummaryWidget, and ForgeLog, this design is wrong.
- If helper-driven cleanup obscures widget ownership so thoroughly that local failures appear as daemon-wide failures, this design is wrong.

## Constraints

- Do not introduce a heavyweight universal widget base class just to share cleanup code.
- Keep widget-local degradation visible; helper usage must not turn lane or subscription failure into daemon-wide disconnect state.
- Worker helper APIs must preserve the async-callable/partial scheduling convention so mock-heavy tests do not leak unawaited coroutine warnings.
- The helper layer must compose with parent-screen ownership of the shared control bridge rather than replacing it.
