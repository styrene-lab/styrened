# Lane-aware IPC ownership for long-running UI work — Tasks

## 1. src/styrened/ipc/bridge.py (modified)

- [ ] 1.1 Traffic-class metadata and `spawn_lane()` define the transport-level sibling-lane primitive.

## 2. src/styrened/tui/lifecycle/widget_resources.py (modified)

- [ ] 2.1 Current ownership helper for widget-local auxiliary lane adoption and teardown.

## 3. src/styrened/tui/lifecycle/screen_content.py (modified)

- [ ] 3.1 Parent-to-pane lifecycle translation that any future lane-aware pane contract must compose with.

## 4. src/styrened/tui/widgets/page_browser.py (modified)

- [ ] 4.1 Reference implementation of a lazy execution lane owned by the surface that starts long-running page work.

## 5. src/styrened/tui/screens/base.py (modified)

- [ ] 5.1 Potential home for any future screen-level helper or ownership convention that mirrors widget-local lane/resource semantics.

## 6. Cross-cutting constraints

- [ ] 6.1 Keep the shared app bridge as the control lane; auxiliary lanes must remain lazy and workload-specific.
- [ ] 6.2 Lane-specific degradation must stay local to the owning surface instead of reading as daemon-wide disconnect.
- [ ] 6.3 The same surface boundary should own worker kickoff, lane teardown, and operator feedback for long-running work.
- [ ] 6.4 Keep `IPCBridge.spawn_lane()` as a low-level transport primitive; do not turn the bridge into a global lane-ownership registry.
- [ ] 6.5 `ScreenContentHost` should remain a lifecycle translator only; pane-local lane ownership stays in pane/widget resource helpers or a screen-local resource scope.
- [ ] 6.6 Suspend/unmount sequencing should stop dependent work before auxiliary-lane disconnect, and resume/reactivation should recreate lanes lazily rather than prewarming them.
