# Lane-aware IPC ownership for long-running UI work — Tasks

## 1. src/styrened/ipc/bridge.py (modified)

- [x] 1.1 Clarify `spawn_lane()` as a low-level sibling-lane primitive whose connect/disconnect lifecycle is owned by the caller rather than global bridge state.

## 2. src/styrened/tui/lifecycle/widget_resources.py (modified)

- [x] 2.1 Extend `WidgetResourceScope` to track dependent workers and cancel them before auxiliary-lane disconnect during teardown.

## 3. src/styrened/tui/lifecycle/screen_content.py (composition contract)

- [x] 3.1 Confirm `ScreenContentHost` remains a lifecycle translator only; pane-local auxiliary lanes continue to live in pane/widget resource helpers instead of the host.

## 4. src/styrened/tui/widgets/page_browser.py (modified)

- [x] 4.1 Track page-browser workers through the shared resource scope so execution-lane teardown cancels dependent work first while keeping lane creation lazy.

## 5. src/styrened/tui/screens/base.py (modified)

- [x] 5.1 Add screen-owned resource-scope support, auxiliary-lane adoption helpers, and lazy lane reacquisition hooks to `StyreneScreen`.

## 6. Verification

- [x] 6.1 Verify targeted lifecycle regressions with `tests/tui/screens/test_screen_base.py`, `tests/tui/widgets/test_widget_resources.py`, and `tests/tui/widgets/test_page_browser.py`.
- [x] 6.2 Run `ruff check` on the touched bridge, lifecycle, screen, widget, and test files.

## 7. Cross-cutting constraints

- [x] 7.1 Keep the shared app bridge as the control lane; auxiliary lanes remain lazy and workload-specific.
- [x] 7.2 Lane-specific degradation stays local to the owning surface instead of reading as daemon-wide disconnect.
- [x] 7.3 The same surface boundary owns worker kickoff, lane teardown, and operator feedback for long-running work.
- [x] 7.4 `IPCBridge.spawn_lane()` remains a low-level transport primitive rather than a global lane-ownership registry.
- [x] 7.5 `ScreenContentHost` remains a lifecycle translator only; pane-local lane ownership stays in pane/widget resource helpers or a screen-local resource scope.
- [x] 7.6 Suspend/unmount sequencing stops dependent work before auxiliary-lane disconnect, and resume/reactivation recreates lanes lazily rather than prewarming them.
