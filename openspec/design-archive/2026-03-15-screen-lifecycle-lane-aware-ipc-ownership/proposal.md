# Lane-aware IPC ownership for long-running UI work

## Intent

Define the lifecycle rules for screen/widget-owned auxiliary IPC lanes: when a surface may spawn a sibling bridge, how lane ownership composes with StyreneScreen worker cleanup, how lane-specific degradation stays local, and how long-running operator-driven work avoids monopolizing the shared control lane.

See [Lane-aware IPC ownership for long-running UI work design doc](../../../docs/screen-lifecycle-lane-aware-ipc-ownership.md) for full context.
