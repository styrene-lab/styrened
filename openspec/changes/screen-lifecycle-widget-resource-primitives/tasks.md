# Composable widget lifecycle resource primitives — Tasks

## 1. Core widget resource scope

- [ ] 1.1 Add `src/styrened/tui/lifecycle/widget_resources.py` with a widget-attached resource scope that supports owned timers, owned subscriptions/cleanup callbacks, owned async teardown callbacks, worker-launch helpers, and owned auxiliary IPC lanes.
- [ ] 1.2 Keep the API composition-first; do not introduce a heavyweight universal widget base class.
- [ ] 1.3 Preserve the async-callable/`partial(...)` worker-launch convention so mocked `run_worker` paths remain warning-free.
- [ ] 1.4 Ensure cleanup ordering and disposal helpers keep resource failures local to the owning widget instead of escalating to daemon-wide disconnect semantics.

## 2. Timer and auxiliary-lane widget migrations

- [ ] 2.1 Migrate `src/styrened/tui/widgets/page_browser.py` to the shared resource scope for worker launching and execution-lane ownership/teardown.
- [ ] 2.2 Migrate `src/styrened/tui/widgets/forge_log.py` to the shared resource scope for mesh-watch timer ownership and cleanup.
- [ ] 2.3 Keep parent-screen ownership of the shared control bridge intact while the helper manages only widget-owned resources.

## 3. Subscription and polling widget migrations

- [ ] 3.1 Migrate `src/styrened/tui/widgets/chat_widget.py` to the shared resource scope for polling timer ownership, event-subscription cleanup, and related worker launch helpers.
- [ ] 3.2 Migrate `src/styrened/tui/widgets/comms_summary.py` to the shared resource scope for periodic polling and refresh-worker ownership.
- [ ] 3.3 Preserve widget-local degradation and existing runtime behavior while replacing ad hoc cleanup code.

## 4. Regression coverage

- [ ] 4.1 Add or update tests under `tests/tui/widgets/` for helper-backed timer stop, unsubscribe/cleanup, and auxiliary-lane disconnect behavior.
- [ ] 4.2 Cover the async-callable worker-launch convention so helper usage does not reintroduce unawaited coroutine warnings in mock-heavy tests.
- [ ] 4.3 Verify the migrated widgets still compose with parent-screen/shared-bridge ownership rather than replacing it.
