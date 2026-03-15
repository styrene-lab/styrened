# Provision workflow lifecycle ownership — Design Spec

> This spec defines acceptance criteria for the design phase.
> Add Given/When/Then scenarios that must be true before marking this node 'decided'.

## Scenarios

### Scenario 1: Provision bootstrap does not depend on raw async screen mount semantics

Given `ProvisionScreen` is opened
When catalog/config bootstrap work begins
Then the screen owns that bootstrap through explicit workflow worker management rather than a raw eager async `on_mount()` path
And the bootstrap can be cancelled or ignored safely if the screen goes away mid-load.

### Scenario 2: Detect and flash work use callable worker scheduling with explicit teardown

Given the operator refreshes disks or starts a flash run
When `ProvisionScreen` schedules `_detect_disks()` or forge execution
Then it passes callable worker inputs instead of eagerly created coroutine objects
And the screen has an explicit teardown boundary for in-flight detect/flash workers during abort or unmount.

### Scenario 3: Post-flash watch stops with the workflow while ForgeLog keeps timer ownership

Given flash completes and mesh watch starts
When the operator aborts, closes, or leaves the provisioning workflow
Then any screen-owned discovery/watch boundary ends with that workflow
And `ForgeLog` remains the owner of widget-local mesh-watch timer cleanup rather than the screen duplicating it.

## Falsifiability

- This design is wrong if Provision can only be stabilized by forcing it wholesale into `StyreneScreen`'s generic resume-refresh cycle.
- This design is wrong if the implementation still relies on eager coroutine `run_worker(...)` calls for detect, flash, or bootstrap paths.
- This design is wrong if post-flash watch or flash work can continue mutating detached UI state after abort, close, suspend, or unmount.

## Constraints

- Provision remains workflow-oriented rather than resume-refresh-oriented.
- ForgeLog keeps ownership of widget-local timer cleanup.
- Callable worker scheduling is required for cleanup-sensitive async work.
- The slice stays limited to Provision workflow ownership and any truly necessary narrow support changes.
