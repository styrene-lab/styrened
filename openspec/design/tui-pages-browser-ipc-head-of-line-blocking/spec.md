# Pages browser IPC head-of-line blocking — Design Spec

> This spec defines acceptance criteria for the design phase.
> Add Given/When/Then scenarios that must be true before marking this node 'decided'.

## Scenarios

### Scenario 1: Slow page loads do not monopolize control-plane IPC

Given a `PageBrowserWidget` page load is in flight for a slow or timing-out node
When the TUI issues an unrelated control-plane request such as daemon status or shared-screen refresh work
Then that request must not be queued behind the page fetch on the same IPC lane

### Scenario 2: Page browsing uses an isolated long-running lane

Given the TUI maintains separate latency classes for quick control/command work, bulk data refreshes, and long-running interactive execution
When Pages browsing is isolated onto its own lane
Then page traffic must stop monopolizing the normal control lane without increasing baseline startup demand

### Scenario 3: Page failures stay local to the browser surface

Given a page fetch fails, times out, or falls back to cached content
When the operator remains elsewhere in the TUI
Then daemon liveness and overall UI responsiveness must remain truthful and distinct from page-browser degradation

## Falsifiability

- If a slow `fetch_page()` still delays unrelated status/control requests issued through the normal shared bridge, this design is disproven.
- If recovering responsiveness requires broad server-wide request-scheduling changes rather than the chosen lower-blast-radius traffic isolation, the design is incomplete or wrong.
- If the solution increases baseline startup IPC demand or reintroduces screen-owned caches to hide latency, the design is disproven.

## Constraints

- Do not reintroduce screen-owned fleet caches just to mask page latency.
- Keep daemon liveness and page-fetch backpressure distinct in operator-facing status.
- Prefer isolating long-lived page requests without increasing baseline startup demand on constrained hardware.
- Preserve separated IPC traffic classes so quick control/command work, bulk hydration, and long-running interactive flows do not collapse back onto one shared lane.
