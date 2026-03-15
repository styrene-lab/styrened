# Remaining StyreneScreen migration tail — Design Spec

> This spec defines acceptance criteria for the design phase.

## Scenarios

### Scenario 1: The remaining migration work is partitioned into actionable child streams

Given the umbrella `screen-lifecycle` node already contains the core lifecycle contract and several landed cleanup passes
When the current repository state is reviewed
Then the residual implementation debt must be split into narrower child nodes instead of leaving the umbrella node as a catch-all implementation bucket

### Scenario 2: The screen-side tail is identified separately from widget-owned refresh debt

Given some remaining surfaces are full screens and others are lower-level widgets
When the migration tail is classified
Then screen-surface migration work and widget-owned refresh or lane-ownership work must be tracked as distinct follow-up streams

### Scenario 3: Recent IPC lane-isolation work is accounted for in the migration split

Given long-running Pages work now uses a dedicated lazy execution lane
When the remaining lifecycle migration is partitioned
Then the split must preserve space for lane-aware ownership and teardown patterns instead of treating all lifecycle debt as generic mount/resume cleanup

## Falsifiability

- If the remaining work still reads like one undifferentiated backlog after the repo scan, this design is wrong.
- If screen-surface migration and widget-owned refresh/lane ownership remain mixed together with no clear ownership boundary, this design is wrong.
- If the recent IPC lane-isolation pattern is ignored and the migration tail assumes only a single shared-bridge lifecycle model, this design is wrong.

## Constraints

- Do not reopen `screen-lifecycle` as the generic active bucket for every remaining lifecycle concern.
- Keep the shared app bridge as the control lane; any auxiliary-lane work belongs in explicit follow-up lifecycle nodes.
- Preserve already-landed cleanup work in Dashboard, Exploration, MeshDeviceDetail, and NodeInfoPanel instead of reclassifying them as unresolved without new evidence.
- Prefer child nodes that can later be implemented or assessed independently rather than one large migration umbrella.
