# Fix TUI startup IPC backpressure

## Intent

Reduce Home first-paint IPC demand so the TUI stays truthful and responsive on large meshes and constrained hardware. Stage DeviceCache hydration in the background, keep Home liveness independent from heavy bulk queries, and represent degraded/backpressured IPC separately from a hard disconnect.

## Scope

<!-- Define what is in scope and out of scope -->

## Success Criteria

<!-- How will we know this change is complete and correct? -->
