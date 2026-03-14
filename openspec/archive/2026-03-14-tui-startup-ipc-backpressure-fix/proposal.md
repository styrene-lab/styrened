# Fix TUI startup IPC backpressure

## Intent

Reduce Home first-paint IPC demand so the TUI stays truthful and responsive on large meshes and constrained hardware. Stage DeviceCache hydration in the background, keep Home liveness independent from heavy bulk queries, and represent degraded/backpressured IPC separately from a hard disconnect.

## Scope

- Stage shared cache priming after first paint.
- Simplify Home refresh to cheap summary IPC only.
- Replace Home's full conversation hydration with unread-count summary hydration.
- Preserve a richer cache-backed path for downstream screens without moving heavy fleet browsing back onto Home.

## Success Criteria

- Home can report a connected daemon even while bulk device hydration is still pending.
- Slow or failed non-critical hydration paths show a degraded/backpressured IPC state rather than a disconnect.
- Shared cache priming still happens and later updates downstream screens.
- Targeted dashboard/app/status-bar tests cover the staged-startup contract.
