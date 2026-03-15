# Lane-aware IPC ownership for long-running UI work — Design Spec

## Scenarios

### Scenario 1: Auxiliary lanes are adopted through a local lifecycle owner

Given a screen, embedded pane, or widget needs a sibling IPC lane for long-running work
When that lane is created
Then it must be adopted through a lifecycle-local resource owner at the same surface boundary that starts the dependent work, while the shared app bridge remains the ambient control lane

### Scenario 2: Suspend and unmount release work before transport

Given a surface has long-running worker activity in flight on an auxiliary lane
When the surface suspends or unmounts
Then it must cancel or stop the dependent work before disconnecting the auxiliary lane, and it must not disturb the shared control lane

### Scenario 3: Resume keeps startup lean and degradation local

Given a previously suspended surface becomes active again
When no long-running lane-bound work has been requested yet
Then the auxiliary lane must remain disconnected until demand returns, and any future lane failure must surface as local degradation on the owning surface rather than a daemon-wide disconnect

## Falsifiability

- This design is wrong if lane ownership only works by teaching `IPCBridge` global parent/child lifetime semantics instead of keeping ownership at the screen/widget lifecycle boundary.
- This design is wrong if a suspended or unmounted surface can still leave long-running worker activity running against a lane it no longer owns.
- This design is wrong if resume/reactivation eagerly reconnects auxiliary lanes even when the operator has not re-entered the long-running workflow that needs them.

## Constraints

- Keep the shared app bridge as the control lane; auxiliary lanes must remain lazy and workload-specific.
- Lane-specific degradation must stay local to the owning surface instead of reading as daemon-wide disconnect.
- The same surface boundary should own worker kickoff, lane teardown, and operator feedback for long-running work.
- Keep `IPCBridge.spawn_lane()` as a low-level transport primitive; do not turn the bridge into a global lane-ownership registry.
- `ScreenContentHost` should remain a lifecycle translator only; pane-local lane ownership stays in pane/widget resource helpers or a screen-local resource scope.
- Suspend/unmount sequencing should stop dependent work before auxiliary-lane disconnect, and resume/reactivation should recreate lanes lazily rather than prewarming them.
