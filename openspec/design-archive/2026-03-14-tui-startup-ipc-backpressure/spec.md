# TUI Startup IPC Backpressure and Demand Shaping — Design Spec

> This spec defines acceptance criteria for the design phase.
> Add Given/When/Then scenarios that must be true before marking this node 'decided'.

## Scenarios

### Scenario 1 — Home first paint does not depend on full fleet hydration

Given the daemon is reachable but fleet inventory or conversation hydration is slow
When the TUI finishes splash/startup initialization
Then Home can render a truthful connected summary without waiting for full `get_devices()` or conversation queries to complete

### Scenario 2 — Liveness is decoupled from bulk hydration failures

Given the daemon control socket is healthy and summary status queries succeed
When a bulk hydration request such as full device inventory times out or lags
Then the UI reports a degraded or backpressured condition rather than a hard daemon disconnect

### Scenario 3 — Shared cache remains the authoritative detail path

Given Home first paint is optimized for cheaper startup work
When detailed fleet data becomes available later
Then the shared app-level `DeviceCache` still supplies synchronized node detail updates without reintroducing per-screen shadow caches

### Scenario 4 — The design remains valid on constrained hardware

Given a low-power or SBC-class deployment
When the startup path is applied there
Then it reduces first-paint work before adding concurrency, and any optional IPC lane isolation is justified as latency isolation rather than as a requirement for correctness

## Falsifiability

- If Home still needs full fleet hydration before it can show the daemon as connected, this design is wrong.
- If one slow bulk query can still flip the UI into the same state as a dead or missing daemon, this design is wrong.
- If the proposed fix relies on reintroducing per-screen caches or moving detailed browsing back onto Home, this design is wrong.
- If the design improves desktop/public-hub startup only by increasing concurrent daemon work with no demand reduction, it is not appropriate for constrained systems.

## Constraints

- Home remains a summary surface rather than the owner of detailed fleet browsing.
- Shared app-level cache semantics stay intact; presence versus readiness must still be handled correctly by consumers.
- Operator-visible states must distinguish connected, degraded/backpressured, and disconnected conditions.
- The preferred path is to shrink and stage startup demand first; traffic-class isolation is a secondary optimization.