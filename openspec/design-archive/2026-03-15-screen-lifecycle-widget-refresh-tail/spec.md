# Widget-owned refresh and lane-ownership tail — Design Spec

> This spec defines acceptance criteria for the design phase.

## Scenarios

### Scenario 1: Widget follow-up focuses on persistent-resource owners

Given many widgets perform some amount of async work
When the widget lifecycle tail is prioritized
Then the first follow-up set must focus on widgets that keep subscriptions, polling timers, spawned lanes, or other teardown-sensitive resources alive across screen lifetime

### Scenario 2: Lane-aware page browsing remains part of the widget lifecycle contract

Given `PageBrowserWidget` now owns a lazily spawned execution lane
When widget lifecycle patterns are normalized
Then auxiliary-lane ownership and disconnect semantics must be treated as first-class widget lifecycle concerns alongside timers and subscriptions

### Scenario 3: Low-risk one-shot helpers stay out of the first migration pass

Given some widgets only kick off a single fetch or short confirmation timer
When the remaining widget debt is staged
Then those helpers should remain lower priority than `ChatWidget`, `CommsSummaryWidget`, `PageBrowserWidget`, and `ForgeLog`

## Falsifiability

- If the first widget follow-up pass spends most of its time on one-shot helpers instead of persistent-resource owners, this design is wrong.
- If spawned IPC lanes are treated as special cases outside the lifecycle contract, this design is wrong.
- If the widget plan ignores the parent-screen ownership boundary and lets local widget cleanup fight shared control-lane ownership, this design is wrong.

## Constraints

- Prioritize widgets that hold persistent resources across screen lifetime; do not spend the first pass on one-shot fetch helpers.
- Keep lane-specific degradation local to the owning widget instead of reporting daemon-wide failure.
- Any widget helper pattern must remain compatible with the async-callable/partial worker scheduling convention used in mock-heavy tests.
- Widget cleanup should complement, not fight, parent-screen ownership of shared control-lane resources.
