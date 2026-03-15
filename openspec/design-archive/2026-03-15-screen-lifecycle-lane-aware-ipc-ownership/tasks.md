# Lane-aware IPC ownership for long-running UI work — Design Tasks

## 1. Design exploration

- [x] 1.1 Capture the current concrete lane pattern from `PageBrowserWidget` and `IPCBridge.spawn_lane()`.
- [x] 1.2 Decide the ownership boundary: lifecycle-local resource scopes own auxiliary lanes, not `IPCBridge` global state.
- [x] 1.3 Decide lifecycle sequencing: suspend/unmount stop dependent work before auxiliary-lane disconnect, and resume recreates lanes lazily.
- [x] 1.4 Record implementation scope and constraints for `StyreneScreen`, `WidgetResourceScope`, and pane composition helpers.
