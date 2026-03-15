# Reusable screen-content lifecycle primitive

## Intent

> Parent: [Remaining screen-surface lifecycle migration](screen-lifecycle-remaining-screen-surfaces.md)
> Spawned from: "What reusable screen-content lifecycle primitive should standardize activation, refresh kickoff, and cleanup for embedded live panes like Exchange tabs without hiding parent-vs-pane ownership?"

Define a narrow parent-owned lifecycle host for embedded live panes inside aggregate workspaces such as `ExchangeScreen`. The primitive should let the parent screen explicitly register content slots, activate only the visible pane, forward tab-switch and screen-resume transitions, and suspend or clean up inactive panes without turning embedded widgets into fake full screens or hiding who owns the shared control bridge.
